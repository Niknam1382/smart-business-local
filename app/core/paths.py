"""مسیر پوشه‌ی داده‌ی برنامه روی سیستم کاربر (ویندوز/مک/لینوکس) + حالت قابل‌حمل.

ترتیب انتخاب پوشه‌ی داده (اولی که جور شد):

۱. متغیر محیطی ``SMART_BUSINESS_DATA_DIR`` (برای کاربران حرفه‌ای/تست/داکر).
۲. **حالت قابل‌حمل (Portable):** اگه کنار برنامه (یا تا چند پوشه بالاتر، وقتی برنامه از
   روی فلش اجرا می‌شه) یه فایل به اسم ``portable.flag`` یا یه پوشه به اسم
   ``SmartBusinessData`` باشه، همون‌جا داده ذخیره می‌شه. تنظیمات، دیتابیس‌ها و
   ``secret.key`` همه توی همین پوشه‌ن، پس فلش رو به هر سیستمی ببری با همون اطلاعات
   باز می‌شه (چیدمان پیشنهادی فلش: یه ``SmartBusinessData`` مشترک + یه پوشه برای هر
   سیستم‌عامل کنارش). اگه پوشه‌ی قابل‌حمل قابل‌نوشتن نبود (فلشِ قفل‌شده)، به پوشه‌ی
   سیستم برمی‌گردیم تا برنامه کرش نکنه.
۳. پوشه‌ی استاندارد سیستم‌عامل:

   ویندوز: %APPDATA%\\SmartBusinessLocal
   مک:     ~/Library/Application Support/SmartBusinessLocal
   لینوکس: $XDG_DATA_HOME/SmartBusinessLocal یا ~/.local/share/SmartBusinessLocal
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from typing import Optional

APP_DIR_NAME = "SmartBusinessLocal"
PORTABLE_DIR_NAME = "SmartBusinessData"
PORTABLE_FLAG_NAME = "portable.flag"
ENV_DATA_DIR = "SMART_BUSINESS_DATA_DIR"

# وقتی برنامه از روی فلش اجرا می‌شه، فایل اجرایی ممکنه چند پوشه پایین‌تر از
# SmartBusinessData باشه (مثلاً Windows/App.exe یا داخل App.app/Contents/MacOS).
_MAX_LEVELS_UP = 5

MODE_ENV = "env"
MODE_PORTABLE = "portable"
MODE_SYSTEM = "system"


def app_anchor() -> Path:
    """پوشه‌ای که برنامه ازش اجرا شده: کنار فایل اجرایی (نسخه‌ی بسته‌بندی‌شده) یا
    ریشه‌ی پروژه (اجرا از سورس)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _is_writable_dir(path: Path) -> bool:
    """آیا می‌شه توی این پوشه فایل ساخت؟ (فلشِ قفل‌شده/فقط‌خواندنی → False)"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".write-test-{uuid.uuid4().hex[:8]}"
        probe.write_bytes(b"ok")
        probe.unlink()
        return True
    except OSError:
        return False


def find_portable_dir(anchor: Optional[Path] = None) -> Optional[Path]:
    """مسیر پوشه‌ی قابل‌حمل (اگه نشانه‌اش پیدا بشه)، وگرنه ``None``.

    اجرا از سورس فقط خودِ ریشه‌ی پروژه رو نگاه می‌کنه (بالا نمی‌ره)؛ نسخه‌ی
    بسته‌بندی‌شده تا ``_MAX_LEVELS_UP`` پوشه بالا می‌ره."""
    current = (anchor or app_anchor()).resolve()
    levels = _MAX_LEVELS_UP if getattr(sys, "frozen", False) else 0
    for _ in range(levels + 1):
        data = current / PORTABLE_DIR_NAME
        if data.is_dir() or (current / PORTABLE_FLAG_NAME).is_file():
            return data
        if current.parent == current:
            break
        current = current.parent
    return None


def _system_default_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_DIR_NAME


def resolve_data_dir() -> tuple:
    """``(مسیر, حالت)`` — حالت یکی از env/portable/system."""
    override = os.environ.get(ENV_DATA_DIR, "").strip()
    if override:
        return Path(override).expanduser(), MODE_ENV
    portable = find_portable_dir()
    if portable is not None and _is_writable_dir(portable):
        return portable, MODE_PORTABLE
    return _system_default_dir(), MODE_SYSTEM


def get_app_data_dir() -> Path:
    """پوشه‌ی داده‌ی برنامه رو برمی‌گردونه؛ در صورت نبود می‌سازدش."""
    app_dir, _mode = resolve_data_dir()
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def data_dir_mode() -> str:
    return resolve_data_dir()[1]


def is_portable() -> bool:
    return data_dir_mode() == MODE_PORTABLE
