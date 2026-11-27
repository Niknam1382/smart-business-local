"""قفلِ تک‌نمونه (۱٫۲٫۲): فقط یک پنجره‌ی برنامه روی یک پوشه‌ی داده.

چرا: دو نسخه‌ی هم‌زمان هر دو ربات را poll می‌کنند (خطای 409 تلگرام) و روی یک دیتابیس می‌نویسند.
قفل یک فایلِ کوچک در پوشه‌ی داده است (``flock`` روی لینوکس/مک، ``msvcrt.locking`` روی ویندوز)؛ با بسته‌شدنِ
پردازش — حتی با کرش — خودکار آزاد می‌شود، پس قفلِ «ماندگار» نداریم. خطایِ غیرمنتظره هرگز برنامه را
نمی‌بندد: در شک، اجازه‌ی اجرا می‌دهیم (قفل یک محافظ است، نه شرطِ اجرا).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

LOCK_NAME = ".instance.lock"
BUSY = "busy"  # مقدارِ بازگشتیِ acquire وقتی نسخه‌ی دیگری باز است

_handle = None  # تا پایانِ پردازش زنده می‌ماند


def _lock_path(data_dir: Optional[Path] = None) -> Path:
    if data_dir is None:
        from app.core.paths import get_app_data_dir

        data_dir = get_app_data_dir()
    return Path(data_dir) / LOCK_NAME


def _try_lock(handle) -> bool:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def acquire(data_dir: Optional[Path] = None):
    """قفل را می‌گیرد. برمی‌گرداند: handle (موفق) | ``BUSY`` (نسخه‌ی دیگری باز است) | ``None`` (خطای غیرمنتظره؛ ادامه بده)."""
    global _handle
    try:
        path = _lock_path(data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "a+b")  # noqa: SIM115 — عمداً باز می‌ماند
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")  # msvcrt.locking یک بایت لازم دارد
            handle.flush()
        if not _try_lock(handle):
            handle.close()
            return BUSY
        _handle = handle
        return handle
    except Exception:  # noqa: BLE001 — قفل نباید برنامه را از کار بیندازد
        return None


def release() -> None:
    global _handle
    handle, _handle = _handle, None
    if handle is not None:
        try:
            handle.close()
        except Exception:  # noqa: BLE001
            pass


BUSY_TITLE = "کسب‌وکار هوشمند"
BUSY_TEXT = (
    "برنامه از قبل باز است.\n\n"
    "اگر پنجره‌اش را نمی‌بینی، آن را از نوارِ وظیفه (Taskbar) یا کنارِ ساعت (Tray) پیدا کن. "
    "اجرای هم‌زمانِ دو نسخه باعث تداخلِ ربات‌ها و خرابیِ داده‌ها می‌شود."
)


def notify_busy() -> None:
    """پیامِ «برنامه از قبل باز است» — ویندوز: پنجره‌ی پیام؛ جاهایِ دیگر: stderr. هرگز exception نمی‌دهد."""
    try:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, BUSY_TEXT, BUSY_TITLE, 0x40)
            return
    except Exception:  # noqa: BLE001
        pass
    print(BUSY_TEXT, file=sys.stderr)
