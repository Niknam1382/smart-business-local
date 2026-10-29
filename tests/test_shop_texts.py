"""R13 — متن‌های قابل‌تنظیم و دوزبانه‌ی ربات."""

import pytest

from app.core import shop_texts
from app.core.orders import Order, OrderItem, build_order_confirmed_text, build_order_summary_text
from app.core.settings import AppSettings
from app.core.shop_texts import TextError


def _order():
    return Order(
        id=7, platform="telegram", chat_id="1", status="confirmed", payment_method="card_to_card", payment_reference="",
        total_irr=2_400_000, note="", created_at="", updated_at="",
        items=[OrderItem(1, "هدفون", 1_200_000, 2)],
    )


def test_default_persian_text_is_unchanged():
    assert build_order_summary_text(_order()) == "سفارش #7\n- هدفون ×2 = 2,400,000 ریال\nجمع کل: 2,400,000 ریال"
    assert build_order_confirmed_text(_order()).startswith("سفارشتون تایید شد 🎉\n\nسفارش #7")
    assert shop_texts.t("pay.left", minutes=5) == "⏳ تا 5 دقیقه‌ی دیگه موجودی برات رزرو شده."


def test_every_key_has_both_languages_and_valid_placeholders():
    for key in shop_texts.keys():
        for lang in shop_texts.SUPPORTED_LANGS:
            assert shop_texts.default(key, lang).strip(), (key, lang)
        assert shop_texts.placeholders(key) == set(shop_texts._fields(shop_texts.default(key, "fa"))) | set(
            shop_texts._fields(shop_texts.default(key, "en"))
        )


def test_language_switch_and_auto_mode():
    s = AppSettings()
    shop_texts.configure(lambda: s)
    assert shop_texts.t("pay.already_paid").startswith("این سفارش")
    s.bot_language = "en"
    assert shop_texts.t("pay.already_paid") == "This order has already been paid ✅"
    s.bot_language = "auto"
    assert shop_texts.render(s, "pay.already_paid", lang=None).startswith("این")  # بدون language_code = فارسی
    assert shop_texts.resolve_lang(s, "en-US") == "en" and shop_texts.resolve_lang(s, "fa") == "fa"
    s.bot_language = "klingon"
    assert shop_texts.resolve_lang(s) == "fa"


def test_owner_override_is_applied_and_validated():
    s = AppSettings()
    shop_texts.configure(lambda: s)
    shop_texts.set_override(s, "order.confirmed_tail", "fa", "ممنون که از «فروشگاه ما» خرید کردی 🌸")
    assert build_order_confirmed_text(_order()).endswith("ممنون که از «فروشگاه ما» خرید کردی 🌸")
    shop_texts.set_override(s, "order.confirmed_tail", "en", "Thanks!")
    s.bot_language = "en"
    assert shop_texts.t("order.confirmed_tail") == "Thanks!"
    shop_texts.set_override(s, "order.confirmed_tail", "fa", "")  # حذفِ override
    s.bot_language = "fa"
    assert shop_texts.t("order.confirmed_tail") == "ممنون از خریدتون!"


@pytest.mark.parametrize(
    "key,text,match",
    [
        ("pay.left", "{minutes} و {bogus}", "ناشناخته"),
        ("pay.left", "{minutes.__class__}", "نامعتبر"),
        ("pay.left", "{minutes!r}", "نامعتبر"),
        ("pay.left", "{minutes:>10}", "نامعتبر"),
        ("pay.left", "باز {minutes", "آکولاد"),
        ("pay.left", "x" * 2000, "بلنده"),
        ("no.such.key", "x", "وجود نداره"),
    ],
)
def test_invalid_overrides_are_rejected(key, text, match):
    s = AppSettings()
    with pytest.raises(TextError, match=match):
        shop_texts.set_override(s, key, "fa", text)
    assert s.bot_texts == {}


def test_render_never_raises_even_with_corrupt_settings_or_missing_params():
    s = AppSettings()
    s.bot_texts = {"fa": {"pay.left": "{minutes} {gone}", "order.head": 123}, "en": "oops"}
    assert shop_texts.render(s, "pay.left", minutes=3) == "⏳ تا 3 دقیقه‌ی دیگه موجودی برات رزرو شده."  # override معیوب → پیش‌فرض
    assert shop_texts.render(s, "order.head", order_id=1) == "سفارش #1"
    assert shop_texts.render(s, "pay.left") == shop_texts.default("pay.left")  # پارامترِ گم‌شده: قالبِ خام، بدونِ exception
    assert shop_texts.render(s, "does.not.exist") == "does.not.exist"


def test_user_values_with_braces_are_not_reinterpreted():
    s = AppSettings()
    out = shop_texts.render(s, "order.item", name="{x.__class__}", qty=1, amount="5")
    assert "{x.__class__}" in out
