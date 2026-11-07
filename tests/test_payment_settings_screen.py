"""
کارت «تنظیمات پرداخت» (۱.۰.۰): فقط دو روش — کارت‌به‌کارت (با رسید) و بله‌پی (درگاهِ بله).

زرین‌پال حذف شده و بله دیگر رباتِ پیام‌رسان نیست، پس:
* بله‌پی با **هر دو** اعتبارنامه روشن می‌شه (توکنِ رباتِ پرداخت + توکنِ کیف‌پول) و هر دو
  رمزنگاری روی دیسک می‌نشن؛
* توکنِ آزمایشیِ مستندات حتماً برچسبِ «آزمایشی» می‌گیره (بی‌سروصدا رد نمی‌شه)؛
* روشِ لینک (لینکِ مستقیم / دیپ‌لینک) ذخیره می‌شه؛
* تأییدِ کارت‌به‌کارت **همیشه دستی** است و UI هم همین را می‌گوید، نه بیشتر.

هیچ تستی شبکه نمی‌زند (BotManager واقعی فقط با دیتابیس‌هایِ موقت).
"""

import pytest
from fake_page import FakePage, collect_text, find, fire

from app import theme
from app.core import settings as settings_module
from app.core.bale_pay import TEST_PROVIDER_TOKEN
from app.core.orders import METHOD_BALE_PAY, METHOD_CARD_TO_CARD
from app.core.settings import AppSettings
from app.screens import payment_settings


def make_card(settings=None, manager=None, lang="fa"):
    settings = settings or AppSettings()
    saves = {"n": 0}

    def save():
        saves["n"] += 1
        settings_module.save_settings(settings)

    page = FakePage()
    control = payment_settings.build(page, lang, settings, save, manager)
    return settings, control, saves


class FakeManager:
    """مدیر جعلی: فقط همان چیزهایی که کارتِ پرداخت لازم دارد (بدونِ ترد و شبکه)."""

    def __init__(self, running=False, diag_result=None):
        self.running = running
        self.diag_calls = []
        self.restarts = []
        self.diag_result = diag_result
        self.errors = {}

    def is_running(self):
        return self.running

    def payment_last_errors(self):
        return dict(self.errors)

    def restart(self, timeout: float = 15.0) -> None:
        self.restarts.append("restart")
        self.running = True

    def diagnose_payment_sync(self, method, timeout=30.0):
        self.diag_calls.append(method)
        if self.diag_result is not None:
            return self.diag_result
        if method == METHOD_CARD_TO_CARD:
            return True, "✅ کارت ثبت شده؛ تأییدِ پرداخت همیشه دستی است."
        return False, "رباتِ پرداختِ بله وصل نیست."


def fill_bale_tokens(settings, control, bot="123456789:balepaybot", provider="WALLET-REAL-123"):
    bot_field = find(control, "ps_bale_bot_token")
    bot_field.value = bot
    fire(bot_field, "on_blur")
    provider_field = find(control, "bale_pay_token")
    provider_field.value = provider
    fire(provider_field, "on_blur")


def make_store_manager(tmp_path, settings, **kw):
    """BotManager واقعیِ حالتِ فروشگاه (دیتابیس‌هایِ موقت، آداپتورِ جعلی) — همان چیزی که
    ``diagnose_payment_sync`` برایِ «تست اتصال» لازم دارد. تست‌های همسایه هم همین را صدا می‌زنن."""
    from app.core.bot_manager import BotManager
    from app.core.conversations import ConversationStore
    from app.core.orders import OrderStore
    from app.core.products import ProductStore
    from test_bot_connect_screen import InstantAdapter

    products = ProductStore(db_path=tmp_path / "p.db")
    orders = OrderStore(db_path=tmp_path / "o.db", product_store=products)
    return BotManager(
        settings,
        store=ConversationStore(db_path=tmp_path / "c.db"),
        product_store=products,
        order_store=orders,
        adapter_factories={"telegram": lambda s, p: InstantAdapter("x", p)},
        log_dir=tmp_path,
        **kw,
    )


# ------------------------------------------------------------------ حذفِ زرین‌پال


