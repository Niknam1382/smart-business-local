"""
کارت «تنظیمات پرداخت»: مقدارها درست ذخیره/رمزنگاری می‌شن، ورودی بد رد می‌شه،
وابستگی بله‌پی به ربات بله نشون داده می‌شه، و — مهم‌تر از همه — چیزی که UI
می‌نویسه دقیقاً همون چیزیه که جریان خرید توی ربات می‌خونه.
"""

import pytest
from fake_page import FakePage, collect_text, find, fire
from fake_servers import FakeBotApiServer
from fakes import ScriptedToolEngine, say, tool
from fake_zarinpal import FakeZarinpalServer
from helpers import wait_until
from test_adapters_e2e import make_settings
from test_bot_connect_screen import InstantAdapter
from test_commerce_e2e import ask, make_commerce_manager, status

from app.core import ai_engine
from app.core import settings as settings_module
from app.core.bot_manager import BotManager
from app.core.conversations import ConversationStore
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
    # روی دیسک هم موند
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
    assert settings.card_to_card_number == "6037-9911-1111-1111", "ورودی بد نباید مقدار قبلیِ درست رو خراب کنه"
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


def test_bale_switch_refuses_without_token():
    settings, control, saves = make_card()
    switch = find(control, "bale_pay_enabled")
    fire(switch, "on_change", value=True)
    assert settings.bale_pay_enabled is False
    assert switch.value is False, "سوییچ باید برگرده خاموش"
    assert find(control, "pay_error").visible
    assert saves["n"] == 0


def test_bale_token_stored_encrypted_and_switch_enables():
    settings = AppSettings()
    settings.set_bale_token("123:bale")
    settings, control, _ = make_card(settings)
    token = find(control, "bale_pay_token")
    token.value = "WALLET-REAL-TOKEN-123"
    fire(token, "on_blur")
    fire(find(control, "bale_pay_enabled"), "on_change", value=True)

    assert settings.bale_pay_enabled is True
    assert settings.get_bale_pay_provider_token() == "WALLET-REAL-TOKEN-123"
    assert "WALLET-REAL-TOKEN-123" not in settings.bale_pay_provider_token_encrypted
    raw_file = (settings_module._settings_path()).read_text(encoding="utf-8")  # noqa: SLF001
    assert "WALLET-REAL-TOKEN-123" not in raw_file, "توکن نباید متن‌ساده روی دیسک باشه"
    assert "فقط با بله‌پی" in collect_text(control)


def test_clearing_token_turns_switch_off():
    settings = AppSettings()
    settings.set_bale_token("123:bale")
    settings.set_bale_pay_provider_token("TOK")
    settings.bale_pay_enabled = True
    settings, control, _ = make_card(settings)
    token = find(control, "bale_pay_token")
    token.value = ""
    fire(token, "on_blur")
    assert settings.bale_pay_enabled is False
    assert find(control, "bale_pay_enabled").value is False
    assert settings.bale_pay_provider_token_encrypted == ""


def test_bale_note_says_bale_bot_required_when_no_bale_token():
    _, control, _ = make_card()
    assert "ربات بله هم وصل و فعال باشه" in find(control, "bale_note").value


def test_bale_pay_not_counted_active_when_bale_bot_missing():
    settings = AppSettings()  # توکن بله نداره
    settings.set_bale_pay_provider_token("TOK")
    settings.bale_pay_enabled = True
    _, control, _ = make_card(settings)
    assert "هیچ روش پرداختی فعال نیست" in collect_text(control), "بله‌پی بدون ربات بله فقط روی کاغذه"


def test_restart_hint_when_bots_started_before_bale_connected(tmp_path):
    settings = AppSettings()
    settings.set_telegram_token("111:tg")
    manager = BotManager(
        settings,
        store=ConversationStore(db_path=tmp_path / "c.db"),
        adapter_factories={
            "telegram": lambda s, p: InstantAdapter(s.get_telegram_token(), p),
            "bale": lambda s, p: InstantAdapter(s.get_bale_token(), p),
        },
        log_dir=tmp_path,
    )
    manager.start()
    try:
        assert manager.started_platforms() == ["telegram"]
        settings.set_bale_token("222:bale")  # بعد از روشن‌شدن
        settings.set_bale_pay_provider_token("TOK")
        settings.bale_pay_enabled = True
        _, control, _ = make_card(settings, manager)
        assert "ری‌استارت" in find(control, "bale_note").value
    finally:
        manager.stop(timeout=10)
    assert manager.started_platforms() == []


