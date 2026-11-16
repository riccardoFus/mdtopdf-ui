"""FastAPI application for MD → PDF Studio."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from . import desktop_dialog
from .config import (
    APP_DIR,
    COLOR_KEYS,
    DEFAULT_SETTINGS,
    ConfigStore,
    SettingsError,
    get_builtin_profiles,
    sanitize_filename,
    theme_presets,
    validate_settings,
)
from .converter import convert_document, read_markdown_file, write_markdown_file
from .markdown_engine import MarkdownError
from .pdf_engine import PdfError, engine_status
from .rich_rendering import rich_available

import mimetypes

mimetypes.add_type("text/javascript", ".mjs")

STATIC_DIR = APP_DIR / "static"
EXAMPLES_DIR = APP_DIR / "examples"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".tif", ".tiff"}

logger = logging.getLogger("md2pdf")
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class DocumentRequest(BaseModel):
    markdown: str = ""
    settings: dict[str, Any] = Field(default_factory=dict)
    filename: str = "documento"
    base_dir: str | None = None
    output_dir: str | None = None
    include_html: bool = False
    save_copy: bool = True


class BatchFile(BaseModel):
    name: str = "documento.md"
    markdown: str = ""
    base_dir: str | None = None


class BatchRequest(BaseModel):
    files: list[BatchFile] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)
    output_dir: str | None = None


class SettingsRequest(BaseModel):
    settings: dict[str, Any]


class DraftRequest(BaseModel):
    content: str = ""


class OpenRequest(BaseModel):
    path: str


class SaveRequest(BaseModel):
    path: str
    content: str = ""


class ProfileRequest(BaseModel):
    name: str
    settings: dict[str, Any]


class RenameRequest(BaseModel):
    newName: str


class ThemeRequest(BaseModel):
    name: str
    colors: dict[str, Any]


class ProfileImportRequest(BaseModel):
    name: str | None = None
    settings: dict[str, Any] | None = None
    profile: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_base_dir(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not path.exists() or not path.is_dir():
        raise MarkdownError(f"Cartella di base non trovata: {path}")
    return path


def _resolve_output_dir(value: str | None, store: ConfigStore) -> Path:
    if not value:
        return store.output_dir
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if path.exists() and not path.is_dir():
        raise SettingsError(f"Il percorso di output non è una cartella: {path}")
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SettingsError(f"Impossibile creare la cartella di output {path}: {exc}") from exc
    if not os.access(path, os.W_OK):
        raise SettingsError(f"La cartella di output non è scrivibile: {path}")
    return path


def _unique_output_path(directory: Path, filename: str) -> Path:
    """Avoid overwriting silently; add a numeric suffix if needed."""
    candidate = directory / sanitize_filename(filename)
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    for index in range(2, 10000):
        alternative = directory / f"{stem}-{index}{suffix}"
        if not alternative.exists():
            return alternative
    return directory / f"{stem}-{uuid.uuid4().hex[:8]}{suffix}"


def _download_url(path: Path, store: ConfigStore) -> str:
    try:
        relative = path.resolve().relative_to(store.output_dir.resolve())
        return "/api/files/" + relative.as_posix()
    except ValueError:
        return ""


def _document_payload(request: DocumentRequest) -> tuple[str, Path | None]:
    return request.markdown, _resolve_base_dir(request.base_dir)


def _log_failure(store: ConfigStore, filename: str, started: float, error: Exception) -> None:
    store.add_log(
        {
            "status": "error",
            "filename": filename,
            "path": "",
            "durationMs": int((time.perf_counter() - started) * 1000),
            "pages": 0,
            "engine": "",
            "warnings": 0,
            "message": str(error),
        }
    )


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app(
    config_path: Path | str | None = None,
    state_dir: Path | str | None = None,
    output_dir: Path | str | None = None,
) -> FastAPI:
    app = FastAPI(
        title="MD → PDF Studio",
        version=__version__,
        description="Studio locale per convertire Markdown in PDF con preview fedele.",
    )
    store = ConfigStore(config_path=config_path, state_dir=state_dir, output_dir=output_dir)
    app.state.store = store

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # -- exception handlers -------------------------------------------------
    @app.exception_handler(MarkdownError)
    async def markdown_error_handler(_request, exc: MarkdownError):
        return JSONResponse(status_code=422, content={"detail": str(exc), "kind": "markdown"})

    @app.exception_handler(SettingsError)
    async def settings_error_handler(_request, exc: SettingsError):
        return JSONResponse(status_code=422, content={"detail": str(exc), "kind": "settings"})

    @app.exception_handler(PdfError)
    async def pdf_error_handler(_request, exc: PdfError):
        return JSONResponse(status_code=500, content={"detail": str(exc), "kind": "pdf"})

    @app.exception_handler(FileNotFoundError)
    async def file_not_found_handler(_request, exc: FileNotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc), "kind": "file"})

    # -- pages --------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    async def index():
        index_path = STATIC_DIR / "index.html"
        if not index_path.exists():
            return HTMLResponse("<h1>MD → PDF Studio</h1><p>Frontend non trovato.</p>", status_code=500)
        return HTMLResponse(index_path.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})

    @app.get("/favicon.ico")
    async def favicon():
        icon = STATIC_DIR / "img" / "favicon.svg"
        if icon.exists():
            return FileResponse(icon, media_type="image/svg+xml")
        return Response(status_code=204)

    @app.get("/api/health")
    async def health():
        engine = engine_status()
        engine["rich"] = rich_available()
        engine["desktopDialog"] = desktop_dialog.available()
        return {"ok": True, "version": __version__, "engine": engine}

    # -- configuration ------------------------------------------------------
    @app.get("/api/config")
    async def get_config():
        try:
            settings = store.get_settings()
        except SettingsError:
            settings = validate_settings({})
        custom_themes = store.list_themes()
        themes = theme_presets()
        themes.update(custom_themes)
        engine = engine_status()
        engine["rich"] = rich_available()
        return {
            "version": __version__,
            "settings": settings,
            "defaults": DEFAULT_SETTINGS,
            "profiles": store.list_profiles(),
            "builtinProfiles": [
                {"name": name, "settings": values} for name, values in get_builtin_profiles().items()
            ],
            "themes": themes,
            "themePresets": list(theme_presets().keys()),
            "customThemes": custom_themes,
            "fonts": store.available_fonts(),
            "outputDir": str(store.output_dir),
            "stateDir": str(store.state_dir),
            "draftPath": str(store.draft_path),
            "engine": engine,
            "desktopDialog": desktop_dialog.available(),
            "headerFooterVariables": ["{title}", "{author}", "{date}", "{page}", "{pages}", "{filename}"],
            "limits": {
                "bodySize": [8, 24],
                "maxMarkdownMb": 8,
                "maxUploadMb": 20,
            },
        }

    @app.post("/api/settings")
    async def save_settings(request: SettingsRequest):
        settings = store.set_settings(request.settings)
        return {"ok": True, "settings": settings}

    @app.post("/api/settings/reset")
    async def reset_settings():
        return {"ok": True, "settings": store.reset_settings()}

    # -- preview / conversion ----------------------------------------------
    @app.post("/api/preview")
    def preview(request: DocumentRequest):
        started = time.perf_counter()
        markdown, base_dir = _document_payload(request)
        filename = request.filename or request.settings.get("document", {}).get("filename") or "documento"
        result = convert_document(
            markdown,
            request.settings,
            base_dir=base_dir,
            filename=filename,
        )
        payload: dict[str, Any] = {
            "ok": True,
            "pdf": base64.b64encode(result.pdf).decode("ascii"),
            "pageCount": result.page_count,
            "marp": result.marp,
            "marpSize": result.marp_size,
            "warnings": result.warnings,
            "durationMs": result.duration_ms,
            "engine": result.engine,
            "headings": [
                {"level": h.level, "text": h.text, "slug": h.slug, "number": h.number}
                for h in result.headings
            ],
            "settings": result.settings,
            "bytes": len(result.pdf),
        }
        if request.include_html:
            payload["html"] = result.html
        return payload

    @app.post("/api/convert")
    def convert(request: DocumentRequest):
        started = time.perf_counter()
        markdown, base_dir = _document_payload(request)
        filename = request.filename or request.settings.get("document", {}).get("filename") or "documento"
        try:
            result = convert_document(
                markdown,
                request.settings,
                base_dir=base_dir,
                filename=filename,
            )
            output_directory = _resolve_output_dir(request.output_dir, store)
            output_path = _unique_output_path(output_directory, filename)
            output_path.write_bytes(result.pdf)
            store.set_settings(validate_settings(request.settings))
            store.add_log(
                {
                    "status": "ok",
                    "filename": output_path.name,
                    "path": str(output_path),
                    "durationMs": result.duration_ms,
                    "pages": result.page_count,
                    "engine": result.engine,
                    "warnings": len(result.warnings),
                    "warningMessages": [item["message"] for item in result.warnings],
                    "message": "",
                }
            )
        except Exception as exc:
            _log_failure(store, filename, started, exc)
            raise
        return {
            "ok": True,
            "path": str(output_path),
            "filename": output_path.name,
            "url": _download_url(output_path, store),
            "pageCount": result.page_count,
            "marp": result.marp,
            "marpSize": result.marp_size,
            "warnings": result.warnings,
            "durationMs": result.duration_ms,
            "engine": result.engine,
            "bytes": len(result.pdf),
            "settings": result.settings,
            "headings": [
                {"level": h.level, "text": h.text, "slug": h.slug, "number": h.number}
                for h in result.headings
            ],
        }

    @app.post("/api/export")
    def export_for_browser(request: DocumentRequest):
        """Convert, return the PDF for the browser dialog and keep a server copy.

        The browser writes the returned bytes through the native save dialog.
        At the same time (unless ``save_copy`` is false) the server stores a
        copy in the configured output folder, so the project keeps an archive.
        """
        started = time.perf_counter()
        markdown, base_dir = _document_payload(request)
        filename = request.filename or request.settings.get("document", {}).get("filename") or "documento"
        try:
            result = convert_document(
                markdown,
                request.settings,
                base_dir=base_dir,
                filename=filename,
            )
            copy_path: Path | None = None
            copy_url = ""
            if request.save_copy:
                try:
                    output_directory = _resolve_output_dir(request.output_dir, store)
                    copy_path = _unique_output_path(output_directory, filename)
                    copy_path.write_bytes(result.pdf)
                    copy_url = _download_url(copy_path, store)
                except Exception as exc:
                    result.warnings.append(
                        {"level": "warning", "message": f"Copia automatica in output non riuscita: {exc}"}
                    )
            store.set_settings(validate_settings(request.settings))
            safe_name = sanitize_filename(filename)
            store.add_log(
                {
                    "status": "ok",
                    "filename": copy_path.name if copy_path else safe_name,
                    "path": str(copy_path) if copy_path else "Dialogo di salvataggio del browser",
                    "destination": "browser+copy" if copy_path else "browser",
                    "durationMs": result.duration_ms,
                    "pages": result.page_count,
                    "engine": result.engine,
                    "warnings": len(result.warnings),
                    "warningMessages": [item["message"] for item in result.warnings],
                    "message": "",
                }
            )
        except Exception as exc:
            _log_failure(store, filename, started, exc)
            raise
        return {
            "ok": True,
            "pdf": base64.b64encode(result.pdf).decode("ascii"),
            "filename": safe_name,
            "pageCount": result.page_count,
            "marp": result.marp,
            "marpSize": result.marp_size,
            "warnings": result.warnings,
            "durationMs": result.duration_ms,
            "engine": result.engine,
            "bytes": len(result.pdf),
            "copyPath": str(copy_path) if copy_path else "",
            "copyUrl": copy_url,
        }

    @app.post("/api/export-dialog")
    def export_with_desktop_dialog(request: DocumentRequest):
        """Open the desktop's native save dialog and write the PDF there.

        This is the reliable path for Firefox (which lacks the File System
        Access API). The conversion happens only after the user confirms a
        destination; a copy is also kept in the configured output folder.
        """
        filename = request.filename or request.settings.get("document", {}).get("filename") or "documento"
        if not desktop_dialog.available():
            return {
                "ok": False,
                "canceled": False,
                "dialogUnavailable": True,
                "detail": "Nessun dialogo di sistema disponibile (zenity/kdialog e ambiente grafico).",
            }
        suggested = desktop_dialog.default_save_path(sanitize_filename(filename))
        choice = desktop_dialog.choose_save_path(suggested)
        if choice.canceled:
            return {"ok": True, "canceled": True, "dialogUnavailable": False}
        if choice.path is None:
            return {
                "ok": False,
                "canceled": False,
                "dialogUnavailable": True,
                "detail": choice.error or "Dialogo di sistema non disponibile.",
            }

        target = Path(choice.path).expanduser()
        if not target.is_absolute():
            target = (Path.cwd() / target).resolve()
        if target.suffix.lower() != ".pdf":
            target = Path(str(target) + ".pdf")
        if target.exists() and target.is_dir():
            raise SettingsError(f"Il percorso scelto è una cartella: {target}")
        if not target.parent.is_dir():
            raise SettingsError(f"La cartella di destinazione non esiste: {target.parent}")

        started = time.perf_counter()
        markdown, base_dir = _document_payload(request)
        try:
            result = convert_document(
                markdown,
                request.settings,
                base_dir=base_dir,
                filename=target.stem or filename,
            )
            try:
                target.write_bytes(result.pdf)
            except OSError as exc:
                raise SettingsError(f"Impossibile scrivere il PDF in {target}: {exc}") from exc

            copy_path = target
            copy_url = ""
            try:
                output_directory = _resolve_output_dir(request.output_dir, store)
                if not target.resolve().is_relative_to(output_directory.resolve()):
                    if request.save_copy:
                        copy_path = _unique_output_path(output_directory, target.name)
                        copy_path.write_bytes(result.pdf)
                copy_url = _download_url(copy_path, store)
            except Exception as exc:
                result.warnings.append(
                    {"level": "warning", "message": f"Copia automatica in output non riuscita: {exc}"}
                )
                copy_path = target
                copy_url = ""

            store.set_settings(validate_settings(request.settings))
            store.add_log(
                {
                    "status": "ok",
                    "filename": target.name,
                    "path": str(target),
                    "copyPath": str(copy_path),
                    "destination": "desktop-dialog",
                    "durationMs": result.duration_ms,
                    "pages": result.page_count,
                    "engine": result.engine,
                    "warnings": len(result.warnings),
                    "warningMessages": [item["message"] for item in result.warnings],
                    "message": "",
                }
            )
        except Exception as exc:
            _log_failure(store, filename, started, exc)
            raise

        return {
            "ok": True,
            "canceled": False,
            "dialogUnavailable": False,
            "path": str(target),
            "savedTo": str(target),
            "filename": target.name,
            "pageCount": result.page_count,
            "marp": result.marp,
            "marpSize": result.marp_size,
            "warnings": result.warnings,
            "durationMs": result.duration_ms,
            "engine": result.engine,
            "bytes": len(result.pdf),
            "copyPath": str(copy_path),
            "copyUrl": copy_url,
        }

    @app.post("/api/batch")
    def batch(request: BatchRequest):
        if not request.files:
            raise MarkdownError("Nessun file selezionato per l'esportazione batch.")
        if len(request.files) > 50:
            raise MarkdownError("Massimo 50 file per operazione batch.")
        started = time.perf_counter()
        output_directory = _resolve_output_dir(request.output_dir, store)
        results: list[dict[str, Any]] = []
        for item in request.files:
            item_started = time.perf_counter()
            try:
                base_dir = _resolve_base_dir(item.base_dir)
                result = convert_document(
                    item.markdown,
                    request.settings,
                    base_dir=base_dir,
                    filename=item.name,
                )
                output_path = _unique_output_path(output_directory, item.name)
                output_path.write_bytes(result.pdf)
                store.add_log(
                    {
                        "status": "ok",
                        "filename": output_path.name,
                        "path": str(output_path),
                        "durationMs": result.duration_ms,
                        "pages": result.page_count,
                        "engine": result.engine,
                        "warnings": len(result.warnings),
                        "warningMessages": [item["message"] for item in result.warnings],
                        "message": "",
                        "batch": True,
                    }
                )
                results.append(
                    {
                        "ok": True,
                        "name": item.name,
                        "path": str(output_path),
                        "filename": output_path.name,
                        "url": _download_url(output_path, store),
                        "pageCount": result.page_count,
            "marp": result.marp,
            "marpSize": result.marp_size,
                        "warnings": result.warnings,
                        "durationMs": result.duration_ms,
                        "engine": result.engine,
                    }
                )
            except Exception as exc:
                _log_failure(store, item.name, item_started, exc)
                results.append({"ok": False, "name": item.name, "error": str(exc)})
        return {
            "ok": all(item["ok"] for item in results),
            "results": results,
            "durationMs": int((time.perf_counter() - started) * 1000),
            "outputDir": str(output_directory),
        }

    # -- profiles -----------------------------------------------------------
    @app.get("/api/profiles")
    async def list_profiles():
        return {
            "profiles": store.list_profiles(),
            "builtinProfiles": [
                {"name": name, "settings": values} for name, values in get_builtin_profiles().items()
            ],
        }

    @app.post("/api/profiles")
    async def save_profile(request: ProfileRequest):
        profile = store.save_profile(request.name, request.settings)
        return {"ok": True, "profile": profile}

    @app.delete("/api/profiles/{name}")
    async def delete_profile(name: str):
        if not store.delete_profile(name):
            raise HTTPException(status_code=404, detail=f"Profilo non trovato: {name}")
        return {"ok": True}

    @app.post("/api/profiles/{name}/rename")
    async def rename_profile(name: str, request: RenameRequest):
        try:
            profile = store.rename_profile(name, request.newName)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Profilo non trovato: {name}") from exc
        return {"ok": True, "profile": profile}

    @app.post("/api/profiles/{name}/duplicate")
    async def duplicate_profile(name: str, request: RenameRequest):
        try:
            profile = store.duplicate_profile(name, request.newName)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Profilo non trovato: {name}") from exc
        return {"ok": True, "profile": profile}

    @app.get("/api/profiles/{name}/export")
    async def export_profile(name: str):
        builtin = get_builtin_profiles()
        settings = store.get_profile(name) or builtin.get(name)
        if settings is None:
            raise HTTPException(status_code=404, detail=f"Profilo non trovato: {name}")
        payload = json.dumps(
            {"format": "md-to-pdf-studio-profile", "version": 1, "name": name, "settings": settings},
            ensure_ascii=False,
            indent=2,
        )
        safe = re.sub(r"[^A-Za-z0-9._ -]+", "-", name).strip() or "profilo"
        return Response(
            content=payload,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="profilo-{safe}.json"'},
        )

    @app.post("/api/profiles/import")
    async def import_profile(request: ProfileImportRequest):
        source = request.settings
        name = request.name
        if request.profile:
            source = request.profile.get("settings", request.profile)
            name = name or request.profile.get("name")
        if not source:
            raise MarkdownError("File profilo non valido: manca l'oggetto settings.")
        profile = store.save_profile(name or "Profilo importato", source)
        return {"ok": True, "profile": profile}

    # -- custom themes ------------------------------------------------------
    @app.post("/api/themes")
    async def save_theme(request: ThemeRequest):
        theme = store.save_theme(request.name, request.colors)
        return {"ok": True, "theme": theme}

    @app.delete("/api/themes/{name}")
    async def delete_theme(name: str):
        if not store.delete_theme(name):
            raise HTTPException(status_code=404, detail=f"Tema non trovato: {name}")
        return {"ok": True}

    # -- draft --------------------------------------------------------------
    @app.get("/api/draft")
    async def get_draft():
        return {"content": store.read_draft(), "path": str(store.draft_path)}

    @app.post("/api/draft")
    async def save_draft(request: DraftRequest):
        store.write_draft(request.content)
        return {"ok": True, "path": str(store.draft_path), "bytes": len(request.content.encode("utf-8"))}

    # -- local files --------------------------------------------------------
    @app.post("/api/open")
    async def open_file(request: OpenRequest):
        content, path = read_markdown_file(request.path)
        stat = path.stat()
        return {
            "ok": True,
            "content": content,
            "path": str(path),
            "name": path.name,
            "baseDir": str(path.parent),
            "bytes": stat.st_size,
            "modified": stat.st_mtime,
        }

    @app.post("/api/save")
    async def save_file(request: SaveRequest):
        path = write_markdown_file(request.path, request.content)
        return {"ok": True, "path": str(path), "name": path.name, "baseDir": str(path.parent)}

    @app.post("/api/assets")
    async def upload_asset(file: UploadFile = File(...)):
        filename = Path(file.filename or "asset").name
        extension = Path(filename).suffix.lower()
        if extension not in IMAGE_EXTENSIONS:
            raise HTTPException(
                status_code=422,
                detail=f"Formato immagine non supportato: {extension or 'sconosciuto'}",
            )
        data = await file.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Immagine troppo grande (max 20 MB).")
        if not data:
            raise HTTPException(status_code=422, detail="File immagine vuoto.")
        safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename).stem).strip(".-") or "asset"
        stored = store.assets_dir / f"{uuid.uuid4().hex[:10]}-{safe_stem}{extension}"
        stored.write_bytes(data)
        return {
            "ok": True,
            "path": str(stored),
            "url": f"/api/assets/{stored.name}",
            "name": stored.name,
            "bytes": len(data),
        }

    @app.get("/api/assets/{name}")
    async def get_asset(name: str):
        safe = Path(name).name
        path = (store.assets_dir / safe).resolve()
        if path.parent != store.assets_dir.resolve() or not path.is_file():
            raise HTTPException(status_code=404, detail="Asset non trovato.")
        return FileResponse(path)

    # -- output download ----------------------------------------------------
    @app.get("/api/files/{filename:path}")
    async def download_output(filename: str):
        path = (store.output_dir / filename).resolve()
        try:
            path.relative_to(store.output_dir.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="File non trovato.") from exc
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"File non trovato: {filename}")
        return FileResponse(path, media_type="application/pdf", filename=path.name)

    # -- logs ---------------------------------------------------------------
    @app.get("/api/logs")
    async def logs(limit: int = 100):
        return {"logs": store.list_logs(limit=limit)}

    @app.delete("/api/logs")
    async def clear_logs():
        store.clear_logs()
        return {"ok": True}

    # -- example ------------------------------------------------------------
    @app.get("/api/example")
    async def example():
        path = EXAMPLES_DIR / "demo.md"
        if not path.exists():
            raise HTTPException(status_code=404, detail="Documento di esempio non disponibile.")
        return {
            "ok": True,
            "content": path.read_text(encoding="utf-8"),
            "name": "demo.md",
            "baseDir": str(EXAMPLES_DIR),
        }

    return app


app = create_app()
