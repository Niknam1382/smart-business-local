"""R1/R2/R5 — فروشگاهِ دکمه‌ای سرتاسری روی تلگرام: aiogram/BotManagerِ واقعی روی سرورِ جعلیِ Bot API.

بله دیگر پیام‌رسانِ گفتگو نیست، پس این فایل فقط یک پلتفرم دارد؛ مسیرِ پرداختِ بله‌پی برای
مشتریِ تلگرامی در test_commerce_e2e.py و test_bale_pay.py تست می‌شود.

ابزارِ مشترکِ این فایل (``shop``، ``send``، ``tap``، ``status``) توسط تست‌های سرتاسریِ دیگر
(test_usage_limits، test_privacy، test_handoff، test_delivery، test_abuse_suite) import می‌شود.
"""

import pytest
from fake_servers import FakeBotApiServer
from fakes import ScriptedToolEngine, say, tool
from helpers import wait_until
from shop_buttons import send, tap  # noqa: F401 — بازم نشرِ helper برای بقیه‌ی فایل‌ها
from test_adapters_e2e import make_settings
from test_commerce_e2e import FAST, got, make_commerce_manager, start_connected, status, use_engine  # noqa: F401

from app.core.orders import STATUS_CONFIRMED, STATUS_PAID, STATUS_PENDING_PAYMENT

MENU_LABELS = ["🛍 محصولات", "🧺 سبد خرید", "📦 سفارش‌های من", "🙋 ارتباط با پشتیبانی"]


@pytest.fixture
def tg():
    srv = FakeBotApiServer(username="tg_shop_bot").start()
    yield srv
    srv.stop()


def shop(tmp_path, tg, monkeypatch, **settings_kw):
    """مدیرِ فروشگاه + موتورِ scripted؛ ``business_mode`` را می‌شود با kwargs عوض کرد (مشاوره‌ای)."""
    settings = make_settings()
    settings.card_to_card_number = "6219-8610-1234-5678"
    settings.card_to_card_holder_name = "فروشگاه نمونه"
    for k, v in settings_kw.items():
        setattr(settings, k, v)
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg)
    engine = ScriptedToolEngine({}, default=say("جواب AI"))
    monkeypatch.setattr("app.core.ai_engine.build_engine_from_settings", lambda s: engine)
    return manager, products, orders, settings, engine


def run_purchase(server, orders, products, pid, chat):
    """از /start تا «پرداخت کردم» و تأییدِ مالک: خریدِ کاملِ دکمه‌ای."""
    send(server, chat, "/start", "فروشگاه")
    menu = server.last_message(chat)["reply_markup"]["keyboard"]
    assert [b["text"] for row in menu for b in row] == MENU_LABELS, "دقیقاً همان چهار دکمه‌ای که مالک خواسته"
    send(server, chat, "🛍 محصولات", "محصولات")
    assert f"c:p:{pid}:-:1" in server.callback_datas(chat)
    tap(server, chat, f"c:p:{pid}:-:1", message_id=server.last_message(chat)["message_id"])
    assert wait_until(lambda: server.edits and "هدفون" in server.edits[-1]["text"])  # ویرایش، نه پیامِ جدید
    tap(server, chat, f"c:a:{pid}:2:-:1")
    assert wait_until(lambda: server.markup_edits)  # فقط کیبورد ویرایش شد
    send(server, chat, "✅ نهایی کردن سفارش", "نام")
    send(server, chat, "مریم احمدی", "موبایل")
    send(server, chat, "۰۹۱۲۱۲۳۴۵۶۷", "آدرس")
    send(server, chat, "شیراز، خیابان زند، پلاک ۵", "کدپستی")
    tap(server, chat, "c:ck:s")  # رد کردنِ کدپستی
    assert wait_until(lambda: "توضیحات" in server.last_message(chat)["text"] or any("توضیحات" in e["text"] for e in server.edits))
    tap(server, chat, "c:ck:s")  # رد کردنِ توضیحات ← خلاصه
    assert wait_until(lambda: "c:ck:ok" in server.callback_datas(chat))
    tap(server, chat, "c:ck:ok")
    tap(server, chat, "c:pm:card_to_card")
    assert wait_until(lambda: any("6219-8610-1234-5678" in m for m in server.sent_to(chat)))
    oid = [o for o in orders.list() if o.chat_id == str(chat)][0].id
    assert orders.get(oid).status == STATUS_PENDING_PAYMENT and orders.get(oid).customer_phone == "09121234567"
    tap(server, chat, f"c:paid:{oid}")
    assert wait_until(lambda: orders.get(oid).status == STATUS_PAID, timeout=20)
    orders.confirm(oid)
    assert orders.get(oid).status == STATUS_CONFIRMED and products.get(pid).stock_quantity == 3
    return oid


