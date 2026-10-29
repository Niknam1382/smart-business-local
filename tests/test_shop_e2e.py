"""R1/R2/R5 — فروشگاهِ دکمه‌ای سرتاسری روی *هر دو* پلتفرم: aiogram/BaleClient/BotManager واقعی روی سرورِ جعلیِ Bot API."""

import pytest
from fake_servers import FakeBotApiServer
from fakes import ScriptedToolEngine, say, tool
from helpers import wait_until
from test_adapters_e2e import make_settings
from test_commerce_e2e import FAST, got, make_commerce_manager, start_both, status, use_engine  # noqa: F401

from app.core.orders import STATUS_CONFIRMED, STATUS_PAID, STATUS_PENDING_PAYMENT


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


def shop(tmp_path, tg, bale, monkeypatch, mode="shop_buttons", **settings_kw):
    settings = make_settings()
    settings.card_to_card_number = "6219-8610-1234-5678"
    settings.card_to_card_holder_name = "فروشگاه نمونه"
    for k, v in settings_kw.items():
        setattr(settings, k, v)
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    settings.shop_mode = mode  # make_commerce_manager برای تست‌های قدیمی shop_ai می‌ذاره
    engine = ScriptedToolEngine({}, default=say("جواب AI"))
    monkeypatch.setattr("app.core.ai_engine.build_engine_from_settings", lambda s: engine)
    return manager, products, orders, settings, engine


def send(server, chat, text, needle, since=0):
    server.push_message(chat, text)
    assert wait_until(lambda: any(needle in m for m in server.sent_to(chat)[since:]), timeout=10), (needle, server.sent_to(chat))


def tap(server, chat, data, message_id=None):
    """کلیک روی دکمه (پیش‌فرض: روی آخرین پیامِ ربات)؛ منتظرِ answerCallbackQuery می‌مونه و شناسه‌ش رو برمی‌گردونه."""
    if message_id is None:
        message_id = (server.last_message(chat) or {}).get("message_id", 1)
    before = len(server.callback_answers)
    cb = server.push_callback_query(chat, data, message_id=message_id)
    assert wait_until(lambda: len(server.callback_answers) > before, timeout=10), (data, server.calls[-6:])
    assert server.callback_answers[-1]["callback_query_id"] == cb
    return cb


def run_purchase(server, orders, products, pid, chat):
    """از /start تا «پرداخت کردم»: خریدِ کاملِ دکمه‌ای روی یه پلتفرم."""
    send(server, chat, "/start", "خوش اومدی")
    menu = server.last_message(chat)["reply_markup"]["keyboard"]
    assert [b["text"] for b in menu[0]] == ["🛍 محصولات", "🧺 سبد خرید"]
    send(server, chat, "🛍 محصولات", "محصولات")
    assert f"c:p:{pid}:-:1" in server.callback_datas(chat)
    tap(server, chat, f"c:p:{pid}:-:1", message_id=server.last_message(chat)["message_id"])
    assert wait_until(lambda: server.edits and "هدفون" in server.edits[-1]["text"])  # پیامِ کاتالوگ ویرایش شد، نه پیامِ جدید
    tap(server, chat, f"c:a:{pid}:2:-:1")
    assert wait_until(lambda: server.markup_edits)  # فقط کیبورد ویرایش شد
    send(server, chat, "✅ نهایی کردن سفارش", "نام")
    send(server, chat, "مریم احمدی", "موبایل")
    send(server, chat, "۰۹۱۲۱۲۳۴۵۶۷", "آدرس")
    send(server, chat, "شیراز، خیابان زند، پلاک ۵", "کدپستی")
    tap(server, chat, "c:ck:s")  # رد کردنِ کدپستی
    assert wait_until(lambda: "توضیحات" in server.last_message(chat)["text"] or any("توضیحات" in e["text"] for e in server.edits))
    tap(server, chat, "c:ck:s")  # رد کردنِ توضیحات → خلاصه
    assert wait_until(lambda: "c:ck:ok" in server.callback_datas(chat))
    tap(server, chat, "c:ck:ok")
    tap(server, chat, "c:pm:card_to_card")
    assert wait_until(lambda: any("6219-8610-1234-5678" in m for m in server.sent_to(chat)))
    oid = [o for o in orders.list() if o.chat_id == str(chat)][0].id
    assert orders.get(oid).status == STATUS_PENDING_PAYMENT and orders.get(oid).customer_phone == "09121234567"
    tap(server, chat, f"c:paid:{oid}")
    assert wait_until(lambda: orders.get(oid).status == STATUS_PAID)
    orders.confirm(oid)
    assert orders.get(oid).status == STATUS_CONFIRMED and products.get(pid).stock_quantity == 3
    return oid


