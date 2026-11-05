@echo off
rem اجرای یک‌کلیکی از روی سورس (ویندوز) - Run from source with a double-click (Windows).
rem   run-from-source.bat          پنجره‌ی دسکتاپ / desktop window
rem   run-from-source.bat --web    در مرورگر / in the browser
rem بار اول یه محیط مجازی (.venv) می‌سازه و وابستگی‌ها رو نصب می‌کنه؛ دفعه‌های بعد مستقیم اجرا می‌شه.
setlocal
chcp 65001 >nul
cd /d "%~dp0.."

where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11+ was not found. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 ( pause & exit /b 1 )
)
if not exist ".venv\.requirements-installed" (
  echo Installing dependencies - a few minutes the first time...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 ( pause & exit /b 1 )
  echo.> ".venv\.requirements-installed"
)
".venv\Scripts\python.exe" run.py %*
if errorlevel 1 pause
