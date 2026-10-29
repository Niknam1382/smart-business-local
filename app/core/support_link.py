"""ساختِ لینکِ حمایتِ دارمت (N15) — فقط سمتِ برنامه؛ هیچ‌وقت داخلِ رباتِ مشتری.

قواعد (تصمیمِ مالک): مبلغ «تومان» و پیام را کاربر خودش تایپ می‌کنه؛ هیچ مبلغ/پیامِ آماده؛ سقفِ پیام ۱۰۰ کاراکتر؛
برنامه هیچ لینکِ حمایتی رو خودکار/زمان‌بندی‌شده نمی‌سازه و توکنِ API دارمت هرگز در برنامه نمی‌آید.
"""

from __future__ import annotations

import unicodedata
from typing import Optional
from urllib.parse import quote

from app import branding

MAX_AMOUNT_TOMAN = 100_000_000
_DIGITS = {ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")}
_DIGITS.update({ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")})
_THOUSANDS = {",", "٬", "،", " ", "\u00a0", "\u202f", "\u200c"}
# کاراکترهای bidi/جهت‌دهی؛ نیم‌فاصله (U+200C) و ZWJ برای فارسی/ایموجی مجازند
_BIDI = set("\u200e\u200f\u061c\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


class SupportLinkError(ValueError):
    """خطای اعتبارسنجیِ فرمِ حمایت (پیامِ فارسیِ قابل‌نمایش)."""


def parse_amount_toman(raw: str) -> int:
    """مبلغِ تومان از ورودیِ کاربر: ارقامِ فارسی/عربی نرمال، جداکننده‌ی هزارگان مجاز، فقط عددِ صحیحِ مثبت."""
    text = (raw or "").strip().translate(_DIGITS)
    if not text:
        raise SupportLinkError("مبلغ رو (به تومان) وارد کن.")
    cleaned = "".join(ch for ch in text if ch not in _THOUSANDS)
    if not cleaned.isascii() or not cleaned.isdigit():
        raise SupportLinkError("مبلغ فقط باید عدد باشه (بدونِ حروف، ممیز یا علامت).")
    amount = int(cleaned)
    if amount <= 0:
        raise SupportLinkError("مبلغ باید بیشتر از صفر باشه.")
    if amount > MAX_AMOUNT_TOMAN:
        raise SupportLinkError(f"مبلغ خیلی بزرگه (حداکثر {MAX_AMOUNT_TOMAN:,} تومان).")
    return amount


def utf16_len(text: str) -> int:
    """طولِ پیام به‌شیوه‌ی محافظه‌کارانه (واحدهای UTF-16، مثلِ JavaScript) تا ایموجی‌ها کمتر از واقع شمرده نشن."""
    return len(text.encode("utf-16-le")) // 2


def clean_message(raw: Optional[str]) -> str:
    """پیامِ اختیاری: بدونِ کاراکترِ کنترلی/bidi و بدونِ خطِ جدید؛ سقفِ ``DARAMET_MESSAGE_MAX``."""
    text = unicodedata.normalize("NFC", (raw or "").strip())
    if not text:
        return ""
    if "\n" in text or "\r" in text:
        raise SupportLinkError("پیام باید یک خط باشه (بدونِ خطِ جدید).")
    for ch in text:
        if ch in _BIDI or unicodedata.category(ch) == "Cc":
            raise SupportLinkError("پیام کاراکترِ کنترلی یا جهت‌دهیِ غیرمجاز داره.")
    if utf16_len(text) > branding.DARAMET_MESSAGE_MAX:
        raise SupportLinkError(f"پیام حداکثر {branding.DARAMET_MESSAGE_MAX} کاراکتر می‌تونه باشه.")
    return text


def message_counter(raw: Optional[str]) -> str:
    """شمارنده‌ی زنده‌ی فرم: «۲۳/۱۰۰» به‌صورتِ ``23/100`` (ارقامِ لاتین برای سازگاری با فونت)."""
    return f"{min(utf16_len(raw or ''), 9999)}/{branding.DARAMET_MESSAGE_MAX}"


def build_support_link(amount_raw: str, message_raw: Optional[str] = "") -> str:
    """لینکِ وب‌اینتنتِ دارمت. پیامِ خالی ⇒ پارامترِ ``message`` اصلاً نمی‌آید.
    اگه ``DARAMET_WEBINTENT_ENABLED`` خاموش باشه فقط لینکِ پروفایل برمی‌گرده."""
    if not branding.DARAMET_WEBINTENT_ENABLED:
        return branding.daramet_profile_url()
    amount = parse_amount_toman(amount_raw)
    message = clean_message(message_raw)
    url = f"{branding.daramet_profile_url()}?webintent&donate={amount}"
    if message:
        url += "&message=" + quote(message, safe="")
    return url