def test_telegram_full_button_purchase(tmp_path, tg, bale, monkeypatch):
    manager, products, orders, settings, _ = shop(tmp_path, tg, bale, monkeypatch)
    pid = products.add("هدفون", 1_000_000, 5)
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        run_purchase(tg, orders, products, pid, 10)
    finally:
        manager.stop()


def test_bale_full_button_purchase(tmp_path, tg, bale, monkeypatch):
    manager, products, orders, settings, _ = shop(tmp_path, tg, bale, monkeypatch)
    pid = products.add("هدفون", 1_000_000, 5)
    manager.start()
    try:
        start_both(manager)
        run_purchase(bale, orders, products, pid, 20)
    finally:
        manager.stop()


def test_photo_product_card_and_back_navigation_falls_back_to_delete_and_send(tmp_path, tg, bale, monkeypatch):
    manager, products, orders, settings, _ = shop(tmp_path, tg, bale, monkeypatch)
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    pid = products.add("دوربین", 5000, 2, photo_path=str(photo))
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        send(tg, 10, "🛍 محصولات", "محصولات")
        tap(tg, 10, f"c:p:{pid}:-:1", message_id=tg.last_message(10)["message_id"])
        assert wait_until(lambda: any(m["kind"] == "sendPhoto" and "دوربین" in m["text"] for m in tg.sent))
        tg.edit_mode = "no_text"  # تلگرام ویرایشِ متنِ پیامِ عکس‌دار رو رد می‌کنه
        before = len(tg.sent)
        tap(tg, 10, "c:l:-:1", message_id=tg.last_message(10)["message_id"])
        assert wait_until(lambda: tg.deleted and len(tg.sent) > before)  # پیامِ عکس‌دار حذف + لیست تازه فرستاده شد
    finally:
        manager.stop()


def test_stale_and_garbage_callbacks_get_friendly_answer_on_both_platforms(tmp_path, tg, bale, monkeypatch):
    manager, products, orders, settings, _ = shop(tmp_path, tg, bale, monkeypatch)
    products.add("کالا", 1000, 1)
    manager.start()
    try:
        start_both(manager)
        for server, chat in ((tg, 10), (bale, 20)):
            for data in ("c:zzz", "garbage", "c:p:999:-:1"):
                tap(server, chat, data)
            assert any(a.get("text") for a in server.callback_answers)
        assert status(manager, "telegram").connected and status(manager, "bale").connected
    finally:
        manager.stop()


