"""
حالت‌های کاریِ ربات (R2): ``ModeRegistry`` — حالتِ تازه = ثبتِ یه تعریف، نه شاخه‌ی ``if`` در هر ماژول.

- ``advisor``       فقط مشاوره (بدونِ هیچ دکمه/کیبورد؛ همون پرامپتِ صاحب کسب‌وکار)
- ``shop_buttons``  فروشگاهِ دکمه‌ای (پیش‌فرضِ فروشگاه)؛ AI فقط پاسخ‌گوی پرسش‌ها (کاتالوگِ فقط‌خواندنی)
- ``shop_ai``       سفارش با AI (جریانِ ۰.۵.۰، «آزمایشی/پیشرفته»)
- ``faq_support``   پاسخ‌گویی از «سؤالات متداول» + پشتیبانیِ انسانی، بدونِ سبد/فروش
- ``lead_capture``  جمع‌آوریِ «سرنخ» با فیلدهای قابل‌تنظیم + اعلان به مالک
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModeDef:
    id: str
    buttons: bool = False  # کیبوردِ پایدار + callbackها (ShopFlow)
    ai_qa: bool = False  # AI فقط پاسخ‌گوی پرسش‌ها (QaAgent) — بدونِ ابزارِ سفارش
    cart: bool = False
    fields: bool = False
    handoff: bool = False
    faq: bool = False
    store_agent: bool = False  # ایجنتِ سفارشِ ۰.۵.۰
    needs_store: bool = False  # فقط وقتی business_mode == store


MODES = {
    "advisor": ModeDef("advisor"),
    "shop_buttons": ModeDef("shop_buttons", buttons=True, ai_qa=True, cart=True, fields=True, handoff=True, faq=True, needs_store=True),
    "shop_ai": ModeDef("shop_ai", store_agent=True, needs_store=True),
    "faq_support": ModeDef("faq_support", buttons=True, ai_qa=True, handoff=True, faq=True),
    "lead_capture": ModeDef("lead_capture", buttons=True, ai_qa=True, fields=True, handoff=True, faq=True),
}
DEFAULT_STORE_MODE = "shop_buttons"
DEFAULT_CONSULT_MODE = "advisor"


def resolve_mode(settings, platform: str = "") -> ModeDef:
    """حالتِ مؤثر برای یه پلتفرم: override پلتفرم → ``shop_mode`` → پیش‌فرض. مقدارِ نامعتبر یا ناسازگار با
    نوعِ کسب‌وکار (مثلاً فروشگاه برای مشاور) هرگز exception نمی‌ده؛ به پیش‌فرضِ امن برمی‌گرده."""
    is_store = getattr(settings, "business_mode", "") == "store"
    overrides = getattr(settings, "shop_mode_overrides", None) or {}
    wanted = (overrides.get(platform) if isinstance(overrides, dict) else None) or getattr(settings, "shop_mode", "") or ""
    mode = MODES.get(wanted)
    if mode is None or (mode.needs_store and not is_store):
        return MODES[DEFAULT_STORE_MODE if is_store else DEFAULT_CONSULT_MODE]
    return mode


def mode_ids() -> list:
    return list(MODES)
