"""
تست سرتاسریِ فروشگاه با «ادمین هوشمند»: ربات‌های واقعی (aiogram / BaleClient / BotManager
واقعی) روی سرور جعلیِ Bot API و زرین‌پالِ جعلی؛ فقط مدلِ زبانی سناریویی‌ه
(ScriptedToolEngine) — یعنی هر ابزاری که «مدل» صدا می‌زنه واقعاً اجرا می‌شه و هر پیامی که
مشتری می‌بینه واقعاً از مسیرِ آداپتور رد شده.
"""

import time

import pytest
from fake_servers import FakeBotApiServer
from fake_zarinpal import FakeZarinpalServer
from fakes import ScriptedToolEngine, say, tool
from helpers import wait_until
from test_adapters_e2e import make_settings

from app.core import ai_engine
from app.core.bale_adapter import BaleAdapter
from app.core.bale_client import BaleClient
from app.core.bot_manager import BotManager
from app.core.conversations import ConversationStore
from app.core.orders import (
    METHOD_BALE_PAY,
    METHOD_CARD_TO_CARD,
    METHOD_ZARINPAL,
    STATUS_CONFIRMED,
    STATUS_EXPIRED,
    STATUS_PAID,
    STATUS_PENDING_PAYMENT,
    OrderStore,
)
from app.core.products import ProductStore
from app.core.telegram_adapter import TelegramAdapter
from app.screens import orders as orders_screen

FAST = dict(debounce_wait=0.1, debounce_max_wait=0.3)
MERCHANT = "12345678-1234-1234-1234-123456789012"


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


@pytest.fixture
def zarinpal():
    srv = FakeZarinpalServer(MERCHANT).start()
    yield srv
    srv.stop()


def use_engine(monkeypatch, scripts=None, default=None):
    engine = ScriptedToolEngine(scripts or {}, default=default)
    monkeypatch.setattr(ai_engine, "build_engine_from_settings", lambda s: engine)
    return engine


def make_commerce_manager(tmp_path, settings, tg, bale, telegram_only=False, zarinpal_base_url=""):
    settings.business_mode = "store"
    settings.shop_mode = "shop_ai"  # جریانِ AIِ ۰.۵.۰ (آزمایشی)؛ پیش‌فرضِ ۱.۰.۰ دکمه‌ایه
    conv_store = ConversationStore(db_path=tmp_path / "conv.db")
    products = ProductStore(db_path=tmp_path / "products.db")
    orders = OrderStore(db_path=tmp_path / "orders.db", product_store=products)

    box: dict = {}  # رفع وابستگیِ دوری: factory به manager نیاز داره که هنوز ساخته نشده

    factories = {
        "telegram": lambda s, p: TelegramAdapter(
            s.get_telegram_token(), p, api_base=tg.base_url, retry_delays=(0.1, 0.3), poll_timeout=1
        ),
    }
    if not telegram_only:
        factories["bale"] = lambda s, p: BaleAdapter(
            s.get_bale_token(),
            p,
            poll_timeout=1,
            retry_delays=(0.1, 0.3),
            client_factory=lambda tok: BaleClient(tok, base_url_template=bale.url_template),
            payments=box["manager"]._payments,  # noqa: SLF001 — همون PaymentServiceِ (با تنظیمات) مدیر
            on_payment_confirmed=lambda order: box["manager"]._notify_payment_confirmed(order),  # noqa: SLF001
        )

    manager = BotManager(
        settings,
        store=conv_store,
        product_store=products,
        order_store=orders,
        adapter_factories=factories,
        pipeline_kwargs=FAST,
        log_dir=tmp_path,
        zarinpal_base_url=zarinpal_base_url,
        maintenance_interval=0.1,
        zarinpal_poll_interval=0.2,
    )
    box["manager"] = manager
    return manager, products, orders


def status(manager, name):
    return manager.get_status().platforms[name]


def got(server, chat_id, needle):
    return any(needle in m for m in server.sent_to(chat_id))


def ask(server, chat_id, text, needle):
    """مشتری پیام می‌ده و منتظر می‌مونه تا پیامی با این متن به همون چت برسه."""
    server.push_message(chat_id, text)
    assert wait_until(lambda: got(server, chat_id, needle), timeout=10), (
        f"جوابِ شامل {needle!r} نیومد؛ پیام‌ها: {server.sent_to(chat_id)}"
    )


