"""Server-side rendering for Mermaid diagrams and LaTeX formulas.

Mermaid is rasterised in headless Chromium (transparent PNG at 2×) so the
result is identical in WeasyPrint and in the Chromium fallback.  LaTeX is
converted with KaTeX to HTML/CSS: WeasyPrint renders the native KaTeX layout
with the bundled KaTeX fonts, preserving inline baseline alignment.

Everything runs locally. Results are cached in memory by content + theme.
"""

from __future__ import annotations

import base64
import html
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .config import APP_DIR
from .pdf_engine import chromium_executable, playwright_available

KATEX_DIR = APP_DIR / "static" / "vendor" / "katex"
KATEX_JS = KATEX_DIR / "katex.min.js"
KATEX_CSS = KATEX_DIR / "katex.min.css"
MERMAID_JS = APP_DIR / "static" / "vendor" / "mermaid" / "mermaid.min.js"

_CACHE: "OrderedDict[tuple[Any, ...], dict[str, Any]]" = OrderedDict()
_CACHE_MAX = 200
_CACHE_LOCK = threading.RLock()
_RENDER_LOCK = threading.Lock()

_BLANK_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  html, body { margin: 0; padding: 0; background: transparent; }
  #host { display: inline-block; background: transparent; }
  #host svg { display: block; max-width: none !important; background: transparent !important; }