def test_no_zarinpal_anywhere_on_the_card():
    _, control, _ = make_card()
    for key in ("zarinpal_enabled", "zarinpal_merchant_id", "zarinpal_sandbox", "zarinpal_callback_url", "zarinpal_error", "diag_zarinpal"):
        assert find(control, key) is None, key
    assert "زرین‌پال" not in collect_text(control)


# ---------------------------------------------------------------- کارت‌به‌کارت


def test_empty_state_warns_no_method_active():
    _, control, _ = make_card()
    assert "هیچ روش پرداختی فعال نیست" in collect_text(control)
    assert find(control, "card_error").visible is False


def test_persian_digits_card_number_is_normalized_and_saved():
    settings, control, saves = make_card()
    field = find(control, "card_number")
    field.value = "۶۲۱۹ ۸۶۱۰ ۱۲۳۴ ۵۶۷۸"
    fire(field, "on_blur")
    assert settings.card_to_card_number == "6219-8610-1234-5678"
    assert field.value == "6219-8610-1234-5678"
    assert saves["n"] == 1
    assert "فقط با کارت‌به‌کارت" in collect_text(control)
    assert settings_module.load_settings().card_to_card_number == "6219-8610-1234-5678"


def test_holder_name_saved_with_card():
    settings, control, _ = make_card()
    find(control, "card_number").value = "6219861012345678"
    holder = find(control, "card_holder")
    holder.value = "  علی رضایی "
    fire(holder, "on_submit")
    assert settings.card_to_card_holder_name == "علی رضایی"
    assert settings.card_to_card_number == "6219-8610-1234-5678"


@pytest.mark.parametrize("bad", ["1234", "6219-8610-1234-567", "62198610123456789", "abcd-efgh-ijkl-mnop"])
def test_invalid_card_rejected_and_previous_value_kept(bad):
    settings = AppSettings()
    settings.card_to_card_number = "6037-9911-1111-1111"
    settings, control, saves = make_card(settings)
    field = find(control, "card_number")
    field.value = bad
    fire(field, "on_blur")
    assert settings.card_to_card_number == "6037-9911-1111-1111", "ورودی بد نباید مقدار قبلیِ درست را خراب کند"
    assert saves["n"] == 0
    err = find(control, "card_error")
    assert err.visible and ("رقم" in err.value or "عدد" in err.value)


def test_clearing_card_number_disables_card_to_card():
    settings = AppSettings()
    settings.card_to_card_number = "6037-9911-1111-1111"
    settings, control, _ = make_card(settings)
    field = find(control, "card_number")
    field.value = ""
    fire(field, "on_blur")
    assert settings.card_to_card_number == ""
    assert "هیچ روش پرداختی فعال نیست" in collect_text(control)


# --------------------------------------------------------- رسیدِ کارت‌به‌کارت


def test_receipt_section_is_on_by_default_and_persists():
    settings, control, _ = make_card()
    assert settings.receipt_check_enabled and settings.receipt_amount_check and settings.alert_on_payment_claim
    for key, attr in (
        ("receipt_check_enabled", "receipt_check_enabled"),
        ("receipt_amount_check", "receipt_amount_check"),
        ("alert_on_payment_claim", "alert_on_payment_claim"),
    ):
        fire(find(control, key), "on_change", value=False)
        assert getattr(settings, attr) is False
        assert getattr(settings_module.load_settings(), attr) is False


def test_receipt_confirmation_is_never_promised_as_automatic():
    """تصمیمِ مالکِ محصول: کارت‌به‌کارت همیشه دستی تأیید می‌شه — UI نباید وعده‌ی تأییدِ خودکار بده."""
    settings = AppSettings()
    settings.card_to_card_number = "6037-9911-1111-1111"
    _, control, _ = make_card(settings)
    text = collect_text(control)
    assert "تأییدِ سفارشِ کارت‌به‌کارت همیشه دستی است" in text
    assert "خودکار تأیید نمی‌شه" in text  # هم خطِ کارت‌به‌کارت، هم بخشِ رسید
    assert "خودکار تایید می‌شه" not in text.replace("خودکار تأیید", "")  # هیچ‌جا تأییدِ خودکارِ کارت‌به‌کارت وعده نمی‌شه


