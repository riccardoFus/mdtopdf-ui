"""PDF rendering tests: complete documents, long content and internal links."""

from __future__ import annotations

import io
import logging
from pathlib import Path

import pymupdf
import pytest
from pypdf import PdfReader

from app.config import validate_settings
from app.converter import convert_document
from app.markdown_engine import MarkdownError


def convert_full(markdown: str, settings: dict, base_dir: Path, filename: str = "test"):
    return convert_document(markdown, settings, base_dir=base_dir, filename=filename)


def test_full_document_renders_all_elements(markdown, settings, sample_dir, caplog):
    caplog.set_level(logging.ERROR)
    result = convert_full(markdown, settings, sample_dir, "completo")
    assert result.page_count >= 4
    assert len(result.pdf) > 10_000
    assert result.warnings == []
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]

    reader = PdfReader(io.BytesIO(result.pdf))
    assert len(reader.pages) == result.page_count
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    for needle in ("Documento completo di prova", "Introduzione", "Tabella 1", "Figura", "Contenuto della prima nota"):
        assert needle in text
    assert "perché" in text and "è" in text
    assert "Immagine non disponibile" not in text

    with pymupdf.open(stream=result.pdf, filetype="pdf") as document:
        assert document.page_count == result.page_count
        for page in document:
            rect = page.rect
            assert round(rect.width) == 595 and round(rect.height) == 842
            for block in page.get_text("blocks"):
                assert block[0] >= -1
                assert block[1] >= -1
                assert block[2] <= rect.width + 1
                assert block[3] <= rect.height + 1


def test_toc_contains_working_internal_links(markdown, settings, sample_dir):
    result = convert_full(markdown, settings, sample_dir)
    with pymupdf.open(stream=result.pdf, filetype="pdf") as document:
        toc_page = document[0]
        assert "Indice" in toc_page.get_text()
        links = toc_page.get_links()
        internal = [
            link for link in links
            if link.get("kind") in (pymupdf.LINK_GOTO, pymupdf.LINK_NAMED)
        ]
        assert len(internal) >= 5
        names = {link.get("nameddest") or link.get("page") for link in internal}
        assert "introduzione" in names
        assert "seconda-parte" in names


def test_cover_suppresses_header_footer_and_uses_full_page(settings, sample_dir):
    settings = validate_settings(settings)
    settings["layout"]["cover"] = {
        "enabled": True,
        "title": "COPERTINA UNICA",
        "subtitle": "Sottotitolo",
        "author": "Autore Copertina",
        "date": "2026",
        "logo": "",
    }
    settings["headerFooter"]["headerCenter"] = "HEADER-VISIBILE"
    settings["headerFooter"]["footerCenter"] = "FOOTER-{page}-{pages}"
    result = convert_document(
        "# Corpo\n\nTesto.\n",
        settings,
        base_dir=sample_dir,
        filename="cover-test",
    )
    assert result.page_count >= 2
    with pymupdf.open(stream=result.pdf, filetype="pdf") as document:
        cover = document[0].get_text()
        body = document[1].get_text()
        assert "COPERTINA UNICA" in cover
        assert "Autore Copertina" in cover
        assert "HEADER-VISIBILE" not in cover
        assert "FOOTER-" not in cover
        assert "HEADER-VISIBILE" in body


def test_watermark_and_page_numbers_are_present(settings, sample_dir):
    settings = validate_settings(settings)
    settings["document"]["toc"] = False
    settings["layout"]["watermark"] = {
        "enabled": True,
        "text": "RISERVATO",
        "opacity": 0.08,
        "rotation": -35,
        "position": "center",
        "color": "#000000",
    }
    settings["document"]["numberPages"] = True
    settings["headerFooter"]["footerCenter"] = "Pagina {page} di {pages}"
    result = convert_document("# Titolo\n\nTesto.\n<!-- pagebreak -->\n# Due\n\nAltro.\n", settings)
    assert result.page_count >= 2
    with pymupdf.open(stream=result.pdf, filetype="pdf") as document:
        for page in document:
            assert "RISERVATO" in page.get_text()
        assert "Pagina 1 di 2" in document[0].get_text()
        assert "Pagina 2 di 2" in document[1].get_text()


def test_long_table_breaks_pages_without_clipping(settings, sample_dir):
    rows = "\n".join(
        f"| {index} | Riga molto lunga numero {index} con descrizione estesa | {index * 7} |"
        for index in range(1, 81)
    )
    markdown = (
        "# Tabella lunga\n\n"
        "| # | Descrizione | Valore |\n|--:|:------------|-------:|\n"
        + rows
        + "\n\nDopo la tabella.\n"
    )
    result = convert_document(markdown, settings, base_dir=sample_dir, filename="tabella")
    assert result.page_count >= 2
    with pymupdf.open(stream=result.pdf, filetype="pdf") as document:
        pages_with_header = sum(
            1 for page in document if "Descrizione" in page.get_text() and "Valore" in page.get_text()
        )
        assert pages_with_header >= 2
        for page in document:
            rect = page.rect
            for block in page.get_text("blocks"):
                assert block[2] <= rect.width + 1
                assert block[3] <= rect.height + 1
        full_text = "\n".join(page.get_text() for page in document)
        assert "Riga molto lunga numero 1 " in full_text
        assert "Riga molto lunga numero 80" in full_text
        assert "Dopo la tabella." in full_text


