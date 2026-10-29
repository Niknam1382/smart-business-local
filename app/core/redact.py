"""
پاک‌کردن اسرار (توکن ربات، آدرس پروکسی با رمز) از هر متنی که قراره توی لاگ یا
پیام خطای UI بیاد.

چرا لازمه: کاربر ممکنه فایل لاگ (bot.log) رو برای رفع اشکال یا توی یه issue
گیت‌هاب به اشتراک بذاره. پیام خطای برخی کتابخونه‌های HTTP (مثلاً aiohttp)
می‌تونه آدرس کامل درخواست رو داشته باشه و آدرس API بله/تلگرام شامل خودِ
توکنه (``/bot<TOKEN>/getMe``). پس هر متنی قبل از نوشته‌شدن از این‌جا رد می‌شه.
"""

from __future__ import annotations

import re

_MASK = "***"

# شکل عمومی توکن ربات تلگرام/بله: «عدد:رشته‌ی طولانی» — حتی اگه خودِ توکن رو
# به تابع ندیم، این الگو جلوی درز اتفاقی رو می‌گیره. عمداً بدون \b اول: توی
# آدرس API توکن درست بعد از «bot» میاد (``/bot123:ABC``) و بین «t» و «1» مرز
# کلمه وجود نداره — تست واقعی همین باگ رو گرفت.
# مرچنت‌کد زرین‌پال (UUID) و توکنِ درگاهِ بله‌پی (مثل WALLET-...): اعتبارنامه‌ان و نباید توی لاگ/issue بیان
_UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_WALLET_TOKEN = re.compile(r"\bWALLET-[A-Za-z0-9_\-]{6,}")
_TOKEN_SHAPE = re.compile(r"\d{6,}:[A-Za-z0-9_\-]{20,}")
# اعتبارنامه‌ی داخل آدرس (proxy): scheme://user:pass@host
_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@")


def redact(text: str, *secrets: str) -> str:
    """هر یک از ``secrets`` (اگه حداقل ۴ کاراکتر باشه) و هر الگوی شبیه توکن یا
    ``user:pass@`` داخل آدرس رو با ``***`` عوض می‌کنه."""
    if not text:
        return text
    for secret in secrets:
        if secret and len(secret) >= 4:
            text = text.replace(secret, _MASK)
    text = _URL_CREDENTIALS.sub(lambda m: f"{m.group('scheme')}{_MASK}@", text)
    text = _TOKEN_SHAPE.sub(_MASK, text)
    text = _UUID.sub(_MASK, text)
    text = _WALLET_TOKEN.sub(_MASK, text)
    return text