# ------------------------------------------------------------------ بله‌پی


def test_bale_switch_refuses_without_any_token():
    settings, control, saves = make_card()
    switch = find(control, "bale_pay_enabled")
    fire(switch, "on_change", value=True)
    assert settings.bale_pay_enabled is False
    assert switch.value is False, "سوییچ باید برگرده خاموش"
    assert find(control, "pay_error").visible and "هر دو" in find(control, "pay_error").value
    assert saves["n"] == 0


def test_bale_switch_refuses_when_only_one_of_two_tokens_is_set():
    settings, control, _ = make_card()
    bot = find(control, "ps_bale_bot_token")
    bot.value = "123456789:balepaybot"
    fire(bot, "on_blur")
    assert settings.get_bale_pay_bot_token() == "123456789:balepaybot"
    assert settings.bale_pay_configured() is False
    switch = find(control, "bale_pay_enabled")
    fire(switch, "on_change", value=True)
    assert settings.bale_pay_enabled is False and switch.value is False
    assert find(control, "pay_error").visible

    # برعکسش: فقط توکنِ کیف‌پول
    settings = AppSettings()
    settings.set_bale_pay_provider_token("6037991100000000")
    _, control, _ = make_card(settings)
    switch = find(control, "bale_pay_enabled")
    fire(switch, "on_change", value=True)
    assert settings.bale_pay_enabled is False, "بدونِ توکنِ رباتِ پرداخت، بله‌پی فقط روی کاغذه"


def test_both_bale_tokens_stored_encrypted_and_switch_enables():
    settings = AppSettings()
    settings, control, _ = make_card(settings)
    fill_bale_tokens(settings, control, provider="WALLET-REAL-TOKEN-123")
    fire(find(control, "bale_pay_enabled"), "on_change", value=True)

    assert settings.bale_pay_enabled is True and settings.bale_pay_configured()
    assert settings.get_bale_pay_bot_token() == "123456789:balepaybot"
    assert settings.get_bale_pay_provider_token() == "WALLET-REAL-TOKEN-123"
    assert "123456789:balepaybot" not in settings.bale_pay_bot_token_encrypted
    assert "WALLET-REAL-TOKEN-123" not in settings.bale_pay_provider_token_encrypted
    raw = settings_module._settings_path().read_text(encoding="utf-8")  # noqa: SLF001
    assert "WALLET-REAL-TOKEN-123" not in raw and "balepaybot" not in raw, "اعتبارنامه‌ها متن‌ساده روی دیسک نیستن"
    assert "فقط با بله‌پی" in collect_text(control)


def test_clearing_either_bale_token_turns_the_switch_off():
    settings = AppSettings()
    settings.set_bale_pay_bot_token("123:balepaybot")
    settings.set_bale_pay_provider_token("TOK")
    settings.bale_pay_enabled = True
    settings, control, _ = make_card(settings)

    bot = find(control, "ps_bale_bot_token")
    bot.value = ""
    fire(bot, "on_blur")
    assert settings.bale_pay_enabled is False and find(control, "bale_pay_enabled").value is False
    assert settings.bale_pay_bot_token_encrypted == ""

    # دوباره با هر دو اعتبارنامه روشنش کن، بعد توکنِ کیف‌پول را پاک کن
    settings.set_bale_pay_bot_token("123:balepaybot")
    fire(find(control, "bale_pay_enabled"), "on_change", value=True)
    assert settings.bale_pay_enabled is True
    provider = find(control, "bale_pay_token")
    provider.value = ""
    fire(provider, "on_blur")
    assert settings.bale_pay_enabled is False and find(control, "bale_pay_enabled").value is False
    assert settings.bale_pay_provider_token_encrypted == ""


def test_provider_token_persian_card_digits_are_normalized():
    settings, control, _ = make_card()
    provider = find(control, "bale_pay_token")
    provider.value = "۶۰۳۷ ۹۹۱۱ ۱۱۱۱ ۱۱۱۱"
    fire(provider, "on_blur")
    assert settings.get_bale_pay_provider_token() == "6037991111111111"
    assert provider.value == "6037991111111111"


