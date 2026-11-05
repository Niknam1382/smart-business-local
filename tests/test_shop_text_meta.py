"""N3: متادیتای متن‌ها (عنوانِ ساده/گروه/سطح/متغیرِ فارسی/پیش‌نمایش)، سقفِ طولِ برچسب، واژه‌های ممنوع و «هر پیام قدمِ بعد را می‌گوید»."""

import re

import pytest

from app.core import shop_text_meta as meta
from app.core import shop_texts
from tests.shop_harness import Harness, datas, labels, texts

OWNER_ONLY = {"lead.owner", "deliver.failed_owner"}  # پیام‌هایی که مشتری نمی‌بینه
FORBIDDEN = ("callback", "regex", "placeholder", "payload", "session", "token", "traceback", "exception", "null", "undefined", "پارامتر", "اعتبارسنجی", "کوئری", "دیتابیس")


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


# ============================================================= پوششِ متادیتا ====

def test_every_text_key_has_metadata_and_nothing_extra():
    assert set(shop_texts.keys()) == set(meta._META)
    assert set(meta.all_keys()) == set(shop_texts.keys())


def test_groups_levels_and_basic_count_follow_the_progressive_disclosure_rule():
    group_ids = {g for g, _title in meta.groups()}
    for key in shop_texts.keys():
        m = meta.meta(key)
        assert m.group in group_ids and m.level in (meta.LEVEL_BASIC, meta.LEVEL_ADVANCED)
    basic = meta.all_keys(meta.LEVEL_BASIC)
    assert 10 <= len(basic) <= 14, basic  # «پایه ≈ ۱۲»
    assert {"menu.welcome", "pay.card.after", "order.confirmed_tail"} <= set(basic)
    assert len(meta.all_keys(group="payment")) > 10


@pytest.mark.parametrize("lang", ["fa", "en"])
def test_titles_and_when_texts_are_plain_language_without_technical_terms(lang):
    for key in shop_texts.keys():
        m = meta.meta(key, lang)
        assert m.title.strip() and m.when.strip()
        assert key not in m.title and "{" not in m.title and "_" not in m.title, (key, m.title)
        assert not re.search(r"\b[a-z]+\.[a-z_.]+\b", m.title), (key, m.title)  # شبیهِ کلیدِ فنی
        for word in FORBIDDEN:
            assert word not in m.title.lower() and word not in m.when.lower(), (key, word)
    assert len({meta.meta(k, lang).title for k in shop_texts.keys()}) == len(shop_texts.keys())  # عنوان‌ها یکتا


# ============================================================ متغیرها و نمونه ====

@pytest.mark.parametrize("lang", ["fa", "en"])
def test_every_variable_has_a_unique_plain_label_and_example(lang):
    for key in shop_texts.keys():
        vs = meta.vars_for(key, lang)
        assert {v.name for v in vs} == shop_texts.placeholders(key)
        assert len({v.label for v in vs}) == len(vs), (key, [v.label for v in vs])  # برچسب‌ها در یک پیام یکتا
        for v in vs:
            assert v.label.strip() and v.example.strip() and "_" not in v.label and "{" not in v.label, (key, v)


def test_every_default_renders_with_sample_values_in_both_languages():
    for key in shop_texts.keys():
        for lang in ("fa", "en"):
            out = meta.preview(key, meta.to_display(key, shop_texts.default(key, lang), lang), lang)
            assert out and "{" not in out and "}" not in out, (key, lang, out)


def test_display_roundtrip_is_lossless_for_all_defaults_and_languages():
    for key in shop_texts.keys():
        for lang_text in ("fa", "en"):
            raw = shop_texts.default(key, lang_text)
            for ui in ("fa", "en"):
                shown = meta.to_display(key, raw, ui)
                assert meta.from_display(key, shown, ui) == raw, (key, ui)
                for v in meta.vars_for(key, ui):
                    if v.name != v.label:
                        assert "{" + v.name + "}" not in shown, (key, shown)  # هیچ placeholderِ خام (مثلِ {order_id}) در نمایش نیست


def test_display_uses_persian_names_and_preview_shows_real_values():
    shown = meta.to_display("pay.left", shop_texts.default("pay.left", "fa"))
    assert "{تعدادِ دقیقه}" in shown
    assert meta.preview("pay.left", shown) == "⏳ تا 15 دقیقه‌ی دیگه موجودی برات رزرو شده."
    assert meta.preview("order.head", "سفارش {شماره‌ی سفارش} ثبت شد") == "سفارش 12 ثبت شد"
    assert meta.preview("cart.warn_short", "فقط {تعدادِ موجود} عدد از {نامِ محصول}") == "فقط 3 عدد از هدفون"
    # معنیِ «تعداد» در هر پیام فرق می‌کنه
    assert [v.label for v in meta.vars_for("prod.in_cart")] == ["تعدادِ داخلِ سبد"]
    assert [v.label for v in meta.vars_for("prod.max")] == ["حداکثرِ تعداد"]


def test_friendly_errors_have_no_technical_terms():
    msg = meta.friendly_error("pay.left", "تا {چیزِ ناشناخته} دقیقه")
    assert "قابل‌استفاده نیست" in msg and "{تعدادِ دقیقه}" in msg and "placeholder" not in msg.lower()
    assert meta.friendly_error("pay.left", "تا {تعدادِ دقیقه دیگه") != ""  # آکولادِ ناجور
    assert meta.friendly_error("pay.left", "تا {تعدادِ دقیقه} دیگه") == ""
    assert "can't be used" in meta.friendly_error("pay.left", "x {nope}", "en")
    assert meta.preview("pay.left", "تا {نامعتبر} دقیقه") is None


