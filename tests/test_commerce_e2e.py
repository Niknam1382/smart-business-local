"""
تست سرتاسریِ سفارش و پرداخت نسخه‌ی ۱.۰.۰: رباتِ واقعی (aiogram + BotManager واقعی) روی سرورِ جعلیِ
Bot API، و «بله» فقط به‌عنوانِ درگاهِ پرداختِ بله‌پی (کلاینتِ واقعیِ BalePayClient روی همان سرورِ
جعلی). مشتری **فقط با دکمه‌ها** خرید می‌کند؛ مدلِ زبانی فقط وقتی در صحنه است که تستی خودش درباره‌ی
پاسخ‌های AI باشد (ScriptedToolEngine).

این فایل ابزارِ مشترکِ تست‌های سرتاسریِ فروش را صادر می‌کند: ``FAST``، ``make_commerce_manager``،
``status``، ``got``، ``ask``، ``wait_status``، ``start_connected``، ``use_engine``، ``bale_pay_settings``.
فیکسچرِ ``bale`` (سرورِ جعلیِ درگاه + وصل‌کردنِ BalePayClient) به ``tests/conftest.py`` منتقل شده تا
چند ماژول بدونِ importِ نامِ فیکسچر ازش استفاده کنند.

زرین‌پال و «رباتِ گفتگویِ بله» حذف شده‌اند؛ تنها دو روشِ پرداخت هست: کارت‌به‌کارت و بله‌پی.
"""

import time

import pytest
from fake_page import FakePage, find, fire
from fake_servers import FakeBotApiServer
from fakes import FakeEngine, ScriptedToolEngine, say, tool
from helpers import wait_until
from shop_buttons import buy, order_of, tap
from test_adapters_e2e import make_settings

from app.core import ai_engine
from app.core.bale_pay import TEST_PROVIDER_TOKEN
from app.core.bot_manager import BotManager
from app.core.conversations import ConversationStore
from app.core.orders import (
    METHOD_BALE_PAY,
    METHOD_CARD_TO_CARD,
    OrderError,
    OrderStore,
    STATUS_CONFIRMED,
    STATUS_EXPIRED,
    STATUS_PAID,
    STATUS_PENDING_PAYMENT,
)
from app.core.products import ProductStore
from app.core.telegram_adapter import TelegramAdapter
from app.screens import orders as orders_screen

FAST = dict(debounce_wait=0.1, debounce_max_wait=0.3)
BALE_PAY_BOT_TOKEN = "987654321:BALEpayBALEpayBALEpayBALEpay12345"


@pytest.fixture
def tg():
    srv = FakeBotApiServer(username="tg_shop_bot").start()
    yield srv
    srv.stop()


def use_engine(monkeypatch, scripts=None, default=None):
    engine = ScriptedToolEngine(scripts or {}, default=default)
    monkeypatch.setattr(ai_engine, "build_engine_from_settings", lambda s: engine)
    return engine


def bale_pay_settings(settings, provider_token: str = TEST_PROVIDER_TOKEN):
    """بله‌پیِ کامل: توکنِ رباتِ پرداخت + توکنِ درگاه + روشن بودن."""
    settings.set_bale_pay_bot_token(BALE_PAY_BOT_TOKEN)
    settings.set_bale_pay_provider_token(provider_token)
    settings.bale_pay_enabled = True
    settings.auto_confirm_gateway_payments = True


