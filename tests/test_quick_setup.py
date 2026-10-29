"""N3: «راه‌اندازیِ سریع» — پیش‌فرض‌های هر نوعِ کسب‌وکار، بدونِ دست‌زدن به توکن/پرداخت/متن‌ها، و اجرای دوباره بی‌اثر."""

import copy
from dataclasses import fields

import pytest

from app.core import checkout_fields as cf
from app.core import modes, quick_setup
from app.core.settings import AppSettings

UNTOUCHED = (
    "telegram_token_enc", "bale_token_enc", "api_key_enc", "card_to_card_number", "card_holder_name", "bale_pay_enabled",
    "faq_items", "custom_buttons", "bot_texts", "working_hours", "bot_bio_text", "owner_ids", "system_prompt", "user_name",
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
    s.shop_mode, s.catalog_page_size, s.max_qty_per_item, s.ai_disclosure_enabled = "faq_support", 3, 2, False
    s.checkout_fields = [{"id": "x", "label": "ایکس", "prompt": "؟", "type": "text", "required": True, "applies_to": "all", "regex": "", "choices": [], "min_len": 1, "max_len": 20}]
    return s


def snapshot(settings):
    return {f.name: copy.deepcopy(getattr(settings, f.name, None)) for f in fields(settings) if f.name in UNTOUCHED}


@pytest.mark.parametrize("preset", [p.id for p in quick_setup.PRESETS if p.store_only])
def test_store_presets_set_mode_form_and_defaults_and_nothing_else(preset):
    s = dirty_store()
    before = snapshot(s)
    changes = quick_setup.apply(s, preset)
    wanted = quick_setup._BY_ID[preset]
    assert modes.resolve_mode(s).id == wanted.mode == "shop_buttons"
    assert [f.id for f in cf.load_fields(s)] == [f.id for f in cf.templates("fa")[wanted.form]]
    assert cf.validate_all(s.checkout_fields) is None
    assert s.catalog_page_size == 6 and s.max_qty_per_item == 10 and s.ai_disclosure_enabled is True
    assert changes and all(isinstance(c, str) and c for c in changes)
    assert snapshot(s) == before  # توکن/پرداخت/FAQ/دکمه/متن/بیو/پرامپت دست‌نخورده


@pytest.mark.parametrize("preset,expected_mode", [("consult", "advisor"), ("support", "faq_support")])
def test_non_store_presets_work_for_consultants_and_stores(preset, expected_mode):
    for business in ("consultant", "store"):
        s = store()
        s.business_mode = business
        before = snapshot(s)
        quick_setup.apply(s, preset)
        assert modes.resolve_mode(s).id == expected_mode
        assert snapshot(s) == before


def test_applying_twice_is_a_no_op():
    for preset in quick_setup.PRESETS:
        s = dirty_store()
        assert quick_setup.apply(s, preset.id)
        again = copy.deepcopy(vars(s))
        assert quick_setup.apply(s, preset.id) == []
        assert vars(s) == again


def test_consultants_cannot_use_shop_presets_and_unknown_is_rejected():
    s = AppSettings()
    s.business_mode = "consultant"
    assert quick_setup.available(s) == ["consult", "support"]
    with pytest.raises(ValueError):
        quick_setup.apply(s, "physical")
    with pytest.raises(ValueError):
        quick_setup.apply(s, "nonsense")
    assert quick_setup.available(store()) == [p.id for p in quick_setup.PRESETS]


def test_english_bots_get_english_form_labels_and_english_change_list():
    s = dirty_store()
    s.bot_language = "en"
    changes = quick_setup.apply(s, "services", "en")
    assert any("Order form" in c and "Name" in c for c in changes)
    assert [f.label for f in cf.load_fields(s)][0] == "Name"
    fa = dirty_store()
    assert any("فرمِ سفارش" in c for c in quick_setup.apply(fa, "services", "fa"))
    assert quick_setup.apply(store(), "physical") == []  # فروشگاهِ تازه از قبل همین پیش‌فرض‌هاست


def test_titles_and_descriptions_exist_in_both_languages_without_jargon():
    for p in quick_setup.PRESETS:
        for lang in ("fa", "en"):
            assert quick_setup.title(p.id, lang) and quick_setup.description(p.id, lang)
            assert "callback" not in quick_setup.description(p.id, lang).lower()
