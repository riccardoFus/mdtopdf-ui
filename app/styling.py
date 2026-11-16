"""CSS generation for paged PDF output (WeasyPrint / Chromium)."""

from __future__ import annotations

import html
import re
from datetime import date
from typing import Any

from pygments.formatters import HtmlFormatter

from .config import page_dimensions

HEADER_FOOTER_VARIABLES = ("title", "author", "date", "pages", "page", "filename")

_GENERIC_FONTS = {
    "serif",
    "sans-serif",
    "monospace",
    "cursive",
    "fantasy",
    "system-ui",
    "ui-serif",
    "ui-sans-serif",
    "ui-monospace",
}


def _css_string(value: str) -> str:
    """Escape a value for a CSS string literal."""
    value = str(value).replace("\\", "\\\\").replace('"', '\\"')
    value = value.replace("\r", " ").replace("\n", " ").replace("\x00", "")
    return f'"{value}"'


def font_stack(font: str, fallback: str = "sans-serif") -> str:
    font = (font or "").strip()
    if not font:
        return fallback
    families = [part.strip().strip("'\"") for part in font.split(",") if part.strip()]
    output: list[str] = []
    for family in families:
        if family.lower() in _GENERIC_FONTS:
            output.append(family)
        else:
            output.append(f'"{family}"')
    if fallback and fallback not in output:
        output.append(fallback)
    # Do NOT list Noto Color Emoji here: Pango falls back to it automatically
    # for emoji, while listing it explicitly makes digits/punctuation render
    # with the emoji font (visibly spaced numbers).
    # Remove duplicates while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for item in output:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return ", ".join(unique)


def _replace_variables(template: str, settings: dict[str, Any], document_name: str) -> str:
    """Return a CSS content expression for a header/footer template."""
    doc = settings["document"]

    def value_for(name: str) -> str:
        if name == "title":
            return doc.get("title") or document_name or "Documento"
        if name == "author":
            return doc.get("author") or ""
        if name == "date":
            return doc.get("date") or date.today().strftime("%d/%m/%Y")
        if name == "filename":
            return document_name or "documento"
        return ""

    chunks: list[str] = []
    position = 0
    for match in re.finditer(r"\{(title|author|date|pages|page|filename)\}", template or ""):
        literal = (template or "")[position:match.start()]
        if literal:
            chunks.append(_css_string(literal))
        token = match.group(1)
        if token in ("page", "pages"):
            chunks.append(f"counter({token})")
        else:
            chunks.append(_css_string(value_for(token)))
        position = match.end()
    tail = (template or "")[position:]
    if tail:
        chunks.append(_css_string(tail))
    return " ".join(chunks) if chunks else "none"


def _margin_box_content(
    template: str,
    settings: dict[str, Any],
    document_name: str,
) -> str:
    if not (template or "").strip():
        return "none"
    return _replace_variables(template, settings, document_name)


def _header_footer_css(settings: dict[str, Any], document_name: str) -> str:
    hf = settings["headerFooter"]
    doc = settings["document"]
    footer_center = hf["footerCenter"]
    default_page_label = "{page} / {pages}"

    if doc["numberPages"]:
        if not footer_center.strip() and not hf["footerLeft"].strip() and not hf["footerRight"].strip():
            footer_center = default_page_label
    else:
        if footer_center.strip() == default_page_label and not hf["footerLeft"].strip() and not hf["footerRight"].strip():
            footer_center = ""

    slots = [
        ("top-left", hf["headerLeft"], hf["headerFontSize"], hf["headerBorder"]),
        ("top-center", hf["headerCenter"], hf["headerFontSize"], hf["headerBorder"]),
        ("top-right", hf["headerRight"], hf["headerFontSize"], hf["headerBorder"]),
        ("bottom-left", hf["footerLeft"], hf["footerFontSize"], hf["footerBorder"]),
        ("bottom-center", footer_center, hf["footerFontSize"], hf["footerBorder"]),
        ("bottom-right", hf["footerRight"], hf["footerFontSize"], hf["footerBorder"]),
    ]
    rules: list[str] = []
    for name, template, size, border in slots:
        if not (template or "").strip():
            continue
        content = _margin_box_content(template, settings, document_name)
        font = font_stack(settings["typography"]["bodyFont"], "sans-serif")
        border_css = ""
        if border:
            border_css = f"border-{'bottom' if name.startswith('top') else 'top'}: 0.4pt solid {settings['theme']['border']};"
        rules.append(
            f"@{name} {{ content: {content}; font-family: {font}; font-size: {size:g}pt;"
            f" color: {settings['theme']['muted']}; padding: 2mm 0; {border_css} }}"
        )
    return "\n".join(rules)