def wait_status(orders, oid, expected, timeout=10):
    assert wait_until(lambda: orders.get(oid).status == expected, timeout=timeout), orders.get(oid).status


def start_both(manager):
    manager.start()
    assert wait_until(lambda: status(manager, "telegram").connected and status(manager, "bale").connected)


def force_deadline_passed(orders, oid):
    conn = orders._connection()  # noqa: SLF001
    conn.execute("UPDATE orders SET expires_ts=? WHERE id=?", (int(time.time()) - 1, oid))
    conn.commit()


# ============================================================ خریدِ کامل با زبانِ طبیعی


def test_telegram_customer_full_natural_language_card_to_card_purchase(tmp_path, tg, bale, monkeypatch):
    settings = make_settings()
    settings.card_to_card_number = "6219-8610-1234-5678"
    settings.card_to_card_holder_name = "فروشگاه نمونه"
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    pid = products.add("گوشی سامسونگ", 1_000_000, 5)
    engine = use_engine(
        monkeypatch,
        {
            "سلام، گوشی دارید؟": [tool("search_products", query="گوشی"), lambda r: say(f"سلام! {r[0]['products'][0]['available']} عدد داریم.")],
            "دو تا می‌خوام": [
                tool("create_order", items=[{"product_id": pid, "quantity": 2}], customer_name="مریم"),
                lambda r: say(f"ثبت شد؛ جمع {r[0]['total']}، {r[0]['reserved_for_minutes']} دقیقه رزرو. چطور پرداخت می‌کنی؟"),
            ],
            "کارت به کارت": [
                tool("start_payment", order_id=1, method="card_to_card"),
                say("پیام پرداخت رو ببین 👆"),
            ],
            "واریز کردم، پیگیری 4321": [
                tool("report_card_payment", order_id=1, reference="4321"),
                say("ثبت شد؛ بعد از تایید فروشنده خبرت می‌کنم."),
            ],
        },
    )
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        ask(tg, 10, "سلام، گوشی دارید؟", "5 عدد داریم")
        ask(tg, 10, "دو تا می‌خوام", "15 دقیقه رزرو")
        assert orders.get(1).status == STATUS_PENDING_PAYMENT and products.get(pid).stock_quantity == 5
        assert orders.available_quantity(pid) == 3, "رزرو، موجودیِ قابل‌فروش رو کم کرده، نه موجودیِ واقعی رو"

        ask(tg, 10, "کارت به کارت", "6219-8610-1234-5678")
        card_msg = [m for m in tg.sent_to(10) if "6219-8610-1234-5678" in m][0]
        assert "فروشگاه نمونه" in card_msg and "2,000,000 ریال" in card_msg, "عیناً از سمتِ برنامه، نه بازنویسیِ مدل"
        texts = tg.sent_to(10)
        assert texts.index("پیام پرداخت رو ببین 👆") < texts.index(card_msg), "اول حرفِ مدل، بعد پیامِ دقیقِ پرداخت"

        ask(tg, 10, "واریز کردم، پیگیری 4321", "بعد از تایید فروشنده")
        order = orders.get(1)
        assert order.status == STATUS_PAID and order.payment_reference == "4321" and order.customer_name == "مریم"
        assert products.get(pid).stock_quantity == 5, "تا تاییدِ صاحب فروشگاه موجودی کم نمی‌شه"

        # صاحب فروشگاه از صفحه‌ی سفارش‌ها تایید می‌کنه -> تاییدیه+فاکتور خودکار
        from fake_page import FakePage, find, fire

        control = orders_screen.build(FakePage(), "fa", orders, manager)
        fire(find(control, "confirm_1"), "on_click")
        assert wait_until(lambda: got(tg, 10, "سفارشتون تایید شد"))
        assert products.get(pid).stock_quantity == 3 and orders.available_quantity(pid) == 3

        # مدل همیشه تازه‌ترین وضعیت رو توی پرامپت می‌بینه
        assert "#%d | گوشی سامسونگ | 1,000,000 ریال | موجود: 5" % pid in engine.calls[0]["system_prompt"]
        history = manager.store.get_messages("telegram", "10")
        assert any("6219-8610-1234-5678" in m.content and m.role == "assistant" for m in history), "پیام پرداخت توی گفتگوها هم ثبت شده"
    finally:
        manager.stop(timeout=10)


