"""متنِ خطایِ قابل‌فهم برای کاربر (۱٫۲٫۰): مشکل چیست و قدمِ بعدی چیست — نه نامِ کلاس، traceback یا کدِ فنی.

خطاهایِ دامنه‌ی خودِ برنامه (``OrderError``، ``BackupError``…) از قبل پیامِ فارسیِ روشن دارند و همان‌طور نشان داده
می‌شوند؛ فقط خطاهایِ خامِ سیستم/شبکه/دیتابیس ترجمه می‌شوند. فقط stdlib.
"""

from __future__ import annotations

import errno
import socket
import sqlite3
import urllib.error

_FA = {
    "permission": "دسترسی به این فایل یا پوشه ممکن نیست. برنامه‌هایی را که آن را باز کرده‌اند ببند یا پوشه‌ی دیگری انتخاب کن.",
    "missing": "فایل یا پوشه پیدا نشد؛ شاید جابه‌جا یا پاک شده باشد.",
    "space": "جای خالیِ دیسک کافی نیست. فضا باز کن یا مسیرِ دیگری انتخاب کن.",
    "timeout": "پاسخی نیامد. اینترنت یا VPN را بررسی کن و دوباره امتحان کن.",
    "network": "اتصال به اینترنت برقرار نشد. اینترنت یا VPN را بررسی کن و دوباره امتحان کن.",
    "busy": "پایگاه‌داده همین الان مشغول است. چند ثانیه صبر کن و دوباره امتحان کن.",
    "generic": "مشکلی پیش آمد. دوباره امتحان کن؛ اگر تکرار شد، گزارشِ عیب‌یابی بگیر و برایِ پشتیبان بفرست.",
}
_EN = {
    "permission": "Access to this file or folder is not possible. Close programs that may have it open, or pick another folder.",
    "missing": "The file or folder was not found; it may have been moved or deleted.",
    "space": "There is not enough free disk space. Free some space or pick another location.",
    "timeout": "No answer arrived. Check your internet/VPN and try again.",
    "network": "Could not connect to the internet. Check your internet/VPN and try again.",
    "busy": "The database is busy right now. Wait a few seconds and try again.",
    "generic": "Something went wrong. Try again; if it keeps happening, create a troubleshooting report and send it to support.",
}


def _has_persian(text: str) -> bool:
    return any("\u0600" <= ch <= "\u06ff" for ch in text)


def friendly_error(exc: BaseException, lang: str = "fa") -> str:
    table = _FA if lang != "en" else _EN
    if isinstance(exc, PermissionError):
        return table["permission"]
    if isinstance(exc, FileNotFoundError):
        return table["missing"]
    if isinstance(exc, OSError) and getattr(exc, "errno", None) in (errno.ENOSPC, getattr(errno, "EDQUOT", -1)):
        return table["space"]
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return table["timeout"]
    if isinstance(exc, urllib.error.HTTPError):
        return table["network"]
    if isinstance(exc, (ConnectionError, urllib.error.URLError, socket.gaierror)):
        return table["network"]
    if isinstance(exc, sqlite3.OperationalError) and "lock" in str(exc).lower():
        return table["busy"]
    text = str(exc).strip()
    if lang != "en" and text and _has_persian(text) and len(text) <= 300:
        return text  # پیامِ فارسیِ خودِ برنامه (خطای دامنه)
    if lang == "en" and text and not _has_persian(text) and type(exc).__module__ == "app.core.orders":
        return text
    return table["generic"]
