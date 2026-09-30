#!/usr/bin/env sh
# Avvio su Linux/macOS (sviluppo)
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { python3 -m venv .venv && .venv/bin/pip install -r requirements.txt; }
exec .venv/bin/python -m alinea
