#!/usr/bin/env bash
# Crea il virtualenv e installa le dipendenze Python di MD → PDF Studio.
set -euo pipefail
cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
  echo "✓ Virtualenv già presente (.venv)"
  PYTHON_BIN=".venv/bin/python"
else
  PYTHON_BIN=""
  for candidate in "${PYTHON:-}" python3 python3.13 python3.12 python3.11; do
    [ -n "$candidate" ] || continue
    command -v "$candidate" >/dev/null 2>&1 || continue
    echo "→ Provo a creare il virtualenv con $candidate"
    rm -rf .venv
    if "$candidate" -m venv .venv >/dev/null 2>&1 && [ -x ".venv/bin/python" ]; then
      PYTHON_BIN=".venv/bin/python"
      break
    fi
  done
  if [ -z "$PYTHON_BIN" ]; then
    rm -rf .venv
    cat >&2 <<'EOF'
✗ Impossibile creare il virtualenv.

Su Debian/Ubuntu installa il modulo venv:
  sudo apt update && sudo apt install -y python3 python3-venv python3-pip

Su Arch Linux:
  sudo pacman -S --needed python python-pip

Poi riprova con: ./install.sh
EOF
    exit 1
  fi
fi

"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install -r requirements.txt

if "$PYTHON_BIN" -c "import weasyprint" >/dev/null 2>&1; then
  echo "✓ WeasyPrint disponibile"
else
  cat >&2 <<'EOF'
⚠ WeasyPrint non è importabile: l'app userà il fallback Chromium (se presente).
  Debian/Ubuntu:
    sudo apt install -y libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libcairo2 libgdk-pixbuf-2.0-0
  Arch Linux:
    sudo pacman -S --needed pango cairo gdk-pixbuf2 harfbuzz
EOF
fi

CHROME_FOUND=""
for browser in google-chrome google-chrome-stable chromium chromium-browser chrome; do
  if command -v "$browser" >/dev/null 2>&1; then CHROME_FOUND="$browser"; break; fi
done
if [ -n "$CHROME_FOUND" ]; then
  echo "✓ Chromium/Chrome disponibile ($CHROME_FOUND): Mermaid, LaTeX e fallback attivi"
else
  cat >&2 <<'EOF'
⚠ Chromium/Chrome non trovato: Mermaid e LaTeX non saranno renderizzati
  e il fallback PDF non sarà disponibile. Installa Google Chrome/Chromium
  oppure esegui: .venv/bin/playwright install chromium
EOF
fi

chmod +x run.sh
mkdir -p output
echo "✓ Installazione completata. Avvia con: ./run.sh  (oppure: make run)"