def test_documented_test_token_is_labelled_as_test_only():
    settings, control, _ = make_card()
    bot = find(control, "ps_bale_bot_token")
    bot.value = "123:balepaybot"
    fire(bot, "on_blur")
    provider = find(control, "bale_pay_token")
    provider.value = TEST_PROVIDER_TOKEN
    fire(provider, "on_blur")
    warn = find(control, "ps_bale_test_warning")
    assert warn.visible is True and "آزمایشی" in warn.value and "پولی" in warn.value
    assert "آزمایشی" in find(control, "ps_bale_token_kind").value, "نوعِ توکن هم صریح گفته می‌شه"
    fire(find(control, "bale_pay_enabled"), "on_change", value=True)
    assert settings.bale_pay_enabled is True, "با هر دو اعتبارنامه، توکنِ تست هم فقط هشدار می‌دهد (بی‌سروصدا نیست)"

    provider.value = "WALLET-REAL-TOKEN-9"
    fire(provider, "on_blur")
    assert find(control, "ps_bale_test_warning").visible is False


def test_link_mode_choice_persists_both_ways():
    settings, control, _ = make_card()
    mode = find(control, "ps_link_mode")
    assert mode.selected == ["auto"]
    mode.selected = ["deeplink"]
    fire(mode, "on_change")
    assert settings.bale_pay_link_mode == "deeplink"
    assert settings_module.load_settings().bale_pay_link_mode == "deeplink"

    mode.selected = ["auto"]
    fire(mode, "on_change")
    assert settings.bale_pay_link_mode == "auto"
    assert settings_module.load_settings().bale_pay_link_mode == "auto"


def test_link_mode_control_shows_both_persian_options():
    _, control, _ = make_card()
    labels = [seg.label.value for seg in find(control, "ps_link_mode").segments]
    assert labels == ["لینکِ مستقیم", "دیپ‌لینکِ ربات"]


def test_bale_note_is_honest_about_credentials_and_running_bots():
    _, control, _ = make_card()
    note = find(control, "bale_note")
    assert "هر دو" in note.value, "بله‌پی بدونِ توکن‌ها عملاً کار نمی‌کنه و باید گفته بشه"

    settings = AppSettings()
    fill_tokens_into_settings(settings)
    _, control, _ = make_card(settings, FakeManager(running=False))
    assert "ربات‌ها" in find(control, "bale_note").value and "روشن" in find(control, "bale_note").value

    _, control, _ = make_card(settings, FakeManager(running=True))
    assert "لینکِ پرداخت" in find(control, "bale_note").value


def fill_tokens_into_settings(settings):
    settings.set_bale_pay_bot_token("123:balepaybot")
    settings.set_bale_pay_provider_token("6037991100000000")
    settings.bale_pay_enabled = True


# ------------------------------------------------------- رزرو و تأییدِ سفارش


def test_reservation_minutes_validation_and_persian_digits():
    settings, control, saves = make_card()
    field = find(control, "reservation_minutes")
    assert field.value == "15"
    for bad in ("0", "241", "abc", "", "-5", "1.5"):
        field.value = bad
        fire(field, "on_blur")
        assert settings.reservation_minutes == 15 and find(control, "reserve_error").visible, bad
    assert saves["n"] == 0
    field.value = "۳۰"
    fire(field, "on_blur")
    assert settings.reservation_minutes == 30 and field.value == "30" and not find(control, "reserve_error").visible
    assert settings_module.load_settings().reservation_minutes == 30


def test_auto_confirm_toggle_persists_and_legacy_toggles_are_gone():
    settings, control, _ = make_card()
    assert settings.auto_confirm_gateway_payments is True
    fire(find(control, "auto_confirm_gateway_payments"), "on_change", value=False)
    assert settings_module.load_settings().auto_confirm_gateway_payments is False
    assert "زرین‌پال" not in find(control, "auto_confirm_gateway_payments").label
    assert find(control, "require_customer_phone") is None and find(control, "require_customer_address") is None