# ============================================================ بله‌پی: لینک توی هر دو پیام‌رسان


def bale_pay_settings(settings):
    settings.set_bale_pay_provider_token("WALLET-TEST-1111111111111111")
    settings.bale_pay_enabled = True


def test_bale_customer_receives_the_native_invoice_inside_the_chat(tmp_path, tg, bale, monkeypatch):
    settings = make_settings()
    bale_pay_settings(settings)
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    pid = products.add("هدفون", 500_000, 3)
    use_engine(
        monkeypatch,
        {
            "یه هدفون می‌خوام": [tool("create_order", items=[{"product_id": pid, "quantity": 1}]), say("ثبت شد. بله‌پی؟")],
            "بله‌پی": [tool("start_payment", order_id=1, method="bale_pay"), say("فاکتور رو ببین")],
        },
    )
    start_both(manager)
    try:
        ask(bale, 40, "یه هدفون می‌خوام", "ثبت شد")
        ask(bale, 40, "بله‌پی", "فاکتور بله‌پی")
        assert wait_until(lambda: bale.invoices)
        inv = bale.invoices[0]
        assert inv["chat_id"] == "40" and inv["payload"] == "order:1" and inv["currency"] == "IRR"
        assert inv["provider_token"] == "WALLET-TEST-1111111111111111"
        assert inv["prices"] == [{"label": "هدفون", "amount": 500_000}]
        assert "createInvoiceLink" not in bale.calls, "دیگه به متدِ نامطمئنِ createInvoiceLink تکیه نمی‌کنیم"
        assert bale.buttons_to(40) == [], "لینکی در کار نیست؛ خودِ فاکتور توی چته"
        assert not tg.sent, "به تلگرام چیزی نباید بره"
    finally:
        manager.stop(timeout=10)


def test_telegram_customer_pays_through_the_bale_deep_link_end_to_end(tmp_path, tg, bale, monkeypatch):
    """مشتریِ تلگرامی دیپ‌لینکِ ربات بله می‌گیره؛ با «شروع» توی بله فاکتورِ بومی میاد؛ پرداخت که
    بشه سفارش تایید و خبرش به **تلگرام** می‌رسه — کلِ مسیر، با دو ربات و بدونِ هیچ لینکِ ساخته‌شده."""
    settings = make_settings()
    bale_pay_settings(settings)
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    pid = products.add("هدفون", 500_000, 3)
    use_engine(
        monkeypatch,
        {
            "یه هدفون می‌خوام": [tool("create_order", items=[{"product_id": pid, "quantity": 1}]), say("ثبت شد. چطور پرداخت می‌کنی؟")],
            "با بله‌پی": [tool("start_payment", order_id=1, method="bale_pay"), say("لینک رو ببین")],
        },
    )
    start_both(manager)
    try:
        ask(tg, 20, "یه هدفون می‌خوام", "ثبت شد")
        ask(tg, 20, "با بله‌پی", "https://ble.ir/bale_shop_bot?start=pay_1_")
        code = orders.get(1).gateway_ref
        link = f"https://ble.ir/bale_shop_bot?start=pay_1_{code}"
        msg = [m for m in tg.sent_to(20) if link in m][0]
        assert "[" not in msg and f"/pay 1 {code}" in msg, "تلگرام متن ساده نشون می‌ده؛ لینکِ عریان + فرمانِ دستی"
        assert tg.buttons_to(20) == [("💳 پرداخت با بله‌پی", link)], "دکمه‌ی لینک توی تلگرام"
        assert not bale.sent and not bale.invoices, "تا «شروع» نزده، چیزی به بله نمی‌ره"

        # مشتری توی بله (چتِ ۷۷) لینک رو باز می‌کنه و «شروع» رو می‌زنه
        bale.push_message(77, f"/start pay_1_{code}")
        assert wait_until(lambda: bale.invoices), "فاکتور باید توی چتِ بله‌ی مشتری بیاد"
        assert bale.invoices[0]["chat_id"] == "77" and bale.invoices[0]["payload"] == "order:1"
        assert wait_until(lambda: got(bale, 77, "فاکتور سفارش #1"))
        assert len(bale.sent_to(77)) == 1, "فرمانِ پرداخت از هوش مصنوعی رد نمی‌شه (فقط یک پاسخِ ثابت)"

        bale.push_pre_checkout_query("q1", 77, "order:1", 500_000)
        assert wait_until(lambda: bale.pre_checkout_answers and bale.pre_checkout_answers[-1]["ok"] is True)
        bale.push_successful_payment(77, "order:1", 500_000, "charge-77")
        wait_status(orders, 1, STATUS_CONFIRMED)
        assert wait_until(lambda: got(tg, 20, "پرداختتون با موفقیت دریافت شد")), "خبر به چتِ تلگرامیِ مشتری"
        assert not got(bale, 77, "پرداختتون با موفقیت دریافت شد"), "تاییدیه به چتِ سمتِ بله نمی‌ره"
    finally:
        manager.stop(timeout=10)


