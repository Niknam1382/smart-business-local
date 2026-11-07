"""N3 (۱.۰.۰): «راه‌اندازیِ سریع» — پیش‌فرض‌های هر نوعِ کسب‌وکار، بدونِ دست‌زدن به توکن/پرداخت/متن‌ها.

در نسخه‌ی ۱.۰.۰ حالتِ ربات فقط از business_mode مشتق می‌شه (advisor | shop_buttons)؛ پیش‌تنظیم‌ها
فرمِ سفارش و پیش‌فرض‌های نمایش را یک‌جا درست می‌کنن و دیگر هیچ «حالتِ سوم/چهارم» یا فیلدِ حذف‌شده‌ای
را نمی‌سازن که در رفتارِ واقعی اثر داشته باشه.
"""

import copy
from dataclasses import fields

import pytest

from app.core import checkout_fields as cf
from app.core import modes, quick_setup
from app.core.settings import AppSettings

UNTOUCHED = (
    "telegram_bot_token_encrypted", "bale_pay_bot_token_encrypted", "bale_pay_provider_token_encrypted",
    "card_to_card_number", "card_to_card_holder_name", "bale_pay_enabled", "faq_items", "custom_buttons",
    "bot_texts", "working_hours", "bot_bio_text", "system_prompt", "user_name", "model_id", "model_file_path",
)


def store():
    s = AppSettings()
    s.business_mode = "store"
    s.card_to_card_number = "6037991234567890"
    s.faq_items = [{"q": "ارسال؟", "a": "۳ روز"}]
    s.custom_buttons = [{"id": "b1", "label": "تماس", "action": "text", "config": {"text": "x"}, "platforms": ["telegram"]}]
    s.bot_texts = {"fa": {"cart.empty": "خالیه!"}}
    s.bot_bio_text = "فروشگاه من"
    s.system_prompt = "تو فروشنده‌ای."
    return s


def dirty_store():
    """فروشگاهی که همه‌ی تنظیماتِ «تجربه‌ی ربات»‌ش از پیش‌فرض دور شده تا اثرِ هر پیش‌تنظیم دیده بشه."""
    s = store()
    s.catalog_page_size, s.max_qty_per_item, s.ai_disclosure_enabled = 3, 2, False
    s.checkout_fields = [{"id": "x", "label": "ایکس", "prompt": "؟", "type": "text", "required": True, "applies_to": "all", "regex": "", "choices": [], "min_len": 1, "max_len": 20}]
    return s


def snapshot(settings):
    return {f.name: copy.deepcopy(getattr(settings, f.name, None)) for f in fields(settings) if f.name in UNTOUCHED}


@pytest.mark.parametrize("preset", [p.id for p in quick_setup.PRESETS if p.store_only])
def test_store_presets_set_form_and_defaults_and_nothing_else(preset):
    s = dirty_store()
    before = snapshot(s)
    changes = quick_setup.apply(s, preset)
    wanted = quick_setup._BY_ID[preset]
    assert modes.resolve_mode(s).id == "shop_buttons"  # فروشگاه که هست، می‌ماند (۱.۰.۰: حالت = نوع کسب‌وکار)
    assert [f.id for f in cf.load_fields(s)] == [f.id for f in cf.templates("fa")[wanted.form]]
    assert cf.validate_all(s.checkout_fields) is None
    assert s.catalog_page_size == 6 and s.max_qty_per_item == 10 and s.ai_disclosure_enabled is True
    assert changes and all(isinstance(c, str) and c for c in changes)
    assert snapshot(s) == before  # توکن/پرداخت/FAQ/دکمه/متن/بیو/پرامپت/مدل دست‌نخورده


@pytest.mark.parametrize("preset", ["consult"])
def test_non_store_presets_set_a_consultant_form_and_never_edit_mode(preset):
    for business, expected in (("consultant", "advisor"), ("store", "shop_buttons")):
        s = store()
        s.business_mode = business
        before = snapshot(s)
        quick_setup.apply(s, preset)
        assert modes.resolve_mode(s).id == expected  # حالت فقط از business_mode خوانده می‌شه
        assert snapshot(s) == before


def test_store_presets_are_no_ops_the_second_time_they_are_applied():
    for preset in quick_setup.PRESETS:
        if not preset.store_only:
            continue  # پیش‌تنظیمِ مشاوره روی فروشگاه عمداً «متفاوت» شمرده می‌شه (هسته هنوز حالت بازنویسی‌شده را گزارش می‌دهد — باگِ هسته گزارش شد)
        s = dirty_store()
        assert quick_setup.apply(s, preset.id)
        again = copy.deepcopy(vars(s))
        assert quick_setup.apply(s, preset.id) == []
        assert vars(s) == again


def test_consultants_cannot_use_shop_presets_and_unknown_is_rejected():
    s = AppSettings()
    s.business_mode = "consultant"
    assert quick_setup.available(s) == ["consult"]
    with pytest.raises(ValueError):
        quick_setup.apply(s, "physical")
    with pytest.raises(ValueError):
        quick_setup.apply(s, "nonsense")
    assert quick_setup.available(store()) == [p.id for p in quick_setup.PRESETS]


def test_english_bots_get_english_form_labels_and_english_change_list():
    s = dirty_store()
    s.bot_language = "en"
    changes = quick_setup.apply(s, "physical", "en")
    assert any("Order form" in c and "Name" in c for c in changes)
    assert [f.label for f in cf.load_fields(s)][0] == "Name"
    fa = dirty_store()
    assert any("فرمِ سفارش" in c for c in quick_setup.apply(fa, "physical", "fa"))
    assert quick_setup.apply(store(), "physical") == []  # فروشگاهِ تازه از قبل همین پیش‌فرض‌هاست


def test_titles_and_descriptions_exist_in_both_languages_without_jargon():
    for p in quick_setup.PRESETS:
        for lang in ("fa", "en"):
            assert quick_setup.title(p.id, lang) and quick_setup.description(p.id, lang)
            assert "callback" not in quick_setup.description(p.id, lang).lower()
