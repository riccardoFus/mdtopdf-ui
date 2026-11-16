"""UI tests with Playwright against a real Uvicorn server.

The tests use the system Google Chrome when available (no browser download is
required). They verify the editor, live preview, settings, profiles, autosave,
export and console cleanliness.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def ui_server(tmp_path_factory):
    base = tmp_path_factory.mktemp("ui-server")
    port = free_port()
    env = os.environ.copy()
    env.update(
        {
            "MD2PDF_CONFIG_PATH": str(base / "config.json"),
            "MD2PDF_STATE_DIR": str(base / "state"),
            "MD2PDF_OUTPUT_DIR": str(base / "output"),
            # The native OS dialog cannot be automated in headless CI; UI tests
            # exercise the browser-picker fallback instead.
            "MD2PDF_DISABLE_DESKTOP_DIALOG": "1",
        }
    )
    log_path = base / "server.log"
    log = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 40
        while time.time() < deadline:
            try:
                response = httpx.get(url + "/api/health", timeout=1)
                if response.status_code == 200:
                    break
            except Exception:
                time.sleep(0.15)
        else:
            raise RuntimeError(f"Server UI non avviato. Log:\n{log_path.read_text()}")
        yield {"url": url, "base": base, "output": base / "output"}
    finally:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
        log.close()


@pytest.fixture(scope="session")
def browser():
    playwright = pytest.importorskip("playwright.sync_api")
    chrome = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
    if not chrome:
        pytest.skip("Google Chrome/Chromium non disponibile per i test UI.")
    with playwright.sync_playwright() as instance:
        browser = instance.chromium.launch(
            executable_path=chrome,
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        yield browser
        browser.close()


@pytest.fixture
def page(browser, ui_server):
    base_url = ui_server["url"]
    # Reset server-side state so tests are independent.
    httpx.post(base_url + "/api/settings/reset", json={}, timeout=10)
    httpx.post(base_url + "/api/draft", json={"content": ""}, timeout=10)

    context = browser.new_context(viewport={"width": 1500, "height": 950}, locale="it-IT")
    # Headless Chrome cannot interact with the native file picker. Provide a
    # deterministic stub that captures the bytes the app writes, so the real
    # File System Access flow (picker → createWritable → write → close) is tested.
    context.add_init_script(
        """
        window.__savedPdfBytes = null;
        window.__savedPdfClosed = false;
        window.__savePickerCalls = [];
        window.showSaveFilePicker = async (options = {}) => {
          window.__savePickerCalls.push(options);
          return {
            name: options.suggestedName || 'esportato.pdf',
            createWritable: async () => ({
              write: async (blob) => {
                const buffer = await blob.arrayBuffer();
                window.__savedPdfBytes = Array.from(new Uint8Array(buffer));
              },
              close: async () => { window.__savedPdfClosed = true; },
              abort: async () => {}
            })
          };
        };
        """
    )
    page = context.new_page()
    console_errors: list[str] = []

    def on_console(message):
        if message.type == "error":
            # The browser reports HTTP failures (e.g. the deliberate 404 in the
            # non-blocking-error test) as resource errors. Those are handled by
            # the UI as toasts; real JavaScript errors are still collected.
            if "Failed to load resource" in message.text:
                return
            console_errors.append(f"console.error: {message.text}")

    def on_page_error(error):
        console_errors.append(f"pageerror: {error}")

    page.on("console", on_console)
    page.on("pageerror", on_page_error)
    page.goto(base_url, wait_until="networkidle")
    page.evaluate("localStorage.clear()")
    page.reload(wait_until="networkidle")
    page.wait_for_function("window.__studio && window.__studio.ready", timeout=20_000)
    page.wait_for_function("window.__studio.state.lastPreviewMeta", timeout=30_000)
    page.wait_for_function("!document.querySelector('#previewPane').classList.contains('busy')", timeout=30_000)

    try:
        yield page
    finally:
        context.close()
        assert not console_errors, "Errori JavaScript in console:\n" + "\n".join(console_errors)


def wait_heading(page, heading: str, timeout: int = 30_000):
    page.wait_for_function(
        "h => window.__studio.state.lastPreviewMeta?.headings?.some(item => item.text === h)",
        arg=heading,
        timeout=timeout,
    )


def wait_idle(page, timeout: int = 30_000):
    page.wait_for_function(
        "() => !document.querySelector('#previewPane').classList.contains('busy')",
        timeout=timeout,
    )


def set_editor(page, markdown: str):
    page.fill("#editor", markdown)


def test_editor_accepts_text_and_uploaded_file(page, tmp_path: Path):
    text = "# Titolo Test UI 123\n\nTesto con **grassetto** e accenti: perché è à ù.\n"
    set_editor(page, text)
    wait_heading(page, "Titolo Test UI 123")
    wait_idle(page)
    assert page.locator(".pdf-page canvas").count() >= 1
    assert "Titolo Test UI 123" in page.locator("#editor").input_value()

    uploaded = tmp_path / "caricato.md"
    uploaded.write_text("# File caricato da UI\n\nContenuto del file.\n", encoding="utf-8")
    page.set_input_files("#fileInput", str(uploaded))
    page.wait_for_function("window.__studio.state.tabs.length === 2", timeout=10_000)
    wait_heading(page, "File caricato da UI")
    assert "File caricato da UI" in page.locator("#editor").input_value()
    assert "caricato.md" in page.evaluate("window.__studio.state.tabs.map(t => t.name)")


def test_settings_font_margin_theme_reflected_in_preview(page):
    set_editor(page, "# Prova impostazioni\n\nTesto di prova per la preview.\n\n<!-- pagebreak -->\n\n# Seconda pagina\n\nAltro testo.\n")
    wait_heading(page, "Prova impostazioni")
    wait_idle(page)
    before = hashlib.sha256(page.locator(".pdf-page canvas").first.screenshot()).hexdigest()

    page.click("#btnSettings")
    page.click('.settings-tab[data-panel="typography"]')
    body_size = page.locator('input[type=number][data-setting="typography.bodySize"]')
    body_size.fill("18")
    page.wait_for_function(
        "() => window.__studio.state.lastPreviewSettings?.typography?.bodySize === 18",
        timeout=30_000,
    )
    wait_idle(page)
    after_font = hashlib.sha256(page.locator(".pdf-page canvas").first.screenshot()).hexdigest()
    assert after_font != before, "La modifica del font size deve cambiare il rendering della preview"

    page.click('.settings-tab[data-panel="layout"]')
    margin = page.locator('input[data-setting="layout.marginLeft"]')
    margin.fill("34")
    page.wait_for_function(
        "() => window.__studio.state.lastPreviewSettings?.layout?.marginLeft === 34",
        timeout=30_000,
    )
    wait_idle(page)
    after_margin = hashlib.sha256(page.locator(".pdf-page canvas").first.screenshot()).hexdigest()
    assert after_margin != after_font, "La modifica dei margini deve cambiare la preview"

    page.click('.settings-tab[data-panel="theme"]')
    page.select_option("#themeSelect", "dark")
    page.wait_for_function(
        "() => window.__studio.state.lastPreviewSettings?.theme?.name === 'dark'",
        timeout=30_000,
    )
    wait_idle(page)
    pixel = page.evaluate(
        """() => {
            const canvas = document.querySelector('.pdf-page canvas');
            const ctx = canvas.getContext('2d');
            return Array.from(ctx.getImageData(4, 4, 1, 1).data);
        }"""
    )
    assert sum(pixel[:3]) < 300, f"Il tema dark deve avere sfondo scuro, pixel={pixel}"
    assert page.evaluate("window.__studio.state.settings.theme.name") == "dark"


def test_export_opens_save_picker_and_writes_pdf(page, ui_server, tmp_path: Path):
    set_editor(page, "# Esportazione UI\n\nContenuto da esportare.\n")
    wait_heading(page, "Esportazione UI")
    wait_idle(page)
    page.click("#btnExport")
    page.wait_for_function("() => window.__savedPdfClosed === true", timeout=40_000)
    result = page.evaluate("window.__studio.state.lastExport")
    assert result["method"] == "picker"
    assert result["savedTo"].endswith(".pdf")
    assert result["pageCount"] >= 1
    options = page.evaluate("window.__savePickerCalls[0]")
    assert options["suggestedName"].endswith(".pdf")
    assert "application/pdf" in options["types"][0]["accept"]

    data = bytes(page.evaluate("window.__savedPdfBytes"))
    output = tmp_path / "scelto-dall-utente.pdf"
    output.write_bytes(data)
    assert output.stat().st_size > 1000
    assert output.read_bytes().startswith(b"%PDF")
    assert page.locator(".toast.success").count() >= 1

    copy_path = Path(result["copyPath"])
    assert copy_path.exists()
    assert copy_path.read_bytes() == data, "la copia in output deve coincidere con il PDF scritto dal dialogo"
    assert result["copyUrl"].startswith("/api/files/")

    logs = httpx.get(ui_server["url"] + "/api/logs", timeout=10).json()["logs"]
    assert any(
        entry.get("destination") == "browser+copy"
        and entry["path"] == str(copy_path)
        and entry["status"] == "ok"
        for entry in logs
    )


def test_preview_pagination_and_zoom(page):
    set_editor(
        page,
        "# Pagina uno\n\nTesto.\n\n<!-- pagebreak -->\n\n# Pagina due\n\nTesto.\n\n"
        "<!-- pagebreak -->\n\n# Pagina tre\n\nTesto.\n",
    )
    wait_heading(page, "Pagina tre")
    wait_idle(page)
    assert page.locator("#pageTotal").inner_text() == "3"
    page.click("#btnNextPage")
    page.wait_for_function("() => document.querySelector('#pageNumber').value === '2'", timeout=10_000)
    assert page.locator("#pageNumber").input_value() == "2"
    page.click("#btnZoomIn")
    page.wait_for_function("() => document.querySelector('#zoomLabel').textContent !== 'Auto'", timeout=10_000)
    assert page.locator("#zoomLabel").inner_text().endswith("%")
    page.click("#btnFitWidth")
    page.wait_for_function("() => document.querySelector('#zoomLabel').textContent === 'Auto'", timeout=10_000)


def test_profile_save_and_reuse_from_ui(page):
    page.click("#btnSettings")
    page.click('.settings-tab[data-panel="typography"]')
    page.locator('input[type=number][data-setting="typography.bodySize"]').fill("15")
    page.wait_for_function(
        "() => window.__studio.state.lastPreviewSettings?.typography?.bodySize === 15",
        timeout=30_000,
    )
    page.click("#btnSaveProfile")
    page.wait_for_selector("#promptDialog[open]")
    profile_name = f"Profilo UI {int(time.time() * 1000)}"
    page.fill("#promptInput", profile_name)
    page.click("#promptConfirm")
    page.wait_for_function(
        "name => window.__studio.state.profiles.some(profile => profile.name === name)",
        arg=profile_name,
        timeout=20_000,
    )

    page.locator('input[type=number][data-setting="typography.bodySize"]').fill("9")
    page.wait_for_function(
        "() => window.__studio.state.lastPreviewSettings?.typography?.bodySize === 9",
        timeout=30_000,
    )
    page.select_option("#profileSelect", f"user:{profile_name}")
    page.click("#btnLoadProfile")
    page.wait_for_function(
        "() => window.__studio.state.lastPreviewSettings?.typography?.bodySize === 15",
        timeout=30_000,
    )
    assert page.locator('input[type=number][data-setting="typography.bodySize"]').input_value() == "15"


def test_draft_autosave_and_restore_in_new_page(page, ui_server):
    text = "# Bozza automatica UI\n\nContenuto recuperabile dopo il riavvio.\n"
    set_editor(page, text)
    wait_heading(page, "Bozza automatica UI")
    page.wait_for_timeout(1700)
    draft = httpx.get(ui_server["url"] + "/api/draft", timeout=10).json()["content"]
    assert "Bozza automatica UI" in draft

    page.evaluate("localStorage.clear(); window.onbeforeunload = null;")
    second = page.context.new_page()
    second.goto(ui_server["url"], wait_until="networkidle")
    second.wait_for_function("window.__studio && window.__studio.ready", timeout=20_000)
    second.wait_for_timeout(500)
    assert "Bozza automatica UI" in second.locator("#editor").input_value()
    second.close()


def test_toasts_do_not_use_blocking_alerts(page):
    # A normal invalid input should produce a non-blocking toast, not alert().
    dialog_events = []
    page.on("dialog", lambda dialog: (dialog_events.append(dialog.type), dialog.dismiss()))
    page.click("#btnOpenPath")
    page.wait_for_selector("#promptDialog[open]")
    page.fill("#promptInput", "/percorso/che/non/esiste.md")
    page.click("#promptConfirm")
    page.wait_for_selector(".toast.error", timeout=10_000)
    assert not dialog_events
    assert page.locator(".toast.error").count() >= 1


def test_math_and_mermaid_render_in_live_preview(page):
    markdown = """# Rich UI

Formula: $E = mc^2$ e blocco:

$$\\sum_{i=1}^{n} i = \\frac{n(n+1)}{2}$$

```mermaid
flowchart LR
  A[Editor] --> B[Preview]
  B --> C[PDF]
```
"""
    set_editor(page, markdown)
    wait_heading(page, "Rich UI")
    wait_idle(page, timeout=60_000)
    meta = page.evaluate("window.__studio.state.lastPreviewMeta")
    assert meta["warnings"] == []
    assert meta["pageCount"] >= 1
    assert page.locator(".pdf-page canvas").count() >= 1


def test_marp_deck_renders_as_slides(page):
    markdown = """---
marp: true
size: 16:9
paginate: true
---

# Slide uno

Prima slide.

---

## Slide due

Seconda slide.
"""
    set_editor(page, markdown)
    page.wait_for_function("() => window.__studio.state.lastPreviewMeta?.marp === true", timeout=30_000)
    wait_idle(page)
    meta = page.evaluate("window.__studio.state.lastPreviewMeta")
    assert meta["pageCount"] == 2
    assert meta["marpSize"] == "16:9"
    assert "Marp" in page.locator("#previewEngine").inner_text().title()
    assert page.locator("#pageTotal").inner_text() == "2"