def test_manual_pay_command_and_wrong_codes_in_the_bale_bot(tmp_path, tg, bale, monkeypatch):
    settings = make_settings()
    bale_pay_settings(settings)
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    pid = products.add("هدفون", 500_000, 3)
    use_engine(
        monkeypatch,
        {"بخرم": [tool("create_order", items=[{"product_id": pid, "quantity": 1}]),
                  lambda r: tool("start_payment", order_id=r[0]["order_id"], method="bale_pay"), say("لینک رفت")]},
    )
    start_both(manager)
    try:
        ask(tg, 20, "بخرم", "لینک رفت")
        code = orders.get(1).gateway_ref
        ask(bale, 78, "/start pay_1_deadbeef", "معتبر نیست")  # کدِ غلط
        ask(bale, 78, "/pay 999 deadbeef", "معتبر نیست")  # سفارشِ ناموجود
        assert bale.invoices == []
        ask(bale, 78, f"/pay 1 {code}", "فاکتور سفارش #1")  # فرمانِ دستی
        assert wait_until(lambda: bale.invoices) and bale.invoices[0]["chat_id"] == "78"
    finally:
        manager.stop(timeout=10)


def test_bale_pay_payment_by_telegram_customer_is_auto_confirmed_and_routed_to_telegram(tmp_path, tg, bale, monkeypatch):
    settings = make_settings()
    bale_pay_settings(settings)
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    pid = products.add("هدفون", 500_000, 3)
    use_engine(
        monkeypatch,
        {
            "یه هدفون می‌خوام": [
                tool("create_order", items=[{"product_id": pid, "quantity": 2}]),
                lambda r: tool("start_payment", order_id=r[0]["order_id"], method="bale_pay"),
                say("لینک پرداخت ارسال شد"),
            ]
        },
    )
    start_both(manager)
    try:
        ask(tg, 20, "یه هدفون می‌خوام", "لینک پرداخت ارسال شد")
        assert orders.get(1).payment_method == METHOD_BALE_PAY
        # مشتری توی بله پرداخت می‌کنه؛ چتِ سمتِ بله (۹۹) با چتِ تلگرامیِ مشتری (۲۰) فرق داره
        bale.push_pre_checkout_query("q1", 99, "order:1", 1_000_000)
        assert wait_until(lambda: bale.pre_checkout_answers and bale.pre_checkout_answers[-1]["ok"] is True)
        bale.push_successful_payment(99, "order:1", 1_000_000, "charge-1")

        wait_status(orders, 1, STATUS_CONFIRMED)
        assert orders.get(1).payment_method == METHOD_BALE_PAY
        assert wait_until(lambda: products.get(pid).stock_quantity == 1), "بعد از ادعای اتمیکِ تایید، موجودی کم می‌شه"
        assert wait_until(lambda: got(tg, 20, "پرداختتون با موفقیت دریافت شد") and got(tg, 20, "سفارشتون تایید شد"))
        assert not bale.sent_to(99), "تاییدیه به چتِ سمتِ بله نباید بره"
    finally:
        manager.stop(timeout=10)


