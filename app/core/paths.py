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
from typing import Optional

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


def install_drive_models_dir() -> Optional[Path]:
    """اگر برنامه **بسته‌بندی‌شده** روی درایوِ دیگری نصب شده باشد، همان درایو را برایِ مدل‌ها
    پیشنهاد می‌دهد (``D:\\SmartBusinessLocal\\models``). بیرون از این حالت ``None``."""
    if not getattr(sys, "frozen", False):
        return None  # اجرایِ از سورس: همان پوشه‌ی داده
    exe, data = Path(sys.executable), _system_default_dir()
    if not exe.drive or exe.drive.lower() == data.drive.lower():
        return None  # یک درایو (حالتِ معمولِ C:) — چیزی عوض نمی‌شه
    candidate = Path(exe.drive + os.sep) / APP_DIR_NAME / "models"
    return candidate


def default_model_dir() -> Path:
    """پوشه‌ی پیش‌فرضِ مدل‌ها.

    قاعده، به همین ترتیب:
    ۱) اگر ``<داده>/models`` همین حالا مدل یا فایلِ نیمه‌کاره دارد، همان‌جا می‌ماند — هیچ
       کاربری که مدلی دانلود کرده با این تغییر، مدلش را «گم» نمی‌کند.
    ۲) اگر نصب‌کننده روی درایوِ دیگری اجرا شده (مثلاً ویندوز روی C: و برنامه روی D:)، مدل
       چندگیگابایتی روی همان درایوِ نصب می‌نشیند و بیرون از پوشه‌ی نصب می‌ماند، پس حذفِ
       برنامه آن‌ها را پاک نمی‌کند.
    ۳) در غیر این صورت همان ``<داده>/models``.
    کاربر می‌تواند این را در «هوش مصنوعی ← پیشرفته ← محل ذخیره‌ی مدل» عوض کند؛ آن عدد بر همه
    اولویت دارد (``settings.model_storage_path``).
    """
    data_models = get_app_data_dir() / "models"
    try:
        if any(data_models.glob("*.gguf")) or any(data_models.glob("*.part")):
            return data_models
    except OSError:
        return data_models
    candidate = install_drive_models_dir()
    if candidate is None:
        return data_models
    try:
        candidate.mkdir(parents=True, exist_ok=True)
    except OSError:
        return data_models  # درایوِ مقصد آماده نیست (فلش کشیده شده، مسیر خواندنی و…)
    return candidate