def make_commerce_manager(tmp_path, settings, tg, bale=None, maintenance_interval=0.1):
    """BotManagerِ واقعی با فروشگاهِSQLite؛ آداپتورِ تلگرام به سرورِ جعلیِ ``tg`` وصل می‌شه.

    ``bale=None`` یعنی بله‌پی تنظیم‌نشده ⇒ فقط کارت‌به‌کارت. ``business_mode`` اگر در تنظیمات
    مشخص شده باشد احترام می‌بیند (تست‌های حالتِ مشاوره‌ای) وگرنه «store»."""
    settings.business_mode = settings.business_mode or "store"
    conv_store = ConversationStore(db_path=tmp_path / "conv.db")
    products = ProductStore(db_path=tmp_path / "products.db")
    orders = OrderStore(db_path=tmp_path / "orders.db", product_store=products)
    factories = {
        "telegram": lambda s, p: TelegramAdapter(
            s.get_telegram_token(), p, api_base=tg.base_url, retry_delays=(0.1, 0.3), poll_timeout=1
        )
    }
    manager = BotManager(
        settings,
        store=conv_store,
        product_store=products,
        order_store=orders,
        adapter_factories=factories,
        pipeline_kwargs=FAST,
        log_dir=tmp_path,
        maintenance_interval=maintenance_interval,
        bale_pay_poll_interval=0.2,
    )
    return manager, products, orders


def status(manager, name):
    return manager.get_status().platforms[name]


def got(server, chat_id, needle):
    return any(needle in m for m in server.sent_to(chat_id))


def got_link_button(server, chat_id, url_prefix, label: str = ""):
    """لینکِ پرداخت فقط در *دکمه* می‌رود (متنِ پیامِ ربات URL خام ندارد) ⇒ سیگنالِ مثبتِ این تست‌ها."""
    return any(
        (url or "").startswith(url_prefix) and (not label or text == label)
        for text, url in server.buttons_to(chat_id)
    )


def wait_link_button(server, chat_id, url_prefix, label: str = ""):
    assert wait_until(lambda: got_link_button(server, chat_id, url_prefix, label), timeout=20), (
        url_prefix, server.buttons_to(chat_id), server.sent_to(chat_id)
    )


def ask(server, chat_id, text, needle):
    """مشتری پیام می‌دهد و منتظر می‌ماند تا پیامی با این متن به همان چت برسد."""
    server.push_message(chat_id, text)
    assert wait_until(lambda: got(server, chat_id, needle), timeout=20), (
        f"جوابِ شامل {needle!r} نیومد؛ پیام‌ها: {server.sent_to(chat_id)}"
    )


def wait_status(orders, oid, expected, timeout=10):
    assert wait_until(lambda: orders.get(oid).status == expected, timeout=timeout), orders.get(oid).status


def start_connected(manager):
    manager.start()
    assert wait_until(lambda: status(manager, "telegram").connected, timeout=20)


def bale_pay_ready(manager):
    """صبرِ مثبت: رباتِ پرداختِ بله واقعاً getMe گرفته (بدونِ آن بله‌پی در منو نیست)."""
    assert wait_until(lambda: manager._bale_pay_client is not None and manager._bale_pay_status == "connected", timeout=20)  # noqa: SLF001


def force_deadline_passed(orders, oid):
    conn = orders._connection()  # noqa: SLF001
    conn.execute("UPDATE orders SET expires_ts=? WHERE id=?", (int(time.time()) - 1, oid))
    conn.commit()


# ================================================== خریدِ کاملِ دکمه‌ای + تأییدِ مالک


def test_telegram_customer_full_button_card_to_card_purchase_and_owner_confirm(tmp_path, tg, monkeypatch):
    settings = make_settings()
    settings.card_to_card_number = "6219-8610-1234-5678"
    settings.card_to_card_holder_name = "فروشگاه نمونه"
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg)
    pid = products.add("گوشی سامسونگ", 1_000_000, 5)
    use_engine(monkeypatch, {})
    start_connected(manager)
    try:
        buy(tg, 10, pid, qty=2, method="card_to_card")
        assert wait_until(lambda: got(tg, 10, "6219-8610-1234-5678"))
        card_msg = [m for m in tg.sent_to(10) if "6219-8610-1234-5678" in m][0]
        assert "فروشگاه نمونه" in card_msg and "2,000,000" in card_msg, "عیناً از سمتِ برنامه"
        order = order_of(orders, 10)
        assert order.status == STATUS_PENDING_PAYMENT and order.customer_name == "مریم احمدی"
        assert products.get(pid).stock_quantity == 5
        assert orders.available_quantity(pid) == 3, "رزرو، موجودیِ قابل‌فروش را کم کرده، نه موجودیِ واقعی را"

        tap(tg, 10, f"c:paid:{order.id}")
        wait_status(orders, order.id, STATUS_PAID)
        assert products.get(pid).stock_quantity == 5, "تا تاییدِ صاحب فروشگاه موجودی کم نمی‌شه"

        # صاحب فروشگاه از صفحه‌ی سفارش‌ها تایید می‌کند ← تاییدیه به مشتری
        control = orders_screen.build(FakePage(), "fa", orders, manager)
        fire(find(control, f"confirm_{order.id}"), "on_click")
        assert wait_until(lambda: got(tg, 10, "سفارشتون تایید شد"), timeout=20)
        assert products.get(pid).stock_quantity == 3 and orders.available_quantity(pid) == 3
    finally:
        manager.stop(timeout=10)


