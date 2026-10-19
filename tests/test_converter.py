import json
import subprocess
import sys
import zipfile
from io import BytesIO

import pytest

from epub_convert import ConversionError, convert_epub


def test_reading_contract_and_spine_order(make_epub):
    data = make_epub(
        """<h1>First</h1><p>A wrapped
paragraph with <em>emphasis</em> and <strong>strength</strong>,
<a href="https://example.com/a_(b)">a <em>formatted</em> label</a>.</p>
<ul><li>Outer<ul><li>Inner</li></ul></li><li>Second</li></ul>
<pre><code>if ready:\n    proceed()\n</code></pre>
<p>Unicode: café — 日本語.</p>""",
        "<h1>Last</h1><p>Final paragraph.</p>",
    )
    md = convert_epub(data)
    assert md.index("# First") < md.index("# Last")
    assert "A wrapped paragraph with *emphasis* and **strength**," in md
    assert "a *formatted* label" in md and "https://example.com" not in md
    assert "\n  - Inner" in md or "\n    - Inner" in md
    assert "if ready:\n    proceed()" in md
    assert "café — 日本語" in md


def test_complex_table_keeps_every_cell_and_caption(make_epub):
    data = make_epub("""<table><caption>Decision guide</caption>
<thead><tr><th>Choice</th><th>Reason</th></tr></thead><tbody>
<tr><td rowspan="2">Keep</td><td><p>First paragraph.</p><p>Second<br/>line.</p></td></tr>
<tr><td><ul><li>Alpha</li><li>Beta</li></ul></td></tr>
<tr><td colspan="2">Spanning footer</td></tr></tbody></table>""")
    md = convert_epub(data)
    assert "[TABLE]" not in md and "<table" not in md and "<br" not in md
    for text in [
        "Decision guide",
        "Choice",
        "Reason",
        "Keep",
        "First paragraph.",
        "Second line.",
        "Alpha",
        "Beta",
        "Spanning footer",
    ]:
        assert md.count(text) == 1
    assert sum(line.startswith("|") for line in md.splitlines()) >= 4
    row = next(line for line in md.splitlines() if "Alpha" in line)
    cells = row.split("|")[1:-1]
    assert not cells[0].strip()
    assert " ".join(cells[1].split()) == "Alpha Beta"


def test_image_description_without_assets_or_urls(make_epub):
    md = convert_epub(make_epub('<p>Before<img src="missing.png" alt="A diagram"/>After</p>'))
    assert "A diagram" in md and "missing.png" not in md
    assert "![" not in md


def test_font_fragments_do_not_change_words_or_create_lists(make_epub):
    md = convert_epub(
        make_epub(
            "<h2>Adolescenc<span>e</span></h2>"
            "<p><span>1</span><span>.</span> A literal numbered reference.</p>"
        )
    )
    assert "## Adolescence" in md
    parsed = json.loads(
        subprocess.check_output(["pandoc", "--from=gfm", "--to=json"], input=md.encode())
    )
    assert [block["t"] for block in parsed["blocks"]] == ["Header", "Para"]


def test_figure_description_and_caption_both_survive_in_visual_order(make_epub):
    md = convert_epub(
        make_epub(
            '<figure><img src="missing.png" alt="Diagram description"/>'
            "<figcaption>Figure caption</figcaption></figure>"
        )
    )
    assert md.count("Diagram description") == md.count("Figure caption") == 1
    assert md.index("Diagram description") < md.index("Figure caption")


def test_invalid_archive_and_input_limits(monkeypatch):
    import epub_convert.converter as converter

    for data, code in [(b"", "empty_file"), (b"not an epub", "invalid_epub")]:
        with pytest.raises(ConversionError) as error:
            convert_epub(data)
        assert error.value.code == code
    monkeypatch.setattr(converter, "MAX_UPLOAD_BYTES", 4)
    with pytest.raises(ConversionError, match="64 MiB") as error:
        convert_epub(b"12345")
    assert error.value.code == "file_too_large"


def test_xml_entities_rejected(make_epub):
    original = zipfile.ZipFile(BytesIO(make_epub("<p>Safe</p>")))
    target = BytesIO()
    with original, zipfile.ZipFile(target, "w") as archive:
        for member in original.infolist():
            data = original.read(member)
            if member.filename == "META-INF/container.xml":
                data = b'<!DOCTYPE container [<!ENTITY x "unsafe">]>' + data
            archive.writestr(member, data)
    with pytest.raises(ConversionError) as error:
        convert_epub(target.getvalue())
    assert error.value.code == "invalid_epub"


def test_engine_timeout_is_a_domain_failure(make_epub, monkeypatch, tmp_path):
    import epub_convert.converter as converter

    executable = tmp_path / "pandoc"
    executable.write_text(
        f"#!{sys.executable}\nimport sys,time\n"
        "if '--version' in sys.argv: print('pandoc 3.12.1')\n"
        "else: time.sleep(5)\n"
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PANDOC_BIN", str(executable))
    monkeypatch.setattr(converter, "CONVERSION_TIMEOUT_SECONDS", 0.02)
    with pytest.raises(ConversionError) as error:
        convert_epub(make_epub("<p>Text</p>"))
    assert error.value.code == "conversion_timeout"
    assert not hasattr(error.value, "status")


def test_cli_file_stdin_and_library_are_identical(make_epub, tmp_path):
    data = make_epub("<h1>CLI</h1><p>Same engine.</p>")
    source = tmp_path / "book.epub"
    target = tmp_path / "book.md"
    source.write_bytes(data)
    from_file = subprocess.run(
        [sys.executable, "-m", "epub_convert.cli", "convert", str(source), "-o", str(target)],
        capture_output=True,
    )
    assert from_file.returncode == 0 and not from_file.stdout
    from_stdin = subprocess.run(
        [sys.executable, "-m", "epub_convert.cli", "convert", "-"], input=data, capture_output=True
    )
    assert from_stdin.returncode == 0
    assert from_stdin.stdout == target.read_bytes() == convert_epub(data).encode()


def test_cli_failure_has_no_traceback_or_partial_output(tmp_path):
    source = tmp_path / "bad.epub"
    target = tmp_path / "existing.md"
    source.write_bytes(b"garbage")
    target.write_text("Keep existing output")
    result = subprocess.run(
        [sys.executable, "-m", "epub_convert.cli", "convert", str(source), "-o", str(target)],
        capture_output=True,
    )
    assert result.returncode != 0 and not result.stdout
    assert b"invalid_epub" in result.stderr and b"Traceback" not in result.stderr
    assert target.read_text() == "Keep existing output"
