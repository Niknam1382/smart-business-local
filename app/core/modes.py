"""
حالت‌های کاریِ ربات — در نسخه‌ی ۱.۰.۰ دقیقاً دو تا هستن، همان‌قدر که مالک خواسته:

- ``advisor``       مشاوره‌ای: ربات فقط با «سیستم‌پرامپتِ» صاحب کسب‌وکار حرف می‌زنه. هیچ دکمه‌ای،
                    هیچ سبدی، هیچ فروشی. هرچه رفتار ربات باشد، همان چیزی است که فروشنده می‌نویسد.
- ``shop_buttons``  فروشگاهی: فروشگاهِ دکمه‌ای با چهار دکمه (محصولات / سبد خرید / سفارش‌های من /
                    ارتباط با پشتیبانی). مدل فقط به سؤال‌ها جواب می‌دهد و حداکثر کارت محصول
                    نشان می‌دهد؛ دستِ آن به سبد، سفارش و پرداخت نمی‌رسه (ناوردا ۱).

``faq_support`` و ``lead_capture`` حذف شدن: پاسخِ سؤالات متداول و پشتیبانیِ انسانی در همان
دکمه‌ی «ارتباط با پشتیبانی» و گفتگویِ عادیِ ربات جا می‌شن، بدونِ حالتِ سوم و چهارم.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModeDef:
    id: str
    buttons: bool = False  # کیبوردِ پایدار + callbackها (ShopFlow)
    ai_qa: bool = False  # مدل فقط پاسخ‌گوی پرسش‌ها (QaAgent) — بدونِ ابزارِ سفارش
    cart: bool = False
    fields: bool = False
    handoff: bool = False
    faq: bool = False
    needs_store: bool = False  # فقط وقتی business_mode == store


MODES = {
    "advisor": ModeDef("advisor"),
    "shop_buttons": ModeDef("shop_buttons", buttons=True, ai_qa=True, cart=True, fields=True, handoff=True, faq=True, needs_store=True),
}
DEFAULT_STORE_MODE = "shop_buttons"
DEFAULT_CONSULT_MODE = "advisor"


def is_store(settings) -> bool:
    return getattr(settings, "business_mode", "") == "store"


def resolve_mode(settings, platform: str = "") -> ModeDef:
    """حالتِ مؤثر. مقدارِ قدیمیِ ذخیره‌شده (``shop_ai``، ``faq_support``، ``lead_capture``) هرگز
    exception نمی‌ده؛ به حالتِ امنِ همان نوع کسب‌وکار برمی‌گرده."""
    return MODES[DEFAULT_STORE_MODE] if is_store(settings) else MODES[DEFAULT_CONSULT_MODE]


def mode_ids() -> list:
    return list(MODES)
