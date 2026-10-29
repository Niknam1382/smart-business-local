"""برند، نمادهای دکمه (N4) و ساختِ لینکِ حمایتِ دارمت (N15)."""

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from app import branding
from app.core import support_link, ui_glyphs
from app.core.support_link import SupportLinkError, build_support_link, clean_message, message_counter, parse_amount_toman

CORE = Path(__file__).resolve().parent.parent / "app" / "core"


# ------------------------------------------------------------------ مبلغ ----

@pytest.mark.parametrize(
    "raw,expected",
    [("5000", 5000), ("۵۰۰۰", 5000), ("٥٠٠٠", 5000), ("5,000", 5000), ("۵٬۰۰۰", 5000), ("۱،۲۵۰،۰۰۰", 1250000), (" 1 000 ", 1000), ("100000000", 100_000_000)],
)
def test_amount_accepts_digits_in_any_script_and_thousands_separators(raw, expected):
    assert parse_amount_toman(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "0", "۰", "-5", "+5", "12.5", "12/5", "abc", "5000تومان", "1e3", "100000001", "۹۹۹۹۹۹۹۹۹۹۹"])
def test_amount_rejects_invalid_zero_negative_fractional_and_huge(raw):
    with pytest.raises(SupportLinkError):
        parse_amount_toman(raw)


# ------------------------------------------------------------------ پیام ----

def test_message_limit_is_100_and_counter_is_live():
    assert clean_message("a" * 100) == "a" * 100
    with pytest.raises(SupportLinkError):
        clean_message("a" * 101)
    assert message_counter("") == "0/100"
    assert message_counter("سلام") == "4/100"


def test_message_length_is_measured_conservatively_for_emoji():
    # هر ایموجیِ «خارج از BMP» دو واحدِ UTF-16 است
    assert clean_message("😀" * 50)
    with pytest.raises(SupportLinkError):
        clean_message("😀" * 51)


@pytest.mark.parametrize("bad", ["خط۱\nخط۲", "a\rb", "a\x00b", "a\u202eb", "a\u200fb", "a\u2066b"])
def test_message_rejects_newlines_control_and_bidi_characters(bad):
    with pytest.raises(SupportLinkError):
        clean_message(bad)


def test_message_keeps_zwnj_for_persian():
    assert clean_message("می\u200cخوام") == "می\u200cخوام"


# ------------------------------------------------------------------- لینک ----

def test_link_without_message_has_no_message_parameter():
    url = build_support_link("5000", "")
    assert url == "https://daramet.com/Niknam1382?webintent&donate=5000"
    assert "message" not in url


def test_link_percent_encodes_persian_emoji_ampersand_hash_and_spaces():
    message = "سلام & خسته نباشید #۱ 😀"
    url = build_support_link("۱٬۵۰۰", message)
    assert url.startswith("https://daramet.com/Niknam1382?webintent&donate=1500&message=")
    tail = url.split("&message=", 1)[1]
    assert " " not in tail and "#" not in tail and "&" not in tail and "😀" not in tail and "سلام" not in tail
    assert parse_qs(urlparse(url).query)["message"] == [message]
    assert parse_qs(urlparse(url).query)["donate"] == ["1500"]


def test_link_propagates_validation_errors():
    for amount, message in (("0", ""), ("abc", ""), ("100", "x" * 101), ("100", "a\nb")):
        with pytest.raises(SupportLinkError):
            build_support_link(amount, message)


def test_webintent_disabled_falls_back_to_profile_link(monkeypatch):
    monkeypatch.setattr(branding, "DARAMET_WEBINTENT_ENABLED", False)
    assert build_support_link("5000", "سلام") == "https://daramet.com/Niknam1382"
    assert build_support_link("", "") == "https://daramet.com/Niknam1382"  # بدونِ اعتبارسنجی: فقط پروفایل


def test_no_preset_amount_or_message_exists_in_the_module():
    source = Path(support_link.__file__).read_text(encoding="utf-8")
    for forbidden in ("PRESET", "DEFAULT_MESSAGE", "DEFAULT_AMOUNT", "suggested_amount"):
        assert forbidden not in source


# ---------------------------------------- هیچ اثری از حمایت/اعتبار در ربات ----

def test_support_form_and_credit_never_appear_in_bot_facing_modules():
    for path in sorted(CORE.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if path.name != "support_link.py":
            assert "daramet" not in text.lower(), f"لینک/اشاره‌ی حمایت در {path.name}"
            assert "support_link" not in text, f"import فرمِ حمایت در {path.name}"
        if path.name != "bot_profile.py":
            assert "CREDIT_" not in text and "credit_for" not in text, f"خطِ اعتبار در {path.name}"
        assert "UPDATE_PUBLIC_KEY_B64" not in text or path.name in {"updater.py", "update_verify.py"}, path.name


def test_credit_texts_fit_telegram_short_description_with_room_for_seller():
    for credit in (branding.CREDIT_FA, branding.CREDIT_EN):
        assert len(credit.encode("utf-16-le")) // 2 <= 60  # حدودِ ۵۰ کاراکتر (سهمِ فروشنده ≈ ۶۰ از ۱۲۰)
        assert "github.com/niknam1382" in credit


# ------------------------------------------------------------- نمادها (N4) ----

def test_bale_glyphs_are_never_emoji_only_and_telegram_keeps_known_emoji():
    for lang in ("fa", "en"):
        bale = ui_glyphs.for_platform("bale", lang)
        for label in (bale.minus, bale.plus, bale.remove, bale.details):
            assert not ui_glyphs.is_emoji_only(label), label
        tg = ui_glyphs.for_platform("telegram", lang)
        assert tg.minus == "➖" and tg.plus == "➕"


def test_is_emoji_only_helper():
    for label in ("➖", "➕", "🗑", "ℹ️", "", "  ", "👍👍"):
        assert ui_glyphs.is_emoji_only(label), label
    for label in ("−", "+", "حذف", "🗑 حذف", "2×", "Back ↩️"):
        assert not ui_glyphs.is_emoji_only(label), label
