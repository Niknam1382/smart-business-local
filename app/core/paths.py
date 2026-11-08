r"""مسیر پوشه‌ی داده‌ی برنامه روی سیستم کاربر (ویندوز/مک/لینوکس).

ترتیب انتخاب پوشه‌ی داده (اولی که جور شد):

۱. متغیر محیطی ``SMART_BUSINESS_DATA_DIR`` (برای کاربران حرفه‌ای/تست/داکر).
۲. بسته‌ی نصبیِ ویندوز بدونِ داده‌ی قبلی: همان درایوِ محلِ نصب،
   ``<درایو>:\SmartBusinessLocal`` (بیرون از پوشه‌ی نصب تا حذفِ برنامه داده را نبرد).
۳. پوشه‌ی استاندارد سیستم‌عامل (ویندوز: %APPDATA%\\SmartBusinessLocal،
   مک: ~/Library/Application Support/SmartBusinessLocal،
   لینوکس: $XDG_DATA_HOME/SmartBusinessLocal یا ~/.local/share/SmartBusinessLocal).
   کاربری که از قبل داده دارد همیشه همین‌جا می‌ماند.

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
MODE_INSTALL = "install"


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


def _has_user_data(directory: Path) -> bool:
    """آیا این پوشه از قبل داده‌ی کاربر دارد؟ نصبِ تازه به درایوِ محلِ نصب می‌رود، ولی کاربرِ
    قدیمی هرگز نباید داده‌اش را در دو جا پیدا کند."""
    try:
        return directory.is_dir() and any(directory.iterdir())
    except OSError:
        return False


def resolve_data_dir() -> tuple:
    r"""``(مسیر, حالت)`` — حالت یکی از env/install/system.

    بسته‌ی نصبیِ ویندوز وقتی پوشه‌ی استانداردِ سیستم خالی است داده را روی **همان درایوی می‌برد که
    برنامه نصب شده** (``<درایو>:\SmartBusinessLocal``) — بیرون از پوشه‌ی نصب، تا حذفِ برنامه داده را
    پاک نکند. اگر آنجا داده‌ی قبلی باشد، همان‌جا می‌ماند.
    """
    override = os.environ.get(ENV_DATA_DIR, "").strip()
    if override:
        return Path(override).expanduser(), MODE_ENV
    system_dir = _system_default_dir()
    if getattr(sys, "frozen", False) and sys.platform == "win32" and not _has_user_data(system_dir):
        drive = app_anchor().drive
        if drive:
            return Path(drive + os.sep) / APP_DIR_NAME, MODE_INSTALL
    return system_dir, MODE_SYSTEM


def get_app_data_dir() -> Path:
    """پوشه‌ی داده‌ی برنامه رو برمی‌گردونه؛ در صورت نبود می‌سازدش."""
    app_dir, _mode = resolve_data_dir()
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def data_dir_mode() -> str:
    return resolve_data_dir()[1]


def install_drive_models_dir(exe=None, data=None) -> Optional[Path]:
    """اگر برنامه‌یِ **بسته‌بندی‌شده** روی درایوِ دیگری نصب شده باشد، همان درایو را برایِ مدل‌ها
    پیشنهاد می‌دهد (``D:\\SmartBusinessLocal\\models``). در غیر این صورت ``None``.

    «درایوِ حرفی» فقط ویندوز معنی دارد: روی لینوکس و مک ``.drive`` خالی است، پس آنجا جای مدل
    مثلِ قبل پوشه‌ی داده می‌ماند. ``exe`` و ``data`` فقط برایِ تست‌اند."""
    if not getattr(sys, "frozen", False):
        return None  # اجرایِ از سورس: همان پوشه‌ی داده
    exe_path = Path(exe) if exe is not None else Path(sys.executable)
    data_path = Path(data) if data is not None else _system_default_dir()
    if not exe_path.drive or exe_path.drive.upper() == data_path.drive.upper():
        return None  # درایوِ واحد، یا نبودِ مفهوم درایو (لینوکس/مک)
    candidate = Path(exe_path.drive + os.sep) / APP_DIR_NAME / "models"
    if candidate == data_path / "models":
        return None
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
