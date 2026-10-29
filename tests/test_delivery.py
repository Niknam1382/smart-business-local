"""R4 — تحویلِ خودکارِ محصولاتِ دیجیتال: متن/لینک/فایل/کلید، idempotency، شکست و تلاشِ مجدد."""

import asyncio

import pytest
from fake_servers import FakeBotApiServer
from helpers import wait_until
from test_shop_e2e import shop, status, tap, send  # noqa: F401

from app.core.delivery import DeliveryService
from app.core.orders import METHOD_CARD_TO_CARD, OrderStore
from app.core.products import ProductStore
from app.core.settings import AppSettings


def setup(tmp_path):
    products = ProductStore(tmp_path / "p.db")
    orders = OrderStore(tmp_path / "o.db", product_store=products)
    return products, orders, DeliveryService(products, orders, lambda: AppSettings())


def confirmed(orders, items, chat="1"):
    oid = orders.create("telegram", chat, items)
    orders.mark_paid(oid, METHOD_CARD_TO_CARD, "r")
    orders.confirm(oid)
    return orders.get(oid)


class Sink:
    def __init__(self, fail_times=0):
        self.msgs, self.fail_times = [], fail_times

    async def __call__(self, msg):
        if self.fail_times:
            self.fail_times -= 1
            raise RuntimeError("network down")
        self.msgs.append(msg)


def deliver(svc, order, sink):
    return asyncio.run(svc.deliver(order, sink))


def test_text_link_file_and_keys_are_delivered_once(tmp_path):
    products, orders, svc = setup(tmp_path)
    f = tmp_path / "guide.pdf"
    f.write_bytes(b"%PDF-1.4 hello")
    t = products.add("نکات", 100, product_type="digital", delivery_kind="text", delivery_payload="کدِ تخفیف: ABC")
    l = products.add("دوره", 200, product_type="digital", delivery_kind="link", delivery_payload="https://x.example/course")
    fl = products.add("راهنما", 300, product_type="digital", delivery_kind="file", delivery_payload=str(f))
    k = products.add("لایسنس", 400, product_type="digital", delivery_kind="keys")
    products.add_keys(k, ["KEY-1", "KEY-2"])
    order = confirmed(orders, [(t, 1), (l, 1), (fl, 1), (k, 2)])
    sink = Sink()
    assert deliver(svc, order, sink) == "delivered"
    texts = "\n".join(m.text for m in sink.msgs)
    assert "ABC" in texts and "https://x.example/course" in texts and "KEY-1" in texts and "KEY-2" in texts
    assert any(m.document == str(f) for m in sink.msgs)
    assert any(b.url == "https://x.example/course" for m in sink.msgs for row in m.rows for b in row)
    assert orders.get(order.id).delivered_ts > 0
    sink2 = Sink()
    assert deliver(svc, order, sink2) == "nothing" and not sink2.msgs  # دوباره‌ی تحویل = هیچ (idempotent)
    assert products.keys_remaining(k) == 0


def test_failed_send_is_retried_and_no_key_is_consumed_twice(tmp_path):
    products, orders, svc = setup(tmp_path)
    k = products.add("لایسنس", 400, product_type="digital", delivery_kind="keys")
    products.add_keys(k, ["A", "B", "C"])
    order = confirmed(orders, [(k, 1)])
    flaky = Sink(fail_times=1)
    assert deliver(svc, order, flaky).startswith("failed:") and orders.get(order.id).delivered_ts == 0
    assert orders.pending_deliveries() == [order.id]
    ok = Sink()
    assert deliver(svc, order, ok) == "delivered"
    assert "A" in "\n".join(m.text for m in ok.msgs) and products.keys_remaining(k) == 2  # همان کلید؛ کلیدِ تازه مصرف نشد
    assert orders.pending_deliveries() == []


def test_physical_only_and_legacy_orders_have_nothing_to_deliver(tmp_path):
    products, orders, svc = setup(tmp_path)
    p = products.add("کالا", 100, 5)
    order = confirmed(orders, [(p, 1)])
    assert orders.get(order.id).delivered_ts == -1 and orders.pending_deliveries() == []
    assert deliver(svc, order, Sink()) == "nothing"


def test_mixed_order_delivers_only_digital_items_and_missing_file_fails_cleanly(tmp_path):
    products, orders, svc = setup(tmp_path)
    phys = products.add("کالا", 100, 5)
    dig = products.add("نکات", 100, product_type="digital", delivery_kind="text", delivery_payload="سلام")
    order = confirmed(orders, [(phys, 1), (dig, 1)])
    sink = Sink()
    assert deliver(svc, order, sink) == "delivered"
    assert all("کالا" not in m.text for m in sink.msgs)
    bad = products.add("فایل", 100, product_type="digital", delivery_kind="file", delivery_payload=str(tmp_path / "gone.zip"))
    order2 = confirmed(orders, [(bad, 1)], chat="2")
    result = deliver(svc, order2, Sink())
    assert result.startswith("failed:") and "پیدا نشد" in result and orders.get(order2.id).delivered_ts == 0


def test_unconfirmed_order_is_never_delivered(tmp_path):
    products, orders, svc = setup(tmp_path)
    dig = products.add("نکات", 100, product_type="digital", delivery_kind="text", delivery_payload="راز")
    oid = orders.create("telegram", "1", [(dig, 1)])
    sink = Sink()
    assert deliver(svc, orders.get(oid), sink) == "nothing" and not sink.msgs


# ---------------------------------------------------------------- e2e (آداپتورِ واقعی) ----


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


def test_delivery_over_telegram_with_document_and_retry_after_bot_outage(tmp_path, tg, bale, monkeypatch):
    monkeypatch.setattr("app.core.bot_manager.DELIVERY_RETRY_MIN_AGE_SECONDS", 0)
    manager, products, orders, settings, _ = shop(tmp_path, tg, bale, monkeypatch)
    f = tmp_path / "e.pdf"
    f.write_bytes(b"%PDF-1.4 x")
    pid = products.add("کتاب", 500, product_type="digital", delivery_kind="file", delivery_payload=str(f))
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        send(tg, 10, "🛍 محصولات", "محصولات")
        tap(tg, 10, f"c:p:{pid}:-:1")
        tap(tg, 10, f"c:a:{pid}:1:-:1")
        send(tg, 10, "✅ نهایی کردن سفارش", "نام")
        send(tg, 10, "مریم", "موبایل")
        send(tg, 10, "09121234567", "توضیحات")  # فقط محصولِ دیجیتال ⇒ آدرس پرسیده نمی‌شه
        tap(tg, 10, "c:ck:s")
        tap(tg, 10, "c:ck:ok")
        tap(tg, 10, "c:pm:card_to_card")
        oid = orders.list()[0].id
        tap(tg, 10, f"c:paid:{oid}")
        assert wait_until(lambda: orders.get(oid).status == "paid")
        tg.reject_documents = True
        orders.confirm(oid)
        assert wait_until(lambda: orders.get(oid).delivered_ts == 0 and not any(m["kind"] == "sendDocument" for m in tg.sent), timeout=3)
        tg.reject_documents = False  # شبکه برگشت؛ حلقه‌ی نگهداری دوباره تلاش می‌کنه
        assert wait_until(lambda: any(m["kind"] == "sendDocument" for m in tg.sent), timeout=15)
        assert wait_until(lambda: orders.get(oid).delivered_ts > 0)
        assert sum(1 for m in tg.sent if m["kind"] == "sendDocument") == 1
    finally:
        manager.stop()
