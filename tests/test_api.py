"""Integration tests for the FastAPI REST API."""

from __future__ import annotations

import base64
import json
from pathlib import Path

from app.config import validate_settings


def test_health_and_config(client):
    health = client.get("/api/health").json()
    assert health["ok"] is True
    assert health["engine"]["weasyprint"] is True or health["engine"]["chromium"] is True

    config = client.get("/api/config").json()
    assert config["settings"]["typography"]["bodySize"] == 10.5
    assert config["builtinProfiles"], "i profili predefiniti devono essere esposti"
    assert "light" in config["themes"] and "dark" in config["themes"]
    assert config["fonts"]
    assert "{page}" in config["headerFooterVariables"]
    assert config["outputDir"]


def test_preview_returns_valid_pdf(client, markdown, settings, sample_dir):
    response = client.post(
        "/api/preview",
        json={
            "markdown": markdown,
            "settings": settings,
            "filename": "anteprima",
            "base_dir": str(sample_dir),
            "include_html": True,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["pageCount"] >= 2
    assert payload["warnings"] == []
    assert payload["engine"] in ("weasyprint", "chromium")
    pdf = base64.b64decode(payload["pdf"])
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 5000
    assert "doc-table" in payload["html"]
    assert payload["headings"]


def test_convert_saves_pdf_and_log(client, markdown, settings, sample_dir, app):
    response = client.post(
        "/api/convert",
        json={
            "markdown": markdown,
            "settings": settings,
            "filename": "relazione finale",
            "base_dir": str(sample_dir),
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    output = Path(payload["path"])
    assert output.exists()
    assert output.parent == app.state.store.output_dir
    assert output.name == "relazione finale.pdf"
    assert output.stat().st_size > 5000
    assert payload["pageCount"] >= 2
    assert payload["url"].startswith("/api/files/")

    download = client.get(payload["url"])
    assert download.status_code == 200
    assert download.content.startswith(b"%PDF")

    logs = client.get("/api/logs").json()["logs"]
    assert logs and logs[0]["status"] == "ok"
    assert logs[0]["path"] == str(output)


def test_convert_does_not_overwrite_existing_pdf(client, settings):
    body = {
        "markdown": "# Titolo\n\nContenuto.\n",
        "settings": settings,
        "filename": "stesso-nome",
    }
    first = client.post("/api/convert", json=body).json()
    second = client.post("/api/convert", json=body).json()
    assert first["path"] != second["path"]
    assert Path(first["path"]).exists() and Path(second["path"]).exists()
    assert second["filename"].startswith("stesso-nome-")


def test_convert_custom_output_directory(client, settings, tmp_path):
    target = tmp_path / "cartella-scelta"
    response = client.post(
        "/api/convert",
        json={
            "markdown": "# Titolo\n",
            "settings": settings,
            "filename": "custom",
            "output_dir": str(target),
        },
    )
    assert response.status_code == 200
    assert Path(response.json()["path"]).parent == target
    assert (target / "custom.pdf").exists()


def test_convert_sanitizes_traversal_filename(client, settings):
    response = client.post(
        "/api/convert",
        json={
            "markdown": "# Titolo\n",
            "settings": settings,
            "filename": "../../etc/passwd.pdf",
        },
    )
    assert response.status_code == 200
    path = Path(response.json()["path"])
    assert "/" not in path.name
    assert "etc/passwd" not in str(path).replace("etc-passwd", "")
    assert path.parent == client.app.state.store.output_dir


def test_convert_empty_markdown_is_422(client, settings):
    response = client.post("/api/convert", json={"markdown": "   ", "settings": settings})
    assert response.status_code == 422
    assert "vuoto" in response.json()["detail"].lower()


def test_convert_invalid_yaml_is_422(client, settings):
    response = client.post(
        "/api/convert",
        json={"markdown": "---\ntitle: [non chiuso\n---\n# Titolo\n", "settings": settings},
    )
    assert response.status_code == 422
    assert "YAML" in response.json()["detail"]


def test_convert_invalid_settings_is_422(client):
    response = client.post(
        "/api/convert",
        json={"markdown": "# Titolo\n", "settings": {"typography": {"bodySize": 99}}},
    )
    assert response.status_code == 422
    assert "bodySize" in response.json()["detail"]


def test_convert_missing_image_returns_warning(client, settings, tmp_path):
    response = client.post(
        "/api/convert",
        json={
            "markdown": "# Titolo\n\n![Manca](manca.png)\n",
            "settings": settings,
            "base_dir": str(tmp_path),
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["warnings"]
    assert any("manca.png" in item["message"] for item in payload["warnings"])


def test_batch_converts_three_files(client, settings):
    files = [
        {"name": f"batch-{index}.md", "markdown": f"# Documento {index}\n\nTesto {index}.\n"}
        for index in range(1, 4)
    ]
    response = client.post("/api/batch", json={"files": files, "settings": settings})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert len(payload["results"]) == 3
    assert all(item["ok"] for item in payload["results"])
    assert all(Path(item["path"]).exists() for item in payload["results"])
    assert all(item["pageCount"] >= 1 for item in payload["results"])
    assert [item["filename"] for item in payload["results"]] == ["batch-1.pdf", "batch-2.pdf", "batch-3.pdf"]


def test_batch_reports_partial_errors(client, settings):
    response = client.post(
        "/api/batch",
        json={
            "files": [
                {"name": "ok.md", "markdown": "# Ok\n"},
                {"name": "rotto.md", "markdown": "---\ntitle: [x\n---\n# Rotto\n"},
            ],
            "settings": settings,
        },
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert results[0]["ok"] is True
    assert results[1]["ok"] is False
    assert "YAML" in results[1]["error"]


def test_batch_empty_is_422(client, settings):
    response = client.post("/api/batch", json={"files": [], "settings": settings})
    assert response.status_code == 422


def test_profile_save_reload_duplicate_rename_export_delete(client, settings):
    response = client.post("/api/profiles", json={"name": "Il mio stile", "settings": settings})
    assert response.status_code == 200, response.text
    saved = response.json()["profile"]["settings"]
    assert saved["typography"]["bodySize"] == settings["typography"]["bodySize"]

    config = client.get("/api/config").json()
    names = [item["name"] for item in config["profiles"]]
    assert "Il mio stile" in names

    duplicate = client.post("/api/profiles/Il mio stile/duplicate", json={"newName": "Copia stile"})
    assert duplicate.status_code == 200

    renamed = client.post("/api/profiles/Copia stile/rename", json={"newName": "Stile rinominato"})
    assert renamed.status_code == 200
    assert renamed.json()["profile"]["name"] == "Stile rinominato"

    export = client.get("/api/profiles/Stile rinominato/export")
    assert export.status_code == 200
    data = json.loads(export.text)
    assert data["name"] == "Stile rinominato"
    assert data["settings"]["document"]["toc"] == settings["document"]["toc"]

    imported = client.post(
        "/api/profiles/import",
        json={"name": "Importato", "settings": data["settings"]},
    )
    assert imported.status_code == 200
    assert imported.json()["profile"]["name"] == "Importato"

    deleted = client.delete("/api/profiles/Il mio stile")
    assert deleted.status_code == 200
    assert client.delete("/api/profiles/Il mio stile").status_code == 404


def test_profile_name_rejects_unsafe_characters(client, settings):
    response = client.post("/api/profiles", json={"name": "profilo/con/slash", "settings": settings})
    assert response.status_code == 422
    assert "non può contenere" in response.json()["detail"]


def test_settings_persist_and_reset(client, settings):
    settings["typography"]["bodySize"] = 14
    response = client.post("/api/settings", json={"settings": settings})
    assert response.status_code == 200
    assert client.get("/api/config").json()["settings"]["typography"]["bodySize"] == 14

    reset = client.post("/api/settings/reset", json={})
    assert reset.status_code == 200
    assert reset.json()["settings"]["typography"]["bodySize"] == 10.5


def test_draft_autosave_and_restore(client, app):
    content = "# Bozza\n\nTesto con accenti: perché è à ù.\n"
    response = client.post("/api/draft", json={"content": content})
    assert response.status_code == 200
    assert app.state.store.draft_path.exists()
    restored = client.get("/api/draft").json()
    assert restored["content"] == content
    assert restored["path"] == str(app.state.store.draft_path)


def test_open_and_save_local_files(client, tmp_path):
    path = tmp_path / "documento.md"
    path.write_text("# Salvato\n\nContenuto salvo.\n", encoding="utf-8")
    opened = client.post("/api/open", json={"path": str(path)})
    assert opened.status_code == 200
    assert opened.json()["content"].startswith("# Salvato")
    assert opened.json()["baseDir"] == str(tmp_path)

    save_path = tmp_path / "nuovo.md"
    saved = client.post("/api/save", json={"path": str(save_path), "content": "# Nuovo\n"})
    assert saved.status_code == 200
    assert save_path.read_text(encoding="utf-8") == "# Nuovo\n"

    missing = client.post("/api/open", json={"path": str(tmp_path / "manca.md")})
    assert missing.status_code == 404


def test_assets_upload_and_download(client, tiny_png_base64):
    data = base64.b64decode(tiny_png_base64)
    response = client.post(
        "/api/assets",
        files={"file": ("pixel.png", data, "image/png")},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert Path(payload["path"]).exists()
    download = client.get(payload["url"])
    assert download.status_code == 200
    assert download.content == data


def test_custom_theme_crud(client):
    colors = {
        "text": "#111111",
        "muted": "#666666",
        "link": "#0000ff",
        "headings": "#222222",
        "border": "#cccccc",
        "codeBg": "#f5f5f5",
        "codeText": "#333333",
        "blockquoteBg": "#eeeeee",
        "tableHeaderBg": "#dddddd",
        "background": "#ffffff",
    }
    response = client.post("/api/themes", json={"name": "Blu", "colors": colors})
    assert response.status_code == 200
    assert "Blu" in client.get("/api/config").json()["customThemes"]
    assert client.delete("/api/themes/Blu").status_code == 200


def test_example_document_available(client):
    response = client.get("/api/example")
    assert response.status_code == 200
    payload = response.json()
    assert "# " in payload["content"]
    assert payload["baseDir"].endswith("examples")


def test_logs_can_be_cleared(client, settings):
    client.post("/api/convert", json={"markdown": "# Log\n", "settings": settings})
    assert client.get("/api/logs").json()["logs"]
    assert client.delete("/api/logs").status_code == 200
    assert client.get("/api/logs").json()["logs"] == []


def test_rejects_unknown_engine_setting(client):
    response = client.post(
        "/api/preview",
        json={"markdown": "# Test\n", "settings": {"pdf": {"engine": "cloud"}}},
    )
    assert response.status_code == 422
    assert "pdf.engine" in response.json()["detail"]


def test_preview_with_math_and_mermaid(client):
    from app.rich_rendering import rich_available

    if not rich_available():
        import pytest

        pytest.skip("Chromium/Playwright non disponibile")
    markdown = """# Rich preview

$E = mc^2$

```mermaid
flowchart LR
  A --> B
```
"""
    response = client.post("/api/preview", json={"markdown": markdown, "settings": {}, "filename": "rich"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["warnings"] == []
    assert payload["pageCount"] >= 1
    pdf = base64.b64decode(payload["pdf"])
    assert pdf.startswith(b"%PDF")


def test_export_returns_pdf_for_browser_dialog_and_keeps_copy(client, settings, app):
    before = set(app.state.store.output_dir.glob("*.pdf"))
    response = client.post(
        "/api/export",
        json={"markdown": "# Dialogo\n\nContenuto scelto dall'utente.\n", "settings": settings, "filename": "scelto"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    pdf = base64.b64decode(payload["pdf"])
    assert pdf.startswith(b"%PDF")
    assert payload["pageCount"] >= 1
    assert payload["filename"] == "scelto.pdf"
    copy_path = Path(payload["copyPath"])
    assert copy_path.exists()
    assert copy_path.parent == app.state.store.output_dir
    assert copy_path.read_bytes() == pdf
    assert payload["copyUrl"].startswith("/api/files/")
    after = set(app.state.store.output_dir.glob("*.pdf"))
    assert after - before == {copy_path}, "l'export deve lasciare una copia nella cartella output"
    logs = client.get("/api/logs").json()["logs"]
    assert any(
        entry.get("destination") == "browser+copy"
        and entry["path"] == str(copy_path)
        and entry["status"] == "ok"
        for entry in logs
    )


def test_export_dialog_writes_chosen_file_and_keeps_output_copy(client, settings, tmp_path, monkeypatch):
    from app import desktop_dialog
    from app.desktop_dialog import SavePathChoice

    target = tmp_path / "scelto-dal-dialogo.pdf"
    monkeypatch.setattr(desktop_dialog, "available", lambda: True)
    monkeypatch.setattr(desktop_dialog, "default_save_path", lambda filename: tmp_path / filename)
    monkeypatch.setattr(desktop_dialog, "choose_save_path", lambda suggested: SavePathChoice(path=target))

    response = client.post(
        "/api/export-dialog",
        json={"markdown": "# Dialogo di sistema\n\nContenuto.\n", "settings": settings, "filename": "scelto"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["canceled"] is False
    assert payload["path"] == str(target)
    assert target.exists()
    assert target.read_bytes().startswith(b"%PDF")
    copy_path = Path(payload["copyPath"])
    assert copy_path.exists()
    assert copy_path != target
    assert copy_path.read_bytes() == target.read_bytes()
    logs = client.get("/api/logs").json()["logs"]
    assert any(
        entry.get("destination") == "desktop-dialog"
        and entry.get("path") == str(target)
        and entry["status"] == "ok"
        for entry in logs
    )


def test_export_dialog_cancel_does_not_create_files(client, settings, tmp_path, monkeypatch):
    from app import desktop_dialog
    from app.desktop_dialog import SavePathChoice

    monkeypatch.setattr(desktop_dialog, "available", lambda: True)
    monkeypatch.setattr(desktop_dialog, "choose_save_path", lambda suggested: SavePathChoice(canceled=True))
    response = client.post(
        "/api/export-dialog",
        json={"markdown": "# Annulla\n", "settings": settings, "filename": "annullato"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["canceled"] is True
    assert not list(tmp_path.glob("*.pdf"))


def test_preview_marp_deck(client):
    markdown = """---
marp: true
size: 16:9
paginate: true
---

# Slide uno

Testo.

---

# Slide due

Altro testo.
"""
    response = client.post("/api/preview", json={"markdown": markdown, "settings": {}, "filename": "deck"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["marp"] is True
    assert payload["marpSize"] == "16:9"
    assert payload["pageCount"] == 2
    assert base64.b64decode(payload["pdf"]).startswith(b"%PDF")
