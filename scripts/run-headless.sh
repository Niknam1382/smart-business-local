#!/usr/bin/env sh
# اجرای حالتِ headless از سورس (سرور/Raspberry Pi) — بدونِ پنجره. نیازمندی: Python 3.11+
set -e
cd "$(dirname "$0")/.."
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install --quiet -r requirements-headless.txt
fi
exec .venv/bin/python run.py --headless "$@"