def test_telegram_full_button_purchase(tmp_path, tg, monkeypatch):
    manager, products, orders, settings, _ = shop(tmp_path, tg, monkeypatch)
    pid = products.add("هدفون", 1_000_000, 5)
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        run_purchase(tg, orders, products, pid, 10)
    finally:
        manager.stop()


def test_cart_button_shows_a_live_counter(tmp_path, tg, monkeypatch):
    """«🧺 سبد خرید (n)» — شمارنده‌ی تعدادِ قلم‌ها روی کیبوردِ پایدار."""
    manager, products, orders, settings, _ = shop(tmp_path, tg, monkeypatch)
    pid = products.add("هدفون", 1_000_000, 5)
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        send(tg, 10, "/start", "فروشگاه")
        labels = [b["text"] for row in tg.last_message(10)["reply_markup"]["keyboard"] for b in row]
        assert "🧺 سبد خرید" in labels, "سبدِ خالی شمارنده ندارد"
        tap(tg, 10, f"c:p:{pid}:-:1", message_id=tg.last_message(10)["message_id"])
        tap(tg, 10, f"c:a:{pid}:2:-:1")
        # کیبوردِ پایدار قابل‌ویرایش نیست ⇒ منوی تازه می‌گیریم و شمارنده را در همان می‌خوانیم
        tap(tg, 10, "c:m")
        assert wait_until(lambda: "🧺 سبد خرید (2)" in _menu_labels(tg, 10), timeout=20)
    finally:
        manager.stop()


def _menu_labels(server, chat) -> list:
    markup = server.last_message(chat).get("reply_markup") or {}
    return [b["text"] for row in markup.get("keyboard", []) for b in row]


def test_photo_product_card_and_back_navigation_falls_back_to_delete_and_send(tmp_path, tg, monkeypatch):
    manager, products, orders, settings, _ = shop(tmp_path, tg, monkeypatch)
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    pid = products.add("دوربین", 5000, 2, photo_path=str(photo))
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        send(tg, 10, "🛍 محصولات", "محصولات")
        tap(tg, 10, f"c:p:{pid}:-:1", message_id=tg.last_message(10)["message_id"])
        assert wait_until(lambda: any(m["kind"] == "sendPhoto" and "دوربین" in m["text"] for m in tg.sent))
        tg.edit_mode = "no_text"  # تلگرام ویرایشِ متنِ پیامِ عکس‌دار را رد می‌کند
        before = len(tg.sent)
        tap(tg, 10, "c:l:-:1", message_id=tg.last_message(10)["message_id"])
        assert wait_until(lambda: tg.deleted and len(tg.sent) > before)  # پیامِ عکس‌دار حذف + لیستِ تازه
    finally:
        manager.stop()


def test_stale_and_garbage_callbacks_get_a_friendly_answer(tmp_path, tg, monkeypatch):
    manager, products, orders, settings, _ = shop(tmp_path, tg, monkeypatch)
    products.add("کالا", 1000, 1)
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        for data in ("c:zzz", "garbage", "c:p:999:-:1"):
            tap(tg, 10, data)
        assert any(a.get("text") for a in tg.callback_answers), "هر کلیکِ بی‌ربط یک پاسخِ دوستانه دارد"
    finally:
        manager.stop()


def test_consultant_mode_never_sends_a_keyboard(tmp_path, tg, monkeypatch):
    """حالتِ مشاوره‌ای: هیچ دکمه‌ای، هیچ سبدی. «محصولات» مثلِ پیامِ آزاد به AI می‌رود."""
    manager, products, orders, settings, _ = shop(tmp_path, tg, monkeypatch, business_mode="consultant")
    products.add("کالا", 1000, 1)
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        send(tg, 10, "/start", "پاسخ: /start")
        send(tg, 10, "🛍 محصولات", "پاسخ: 🛍 محصولات")
        assert all(m.get("reply_markup") is None for m in tg.sent), "در حالتِ مشاوره هیچ reply_markup نباید برود"
        tap_before = len(tg.callback_answers)
        tg.push_callback_query(10, "c:l:-:1")
        assert wait_until(lambda: len(tg.callback_answers) > tap_before)  # کلیکِ قدیمی بی‌اثر ولی spinner قطع می‌شه
    finally:
        manager.stop()


def test_mode_switch_needs_no_restart(tmp_path, tg, monkeypatch):
    """مشاور ← فروشگاه فقط با تنظیمات؛ رباتِ همانِ در حال اجرا کیبورد می‌فرستد."""
    manager, products, orders, settings, _ = shop(tmp_path, tg, monkeypatch, business_mode="consultant")
    products.add("کالا", 1000, 1)
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        send(tg, 10, "سلام", "پاسخ: سلام")
        assert all(m.get("reply_markup") is None for m in tg.sent)
        settings.business_mode = "store"
        send(tg, 10, "🛍 محصولات", "محصولات", since=len(tg.sent_to(10)))
        assert wait_until(lambda: any(m.get("reply_markup") for m in tg.sent), timeout=20)
    finally:
        manager.stop()


