"""Configuration, defaults, themes, profiles and persistence for MD → PDF Studio."""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import threading
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = APP_DIR / "config.json"
DEFAULT_STATE_DIR = Path.home() / ".config" / "md-to-pdf-studio"
DEFAULT_OUTPUT_DIR = APP_DIR / "output"
MAX_MARKDOWN_BYTES = 8 * 1024 * 1024

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS: dict[str, Any] = {
    "document": {
        "title": "",
        "subtitle": "",
        "author": "",
        "date": "",
        "lang": "it",
        "toc": False,
        "tocDepth": 3,
        "tocTitle": "Indice",
        "numberHeadings": False,
        "numberTables": False,
        "numberFigures": False,
        "numberPages": True,
        "figureCaptions": True,
        "filename": "documento",
    },
    "typography": {
        "bodyFont": "DejaVu Serif",
        "headingFont": "DejaVu Sans",
        "monoFont": "DejaVu Sans Mono",
        "bodySize": 10.5,
        "h1Size": 22.0,
        "h2Size": 16.0,
        "h3Size": 13.5,
        "h4Size": 11.5,
        "tableSize": 9.5,
        "codeSize": 9.0,
        "captionSize": 8.5,
        "lineHeight": 1.5,
        "paragraphSpacing": 0.65,
        "listIndent": 1.6,
        "textAlign": "left",
        "codeLineNumbers": False,
        "hyphenate": False,
    },
    "layout": {
        "pageSize": "A4",
        "orientation": "portrait",
        "customWidth": 210.0,
        "customHeight": 297.0,
        "marginTop": 20.0,
        "marginBottom": 20.0,
        "marginLeft": 20.0,
        "marginRight": 20.0,
        "scale": 100,
        "maxImageWidth": 100,
        "avoidHeadingOrphans": True,
        "avoidBreakInside": True,
        "cover": {
            "enabled": False,
            "title": "",
            "subtitle": "",
            "author": "",
            "date": "",
            "logo": "",
        },
        "watermark": {
            "enabled": False,
            "text": "BOZZA",
            "opacity": 0.07,
            "rotation": -35,
            "position": "center",
            "color": "#111827",
        },
    },
    "theme": {
        "name": "light",
        "text": "#1f2933",
        "muted": "#5c6b7a",
        "link": "#2563eb",
        "headings": "#16324f",
        "border": "#cbd5e0",
        "codeBg": "#f6f8fa",
        "codeText": "#24292f",
        "blockquoteBg": "#eef6ff",
        "tableHeaderBg": "#edf2f7",
        "background": "#ffffff",
    },
    "headerFooter": {
        "headerLeft": "",
        "headerCenter": "",
        "headerRight": "",
        "footerLeft": "",
        "footerCenter": "{page} / {pages}",
        "footerRight": "",
        "headerFontSize": 8.5,
        "footerFontSize": 8.5,
        "headerBorder": False,
        "footerBorder": False,
    },
    "pdf": {
        "engine": "auto",
        "outputDir": "",
    },
}

COLOR_KEYS = (
    "text",
    "muted",
    "link",
    "headings",
    "border",
    "codeBg",
    "codeText",
    "blockquoteBg",
    "tableHeaderBg",
    "background",
)

