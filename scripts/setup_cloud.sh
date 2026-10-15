#!/usr/bin/env bash
set -euo pipefail
cd /workspace/alosalem
python3 -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check --no-cache-dir -r requirements.lock
.venv/bin/python main.py --check
.venv/bin/python -m unittest discover -s tests
