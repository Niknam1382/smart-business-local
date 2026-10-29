"""
کنسولِ مالک: ثبتِ امنِ مالک با کدِ یک‌بارمصرف، فرمان‌های /confirm /reject ...، اعلانِ پرداخت و
فروش، و ابزارِ «نیاز به پیگیری» — هم واحد (OwnerConsole) هم سرتاسری (ربات‌های واقعی).
"""

import asyncio
import time

import pytest
from fake_page import FakePage, find, fire
from fake_servers import FakeBotApiServer
from fakes import say, tool
from helpers import wait_until
from test_adapters_e2e import make_settings
from test_commerce_e2e import ask, force_deadline_passed, got, make_commerce_manager, start_both, use_engine

from app.core import settings as settings_module
from app.core.orders import (
    METHOD_BALE_PAY,
    METHOD_CARD_TO_CARD,
    STATUS_CONFIRMED,
    STATUS_PAID,
    OrderStore,
)
from app.core.owner_console import (
    _CODE_ALPHABET,
    LINK_CODE_TTL_SECONDS,
    OwnerConsole,
    order_alert_text,
)
from app.core.products import ProductStore
from app.core.settings import AppSettings
from app.screens import owner_settings


class Rig:
    """OwnerConsole با ذخیره‌گاه‌های واقعی و یه «deliver» ضبط‌کننده."""

    def __init__(self, tmp_path):
        self.products = ProductStore(db_path=tmp_path / "p.db")
        self.orders = OrderStore(db_path=tmp_path / "o.db", product_store=self.products)
        self.settings = AppSettings()
        self.delivered = []  # (platform, chat_id, text, log_history)
        self.deliver_ok = True
        self.saves = 0

        async def deliver(platform, chat_id, text, log_history):
            self.delivered.append((platform, chat_id, text, log_history))
            return self.deliver_ok

        def save():
            self.saves += 1
            settings_module.save_settings(self.settings)

        self.console = OwnerConsole(lambda: self.settings, self.orders, self.products, deliver, save)
        self.replies = []

    async def say(self, platform, chat_id, text):
        async def send(reply):
            self.replies.append(reply)

        return await self.console.handle(platform, chat_id, text, send)

    def run(self, platform, chat_id, text):
        self.replies.clear()
        handled = asyncio.run(self.say(platform, chat_id, text))
        return handled, (self.replies[-1] if self.replies else "")

    def link_owner(self, platform="telegram", chat_id="900"):
        code = self.console.new_link_code()
        handled, _ = self.run(platform, chat_id, f"/owner {code}")
        assert handled
        return code

    def paid_order(self, platform="telegram", chat_id="10", qty=2, stock=5, method=METHOD_CARD_TO_CARD):
        pid = self.products.add("گوشی", 1_000_000, stock)
        oid = self.orders.create(platform, chat_id, [(pid, qty)], customer_name="مریم", customer_phone="09121234567", customer_address="تهران")
        self.orders.mark_paid(oid, method, "4321")
        return pid, oid


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


# ----------------------------------------------------------------- ثبتِ مالک


def test_link_code_shape_is_unambiguous_and_unguessable(rig):
    code = rig.console.new_link_code()
    assert len(code) == 10 and set(code) <= set(_CODE_ALPHABET) and not set(code) & set("O0I1")
    assert rig.console.new_link_code() != code


def test_registration_happy_path_persists_and_is_single_use(rig):
    code = rig.console.new_link_code()
    handled, reply = rig.run("telegram", "900", f"/owner {code}")
    assert handled and "ثبت شد" in reply and "/confirm" in reply, "راهنما هم نشون داده می‌شه"
    assert rig.settings.owner_chats == {"telegram": "900"} and rig.console.is_owner("telegram", "900")
    assert settings_module.load_settings().owner_chats == {"telegram": "900"}
    # همون کد از چتِ دیگه‌ای: بی‌صدا رد می‌شه
    handled, _ = rig.run("telegram", "901", f"/owner {code}")
    assert handled is False and not rig.console.is_owner("telegram", "901")