# ================================================== بله‌پی: لینکِ پرداخت برای مشتریِ تلگرامی


def test_telegram_customer_gets_a_direct_bale_pay_invoice_link(tmp_path, tg, bale, monkeypatch):
    settings = make_settings()
    bale_pay_settings(settings)
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    pid = products.add("هدفون", 500_000, 3)
    use_engine(monkeypatch, {})
    start_connected(manager)
    bale_pay_ready(manager)
    try:
        buy(tg, 20, pid, method="bale_pay")
        assert wait_until(lambda: bale.invoice_links, timeout=20), "بله‌پی باید لینکِ مستقیم بسازد"
        oid = order_of(orders, 20).id
        link = bale.invoice_links[0]
        assert link["currency"] == "IRR" and link["provider_token"] == TEST_PROVIDER_TOKEN
        assert link["payload"] == f"order:{oid}:{orders.get(oid).gateway_ref}"
        assert link["prices"] == [{"label": "هدفون", "amount": 500_000}], "قیمت‌ها از دیتابیس، نه از مشتری"
        wait_link_button(tg, 20, "https://bale.ai/pay/", label="🔵 پرداخت در بله")
        assert not bale.invoices, "مسیرِ اصلی لینک است؛ فاکتورِ بومی فقط پشتیبان است"
    finally:
        manager.stop(timeout=10)


def test_bale_pay_payment_is_auto_confirmed_and_routed_to_telegram(tmp_path, tg, bale, monkeypatch):
    settings = make_settings()
    bale_pay_settings(settings)
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    pid = products.add("هدفون", 500_000, 3)
    use_engine(monkeypatch, {})
    start_connected(manager)
    bale_pay_ready(manager)
    try:
        buy(tg, 20, pid, qty=2, method="bale_pay")
        assert wait_until(lambda: order_of(orders, 20) is not None and order_of(orders, 20).payment_method == METHOD_BALE_PAY, timeout=20)
        oid = order_of(orders, 20).id
        code = orders.get(oid).gateway_ref
        # مشتری در بله پرداخت می‌کند؛ چتِ سمتِ بله (۹۹) با چتِ تلگرامیِ مشتری (۲۰) فرق دارد
        bale.push_pre_checkout_query("q1", 99, f"order:{oid}:{code}", 1_000_000)
        assert wait_until(lambda: bale.pre_checkout_answers and bale.pre_checkout_answers[-1]["ok"] is True, timeout=20)
        bale.push_successful_payment(99, f"order:{oid}:{code}", 1_000_000, "charge-1")

        wait_status(orders, oid, STATUS_CONFIRMED)
        assert orders.get(oid).payment_method == METHOD_BALE_PAY
        assert wait_until(lambda: products.get(pid).stock_quantity == 1, timeout=20), "بعد از تایید، موجودی کم می‌شه"
        assert wait_until(lambda: got(tg, 20, "پرداختتون با موفقیت دریافت شد") and got(tg, 20, "سفارشتون تایید شد"), timeout=20)
        assert not bale.sent_to(99), "تاییدیه به چتِ سمتِ بله نباید بره"
        assert "charge-1" in bale.inquired_transactions, "قبل از تایید، تراکنش از خودِ بله استعلام شده"
    finally:
        manager.stop(timeout=10)