def test_builds_in_english():
    _, control, _ = make_card(lang="en")
    assert "No payment method is active yet" in collect_text(control)


# -------------------- چیزی که UI می‌نویسه = چیزی که ربات می‌خونه (سرتاسری) ----


@pytest.fixture
def tg():
    srv = FakeBotApiServer(username="tg_shop_bot").start()
    yield srv
    srv.stop()


@pytest.fixture
def bale():
    srv = FakeBotApiServer(username="bale_shop_bot").start()
    yield srv
    srv.stop()


MERCHANT = "12345678-1234-1234-1234-123456789012"


# ----------------------------------------------------------------- زرین‌پال


def test_zarinpal_merchant_id_validated_stored_encrypted_and_switch_enables():
    settings, control, saves = make_card()
    merchant = find(control, "zarinpal_merchant_id")
    merchant.value = "abc"
    fire(merchant, "on_blur")
    assert settings.get_zarinpal_merchant_id() == "" and saves["n"] == 0
    assert find(control, "zarinpal_error").visible and "۳۶ کاراکتر" in find(control, "zarinpal_error").value

    merchant.value = f"  {MERCHANT}  "
    fire(merchant, "on_blur")
    fire(find(control, "zarinpal_enabled"), "on_change", value=True)
    assert settings.zarinpal_enabled is True and settings.get_zarinpal_merchant_id() == MERCHANT
    assert MERCHANT not in settings_module._settings_path().read_text(encoding="utf-8"), "مرچنت‌کد متن‌ساده روی دیسک نیست"  # noqa: SLF001
    assert not find(control, "zarinpal_error").visible
    assert "فقط با زرین‌پال" in collect_text(control)


def test_zarinpal_switch_refuses_without_valid_merchant_id():
    settings, control, saves = make_card()
    switch = find(control, "zarinpal_enabled")
    fire(switch, "on_change", value=True)
    assert settings.zarinpal_enabled is False and switch.value is False
    assert "اول مرچنت‌کد" in find(control, "zarinpal_error").value
    assert saves["n"] == 0


def test_clearing_merchant_id_turns_zarinpal_off():
    settings = AppSettings()
    settings.set_zarinpal_merchant_id(MERCHANT)
    settings.zarinpal_enabled = True
    settings, control, _ = make_card(settings)
    merchant = find(control, "zarinpal_merchant_id")
    merchant.value = ""
    fire(merchant, "on_blur")
    assert settings.zarinpal_enabled is False and find(control, "zarinpal_enabled").value is False
    assert settings.zarinpal_merchant_id_encrypted == ""


def test_zarinpal_sandbox_and_callback_url_saved():
    settings, control, _ = make_card()
    fire(find(control, "zarinpal_sandbox"), "on_change", value=True)
    cb = find(control, "zarinpal_callback_url")
    cb.value = "  https://myshop.ir/thanks "
    fire(cb, "on_blur")
    assert settings.zarinpal_sandbox is True and settings.zarinpal_callback_url == "https://myshop.ir/thanks"


def test_summary_lists_all_active_methods():
    settings = AppSettings()
    settings.card_to_card_number = "6037-9911-1111-1111"
    settings.set_zarinpal_merchant_id(MERCHANT)
    settings.zarinpal_enabled = True
    settings.set_bale_token("222:bale")
    settings.set_bale_pay_provider_token("TOK")
    settings.bale_pay_enabled = True
    _, control, _ = make_card(settings)
    text = find(control, "pay_summary").value
    assert "کارت‌به‌کارت" in text and "بله‌پی" in text and "زرین‌پال" in text


# ----------------------------------------------------------------- سفارش‌گیری هوشمند


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


