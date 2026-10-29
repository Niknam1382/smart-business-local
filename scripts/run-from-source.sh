#!/usr/bin/env bash
# اجرای یک‌کلیکی از روی سورس (macOS / Linux) — Run from source with one command (macOS / Linux).
#
#   ./scripts/run-from-source.sh          # پنجره‌ی دسکتاپ | desktop window
#   ./scripts/run-from-source.sh --web    # در مرورگر | in the browser
#
# بار اول یه محیط مجازی (.venv) می‌سازه و وابستگی‌ها رو نصب می‌کنه؛ دفعه‌های بعد مستقیم اجرا می‌شه.
# First run creates a virtual environment (.venv) and installs dependencies; later runs start immediately.
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Python 3.11+ پیدا نشد / Python 3.11+ was not found. https://www.python.org/downloads/" >&2
  exit 1
fi
"$PYTHON" - <<'PY' || { echo "Python 3.11+ لازمه / Python 3.11+ is required" >&2; exit 1; }
import sys
sys.exit(0 if sys.version_info >= (3, 11) else 1)
PY

if [ ! -x ".venv/bin/python" ]; then
  echo "▶ ساخت محیط مجازی / creating virtual environment…"
  "$PYTHON" -m venv .venv
fi
STAMP=".venv/.requirements-installed"
if [ ! -f "$STAMP" ] || [ requirements.txt -nt "$STAMP" ]; then
  echo "▶ نصب وابستگی‌ها (بار اول چند دقیقه) / installing dependencies (a few minutes the first time)…"
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
  touch "$STAMP"
fi
exec .venv/bin/python run.py "$@"
