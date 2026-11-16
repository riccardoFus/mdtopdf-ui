"""PDF engines: WeasyPrint (primary) with a Chromium/Playwright fallback."""

from __future__ import annotations

import io
import logging
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

from pypdf import PdfReader

try:  # pragma: no cover - availability depends on system libraries
    from weasyprint import HTML as WeasyHTML

    WEASYPRINT_AVAILABLE = True
    WEASYPRINT_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover
    WeasyHTML = None  # type: ignore[assignment]
    WEASYPRINT_AVAILABLE = False
    WEASYPRINT_IMPORT_ERROR = str(exc)

# WeasyPrint >= 70 exposes URLFetcher; older releases expose default_url_fetcher.
try:  # pragma: no cover
    from weasyprint.urls import URLFetcher
except Exception:  # pragma: no cover
    URLFetcher = None  # type: ignore[assignment]

try:  # pragma: no cover
    from weasyprint import default_url_fetcher
except Exception:  # pragma: no cover
    default_url_fetcher = None  # type: ignore[assignment]

_RENDER_LOCK = threading.Lock()


class PdfError(RuntimeError):
    """Raised when no PDF engine can produce a document."""


class _CollectHandler(logging.Handler):
    def __init__(self, sink: list[str]) -> None:
        super().__init__(level=logging.WARNING)
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:
            return
        if not message:
            return
        # WeasyPrint emits verbose "Ignored ..." notices for unsupported CSS.
        # Keep actionable diagnostics only.
        if message.startswith("Ignored `"):
            return
        if "does not support" in message and "Ignored" in message:
            return
        self.sink.append(message)


def weasyprint_available() -> bool:
    return WEASYPRINT_AVAILABLE


def chromium_executable() -> str | None:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return None


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
    except Exception:
        return False
    return chromium_executable() is not None


def engine_status() -> dict[str, Any]:
    return {
        "weasyprint": WEASYPRINT_AVAILABLE,
        "chromium": playwright_available(),
        "active": "weasyprint" if WEASYPRINT_AVAILABLE else ("chromium" if playwright_available() else "none"),
        "weasyprintError": WEASYPRINT_IMPORT_ERROR,
    }


def page_count(pdf_bytes: bytes) -> int:
    try:
        return len(PdfReader(io.BytesIO(pdf_bytes)).pages)
    except Exception:
        try:
            import pymupdf

            with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
                return doc.page_count
        except Exception:
            return 0


def _placeholder_fetcher(url: str, warnings: list[str]):  # pragma: no cover - network path
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="180">'
        '<rect width="800" height="180" fill="#f8fafc" stroke="#cbd5e0" stroke-dasharray="8 6"/>'
        '<text x="400" y="95" font-family="sans-serif" font-size="18" fill="#64748b" '
        'text-anchor="middle">Risorsa remota non raggiungibile</text></svg>'
    )
    return {
        "string": svg.encode("utf-8"),
        "mime_type": "image/svg+xml",
        "redirected_url": url,
    }


def _weasyprint_pdf(
    html: str,
    base_url: str,
    warnings: list[dict[str, str]],
) -> bytes:
    assert WeasyHTML is not None
    messages: list[str] = []
    handler = _CollectHandler(messages)
    loggers = [logging.getLogger("weasyprint"), logging.getLogger("weasyprint.progress")]
    for logger in loggers:
        logger.addHandler(handler)

    def _make_fetcher():
        if URLFetcher is not None:
            return URLFetcher(timeout=10)
        if default_url_fetcher is not None:
            def legacy_fetcher(url: str, *args: Any, **kwargs: Any):
                try:
                    return default_url_fetcher(url, timeout=10)  # type: ignore[misc]
                except Exception as exc:
                    warnings.append({"level": "warning", "message": f"Impossibile caricare {url}: {exc}"})
                    return _placeholder_fetcher(url, warnings)

            return legacy_fetcher
        return None

    fetcher = _make_fetcher()
    kwargs: dict[str, Any] = {"string": html, "base_url": base_url}
    if fetcher is not None:
        kwargs["url_fetcher"] = fetcher

    try:
        with _RENDER_LOCK:
            document = WeasyHTML(**kwargs)
            pdf = document.write_pdf()
    finally:
        for logger in loggers:
            logger.removeHandler(handler)

    for message in messages:
        lowered = message.lower()
        if any(term in lowered for term in ("failed", "error", "not found", "unable", "cannot")):
            warnings.append({"level": "warning", "message": f"WeasyPrint: {message}"})
    if not pdf:
        raise PdfError("WeasyPrint non ha prodotto alcun PDF.")
    return bytes(pdf)


def _chromium_pdf(html: str, settings: dict[str, Any], warnings: list[dict[str, str]]) -> bytes:
    executable = chromium_executable()
    if not executable:
        raise PdfError(
            "Chromium non trovato. Installa Google Chrome/Chromium oppure abilita WeasyPrint."
        )
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover
        raise PdfError(
            "Il fallback Chromium richiede Playwright: esegui `pip install playwright`."
        ) from exc

    warnings.append(
        {
            "level": "info",
            "message": "Conversione eseguita con il fallback Chromium: header/footer CSS possono differire.",
        }
    )
    try:  # pragma: no cover - only used when WeasyPrint is unavailable
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=executable,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = browser.new_page()
            with tempfile.TemporaryDirectory(prefix="md2pdf-chromium-") as temporary:
                document_path = Path(temporary) / "document.html"
                document_path.write_text(html, encoding="utf-8")
                page.goto(document_path.as_uri(), wait_until="load", timeout=30_000)
                page.emulate_media(media="print")
                try:
                    page.evaluate("document.fonts.ready")
                except Exception:
                    pass
                page.wait_for_timeout(150)
                pdf = page.pdf(
                    print_background=True,
                    prefer_css_page_size=True,
                    display_header_footer=False,
                )
            browser.close()
    except PdfError:
        raise
    except Exception as exc:
        raise PdfError(f"Fallback Chromium non riuscito: {exc}") from exc
    if not pdf:
        raise PdfError("Chromium non ha prodotto alcun PDF.")
    return bytes(pdf)


def render_pdf(
    html: str,
    settings: dict[str, Any],
    base_url: str,
    warnings: list[dict[str, str]] | None = None,
) -> tuple[bytes, str, list[dict[str, str]]]:
    """Render HTML to PDF. Returns (pdf_bytes, engine_name, warnings)."""
    collected = list(warnings or [])
    requested = settings.get("pdf", {}).get("engine", "auto")
    candidates: list[str]
    if requested == "weasyprint":
        candidates = ["weasyprint"]
    elif requested == "chromium":
        candidates = ["chromium"]
    else:
        candidates = ["weasyprint", "chromium"]

    errors: list[str] = []
    for candidate in candidates:
        try:
            if candidate == "weasyprint":
                if not WEASYPRINT_AVAILABLE:
                    errors.append(f"WeasyPrint non disponibile: {WEASYPRINT_IMPORT_ERROR}")
                    continue
                pdf = _weasyprint_pdf(html, base_url, collected)
                return pdf, "weasyprint", collected
            if candidate == "chromium":
                pdf = _chromium_pdf(html, settings, collected)
                return pdf, "chromium", collected
        except Exception as exc:
            errors.append(f"{candidate}: {exc}")

    raise PdfError(
        "Impossibile generare il PDF. "
        + (" | ".join(errors) if errors else "Nessun motore disponibile.")
    )
