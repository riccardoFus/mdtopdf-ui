#!/usr/bin/env python3
"""Generate the Marp demo deck into output/marp-demo.pdf."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import ConfigStore, validate_settings  # noqa: E402
from app.converter import convert_document, read_markdown_file  # noqa: E402


def main() -> int:
    store = ConfigStore()
    markdown, source = read_markdown_file(ROOT / "examples" / "marp-demo.md")
    result = convert_document(
        markdown,
        validate_settings({}),
        base_dir=source.parent,
        filename="marp-demo",
    )
    output = store.output_dir / "marp-demo.pdf"
    output.write_bytes(result.pdf)
    print(f"PDF Marp creato: {output}")
    print(f"Slide: {result.page_count} · {result.marp_size} · {result.duration_ms} ms · {len(result.pdf)} byte")
    for warning in result.warnings:
        print(f"  avviso: {warning['message']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