THEME_PRESETS: dict[str, dict[str, str]] = {
    "light": {
        "text": "#1f2933",
        "muted": "#5c6b7a",
        "link": "#2563eb",
        "headings": "#16324f",
        "border": "#cbd5e0",
        "codeBg": "#f6f8fa",
        "codeText": "#24292f",
        "blockquoteBg": "#eef6ff",
        "tableHeaderBg": "#edf2f7",
        "background": "#ffffff",
    },
    "dark": {
        "text": "#e2e8f0",
        "muted": "#94a3b8",
        "link": "#7dd3fc",
        "headings": "#f8fafc",
        "border": "#334155",
        "codeBg": "#1e293b",
        "codeText": "#e2e8f0",
        "blockquoteBg": "#1a2438",
        "tableHeaderBg": "#1e293b",
        "background": "#0f172a",
    },
    "print": {
        "text": "#000000",
        "muted": "#444444",
        "link": "#000000",
        "headings": "#000000",
        "border": "#8a8a8a",
        "codeBg": "#f4f4f4",
        "codeText": "#000000",
        "blockquoteBg": "#f7f7f7",
        "tableHeaderBg": "#ececec",
        "background": "#ffffff",
    },
    "minimal": {
        "text": "#27272a",
        "muted": "#71717a",
        "link": "#0f766e",
        "headings": "#18181b",
        "border": "#e4e4e7",
        "codeBg": "#fafafa",
        "codeText": "#3f3f46",
        "blockquoteBg": "#fafafa",
        "tableHeaderBg": "#f4f4f5",
        "background": "#ffffff",
    },
    "academic": {
        "text": "#1c1917",
        "muted": "#57534e",
        "link": "#1e3a8a",
        "headings": "#1c1917",
        "border": "#d6d3d1",
        "codeBg": "#f5f5f4",
        "codeText": "#292524",
        "blockquoteBg": "#fafaf9",
        "tableHeaderBg": "#efece9",
        "background": "#ffffff",
    },
    "technical": {
        "text": "#1e293b",
        "muted": "#64748b",
        "link": "#0369a1",
        "headings": "#0f4c81",
        "border": "#cbd5e1",
        "codeBg": "#f1f5f9",
        "codeText": "#0f172a",
        "blockquoteBg": "#eef6ff",
        "tableHeaderBg": "#e2e8f0",
        "background": "#ffffff",
    },
}

PAGE_SIZES_MM: dict[str, tuple[float, float]] = {
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
    "A5": (148.0, 210.0),
    "Letter": (215.9, 279.4),
    "Legal": (215.9, 355.6),
    "custom": (210.0, 297.0),
}