def test_long_code_block_does_not_overflow(settings, sample_dir):
    settings = validate_settings(settings)
    settings["typography"]["codeLineNumbers"] = True
    code = "\n".join(f"valore_{index} = {index}  # riga {index}" for index in range(1, 121))
    markdown = f"# Codice lungo\n\n```python linenums\n{code}\n```\n\nFine del codice.\n"
    result = convert_document(markdown, settings, base_dir=sample_dir, filename="codice")
    assert result.page_count >= 2
    with pymupdf.open(stream=result.pdf, filetype="pdf") as document:
        for page in document:
            rect = page.rect
            for block in page.get_text("blocks"):
                assert block[2] <= rect.width + 1
                assert block[3] <= rect.height + 1
        full_text = "\n".join(page.get_text() for page in document)
        assert "valore_120" in full_text
        assert "Fine del codice." in full_text


def test_landscape_and_custom_page_size(settings, sample_dir):
    settings = validate_settings(settings)
    settings["layout"].update({"pageSize": "A5", "orientation": "landscape", "marginTop": 10, "marginBottom": 10})
    result = convert_document("# Paesaggio\n\nTesto.\n", settings, base_dir=sample_dir)
    with pymupdf.open(stream=result.pdf, filetype="pdf") as document:
        rect = document[0].rect
        assert round(rect.width) == 595  # A5 landscape = 210mm wide
        assert round(rect.height) == 420  # 148mm high


def test_missing_image_produces_readable_placeholder(settings, tmp_path: Path):
    settings = validate_settings(settings)
    settings["document"]["toc"] = False
    markdown = "# Con immagine mancante\n\n![Non trovata](manca.png)\n\nTesto finale.\n"
    result = convert_document(markdown, settings, base_dir=tmp_path, filename="mancante")
    assert result.warnings
    with pymupdf.open(stream=result.pdf, filetype="pdf") as document:
        text = document[0].get_text()
        assert "Immagine non disponibile" in text
        assert "Testo finale." in text


def test_chromium_fallback_engine(settings):
    from app.pdf_engine import playwright_available

    if not playwright_available():
        pytest.skip("Chromium/Playwright non disponibile")
    settings = validate_settings(settings)
    settings["pdf"]["engine"] = "chromium"
    settings["document"]["toc"] = False
    result = convert_document("# Fallback Chromium\n\nTesto 2026 😀\n", settings)
    assert result.engine == "chromium"
    assert result.pdf.startswith(b"%PDF")
    assert result.page_count >= 1


def test_digits_use_text_font_not_emoji_font(settings):
    settings = validate_settings(settings)
    settings["document"]["toc"] = False
    markdown = "# Numeri 123\n\nAnno 2026, importo 1.250,00 €. Emoji 😀 🚀.\n"
    result = convert_document(markdown, settings, filename="numeri")
    with pymupdf.open(stream=result.pdf, filetype="pdf") as document:
        spans = [
            span
            for block in document[0].get_text("dict")["blocks"]
            for line in block.get("lines", [])
            for span in line["spans"]
        ]
        numeric = [span for span in spans if "2026" in span["text"] or "123" in span["text"]]
        assert numeric
        assert all("Emoji" not in span["font"] for span in numeric)
        assert any("Emoji" in span["font"] for span in spans if "😀" in span["text"] or "🚀" in span["text"])


def test_avoid_break_inside_heading_option(settings):
    settings = validate_settings(settings)
    settings["layout"]["avoidHeadingOrphans"] = True
    fill = "\n\n".join(f"Paragrafo {index} con testo di riempimento." for index in range(1, 60))
    markdown = f"# Riempimento\n\n{fill}\n\n## Titolo che non deve restare isolato\n\nTesto.\n"
    result = convert_document(markdown, settings)
    assert result.page_count >= 2
    with pymupdf.open(stream=result.pdf, filetype="pdf") as document:
        for page_number, page in enumerate(document):
            text = page.get_text().strip().splitlines()
            if not text:
                continue
            # A heading must not be the very last line on a page.
            assert not text[-1].strip().startswith("## ")


def _rich_markdown() -> str:
    return """# Diagrammi e formule

Formula inline: $E = mc^2$ e $a^2 + b^2 = c^2$.

$$\\int_0^\\infty e^{-x^2}\\,dx = \\frac{\\sqrt{\\pi}}{2}$$

```mermaid
flowchart LR
  A[Markdown] --> B[Motore]
  B --> C[PDF]
```

Testo finale.
"""


def test_math_and_mermaid_in_pdf(settings, caplog):
    from app.rich_rendering import rich_available

    if not rich_available():
        pytest.skip("Chromium/Playwright non disponibile")
    caplog.set_level(logging.ERROR)
    settings = validate_settings(settings)
    settings["document"]["toc"] = False
    result = convert_document(_rich_markdown(), settings, filename="rich")
    assert result.page_count >= 1
    assert result.warnings == []
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
    with pymupdf.open(stream=result.pdf, filetype="pdf") as document:
        page = document[0]
        text = page.get_text()
        assert "Diagrammi e formule" in text
        assert "mc" in text
        assert page.get_images(full=True)
        for block in page.get_text("blocks"):
            assert block[2] <= page.rect.width + 1
            assert block[3] <= page.rect.height + 1


def test_chromium_fallback_with_math_and_mermaid(settings):
    from app.pdf_engine import playwright_available
    from app.rich_rendering import rich_available

    if not playwright_available() or not rich_available():
        pytest.skip("Chromium/Playwright non disponibile")
    settings = validate_settings(settings)
    settings["document"]["toc"] = False
    settings["pdf"]["engine"] = "chromium"
    result = convert_document(_rich_markdown(), settings, filename="rich-chromium")
    assert result.engine == "chromium"
    assert result.page_count >= 1
    assert result.pdf.startswith(b"%PDF")