def test_code_is_case_insensitive_and_expires(rig, monkeypatch):
    code = rig.console.new_link_code()
    assert rig.run("bale", "7", f"/owner {code.lower()}")[0] is True
    code2 = rig.console.new_link_code()
    real = time.time()
    monkeypatch.setattr(time, "time", lambda: real + LINK_CODE_TTL_SECONDS + 1)
    assert rig.run("telegram", "8", f"/owner {code2}")[0] is False and not rig.console.is_owner("telegram", "8")


def test_wrong_or_missing_code_from_a_stranger_looks_like_a_normal_message(rig):
    rig.console.new_link_code()
    for text in ("/owner WRONGWRONG", "/owner", "/owner abc", "owner ABCDEFGHJK", "/owner ABCDEFGHJK extra"):
        handled, reply = rig.run("telegram", "666", text)
        assert handled is False and reply == "", text
    assert rig.settings.owner_chats == {}


def test_a_new_code_invalidates_the_previous_one(rig):
    old = rig.console.new_link_code()
    rig.console.new_link_code()
    assert rig.run("telegram", "1", f"/owner {old}")[0] is False


def test_owner_is_per_platform(rig):
    rig.link_owner("telegram", "900")
    assert rig.console.is_owner("telegram", "900") and not rig.console.is_owner("bale", "900")
    rig.link_owner("bale", "900")
    assert rig.settings.owner_chats == {"telegram": "900", "bale": "900"}


# ----------------------------------------------------------------- فرمان‌ها


def test_strangers_cannot_run_owner_commands(rig):
    pid, oid = rig.paid_order()
    for text in (f"/confirm {oid}", f"/reject {oid}", "/orders", f"تایید {oid}", "/stock"):
        handled, _ = rig.run("telegram", "10", text)  # حتی خودِ مشتری
        assert handled is False, text
    assert rig.orders.get(oid).status == STATUS_PAID and rig.delivered == []


def test_orders_listing_and_details(rig):
    rig.link_owner()
    assert "منتظر تایید نداری" in rig.run("telegram", "900", "/orders")[1]
    pid, oid = rig.paid_order()
    handled, reply = rig.run("telegram", "900", "/orders")
    assert handled and f"#{oid}" in reply and "گوشی×2" in reply and "کارت‌به‌کارت" in reply and "/confirm" in reply
    handled, reply = rig.run("telegram", "900", f"/order {oid}")
    assert "مریم" in reply and "09121234567" in reply and "تهران" in reply and "پیگیری: 4321" in reply and "paid" in reply
    assert "پیدا نشد" in rig.run("telegram", "900", "/order 999")[1]


def test_confirm_deducts_stock_and_sends_invoice_to_the_customers_own_platform(rig):
    rig.link_owner("bale", "900")  # مالک روی بله، مشتری روی تلگرام
    pid, oid = rig.paid_order("telegram", "10", qty=2, stock=5)
    handled, reply = rig.run("bale", "900", f"/confirm {oid}")
    assert handled and "تایید شد" in reply and "فاکتور برای مشتری ارسال شد" in reply and "تهران" in reply
    assert rig.orders.get(oid).status == STATUS_CONFIRMED and rig.products.get(pid).stock_quantity == 3
    [(platform, chat, text, log_history)] = rig.delivered
    assert (platform, chat, log_history) == ("telegram", "10", True) and "سفارشتون تایید شد" in text and "گوشی" in text


def test_confirm_warns_when_customer_message_could_not_be_delivered(rig):
    rig.link_owner()
    pid, oid = rig.paid_order()
    rig.deliver_ok = False
    reply = rig.run("telegram", "900", f"/confirm {oid}")[1]
    assert "تایید شد" in reply and "پیام برای مشتری نرفت" in reply
    assert rig.orders.get(oid).status == STATUS_CONFIRMED, "ارسال ناموفق تایید رو برنمی‌گردونه"


def test_confirm_errors_are_persian_and_change_nothing(rig):
    rig.link_owner()
    assert "پیدا نشد" in rig.run("telegram", "900", "/confirm 404")[1]
    pid, oid = rig.paid_order(qty=2, stock=5)
    rig.products.adjust_stock(pid, -4)  # موجودی کم شد
    reply = rig.run("telegram", "900", f"/confirm {oid}")[1]
    assert reply.startswith("❌ تایید نشد") and rig.orders.get(oid).status == STATUS_PAID
    other = rig.products.add("هدفون", 500, 5)
    pending = rig.orders.create("telegram", "11", [(other, 1)])  # هنوز پرداخت نشده
    assert "❌ تایید نشد" in rig.run("telegram", "900", f"/confirm {pending}")[1]
    rig.products.adjust_stock(pid, 4)
    assert "تایید شد" in rig.run("telegram", "900", f"/confirm {oid}")[1]
    assert "❌ تایید نشد" in rig.run("telegram", "900", f"/confirm {oid}")[1], "دوباره تایید نمی‌شه"
    assert rig.products.get(pid).stock_quantity == 3