def test_bale_pay_stays_paid_for_manual_confirm_when_auto_confirm_is_off(tmp_path, tg, bale, monkeypatch):
    settings = make_settings()
    bale_pay_settings(settings)
    settings.auto_confirm_gateway_payments = False
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    pid = products.add("هدفون", 500_000, 3)
    use_engine(
        monkeypatch,
        {"بخرم": [tool("create_order", items=[{"product_id": pid, "quantity": 1}]),
                  lambda r: tool("start_payment", order_id=r[0]["order_id"], method="bale_pay"), say("لینک رفت")]},
    )
    start_both(manager)
    try:
        ask(tg, 20, "بخرم", "لینک رفت")
        bale.push_successful_payment(99, "order:1", 500_000, "charge-2")
        wait_status(orders, 1, STATUS_PAID)
        assert wait_until(lambda: got(tg, 20, "پرداختتون با موفقیت دریافت شد"))
        time.sleep(0.4)
        assert orders.get(1).status == STATUS_PAID and products.get(pid).stock_quantity == 3
        assert not got(tg, 20, "سفارشتون تایید شد")
    finally:
        manager.stop(timeout=10)


def test_pre_checkout_rejects_expired_orders_and_mismatched_amounts(tmp_path, tg, bale, monkeypatch):
    settings = make_settings()
    bale_pay_settings(settings)
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    pid = products.add("هدفون", 500_000, 5)
    use_engine(
        monkeypatch,
        {"بخرم": [tool("create_order", items=[{"product_id": pid, "quantity": 1}]), say("ثبت شد")]},
    )
    start_both(manager)
    try:
        ask(bale, 40, "بخرم", "ثبت شد")
        bale.push_pre_checkout_query("ok1", 40, "order:1", 500_000)
        bale.push_pre_checkout_query("bad-amount", 40, "order:1", 499_000)
        bale.push_pre_checkout_query("unknown", 40, "order:777", 500_000)
        assert wait_until(lambda: len(bale.pre_checkout_answers) >= 3)
        by_id = {a["pre_checkout_query_id"]: a["ok"] for a in bale.pre_checkout_answers}
        assert by_id == {"ok1": True, "bad-amount": False, "unknown": False}

        force_deadline_passed(orders, 1)
        bale.push_pre_checkout_query("late", 40, "order:1", 500_000)
        assert wait_until(lambda: any(a["pre_checkout_query_id"] == "late" for a in bale.pre_checkout_answers))
        assert [a for a in bale.pre_checkout_answers if a["pre_checkout_query_id"] == "late"][0]["ok"] is False
    finally:
        manager.stop(timeout=10)


def test_invoice_rejected_by_bale_is_reported_not_swallowed(tmp_path, tg, bale, monkeypatch):
    settings = make_settings()
    bale_pay_settings(settings)
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    pid = products.add("هدفون", 500_000, 3)
    bale.invoice_mode = "error"
    use_engine(
        monkeypatch,
        {"بخرم": [tool("create_order", items=[{"product_id": pid, "quantity": 1}]),
                  lambda r: tool("start_payment", order_id=r[0]["order_id"], method="bale_pay"),
                  say("متاسفم، بله‌پی الان خطا داد؛ کارت‌به‌کارت؟")]},
    )
    start_both(manager)
    try:
        ask(bale, 40, "بخرم", "کارت‌به‌کارت؟")
        assert bale.invoices and "فاکتور بله‌پی" not in "".join(bale.sent_to(40)), "پیامِ پرداخت نباید بره"
        assert "invalid provider_token" in manager.payment_last_errors()["bale_pay"], "خطای دقیقِ بله برای مالک ثبت می‌شه"
    finally:
        manager.stop(timeout=10)


def test_telegram_rejecting_buttons_still_delivers_the_deep_link_text(tmp_path, tg, bale, monkeypatch):
    settings = make_settings()
    bale_pay_settings(settings)
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    pid = products.add("هدفون", 500_000, 5)
    tg.reject_markup = True
    use_engine(
        monkeypatch,
        {"تلگرام بخرم": [tool("create_order", items=[{"product_id": pid, "quantity": 1}]),
                         lambda r: tool("start_payment", order_id=r[0]["order_id"], method="bale_pay"), say("لینک رفت")]},
    )
    start_both(manager)
    try:
        ask(tg, 20, "تلگرام بخرم", "https://ble.ir/bale_shop_bot?start=pay_1_")
        assert tg.buttons_to(20) == [], "دکمه رد شد؛ متنِ همراهِ لینک سالم رسیده"
    finally:
        manager.stop(timeout=10)


