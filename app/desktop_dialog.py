"""Native desktop save dialog (Linux) used by the local export flow.

Firefox does not implement the File System Access API, so the browser cannot
show a "save as" dialog.  The backend runs in the same graphical session as the
browser and can therefore ask the desktop's native dialog (zenity on GNOME,
kdialog on KDE) for a destination path.

The dialog is entirely local.  If no graphical session or no helper is
available, the API reports ``dialogUnavailable`` and the UI falls back to the
browser download/picker flow.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

DIALOG_TIMEOUT = 600


@dataclass
class SavePathChoice:
    canceled: bool = False
    path: Path | None = None
    error: str = ""


def _display_available() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _backend_order() -> list[str]:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    zenity = shutil.which("zenity")
    kdialog = shutil.which("kdialog")
    preferred: list[str] = []
    if "KDE" in desktop and kdialog:
        preferred.append(kdialog)
    if zenity:
        preferred.append(zenity)
    if kdialog and kdialog not in preferred:
        preferred.append(kdialog)
    return preferred


def available() -> bool:
    if os.environ.get("MD2PDF_DISABLE_DESKTOP_DIALOG") == "1":
        return False
    return _display_available() and bool(_backend_order())


def _default_directory() -> Path:
    home = Path.home()
    for name in ("Scrivania", "Desktop", "Documenti", "Documents"):
        candidate = home / name
        if candidate.is_dir():
            return candidate
    return home


def default_save_path(filename: str) -> Path:
    return _default_directory() / filename


def choose_save_path(suggested: Path) -> SavePathChoice:
    """Open the native save dialog.  Returns canceled/path/error."""
    if not available():
        return SavePathChoice(
            error=(
                "Nessun dialogo di sistema disponibile (serve un ambiente grafico "
                "e zenity o kdialog installati)."
            )
        )

    suggested = Path(suggested).expanduser()
    if not suggested.is_absolute():
        suggested = (Path.cwd() / suggested).resolve()
    errors: list[str] = []

    for executable in _backend_order():
        name = Path(executable).name.lower()
        if name == "zenity":
            command = [
                executable,
                "--file-selection",
                "--save",
                "--modal",
                "--title=Salva PDF — MD → PDF Studio",
                "--file-filter=Documenti PDF | *.pdf",
                f"--filename={suggested}",
            ]
        else:
            command = [
                executable,
                "--getsavefilename",
                str(suggested.parent),
                "PDF (*.pdf)",
                "--title",
                "Salva PDF — MD → PDF Studio",
            ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=DIALOG_TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return SavePathChoice(error="Il dialogo di salvataggio è scaduto.")
        except OSError as exc:
            errors.append(f"{name}: {exc}")
            continue

        if completed.returncode == 0:
            selected = completed.stdout.strip().splitlines()
            if selected and selected[0].strip():
                return SavePathChoice(path=Path(selected[0]).expanduser())
            errors.append(f"{name}: nessun percorso restituito")
            continue
        if completed.returncode == 1 and not completed.stderr.strip():
            return SavePathChoice(canceled=True)
        message = completed.stderr.strip() or f"uscita {completed.returncode}"
        errors.append(f"{name}: {message}")

    return SavePathChoice(error=" | ".join(errors) or "Dialogo non disponibile.")