def build_css(settings: dict[str, Any], document_name: str = "documento") -> str:
    """Build the complete print stylesheet for the current settings."""
    typo = settings["typography"]
    layout = settings["layout"]
    theme = settings["theme"]
    doc = settings["document"]
    scale = float(layout["scale"]) / 100.0

    width, height = page_dimensions(settings)
    body_font = font_stack(typo["bodyFont"], "serif")
    heading_font = font_stack(typo["headingFont"], "sans-serif")
    mono_font = font_stack(typo["monoFont"], "monospace")

    def pt(value: float) -> str:
        return f"{float(value) * scale:.2f}".rstrip("0").rstrip(".") + "pt"

    align = typo["textAlign"]
    pygments_style = "monokai" if theme.get("name") == "dark" else "friendly"
    pygments_css = HtmlFormatter(style=pygments_style).get_style_defs(".code-block")
    # Keep Pygments token colours but let our theme own the block background.
    pygments_css = re.sub(r"(?m)^\.code-block \{.*?\}\s*$", "", pygments_css)

    heading_avoid = "break-after: avoid-page; page-break-after: avoid;" if layout["avoidHeadingOrphans"] else ""
    break_inside = "break-inside: avoid; page-break-inside: avoid;" if layout["avoidBreakInside"] else ""
    hyphen = "hyphens: auto;" if typo["hyphenate"] else "hyphens: manual;"

    header_footer = _header_footer_css(settings, document_name)

    watermark_css = ""
    watermark = layout["watermark"]
    if watermark["enabled"] and watermark["text"].strip():
        position = watermark["position"]
        positions = {
            "center": ("top: 50%; left: 50%;", "translate(-50%, -50%)"),
            "top-left": ("top: 18%; left: 8%;", "rotate(-0deg)"),
            "top-right": ("top: 18%; right: 8%;", "rotate(0deg)"),
            "bottom-left": ("bottom: 14%; left: 8%;", "rotate(0deg)"),
            "bottom-right": ("bottom: 14%; right: 8%;", "rotate(0deg)"),
        }
        placement, transform = positions[position]
        rotation = float(watermark["rotation"])
        if position == "center":
            transform = f"translate(-50%, -50%) rotate({rotation}deg)"
        else:
            transform = f"rotate({rotation}deg)"
        watermark_css = f"""
.watermark {{ position: fixed; inset: 0; z-index: 0; pointer-events: none; }}
.watermark span {{
  position: absolute; {placement} transform: {transform}; transform-origin: center;
  font-family: {heading_font}; font-size: 64pt; font-weight: 700; letter-spacing: 0.08em;
  color: {watermark['color']}; opacity: {float(watermark['opacity']):.3f}; white-space: nowrap;
}}
body > *:not(.watermark) {{ position: relative; z-index: 1; }}
"""

    cover_css = ""
    if layout["cover"]["enabled"]:
        cover_css = """
@page cover { size: %(w)smm %(h)smm; margin: 0; background: %(bg)s;
  @top-left { content: none; } @top-center { content: none; } @top-right { content: none; }
  @bottom-left { content: none; } @bottom-center { content: none; } @bottom-right { content: none; } }
.cover { page: cover; height: %(h)smm; box-sizing: border-box; padding: 32mm 28mm 28mm;
  text-align: center; break-after: page; page-break-after: always; }
.cover .cover-logo { max-width: 62mm; max-height: 40mm; margin: 0 auto 18mm; display: block; }
.cover .cover-kicker { font-family: %(body)s; font-size: %(caption)s; letter-spacing: 0.18em;
  text-transform: uppercase; color: %(accent)s; margin-bottom: 8mm; }
.cover h1.cover-title { font-family: %(heading)s; font-size: %(title)s; line-height: 1.15;
  color: %(headings)s; margin: 0 0 6mm; border: 0; padding: 0; }
.cover .cover-subtitle { font-family: %(body)s; font-size: %(subtitle)s; color: %(muted)s; margin: 0 0 18mm; }
.cover .cover-rule { width: 28mm; height: 1.2pt; background: %(accent)s; margin: 0 auto 12mm; }
.cover .cover-author { font-family: %(body)s; font-size: %(author)s; color: %(text)s; margin-bottom: 3mm; }
.cover .cover-date { font-family: %(body)s; font-size: %(date)s; color: %(muted)s; }
.cover .cover-spacer { height: 40mm; }
""" % {
            "w": f"{width:g}",
            "h": f"{height:g}",
            "bg": theme["background"],
            "body": body_font,
            "heading": heading_font,
            "caption": pt(typo["captionSize"]),
            "title": pt(max(28.0, typo["h1Size"] * 1.35)),
            "subtitle": pt(max(14.0, typo["h2Size"] * 0.95)),
            "author": pt(max(11.0, typo["bodySize"] * 1.1)),
            "date": pt(typo["bodySize"]),
            "accent": theme["link"],
            "headings": theme["headings"],
            "muted": theme["muted"],
            "text": theme["text"],
        }

    return f"""
/* =====================================================================
   MD → PDF Studio — generated print stylesheet
   page: {width:g} x {height:g} mm | align: {align} | scale: {layout['scale']}%
   ===================================================================== */
@page {{
  size: {width:g}mm {height:g}mm;
  margin: {layout['marginTop']:g}mm {layout['marginRight']:g}mm {layout['marginBottom']:g}mm {layout['marginLeft']:g}mm;
  background: {theme['background']};
{header_footer}
}}

* {{ box-sizing: border-box; }}

html {{ font-size: {pt(typo['bodySize'])}; }}

body {{
  margin: 0;
  padding: 0;
  font-family: {body_font};
  font-size: {pt(typo['bodySize'])};
  line-height: {typo['lineHeight']:g};
  color: {theme['text']};
  background: {theme['background']};
  text-align: {align};
  {hyphen}
  overflow-wrap: break-word;
}}

p {{ margin: 0 0 {typo['paragraphSpacing']:g}em; orphans: 2; widows: 2; }}
p:last-child {{ margin-bottom: 0; }}

h1, h2, h3, h4, h5, h6 {{
  font-family: {heading_font};
  color: {theme['headings']};
  line-height: 1.22;
  font-weight: 700;
  margin: 1.15em 0 0.5em;
  {heading_avoid}
  break-inside: avoid;
  page-break-inside: avoid;
}}
h1 {{ font-size: {pt(typo['h1Size'])}; margin-top: 0.2em; padding-bottom: 0.18em; border-bottom: 1.2pt solid {theme['border']}; }}
h2 {{ font-size: {pt(typo['h2Size'])}; padding-bottom: 0.12em; border-bottom: 0.6pt solid {theme['border']}; }}
h3 {{ font-size: {pt(typo['h3Size'])}; }}
h4 {{ font-size: {pt(typo['h4Size'])}; }}
h5 {{ font-size: {pt(max(8.0, typo['h4Size'] * 0.93))}; }}
h6 {{ font-size: {pt(max(8.0, typo['h4Size'] * 0.86))}; color: {theme['muted']}; }}
.heading .hnum {{ color: {theme['muted']}; font-weight: 600; }}

a {{ color: {theme['link']}; text-decoration: underline; text-decoration-thickness: 0.5pt; overflow-wrap: break-word; }}
strong {{ font-weight: 700; }}
em {{ font-style: italic; }}
del, s {{ color: {theme['muted']}; }}

ul, ol {{ margin: 0.35em 0 {typo['paragraphSpacing']:g}em; padding-left: {typo['listIndent']:g}em; }}
li {{ margin: 0.18em 0; }}
li > ul, li > ol {{ margin: 0.15em 0; }}
ul.contains-task-list, ul.task-list {{ list-style: none; padding-left: 0.2em; }}
li.task-list-item {{ list-style: none; }}
.task-checkbox {{
  display: inline-block; width: 0.82em; height: 0.82em; line-height: 0.72em;
  margin-right: 0.45em; border: 0.9pt solid {theme['muted']}; border-radius: 2px;
  font-size: 0.8em; text-align: center; color: {theme['background']};
  vertical-align: -0.05em; font-weight: 700;
}}
.task-checkbox.is-checked {{ background: {theme['link']}; border-color: {theme['link']}; }}

code, kbd, samp {{
  font-family: {mono_font};
  font-size: 0.9em;
  background: {theme['codeBg']};
  color: {theme['codeText']};
  border: 0.5pt solid {theme['border']};
  border-radius: 2px;
  padding: 0.08em 0.28em;
}}

.code-block {{
  margin: 0.7em 0 1em;
  border: 0.6pt solid {theme['border']};
  border-radius: 3px;
  background: {theme['codeBg']};
  overflow: hidden;
  {break_inside}
}}
.code-head {{
  padding: 0.35em 0.7em;
  border-bottom: 0.5pt solid {theme['border']};
  font-family: {mono_font};
  font-size: {pt(max(6.0, typo['codeSize'] * 0.78))};
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: {theme['muted']};
}}
.code-lang {{ font-weight: 600; }}
pre.code-pre {{
  margin: 0;
  padding: 0.7em 0.8em;
  background: transparent;
  color: {theme['codeText']};
  font-family: {mono_font};
  font-size: {pt(typo['codeSize'])};
  line-height: 1.42;
  white-space: pre-wrap;
  overflow-wrap: break-word;
  border: 0;
}}
pre.code-pre code {{ background: transparent; border: 0; padding: 0; font-size: inherit; color: inherit; }}
.code-table {{ width: 100%; border-collapse: collapse; margin: 0; border: 0; }}
.code-table td {{ border: 0; padding: 0; vertical-align: top; }}
.code-table .code-gutter {{
  width: 1%; white-space: nowrap;
  border-right: 0.5pt solid {theme['border']};
  background: {theme['tableHeaderBg']};
}}
.code-table .code-gutter pre {{
  margin: 0; padding: 0.7em 0.55em; color: {theme['muted']};
  font-family: {mono_font}; font-size: {pt(typo['codeSize'])}; line-height: 1.42; text-align: right;
}}
.code-table .code-line-cell pre.code-pre {{ padding-left: 0.8em; }}

blockquote {{
  margin: 0.8em 0;
  padding: 0.5em 0.9em;
  border-left: 2.5pt solid {theme['link']};
  background: {theme['blockquoteBg']};
  color: {theme['text']};
  {break_inside}
}}
blockquote p:last-child {{ margin-bottom: 0; }}

table.doc-table {{
  width: 100%;
  border-collapse: collapse;
  margin: 0.7em 0 1em;
  font-size: {pt(typo['tableSize'])};
  line-height: 1.35;
  {break_inside}
}}
table.doc-table thead {{ display: table-header-group; }}
table.doc-table tr {{ break-inside: avoid; page-break-inside: avoid; }}
table.doc-table th, table.doc-table td {{
  border: 0.6pt solid {theme['border']};
  padding: 0.42em 0.55em;
  vertical-align: top;
  text-align: left;
}}
table.doc-table th {{ background: {theme['tableHeaderBg']}; font-weight: 700; color: {theme['headings']}; }}
table.doc-table tbody tr:nth-child(even) {{ background: {theme['tableHeaderBg']}; }}
table.doc-table caption.table-caption {{
  caption-side: top;
  text-align: left;
  font-family: {heading_font};
  font-size: {pt(typo['captionSize'])};
  color: {theme['muted']};
  font-weight: 600;
  padding-bottom: 0.35em;
  break-after: avoid;
  page-break-after: avoid;
}}

img.doc-image {{ max-width: {layout['maxImageWidth']}%; height: auto; }}
p.image-paragraph {{ text-align: center; margin: 0.8em 0; }}
figure.doc-figure {{ margin: 0.9em 0 1.1em; text-align: center; {break_inside} }}
figure.doc-figure img {{ max-width: {layout['maxImageWidth']}%; height: auto; }}
figcaption.figure-caption {{
  margin-top: 0.4em;
  font-family: {body_font};
  font-size: {pt(typo['captionSize'])};
  color: {theme['muted']};
  font-style: italic;
}}

hr {{ border: 0; border-top: 0.7pt solid {theme['border']}; margin: 1.2em 0; }}

/* LaTeX (KaTeX) */
.math-inline {{ white-space: nowrap; color: {theme['text']}; }}
.math-inline .katex {{ font-size: 1.03em; }}
.math-block {{
  margin: 0.95em 0 1.15em;
  text-align: center;
  color: {theme['text']};
  break-inside: avoid;
  page-break-inside: avoid;
}}
.math-block .katex-display {{ margin: 0.25em 0; }}
.math-block .katex {{ font-size: 1.06em; }}
.math-error-inline {{
  font-family: {mono_font};
  font-size: 0.88em;
  color: {theme['text']};
  border-bottom: 0.8pt dotted {theme['muted']};
}}
.math-error-block {{
  text-align: left;
  padding: 0.7em 0.85em;
  border: 0.6pt solid {theme['border']};
  border-radius: 3px;
  background: {theme['codeBg']};
  color: {theme['codeText']};
  font-family: {mono_font};
  font-size: {pt(max(7.0, typo['bodySize'] * 0.86))};
}}
.math-error-source {{ white-space: pre-wrap; color: {theme['codeText']}; background: transparent; border: 0; padding: 0; }}
.math-error-note {{ margin-top: 0.45em; font-family: {body_font}; font-size: {pt(typo['captionSize'])}; color: {theme['muted']}; }}

/* Mermaid */
.mermaid-figure {{
  margin: 1em 0 1.2em;
  text-align: center;
  break-inside: avoid;
  page-break-inside: avoid;
}}
.mermaid-image {{ max-width: 100%; height: auto; }}
.mermaid-error {{
  margin: 0.9em 0;
  padding: 0.7em 0.85em;
  border: 0.6pt solid {theme['border']};
  border-left: 2.5pt solid {theme['link']};
  border-radius: 3px;
  background: {theme['codeBg']};
  color: {theme['codeText']};
  break-inside: avoid;
}}
.mermaid-error-title {{ font-family: {heading_font}; font-size: {pt(typo['captionSize'] + 1)}; font-weight: 700; color: {theme['headings']}; margin-bottom: 0.35em; }}
.mermaid-error-source {{
  margin: 0;
  padding: 0;
  background: transparent;
  border: 0;
  color: {theme['codeText']};
  font-family: {mono_font};
  font-size: {pt(typo['codeSize'])};
  white-space: pre-wrap;
}}
.mermaid-error-note {{ margin-top: 0.45em; font-family: {body_font}; font-size: {pt(typo['captionSize'])}; color: {theme['muted']}; }}

.footnotes {{
  margin-top: 1.4em;
  padding-top: 0.7em;
  border-top: 0.6pt solid {theme['border']};
  font-size: 0.86em;
  color: {theme['muted']};
}}
.footnotes ol {{ padding-left: 1.4em; }}
.footnotes li {{ margin-bottom: 0.4em; }}
.footnote-ref {{ font-size: 0.75em; vertical-align: super; text-decoration: none; }}
.footnote-backref {{ text-decoration: none; margin-left: 0.25em; }}

.page-break {{ break-after: page; page-break-after: always; height: 0; margin: 0; padding: 0; }}

.toc-page {{ break-after: page; page-break-after: always; }}
.toc-title {{ font-size: {pt(typo['h1Size'] * 0.9)}; border-bottom: 1.2pt solid {theme['border']}; }}
.toc ul {{ list-style: none; padding-left: 1.1em; margin: 0.2em 0; }}
.toc > ul {{ padding-left: 0; }}
.toc li {{ margin: 0.28em 0; }}
.toc a {{ color: {theme['text']}; text-decoration: none; }}
.toc a::after {{ content: leader('.') target-counter(attr(href), page); color: {theme['muted']}; }}
.toc-level-1 > a {{ font-weight: 700; color: {theme['headings']}; }}
.toc-level-2 > a {{ font-weight: 600; }}

/* anchors for internal PDF links */
.heading {{ scroll-margin-top: 0; }}

/* Pygments token colours (background overridden above) */
{pygments_css}

.watermark-cover {{ display: none; }}
{watermark_css}
{cover_css}
"""


