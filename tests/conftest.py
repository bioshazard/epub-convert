import zipfile
from io import BytesIO

import pytest


@pytest.fixture
def make_epub():
    """Small real EPUBs, independent of the converter and any private book."""

    def build(*chapters):
        output = BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("mimetype", "application/epub+zip")
            archive.writestr(
                "META-INF/container.xml",
                """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="book.opf" media-type="application/oebps-package+xml"/></rootfiles></container>""",
            )
            items = "".join(
                f'<item id="c{i}" href="c{i}.xhtml" media-type="application/xhtml+xml"/>'
                for i in range(len(chapters))
            )
            spine = "".join(f'<itemref idref="c{i}"/>' for i in range(len(chapters)))
            archive.writestr(
                "book.opf",
                f"""<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">test</dc:identifier><dc:title>Fixture</dc:title><dc:language>en</dc:language></metadata><manifest>{items}</manifest><spine>{spine}</spine></package>""",
            )
            for i, chapter in enumerate(chapters):
                archive.writestr(
                    f"c{i}.xhtml",
                    '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Fixture</title></head><body>'
                    + chapter
                    + "</body></html>",
                )
        return output.getvalue()

    return build