def test_summary_lists_both_active_methods():
    settings = AppSettings()
    settings.card_to_card_number = "6037-9911-1111-1111"
    fill_tokens_into_settings(settings)
    _, control, _ = make_card(settings)
    text = find(control, "pay_summary").value
    assert "کارت‌به‌کارت" in text and "بله‌پی" in text


def test_builds_in_english():
    _, control, _ = make_card(lang="en")
    assert "No payment method is active yet" in collect_text(control)
    assert "Card-to-card receipts" in collect_text(control)


# ------------------------------------------------------------------ تست اتصال


def test_diagnostic_buttons_hidden_without_manager():
    _, control, _ = make_card()
    assert find(control, "diag_bale_pay") is None
    assert find(control, "diag_card_to_card") is None


def test_bale_diagnostic_calls_manager_and_prints_result():
    settings = AppSettings()
    fill_tokens_into_settings(settings)
    manager = FakeManager(running=True, diag_result=(True, "✅ لینکِ پرداختِ آزمایشی ساخته شد: https://pay.bale/xyz"))
    _, control, _ = make_card(settings, manager)
    fire(find(control, "diag_bale_pay"), "on_click")
    assert manager.diag_calls == [METHOD_BALE_PAY]
    out = find(control, "diag_bale_result")
    assert out.visible and "لینکِ پرداختِ آزمایشی" in out.value and out.color == theme.SUCCESS

    manager.diag_result = (False, "بله لینکِ آزمایشی را نپذیرفت: invalid provider_token")
    fire(find(control, "diag_bale_pay"), "on_click")
    assert out.color == theme.DANGER and "نپذیرفت" in out.value


def test_restart_bots_button_restarts_and_says_so():
    """۱۲: «بله‌پی وصل نیست» باید راه‌حلِ واقعی داشته باشد، نه اشاره به صفحه‌ی دیگر."""
    settings = AppSettings()
    fill_tokens_into_settings(settings)
    manager = FakeManager(running=False)
    _, control, _ = make_card(settings, manager)
    fire(find(control, "restart_bots"), "on_click")
    assert manager.restarts == ["restart"] and manager.running is True
    assert "ری‌استارت" in collect_text(control)


def test_restart_bots_button_absent_without_manager():
    _, control, _ = make_card()
    assert find(control, "restart_bots") is None


def test_card_to_card_diagnostic_is_available_without_bots():
    settings = AppSettings()
    settings.card_to_card_number = "6037-9911-1111-1111"
    manager = FakeManager(running=False)
    _, control, _ = make_card(settings, manager)
    fire(find(control, "diag_card_to_card"), "on_click")
    assert manager.diag_calls == [METHOD_CARD_TO_CARD]
    out = find(control, "diag_card_result")
    assert out.visible and "همیشه دستی" in out.value and out.color == theme.SUCCESS


def test_real_manager_answers_card_to_card_without_network(tmp_path):
    """BotManager واقعی (بدونِ آداپتور و شبکه): کارت‌به‌کارت از تنظیمات جواب می‌ده، بله‌پی نه."""
    settings = AppSettings()
    settings.business_mode = "store"
    settings.card_to_card_number = "6037-9911-1111-1111"
    manager = make_store_manager(tmp_path, settings)
    _, control, _ = make_card(settings, manager)

    fire(find(control, "diag_card_to_card"), "on_click")
    assert "همیشه دستی" in find(control, "diag_card_result").value

    fill_tokens_into_settings(settings)
    fire(find(control, "diag_bale_pay"), "on_click")
    assert "خاموش" in find(control, "diag_bale_result").value, "رباتِ پرداختِ بله با ربات‌های خاموش بالا نمی‌آید"


def test_last_real_chat_errors_are_shown_on_the_card(tmp_path):
    settings = AppSettings()
    settings.business_mode = "store"
    manager = FakeManager()
    manager.errors[METHOD_BALE_PAY] = "بله خطا برگرداند: invalid provider_token"
    _, control, _ = make_card(settings, manager)
    shown = find(control, "last_errors")
    assert shown.visible and "invalid provider_token" in shown.value and "بله‌پی" in shown.value