def test_reject_notifies_customer_with_refund_note(rig):
    rig.link_owner()
    pid, oid = rig.paid_order()
    reply = rig.run("telegram", "900", f"/reject {oid}")[1]
    assert "رد شد" in reply and "به مشتری اطلاع داده شد" in reply
    assert rig.orders.get(oid).status == "rejected" and rig.products.get(pid).stock_quantity == 5
    [(_, chat, text, _)] = rig.delivered
    assert chat == "10" and "تایید نشد" in text and "برمی‌گردونه" in text


def test_persian_aliases_and_persian_digits(rig):
    rig.link_owner()
    pid, oid = rig.paid_order()
    assert "منتظر تایید" in rig.run("telegram", "900", "سفارش‌ها")[1]
    assert "کم‌موجود" in rig.run("telegram", "900", "موجودی")[1] or "کافی" in rig.run("telegram", "900", "موجودی")[1]
    persian_id = str(oid).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
    assert "تایید شد" in rig.run("telegram", "900", f"تایید {persian_id}")[1]
    pid2, oid2 = rig.paid_order(chat_id="12")
    assert "رد شد" in rig.run("telegram", "900", f"رد #{oid2}")[1]


def test_owners_normal_messages_still_reach_the_ai(rig):
    """مالک می‌خواد ربات رو با حساب خودش تست کنه: متن‌های عادی نباید بلعیده بشن."""
    rig.link_owner()
    for text in ("سلام", "رد شدم", "سفارش دادم", "تایید می‌کنم که بخرم", "/start", "تایید abc", "confirm please", "می‌خوام 2 تا بخرم 3", "/confirm 1 2"):
        assert rig.run("telegram", "900", text)[0] is False, text


def test_command_without_a_usable_id_gets_a_usage_hint_only_when_slashed(rig):
    rig.link_owner()
    assert "شماره‌ی سفارش" in rig.run("telegram", "900", "/confirm")[1]
    assert "عدد" in rig.run("telegram", "900", "/confirm abc")[1]
    assert rig.run("telegram", "900", "تایید")[0] is False


def test_unlink_stops_commands_and_notifications(rig):
    rig.link_owner()
    handled, reply = rig.run("telegram", "900", "/unlink")
    assert handled and "قطع شد" in reply and rig.settings.owner_chats == {}
    assert rig.run("telegram", "900", "/orders")[0] is False
    assert asyncio.run(rig.console.notify("x")) is False and rig.delivered == []


def test_help_for_owner_only(rig):
    rig.link_owner()
    assert "/confirm" in rig.run("telegram", "900", "/help")[1] and "/reject" in rig.run("telegram", "900", "راهنما")[1]
    assert rig.run("telegram", "123", "/help")[0] is False


# ----------------------------------------------------------------- اعلان‌ها


def test_notify_reaches_every_owner_chat_and_survives_one_failure(rig):
    rig.link_owner("telegram", "900")
    rig.link_owner("bale", "800")
    calls = []

    async def deliver(platform, chat_id, text, log_history):
        calls.append(platform)
        if platform == "telegram":
            raise RuntimeError("down")
        return True

    rig.console._deliver = deliver  # noqa: SLF001
    assert asyncio.run(rig.console.notify("سلام")) is True and sorted(calls) == ["bale", "telegram"]


def test_notify_returns_false_when_nobody_is_linked(rig):
    assert asyncio.run(rig.console.notify("x")) is False


