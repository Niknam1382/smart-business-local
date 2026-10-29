"""
تایید سفارش توسط صاحب فروشگاه (دکمه‌ی صفحه‌ی «سفارش‌ها») باید خودکار یه پیام
«تایید + فاکتور» برای مشتری بفرسته — روی پلتفرمِ *واقعیِ* سفارش، از طریق
BotManager واقعی و سرور جعلی Bot API.
"""

import pytest
from fake_page import FakePage, collect_text, find, fire
from fake_servers import FakeBotApiServer
from fakes import FakeEngine
from helpers import wait_until
from test_adapters_e2e import make_settings
from test_commerce_e2e import make_commerce_manager, status

from app.core import ai_engine
from app.core.bot_manager import BotManagerError
from app.core.orders import METHOD_BALE_PAY, METHOD_CARD_TO_CARD
from app.screens import orders as orders_screen


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


@pytest.fixture(autouse=True)
def engine(monkeypatch):
    eng = FakeEngine(reply=lambda text: f"پاسخ: {text}")
    monkeypatch.setattr(ai_engine, "build_engine_from_settings", lambda s: eng)
    return eng


def _paid_order(orders, products, platform, chat_id, qty=2, method=METHOD_CARD_TO_CARD):
    pid = products.add("گوشی", 1_000_000, 5)
    oid = orders.create(platform, chat_id, [(pid, qty)])
    orders.mark_paid(oid, method)
    return pid, oid


def test_confirm_sends_confirmation_to_telegram_customer(tmp_path, tg, bale):
    settings = make_settings()
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    pid, oid = _paid_order(orders, products, "telegram", "10")

    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        page = FakePage()
        control = orders_screen.build(page, "fa", orders, manager)
        fire(find(control, f"confirm_{oid}"), "on_click")

        assert orders.get(oid).status == "confirmed"
        assert products.get(pid).stock_quantity == 3
        assert wait_until(lambda: any("سفارشتون تایید شد" in m for m in tg.sent_to(10)))
        text = [m for m in tg.sent_to(10) if "سفارشتون تایید شد" in m][-1]
        assert "گوشی" in text, "فاکتور باید اقلام رو داشته باشه"
        assert not bale.sent, "به ربات بله نباید چیزی بره"
        # توی تاریخچه هم ثبت شده تا صاحب فروشگاه توی تب «گفتگوها» ببینه
        history = manager.store.get_messages("telegram", "10")
        assert any(m.role == "assistant" and "سفارشتون تایید شد" in m.content for m in history)
        assert "تاییدیه + فاکتور برای مشتری فرستاده شد" in collect_text(control)
    finally:
        manager.stop(timeout=10)


def test_confirm_sends_to_bale_customer_on_bale(tmp_path, tg, bale):
    settings = make_settings()
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    _, oid = _paid_order(orders, products, "bale", "40", qty=1)

    manager.start()
    try:
        assert wait_until(lambda: status(manager, "bale").connected)
        control = orders_screen.build(FakePage(), "fa", orders, manager)
        fire(find(control, f"confirm_{oid}"), "on_click")
        assert wait_until(lambda: any("سفارشتون تایید شد" in m for m in bale.sent_to(40)))
        assert not tg.sent
    finally:
        manager.stop(timeout=10)


def test_bale_pay_order_of_telegram_customer_confirmation_goes_to_telegram(tmp_path, tg, bale):
    """همون الگوی باگِ مسیریابیِ فاز ۴: سفارشِ بله‌پیِ مشتریِ تلگرامی — تاییدیه‌ی
    دستی هم باید به تلگرام و chat_id خودِ مشتری بره، نه بله."""
    settings = make_settings()
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    _, oid = _paid_order(orders, products, "telegram", "20", qty=1, method=METHOD_BALE_PAY)

    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected and status(manager, "bale").connected)
        control = orders_screen.build(FakePage(), "fa", orders, manager)
        fire(find(control, f"confirm_{oid}"), "on_click")
        assert wait_until(lambda: any("سفارشتون تایید شد" in m for m in tg.sent_to(20)))
        assert not bale.sent_to(20), "chat_id تلگرامی نباید به بله بره"
    finally:
        manager.stop(timeout=10)


