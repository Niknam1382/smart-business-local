"""مسیر پوشه‌ی داده‌ی برنامه روی سیستم کاربر (ویندوز/مک/لینوکس).

ترتیب انتخاب پوشه‌ی داده (اولی که جور شد):

۱. متغیر محیطی ``SMART_BUSINESS_DATA_DIR`` (برای کاربران حرفه‌ای/تست/داکر).
۲. پوشه‌ی استاندارد سیستم‌عامل:

   ویندوز: %APPDATA%\\SmartBusinessLocal
   مک:     ~/Library/Application Support/SmartBusinessLocal
   لینوکس: $XDG_DATA_HOME/SmartBusinessLocal یا ~/.local/share/SmartBusinessLocal

همه‌ی داده‌ها (تنظیمات، دیتابیس‌ها، ``secret.key``، مدل‌ها، فاکتورها) توی همین یک پوشه‌ان و
از «تنظیمات ← داده و ایمنی» پشتیبان گرفته می‌شه.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "SmartBusinessLocal"
ENV_DATA_DIR = "SMART_BUSINESS_DATA_DIR"

MODE_ENV = "env"
MODE_SYSTEM = "system"


def app_anchor() -> Path:
    """پوشه‌ای که برنامه ازش اجرا شده: کنار فایل اجرایی (نسخه‌ی بسته‌بندی‌شده) یا
    ریشه‌ی پروژه (اجرا از سورس)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _system_default_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_DIR_NAME


def resolve_data_dir() -> tuple:
    """``(مسیر, حالت)`` — حالت یکی از env/system."""
    override = os.environ.get(ENV_DATA_DIR, "").strip()
    if override:
        return Path(override).expanduser(), MODE_ENV
    return _system_default_dir(), MODE_SYSTEM


def get_app_data_dir() -> Path:
    """پوشه‌ی داده‌ی برنامه رو برمی‌گردونه؛ در صورت نبود می‌سازدش."""
    app_dir, _mode = resolve_data_dir()
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def data_dir_mode() -> str:
    return resolve_data_dir()[1]