# ============================================================ زرین‌پال


def test_zarinpal_payment_detected_by_polling_and_auto_confirmed(tmp_path, tg, bale, zarinpal, monkeypatch):
    settings = make_settings()
    settings.set_zarinpal_merchant_id(MERCHANT)
    settings.zarinpal_enabled = True
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale, zarinpal_base_url=zarinpal.base_url)
    pid = products.add("گوشی", 2_000_000, 5)
    use_engine(
        monkeypatch,
        {"دو تا گوشی با زرین‌پال": [
            tool("create_order", items=[{"product_id": pid, "quantity": 2}]),
            lambda r: tool("start_payment", order_id=r[0]["order_id"], method="zarinpal"),
            say("لینک زرین‌پال رو بزن")]},
    )
    start_both(manager)
    try:
        ask(tg, 20, "دو تا گوشی با زرین‌پال", "لینک زرین‌پال رو بزن")
        authority = zarinpal.last_authority
        url = f"{zarinpal.base_url}/pg/StartPay/{authority}"
        assert wait_until(lambda: got(tg, 20, url)) and tg.buttons_to(20) == [("💳 پرداخت با زرین‌پال", url)]
        assert zarinpal.requests[0]["callback_url"] == "https://t.me/tg_shop_bot"
        assert zarinpal.requests[0]["amount"] == 4_000_000

        # هنوز پرداخت نشده: استعلام انجام می‌شه ولی چیزی عوض نمی‌شه
        assert wait_until(lambda: len(zarinpal.verifies) >= 2)
        assert orders.get(1).status == STATUS_PENDING_PAYMENT

        zarinpal.pay(authority)
        wait_status(orders, 1, STATUS_CONFIRMED)
        o = orders.get(1)
        assert o.payment_method == METHOD_ZARINPAL and o.payment_reference == "201" and o.paid_late is False
        # confirm() اول وضعیت رو «تاییدشده» می‌کنه (ادعای اتمیک) و *بعدش* موجودی رو کم می‌کنه؛ پس بعد از
        # دیدنِ وضعیت باید منتظرِ کم‌شدنِ موجودی هم بود (قبلاً گاهی زیر بارِ کلِ تست‌ها فلَیک می‌شد)
        assert wait_until(lambda: products.get(pid).stock_quantity == 3)
        assert wait_until(lambda: got(tg, 20, "پرداختتون با موفقیت دریافت شد") and got(tg, 20, "سفارشتون تایید شد"))
        assert zarinpal.verifies[-1]["amount"] == 4_000_000 and zarinpal.verifies[-1]["authority"] == authority
    finally:
        manager.stop(timeout=10)


def test_zarinpal_is_not_polled_after_payment_is_done(tmp_path, tg, bale, zarinpal, monkeypatch):
    settings = make_settings()
    settings.set_zarinpal_merchant_id(MERCHANT)
    settings.zarinpal_enabled = True
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale, zarinpal_base_url=zarinpal.base_url)
    pid = products.add("گوشی", 2_000_000, 5)
    use_engine(
        monkeypatch,
        {"بخرم": [tool("create_order", items=[{"product_id": pid, "quantity": 1}]),
                  lambda r: tool("start_payment", order_id=r[0]["order_id"], method="zarinpal"), say("لینک رفت")]},
    )
    start_both(manager)
    try:
        ask(bale, 40, "بخرم", "لینک رفت")
        zarinpal.pay(zarinpal.last_authority)
        wait_status(orders, 1, STATUS_CONFIRMED)
        n = len(zarinpal.verifies)
        time.sleep(0.8)
        assert len(zarinpal.verifies) <= n + 1, "بعد از نهایی‌شدن دیگه استعلام نمی‌شه"
        assert sum(1 for m in bale.sent_to(40) if "پرداختتون با موفقیت دریافت شد" in m) == 1, "فقط یک بار اطلاع‌رسانی"
    finally:
        manager.stop(timeout=10)


