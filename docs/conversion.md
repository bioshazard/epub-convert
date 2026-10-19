# Conversion design

The original experiment established the useful reading format: headings, tables,
continuous paragraphs and link labels without destinations. Its scripts are an
output reference, not a runtime dependency.

## Two implementations considered

| Design | What it owns | Evidence / cost |
| --- | --- | --- |
| Pandoc → unwrapped HTML → Markdownify profile | HTML parsing, a second document model and renderer | Retains the old route; merged rows can move cells into the wrong column. Still needs formatting-specific fixes. |
| Pandoc EPUB document → reading policy → Markdown writer | One document model; parser/writer stay with Pandoc | Chosen after testing real books and structural edge cases. Deletes HTML serialization/parsing, Markdownify dependencies, worker processes, intermediate files and regex cleanup. |

The goal is a correct reading document, not the shortest chain. Initial direct
GFM conversion failed: disabling raw HTML produced `[TABLE]` placeholders for
multiline tables. That was rejected, not accepted as a formatting difference.
The policy now simplifies table cells structurally and uses Pandoc's span-aware
simple-table conversion, retaining captions and cell placement. Cell paragraph/list
boundaries must become spaces, not concatenated words.

The original newline cut compensated for wrapped HTML text. `--wrap=none` supplies
one source line per paragraph directly, leaving actual lists/code/paragraphs intact.
Removing links happens on Link nodes, so parentheses, nested formatting and images
cannot be accidentally rewritten by a Markdown link regex.

Removing presentation spans can expose adjacent text fragments. They are coalesced
before writing, so a split word stays one word and a literal number-plus-period is
escaped correctly instead of becoming a list marker. Unlabelled code gets a `text`
fence, avoiding indented-code ambiguities after lists. Figure descriptions precede
captions in visual reading order, despite Pandoc storing captions first in its AST.

## Ownership

`converter.py` validates bounded EPUB input, invokes sandboxed Pandoc over stdin,
and returns Markdown or a semantic `ConversionError`. It owns no HTTP status codes,
files, retry queues or persistent lifecycle. The bundled trusted Lua policy owns
reading-format choices. It does not execute book-supplied filters or code.

CLI owns bounded file/stdin reads, stdout/file output and diagnostics. HTTP owns
multipart/stream limits, admission, filenames and status mapping. Both call the same
operation; neither cleans up its output. Temporary multipart files close with the
request; conversion itself creates no files. The only durable state is what a
caller elects to save.

## Verification / adoption

Tests cover transport equivalence, wrapped prose, nested lists, code indentation,
Unicode, nested link labels, image descriptions, table spans/multiline cells,
malformed archives/XML, input limits, timeouts, concurrent requests and recovery.

`scripts/verify_books.py` is a reusable independent audit: parse source EPUB and
rendered Markdown, compare reading word tokens in order, and compare library/CLI/API
bytes. It normalizes Unicode compatibility forms and does not count URLs, document
attributes or non-reading raw markup as prose. It reads figures in visual order.
It is a content/structure check, not a claim of identical typography or proof for
every possible EPUB. Private evidence and outputs stay outside Git.

The four original source EPUBs are the acceptance corpus. The v0.1.0 tag/image
remains the rollback reference; this work changes serialization under a new pipeline
identifier and package version. No production consumer is switched by this branch.

## Engine reproducibility

Debian's Pandoc 3.1.11 and the tested 3.12.1 read the endnotes of one acceptance
book differently. A reader/writer round-trip alone would not catch cross-version
variation. The engine therefore requires Pandoc 3.12.1, checked once per executable
per process. Both container architectures install official 3.12.1 binaries verified
against their release SHA-256 checksums. The acceptance audit is run on macOS and
Linux, and the final Markdown hashes are compared across those environments.
Upgrades require repeating that corpus check; package-locking Python alone is
insufficient.

## Acceptance receipt

Checked with Pandoc 3.12.1 on macOS and Linux:

| Original source book | Audited word tokens | Lost / added / reordered |
| --- | ---: | --- |
| The Practice of Adaptive Leadership | 99,721 | 0 / 0 / no |
| To Sell Is Human | 65,356 | 0 / 0 / no |
| Age of Invisible Machines, second edition | 97,235 | 0 / 0 / no |
| iooh-og | 159,411 | 0 / 0 / no |

All four produce byte-identical Markdown across macOS and Linux, and identical
library/CLI/API results. Nineteen regression tests pass on both platforms; the
non-root, read-only runtime image passes an actual HTTP conversion. The private
corpus and generated books are deliberately excluded from this public repository.