def test_unknown_or_raw_tokens_are_flagged_not_silently_accepted():
    assert meta.unknown_tokens("pay.left", "{minutes} و {تعدادِ دقیقه} و {x}") == ["x"]  # نامِ خام هم مجازه (سازگاری)
    assert meta.from_display("pay.left", "{x} {تعدادِ دقیقه}") == "{x} {minutes}"


def test_button_labels_are_capped_for_owner_edits():
    assert meta.is_button("cart.checkout") and not meta.is_button("menu.welcome")
    assert meta.friendly_error("cart.checkout", "✅ " + "ا" * 60) != ""
    assert meta.friendly_error("cart.checkout", "✅ ثبتِ سفارش") == ""
    assert meta.friendly_error("menu.welcome", "ا" * 300) == ""  # فقط دکمه‌ها سقف دارن


# =========================================================== نگارشِ پیام‌ها ====

@pytest.mark.parametrize("lang", ["fa", "en"])
def test_default_button_labels_are_short_everywhere(lang):
    for key in sorted(meta.BUTTON_KEYS):
        assert shop_texts.has(key), key
        label = shop_texts.default(key, lang).format(**meta.sample_values(key))
        assert len(label) <= meta.MAX_DEFAULT_LABEL, (key, lang, len(label), label)


@pytest.mark.parametrize("lang", ["fa", "en"])
def test_customer_texts_contain_no_forbidden_technical_words(lang):
    for key in shop_texts.keys():
        if key in OWNER_ONLY:
            continue
        text = shop_texts.default(key, lang).lower()
        for word in FORBIDDEN:
            assert word not in text, (key, lang, word)
        assert not re.search(r"\b(?:c:|cb:|id=|\w+_\w+)\b", text.replace("{order_id}", "").replace("order_id", "")) or "_" not in text, (key, text)


NEXT_STEP = {
    "cart.cleared": "محصولات", "cart.fixed": "ثبتِ سفارش", "cart.fix_hint": "درست کن", "co.cancelled": "سبد خرید", "ord.none": "محصولات",
    "ord.cancelled": "محصولات", "ord.not_found": "سفارش‌هام", "co.pending_exists": "سفارش‌هام", "faq.empty": "بنویس", "pay.ref_saved": "بررسی",
    "guide.body": "محصولات", "cart.empty": "محصولات", "co.continue_or_cancel": "ادامه",
}


def test_messages_tell_the_customer_the_next_step():
    for key, needle in NEXT_STEP.items():
        assert needle in shop_texts.default(key, "fa"), (key, needle)


def test_old_confusing_labels_are_gone():
    joined = " ".join(shop_texts.default(k, "fa") for k in shop_texts.keys())
    for old in ("اصلاحِ خودکار", "انصراف؟", "اشتراکِ شماره"):
        assert old not in joined


# ======================================================= خلاصه‌ی سفارش: ≤ ۳ گزینه ====

def reach_summary(h, fields=None):
    pid = h.products.add("کالا", 1000, 5)
    h.tap(f"c:a:{pid}:1:-:1")
    h.tap("c:co")
    h.say("علی رضایی")
    h.say("۰۹۱۲۳۴۵۶۷۸۹")
    h.say("تهران، خیابان آزادی، پلاک ۱۲")
    h.tap("c:ck:s")
    return h.tap("c:ck:s")


def test_summary_offers_only_three_options_and_edit_opens_a_field_chooser(h):
    summary = reach_summary(h)
    assert "خلاصه" in texts(summary)
    assert datas(summary) == ["c:ck:ok", "c:ck:ed", "c:ck:x"]
    assert labels(summary) == ["✅ تأیید و پرداخت", "✏️ ویرایشِ اطلاعات", "✖️ لغوِ ثبتِ سفارش"]
    chooser = h.tap("c:ck:ed")
    assert "کدوم اطلاعات" in texts(chooser)
    assert {"c:ck:e:0", "c:ck:e:1", "c:ck:e:2", "c:ck:r"} <= set(datas(chooser)) and "c:ck:ok" not in datas(chooser)
    prompt = h.tap("c:ck:e:1")  # ویرایشِ موبایل
    assert "موبایل" in texts(prompt)
    back = h.say("۰۹۳۵۱۱۱۲۲۲۳")
    assert "09351112223" in texts(back) and datas(back) == ["c:ck:ok", "c:ck:ed", "c:ck:x"]


def test_chooser_back_returns_to_the_summary_and_garbage_is_safe(h):
    reach_summary(h)
    h.tap("c:ck:ed")
    again = h.tap("c:ck:r")
    assert "خلاصه" in texts(again) and "c:ck:ok" in datas(again)
    for data in ("c:ck:ed", "c:ck:ed:1", "c:ck:e", "c:ck:e:99", "c:ck:e:x"):
        assert h.tap(data).messages  # هرگز exception


def test_single_field_form_edits_directly_without_a_chooser(h):
    h.settings.checkout_fields = [{"id": "name", "label": "نام", "prompt": "اسمت؟", "type": "text", "required": True, "applies_to": "all", "regex": "", "choices": [], "min_len": 2, "max_len": 50}]
    pid = h.products.add("کالا", 1000, 5)
    h.tap(f"c:a:{pid}:1:-:1")
    h.tap("c:co")
    summary = h.say("علی رضایی")
    assert datas(summary) == ["c:ck:ok", "c:ck:e:0", "c:ck:x"]


def test_cart_fix_hint_appears_only_when_there_is_a_problem(h):
    a = h.products.add("الف", 1000, 5)
    h.tap(f"c:a:{a}:4:-:1")
    assert "سبدم رو درست کن" not in texts(h.tap("c:cart"))
    h.products.adjust_stock(a, -3)
    cart = h.tap("c:cart")
    assert "🔧 سبدم رو درست کن" in labels(cart) and "برای ادامه" in texts(cart)