def test_bale_pay_stays_paid_for_manual_confirm_when_auto_confirm_is_off(tmp_path, tg, bale, monkeypatch):
    settings = make_settings()
    bale_pay_settings(settings)
    settings.auto_confirm_gateway_payments = False
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    pid = products.add("هدفون", 500_000, 3)
    use_engine(monkeypatch, {})
    start_connected(manager)
    bale_pay_ready(manager)
    try:
        buy(tg, 20, pid, method="bale_pay")
        oid = order_of(orders, 20).id
        code = orders.get(oid).gateway_ref
        bale.push_successful_payment(99, f"order:{oid}:{code}", 500_000, "charge-2")
        wait_status(orders, oid, STATUS_PAID)
        assert wait_until(lambda: got(tg, 20, "پرداختتون با موفقیت دریافت شد"), timeout=20)
        # سیگنالِ مثبتِ «پردازشِ این رویداد تمام شد»: استعلامِ تراکنش در سرور ثبت شده
        assert wait_until(lambda: "charge-2" in bale.inquired_transactions, timeout=20)
        assert orders.get(oid).status == STATUS_PAID and products.get(pid).stock_quantity == 3
        assert not got(tg, 20, "سفارشتون تایید شد")
    finally:
        manager.stop(timeout=10)


def test_pre_checkout_rejects_expired_orders_and_mismatched_amounts(tmp_path, tg, bale, monkeypatch):
    settings = make_settings()
    bale_pay_settings(settings)
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    pid = products.add("هدفون", 500_000, 5)
    oid = orders.create("telegram", "40", [(pid, 1)])  # تمرکزِ این تست روی پیش‌پرداخته، نه روی ساختنِ سفارش
    use_engine(monkeypatch, {})
    start_connected(manager)
    bale_pay_ready(manager)
    try:
        bale.push_pre_checkout_query("ok1", 40, f"order:{oid}", 500_000)
        bale.push_pre_checkout_query("bad-amount", 40, f"order:{oid}", 499_000)
        bale.push_pre_checkout_query("unknown", 40, "order:777", 500_000)
        assert wait_until(lambda: len(bale.pre_checkout_answers) >= 3, timeout=20)
        by_id = {a["pre_checkout_query_id"]: a["ok"] for a in bale.pre_checkout_answers}
        assert by_id == {"ok1": True, "bad-amount": False, "unknown": False}

        force_deadline_passed(orders, oid)
        bale.push_pre_checkout_query("late", 40, f"order:{oid}", 500_000)
        assert wait_until(lambda: any(a["pre_checkout_query_id"] == "late" for a in bale.pre_checkout_answers), timeout=20)
        assert [a for a in bale.pre_checkout_answers if a["pre_checkout_query_id"] == "late"][0]["ok"] is False
    finally:
        manager.stop(timeout=10)


def test_invoice_link_failure_falls_back_to_the_bale_deep_link_and_pay_command(tmp_path, tg, bale, monkeypatch):
    """بله لینک نساخت → برنامه دیپ‌لینکِ رباتِ پرداخت می‌دهد و مشتری با /pay فاکتورِ بومی می‌گیرد."""
    settings = make_settings()
    bale_pay_settings(settings)
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    pid = products.add("هدفون", 500_000, 3)
    bale.invoice_link_mode = "error"
    use_engine(monkeypatch, {})
    start_connected(manager)
    bale_pay_ready(manager)
    try:
        buy(tg, 20, pid, method="bale_pay")
        wait_link_button(tg, 20, "https://ble.ir/bale_pay_bot?start=pay_")
        oid = order_of(orders, 20).id
        code = orders.get(oid).gateway_ref
        msg = [m for m in tg.sent_to(20) if f"/pay {oid} {code}" in m][0]
        assert f"/pay {oid} {code}" in msg, "متنِ پشتیبانِ دستی هم در پیام است"
        assert "[" not in msg, "لینکِ مارک‌داون نمی‌رود؛ تلگرام متنِ ساده نشان می‌دهد"
        assert not bale.invoices, "تا «شروع» نزده، چیزی به بله نمی‌رود"

        bale.push_message(77, f"/start pay_{oid}_{code}")
        assert wait_until(lambda: bale.invoices, timeout=20), "فاکتور باید در چتِ بله‌ی مشتری بیاید"
        assert bale.invoices[0]["chat_id"] == "77" and bale.invoices[0]["payload"] == f"order:{oid}:{code}"
        assert bale.invoices[0]["currency"] == "IRR" and bale.invoices[0]["prices"] == [{"label": "هدفون", "amount": 500_000}]
        assert wait_until(lambda: got(bale, 77, f"سفارش #{oid}"), timeout=20)
        assert len(bale.sent_to(77)) == 1, "فرمانِ پرداخت از هوش مصنوعی رد نمی‌شه (فقط یک پاسخِ ثابت)"
    finally:
        manager.stop(timeout=10)


