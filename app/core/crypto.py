"""
رمزنگاری اسرار (کلید API، توکن ربات‌ها) با Fernet — همون الگویی که در نسخه‌ی
SaaS «کسب‌وکار هوشمند» برای رمزنگاری توکن ربات‌ها استفاده شده.

کلید رمزنگاری یک‌بار روی سیستم خودِ کاربر ساخته و ذخیره می‌شه و هیچ‌وقت به
جایی فرستاده نمی‌شه.

۱٫۲٫۲: فایلِ کلیدِ خالی/خراب دیگر برنامه را از کار نمی‌اندازد؛ کلیدِ خراب کنار گذاشته می‌شود
(``secret.key.bad-…``)، کلیدِ تازه با نوشتنِ اتمیک ساخته می‌شود و ``problem()`` به رابط خبر می‌دهد تا
به کاربر بگوید توکن‌ها باید دوباره وارد شوند. نوشتنِ کلید هم اتمیک است (کرشِ وسطِ نوشتن فایلِ نیمه‌کاره نمی‌گذارد).
"""

from __future__ import annotations

import logging
import os
import stat
import time

from cryptography.fernet import Fernet, InvalidToken

from app.core.paths import get_app_data_dir

logger = logging.getLogger(__name__)

_KEY_FILE_NAME = "secret.key"

PROBLEM_KEY_RESET = "key_reset"  # فایلِ کلید خراب/خالی بود و کلیدِ تازه ساخته شد
PROBLEM_UNREADABLE = "unreadable"  # مقدارِ رمزشده با کلیدِ فعلی باز نشد (کلیدِ گم‌شده/عوض‌شده)

_problem = ""


def problem() -> str:
    """``""`` یا یکی از ``PROBLEM_*``؛ رابط برایِ نمایشِ هشدارِ فارسی از آن می‌خواند."""
    return _problem


def clear_problem() -> None:
    global _problem
    _problem = ""


def _key_path():
    return get_app_data_dir() / _KEY_FILE_NAME


def _valid(raw: bytes) -> bool:
    try:
        Fernet(raw)
    except Exception:  # noqa: BLE001 — ValueError/TypeError برایِ کلیدِ خالی/کوتاه/نامعتبر
        return False
    return True


def _write_key_atomic(path, key: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(key)
    try:
        tmp.chmod(stat.S_IRUSR | stat.S_IWUSR)  # فقط همین کاربر بتونه بخونه/بنویسه
    except OSError:
        pass  # روی ویندوز ممکنه chmod این‌طوری اثر نکنه؛ بی‌خطره
    os.replace(tmp, path)


def get_or_create_key() -> bytes:
    global _problem
    path = _key_path()
    if path.exists():
        try:
            raw = path.read_bytes().strip()
        except OSError:
            raw = b""
        if _valid(raw):
            return raw
        # کلیدِ خراب: کنار بگذار (برایِ بازیابیِ دستی)، کلیدِ تازه بساز، و خبر بده
        try:
            os.replace(path, path.with_name(f"{_KEY_FILE_NAME}.bad-{int(time.time())}"))
        except OSError:
            pass
        _problem = PROBLEM_KEY_RESET
        logger.error("فایلِ secret.key خالی یا خراب بود؛ کلیدِ تازه ساخته شد (توکن‌ها باید دوباره وارد شوند)")
    key = Fernet.generate_key()
    _write_key_atomic(path, key)
    return key


def encrypt(plaintext: str) -> str:
    if not plaintext:
        return ""
    f = Fernet(get_or_create_key())
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> str:
    global _problem
    if not token:
        return ""
    f = Fernet(get_or_create_key())
    try:
        return f.decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        if not _problem:
            _problem = PROBLEM_UNREADABLE
            logger.error("یک مقدارِ رمزشده با کلیدِ فعلی باز نشد (کلیدِ گم‌شده یا عوض‌شده)")
        return ""