def test_late_zarinpal_payment_after_expiry_is_recorded_and_flagged_when_stock_was_sold(tmp_path, tg, bale, zarinpal, monkeypatch):
    settings = make_settings()
    settings.set_zarinpal_merchant_id(MERCHANT)
    settings.zarinpal_enabled = True
    settings.card_to_card_number = "6219-8610-1234-5678"
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale, zarinpal_base_url=zarinpal.base_url)
    pid = products.add("آخرین قطعه", 1_000_000, 1)
    use_engine(
        monkeypatch,
        {
            "اولی بخرم": [tool("create_order", items=[{"product_id": pid, "quantity": 1}]),
                          lambda r: tool("start_payment", order_id=r[0]["order_id"], method="zarinpal"), say("لینک رفت")],
            "دومی بخرم": [tool("create_order", items=[{"product_id": pid, "quantity": 1}]),
                          lambda r: say("ثبت شد" if r[0]["ok"] else "رزرو شده")],
        },
    )
    start_both(manager)
    try:
        ask(tg, 20, "اولی بخرم", "لینک رفت")
        authority = zarinpal.last_authority
        force_deadline_passed(orders, 1)
        wait_status(orders, 1, STATUS_EXPIRED)

        # مشتریِ دوم آخرین قطعه رو می‌خره و فروشنده تاییدش می‌کنه
        ask(bale, 40, "دومی بخرم", "ثبت شد")
        orders.mark_paid(2, METHOD_CARD_TO_CARD)
        orders.confirm(2)
        assert products.get(pid).stock_quantity == 0

        # حالا مشتریِ اول (که لینک دستش بود) دیر پرداخت می‌کنه
        zarinpal.pay(authority)
        wait_status(orders, 1, STATUS_PAID)
        o = orders.get(1)
        assert o.paid_late is True and o.payment_reference == "201", "پول گرفته شده؛ نباید گم بشه"
        assert wait_until(lambda: got(tg, 20, "بعد از پایان مهلتِ رزرو رسید"))
        assert products.get(pid).stock_quantity == 0
    finally:
        manager.stop(timeout=10)


# ============================================================ رزرو ۱۵ دقیقه‌ای


def test_expired_reservation_is_released_and_customer_is_told(tmp_path, tg, bale, monkeypatch):
    settings = make_settings()
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    pid = products.add("آخرین قطعه", 1_000_000, 1)
    use_engine(
        monkeypatch,
        {
            "اولی": [tool("create_order", items=[{"product_id": pid, "quantity": 1}]), say("ثبت شد، ۱۵ دقیقه فرصت داری")],
            "دومی": [tool("create_order", items=[{"product_id": pid, "quantity": 1}]),
                     lambda r: say("ثبت شد برای دومی" if r[0]["ok"] else f"رزرو: {r[0]['error']}")],
        },
    )
    start_both(manager)
    try:
        ask(tg, 20, "اولی", "ثبت شد، ۱۵ دقیقه")
        ask(bale, 40, "دومی", "رزرو:")  # وسطِ مهلت: آخرین قطعه برای نفر اول رزرو شده
        assert orders.list_for_chat("bale", "40") == []

        force_deadline_passed(orders, 1)
        wait_status(orders, 1, STATUS_EXPIRED)
        assert wait_until(lambda: got(tg, 20, "مهلتِ پرداختِ سفارش #1 تموم شد"))
        assert products.get(pid).stock_quantity == 1 and orders.available_quantity(pid) == 1

        ask(bale, 40, "دومی", "ثبت شد برای دومی")
        assert orders.list_for_chat("bale", "40")[0].status == STATUS_PENDING_PAYMENT
    finally:
        manager.stop(timeout=10)


# ============================================================ رفتارِ عمومی


def test_plain_engine_without_tool_support_still_chats_in_store_mode(tmp_path, tg, bale, monkeypatch):
    from fakes import FakeEngine

    settings = make_settings(bale_token="")
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale, telegram_only=True)
    monkeypatch.setattr(ai_engine, "build_engine_from_settings", lambda s: FakeEngine(reply=lambda t: f"ساده: {t}"))
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        ask(tg, 10, "سلام", "ساده: سلام")
    finally:
        manager.stop(timeout=10)


