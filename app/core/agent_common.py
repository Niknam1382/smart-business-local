"""
اجزای مشترکِ پاسخ‌گوییِ AI در ربات بعد از حذفِ «سفارش با AI».

**AI هیچ‌وقت سبد، سفارش یا پرداخت را تغییر نمی‌ده**: ثبتِ سفارش و مدیریتِ سبد (افزودن/کم‌کردن/حذف) فقط با دکمه‌هاست.
AI فقط به پرسش‌ها جواب می‌ده (``qa_agent``) و در بهترین حالت «جزئیاتِ» محصول را نشان می‌ده.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core import shop_texts

FALLBACK_REPLY = shop_texts.default("ai.fallback")  # متنِ واقعی: shop_texts.t("ai.fallback") (قابل‌تنظیم)

# محدودیتِ «احتکارِ موجودی»: رزرو رایگانه، پس کسی می‌تونه پیاپی سفارش بسازه تا کالا رو از بقیه
# بگیره. این سقف‌ها مشتریِ واقعی رو اذیت نمی‌کنن (ویرایشِ سبد = سفارشِ جدید نیست).
MAX_ORDERS_PER_HOUR = 6
MAX_EXPIRED_UNPAID_PER_DAY = 3


@dataclass
class OutMessage:
    text: str
    buttons: list = field(default_factory=list)  # [(برچسب, url)]


@dataclass
class AgentReply:
    text: str
    outbox: list = field(default_factory=list)  # list[OutMessage]


def sanitize_display_name(name: str) -> str:
    """نامِ پروفایلِ مشتری *غیرقابل‌اعتماده* و توی پرامپتِ سیستمی می‌ره (سطحِ اعتمادِ بالا):
    فقط یه خطِ کوتاهِ بدونِ کاراکترِ کنترلی/خط‌جدید/بک‌تیک قبول می‌کنیم تا نتونه ساختارِ پرامپت
    رو بشکنه یا دستورِ جعلی جا بزنه.

    برچسب‌هایِ جهت (U+202A–202E، U+2066–2069) و نویسه‌هایِ پهنایِ صفر هم حذف می‌شن: همان‌ها
    که ``checkout_fields`` و ``invoice_pdf`` هم پاک می‌کنند — با آنها می‌شد متنی را در چشمِ مالک
    و مدل برعکس/پنهان نشان داد."""
    cleaned = re.sub(r"[\x00-\x1f\x7f\u2028\u2029\u200b-\u200f\ufeff\u202a-\u202e\u2066-\u2069`#]+", " ", name or "")
    return re.sub(r"\s+", " ", cleaned).strip()[:40]


# ============================================================ تمیزکردنِ پاسخِ مدل ====

_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.DOTALL)
_ITALIC_STAR = re.compile(r"(?<![*\w])\*([^*\n]{1,120})\*(?![*\w])")
_UNDERSCORE_IT = re.compile(r"(?<![_\w])_([^_\n]{1,120})_(?![_\w])")
_INLINE_CODE = re.compile(r"`{1,3}([^`\n]{1,400})`{1,3}")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_BULLET = re.compile(r"^\s*[-*+•]\s+", re.MULTILINE)
_TABLE_LINE = re.compile(r"^\s*\|?[\s:|-]{3,}\|?\s*$", re.MULTILINE)  # خطِ جداکننده‌ی جدولِ مارک‌داون


def plain_answer(text: str) -> str:
    """مارک‌داون را از پاسخِ مدل می‌گیرد: تلگرام (و بله) متنِ ساده می‌فرستند، پس «**قیمت**»
    همان‌طور با ستاره به چشمِ مشتری می‌آید.

    ستاره/زیرخط/بک‌تیک و سرِصفحه‌ها حذف می‌شن، لیست‌ها با «- » می‌مونند و خطِ جداکننده‌ی
    جدول (که در چت فقط شلوغی است) برداشته می‌شه. متنِ خودِ پاسخ دست‌نخورده می‌ماند.
    """
    if not text:
        return ""
    out = _BOLD.sub(lambda m: m.group(1) if m.group(1) is not None else m.group(2), text)
    out = _ITALIC_STAR.sub(r"\1", out)
    out = _UNDERSCORE_IT.sub(r"\1", out)
    out = _INLINE_CODE.sub(r"\1", out)
    out = _HEADING.sub("", out)
    out = _TABLE_LINE.sub("", out)
    out = _BULLET.sub("- ", out)
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()
