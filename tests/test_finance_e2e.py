"""N19 سرتاسری: تاییدِ سفارش ⇒ دفترِ مالی + PDFِ فاکتور واقعاً از آداپتورِ تلگرام/بله (آپلودِ multipart) به مشتری می‌رسه."""

import pytest
from fake_servers import FakeBotApiServer
from helpers import wait_until
from test_adapters_e2e import make_settings
from test_commerce_e2e import make_commerce_manager, start_both

CHAT = {"telegram": 71001, "bale": 72002}


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


def docs(server, chat):
    return [m for m in server.sent if m["kind"] == "sendDocument" and m["chat_id"] == str(chat)]


def confirmed_order(orders, products, platform):
    pid = products.add("کفش", 100_000, 10)
    products.set_cost(pid, 60_000)
    oid = orders.create(platform, str(CHAT[platform]), [(pid, 2)], payment_method="card_to_card", customer_name="علی رضایی")
    orders.mark_paid(oid, "card_to_card")
    orders.confirm(oid)
    return oid


@pytest.mark.parametrize("platform", ["telegram", "bale"])
def test_confirm_posts_ledger_and_delivers_invoice_pdf(tmp_path, tg, bale, platform):
    settings = make_settings()
    settings.invoice_auto_send = "after_confirm"
    settings.invoice_seller_name = "فروشگاه آزمایشی"
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    start_both(manager)
    try:
        oid = confirmed_order(orders, products, platform)
        server = tg if platform == "telegram" else bale
        assert wait_until(lambda: len(docs(server, CHAT[platform])) == 1, timeout=10), server.sent
        doc = docs(server, CHAT[platform])[0]
        assert doc["document"]["filename"].endswith(".pdf") and doc["document"]["size"] > 5000
        assert "فاکتور" in doc["text"] and f"#{oid}" in doc["text"]
        rep = manager.finance.report(0, 2**40)
        assert (rep.sales_net, rep.cogs, rep.orders_count) == (200_000, 120_000, 1)
        # فایل قبل از نوشتنِ وضعیتِ ارسال در دیتابیس به سرور می‌رسه؛ منتظرِ ثبتِ وضعیت می‌مونیم
        assert wait_until(lambda: manager.invoices.store.for_order(oid).sent.get("customer", {}).get("ok") is True, timeout=10)
        assert manager.invoices.store.for_order(oid).pdf_sha256
        # دوباره‌کاری بی‌اثر است: نه فاکتورِ دوم، نه ارسالِ دوم، نه ردیفِ دفترِ دوم
        orders.recover_inventory()
        manager._invoices._cooldown.clear()  # noqa: SLF001
        settle(manager)
        assert len(docs(server, CHAT[platform])) == 1 and len(manager.invoices.store.list()) == 1
        assert manager.finance.report(0, 2**40).orders_count == 1
    finally:
        manager.stop()


def settle(manager) -> None:
    """منتظرِ پایانِ اجراهای در-پروازِ فاکتور می‌مونه، بعد یک دورِ کاملِ ``process_pending`` را قطعی اجرا می‌کنه (بدونِ sleepِ حدسی)."""
    import asyncio

    assert wait_until(lambda: not manager._invoice_tasks, timeout=15)  # noqa: SLF001
    asyncio.run_coroutine_threadsafe(manager.invoices.process_pending(), manager._loop).result(30)  # noqa: SLF001


def test_blocked_customer_gets_nothing_and_off_means_off(tmp_path, tg, bale):
    settings = make_settings()
    settings.invoice_auto_send = "after_confirm"
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    start_both(manager)
    try:
        manager._store.ensure_conversation("telegram", str(CHAT["telegram"]), "علی")  # noqa: SLF001
        manager._store.set_blocked("telegram", str(CHAT["telegram"]), True)  # noqa: SLF001
        oid = confirmed_order(orders, products, "telegram")
        assert wait_until(lambda: manager.finance.report(0, 2**40).orders_count == 1, timeout=10)
        assert wait_until(lambda: manager.invoices.store.for_order(oid) is not None, timeout=10)  # صادر شد…
        settle(manager)
        assert manager.invoices.store.for_order(oid).sent == {}  # …ولی هرگز تلاشِ ارسالی نبود
        assert docs(tg, CHAT["telegram"]) == [] and manager.attention.count_open() == 0
        settings.invoice_auto_send = "off"
        oid2 = confirmed_order(orders, products, "bale")
        assert wait_until(lambda: manager.finance.report(0, 2**40).orders_count == 2, timeout=10)
        settle(manager)
        assert docs(bale, CHAT["bale"]) == [] and manager.invoices.store.for_order(oid2) is None  # خاموش = حتی صادر هم نمی‌شه
    finally:
        manager.stop()