MARP_SIZES_MM: dict[str, tuple[float, float]] = {
    "16:9": (338.667, 190.5),
    "4:3": (254.0, 190.5),
    "16:10": (304.8, 190.5),
}

MARP_THEMES: dict[str, dict[str, str]] = {
    "default": {
        "bg": "#ffffff",
        "text": "#1f2937",
        "heading": "#1f2937",
        "muted": "#6b7280",
        "accent": "#0288d1",
        "code_bg": "#f5f5f5",
        "code_text": "#24292f",
        "border": "#d1d5db",
    },
    "gaia": {
        "bg": "#ffffff",
        "text": "#222222",
        "heading": "#222222",
        "muted": "#6b7280",
        "accent": "#b45309",
        "code_bg": "#faf7ef",
        "code_text": "#292524",
        "border": "#e7e0d0",
    },
    "uncover": {
        "bg": "#1a1a1a",
        "text": "#e5e5e5",
        "heading": "#ffffff",
        "muted": "#a3a3a3",
        "accent": "#fbbf24",
        "code_bg": "#262626",
        "code_text": "#f5f5f5",
        "border": "#404040",
    },
}


def marp_page_dimensions(size: str) -> tuple[float, float]:
    return MARP_SIZES_MM.get(size, MARP_SIZES_MM["16:9"])


