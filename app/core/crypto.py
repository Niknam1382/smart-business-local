"""
رمزنگاری اسرار (کلید API، توکن ربات‌ها) با Fernet — همون الگویی که در نسخه‌ی
SaaS «کسب‌وکار هوشمند» برای رمزنگاری توکن ربات‌ها استفاده شده.

کلید رمزنگاری یک‌بار روی سیستم خودِ کاربر ساخته و ذخیره می‌شه و هیچ‌وقت به
جایی فرستاده نمی‌شه.
"""

from __future__ import annotations

import stat

from cryptography.fernet import Fernet, InvalidToken

from app.core.paths import get_app_data_dir

_KEY_FILE_NAME = "secret.key"


def _key_path():
    return get_app_data_dir() / _KEY_FILE_NAME


def get_or_create_key() -> bytes:
    path = _key_path()
    if path.exists():
        return path.read_bytes()
    key = Fernet.generate_key()
    path.write_bytes(key)
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # فقط همین کاربر بتونه بخونه/بنویسه
    except OSError:
        pass  # روی ویندوز ممکنه chmod این‌طوری اثر نکنه؛ بی‌خطره
    return key


def encrypt(plaintext: str) -> str:
    if not plaintext:
        return ""
    f = Fernet(get_or_create_key())
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> str:
    if not token:
        return ""
    f = Fernet(get_or_create_key())
    try:
        return f.decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return ""