def test_smart_ordering_toggles_persist():
    settings, control, _ = make_card()
    assert settings.auto_confirm_gateway_payments is True
    fire(find(control, "auto_confirm_gateway_payments"), "on_change", value=False)
    fire(find(control, "require_customer_phone"), "on_change", value=True)
    fire(find(control, "require_customer_address"), "on_change", value=True)
    loaded = settings_module.load_settings()
    assert (loaded.auto_confirm_gateway_payments, loaded.require_customer_phone, loaded.require_customer_address) == (False, True, True)


# ----------------------------------------------------------------- تست اتصال (تشخیص)


@pytest.fixture
def zp_server():
    srv = FakeZarinpalServer(MERCHANT).start()
    yield srv
    srv.stop()


def make_store_manager(tmp_path, settings, **kw):
    from app.core.orders import OrderStore
    from app.core.products import ProductStore

    products = ProductStore(db_path=tmp_path / "p.db")
    orders = OrderStore(db_path=tmp_path / "o.db", product_store=products)
    return BotManager(
        settings, store=ConversationStore(db_path=tmp_path / "c.db"), product_store=products, order_store=orders,
        adapter_factories={"telegram": lambda s, p: InstantAdapter("x", p)}, log_dir=tmp_path, **kw,
    )


def test_diagnostic_buttons_hidden_without_manager():
    _, control, _ = make_card()
    assert find(control, "diag_zarinpal") is None and find(control, "diag_bale_pay") is None


def test_zarinpal_connection_test_success_and_failure(tmp_path, zp_server):
    settings = AppSettings()
    settings.business_mode = "store"
    settings.set_zarinpal_merchant_id(MERCHANT)
    settings.zarinpal_enabled = True
    manager = make_store_manager(tmp_path, settings, zarinpal_base_url=zp_server.base_url)
    _, control, _ = make_card(settings, manager)
    fire(find(control, "diag_zarinpal"), "on_click")
    out = find(control, "diag_zarinpal_result")
    assert out.visible and "زرین‌پال کار می‌کنه" in out.value and "/pg/StartPay/" in out.value

    zp_server.fail_request_with = {"code": -11, "message": "inactive"}
    fire(find(control, "diag_zarinpal"), "on_click")
    assert "فعال نیست" in out.value and out.color == theme_danger()


def theme_danger():
    from app import theme

    return theme.DANGER


def test_zarinpal_test_explains_when_not_configured(tmp_path, zp_server):
    settings = AppSettings()
    settings.business_mode = "store"
    manager = make_store_manager(tmp_path, settings, zarinpal_base_url=zp_server.base_url)
    _, control, _ = make_card(settings, manager)
    fire(find(control, "diag_zarinpal"), "on_click")
    assert "معتبر" in find(control, "diag_zarinpal_result").value and not zp_server.requests


def test_bale_pay_test_needs_running_bots_then_reports_real_result(tmp_path, tg_bale_pair):
    tg, bale = tg_bale_pair
    settings = make_settings()
    settings.business_mode = "store"
    settings.set_bale_pay_provider_token("WALLET-TEST-1")
    settings.bale_pay_enabled = True
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    _, control, _ = make_card(settings, manager)

    fire(find(control, "diag_bale_pay"), "on_click")  # هنوز خاموشه
    assert "خاموشن" in find(control, "diag_bale_result").value

    manager.start()
    try:
        assert wait_until(lambda: status(manager, "bale").connected)
        fire(find(control, "diag_bale_pay"), "on_click")
        assert "ربات بله وصله" in find(control, "diag_bale_result").value, "بدون چتِ مالک: فقط اتصال و نوعِ توکن"
        assert bale.invoices == []

        settings.owner_chats = {"bale": "555"}  # مالک چتِ بله‌ش رو ثبت کرده
        fire(find(control, "diag_bale_pay"), "on_click")
        assert "فاکتورِ آزمایشی" in find(control, "diag_bale_result").value
        assert bale.invoices[-1]["chat_id"] == "555" and bale.invoices[-1]["provider_token"] == "WALLET-TEST-1"
        assert bale.invoices[-1]["prices"][0]["amount"] == 10_000

        bale.invoice_mode = "error"
        fire(find(control, "diag_bale_pay"), "on_click")
        assert "نپذیرفت" in find(control, "diag_bale_result").value
        assert "invalid provider_token" in find(control, "diag_bale_result").value, "پیامِ دقیقِ خطای بله دیده می‌شه"
    finally:
        manager.stop(timeout=10)