</style></head><body><div id="host"></div></body></html>"""

_MATH_JS = """(payload) => {
  try {
    const rendered = katex.renderToString(payload.code, {
      displayMode: payload.display,
      throwOnError: true,
      strict: 'ignore',
      trust: false,
      output: 'htmlAndMathml'
    });
    return {ok: true, html: rendered};
  } catch (error) {
    return {ok: false, error: String(error && error.message ? error.message : error)};
  }
}"""

_MERMAID_RENDER_JS = """async (payload) => {
  try {
    const host = document.getElementById('host');
    host.innerHTML = '';
    const {svg} = await mermaid.render(payload.id, payload.code);
    host.innerHTML = svg;
    const element = host.querySelector('svg');
    if (!element) return {ok: false, error: 'SVG non generato'};
    const box = element.viewBox && element.viewBox.baseVal;
    const width = box && box.width ? box.width : 800;
    const height = box && box.height ? box.height : 400;
    element.setAttribute('width', width);
    element.setAttribute('height', height);
    element.style.width = width + 'px';
    element.style.height = height + 'px';
    element.style.maxWidth = 'none';
    element.style.background = 'transparent';
    await document.fonts.ready;
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const rect = host.getBoundingClientRect();
    return {ok: true, width: rect.width, height: rect.height};
  } catch (error) {
    return {ok: false, error: String(error && error.message ? error.message : error)};
  }
}"""

_MERMAID_INIT_JS = """(payload) => {
  mermaid.initialize({
    startOnLoad: false,
    theme: payload.theme,
    securityLevel: 'strict',
    suppressErrorRendering: true,
    fontFamily: payload.font,
    themeVariables: {fontFamily: payload.font},
    flowchart: {htmlLabels: false, useMaxWidth: false, curve: 'basis'},
    sequence: {useMaxWidth: false, wrap: true},
    gantt: {useMaxWidth: false},
    journey: {useMaxWidth: false},
    timeline: {useMaxWidth: false},
    mindmap: {useMaxWidth: false},
  });
}"""


@dataclass
class RichRenderResult:
    math: dict[tuple[str, bool], dict[str, Any]] = field(default_factory=dict)
    mermaid: dict[str, dict[str, Any]] = field(default_factory=dict)
    warnings: list[dict[str, str]] = field(default_factory=list)


def rich_available() -> bool:
    """True when Chromium/Playwright and the bundled JS/CSS are available."""
    return bool(
        KATEX_JS.exists()
        and KATEX_CSS.exists()
        and MERMAID_JS.exists()
        and playwright_available()
        and chromium_executable()
    )


def _is_dark(color: str) -> bool:
    value = (color or "").strip()
    match = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", value)
    if not match:
        return False
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(character * 2 for character in digits)
    red, green, blue = (int(digits[index:index + 2], 16) for index in (0, 2, 4))
    luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255
    return luminance < 0.45


def _cache_get(key: tuple[Any, ...]) -> dict[str, Any] | None:
    with _CACHE_LOCK:
        value = _CACHE.get(key)
        if value is None:
            return None
        _CACHE.move_to_end(key)
        return dict(value)


def _cache_put(key: tuple[Any, ...], value: dict[str, Any]) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = dict(value)
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)


def clear_rich_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _normalise_math(code: str) -> str:
    value = (code or "").strip()
    if value.startswith("$$") and value.endswith("$$") and len(value) >= 4:
        value = value[2:-2]
    elif value.startswith("$") and value.endswith("$") and len(value) >= 2:
        value = value[1:-1]
    return value.strip()


def _error_message(error: str) -> str:
    text = re.sub(r"\s+", " ", str(error or "errore sconosciuto")).strip()
    return text[:300]


def _fallback_math_warning(error: str) -> str:
    return f"Formula LaTeX non valida: {_error_message(error)}"


def render_rich_content(
    math_items: Iterable[tuple[str, bool]],
    mermaid_items: Iterable[str],
    settings: dict[str, Any],
) -> RichRenderResult:
    """Render all math/Mermaid jobs, using the cache where possible."""
    math_jobs = sorted({(_normalise_math(code), bool(display)) for code, display in math_items if _normalise_math(code)})
    mermaid_jobs = sorted({(code or "").strip() for code in mermaid_items if (code or "").strip()})
    result = RichRenderResult()
    if not math_jobs and not mermaid_jobs:
        return result

    theme = settings.get("theme", {})
    mermaid_theme = "dark" if _is_dark(theme.get("background", "#ffffff")) else "default"
    font = str(settings.get("typography", {}).get("bodyFont", "DejaVu Sans")).split(",")[0].strip() or "DejaVu Sans"

    missing_math: list[tuple[str, bool]] = []
    missing_mermaid: list[str] = []
    for code, display in math_jobs:
        cached = _cache_get(("math", code, display))
        if cached is None:
            missing_math.append((code, display))
        else:
            result.math[(code, display)] = cached
    for code in mermaid_jobs:
        cached = _cache_get(("mermaid", code, mermaid_theme, font))
        if cached is None:
            missing_mermaid.append(code)
        else:
            result.mermaid[code] = cached

    if not missing_math and not missing_mermaid:
        return result

    if not rich_available():
        message = (
            "Mermaid e LaTeX richiedono Chromium/Playwright. "
            "Installa Playwright e un browser Chrome/Chromium, oppure usa WeasyPrint per il resto del documento."
        )
        result.warnings.append({"level": "warning", "message": message})
        for code, display in missing_math:
            result.math[(code, display)] = {"ok": False, "error": "Chromium/Playwright non disponibile"}
        for code in missing_mermaid:
            result.mermaid[code] = {"ok": False, "error": "Chromium/Playwright non disponibile"}
        return result

    try:
        math_results, mermaid_results = _render_missing(
            missing_math,
            missing_mermaid,
            mermaid_theme=mermaid_theme,
            font=font,
        )
    except Exception as exc:  # pragma: no cover - environment failure
        message = f"Rendering Mermaid/LaTeX non riuscito: {_error_message(str(exc))}"
        result.warnings.append({"level": "warning", "message": message})
        for code, display in missing_math:
            result.math[(code, display)] = {"ok": False, "error": message}
        for code in missing_mermaid:
            result.mermaid[code] = {"ok": False, "error": message}
        return result

    for key, value in math_results.items():
        result.math[key] = value
        if value.get("ok"):
            _cache_put(("math", key[0], key[1]), value)
        else:
            result.warnings.append({"level": "warning", "message": _fallback_math_warning(value.get("error", ""))})
    for code, value in mermaid_results.items():
        result.mermaid[code] = value
        if value.get("ok"):
            _cache_put(("mermaid", code, mermaid_theme, font), value)
        else:
            result.warnings.append(
                {"level": "warning", "message": f"Diagramma Mermaid non valido: {_error_message(value.get('error', ''))}"}
            )
    return result


def _render_missing(
    math_jobs: list[tuple[str, bool]],
    mermaid_jobs: list[str],
    mermaid_theme: str,
    font: str,
) -> tuple[dict[tuple[str, bool], dict[str, Any]], dict[str, dict[str, Any]]]:
    from playwright.sync_api import sync_playwright

    executable = chromium_executable()
    if not executable:
        raise RuntimeError("Chromium non trovato")

    math_results: dict[tuple[str, bool], dict[str, Any]] = {}
    mermaid_results: dict[str, dict[str, Any]] = {}
    with _RENDER_LOCK:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=executable,
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            try:
                page = browser.new_page(
                    viewport={"width": 1600, "height": 1200},
                    device_scale_factor=2,
                )
                page.set_content(_BLANK_PAGE, wait_until="load")
                if math_jobs:
                    page.add_script_tag(path=str(KATEX_JS))
                if mermaid_jobs:
                    page.add_script_tag(path=str(MERMAID_JS))
                    page.evaluate(_MERMAID_INIT_JS, {"theme": mermaid_theme, "font": font})

                for index, (code, display) in enumerate(math_jobs):
                    outcome = page.evaluate(_MATH_JS, {"code": code, "display": display})
                    math_results[(code, display)] = outcome

                for index, code in enumerate(mermaid_jobs):
                    outcome = page.evaluate(
                        _MERMAID_RENDER_JS,
                        {"code": code, "id": f"md2pdf-mermaid-{index}"},
                    )
                    if outcome.get("ok"):
                        png = page.locator("#host").screenshot(omit_background=True)
                        outcome["data_uri"] = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
                        outcome["width"] = float(outcome.get("width") or 800)
                        outcome["height"] = float(outcome.get("height") or 400)
                    mermaid_results[code] = outcome
            finally:
                browser.close()
    return math_results, mermaid_results


def math_html(code: str, display: bool, results: dict[tuple[str, bool], dict[str, Any]]) -> str:
    """Return the safe HTML (or a readable fallback) for a formula."""
    normalised = _normalise_math(code)
    result = results.get((normalised, bool(display)))
    if result and result.get("ok") and result.get("html"):
        if display:
            return f'<div class="math-block">{result["html"]}</div>\n'
        return f'<span class="math-inline">{result["html"]}</span>'
    error = _error_message(result.get("error", "") if result else "Motore matematico non disponibile")
    if display:
        return (
            '<div class="math-block math-error-block">'
            f'<code class="math-error-source">{html.escape(normalised)}</code>'
            f'<div class="math-error-note">Formula LaTeX non valida: {html.escape(error)}</div>'
            "</div>\n"
        )
    return (
        f'<code class="math-error-inline" title="{html.escape(error, quote=True)}">'
        f"${html.escape(normalised)}$</code>"
    )


def mermaid_html(code: str, results: dict[str, dict[str, Any]]) -> str:
    normalised = (code or "").strip()
    result = results.get(normalised)
    if result and result.get("ok") and result.get("data_uri"):
        width = max(40.0, float(result.get("width") or 800))
        return (
            '<figure class="mermaid-figure">'
            f'<img class="mermaid-image" src="{result["data_uri"]}" alt="Diagramma Mermaid"'
            f' style="width:{width:.1f}px">'
            "</figure>\n"
        )
    error = _error_message(result.get("error", "") if result else "Motore diagrammi non disponibile")
    return (
        '<div class="mermaid-error">'
        '<div class="mermaid-error-title">Diagramma Mermaid non disponibile</div>'
        f'<pre class="mermaid-error-source">{html.escape(normalised)}</pre>'
        f'<div class="mermaid-error-note">{html.escape(error)}</div>'
        "</div>\n"
    )
