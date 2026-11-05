"""میوتکسِ نام‌دارِ ویندوز برای نصب‌کننده (N14b).

``installer/SmartBusinessLocal.iss`` با ``AppMutex=SmartBusinessLocalAppMutex`` می‌فهمه برنامه باز است و (با
``CloseApplications=yes``) از کاربر می‌خواد ببنده یا خودش می‌بنده. این یک «قفلِ تک‌نمونه» **نیست** و اجرای دوم را
متوقف نمی‌کند؛ فقط برای نصب‌کننده نشانه می‌گذارد. در سیستم‌عامل‌های دیگر هیچ کاری نمی‌کنه.
"""

from __future__ import annotations

import sys

MUTEX_NAME = "SmartBusinessLocalAppMutex"

_handle = None  # تا پایانِ پردازش زنده نگه داشته می‌شه (بسته‌شدنِ handle = آزادشدنِ میوتکس)


def acquire() -> bool:
    """میوتکس را می‌سازه؛ ``True`` فقط وقتی روی ویندوز ساخته شد. هرگز exception نمی‌ده."""
    global _handle
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        _handle = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
        return bool(_handle)
    except Exception:  # noqa: BLE001 — نشانه‌ی نصب‌کننده نباید برنامه را بشکند
        return False
