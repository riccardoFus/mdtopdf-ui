"""Tests for Marp-compatible slide decks."""

from __future__ import annotations

import io
import logging

import pymupdf
import pytest
from pypdf import PdfReader

from app.config import validate_settings
from app.converter import convert_document
from app.markdown_engine import parse_marp_deck, split_frontmatter, split_marp_slides


PLAIN_DECK = """# Prima slide

Contenuto uno.

---

## Seconda slide

Contenuto due.

---

## Terza slide

Contenuto tre.
"""


def test_split_marp_slides_ignores_separators_inside_code():
    text = "# A\n\n```\n---\n```\n\n---\n\n# B\n"
    slides = split_marp_slides(text)
    assert len(slides) == 2
    assert "---" in slides[0]
    assert "B" in slides[1]


def test_marp_deck_detection_and_page_geometry():
    markdown = f"""---
marp: true
size: 16:9
theme: default
paginate: true
---

<!-- _class: lead -->
<!-- _paginate: false -->

{PLAIN_DECK}
"""
    result = convert_document(markdown, validate_settings({}), filename="deck")
    assert result.marp is True
    assert result.marp_size == "16:9"
    assert result.page_count == 3
    assert result.warnings == []
    assert 'class="marp-slide marp-theme-default lead"' in result.html
    assert result.html.count('class="marp-page-number"') == 2  # first slide opts out
    assert "_paginate" not in result.html and "_class" not in result.html

    with pymupdf.open(stream=result.pdf, filetype="pdf") as document:
        assert document.page_count == 3
        for page in document:
            assert round(page.rect.width) == 960
            assert round(page.rect.height) == 540
        assert "Prima slide" in document[0].get_text()
        assert "Terza slide" in document[2].get_text()

    reader = PdfReader(io.BytesIO(result.pdf))
    assert len(reader.pages) == 3


def test_marp_4_3_and_theme_uncover():
    markdown = """---
marp: true
size: 4:3
theme: uncover
paginate: false
---

# Dark
"""
    result = convert_document(markdown, validate_settings({}), filename="deck43")
    assert result.marp is True
    with pymupdf.open(stream=result.pdf, filetype="pdf") as document:
        assert round(document[0].rect.width) == 720
        assert round(document[0].rect.height) == 540
        assert "marp-theme-uncover" in result.html


def test_regular_markdown_horizontal_rule_is_not_a_deck():
    result = convert_document(
        "# Un titolo\n\n---\n\n# Un altro titolo\n",
        validate_settings({}),
        filename="normal",
    )
    assert result.marp is False
    assert "<hr" in result.html
    assert "marp-slide" not in result.html


def test_marp_math_and_mermaid_render_in_pdf(caplog):
    from app.rich_rendering import rich_available

    if not rich_available():
        pytest.skip("Chromium/Playwright non disponibile")
    caplog.set_level(logging.ERROR)
    markdown = """---
marp: true
size: 16:9
paginate: true
---

# Diagramma

```mermaid
flowchart LR
  A[Markdown] --> B[PDF]
```

---

# Formula

$E = mc^2$
"""
    result = convert_document(markdown, validate_settings({}), filename="marp-rich")
    assert result.marp is True
    assert result.page_count == 2
    assert result.warnings == []
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
    with pymupdf.open(stream=result.pdf, filetype="pdf") as document:
        assert any(page.get_images(full=True) for page in document)
        assert "mc" in document[1].get_text()


def test_parse_marp_deck_returns_slide_sections():
    meta, body = split_frontmatter(
        "---\nmarp: true\nsize: 16:9\n---\n\n# Uno\n\n---\n\n## Due\n"
    )
    rendered = parse_marp_deck(body, validate_settings({}), meta)
    assert rendered.marp is True
    assert rendered.body_html.count("<section") == 2
    assert "marp-slide" in rendered.body_html