def test_manual_pay_command_and_wrong_codes_in_the_bale_pay_bot(tmp_path, tg, bale, monkeypatch):
    settings = make_settings()
    bale_pay_settings(settings)
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    pid = products.add("هدفون", 500_000, 3)
    use_engine(monkeypatch, {})
    start_connected(manager)
    bale_pay_ready(manager)
    try:
        buy(tg, 20, pid, method="bale_pay")
        wait_link_button(tg, 20, "https://bale.ai/pay/")
        oid = order_of(orders, 20).id
        code = orders.get(oid).gateway_ref
        ask(bale, 78, f"/start pay_{oid}_deadbeef", "معتبر نیست")  # کدِ غلط
        ask(bale, 78, "/pay 999 deadbeef", "معتبر نیست")  # سفارشِ ناموجود
        assert bale.invoices == []
        ask(bale, 78, f"/pay {oid} {code}", f"سفارش #{oid}")  # فرمانِ دستی
        assert wait_until(lambda: bale.invoices, timeout=20) and bale.invoices[0]["chat_id"] == "78"
    finally:
        manager.stop(timeout=10)


def test_send_invoice_rejected_by_bale_is_reported_not_swallowed(tmp_path, tg, bale, monkeypatch):
    settings = make_settings()
    bale_pay_settings(settings)
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    pid = products.add("هدفون", 500_000, 3)
    bale.invoice_link_mode = "error"
    bale.invoice_mode = "error"  # بله فاکتورِ بومی را هم رد می‌کند (provider_token نامعتبر)
    use_engine(monkeypatch, {})
    start_connected(manager)
    bale_pay_ready(manager)
    try:
        buy(tg, 20, pid, method="bale_pay")
        oid = order_of(orders, 20).id
        code = orders.get(oid).gateway_ref
        ask(bale, 79, f"/pay {oid} {code}", "ممکن نشد")
        assert wait_until(lambda: bale.invoices, timeout=20), "فاکتور فرستاده شد ولی بله ردش کرد"
        assert wait_until(lambda: "bale_pay" in manager.payment_last_errors(), timeout=20)
        assert "invalid provider_token" in manager.payment_last_errors()["bale_pay"], "خطای دقیقِ بله برای مالک ثبت می‌شه"
    finally:
        manager.stop(timeout=10)