def test_free_text_goes_to_ai_and_suggest_products_renders_details_only_cards(tmp_path, tg, monkeypatch):
    manager, products, orders, settings, _ = shop(tmp_path, tg, monkeypatch)
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
        assert wait_until(lambda: any("هدفون" in m["text"] and m.get("reply_markup") for m in tg.sent), timeout=20)
        card = [m for m in tg.sent if "هدفون" in m["text"] and m.get("reply_markup")][0]
        datas = [b["callback_data"] for row in card["reply_markup"]["inline_keyboard"] for b in row if b.get("callback_data")]
        assert f"c:p:{pid}:-:1" in datas, "فقط «جزئیات»"
        assert not [d for d in datas if d.startswith("c:a:")], "کارتِ پیشنهادیِ AI هیچ دکمه‌ی افزودن/کم‌کردنِ سبد ندارد"
        assert engine.calls[0]["tools"] == ["suggest_products"]
        assert f"شناسه={pid}" in engine.calls[0]["system_prompt"], "کاتالوگ در حالت فروشگاه تزریق می‌شه"
        assert manager._pipeline._shop_flow.carts.quantity("telegram", "10", pid) == 0  # noqa: SLF001 — AI سبد را دست نزد
        tap(tg, 10, f"c:p:{pid}:-:1", message_id=card["message_id"])
        tap(tg, 10, f"c:a:{pid}:1:-:1")  # افزودن فقط با دکمه‌ی خودِ مشتری
        assert wait_until(lambda: manager._pipeline._shop_flow.carts.quantity("telegram", "10", pid) == 1, timeout=20)  # noqa: SLF001
    finally:
        manager.stop()


def test_call_button_sends_number_and_contact_card_even_if_platform_rejects_tel_url(tmp_path, tg, monkeypatch):
    tg.reject_tel_buttons = True
    manager, products, orders, settings, _ = shop(
        tmp_path, tg, monkeypatch,
        custom_buttons=[
            {"id": "call", "label": "تماس", "emoji": "📞", "action": "phone", "config": {"phone": "02112345678"}, "platforms": ["telegram"]},
            {"id": "insta", "label": "اینستاگرام", "action": "url", "config": {"url": "https://instagram.com/shop"}},
        ],
    )
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        send(tg, 10, "🙋 ارتباط با پشتیبانی", "راهنما و سؤالات متداول")  # دکمه‌های سفارشی پشتِ «پشتیبانی»اند
        send(tg, 10, "📞 تماس", "02112345678")
        assert wait_until(lambda: any(m["kind"] == "sendContact" for m in tg.sent))
        send(tg, 10, "اینستاگرام", "اینستاگرام")
        assert ("اینستاگرام", "https://instagram.com/shop") in tg.buttons_to(10)
        tg.reject_markup = True  # اگر پلتفرم دکمه را رد کرد، لینک داخلِ متن می‌ماند
        send(tg, 10, "اینستاگرام", "https://instagram.com/shop", since=len(tg.sent_to(10)) - 1)
    finally:
        manager.stop()


def test_menu_moves_guide_and_faq_behind_the_support_button(tmp_path, tg, monkeypatch):
    """راهنما و سؤالات متداول از منوی اصلی برداشته شده‌اند: منو دقیقاً چهار دکمه است و
    FAQ/راهنما/دکمه‌های سفارشی از «ارتباط با پشتیبانی» باز می‌شوند."""
    manager, products, orders, settings, _ = shop(
        tmp_path, tg, monkeypatch,
        faq_items=[{"q": "ارسال چند روزه؟", "a": "دو روز کاری."}],
    )
    products.add("کالا", 1000, 1)
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        send(tg, 10, "/start", "فروشگاه")
        labels = [b["text"] for row in tg.last_message(10)["reply_markup"]["keyboard"] for b in row]
        assert labels == MENU_LABELS
        assert "ℹ️ راهنما" not in labels and "❓ سؤالات متداول" not in labels
        send(tg, 10, "🙋 ارتباط با پشتیبانی", "راهنما و سؤالات متداول")
        support = [b.get("callback_data") for row in tg.last_message(10)["reply_markup"]["inline_keyboard"] for b in row]
        assert "c:f:1" in support and "c:g:1" in support, "FAQ و راهنما زیرِ دکمه‌ی پشتیبانی"
        assert "c:m" in support, "از پشتیبانی بازگشت به منو"
        tap(tg, 10, "c:f:1")
        assert wait_until(lambda: "c:fa:0" in tg.callback_datas(10), timeout=20), "لیستِ سؤالات متداول"
        tap(tg, 10, "c:fa:0")
        # پاسخِ FAQ روی همان پیام ویرایش می‌شود (editMessageText)، پس در edits دیده می‌شود نه sent
        assert wait_until(lambda: any("دو روز کاری" in (e["text"] or "") for e in tg.edits), timeout=20)
    finally:
        manager.stop()
