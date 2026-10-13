#!/usr/bin/env bash
# GLPal: start on macOS/Linux. First run creates .venv and installs packages.
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip >/dev/null
  .venv/bin/pip install -r requirements.txt
fi
[ -f .env ] || cp .env.example .env
echo "GLPal is starting at http://127.0.0.1:8000 (Ctrl+C to stop)"
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