def test_consultant_mode_never_uses_the_store_agent(tmp_path, tg, bale, monkeypatch):
    settings = make_settings(bale_token="")
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale, telegram_only=True)
    settings.business_mode = "consultant"
    engine = use_engine(monkeypatch, {})
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        ask(tg, 10, "سلام", "پاسخ: سلام")
        assert engine.calls == [], "حالت مشاوره: همون گفتگوی ساده، نه ایجنتِ فروشگاه"
    finally:
        manager.stop(timeout=10)


def test_model_error_after_work_still_delivers_payment_message(tmp_path, tg, bale, monkeypatch):
    settings = make_settings(bale_token="")
    settings.card_to_card_number = "6219-8610-1234-5678"
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale, telegram_only=True)
    pid = products.add("گوشی", 1_000_000, 5)

    def boom(results):
        raise ai_engine.AiEngineError("quota exceeded")

    use_engine(
        monkeypatch,
        {"بخرم": [tool("create_order", items=[{"product_id": pid, "quantity": 1}]),
                  lambda r: tool("start_payment", order_id=r[0]["order_id"], method="card_to_card"), boom]},
    )
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        ask(tg, 10, "بخرم", "6219-8610-1234-5678")
        assert not got(tg, 10, "متأسفم"), "سفارش ثبت شده؛ پیامِ خطای عمومی گمراه‌کننده‌ست"
    finally:
        manager.stop(timeout=10)


# ============================================================ بازبینیِ بی‌رحمانه: سناریوهای واقعی


def test_receipt_photo_reaches_the_ai_as_a_note_instead_of_being_ignored(tmp_path, tg, bale, monkeypatch):
    settings = make_settings()
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    engine = use_engine(
        monkeypatch,
        {
            "[پیوست: عکس — محتوای فایل برای من قابل‌خوندن نیست]": [say("عکس رسید رسید؛ شماره پیگیریش رو هم بنویس")],
            "این رسیدمه\n[پیوست: فایل — محتوای فایل برای من قابل‌خوندن نیست]": [say("فایل رسید؛ ممنون")],
            "[پیوست: پیام صوتی — محتوای فایل برای من قابل‌خوندن نیست]": [say("صدا رو نمی‌تونم بشنوم، بنویس لطفاً")],
        },
    )
    start_both(manager)
    try:
        tg.push_media(20, "photo")
        assert wait_until(lambda: got(tg, 20, "شماره پیگیریش رو هم بنویس"), timeout=10)
        tg.push_media(20, "document", caption="این رسیدمه")
        assert wait_until(lambda: got(tg, 20, "فایل رسید؛ ممنون"), timeout=10)
        bale.push_media(40, "voice")
        assert wait_until(lambda: got(bale, 40, "صدا رو نمی‌تونم بشنوم"), timeout=10)
        assert len(engine.calls) == 3
    finally:
        manager.stop(timeout=10)


def test_stale_expiry_is_silent_but_recent_expiry_notifies_and_card_orders_get_a_hint(tmp_path, tg, bale, monkeypatch):
    settings = make_settings()
    settings.card_to_card_number = "6219-8610-1234-5678"
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
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
    start_both(manager)
    try:
        assert wait_until(lambda: got(tg, 11, "مهلتِ پرداختِ سفارش") and got(tg, 12, "مهلتِ پرداختِ سفارش"))
        assert not got(tg, 11, "پرداخت کردم"), "کارت‌به‌کارت نبوده؛ راهنمای واریز نمی‌خواد"
        assert got(tg, 12, "پرداخت کردم"), "کارت‌به‌کارت بوده؛ اگه واریز کرده بنویسه"
        assert all(orders.get(i).status == STATUS_EXPIRED for i in (old, recent_plain, recent_card))
        time.sleep(0.4)
        assert tg.sent_to(10) == [], "سفارشِ ساعت‌ها پیش منقضی‌شده بی‌صدا منقضی می‌شه"
    finally:
        manager.stop(timeout=10)
