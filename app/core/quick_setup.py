"""«راه‌اندازیِ سریع» (N3): نوعِ کسب‌وکار → پیش‌فرض‌های درستِ ربات (حالت، فرمِ سفارش، تعدادها) با یک دکمه.

فقط تنظیماتِ «تجربه‌ی ربات» عوض می‌شه؛ به توکن/کلیدِ AI، روش‌های پرداخت (کارت، بله‌پی، زرین‌پال)، مدیران، سؤالاتِ
متداول، دکمه‌های سفارشی، متن‌های سفارشی، ساعتِ کاری و بیوگرافی دست نمی‌زنه. اجرای دوباره بی‌اثره (idempotent).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from app.core import checkout_fields as cf
from app.core import modes

DEFAULT_PAGE_SIZE = 6
DEFAULT_MAX_QTY = 10


@dataclass(frozen=True)
class Preset:
    id: str
    store_only: bool
    mode: str
    form: Optional[str]  # کلیدِ قالبِ فرمِ سفارش در checkout_fields.templates


PRESETS = (
    Preset("physical", True, "shop_buttons", "physical"),
    Preset("digital", True, "shop_buttons", "digital"),
    Preset("services", True, "shop_buttons", "services"),
    Preset("consult", False, "advisor", None),
    Preset("support", False, "faq_support", None),
)
_BY_ID = {p.id: p for p in PRESETS}

_TEXT = {
    "physical": ("فروشگاهِ کالای فیزیکی", "Physical goods shop", "فروشگاهِ دکمه‌ای؛ فرمِ سفارش: نام، موبایل، آدرس، کدپستی و توضیحات.", "Button shop; order form: name, phone, address, postal code and notes."),
    "digital": ("محصولِ دیجیتال (فایل، لینک، کلید)", "Digital products (files, links, keys)", "فروشگاهِ دکمه‌ای؛ فرمِ سفارش: فقط نام، ایمیل و موبایلِ اختیاری (بدونِ آدرس).", "Button shop; order form: name, optional email and phone (no address)."),
    "services": ("خدمات (سفارشِ خدمت)", "Services (orders for a service)", "فروشگاهِ دکمه‌ای؛ فرمِ سفارش: نام، موبایل و توضیحِ درخواست.", "Button shop; order form: name, phone and a description of the request."),
    "consult": ("مشاوره (فقط گفتگو)", "Consulting (chat only)", "ربات فقط با هوش مصنوعی گفتگو و مشاوره می‌ده؛ بدونِ دکمه و سبد.", "The bot only chats and advises with AI; no buttons or cart."),
    "support": ("پاسخ‌گویی و پشتیبانی", "Answers & support", "پاسخ از «سؤالات متداول» و هوش مصنوعی + اتصال به پشتیبانِ انسانی؛ بدونِ فروش.", "Answers from your FAQ and AI + a link to a human; no selling."),
}
_MODE_NAME = {
    "shop_buttons": ("فروشگاه (دکمه‌ای)", "Button shop"),
    "advisor": ("مشاوره", "Consulting"),
    "faq_support": ("پاسخ‌گویی + پشتیبانی", "Answers + support"),
}


def title(preset_id: str, lang: str = "fa") -> str:
    fa, en, _dfa, _den = _TEXT[preset_id]
    return en if lang == "en" else fa


def description(preset_id: str, lang: str = "fa") -> str:
    _fa, _en, dfa, den = _TEXT[preset_id]
    return den if lang == "en" else dfa


def available(settings) -> list:
    """پیش‌تنظیم‌های مناسبِ نوعِ کسب‌وکارِ فعلی (مشاور: بدونِ فروشگاه)."""
    is_store = getattr(settings, "business_mode", "") == "store"
    return [p.id for p in PRESETS if is_store or not p.store_only]


def apply(settings, preset_id: str, lang: str = "fa") -> list:
    """پیش‌تنظیم را اعمال می‌کنه و فهرستِ «چه چیزی عوض شد» (به زبانِ ``lang``) را برمی‌گردونه؛ خالی = از قبل همین بود."""
    preset = _BY_ID.get(preset_id)
    if preset is None:
        raise ValueError("پیش‌تنظیمِ ناشناخته.")
    if preset_id not in available(settings):
        raise ValueError("این پیش‌تنظیم مخصوصِ فروشگاه است.")
    en = lang == "en"
    changes: list = []

    old_mode = modes.resolve_mode(settings).id
    settings.shop_mode = preset.mode
    if old_mode != preset.mode:
        fa_name, en_name = _MODE_NAME[preset.mode]
        changes.append(("Bot mode: " if en else "حالتِ ربات: ") + (en_name if en else fa_name))

    if preset.form:
        wanted = [asdict(f) for f in cf.templates("en" if getattr(settings, "bot_language", "fa") == "en" else "fa")[preset.form]]
        error = cf.validate_all(wanted)
        if error:  # نباید رخ بده؛ قالب‌ها تست می‌شن
            raise ValueError(error)
        current = [asdict(f) for f in cf.load_fields(settings)]
        if [f["id"] for f in current] != [f["id"] for f in wanted] or current != wanted:
            settings.checkout_fields = wanted
            names = ("، " if not en else ", ").join(f["label"] for f in wanted)
            changes.append(("Order form: " if en else "فرمِ سفارش: ") + names)

    for attr, value, fa_label, en_label in (
        ("ai_disclosure_enabled", True, "هشدارِ «پاسخ با هوش مصنوعی» روشن", "AI-answer notice on"),
        ("catalog_page_size", DEFAULT_PAGE_SIZE, f"{DEFAULT_PAGE_SIZE} محصول در هر صفحه", f"{DEFAULT_PAGE_SIZE} products per page"),
        ("max_qty_per_item", DEFAULT_MAX_QTY, f"حداکثر {DEFAULT_MAX_QTY} عدد از هر محصول", f"at most {DEFAULT_MAX_QTY} of each product"),
    ):
        if getattr(settings, attr, None) != value:
            setattr(settings, attr, value)
            changes.append(en_label if en else fa_label)
    return changes
