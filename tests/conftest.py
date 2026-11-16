"""Shared pytest fixtures for MD → PDF Studio."""

from __future__ import annotations

import base64
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_builtin_profiles, validate_settings  # noqa: E402

SVG_IMAGE = """<svg xmlns="http://www.w3.org/2000/svg" width="640" height="280" viewBox="0 0 640 280">
<rect width="640" height="280" rx="12" fill="#eef6ff" stroke="#93c5fd"/>
<circle cx="90" cy="90" r="42" fill="#0284c7"/>
<text x="90" y="99" text-anchor="middle" font-family="DejaVu Sans, sans-serif" font-size="22" fill="#fff">MD</text>
<rect x="190" y="50" width="380" height="36" rx="6" fill="#ffffff" stroke="#cbd5e1"/>
<rect x="190" y="110" width="300" height="18" rx="4" fill="#cbd5e1"/>
<rect x="190" y="142" width="340" height="18" rx="4" fill="#dbeafe"/>
<rect x="190" y="174" width="250" height="18" rx="4" fill="#cbd5e1"/>
<rect x="40" y="205" width="560" height="2" fill="#bfdbfe"/>
<text x="40" y="245" font-family="DejaVu Sans, sans-serif" font-size="16" fill="#475569">Documento di prova — immagine locale</text>
</svg>
"""


def _make_markdown() -> str:
    rows = "\n".join(
        f"| {index} | Attività numero {index} | Team {index % 3} | {'Completata' if index % 2 else 'In corso'} |"
        for index in range(1, 26)
    )
    code = "\n".join(f"print('riga {index}')" for index in range(1, 31))
    return f"""---
title: "Documento completo di prova"
subtitle: "Tutti gli elementi Markdown supportati"
author: "Mario Rossi"
date: "23 ottobre 2026"
lang: it
toc: true
toc_depth: 3
header: "{{title}} — {{author}}"
footer: "Pagina {{page}} di {{pages}} — {{filename}}"
---

# Introduzione

Testo italiano con accenti: perché, è, à, ù, ò, ì. Emoji: 😀 🚀 📄.

**Grassetto**, *corsivo*, ~~barrato~~, `codice inline` e [un link](https://example.com).

## Sezione con note

Una nota a piè di pagina[^1] e un'altra[^2].

[^1]: Contenuto della prima nota.
[^2]: Contenuto della seconda nota, con **formattazione**.

### Checklist

- [x] Primo punto completato
- [ ] Secondo punto da fare
- [x] Terzo punto completato

### Tabella lunga

| # | Attività | Team | Stato |
|--:|:---------|:-----|:-----:|
{rows}

## Codice

~~~python linenums
{code}
~~~

```json
{{"nome": "valore", "numero": 42}}
```

## Immagine e didascalia

![Immagine locale di prova](assets/pic.svg "Figura: architettura del sistema")

> Una citazione con **enfasi** e [link](https://example.org).

<!-- pagebreak -->

# Seconda parte

## Sezione finale

Testo dopo l'interruzione di pagina.

\\newpage

### Ultimo titolo

Paragrafo conclusivo.
"""


FULL_MARKDOWN = _make_markdown()


@pytest.fixture
def sample_dir(tmp_path: Path) -> Path:
    docs = tmp_path / "docs"
    (docs / "assets").mkdir(parents=True)
    (docs / "assets" / "pic.svg").write_text(SVG_IMAGE, encoding="utf-8")
    (docs / "full.md").write_text(FULL_MARKDOWN, encoding="utf-8")
    return docs


@pytest.fixture
def markdown(sample_dir: Path) -> str:
    return (sample_dir / "full.md").read_text(encoding="utf-8")


@pytest.fixture
def settings() -> dict:
    return validate_settings(
        {
            "document": {
                "toc": True,
                "tocDepth": 3,
                "numberHeadings": True,
                "numberTables": True,
                "numberFigures": True,
                "numberPages": True,
                "figureCaptions": True,
            },
            "typography": {"bodySize": 10.5, "codeLineNumbers": True},
            "layout": {
                "avoidHeadingOrphans": True,
                "avoidBreakInside": True,
                "watermark": {"enabled": False},
            },
            "headerFooter": {
                "footerCenter": "Pagina {page} di {pages}",
            },
        }
    )


@pytest.fixture
def app(tmp_path: Path):
    from app.main import create_app

    return create_app(
        config_path=tmp_path / "config.json",
        state_dir=tmp_path / "state",
        output_dir=tmp_path / "output",
    )


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def tiny_png_base64() -> str:
    # 2x2 red PNG
    return (
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVR4nGP8z8Dwn4GBgYkBBAAAHgIC"
        "6X0F6QAAAABJRU5ErkJggg=="
    )