def test_confirm_when_bots_off_still_confirms_but_warns_owner(tmp_path, tg, bale):
    settings = make_settings()
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)  # هیچ‌وقت start نمی‌شه
    pid, oid = _paid_order(orders, products, "telegram", "10")

    control = orders_screen.build(FakePage(), "fa", orders, manager)
    fire(find(control, f"confirm_{oid}"), "on_click")

    assert orders.get(oid).status == "confirmed", "شکستِ ارسال نباید تایید رو برگردونه"
    assert products.get(pid).stock_quantity == 3
    shown = collect_text(control)
    assert "پیام برای مشتری نرفت" in shown and "خودت بهش خبر بده" in shown
    assert "Traceback" not in shown


def test_confirm_when_only_other_platform_connected_warns_owner(tmp_path, tg, bale):
    settings = make_settings(bale_token="")  # فقط تلگرام وصل
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale, telegram_only=True)
    _, oid = _paid_order(orders, products, "bale", "40", qty=1)

    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        control = orders_screen.build(FakePage(), "fa", orders, manager)
        fire(find(control, f"confirm_{oid}"), "on_click")
        assert orders.get(oid).status == "confirmed"
        assert "پیام برای مشتری نرفت" in collect_text(control)
        assert not tg.sent
    finally:
        manager.stop(timeout=10)


def test_insufficient_stock_sends_nothing(tmp_path, tg, bale):
    settings = make_settings()
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    pid = products.add("گوشی", 1_000_000, 1)
    oid = orders.create("telegram", "10", [(pid, 1)])
    orders.mark_paid(oid, METHOD_CARD_TO_CARD)
    products.adjust_stock(pid, -1)  # موجودی بعد از ثبت سفارش تموم شده

    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        control = orders_screen.build(FakePage(), "fa", orders, manager)
        fire(find(control, f"confirm_{oid}"), "on_click")
        assert orders.get(oid).status == "paid"
        assert not tg.sent_to(10), "تایید ناموفق = هیچ پیامی برای مشتری"
        assert "تایید نشد" in collect_text(control)
    finally:
        manager.stop(timeout=10)


def test_reject_tells_the_customer_what_happened_and_about_the_money(tmp_path, tg, bale):
    """ردِ سفارشِ *پرداخت‌شده*: مشتری پول داده؛ بی‌خبر گذاشتنش بدترین حالته."""
    settings = make_settings()
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    pid, oid = _paid_order(orders, products, "telegram", "10")
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        control = orders_screen.build(FakePage(), "fa", orders, manager)
        fire(find(control, f"reject_{oid}"), "on_click")
        assert orders.get(oid).status == "rejected"
        assert products.get(pid).stock_quantity == 5, "ردِ سفارش موجودی رو دست نمی‌زنه"
        assert wait_until(lambda: any("تایید نشد" in m for m in tg.sent_to(10)))
        text = [m for m in tg.sent_to(10) if "تایید نشد" in m][-1]
        assert f"#{oid}" in text and "برمی‌گردونه" in text and "گوشی" in text
        assert "مشتری اطلاع داده شد" in collect_text(control)
    finally:
        manager.stop(timeout=10)


def test_reject_with_bots_off_still_rejects_but_warns_owner_to_contact_customer(tmp_path, tg, bale):
    settings = make_settings()
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)  # هیچ‌وقت start نمی‌شه
    _, oid = _paid_order(orders, products, "telegram", "10")
    control = orders_screen.build(FakePage(), "fa", orders, manager)
    fire(find(control, f"reject_{oid}"), "on_click")
    assert orders.get(oid).status == "rejected"
    assert "پیام برای مشتری نرفت" in collect_text(control) and "مبلغ رو برگردون" in collect_text(control)


def test_send_message_sync_raises_persian_error_when_not_running(tmp_path, tg, bale):
    manager, *_ = make_commerce_manager(tmp_path, make_settings(), tg, bale)
    with pytest.raises(BotManagerError) as exc:
        manager.send_message_sync("telegram", "1", "سلام")
    assert "خاموش" in str(exc.value)