@pytest.fixture
def tg_bale_pair():
    a = FakeBotApiServer(username="tg_shop_bot").start()
    b = FakeBotApiServer(username="bale_shop_bot").start()
    yield a, b
    a.stop()
    b.stop()


def test_last_real_chat_errors_are_shown_on_the_card(tmp_path):
    settings = AppSettings()
    settings.business_mode = "store"
    manager = make_store_manager(tmp_path, settings)
    manager._payments.last_errors["bale_pay"] = "بله خطا برگردوند: invalid provider_token"  # noqa: SLF001
    _, control, _ = make_card(settings, manager)
    shown = find(control, "last_errors")
    assert shown.visible and "invalid provider_token" in shown.value and "بله‌پی" in shown.value


# ----------------------------------------------------------------- UI = چیزی که مشتری می‌بینه


def test_ui_configured_payment_is_what_customer_sees(tmp_path, tg_bale_pair, zp_server, monkeypatch):
    tg, bale = tg_bale_pair
    settings = make_settings()
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale, zarinpal_base_url=zp_server.base_url)
    pid = products.add("گوشی", 1_000_000, 5)

    # صاحب فروشگاه همه‌چیز رو از همین کارت UI تنظیم می‌کنه (نه با ست‌کردنِ مستقیمِ فیلد)
    _, control, _ = make_card(settings, manager)
    num = find(control, "card_number")
    num.value = "۶۲۱۹۸۶۱۰۱۲۳۴۵۶۷۸"
    fire(num, "on_blur")
    holder = find(control, "card_holder")
    holder.value = "فروشگاه نمونه"
    fire(holder, "on_blur")
    tok = find(control, "bale_pay_token")
    tok.value = "WALLET-TEST-1111111111111111"
    fire(tok, "on_blur")
    fire(find(control, "bale_pay_enabled"), "on_change", value=True)
    merchant = find(control, "zarinpal_merchant_id")
    merchant.value = MERCHANT
    fire(merchant, "on_blur")
    fire(find(control, "zarinpal_enabled"), "on_change", value=True)
    fire(find(control, "require_customer_phone"), "on_change", value=True)
    reserve = find(control, "reservation_minutes")
    reserve.value = "20"
    fire(reserve, "on_blur")

    engine = ScriptedToolEngine(
        {
            "بخرم": [
                tool("create_order", items=[{"product_id": pid, "quantity": 1}], customer_phone="09121234567"),
                lambda r: tool("start_payment", order_id=r[0]["order_id"], method="card_to_card"),
                say("پیام پرداخت رو ببین"),
            ],
            "بدون تلفن": [tool("create_order", items=[{"product_id": pid, "quantity": 1}]), lambda r: say(f"خطا: {r[0]['error']} {r[0]['missing']}")],
        }
    )
    monkeypatch.setattr(ai_engine, "build_engine_from_settings", lambda s: engine)
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected and status(manager, "bale").connected)
        ask(tg, 50, "بدون تلفن", "خطا: missing_info ['phone']")  # «تلفن اجباری» از UI اعمال شده
        ask(tg, 51, "بخرم", "6219-8610-1234-5678")
        msg = [m for m in tg.sent_to(51) if "6219-8610-1234-5678" in m][0]
        assert "فروشگاه نمونه" in msg and "1,000,000 ریال" in msg
        prompt = engine.calls[0]["system_prompt"]
        assert "20 دقیقه" in prompt and "کارت‌به‌کارت (`card_to_card`)" in prompt
        assert "بله‌پی (`bale_pay`)" in prompt and "زرین‌پال (`zarinpal`)" in prompt, "هر سه روش از UI فعال شده"
        assert orders.list_for_chat("telegram", "51")[0].customer_phone == "09121234567"
        assert 19 * 60 < orders.list_for_chat("telegram", "51")[0].seconds_left() <= 20 * 60
    finally:
        manager.stop(timeout=10)