def test_alert_texts_for_each_situation(rig):
    pid, oid = rig.paid_order()
    order = rig.orders.get(oid)
    needs = order_alert_text(order, "needs_confirm")
    assert "منتظر تاییدته" in needs and f"/confirm {oid}" in needs and f"/reject {oid}" in needs
    assert "واریز رو توی حسابت چک کن" in needs, "کارت‌به‌کارت: مالک باید حساب رو چک کنه"
    rig.orders.confirm(oid)
    sale = order_alert_text(rig.orders.get(oid), "sale")
    assert "فروش جدید" in sale and "تهران" in sale and "09121234567" in sale and "/confirm" not in sale
    pid2 = rig.products.add("هدفون", 500, 5)
    late = rig.orders.create("telegram", "20", [(pid2, 1)])
    rig.orders.expire_stale(now=time.time() + 3600)
    rig.orders.mark_paid(late, METHOD_BALE_PAY, "r")
    assert "بعد از پایان مهلت رزرو" in order_alert_text(rig.orders.get(late), "needs_confirm")
    assert "واریز رو توی حسابت" not in order_alert_text(rig.orders.get(late), "needs_confirm")


def test_alert_order_picks_the_right_kind_by_status(rig):
    rig.link_owner()
    pid, oid = rig.paid_order()
    assert asyncio.run(rig.console.alert_order(rig.orders.get(oid))) is True
    assert "منتظر تاییدته" in rig.delivered[-1][2]
    rig.orders.confirm(oid)
    asyncio.run(rig.console.alert_order(rig.orders.get(oid)))
    assert "فروش جدید" in rig.delivered[-1][2]
    pending = rig.orders.create("telegram", "30", [(pid, 1)])
    assert asyncio.run(rig.console.alert_order(rig.orders.get(pending))) is False


# ----------------------------------------------------------------- UI


def test_owner_card_shows_status_creates_code_and_unlinks(tmp_path):
    from test_payment_settings_screen import make_store_manager

    settings = AppSettings()
    settings.business_mode = "store"
    settings.shop_mode = "shop_ai"  # جریانِ AIِ ۰.۵.۰ (آزمایشی)؛ پیش‌فرضِ ۱.۰.۰ دکمه‌ایه
    manager = make_store_manager(tmp_path, settings)
    control = owner_settings.build(FakePage(), "fa", settings, manager)
    assert "متصل نیست" in find(control, "owner_status_telegram").value
    assert find(control, "owner_unlink_telegram").visible is False

    fire(find(control, "owner_link_btn"), "on_click")
    shown = find(control, "owner_code_text")
    assert shown.visible and shown.value.startswith("/owner ") and len(shown.value.split()[1]) == 10
    code = shown.value.split()[1]

    async def link():
        async def send(_):
            pass

        return await manager.owner_console.handle("telegram", "123456", f"/owner {code}", send)

    assert asyncio.run(link()) is True
    control = owner_settings.build(FakePage(), "fa", settings, manager)  # دوباره ساخته می‌شه
    assert "متصل (•••456)" in find(control, "owner_status_telegram").value
    fire(find(control, "owner_unlink_telegram"), "on_click")
    assert settings.owner_chats == {} and "متصل نیست" in find(control, "owner_status_telegram").value


def test_owner_card_is_empty_without_a_manager():
    control = owner_settings.build(FakePage(), "fa", AppSettings(), None)
    assert find(control, "owner_link_btn") is None


# ----------------------------------------------------------------- سرتاسری


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