# Partial overrides for the bundled profiles. Deep-merged with DEFAULT_SETTINGS.
_PROFILE_OVERRIDES: dict[str, dict[str, Any]] = {
    "Documento semplice": {
        "document": {"toc": False, "numberHeadings": False, "numberTables": False},
        "typography": {
            "bodyFont": "DejaVu Sans",
            "headingFont": "DejaVu Sans",
            "bodySize": 10.5,
            "textAlign": "left",
            "codeLineNumbers": False,
        },
        "layout": {
            "marginTop": 20,
            "marginBottom": 20,
            "marginLeft": 20,
            "marginRight": 20,
            "avoidHeadingOrphans": True,
            "avoidBreakInside": True,
        },
        "theme": {"name": "light", **THEME_PRESETS["light"]},
        "headerFooter": {
            "headerLeft": "",
            "headerCenter": "",
            "headerRight": "",
            "footerLeft": "",
            "footerCenter": "{page} / {pages}",
            "footerRight": "",
            "headerBorder": False,
        },
    },
    "Report tecnico": {
        "document": {
            "toc": True,
            "tocDepth": 3,
            "numberHeadings": True,
            "numberTables": True,
            "numberFigures": True,
            "numberPages": True,
        },
        "typography": {
            "bodyFont": "DejaVu Sans",
            "headingFont": "DejaVu Sans",
            "bodySize": 10,
            "h1Size": 20,
            "h2Size": 15,
            "h3Size": 12.5,
            "lineHeight": 1.45,
            "textAlign": "left",
            "codeLineNumbers": False,
        },
        "layout": {
            "marginTop": 22,
            "marginBottom": 20,
            "marginLeft": 18,
            "marginRight": 18,
            "avoidHeadingOrphans": True,
            "avoidBreakInside": True,
        },
        "theme": {"name": "technical", **THEME_PRESETS["technical"]},
        "headerFooter": {
            "headerLeft": "{title}",
            "headerCenter": "",
            "headerRight": "{date}",
            "footerLeft": "{author}",
            "footerCenter": "{page} / {pages}",
            "footerRight": "",
            "headerBorder": True,
            "footerBorder": False,
        },
    },
    "Articolo": {
        "document": {
            "toc": False,
            "numberHeadings": False,
            "numberPages": True,
            "figureCaptions": True,
        },
        "typography": {
            "bodyFont": "DejaVu Serif",
            "headingFont": "DejaVu Serif",
            "bodySize": 11,
            "h1Size": 24,
            "h2Size": 16,
            "h3Size": 13,
            "lineHeight": 1.65,
            "paragraphSpacing": 0.8,
            "textAlign": "justify",
            "hyphenate": True,
        },
        "layout": {
            "marginTop": 25,
            "marginBottom": 25,
            "marginLeft": 25,
            "marginRight": 25,
            "avoidHeadingOrphans": True,
            "avoidBreakInside": True,
        },
        "theme": {"name": "academic", **THEME_PRESETS["academic"]},
        "headerFooter": {
            "headerLeft": "",
            "headerCenter": "",
            "headerRight": "",
            "footerLeft": "{author}",
            "footerCenter": "{page}",
            "footerRight": "",
        },
    },
    "Slide/handout": {
        "document": {"toc": False, "numberPages": True, "numberHeadings": False},
        "typography": {
            "bodyFont": "DejaVu Sans",
            "headingFont": "DejaVu Sans",
            "bodySize": 16,
            "h1Size": 30,
            "h2Size": 22,
            "h3Size": 18,
            "tableSize": 12,
            "codeSize": 11,
            "lineHeight": 1.35,
            "paragraphSpacing": 0.7,
        },
        "layout": {
            "pageSize": "A4",
            "orientation": "landscape",
            "marginTop": 15,
            "marginBottom": 15,
            "marginLeft": 15,
            "marginRight": 15,
            "maxImageWidth": 80,
            "avoidHeadingOrphans": True,
            "avoidBreakInside": True,
        },
        "theme": {"name": "minimal", **THEME_PRESETS["minimal"]},
        "headerFooter": {
            "footerLeft": "{title}",
            "footerCenter": "{page} / {pages}",
            "footerRight": "{date}",
        },
    },
    "Codice": {
        "document": {"toc": True, "tocDepth": 3, "numberPages": True},
        "typography": {
            "bodyFont": "DejaVu Sans",
            "headingFont": "DejaVu Sans",
            "monoFont": "DejaVu Sans Mono",
            "bodySize": 9.5,
            "h1Size": 19,
            "h2Size": 14,
            "h3Size": 12,
            "tableSize": 8.5,
            "codeSize": 8.5,
            "lineHeight": 1.4,
            "codeLineNumbers": True,
        },
        "layout": {
            "marginTop": 16,
            "marginBottom": 16,
            "marginLeft": 16,
            "marginRight": 16,
            "avoidHeadingOrphans": True,
            "avoidBreakInside": False,
        },
        "theme": {"name": "technical", **THEME_PRESETS["technical"]},
        "headerFooter": {
            "headerLeft": "{title}",
            "footerCenter": "{page} / {pages}",
            "headerBorder": True,
        },
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    """Recursively merge *override* into a deep copy of *base*."""
    out = copy.deepcopy(base)
    if not override:
        return out
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def get_builtin_profiles() -> dict[str, dict[str, Any]]:
    """Return the bundled profiles as complete settings dictionaries."""
    return {name: deep_merge(DEFAULT_SETTINGS, overrides) for name, overrides in _PROFILE_OVERRIDES.items()}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class SettingsError(ValueError):
    """Raised when user supplied settings are not valid."""


def _number(value: Any, path: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise SettingsError(f"{path}: atteso un numero.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SettingsError(f"{path}: atteso un numero, ricevuto {value!r}.") from exc
    if number != number or number in (float("inf"), float("-inf")):
        raise SettingsError(f"{path}: numero non valido.")
    if number < minimum or number > maximum:
        raise SettingsError(f"{path}: il valore deve essere compreso tra {minimum:g} e {maximum:g}.")
    return number


def _boolean(value: Any, path: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false", "1", "0", "on", "off"):
        return value.lower() in ("true", "1", "on")
    raise SettingsError(f"{path}: atteso un valore booleano.")


def _choice(value: Any, path: str, choices: set[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise SettingsError(f"{path}: valore non valido ({value!r}). Valori ammessi: {', '.join(sorted(choices))}.")
    return value


_COLOR_RE = re.compile(
    r"^(#[0-9a-fA-F]{3,8}|rgba?\([\d\s.,%/]+\)|hsla?\([\d\s.,%/]+\)|[a-zA-Z]{2,24})$"
)
_FONT_RE = re.compile(r"^[\w\s.,'’\-]+$", re.UNICODE)


def _font(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SettingsError(f"{path}: font non valido.")
    value = value.strip()
    if len(value) > 120 or not _FONT_RE.match(value):
        raise SettingsError(f"{path}: nome font non valido.")
    return value


def _color(value: Any, path: str) -> str:
    if not isinstance(value, str) or not _COLOR_RE.match(value.strip()):
        raise SettingsError(f"{path}: colore non valido ({value!r}).")
    return value.strip()


def _text(value: Any, path: str, maximum: int = 500) -> str:
    if value is None:
        return ""
    if not isinstance(value, (str, int, float, date, datetime)):
        raise SettingsError(f"{path}: atteso testo.")
    text = str(value)
    if len(text) > maximum:
        raise SettingsError(f"{path}: testo troppo lungo (max {maximum} caratteri).")
    return text


def validate_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Merge user settings with defaults and validate every supported field."""
    if raw is not None and not isinstance(raw, dict):
        raise SettingsError("settings: atteso un oggetto JSON.")
    settings = deep_merge(DEFAULT_SETTINGS, raw or {})

    doc = settings["document"]
    doc["title"] = _text(doc.get("title"), "document.title")
    doc["subtitle"] = _text(doc.get("subtitle"), "document.subtitle")
    doc["author"] = _text(doc.get("author"), "document.author")
    doc["date"] = _text(doc.get("date"), "document.date")
    doc["lang"] = _text(doc.get("lang"), "document.lang", 20).strip() or "it"
    if not re.match(r"^[A-Za-z]{2,8}(-[A-Za-z0-9]{2,8})*$", doc["lang"]):
        raise SettingsError("document.lang: codice lingua non valido (es. 'it' o 'it-IT').")
    for key in ("toc", "numberHeadings", "numberTables", "numberFigures", "numberPages", "figureCaptions"):
        doc[key] = _boolean(doc.get(key), f"document.{key}")
    doc["tocDepth"] = int(_number(doc.get("tocDepth"), "document.tocDepth", 1, 6))
    doc["tocTitle"] = _text(doc.get("tocTitle"), "document.tocTitle", 80).strip() or "Indice"
    doc["filename"] = sanitize_filename(_text(doc.get("filename"), "document.filename", 120), fallback="documento")
    if doc["filename"].lower().endswith(".pdf"):
        doc["filename"] = doc["filename"][:-4]

    typo = settings["typography"]
    for key in ("bodyFont", "headingFont", "monoFont"):
        typo[key] = _font(typo.get(key), f"typography.{key}")
    typo["bodySize"] = _number(typo.get("bodySize"), "typography.bodySize", 8, 24)
    typo["h1Size"] = _number(typo.get("h1Size"), "typography.h1Size", 8, 72)
    typo["h2Size"] = _number(typo.get("h2Size"), "typography.h2Size", 8, 64)
    typo["h3Size"] = _number(typo.get("h3Size"), "typography.h3Size", 8, 56)
    typo["h4Size"] = _number(typo.get("h4Size"), "typography.h4Size", 8, 48)
    typo["tableSize"] = _number(typo.get("tableSize"), "typography.tableSize", 6, 32)
    typo["codeSize"] = _number(typo.get("codeSize"), "typography.codeSize", 6, 32)
    typo["captionSize"] = _number(typo.get("captionSize"), "typography.captionSize", 6, 32)
    typo["lineHeight"] = _number(typo.get("lineHeight"), "typography.lineHeight", 0.8, 3)
    typo["paragraphSpacing"] = _number(typo.get("paragraphSpacing"), "typography.paragraphSpacing", 0, 3)
    typo["listIndent"] = _number(typo.get("listIndent"), "typography.listIndent", 0, 6)
    typo["textAlign"] = _choice(typo.get("textAlign"), "typography.textAlign", {"left", "justify", "center"})
    for key in ("codeLineNumbers", "hyphenate"):
        typo[key] = _boolean(typo.get(key), f"typography.{key}")

    layout = settings["layout"]
    layout["pageSize"] = _choice(
        layout.get("pageSize"), "layout.pageSize", {"A4", "A3", "A5", "Letter", "Legal", "custom"}
    )
    layout["orientation"] = _choice(layout.get("orientation"), "layout.orientation", {"portrait", "landscape"})
    layout["customWidth"] = _number(layout.get("customWidth"), "layout.customWidth", 50, 1000)
    layout["customHeight"] = _number(layout.get("customHeight"), "layout.customHeight", 50, 1000)
    for key in ("marginTop", "marginBottom", "marginLeft", "marginRight"):
        layout[key] = _number(layout.get(key), f"layout.{key}", 0, 80)
    layout["scale"] = int(_number(layout.get("scale"), "layout.scale", 50, 200))
    layout["maxImageWidth"] = int(_number(layout.get("maxImageWidth"), "layout.maxImageWidth", 10, 100))
    for key in ("avoidHeadingOrphans", "avoidBreakInside"):
        layout[key] = _boolean(layout.get(key), f"layout.{key}")

    cover = layout["cover"]
    cover["enabled"] = _boolean(cover.get("enabled"), "layout.cover.enabled")
    for key in ("title", "subtitle", "author", "date", "logo"):
        cover[key] = _text(cover.get(key), f"layout.cover.{key}", 1000)

    mark = layout["watermark"]
    mark["enabled"] = _boolean(mark.get("enabled"), "layout.watermark.enabled")
    mark["text"] = _text(mark.get("text"), "layout.watermark.text", 120)
    mark["opacity"] = _number(mark.get("opacity"), "layout.watermark.opacity", 0, 1)
    mark["rotation"] = _number(mark.get("rotation"), "layout.watermark.rotation", -180, 180)
    mark["position"] = _choice(
        mark.get("position"),
        "layout.watermark.position",
        {"center", "top-left", "top-right", "bottom-left", "bottom-right"},
    )
    mark["color"] = _color(mark.get("color"), "layout.watermark.color")

    theme = settings["theme"]
    theme["name"] = _text(theme.get("name"), "theme.name", 60).strip() or "light"
    for key in COLOR_KEYS:
        theme[key] = _color(theme.get(key), f"theme.{key}")

    hf = settings["headerFooter"]
    for key in ("headerLeft", "headerCenter", "headerRight", "footerLeft", "footerCenter", "footerRight"):
        hf[key] = _text(hf.get(key), f"headerFooter.{key}", 300)
    hf["headerFontSize"] = _number(hf.get("headerFontSize"), "headerFooter.headerFontSize", 5, 16)
    hf["footerFontSize"] = _number(hf.get("footerFontSize"), "headerFooter.footerFontSize", 5, 16)
    for key in ("headerBorder", "footerBorder"):
        hf[key] = _boolean(hf.get(key), f"headerFooter.{key}")

    pdf = settings["pdf"]
    pdf["engine"] = _choice(pdf.get("engine"), "pdf.engine", {"auto", "weasyprint", "chromium"})
    pdf["outputDir"] = _text(pdf.get("outputDir"), "pdf.outputDir", 500).strip()

    return settings


def _label(value: str, kind: str, maximum: int = 80) -> str:
    clean = str(value or "").strip()
    if not clean or len(clean) > maximum:
        raise SettingsError(f"Il nome del {kind} deve contenere da 1 a {maximum} caratteri.")
    if any(character in clean for character in "/\\?#%\x00\r\n\t"):
        raise SettingsError(f"Il nome del {kind} non può contenere / \\ ? # % o caratteri di controllo.")
    return clean


def sanitize_filename(name: str | None, fallback: str = "documento", extension: str = ".pdf") -> str:
    """Turn arbitrary text into a safe local filename (no path traversal)."""
    candidate = unicodedata.normalize("NFKC", str(name or "")).strip()
    candidate = candidate.replace("\x00", "")
    candidate = re.sub(r"[\\/]+", "-", candidate)
    candidate = re.sub(r"\.{2,}", "", candidate)
    candidate = re.sub(r"[\r\n\t]+", " ", candidate)
    candidate = re.sub(r'[<>:"|?*]', "", candidate)
    candidate = re.sub(r"\s+", " ", candidate)
    candidate = re.sub(r"-{2,}", "-", candidate)
    candidate = candidate.strip(" .-")
    for suffix in (extension, ".md", ".markdown", ".mdown", ".txt"):
        if suffix and candidate.lower().endswith(suffix.lower()):
            candidate = candidate[: -len(suffix)]
            break
    candidate = candidate.strip(" .-")
    if not candidate:
        candidate = fallback
    return candidate[:120] + extension


def page_dimensions(settings: dict[str, Any]) -> tuple[float, float]:
    """Return page width/height in millimetres, honouring orientation."""
    layout = settings["layout"]
    if layout["pageSize"] == "custom":
        width, height = float(layout["customWidth"]), float(layout["customHeight"])
    else:
        width, height = PAGE_SIZES_MM[layout["pageSize"]]
    if layout["orientation"] == "landscape":
        width, height = max(width, height), min(width, height)
    else:
        width, height = min(width, height), max(width, height)
    return width, height


def theme_presets() -> dict[str, dict[str, str]]:
    return copy.deepcopy(THEME_PRESETS)


# ---------------------------------------------------------------------------
# Persistent store
# ---------------------------------------------------------------------------

class ConfigStore:
    """Thread-safe JSON configuration plus drafts, logs and output files."""

    def __init__(
        self,
        config_path: Path | str | None = None,
        state_dir: Path | str | None = None,
        output_dir: Path | str | None = None,
    ) -> None:
        self.config_path = Path(config_path or os.environ.get("MD2PDF_CONFIG_PATH") or DEFAULT_CONFIG_PATH)
        self.state_dir = Path(state_dir or os.environ.get("MD2PDF_STATE_DIR") or DEFAULT_STATE_DIR).expanduser()
        self.output_dir = Path(output_dir or os.environ.get("MD2PDF_OUTPUT_DIR") or DEFAULT_OUTPUT_DIR).expanduser()
        self.assets_dir = self.state_dir / "assets"
        self.draft_path = self.state_dir / "draft.md"
        self.log_path = self.state_dir / "conversions.jsonl"
        self._lock = threading.RLock()
        self._ensure_dirs()
        self._config = self._load()

    # -- low level ---------------------------------------------------------
    def _ensure_dirs(self) -> None:
        for directory in (self.config_path.parent, self.state_dir, self.output_dir, self.assets_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def _seed(self) -> dict[str, Any]:
        return {
            "version": 1,
            "settings": copy.deepcopy(DEFAULT_SETTINGS),
            "profiles": {},
            "themes": {},
            "lastFilename": "documento",
        }

    def _load(self) -> dict[str, Any]:
        if not self.config_path.exists():
            config = self._seed()
            self._write(config)
            return config
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("root is not an object")
        except (OSError, ValueError):
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            try:
                self.config_path.replace(self.config_path.with_suffix(f".broken-{stamp}.json"))
            except OSError:
                pass
            config = self._seed()
            self._write(config)
            return config
        config = self._seed()
        config.update(data)
        config["settings"] = deep_merge(DEFAULT_SETTINGS, data.get("settings") or {})
        if not isinstance(config.get("profiles"), dict):
            config["profiles"] = {}
        if not isinstance(config.get("themes"), dict):
            config["themes"] = {}
        return config

    def _write(self, config: dict[str, Any]) -> None:
        payload = json.dumps(config, ensure_ascii=False, indent=2)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".config-", suffix=".json", dir=self.config_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.config_path)
        finally:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass

    def save(self) -> None:
        with self._lock:
            self._write(self._config)

    # -- settings ----------------------------------------------------------
    def get_settings(self) -> dict[str, Any]:
        with self._lock:
            return validate_settings(self._config.get("settings") or {})

    def set_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        validated = validate_settings(settings)
        with self._lock:
            self._config["settings"] = validated
            self._config["lastFilename"] = validated["document"]["filename"]
            self._write(self._config)
        return validated

    def reset_settings(self) -> dict[str, Any]:
        with self._lock:
            self._config["settings"] = copy.deepcopy(DEFAULT_SETTINGS)
            self._write(self._config)
        return self.get_settings()

    # -- profiles ----------------------------------------------------------
    def list_profiles(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {"name": name, "settings": entry["settings"], "builtin": False}
                for name, entry in sorted(self._config.get("profiles", {}).items())
            ]

    def get_profile(self, name: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._config.get("profiles", {}).get(name)
            return copy.deepcopy(entry["settings"]) if entry else None

    def save_profile(self, name: str, settings: dict[str, Any]) -> dict[str, Any]:
        clean = _label(name, "profilo")
        validated = validate_settings(settings)
        with self._lock:
            self._config.setdefault("profiles", {})[clean] = {
                "settings": validated,
                "updatedAt": datetime.now().isoformat(timespec="seconds"),
            }
            self._write(self._config)
        return {"name": clean, "settings": validated, "builtin": False}

    def delete_profile(self, name: str) -> bool:
        with self._lock:
            if name in self._config.get("profiles", {}):
                del self._config["profiles"][name]
                self._write(self._config)
                return True
            return False

    def rename_profile(self, old: str, new: str) -> dict[str, Any]:
        new_clean = _label(new, "profilo")
        with self._lock:
            profiles = self._config.setdefault("profiles", {})
            if old not in profiles:
                raise KeyError(old)
            if new_clean in profiles and new_clean != old:
                raise SettingsError(f"Esiste già un profilo chiamato “{new_clean}”.")
            profiles[new_clean] = profiles.pop(old)
            self._write(self._config)
            return {"name": new_clean, "settings": profiles[new_clean]["settings"], "builtin": False}

    def duplicate_profile(self, old: str, new: str) -> dict[str, Any]:
        settings = self.get_profile(old)
        if settings is None:
            raise KeyError(old)
        return self.save_profile(new, settings)

    # -- custom themes -----------------------------------------------------
    def list_themes(self) -> dict[str, dict[str, str]]:
        with self._lock:
            return copy.deepcopy(self._config.get("themes", {}))

    def save_theme(self, name: str, colors: dict[str, Any]) -> dict[str, Any]:
        clean = _label(name, "tema", 60)
        validated = {key: _color(colors.get(key), f"theme.{key}") for key in COLOR_KEYS}
        with self._lock:
            self._config.setdefault("themes", {})[clean] = validated
            self._write(self._config)
        return {"name": clean, "colors": validated}

    def delete_theme(self, name: str) -> bool:
        with self._lock:
            if name in self._config.get("themes", {}):
                del self._config["themes"][name]
                self._write(self._config)
                return True
            return False

    # -- draft -------------------------------------------------------------
    def read_draft(self) -> str:
        try:
            return self.draft_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    def write_draft(self, content: str) -> None:
        if len(content.encode("utf-8")) > MAX_MARKDOWN_BYTES:
            raise SettingsError("La bozza supera il limite di 8 MB.")
        with self._lock:
            self.draft_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.draft_path.with_suffix(".tmp")
            tmp.write_text(content, encoding="utf-8")
            os.replace(tmp, self.draft_path)

    # -- logs --------------------------------------------------------------
    def add_log(self, entry: dict[str, Any]) -> None:
        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            **entry,
        }
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def list_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        with self._lock:
            if not self.log_path.exists():
                return []
            lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        entries: list[dict[str, Any]] = []
        for line in lines[-limit:]:
            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    entries.append(parsed)
            except ValueError:
                continue
        return list(reversed(entries))

    def clear_logs(self) -> None:
        with self._lock:
            try:
                self.log_path.unlink()
            except FileNotFoundError:
                pass

    # -- files -------------------------------------------------------------
    def output_path(self, filename: str) -> Path:
        return self.output_dir / sanitize_filename(filename)

    def available_fonts(self) -> list[str]:
        """Return installed font families via fontconfig, with a safe fallback."""
        fonts: set[str] = set()
        try:
            import subprocess

            result = subprocess.run(
                ["fc-list", ":", "family"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            for line in result.stdout.splitlines():
                for family in line.split(","):
                    family = family.strip()
                    if family:
                        fonts.add(family)
        except (OSError, subprocess.SubprocessError):
            pass
        fonts.update(
            {
                "DejaVu Sans",
                "DejaVu Serif",
                "DejaVu Sans Mono",
                "Liberation Sans",
                "Liberation Serif",
                "Liberation Mono",
                "Noto Sans",
                "Noto Serif",
                "Lato",
                "Hack",
            }
        )
        # Emoji-only fonts contain digits/punctuation and are a poor choice for
        # body text; Pango already falls back to them automatically.
        fonts = {font for font in fonts if "emoji" not in font.casefold()}
        return sorted(fonts, key=lambda item: item.casefold())
