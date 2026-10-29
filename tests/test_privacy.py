"""R10-۴ — حریمِ خصوصی: نگه‌داریِ محدود، /forget، خطِ شفافیتِ AI."""

import pytest
from fake_servers import FakeBotApiServer
from helpers import wait_until
from shop_harness import Harness, texts  # noqa: F401
from test_shop_e2e import send, shop, status, tap  # noqa: F401

from app.core.conversations import ConversationStore
from app.core.orders import METHOD_CARD_TO_CARD, OrderStore
from app.core.products import ProductStore


def age(conn, table, column, days, where="1=1"):
    conn.execute(f"UPDATE {table} SET {column} = datetime('now', '-{days} day') WHERE {where}")
    conn.commit()


def test_purge_older_than_keeps_recent_and_blocked(tmp_path):
    store = ConversationStore(tmp_path / "c.db")
    for chat in ("old", "new", "blocked"):
        store.ensure_conversation("telegram", chat, chat)
        store.add_message("telegram", chat, "user", f"سلام {chat}")
    store.set_blocked("telegram", "blocked", True)
    conn = store.connection()
    age(conn, "messages", "created_at", 40, "chat_id IN ('old','blocked')")
    age(conn, "conversations", "updated_at", 40, "chat_id IN ('old','blocked')")
    assert store.purge_older_than(0) == 0  # ۰ = نگه‌دار
    assert store.purge_older_than(30) == 2
    assert [m.content for m in store.get_messages("telegram", "new")] == ["سلام new"]
    assert store.get_messages("telegram", "old") == []
    assert store.is_blocked("telegram", "blocked") is True  # فهرستِ بلاک نباید با حذفِ قدیمی‌ها گم بشه
    names = {c.chat_id for c in store.list_conversations()}
    assert "old" not in names and {"new", "blocked"} <= names


def test_anonymize_closed_orders_only_and_keeps_totals(tmp_path):
    products = ProductStore(tmp_path / "p.db")
    orders = OrderStore(tmp_path / "o.db", product_store=products)
    pid = products.add("کالا", 1000, 50)
    ids = {}
    for kind in ("confirmed", "pending", "paid"):
        oid = orders.create("telegram", kind, [(pid, 2)], customer_name="مریم", customer_phone="0912", customer_address="شیراز",
                            note="زنگ نزنید", customer_info={"city": "شیراز"})
        if kind != "pending":
            orders.mark_paid(oid, METHOD_CARD_TO_CARD, "r")
        if kind == "confirmed":
            orders.confirm(oid)
        ids[kind] = oid
    conn = orders.connection()
    age(conn, "orders", "updated_at", 60)
    assert orders.anonymize_closed(0) == 0
    assert orders.anonymize_closed(30) == 1
    done = orders.get(ids["confirmed"])
    assert (done.customer_name, done.customer_phone, done.customer_address, done.note, done.customer_info) == ("", "", "", "", {})
    assert done.total_irr == 2000 and done.items[0].quantity == 2  # حسابداری سالم
    for open_status in ("pending", "paid"):
        assert orders.get(ids[open_status]).customer_name == "مریم"  # سفارش‌های باز دست‌نخورده
    assert orders.anonymize_closed(30) == 0  # idempotent


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


def test_welcome_includes_ai_disclosure_by_default_and_can_be_disabled_or_edited(h):
    assert "هوش مصنوعی" in texts(h.say("/start"))
    h.settings.ai_disclosure_enabled = False
    assert "هوش مصنوعی" not in texts(h.say("/start"))
    h.settings.ai_disclosure_enabled = True
    from app.core import shop_texts

    shop_texts.set_override(h.settings, "privacy.ai_disclosure", "fa", "🤖 دستیارِ هوشمندِ فروشگاهِ ما")
    assert "دستیارِ هوشمندِ فروشگاهِ ما" in texts(h.say("/start"))


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


def test_forget_wipes_chat_data_but_keeps_open_orders_and_blocks(tmp_path, tg, bale, monkeypatch):
    manager, products, orders, settings, engine = shop(tmp_path, tg, bale, monkeypatch)
    pid = products.add("کالا", 1000, 9)
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        send(tg, 10, "سلام، یه سؤال", "جواب AI")
        tap_cart = manager._pipeline._shop_flow  # noqa: SLF001
        tap_cart.carts.set_qty("telegram", "10", pid, 2)
        tap_cart.sessions.put("telegram", "10", "field", {"fields": ["name"], "answers": {}, "idx": 0})
        closed = orders.create("telegram", "10", [(pid, 1)], customer_name="علی", customer_phone="0912")
        orders.mark_paid(closed, METHOD_CARD_TO_CARD, "r")
        orders.confirm(closed)
        open_order = orders.create("telegram", "10", [(pid, 1)], customer_name="علی", customer_phone="0912")
        assert manager.store.get_messages("telegram", "10")
        send(tg, 10, "/forget", "پاک شد")
        assert manager.store.get_messages("telegram", "10") == []
        assert tap_cart.carts.count("telegram", "10") == 0 and tap_cart.sessions.get("telegram", "10") is None
        assert orders.get(closed).customer_name == "" and orders.get(closed).customer_phone == ""
        assert orders.get(open_order).customer_name == "علی"  # سفارشِ در جریان دست‌نخورده
        manager.store.ensure_conversation("telegram", "10", "علی")
        manager.store.set_blocked("telegram", "10", True)
        tg.push_message(10, "/forget")
        assert wait_until(lambda: sum("پاک شد" in m for m in tg.sent_to(10)) == 2)
        assert manager.store.is_blocked("telegram", "10")  # /forget بلاک رو دور نمی‌زنه
    finally:
        manager.stop()


def test_advisor_mode_sends_disclosure_on_start_then_ai_answers(tmp_path, tg, bale, monkeypatch):
    manager, products, orders, settings, engine = shop(tmp_path, tg, bale, monkeypatch, mode="advisor")
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        send(tg, 10, "/start", "هوش مصنوعی")
        assert wait_until(lambda: any("پاسخ: /start" in m for m in tg.sent_to(10)))  # AIِ خالص (بدونِ ابزار) طبقِ معمول جواب داد
    finally:
        manager.stop()
