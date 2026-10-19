import argparse
import os
from pathlib import Path

import uvicorn

from .converter import ConversionError, check_dependencies, convert_epub


def main():
    parser = argparse.ArgumentParser(description="EPUB to Markdown using the iooh-epub pipeline")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Start the HTTP API")
    serve.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("PORT", "3000")))
    convert = commands.add_parser("convert", help="Convert an EPUB locally")
    convert.add_argument("input", type=Path)
    convert.add_argument("-o", "--output", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "serve":
        uvicorn.run("epub_convert.api:app", host=args.host, port=args.port)
    else:
        check_dependencies()
        try:
            markdown = convert_epub(args.input.read_bytes())
        except ConversionError as exc:
            parser.exit(1, f"{exc.code}: {exc}\n")
        args.output.write_text(markdown, encoding="utf-8")


if __name__ == "__main__":
    main()
