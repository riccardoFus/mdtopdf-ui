#!/usr/bin/env python3
"""Generate a complete demonstration PDF into output/."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import ConfigStore, get_builtin_profiles  # noqa: E402
from app.converter import convert_document, read_markdown_file  # noqa: E402


def main() -> int:
    store = ConfigStore()
    markdown, source = read_markdown_file(ROOT / "examples" / "demo.md")
    settings = get_builtin_profiles()["Report tecnico"]

    # A few flourishes that make the sample exercise every layout feature.
    settings["document"]["numberHeadings"] = True
    settings["document"]["numberTables"] = True
    settings["document"]["numberFigures"] = True
    settings["layout"]["cover"] = {
        "enabled": True,
        "title": "MD → PDF Studio",
        "subtitle": "Guida operativa e documento di prova",
        "author": "Studio MD → PDF",
        "date": "23 ottobre 2026",
        "logo": "",
    }
    settings["layout"]["watermark"] = {
        "enabled": True,
        "text": "ESEMPIO",
        "opacity": 0.055,
        "rotation": -35,
        "position": "center",
        "color": "#1e3a8a",
    }
    result = convert_document(
        markdown,
        settings,
        base_dir=source.parent,
        filename="esempio-completo",
    )
    output = store.output_dir / "esempio-completo.pdf"
    output.write_bytes(result.pdf)
    print(f"PDF creato: {output}")
    print(f"Pagine: {result.page_count} · motore: {result.engine} · {result.duration_ms} ms · {len(result.pdf)} byte")
    if result.warnings:
        print("Avvisi:")
        for warning in result.warnings:
            print(f"  - {warning['message']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
