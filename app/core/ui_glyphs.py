"""نمادهای دکمه‌ها به‌ازای هر پلتفرم (N4).

ایموجیِ ➖/➕ در بله کم‌رنگ/نامشخص رندر می‌شه (سرورِ جعلی این رو نمی‌بینه؛ مالک روی بلهِ اندروید و iOS تأیید می‌کنه).
پس برای بله نمادِ متنیِ ساده («−» و «+») و برچسبِ متنیِ «حذف» داریم؛ تلگرام همان ایموجی‌های آشنا را نگه می‌دارد.
همه‌ی نقاطِ رابط (کارتِ محصول، سبد) فقط از همین‌جا نماد می‌گیرن تا یکسان بمانند.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class Glyphs:
    minus: str
    plus: str
    remove: str  # دکمه‌ی حذفِ یک قلم از سبد (وقتی تعداد ۱ است، «−» همین می‌شه)
    details: str  # «جزئیات» روی کارتِ پیشنهادیِ محصول


_TELEGRAM = Glyphs(minus="➖", plus="➕", remove="🗑", details="ℹ️ جزئیات")
# بله: بدونِ ایموجی‌ی تنها؛ همیشه حداقل یک حرفِ واقعی یا نمادِ متنی
_BALE = Glyphs(minus="−", plus="+", remove="حذف", details="جزئیات")
_BALE_EN = Glyphs(minus="−", plus="+", remove="Remove", details="Details")
_TELEGRAM_EN = Glyphs(minus="➖", plus="➕", remove="🗑", details="ℹ️ Details")


def for_platform(platform: str, lang: str = "fa") -> Glyphs:
    if platform == "bale":
        return _BALE_EN if lang == "en" else _BALE
    return _TELEGRAM_EN if lang == "en" else _TELEGRAM


def is_emoji_only(label: str) -> bool:
    """آیا برچسب هیچ حرف/رقمِ واقعی نداره؟ (فقط ایموجی/نماد/فاصله) — «−» و «+» نمادِ ریاضی‌اند و مجاز."""
    text = (label or "").strip()
    if not text:
        return True
    if text in {"−", "+", "-"}:
        return False
    for ch in text:
        if 0x2100 <= ord(ch) <= 0x214F:  # Letterlike Symbols (مثلِ ℹ) در یونیکد «حرف» حساب می‌شن ولی ایموجی‌اند
            continue
        if unicodedata.category(ch).startswith(("L", "N")):  # حرف یا عدد
            return False
    return True
