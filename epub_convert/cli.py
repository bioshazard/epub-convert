"""Command-line adapter over the same conversion engine used by HTTP."""

import argparse
import os
import sys
from importlib.metadata import version
from pathlib import Path

from .converter import MAX_UPLOAD_BYTES, ConversionError, check_dependencies, convert_epub


def main():
    parser = argparse.ArgumentParser(description="Convert EPUBs to reading-ready Markdown")
    parser.add_argument("--version", action="version", version=version("epub-convert"))
    commands = parser.add_subparsers(dest="command", required=True)
    convert = commands.add_parser("convert", help="Convert a book; '-' reads stdin")
    convert.add_argument("input")
    convert.add_argument("-o", "--output", type=Path, help="Write a file instead of stdout")
    serve = commands.add_parser("serve", help="Serve the same conversion over HTTP")
    serve.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("PORT", "3000")))
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn

        uvicorn.run("epub_convert.api:app", host=args.host, port=args.port)
        return
    try:
        check_dependencies()
        if args.input == "-":
            data = sys.stdin.buffer.read(MAX_UPLOAD_BYTES + 1)
        else:
            with Path(args.input).open("rb") as source:
                data = source.read(MAX_UPLOAD_BYTES + 1)
        markdown = convert_epub(data)
        if args.output:
            args.output.write_text(markdown, encoding="utf-8")
        else:
            sys.stdout.write(markdown)
    except ConversionError as exc:
        parser.exit(1, f"{exc.code}: {exc}\n")
    except OSError as exc:
        parser.exit(1, f"{exc.strerror}: {exc.filename or args.input}\n")


if __name__ == "__main__":
    main()
