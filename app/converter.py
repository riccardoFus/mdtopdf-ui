"""High-level conversion pipeline: Markdown -> HTML -> PDF."""

from __future__ import annotations

import copy
import html
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import (
    APP_DIR,
    MAX_MARKDOWN_BYTES,
    SettingsError,
    sanitize_filename,
    validate_settings,
)
from .markdown_engine import (
    Heading,
    MarkdownError,
    RenderedMarkdown,
    apply_frontmatter,
    parse_marp_deck,
    parse_markdown,
    split_frontmatter,
    _resolve_image,
)
from .pdf_engine import PdfError, page_count, render_pdf
from .rich_rendering import KATEX_CSS
from .styling import build_css, build_marp_css

ALLOWED_EXTENSIONS = {".md", ".markdown", ".mdown", ".txt"}


@dataclass
class ConversionResult:
    pdf: bytes
    html: str
    page_count: int
    warnings: list[dict[str, str]]
    duration_ms: int
    engine: str
    settings: dict[str, Any]
    headings: list[Heading] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    marp: bool = False
    marp_size: str = ""

    def meta_dict(self) -> dict[str, Any]:
        return {
            "pageCount": self.page_count,
            "warnings": self.warnings,
            "durationMs": self.duration_ms,
            "engine": self.engine,
            "marp": self.marp,
            "marpSize": self.marp_size,
            "headings": [
                {"level": h.level, "text": h.text, "slug": h.slug, "number": h.number}
                for h in self.headings
            ],
        }


def _document_name(filename: str | None) -> str:
    raw = Path(str(filename or "")).name
    for suffix in (".pdf", ".md", ".markdown", ".mdown", ".txt"):
        if raw.lower().endswith(suffix):
            raw = raw[: -len(suffix)]
            break
    raw = raw.strip()
    return raw or "documento"


def _cover_logo(
    logo: str,
    base_dir: Path | None,
    warnings: list[dict[str, str]],
) -> str:
    logo = (logo or "").strip()
    if not logo:
        return ""
    if logo.lower().startswith(("data:", "http://", "https://")):
        return logo
    candidate = Path(logo).expanduser()
    if not candidate.is_absolute():
        if base_dir is None:
            warnings.append({"level": "warning", "message": f"Logo copertina relativo senza cartella di base: {logo}"})
            return ""
        candidate = base_dir / candidate
    try:
        candidate = candidate.resolve()
    except OSError:
        pass
    if candidate.exists() and candidate.is_file():
        return candidate.as_uri()
    warnings.append({"level": "warning", "message": f"Logo copertina non trovato: {candidate}"})
    return ""


def build_document_html(
    rendered: RenderedMarkdown,
    settings: dict[str, Any],
    document_name: str,
    base_dir: Path | None = None,
) -> str:
    """Assemble the complete printable HTML document."""
    doc = settings["document"]
    theme = settings["theme"]
    layout = settings["layout"]
    warnings = rendered.warnings

    title = doc["title"] or document_name or "Documento"
    css = build_css(settings, document_name)
    if rendered.marp:
        css += build_marp_css(rendered.marp_size, rendered.marp_theme, settings)

    watermark_html = ""
    cover_html = ""
    toc_html = ""
    if not rendered.marp:
        watermark = layout["watermark"]
        if watermark["enabled"] and watermark["text"].strip():
            watermark_html = (
                f'<div class="watermark" aria-hidden="true"><span>{html.escape(watermark["text"])}</span></div>'
            )

        cover = layout["cover"]
        if cover["enabled"]:
            logo = _cover_logo(cover["logo"], base_dir, warnings)
            cover_title = cover["title"] or doc["title"] or document_name
            cover_subtitle = cover["subtitle"] or doc["subtitle"]
            cover_author = cover["author"] or doc["author"]
            cover_date = cover["date"] or doc["date"]
            parts = ['<section class="cover">']
            if logo:
                parts.append(f'<img class="cover-logo" src="{html.escape(logo, quote=True)}" alt="Logo">')
            if cover_subtitle and not cover_title:
                parts.append(f'<div class="cover-kicker">{html.escape(cover_subtitle)}</div>')
            parts.append(f'<h1 class="cover-title">{html.escape(cover_title)}</h1>')
            if cover_subtitle:
                parts.append(f'<div class="cover-subtitle">{html.escape(cover_subtitle)}</div>')
            parts.append('<div class="cover-rule"></div>')
            if cover_author:
                parts.append(f'<div class="cover-author">{html.escape(cover_author)}</div>')
            if cover_date:
                parts.append(f'<div class="cover-date">{html.escape(cover_date)}</div>')
            parts.append("</section>")
            cover_html = "".join(parts)

        toc_html = rendered.toc_html
        if doc["toc"] and not toc_html:
            warnings.append(
                {"level": "warning", "message": "Indice attivo ma il documento non contiene titoli."}
            )

    meta_author = f'<meta name="author" content="{html.escape(doc["author"], quote=True)}">' if doc["author"] else ""
    meta_subtitle = (
        f'<meta name="description" content="{html.escape(doc["subtitle"], quote=True)}">' if doc["subtitle"] else ""
    )
    katex_css = (
        f'<link rel="stylesheet" href="{KATEX_CSS.as_uri()}">'
        if rendered.has_math and KATEX_CSS.exists()
        else ""
    )
    main_class = "marp-deck" if rendered.marp else "content"

    return f"""<!DOCTYPE html>
<html lang="{html.escape(doc['lang'], quote=True)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
{meta_author}
{meta_subtitle}
<meta name="generator" content="MD → PDF Studio">
{katex_css}
<style>{css}</style>
</head>
<body>
{watermark_html}
{cover_html}
{toc_html}
<main class="{main_class}">
{rendered.body_html}
</main>
</body>
</html>"""


