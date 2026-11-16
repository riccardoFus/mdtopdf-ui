"""Markdown parsing and HTML rendering for MD → PDF Studio.

The engine is built on markdown-it-py plus the official plugins
(footnotes, task lists, attributes).  It intentionally keeps the output
deterministic so the same HTML/CSS can be rendered by WeasyPrint or by
Chromium (fallback).
"""

from __future__ import annotations

import base64
import copy
import html
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import yaml
from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.attrs import attrs_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin
from pygments import highlight as pygments_highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

from .config import deep_merge, validate_settings
from .rich_rendering import RichRenderResult, math_html, mermaid_html, render_rich_content

FRONTMATTER_RE = re.compile(r"^\ufeff?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", re.DOTALL)
PAGEBREAK_COMMENT_RE = re.compile(r"<!--\s*(?:pagebreak|page-break|newpage)\s*-->", re.IGNORECASE)
PAGEBREAK_LINE_RE = re.compile(r"^\s*\\(?:newpage|pagebreak)\s*$", re.IGNORECASE)
ATTRS_RE = re.compile(r"\s*\{([#.][^}]*)\}\s*$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
CODE_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")


class MarkdownError(ValueError):
    """User-facing Markdown/frontmatter error."""


@dataclass
class Heading:
    level: int
    text: str
    slug: str
    number: str = ""


@dataclass
class RenderedMarkdown:
    body_html: str
    headings: list[Heading]
    warnings: list[dict[str, str]]
    meta: dict[str, Any] = field(default_factory=dict)
    toc_html: str = ""
    has_math: bool = False
    marp: bool = False
    marp_size: str = "16:9"
    marp_theme: str = "default"
    marp_paginate: bool = False


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------

def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Extract YAML frontmatter.  Raises MarkdownError on invalid YAML."""
    if not isinstance(text, str):
        raise MarkdownError("Il documento Markdown deve essere testo.")
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw_yaml = match.group(1)
    # PyYAML follows YAML 1.1 and parses "4:3" as a sexagesimal integer (243).
    # Marp sizes must stay strings.
    raw_yaml = re.sub(
        r"(?m)^(\s*size\s*:\s*)(\d+:\d+)(\s*)$",
        r'\1"\2"\3',
        raw_yaml,
    )
    try:
        data = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        problem = getattr(exc, "problem", None) or "sintassi non valida"
        mark = getattr(exc, "problem_mark", None)
        position = f" (riga {mark.line + 1}, colonna {mark.column + 1})" if mark else ""
        raise MarkdownError(f"YAML frontmatter non valido{position}: {problem}.") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise MarkdownError("Il frontmatter YAML deve essere una mappa chiave/valore.")
    clean: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, (date, datetime)):
            value = value.isoformat()
        clean[str(key)] = value
    return clean, text[match.end():]


def apply_frontmatter(settings: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    """Merge supported frontmatter keys into settings (validated afterwards)."""
    out = deep_merge(settings, {})
    doc = out["document"]
    aliases = {
        "toc": "toc",
        "tocDepth": "tocDepth",
        "toc_depth": "tocDepth",
        "tocTitle": "tocTitle",
        "toc_title": "tocTitle",
        "numberHeadings": "numberHeadings",
        "number_headings": "numberHeadings",
    }
    for key in ("title", "subtitle", "author", "date", "lang"):
        if key in meta and meta[key] is not None and not isinstance(meta[key], (dict, list)):
            doc[key] = meta[key]
    for source, target in aliases.items():
        if source in meta and meta[source] is not None:
            doc[target] = meta[source]

    header = meta.get("header")
    footer = meta.get("footer")
    if isinstance(header, str):
        out["headerFooter"]["headerLeft"] = ""
        out["headerFooter"]["headerCenter"] = header
        out["headerFooter"]["headerRight"] = ""
    elif isinstance(header, dict):
        for slot in ("headerLeft", "headerCenter", "headerRight"):
            if slot in header:
                out["headerFooter"][slot] = header[slot]
            elif slot.replace("header", "left") in header:  # e.g. {"left": "..."}
                out["headerFooter"][slot] = header[slot.replace("header", "left")]
    if isinstance(footer, str):
        out["headerFooter"]["footerLeft"] = ""
        out["headerFooter"]["footerCenter"] = footer
        out["headerFooter"]["footerRight"] = ""
    elif isinstance(footer, dict):
        for slot in ("footerLeft", "footerCenter", "footerRight"):
            if slot in footer:
                out["headerFooter"][slot] = footer[slot]
            elif slot.replace("footer", "").lower() in footer:
                out["headerFooter"][slot] = footer[slot.replace("footer", "").lower()]
    return validate_settings(out)


# ---------------------------------------------------------------------------
# Page breaks
# ---------------------------------------------------------------------------

def inject_pagebreaks(text: str) -> str:
    """Replace explicit page-break markers outside fenced code blocks."""
    lines = text.splitlines()
    output: list[str] = []
    fence: str | None = None
    for line in lines:
        fence_match = CODE_FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)[0] * 3
            if fence is None:
                fence = marker
            elif line.strip().startswith(fence):
                fence = None
            output.append(line)
            continue
        if fence is None:
            if PAGEBREAK_LINE_RE.match(line):
                output.append('\n<div class="page-break" aria-hidden="true"></div>\n')
                continue
            line = PAGEBREAK_COMMENT_RE.sub('\n<div class="page-break" aria-hidden="true"></div>\n', line)
        output.append(line)
    return "\n".join(output)


def _transform_outside_inline_code(line: str, transform) -> str:
    parts = re.split(r"(`+[^`\n]*?`+)", line)
    for index in range(0, len(parts), 2):
        if parts[index] and not parts[index].startswith("`"):
            parts[index] = transform(parts[index])
    return "".join(parts)


def normalize_latex_delimiters(text: str) -> str:
    """Support \\(...\\) and \\[...\\] in addition to $...$ and $$...$$.

    Delimiter replacement is skipped inside fenced code and inline code spans.
    """
    lines = text.splitlines()
    output: list[str] = []
    fence: str | None = None
    in_display = False
    buffer: list[str] = []

    for line in lines:
        fence_match = CODE_FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)[0] * 3
            if fence is None:
                fence = marker
            elif line.strip().startswith(fence):
                fence = None
            output.append(line)
            continue
        if fence is not None:
            output.append(line)
            continue

        if in_display:
            if r"\]" in line:
                before, after = line.split(r"\]", 1)
                buffer.append(before)
                content = "\n".join(buffer).strip("\n")
                output.append("$$\n" + content + "\n$$")
                buffer = []
                in_display = False
                if after.strip():
                    output.append(after)
            else:
                buffer.append(line)
            continue

        if r"\[" in line and r"\]" not in line and line.count("`") % 2 == 0:
            before, after = line.split(r"\[", 1)
            output.append(before)
            buffer = [after]
            in_display = True
            continue

        def transform(segment: str) -> str:
            segment = re.sub(
                r"(?<!\\)\\\[(.+?)\\\]",
                lambda match: "\n$$\n" + match.group(1) + "\n$$\n",
                segment,
            )
            segment = re.sub(
                r"(?<!\\)\\\((.+?)\\\)",
                lambda match: "$" + match.group(1) + "$",
                segment,
            )
            return segment

        output.append(_transform_outside_inline_code(line, transform))

    if in_display:
        output.append("$$\n" + "\n".join(buffer).strip("\n") + "\n$$")
    return "\n".join(output) + ("\n" if text.endswith("\n") else "")


# ---------------------------------------------------------------------------
# Marp deck support
# ---------------------------------------------------------------------------

MARP_SLIDE_SEPARATOR_RE = re.compile(r"^\s*-{3,}\s*$")
MARP_DIRECTIVE_RE = re.compile(
    r"<!--\s*(_?(?:class|paginate|backgroundColor|color|header|footer))\s*:\s*([^>]*?)\s*-->",
    re.IGNORECASE | re.DOTALL,
)
MARP_COLOR_RE = re.compile(
    r"^(#[0-9a-fA-F]{3,8}|rgba?\([\d\s.,%/]+\)|hsla?\([\d\s.,%/]+\)|[a-zA-Z]{2,24})$"
)
MARP_CLASS_RE = re.compile(r"^[\w-]{1,60}$", re.UNICODE)


def _marp_truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "on")


def _safe_marp_color(value: str) -> str:
    value = (value or "").strip()
    return value if MARP_COLOR_RE.match(value) else ""


def split_marp_slides(text: str) -> list[str]:
    """Split a Marp deck on top-level ``---`` lines (not inside code fences)."""
    slides: list[str] = []
    current: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        fence_match = CODE_FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)[0] * 3
            if fence is None:
                fence = marker
            elif line.strip().startswith(fence):
                fence = None
            current.append(line)
            continue
        if fence is None and MARP_SLIDE_SEPARATOR_RE.match(line):
            slides.append("\n".join(current))
            current = []
            continue
        current.append(line)
    slides.append("\n".join(current))
    return [slide.strip("\n") for slide in slides if slide.strip()]


def extract_marp_directives(text: str) -> tuple[dict[str, str], str]:
    """Remove per-slide Marp directives and return them as a dictionary."""
    directives: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        canonical = {
            "_class": "_class",
            "_paginate": "_paginate",
            "_backgroundcolor": "_backgroundColor",
            "_color": "_color",
            "_header": "_header",
            "_footer": "_footer",
            "class": "class",
            "paginate": "paginate",
            "backgroundcolor": "backgroundColor",
            "color": "color",
            "header": "header",
            "footer": "footer",
        }.get(key.lower(), key)
        directives[canonical] = match.group(2).strip()
        return ""

    clean = MARP_DIRECTIVE_RE.sub(replace, text)
    return directives, clean.strip("\n")


def _marp_classes(value: str) -> list[str]:
    classes = []
    for item in re.split(r"\s+", value or ""):
        if item and MARP_CLASS_RE.match(item):
            classes.append(item)
    return classes


def _marp_theme_name(meta: dict[str, Any]) -> str:
    theme = str(meta.get("theme") or "default").strip().lower()
    if not MARP_CLASS_RE.match(theme):
        return "default"
    return theme


def _marp_size_name(meta: dict[str, Any]) -> str:
    size = str(meta.get("size") or "16:9").strip()
    if size in ("16:9", "4:3", "16:10"):
        return size
    return "16:9"


def collect_rich_jobs(
    text: str,
    settings: dict[str, Any],
    base_dir: Path | None = None,
    document_name: str = "documento",
) -> tuple[set[tuple[str, bool]], set[str]]:
    """Collect math/Mermaid jobs from a slide without rendering them."""
    engine = _Engine(settings, base_dir, [], document_name)
    prepared = normalize_latex_delimiters(inject_pagebreaks(text))
    tokens = engine.md.parse(prepared, {})
    math_jobs: set[tuple[str, bool]] = set()
    mermaid_jobs: set[str] = set()
    for token in _walk_tokens(tokens):
        if token.type == "math_inline":
            math_jobs.add((token.content.strip(), False))
        elif token.type == "math_block":
            math_jobs.add((token.content.strip(), True))
        elif token.type == "fence":
            info = (token.info or "").strip().split()
            language = info[0].lower() if info else ""
            if language in ("mermaid", "mmd"):
                mermaid_jobs.add((token.content or "").strip())
    return math_jobs, mermaid_jobs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    """GitHub-flavoured anchor slug that keeps unicode letters (Italian accents)."""
    value = unicodedata.normalize("NFKC", text or "").strip().lower()
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"[^\w\s\-]", "", value, flags=re.UNICODE)
    value = re.sub(r"[\s]+", "-", value)
    value = re.sub(r"-{2,}", "-", value)
    return value.strip("-") or "sezione"


def _unique_slug(text: str, env: dict[str, Any]) -> str:
    used: dict[str, int] = env.setdefault("slugs", {})
    base = slugify(text)
    slug = base
    if slug in used:
        used[base] += 1
        slug = f"{base}-{used[base]}"
    else:
        used[base] = 0
    return slug


def _inline_text(children: list[Any] | None) -> str:
    if not children:
        return ""
    parts: list[str] = []
    for child in children:
        if child.type in ("text", "code_inline", "math_inline"):
            parts.append(child.content)
        elif child.type == "image":
            parts.append(child.content or "immagine")
        elif child.type in ("softbreak", "hardbreak"):
            parts.append(" ")
        elif getattr(child, "children", None):
            parts.append(_inline_text(child.children))
    return "".join(parts).strip()


def _walk_tokens(tokens: list[Any]) -> Any:
    for token in tokens:
        yield token
        children = getattr(token, "children", None)
        if children:
            yield from _walk_tokens(children)


def _attr(tag: str, name: str) -> str:
    match = re.search(rf'\b{name}="([^"]*)"', tag, re.IGNORECASE)
    return html.unescape(match.group(1)) if match else ""


def _placeholder_image(message: str) -> str:
    label = html.escape(message[:80])
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="900" height="220" viewBox="0 0 900 220">
<rect width="900" height="220" fill="#f8fafc" stroke="#cbd5e0" stroke-width="2" stroke-dasharray="10 8"/>
<text x="450" y="100" font-family="DejaVu Sans, sans-serif" font-size="22" fill="#64748b" text-anchor="middle">Immagine non disponibile</text>
<text x="450" y="140" font-family="DejaVu Sans Mono, monospace" font-size="15" fill="#94a3b8" text-anchor="middle">{label}</text>
</svg>"""
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _resolve_image(src: str, base_dir: Path | None, warnings: list[dict[str, str]]) -> str:
    src = (src or "").strip()
    if not src:
        warnings.append({"level": "warning", "message": "Immagine senza percorso (src vuoto)."})
        return _placeholder_image("src vuoto")
    lowered = src.lower()
    if lowered.startswith(("data:", "http://", "https://")):
        return src
    if lowered.startswith("file://"):
        parsed = Path(unquote(urlparse(src).path))
        if parsed.exists():
            return parsed.as_uri()
        warnings.append({"level": "warning", "message": f"Immagine non trovata: {parsed}"})
        return _placeholder_image(str(parsed))

    candidate = Path(src).expanduser()
    if not candidate.is_absolute():
        if base_dir is None:
            warnings.append(
                {
                    "level": "warning",
                    "message": f"Immagine relativa senza cartella di base: {src}",
                }
            )
            return _placeholder_image(src)
        candidate = base_dir / candidate
    try:
        candidate = candidate.resolve()
    except OSError:
        pass
    if candidate.exists() and candidate.is_file():
        return candidate.as_uri()
    warnings.append({"level": "warning", "message": f"Immagine non trovata: {candidate}"})
    return _placeholder_image(str(candidate))


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

class _Engine:
    def __init__(
        self,
        settings: dict[str, Any],
        base_dir: Path | None,
        warnings: list[dict[str, str]],
        document_name: str,
        rich_results: RichRenderResult | None = None,
    ) -> None:
        self.settings = settings
        self.base_dir = base_dir
        self.warnings = warnings
        self.document_name = document_name
        self.rich_results = rich_results
        self.env: dict[str, Any] = {"headings": [], "slugs": {}, "counters": [0] * 6, "tables": 0, "figures": 0}
        self.math_results: dict[tuple[str, bool], dict[str, Any]] = {}
        self.mermaid_results: dict[str, dict[str, Any]] = {}
        self.has_math = False
        self.md = MarkdownIt(
            "commonmark",
            {
                "html": True,
                "linkify": True,
                "typographer": True,
                "breaks": False,
                "highlight": None,
            },
        )
        self.md.enable("table")
        self.md.enable("strikethrough")
        self.md.use(footnote_plugin)
        self.md.use(tasklists_plugin, enabled=True)
        self.md.use(attrs_plugin, allowed=["id", "class", "title"])
        self.md.use(dollarmath_plugin, allow_space=False, allow_digits=False)

        engine = self

        def heading_open(renderer, tokens: list[Any], idx: int, options: Any, env: dict[str, Any]) -> str:
            token = tokens[idx]
            level = int(token.tag[1])
            inline = tokens[idx + 1] if idx + 1 < len(tokens) else None
            text = _inline_text(inline.children if inline else None)

            explicit_id = ""
            attr_match = ATTRS_RE.search(text)
            if attr_match:
                spec = attr_match.group(1)
                id_match = re.search(r"#([\w\-:.\u00C0-\uFFFF]+)", spec)
                if id_match:
                    explicit_id = id_match.group(1)
                text = ATTRS_RE.sub("", text).strip()
                if inline and inline.children:
                    for child in reversed(inline.children):
                        if child.type == "text":
                            child.content = ATTRS_RE.sub("", child.content).rstrip()
                            break

            counters: list[int] = env["counters"]
            counters[level - 1] += 1
            for deeper in range(level, 6):
                counters[deeper] = 0
            number = ""
            if engine.settings["document"]["numberHeadings"]:
                visible = [str(value) for value in counters[:level] if value > 0]
                number = ".".join(visible)

            slug = explicit_id or _unique_slug(text or f"sezione-{len(env['headings']) + 1}", env)
            if explicit_id:
                env["slugs"][slug] = 0
            env["headings"].append(Heading(level=level, text=text, slug=slug, number=number))
            if number and inline is not None and inline.children:
                number_token = Token("html_inline", "", 0)
                number_token.content = f'<span class="hnum">{html.escape(number)}.</span> '
                inline.children.insert(0, number_token)
            return f'<{token.tag} id="{html.escape(slug, quote=True)}" class="heading heading-{level}">'

        def heading_close(renderer, tokens: list[Any], idx: int, options: Any, env: dict[str, Any]) -> str:
            return f"</{tokens[idx].tag}>\n"

        def fence(renderer, tokens: list[Any], idx: int, options: Any, env: dict[str, Any]) -> str:
            token = tokens[idx]
            info = (token.info or "").strip()
            parts = info.split()
            lang = parts[0] if parts else ""
            if lang.startswith("{."):
                lang = lang[2:].rstrip("}")
            flags = {part.strip("{}.").lower() for part in parts[1:]}
            code = token.content or ""
            if code.endswith("\n"):
                code = code[:-1]
            if lang.lower() in ("mermaid", "mmd"):
                return mermaid_html(code.strip(), engine.mermaid_results)
            line_numbers = bool(engine.settings["typography"]["codeLineNumbers"]) or bool(
                flags & {"linenums", "linenos", "line-numbers", "numbered"}
            )

            highlighted = html.escape(code)
            if lang:
                try:
                    lexer = get_lexer_by_name(lang, stripall=False)
                    highlighted = pygments_highlight(code, lexer, HtmlFormatter(nowrap=True))
                except ClassNotFound:
                    pass

            lang_label = html.escape(lang)
            head = f'<div class="code-head"><span class="code-lang">{lang_label}</span></div>' if lang else ""
            css_extra = " has-line-numbers" if line_numbers else ""
            classes = f"code-block{css_extra}"
            if line_numbers:
                lines = code.count("\n") + 1
                gutter = "\n".join(str(number) for number in range(1, lines + 1))
                return (
                    f'<div class="{classes}">{head}'
                    '<table class="code-table"><tbody><tr>'
                    f'<td class="code-gutter"><pre>{gutter}</pre></td>'
                    f'<td class="code-line-cell"><pre class="code-pre"><code class="language-{lang_label}">{highlighted}</code></pre></td>'
                    "</tr></tbody></table></div>\n"
                )
            return (
                f'<div class="{classes}">{head}'
                f'<pre class="code-pre"><code class="language-{lang_label}">{highlighted}</code></pre>'
                "</div>\n"
            )

        def image(renderer, tokens: list[Any], idx: int, options: Any, env: dict[str, Any]) -> str:
            token = tokens[idx]
            src = token.attrGet("src") or ""
            alt = token.content or ""
            title = token.attrGet("title") or ""
            resolved = _resolve_image(src, engine.base_dir, engine.warnings)
            return (
                f'<img src="{html.escape(resolved, quote=True)}" alt="{html.escape(alt, quote=True)}"'
                + (f' title="{html.escape(title, quote=True)}"' if title else "")
                + ' class="doc-image" data-title="'
                + html.escape(title, quote=True)
                + '">'
            )

        def math_inline(renderer, tokens: list[Any], idx: int, options: Any, env: dict[str, Any]) -> str:
            return math_html(tokens[idx].content, False, engine.math_results)

        def math_block(renderer, tokens: list[Any], idx: int, options: Any, env: dict[str, Any]) -> str:
            return math_html(tokens[idx].content, True, engine.math_results)

        def table_open(renderer, tokens: list[Any], idx: int, options: Any, env: dict[str, Any]) -> str:
            env["tables"] += 1
            caption = ""
            if engine.settings["document"]["numberTables"]:
                caption = f'<caption class="table-caption">Tabella {env["tables"]}</caption>'
            return f'<table class="doc-table">{caption}'

        def table_close(renderer, tokens: list[Any], idx: int, options: Any, env: dict[str, Any]) -> str:
            return "</table>\n"

        self.md.add_render_rule("heading_open", heading_open)
        self.md.add_render_rule("heading_close", heading_close)
        self.md.add_render_rule("fence", fence)
        self.md.add_render_rule("image", image)
        self.md.add_render_rule("math_inline", math_inline)
        self.md.add_render_rule("math_block", math_block)
        self.md.add_render_rule("table_open", table_open)
        self.md.add_render_rule("table_close", table_close)

    def _figures(self, body: str) -> str:
        show_captions = bool(self.settings["document"]["figureCaptions"])
        number_figures = bool(self.settings["document"]["numberFigures"])
        counter = {"n": 0}

        def repl(match: re.Match[str]) -> str:
            tag = match.group(1)
            alt = _attr(tag, "alt")
            title = _attr(tag, "title") or _attr(tag, "data-title")
            caption = title or alt
            parts: list[str] = []
            if number_figures:
                counter["n"] += 1
                parts.append(f"Figura {counter['n']}")
            if show_captions and caption:
                parts.append(caption)
            if not parts:
                return f'<p class="image-paragraph">{tag}</p>'
            return (
                f'<figure class="doc-figure">{tag}'
                f'<figcaption class="figure-caption">{html.escape(" — ".join(parts))}</figcaption></figure>'
            )

        return re.sub(r"<p>\s*(<img\b[^>]*class=\"doc-image\"[^>]*>)\s*</p>", repl, body)

    def _task_checkboxes(self, body: str) -> str:
        def repl(match: re.Match[str]) -> str:
            tag = match.group(0)
            checked = " checked" in tag or 'checked=""' in tag
            return (
                '<span class="task-checkbox'
                + (" is-checked" if checked else "")
                + '" aria-hidden="true">'
                + ("✓" if checked else "")
                + "</span>"
            )

        body = re.sub(r'<input[^>]*type="checkbox"[^>]*>', repl, body, flags=re.IGNORECASE)
        return body

    def render(self, text: str) -> RenderedMarkdown:
        prepared = normalize_latex_delimiters(inject_pagebreaks(text))
        tokens = self.md.parse(prepared, self.env)

        math_jobs: set[tuple[str, bool]] = set()
        mermaid_jobs: set[str] = set()
        for token in _walk_tokens(tokens):
            if token.type == "math_inline":
                math_jobs.add((token.content.strip(), False))
            elif token.type == "math_block":
                math_jobs.add((token.content.strip(), True))
            elif token.type == "fence":
                info = (token.info or "").strip().split()
                language = info[0].lower() if info else ""
                if language in ("mermaid", "mmd"):
                    mermaid_jobs.add((token.content or "").strip())
        self.has_math = bool(math_jobs)

        if math_jobs or mermaid_jobs:
            if self.rich_results is not None:
                self.math_results = self.rich_results.math
                self.mermaid_results = self.rich_results.mermaid
            else:
                rich = render_rich_content(math_jobs, mermaid_jobs, self.settings)
                self.math_results = rich.math
                self.mermaid_results = rich.mermaid
                self.warnings.extend(rich.warnings)

        body = self.md.renderer.render(tokens, self.md.options, self.env)
        body = self._figures(body)
        body = self._task_checkboxes(body)
        headings: list[Heading] = self.env["headings"]
        toc_html = build_toc(headings, self.settings) if self.settings["document"]["toc"] else ""
        return RenderedMarkdown(
            body_html=body,
            headings=headings,
            warnings=self.warnings,
            meta={},
            toc_html=toc_html,
            has_math=self.has_math,
        )


def parse_markdown(
    text: str,
    settings: dict[str, Any],
    base_dir: Path | str | None = None,
    document_name: str = "documento",
    warnings: list[dict[str, str]] | None = None,
    rich_results: RichRenderResult | None = None,
) -> RenderedMarkdown:
    """Render Markdown body (without frontmatter) to HTML."""
    if text is None or not str(text).strip():
        raise MarkdownError("Il documento Markdown è vuoto.")
    settings = validate_settings(settings)
    if base_dir is not None:
        base_dir = Path(base_dir).expanduser().resolve()
        if not base_dir.is_dir():
            raise MarkdownError(f"Cartella di base non valida: {base_dir}")
    collected = list(warnings or [])
    engine = _Engine(
        settings,
        Path(base_dir) if base_dir else None,
        collected,
        document_name,
        rich_results=rich_results,
    )
    return engine.render(text)


def parse_marp_deck(
    text: str,
    settings: dict[str, Any],
    meta: dict[str, Any],
    base_dir: Path | str | None = None,
    document_name: str = "documento",
) -> RenderedMarkdown:
    """Render a Marp deck: one section (one PDF page) per slide."""
    if text is None or not str(text).strip():
        raise MarkdownError("La presentazione Marp è vuota.")
    settings = validate_settings(settings)
    slide_settings = copy.deepcopy(settings)
    slide_settings["document"].update(
        {
            "toc": False,
            "numberHeadings": False,
            "numberTables": False,
            "numberFigures": False,
            "numberPages": False,
        }
    )

    slides: list[tuple[str, dict[str, str]]] = []
    for raw in split_marp_slides(text):
        directives, content = extract_marp_directives(raw)
        if content.strip():
            slides.append((content, directives))
    if not slides:
        raise MarkdownError("La presentazione Marp non contiene slide.")

    resolved_base: Path | None = None
    if base_dir is not None:
        resolved_base = Path(base_dir).expanduser().resolve()
        if not resolved_base.is_dir():
            raise MarkdownError(f"Cartella di base non valida: {resolved_base}")

    theme = _marp_theme_name(meta)
    # Mermaid picks its dark/light theme from the page background.
    if theme == "uncover":
        slide_settings["theme"]["background"] = "#1a1a1a"
        slide_settings["theme"]["text"] = "#e5e5e5"
        slide_settings["theme"]["muted"] = "#a3a3a3"
    else:
        slide_settings["theme"]["background"] = "#ffffff"
        slide_settings["theme"]["text"] = "#1f2937"
        slide_settings["theme"]["muted"] = "#6b7280"

    all_math: set[tuple[str, bool]] = set()
    all_mermaid: set[str] = set()
    for content, _directives in slides:
        math_jobs, mermaid_jobs = collect_rich_jobs(
            content, slide_settings, resolved_base, document_name
        )
        all_math |= math_jobs
        all_mermaid |= mermaid_jobs

    rich = (
        render_rich_content(all_math, all_mermaid, slide_settings)
        if all_math or all_mermaid
        else RichRenderResult()
    )
    warnings = list(rich.warnings)
    deck_paginate = _marp_truthy(meta.get("paginate"), False)
    sections: list[str] = []
    headings: list[Heading] = []
    has_math = False

    for index, (content, directives) in enumerate(slides, start=1):
        rendered = parse_markdown(
            content,
            slide_settings,
            base_dir=resolved_base,
            document_name=document_name,
            warnings=[],
            rich_results=rich,
        )
        warnings.extend(rendered.warnings)
        headings.extend(rendered.headings)
        has_math = has_math or rendered.has_math

        classes = ["marp-slide", f"marp-theme-{theme}"]
        classes.extend(_marp_classes(directives.get("_class", directives.get("class", ""))))
        if index == len(slides):
            classes.append("marp-last")

        paginate = deck_paginate
        if "_paginate" in directives or "paginate" in directives:
            paginate = _marp_truthy(directives.get("_paginate", directives.get("paginate")))
        page_number = (
            f'<div class="marp-page-number">{index}</div>' if paginate else ""
        )

        background = _safe_marp_color(
            directives.get("_backgroundColor", directives.get("backgroundColor", ""))
        )
        color = _safe_marp_color(directives.get("_color", directives.get("color", "")))
        style = ""
        if background:
            style += f"background-color: {background}; "
        if color:
            style += f"color: {color}; "

        sections.append(
            f'<section class="{" ".join(dict.fromkeys(classes))}"'
            + (f' style="{html.escape(style, quote=True)}"' if style else "")
            + ">\n"
            + rendered.body_html
            + (f"\n{page_number}" if page_number else "")
            + "\n</section>"
        )

    return RenderedMarkdown(
        body_html="\n".join(sections),
        headings=headings,
        warnings=warnings,
        toc_html="",
        has_math=has_math,
        marp=True,
        marp_size=_marp_size_name(meta),
        marp_theme=theme,
        marp_paginate=deck_paginate,
    )


# ---------------------------------------------------------------------------
# TOC
# ---------------------------------------------------------------------------

@dataclass
class _TocNode:
    heading: Heading
    children: list["_TocNode"]


def _toc_tree(headings: list[Heading], depth: int) -> list[_TocNode]:
    roots: list[_TocNode] = []
    stack: list[tuple[int, list[_TocNode]]] = [(0, roots)]
    for heading in headings:
        if heading.level > depth:
            continue
        while len(stack) > 1 and stack[-1][0] >= heading.level:
            stack.pop()
        node = _TocNode(heading=heading, children=[])
        stack[-1][1].append(node)
        stack.append((heading.level, node.children))
    return roots


def _render_toc_nodes(nodes: list[_TocNode]) -> str:
    if not nodes:
        return ""
    out = ["<ul>"]
    for node in nodes:
        label = f'{html.escape(node.heading.number)}. ' if node.heading.number else ""
        out.append(
            f'<li class="toc-level-{node.heading.level}">'
            f'<a href="#{html.escape(node.heading.slug, quote=True)}">{label}{html.escape(node.heading.text)}</a>'
        )
        out.append(_render_toc_nodes(node.children))
        out.append("</li>")
    out.append("</ul>")
    return "".join(out)


def build_toc(headings: list[Heading], settings: dict[str, Any]) -> str:
    depth = int(settings["document"]["tocDepth"])
    tree = _toc_tree(headings, depth)
    if not tree:
        return ""
    title = html.escape(settings["document"]["tocTitle"] or "Indice")
    return (
        '<section class="toc-page">'
        f'<h1 class="toc-title">{title}</h1>'
        f'<nav class="toc" aria-label="{title}">{_render_toc_nodes(tree)}</nav>'
        "</section>"
    )