def build_marp_css(size: str, theme: str, settings: dict[str, Any]) -> str:
    """CSS overrides for a Marp-compatible 16:9/4:3 deck."""
    width, height = marp_page_dimensions(size)
    colors = MARP_THEMES.get(theme, MARP_THEMES["default"])
    font = font_stack(settings["typography"]["headingFont"], "sans-serif")
    mono = font_stack(settings["typography"]["monoFont"], "monospace")
    return f"""
/* =====================================================================
   Marp-compatible deck mode ({size}) — one slide per PDF page
   ===================================================================== */
@page {{
  size: {width:g}mm {height:g}mm;
  margin: 0;
  background: {colors['bg']};
  @top-left {{ content: none; }} @top-center {{ content: none; }} @top-right {{ content: none; }}
  @bottom-left {{ content: none; }} @bottom-center {{ content: none; }} @bottom-right {{ content: none; }}
}}

html, body {{
  margin: 0;
  padding: 0;
  background: {colors['bg']};
}}

main.marp-deck {{
  margin: 0;
  padding: 0;
  background: {colors['bg']};
  color: {colors['text']};
  font-family: {font};
  text-align: left;
}}

.marp-slide {{
  position: relative;
  width: 100%;
  height: {height:g}mm;
  box-sizing: border-box;
  padding: 17mm 20mm;
  overflow: hidden;
  background: {colors['bg']};
  color: {colors['text']};
  font-family: {font};
  font-size: 20pt;
  line-height: 1.35;
  text-align: left;
  break-after: page;
  page-break-after: always;
}}

.marp-slide.marp-last {{
  break-after: auto;
  page-break-after: auto;
}}

.marp-slide h1, .marp-slide h2, .marp-slide h3,
.marp-slide h4, .marp-slide h5, .marp-slide h6 {{
  font-family: {font};
  color: {colors['heading']};
  border: 0;
  padding: 0;
  margin: 0 0 0.48em;
  line-height: 1.15;
  break-after: avoid-page;
  page-break-after: avoid;
}}

.marp-slide h1 {{ font-size: 34pt; }}
.marp-slide h2 {{ font-size: 27pt; }}
.marp-slide h3 {{ font-size: 22pt; }}
.marp-slide h4 {{ font-size: 19pt; }}
.marp-slide h5 {{ font-size: 17pt; }}
.marp-slide h6 {{ font-size: 16pt; color: {colors['muted']}; }}

.marp-slide.lead {{
  text-align: center;
  padding-top: 43mm;
}}
.marp-slide.lead h1 {{ font-size: 38pt; }}
.marp-slide.lead p {{ margin-left: auto; margin-right: auto; }}

.marp-slide p {{ margin: 0 0 0.55em; orphans: 2; widows: 2; }}
.marp-slide ul, .marp-slide ol {{ margin: 0.25em 0 0.55em; padding-left: 1.2em; }}
.marp-slide li {{ margin: 0.12em 0; }}
.marp-slide a {{ color: {colors['accent']}; text-decoration: underline; }}
.marp-slide strong {{ color: {colors['accent']}; }}

.marp-slide blockquote {{
  margin: 0.45em 0;
  padding: 0.35em 0.75em;
  border-left: 3pt solid {colors['accent']};
  background: {colors['code_bg']};
  color: {colors['text']};
}}

.marp-slide code {{
  background: {colors['code_bg']};
  color: {colors['code_text']};
  border-color: {colors['border']};
  font-size: 0.82em;
}}
.marp-slide .code-block {{
  margin: 0.35em 0 0.55em;
  background: {colors['code_bg']};
  border-color: {colors['border']};
}}
.marp-slide pre.code-pre,
.marp-slide .code-table .code-gutter pre {{
  font-size: 10.5pt;
  line-height: 1.3;
}}
.marp-slide .code-head {{ color: {colors['muted']}; }}

.marp-slide table.doc-table {{
  font-size: 13pt;
  margin: 0.35em 0 0.55em;
}}
.marp-slide table.doc-table th,
.marp-slide table.doc-table td {{
  padding: 0.3em 0.45em;
  border-color: {colors['border']};
}}
.marp-slide table.doc-table th {{ background: {colors['code_bg']}; color: {colors['heading']}; }}

.marp-slide .mermaid-figure {{
  margin: 0.35em 0 0.55em;
  break-inside: avoid;
}}
.marp-slide .mermaid-image {{
  max-width: 100%;
  max-height: 108mm;
}}
.marp-slide .math-block {{ margin: 0.35em 0 0.55em; color: {colors['text']}; }}
.marp-slide .math-block .katex {{ font-size: 1em; }}
.marp-slide .math-inline, .marp-slide .math-inline .katex {{ color: {colors['text']}; font-size: 1em; }}

.marp-page-number {{
  position: absolute;
  right: 10mm;
  bottom: 6mm;
  font-family: {font};
  font-size: 10pt;
  line-height: 1;
  color: {colors['muted']};
}}

.marp-theme-uncover .marp-page-number {{ color: {colors['muted']}; }}
"""