def test_duplicate_charge_id_does_not_confirm_twice(tmp_path, tg, bale, monkeypatch):
    """یک تراکنش = یک سفارش؛ تکرارِ رویدادِ پرداخت نباید موجودی را دو بار کم کند."""
    settings = make_settings()
    bale_pay_settings(settings)
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    pid = products.add("هدفون", 500_000, 3)
    use_engine(monkeypatch, {})
    start_connected(manager)
    bale_pay_ready(manager)
    try:
        buy(tg, 20, pid, method="bale_pay")
        oid = order_of(orders, 20).id
        code = orders.get(oid).gateway_ref
        bale.push_successful_payment(91, f"order:{oid}:{code}", 500_000, "charge-dup")
        wait_status(orders, oid, STATUS_CONFIRMED)
        assert wait_until(lambda: products.get(pid).stock_quantity == 2, timeout=20)
        bale.push_successful_payment(91, f"order:{oid}:{code}", 500_000, "charge-dup")
        # سیگنالِ مثبت: دورِ بعدیِ پولینگِ پرداخت انجام شده (رویدادِ تکراری مصرف شده)
        polls = bale.calls.count("getUpdates")
        assert wait_until(lambda: bale.calls.count("getUpdates") > polls, timeout=20)
        assert products.get(pid).stock_quantity == 2 and orders.get(oid).status == STATUS_CONFIRMED
    finally:
        manager.stop(timeout=10)


# ================================================== رزرو ۱۵ دقیقه‌ای


def test_expired_reservation_is_released_and_customer_is_told(tmp_path, tg, monkeypatch):
    settings = make_settings()
    settings.card_to_card_number = "6219-8610-1234-5678"
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg)
    pid = products.add("آخرین قطعه", 1_000_000, 1)
    use_engine(monkeypatch, {})
    start_connected(manager)
    try:
        buy(tg, 20, pid, method="card_to_card")
        first = order_of(orders, 20).id
        assert orders.available_quantity(pid) == 0
        with pytest.raises(OrderError):  # وسطِ مهلت: آخرین قطعه برای نفر اول رزرو شده
            orders.create("telegram", "40", [(pid, 1)])
        assert orders.list_for_chat("telegram", "40") == []

        force_deadline_passed(orders, first)
        wait_status(orders, first, STATUS_EXPIRED)
        assert wait_until(lambda: got(tg, 20, f"مهلتِ پرداختِ سفارش #{first}"), timeout=20)
        assert products.get(pid).stock_quantity == 1 and orders.available_quantity(pid) == 1

        buy(tg, 40, pid, method="card_to_card")
        assert order_of(orders, 40).status == STATUS_PENDING_PAYMENT
    finally:
        manager.stop(timeout=10)


# ================================================== رفتارِ عمومیِ AI (بدونِ دخالت در سبد)


def test_plain_engine_without_tool_support_still_chats_in_store_mode(tmp_path, tg, monkeypatch):
    settings = make_settings()
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg)
    monkeypatch.setattr(ai_engine, "build_engine_from_settings", lambda s: FakeEngine(reply=lambda t: f"ساده: {t}"))
    start_connected(manager)
    try:
        ask(tg, 10, "سلام", "ساده: سلام")
    finally:
        manager.stop(timeout=10)


def test_consultant_mode_uses_plain_chat_without_any_shop_agent(tmp_path, tg, monkeypatch):
    settings = make_settings()
    settings.business_mode = "consultant"
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg)
    engine = use_engine(monkeypatch, {})
    start_connected(manager)
    try:
        ask(tg, 10, "سلام", "پاسخ: سلام")
        assert engine.calls == [], "حالت مشاوره: همون گفتگوی ساده، بدونِ هیچ ابزار"
    finally:
        manager.stop(timeout=10)


def test_ai_can_never_touch_the_cart_or_orders_even_if_the_model_tries(tmp_path, tg, monkeypatch):
    """هر ابزارِ سبد/سفارش/پرداخت که «مدل» صدا بزند ناشناخته است: نه سفارشی ساخته می‌شه، نه سبدی عوض می‌شه."""
    settings = make_settings()
    settings.card_to_card_number = "6219-8610-1234-5678"
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg)
    pid = products.add("گوشی", 1_000_000, 5)
    engine = use_engine(
        monkeypatch,
        {"دو تا گوشی بخر برام": [
            tool("create_order", items=[{"product_id": pid, "quantity": 2}]),
            tool("add_to_cart", product_id=pid, quantity=2),
            lambda r: say("از دکمه‌های منو استفاده کن 🙂"),
        ]},
    )
    start_connected(manager)
    try:
        ask(tg, 10, "دو تا گوشی بخر برام", "از دکمه‌های منو استفاده کن")
        assert orders.list() == [] and products.get(pid).stock_quantity == 5 and orders.available_quantity(pid) == 5
        assert not got(tg, 10, "6219-8610-1234-5678"), "پیامِ پرداخت فقط از دکمه‌ها می‌آد"
        tools = {t for c in engine.calls for t in c["tools"]}
        assert tools and tools <= {"suggest_products"}, f"AI فقط پیشنهادِ کالا دارد: {tools}"
        assert manager._pipeline._shop_flow.carts.quantity("telegram", "10", pid) == 0  # noqa: SLF001
    finally:
        manager.stop(timeout=10)