def test_owner_links_via_messenger_gets_alerts_and_confirms_from_chat(tmp_path, tg, bale, monkeypatch):
    settings = make_settings()
    settings.business_mode = "store"
    settings.shop_mode = "shop_ai"  # جریانِ AIِ ۰.۵.۰ (آزمایشی)؛ پیش‌فرضِ ۱.۰.۰ دکمه‌ایه
    settings.card_to_card_number = "6219-8610-1234-5678"
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    pid = products.add("گوشی", 1_000_000, 5)
    use_engine(
        monkeypatch,
        {
            "یکی می‌خوام": [
                tool("create_order", items=[{"product_id": pid, "quantity": 2}], customer_name="مریم", customer_address="تهران، ولیعصر"),
                lambda r: tool("start_payment", order_id=r[0]["order_id"], method="card_to_card"),
                say("پیام پرداخت رو ببین"),
            ],
            "واریز کردم": [tool("report_card_payment", order_id=1, reference="4321"), lambda r: say(f"ثبت شد (مالک مطلع: {r[0]['owner_alerted']})")],
            "سلام": [say("سلام! 🌹")],
        },
    )
    start_both(manager)
    try:
        # ۱) مالک با کدِ اپ خودش رو ثبت می‌کنه
        code = manager.owner_console.new_link_code()
        tg.push_message(900, f"/owner {code}")
        assert wait_until(lambda: got(tg, 900, "ثبت شد"), timeout=10)
        assert settings.owner_chats == {"telegram": "900"}
        assert not manager.store.get_messages("telegram", "900"), "گفتگوی مالک وارد تاریخچه‌ی مشتری‌ها نمی‌شه"

        # ۲) مشتری سفارش می‌ده و می‌گه واریز کرده ← مالک اعلان می‌گیره
        ask(bale, 40, "یکی می‌خوام", "پیام پرداخت رو ببین")
        ask(bale, 40, "واریز کردم", "مالک مطلع: True")
        assert wait_until(lambda: got(tg, 900, "منتظر تاییدته"), timeout=10)
        alert = [m for m in tg.sent_to(900) if "منتظر تاییدته" in m][0]
        assert "/confirm 1" in alert and "تهران، ولیعصر" in alert and "کارت‌به‌کارت" in alert and "4321" in alert

        # ۳) مالک از همون چت تایید می‌کنه ← مشتری (روی بله) تاییدیه می‌گیره
        tg.push_message(900, "/confirm 1")
        assert wait_until(lambda: got(tg, 900, "فاکتور برای مشتری ارسال شد"), timeout=10)
        assert wait_until(lambda: got(bale, 40, "سفارشتون تایید شد"), timeout=10)
        assert orders.get(1).status == STATUS_CONFIRMED and products.get(pid).stock_quantity == 3
        assert not tg.sent_to(40) and not bale.sent_to(900), "پلتفرم‌ها قاطی نمی‌شن"

        # ۴) مالک وقتی متنِ عادی می‌نویسه، مثل یه کاربر با ربات حرف می‌زنه
        ask(tg, 900, "سلام", "سلام! 🌹")
    finally:
        manager.stop(timeout=10)


def test_owner_reject_from_chat_tells_the_customer(tmp_path, tg, bale, monkeypatch):
    settings = make_settings()
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    pid = products.add("گوشی", 1_000_000, 5)
    oid = orders.create("telegram", "10", [(pid, 1)])
    orders.mark_paid(oid, METHOD_CARD_TO_CARD, "999")
    use_engine(monkeypatch, {})
    start_both(manager)
    try:
        tg.push_message(900, f"/owner {manager.owner_console.new_link_code()}")
        assert wait_until(lambda: got(tg, 900, "ثبت شد"), timeout=10)
        tg.push_message(900, "/orders")
        assert wait_until(lambda: got(tg, 900, "منتظر تایید: 1"), timeout=10)
        tg.push_message(900, f"/reject {oid}")
        assert wait_until(lambda: got(tg, 10, "تایید نشد"), timeout=10)
        assert orders.get(oid).status == "rejected" and products.get(pid).stock_quantity == 5
    finally:
        manager.stop(timeout=10)


def test_online_sale_alerts_the_owner_with_shipping_details(tmp_path, tg, bale, monkeypatch):
    settings = make_settings()
    settings.set_bale_pay_provider_token("WALLET-TEST-1111111111111111")
    settings.bale_pay_enabled = True
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    pid = products.add("هدفون", 500_000, 3)
    use_engine(
        monkeypatch,
        {"بخرم": [tool("create_order", items=[{"product_id": pid, "quantity": 1}], customer_name="رضا", customer_phone="09123334444", customer_address="شیراز"),
                  lambda r: tool("start_payment", order_id=r[0]["order_id"], method="bale_pay"), say("لینک رفت")]},
    )
    start_both(manager)
    try:
        bale.push_message(800, f"/owner {manager.owner_console.new_link_code()}")
        assert wait_until(lambda: got(bale, 800, "ثبت شد"), timeout=10)
        ask(tg, 20, "بخرم", "لینک رفت")
        bale.push_successful_payment(99, "order:1", 500_000, "charge-1")
        assert wait_until(lambda: got(bale, 800, "فروش جدید"), timeout=10)
        msg = [m for m in bale.sent_to(800) if "فروش جدید" in m][0]
        assert "شیراز" in msg and "09123334444" in msg and "رضا" in msg and "هدفون" in msg
        assert orders.get(1).status == STATUS_CONFIRMED
    finally:
        manager.stop(timeout=10)


