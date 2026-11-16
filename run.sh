#!/usr/bin/env bash
# Avvia MD → PDF Studio su http://127.0.0.1:8765
set -euo pipefail
cd "$(dirname "$0")"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8765}"
URL="http://${HOST}:${PORT}"

if [ ! -x ".venv/bin/python" ]; then
  echo "Virtualenv non trovato: eseguo install.sh..."
  ./install.sh
fi

if [ "${MD2PDF_NO_BROWSER:-0}" != "1" ] && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
  (
    sleep 1.4
    if command -v xdg-open >/dev/null 2>&1; then
      xdg-open "$URL" >/dev/null 2>&1 || true
    elif command -v sensible-browser >/dev/null 2>&1; then
      sensible-browser "$URL" >/dev/null 2>&1 || true
    fi
  ) &
fi

echo "MD → PDF Studio — ${URL}"
echo "Premi Ctrl+C per fermare il server."
exec .venv/bin/python -m uvicorn app.main:app --host "$HOST" --port "$PORT" --log-level info