def test_pdf_rejected_by_server_alerts_owner_and_manual_resend_works(tmp_path, tg, bale):
    settings = make_settings()
    settings.invoice_auto_send = "after_confirm"
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale, telegram_only=False)
    tg.reject_documents = True
    start_both(manager)
    try:
        oid = confirmed_order(orders, products, "telegram")
        assert wait_until(lambda: any("فاکتور" in m for m in tg.sent_to(CHAT["telegram"])), timeout=15)  # جایگزینِ متنی
        assert wait_until(lambda: manager.attention.count_open() >= 1, timeout=10)
        inv = manager.invoices.store.for_order(oid)
        assert wait_until(lambda: manager.invoices.store.get(inv.id).sent.get("customer", {}).get("ok") is False, timeout=10)
        tg.reject_documents = False
        import asyncio

        out = asyncio.run_coroutine_threadsafe(manager.invoices.send_customer(inv.id, force=True), manager._loop).result(15)  # noqa: SLF001
        assert out == "sent" and len(docs(tg, CHAT["telegram"])) == 1
        assert manager.attention.count_open() == 0  # با ارسالِ موفق «نیاز به توجه» بسته شد
    finally:
        manager.stop()


def test_customer_invoice_button_sends_only_own_confirmed_order(tmp_path, tg, bale):
    settings = make_settings()
    settings.invoice_seller_name = "فروشگاه آزمایشی"
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    settings.shop_mode = "shop_buttons"  # پیش‌فرضِ ۱.۰: جریانِ دکمه‌ای
    start_both(manager)
    try:
        oid = confirmed_order(orders, products, "telegram")
        tg.push_callback_query(CHAT["telegram"], f"c:od:{oid}")
        assert wait_until(lambda: any(f"c:inv:{oid}" in str(m) for m in tg.sent + tg.edits), timeout=10), "دکمه‌ی فاکتور دیده نشد"
        tg.push_callback_query(CHAT["telegram"], f"c:inv:{oid}")
        assert wait_until(lambda: len(docs(tg, CHAT["telegram"])) == 1, timeout=10)
        # مشتریِ دیگر با شناسه‌ی سفارشِ این مشتری چیزی نمی‌گیرد
        answered = len(tg.callback_answers)
        tg.push_callback_query(CHAT["telegram"] + 1, f"c:inv:{oid}")
        assert wait_until(lambda: len(tg.callback_answers) > answered, timeout=10)  # ربات جواب داد (نه فقط ساکت ماند)
        assert docs(tg, CHAT["telegram"] + 1) == [] and len(docs(tg, CHAT["telegram"])) == 1
    finally:
        manager.stop()


# ------------------------------------------------------------------- A7: هشدارِ موجودیِ کم
def test_low_stock_alert_is_raised_deduplicated_and_closed_on_restock(tmp_path, tg, bale):
    settings = make_settings()
    settings.low_stock_threshold = 3
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    start_both(manager)
    try:
        pid = products.add("کفش", 100_000, 5)
        unlimited = products.add("خدمت", 10_000, 1)
        with products._connection() as c:  # noqa: SLF001
            c.execute("UPDATE products SET unlimited_stock=1 WHERE id=?", (unlimited,))
        plenty = products.add("فراوان", 1000, 500)

        def buy(product, qty, chat):
            oid = orders.create("telegram", str(chat), [(product, qty)], payment_method="card_to_card", customer_name="x")
            orders.mark_paid(oid, "card_to_card")
            orders.confirm(oid)

        buy(plenty, 1, 1)
        buy(unlimited, 1, 2)
        assert manager.attention.count_open() == 0  # موجودیِ زیاد/نامحدود ⇒ هشدار نه
        buy(pid, 1, 3)  # ۵ → ۴: هنوز بالای آستانه
        assert manager.attention.count_open() == 0
        buy(pid, 1, 4)  # ۴ → ۳: رسید به آستانه
        items = manager.attention.list_open()
        assert [(i.type, i.ref) for i in items] == [("low_stock", str(pid))] and "3 عدد مانده" in items[0].detail
        buy(pid, 1, 5)  # ۳ → ۲: همان هشدار، تکراری ثبت نمی‌شود
        assert manager.attention.count_open() == 1
        products.adjust_stock(pid, 50)  # دوباره پر شد
        manager._reconcile_low_stock()  # noqa: SLF001 — حلقه‌ی نگهداری همین را صدا می‌زند
        assert manager.attention.count_open() == 0
        settings.low_stock_threshold = 0
        buy(pid, 49, 6)
        assert manager.attention.count_open() == 0  # آستانه‌ی ۰ = خاموش
    finally:
        manager.stop()