def test_late_payment_alerts_owner_as_needs_confirm_not_sale(tmp_path, tg, bale, monkeypatch):
    settings = make_settings()
    settings.business_mode = "store"
    settings.shop_mode = "shop_ai"  # جریانِ AIِ ۰.۵.۰ (آزمایشی)؛ پیش‌فرضِ ۱.۰.۰ دکمه‌ایه
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    pid = products.add("گوشی", 1_000_000, 5)
    use_engine(
        monkeypatch,
        {"بخرم": [tool("create_order", items=[{"product_id": pid, "quantity": 1}]), say("ثبت شد")]},
    )
    start_both(manager)
    try:
        tg.push_message(900, f"/owner {manager.owner_console.new_link_code()}")
        assert wait_until(lambda: got(tg, 900, "ثبت شد"), timeout=10)
        ask(bale, 40, "بخرم", "ثبت شد")
        force_deadline_passed(orders, 1)
        assert wait_until(lambda: orders.get(1).status == "expired", timeout=10)
        bale.push_pre_checkout_query("late", 40, "order:1", 1_000_000)  # فاکتور بله بعد از انقضا
        assert wait_until(lambda: bale.pre_checkout_answers and bale.pre_checkout_answers[-1]["ok"] is False, timeout=10)
        # پرداختِ دیررس از درگاه (مثلاً زرین‌پال) بعد از انقضا
        order = manager._payments.finalize_online_payment(1, METHOD_BALE_PAY, "late-ref")  # noqa: SLF001
        assert order.status == STATUS_PAID and order.paid_late, "پرداختِ دیررس خودکار تایید نمی‌شه"
        asyncio.run_coroutine_threadsafe(manager._notify_payment_confirmed(order), manager._loop).result(10)  # noqa: SLF001
        assert wait_until(lambda: got(tg, 900, "منتظر تاییدته"), timeout=10)
        alert = [m for m in tg.sent_to(900) if "منتظر تاییدته" in m][0]
        assert "بعد از پایان مهلت رزرو" in alert and "/confirm 1" in alert
        assert not got(tg, 900, "فروش جدید"), "پرداخت دیررس «فروش» نیست؛ تصمیم با مالکه"
        assert wait_until(lambda: got(bale, 40, "بعد از پایان مهلتِ رزرو رسید"), timeout=10), "مشتری هم می‌فهمه"
    finally:
        manager.stop(timeout=10)


def test_escalation_tool_alerts_owner_once_and_is_honest_when_nobody_is_linked(tmp_path, tg, bale, monkeypatch):
    from app.core.store_agent import StoreToolbox

    StoreToolbox._escalations.clear()
    settings = make_settings()
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    products.add("گوشی", 1_000_000, 5)
    use_engine(
        monkeypatch,
        {
            "مشکل دارم": [tool("escalate_to_owner", reason="کالا خراب رسید"), lambda r: say(f"delivered={r[0]['delivered']}")],
            "باز هم مشکل": [tool("escalate_to_owner", reason="باز هم"), lambda r: say(f"دوباره delivered={r[0]['delivered']}")],
        },
    )
    start_both(manager)
    try:
        ask(tg, 20, "مشکل دارم", "delivered=False")  # هنوز مالکی وصل نیست؛ AI نباید دروغ بگه
        StoreToolbox._escalations.clear()
        bale.push_message(800, f"/owner {manager.owner_console.new_link_code()}")
        assert wait_until(lambda: got(bale, 800, "ثبت شد"), timeout=10)
        ask(tg, 20, "مشکل دارم", "delivered=True")
        assert wait_until(lambda: got(bale, 800, "نیاز به پیگیری"), timeout=10)
        alert = [m for m in bale.sent_to(800) if "نیاز به پیگیری" in m][0]
        assert "کالا خراب رسید" in alert and "telegram" in alert
        ask(tg, 20, "باز هم مشکل", "دوباره delivered=False")  # ضدِ اسپم: ۱۰ دقیقه‌ای
    finally:
        manager.stop(timeout=10)