def convert_document(
    markdown: str,
    settings: dict[str, Any],
    base_dir: Path | str | None = None,
    filename: str = "documento",
    source_path: Path | str | None = None,
) -> ConversionResult:
    """Convert Markdown text to a PDF. Raises MarkdownError/SettingsError/PdfError."""
    started = time.perf_counter()
    if markdown is None or not str(markdown).strip():
        raise MarkdownError("Il documento Markdown è vuoto.")
    if len(str(markdown).encode("utf-8")) > MAX_MARKDOWN_BYTES:
        raise MarkdownError("Il documento supera il limite di 8 MB.")

    validated = validate_settings(settings)
    meta, body = split_frontmatter(str(markdown))
    effective = apply_frontmatter(validated, meta)

    resolved_base: Path | None = None
    if base_dir is not None:
        resolved_base = Path(base_dir).expanduser().resolve()
        if not resolved_base.is_dir():
            raise MarkdownError(f"Cartella di base non valida: {resolved_base}")
    elif source_path:
        resolved_base = Path(source_path).expanduser().resolve().parent

    document_name = _document_name(filename)
    marp_enabled = str(meta.get("marp", "")).strip().lower() in ("true", "1", "yes", "on")
    render_settings = effective
    if marp_enabled:
        render_settings = copy.deepcopy(effective)
        render_settings["document"].update(
            {
                "toc": False,
                "numberHeadings": False,
                "numberTables": False,
                "numberFigures": False,
                "numberPages": False,
            }
        )
        render_settings["layout"]["cover"]["enabled"] = False
        render_settings["layout"]["watermark"]["enabled"] = False
        render_settings["layout"].update(
            {"marginTop": 0, "marginBottom": 0, "marginLeft": 0, "marginRight": 0}
        )
        for key in (
            "headerLeft",
            "headerCenter",
            "headerRight",
            "footerLeft",
            "footerCenter",
            "footerRight",
        ):
            render_settings["headerFooter"][key] = ""
        render_settings["headerFooter"]["headerBorder"] = False
        render_settings["headerFooter"]["footerBorder"] = False
        rendered = parse_marp_deck(
            body,
            render_settings,
            meta,
            base_dir=resolved_base,
            document_name=document_name,
        )
    else:
        rendered = parse_markdown(
            body,
            effective,
            base_dir=resolved_base,
            document_name=document_name,
            warnings=[],
        )
    rendered.meta = meta
    document_html = build_document_html(rendered, render_settings, document_name, resolved_base)

    base_url = (resolved_base or APP_DIR).as_uri() + "/"
    pdf, engine, warnings = render_pdf(document_html, render_settings, base_url, rendered.warnings)
    pages = page_count(pdf)
    if pages < 1:
        raise PdfError("Il PDF generato non contiene pagine.")

    # De-duplicate warnings while preserving order.
    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for warning in warnings:
        key = (warning.get("level", "warning"), warning.get("message", ""))
        if key not in seen:
            seen.add(key)
            unique.append(warning)

    duration = int(round((time.perf_counter() - started) * 1000))
    return ConversionResult(
        pdf=pdf,
        html=document_html,
        page_count=pages,
        warnings=unique,
        duration_ms=duration,
        engine=engine,
        settings=effective,
        headings=rendered.headings,
        meta=meta,
        marp=rendered.marp,
        marp_size=rendered.marp_size if rendered.marp else "",
    )


def read_markdown_file(path: str | Path) -> tuple[str, Path]:
    """Read a local Markdown file with encoding fallbacks."""
    file_path = Path(path).expanduser()
    if not file_path.is_absolute():
        file_path = (Path.cwd() / file_path).resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"File non trovato: {file_path}")
    if not file_path.is_file():
        raise MarkdownError(f"Il percorso non è un file: {file_path}")
    if file_path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise MarkdownError(
            f"Estensione non supportata ({file_path.suffix}). Usa .md, .markdown, .mdown o .txt."
        )
    if file_path.stat().st_size > MAX_MARKDOWN_BYTES:
        raise MarkdownError("Il file supera il limite di 8 MB.")
    data = file_path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding), file_path
        except UnicodeDecodeError:
            continue
    raise MarkdownError(f"Impossibile decodificare il file: {file_path}")


def write_markdown_file(path: str | Path, content: str) -> Path:
    file_path = Path(path).expanduser()
    if not file_path.is_absolute():
        file_path = (Path.cwd() / file_path).resolve()
    if file_path.suffix.lower() not in ALLOWED_EXTENSIONS:
        file_path = file_path.with_suffix(".md")
    if not file_path.parent.exists():
        raise MarkdownError(f"La cartella di destinazione non esiste: {file_path.parent}")
    if len(content.encode("utf-8")) > MAX_MARKDOWN_BYTES:
        raise MarkdownError("Il documento supera il limite di 8 MB.")
    file_path.write_text(content, encoding="utf-8")
    return file_path


__all__ = [
    "ALLOWED_EXTENSIONS",
    "ConversionResult",
    "build_document_html",
    "convert_document",
    "read_markdown_file",
    "write_markdown_file",
    "sanitize_filename",
    "SettingsError",
]