def test_advisor_mode_never_sends_a_keyboard_and_mode_switch_needs_no_restart(tmp_path, tg, bale, monkeypatch):
    manager, products, orders, settings, engine = shop(tmp_path, tg, bale, monkeypatch, mode="advisor")
    products.add("کالا", 1000, 1)
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        send(tg, 10, "/start", "پاسخ: /start")  # (خطِ شفافیتِ AI هم «پاسخ» داره؛ منتظرِ خودِ جوابِ AI می‌مونیم تا دو پیام ادغام نشن)
        send(tg, 10, "🛍 محصولات", "پاسخ: 🛍 محصولات")
        assert all(m.get("reply_markup") is None for m in tg.sent), "در حالتِ مشاوره هیچ reply_markup نباید برود"
        tap_before = len(tg.callback_answers)
        tg.push_callback_query(10, "c:l:-:1")
        assert wait_until(lambda: len(tg.callback_answers) > tap_before)  # کلیکِ قدیمی بی‌اثر ولی spinner قطع می‌شه
        settings.shop_mode = "shop_buttons"  # تغییرِ حالت بدونِ ری‌استارت
        send(tg, 10, "🛍 محصولات", "🛍 محصولات", since=len(tg.sent_to(10)))
        assert wait_until(lambda: any(m.get("reply_markup") for m in tg.sent))
    finally:
        manager.stop()


def test_free_text_goes_to_ai_and_suggest_products_renders_add_to_cart_card(tmp_path, tg, bale, monkeypatch):
    manager, products, orders, settings, _ = shop(tmp_path, tg, bale, monkeypatch)
    pid = products.add("هدفون", 1_000_000, 5, description="بی‌سیم")
    engine = ScriptedToolEngine(
        {"هدفون خوب چی دارید؟": [tool("suggest_products", product_ids=[pid, 999]), lambda r: say("این رو پیشنهاد می‌کنم 👆")]},
        default=say("جواب AI"),
    )
    monkeypatch.setattr("app.core.ai_engine.build_engine_from_settings", lambda s: engine)
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        send(tg, 10, "هدفون خوب چی دارید؟", "این رو پیشنهاد می‌کنم")
        # متنِ AI اول می‌ره و کارت‌ها بلافاصله بعدش؛ منتظرِ خودِ کارت می‌مونیم (نه فقط متن)
        assert wait_until(lambda: any("هدفون" in m["text"] and m.get("reply_markup") for m in tg.sent), timeout=10)
        card = [m for m in tg.sent if "هدفون" in m["text"] and m.get("reply_markup")][0]
        datas = [b["callback_data"] for row in card["reply_markup"]["inline_keyboard"] for b in row if b.get("callback_data")]
        assert f"c:a:{pid}:1:-:1" in datas
        assert engine.calls[0]["tools"] == ["suggest_products"]
        assert "id=%d" % pid in engine.calls[0]["system_prompt"] and "cannot" in engine.calls[0]["system_prompt"].lower() or "can NOT" in engine.calls[0]["system_prompt"]
        tap(tg, 10, f"c:a:{pid}:1:-:1")
        assert wait_until(lambda: manager._pipeline._shop_flow.carts.quantity("telegram", "10", pid) == 1, timeout=10)  # noqa: SLF001
    finally:
        manager.stop()


def test_call_button_sends_number_and_contact_card_even_if_platform_rejects_tel_url(tmp_path, tg, bale, monkeypatch):
    tg.reject_tel_buttons = True
    manager, products, orders, settings, _ = shop(
        tmp_path, tg, bale, monkeypatch,
        custom_buttons=[
            {"id": "call", "label": "تماس", "emoji": "📞", "action": "phone", "config": {"phone": "02112345678"}, "platforms": ["telegram", "bale"]},
            {"id": "insta", "label": "اینستاگرام", "action": "url", "config": {"url": "https://instagram.com/shop"}},
        ],
    )
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        send(tg, 10, "📞 تماس", "02112345678")
        assert wait_until(lambda: any(m["kind"] == "sendContact" for m in tg.sent))
        send(tg, 10, "اینستاگرام", "اینستاگرام")
        assert ("اینستاگرام", "https://instagram.com/shop") in tg.buttons_to(10)
        tg.reject_markup = True  # اگه پلتفرم دکمه رو رد کرد، لینک داخلِ متن می‌مونه
        send(tg, 10, "اینستاگرام", "https://instagram.com/shop", since=len(tg.sent_to(10)) - 1)
    finally:
        manager.stop()
