"""Reading-ready EPUB conversion; CLI and HTTP are adapters over one engine."""

from .converter import ConversionError, convert_epub

__all__ = ["ConversionError", "convert_epub"]