def test_receipt_photo_outside_the_receipt_step_goes_to_the_ai_as_a_note(tmp_path, tg, monkeypatch):
    """عکسی که مشتری *بیرونِ* مرحله‌ی رسید می‌فرستد نادیده گرفته نمی‌شود؛ به‌صورت یادداشت به AI می‌رود."""
    settings = make_settings()
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg)
    engine = use_engine(
        monkeypatch,
        {
            "[پیوست: عکس — محتوای فایل برای من قابل‌خوندن نیست]": [say("عکس رسید رسید؛ شماره پیگیریش رو هم بنویس")],
            "این رسیدمه\n[پیوست: فایل — محتوای فایل برای من قابل‌خوندن نیست]": [say("فایل رسید؛ ممنون")],
        },
    )
    start_connected(manager)
    try:
        tg.push_media(20, "photo")
        assert wait_until(lambda: got(tg, 20, "شماره پیگیریش رو هم بنویس"), timeout=20)
        tg.push_media(20, "document", caption="این رسیدمه")
        assert wait_until(lambda: got(tg, 20, "فایل رسید؛ ممنون"), timeout=20)
        assert len(engine.calls) == 2
    finally:
        manager.stop(timeout=10)


def test_stale_expiry_is_silent_but_recent_expiry_notifies_and_card_orders_get_a_hint(tmp_path, tg, monkeypatch):
    settings = make_settings()
    settings.card_to_card_number = "6219-8610-1234-5678"
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, maintenance_interval=0.2)
    pid = products.add("گوشی", 1_000_000, 9)
    old = orders.create("telegram", "10", [(pid, 1)])  # برنامه ساعت‌ها خاموش بود
    recent_plain = orders.create("telegram", "11", [(pid, 1)])
    recent_card = orders.create("telegram", "12", [(pid, 1)])
    orders.set_payment_info(recent_card, METHOD_CARD_TO_CARD)
    conn = orders._connection()  # noqa: SLF001
    conn.execute("UPDATE orders SET expires_ts=? WHERE id=?", (int(time.time()) - 3 * 3600, old))
    conn.execute("UPDATE orders SET expires_ts=? WHERE id IN (?, ?)", (int(time.time()) - 60, recent_plain, recent_card))
    conn.commit()
    use_engine(monkeypatch, {})
    start_connected(manager)
    try:
        assert wait_until(lambda: got(tg, 11, "مهلتِ پرداختِ سفارش") and got(tg, 12, "مهلتِ پرداختِ سفارش"), timeout=20)
        assert not got(tg, 11, "پرداخت کردم"), "کارت‌به‌کارت نبوده؛ راهنمای واریز نمی‌خواد"
        assert got(tg, 12, "پرداخت کردم"), "کارت‌به‌کارت بوده؛ اگه واریز کرده بنویسه"
        assert all(orders.get(i).status == STATUS_EXPIRED for i in (old, recent_plain, recent_card))
        # سیگنالِ مثبتِ «جاروکننده یک دور کامل زده»: وضعیتِ سفارشِ قدیمی هم بررسی شده
        assert wait_until(lambda: orders.get(old).status == STATUS_EXPIRED, timeout=20)
        assert tg.sent_to(10) == [], "سفارشِ ساعت‌ها پیش منقضی‌شده بی‌صدا منقضی می‌شه"
    finally:
        manager.stop(timeout=10)
