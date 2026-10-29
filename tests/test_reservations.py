"""
رزروِ موجودی (مهلت پیش‌فرض ۱۵ دقیقه): تا وقتی سفارشی منتظر پرداخته، همون تعداد
به مشتری دیگه فروخته نمی‌شه؛ بعد از انقضا آزاد می‌شه؛ پرداخت‌شده‌ها تا تایید/
رد رزرو می‌مونن؛ و دو مشتریِ هم‌زمان نمی‌تونن آخرین قطعه رو دوبار رزرو کنن.
"""

import sqlite3
import threading
import time

import pytest

from app.core.orders import (
    METHOD_CARD_TO_CARD,
    METHOD_ZARINPAL,
    STATUS_EXPIRED,
    STATUS_PAID,
    STATUS_PENDING_PAYMENT,
    OrderError,
    OrderStore,
)
from app.core.products import ProductStore


def make_stores(tmp_path):
    products = ProductStore(db_path=tmp_path / "p.db")
    orders = OrderStore(db_path=tmp_path / "o.db", product_store=products)
    return products, orders


def test_pending_order_holds_stock_for_others(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("گوشی", 1000, 2)
    orders.create("telegram", "1", [(pid, 2)])

    assert orders.available_quantity(pid) == 0
    assert products.get(pid).stock_quantity == 2, "موجودیِ واقعی با رزرو دست نمی‌خوره"
    with pytest.raises(OrderError, match="رزرو"):
        orders.create("bale", "2", [(pid, 1)])


def test_partial_availability_message_has_the_number(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("گوشی", 1000, 3)
    orders.create("telegram", "1", [(pid, 2)])
    with pytest.raises(OrderError, match="فقط 1 عدد"):
        orders.create("bale", "2", [(pid, 2)])
    orders.create("bale", "2", [(pid, 1)])  # همون یکی که مونده، قابل‌سفارشه


def test_reservation_released_after_expiry(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("گوشی", 1000, 1)
    oid = orders.create("telegram", "1", [(pid, 1)], reserve_minutes=15)
    assert orders.get(oid).seconds_left() > 14 * 60

    # هنوز ۱۴ دقیقه گذشته -> رزرو سر جاشه
    assert orders.expire_stale(now=time.time() + 14 * 60) == []
    assert orders.available_quantity(pid, now=time.time() + 14 * 60) == 0

    # بعد از ۱۵ دقیقه: حتی قبل از اجرای جاروکننده، موجودیِ قابل‌فروش آزاده
    later = time.time() + 15 * 60 + 5
    assert orders.available_quantity(pid, now=later) == 1

    expired = orders.expire_stale(now=later)
    assert [o.id for o in expired] == [oid]
    assert orders.get(oid).status == STATUS_EXPIRED
    assert orders.expire_stale(now=later) == [], "دومین بار چیزی برای انقضا نیست"
    orders.create("bale", "2", [(pid, 1)])  # مشتری بعدی می‌تونه بخره


def test_custom_reservation_minutes(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("x", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 1)], reserve_minutes=30)
    left = orders.get(oid).seconds_left()
    assert 29 * 60 < left <= 30 * 60


def test_paid_orders_keep_reservation_until_decided(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("گوشی", 1000, 1)
    oid = orders.create("telegram", "1", [(pid, 1)], reserve_minutes=15)
    orders.mark_paid(oid, METHOD_CARD_TO_CARD)

    far_future = time.time() + 5 * 3600
    assert orders.expire_stale(now=far_future) == [], "سفارشِ پرداخت‌شده هیچ‌وقت منقضی نمی‌شه"
    assert orders.available_quantity(pid, now=far_future) == 0

    orders.reject(oid)
    assert orders.available_quantity(pid) == 1, "رد سفارش رزرو رو آزاد می‌کنه"


def test_confirm_converts_reservation_into_real_deduction(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("گوشی", 1000, 3)
    oid = orders.create("telegram", "1", [(pid, 2)])
    orders.mark_paid(oid, METHOD_CARD_TO_CARD)
    assert orders.available_quantity(pid) == 1

    orders.confirm(oid)
    assert products.get(pid).stock_quantity == 1
    assert orders.available_quantity(pid) == 1, "رزرو دوبار از موجودی کم نمی‌شه"


def test_cancel_releases_reservation(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("گوشی", 1000, 1)
    oid = orders.create("telegram", "1", [(pid, 1)])
    orders.cancel(oid)
    assert orders.available_quantity(pid) == 1


def test_same_product_twice_in_one_order_is_merged_for_the_stock_check(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("گوشی", 1000, 3)
    with pytest.raises(OrderError, match="فقط 3 عدد"):
        orders.create("telegram", "1", [(pid, 2), (pid, 2)])
    assert orders.list() == []
    oid = orders.create("telegram", "1", [(pid, 2), (pid, 1)])
    assert sum(i.quantity for i in orders.get(oid).items) == 3


def test_failed_multi_item_order_creates_nothing(tmp_path):
    products, orders = make_stores(tmp_path)
    a = products.add("الف", 1000, 5)
    b = products.add("ب", 1000, 1)
    with pytest.raises(OrderError):
        orders.create("telegram", "1", [(a, 2), (b, 2)])
    assert orders.list() == []
    assert orders.available_quantity(a) == 5


def test_concurrent_creates_never_oversell(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("کمیاب", 1000, 3)
    ok, bad = [], []
    lock = threading.Lock()
    barrier = threading.Barrier(12)

    def worker(i):
        barrier.wait()
        try:
            oid = orders.create("telegram", str(i), [(pid, 1)])
            with lock:
                ok.append(oid)
        except OrderError as exc:
            with lock:
                bad.append(str(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(ok) == 3 and len(bad) == 9
    assert orders.available_quantity(pid) == 0


def test_late_gateway_payment_on_expired_order_is_flagged(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("گوشی", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 1)])
    orders.expire_stale(now=time.time() + 16 * 60)
    orders.mark_paid(oid, METHOD_ZARINPAL, "ref-1")
    order = orders.get(oid)
    assert order.status == STATUS_PAID and order.paid_late is True


def test_normal_payment_is_not_flagged_late(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("گوشی", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 1)])
    orders.mark_paid(oid, METHOD_CARD_TO_CARD)
    assert orders.get(oid).paid_late is False


def test_set_payment_info_only_while_pending(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("گوشی", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 1)])
    orders.set_payment_info(oid, METHOD_ZARINPAL, gateway_ref="A00001", payment_url="https://pay/x")
    o = orders.get(oid)
    assert (o.payment_method, o.gateway_ref, o.payment_url) == (METHOD_ZARINPAL, "A00001", "https://pay/x")
    orders.mark_paid(oid, METHOD_ZARINPAL)
    with pytest.raises(OrderError):
        orders.set_payment_info(oid, METHOD_CARD_TO_CARD)


def test_update_customer_details(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("گوشی", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 1)], customer_name="علی")
    orders.update_customer(oid, phone=" 09120000000 ", address="تهران، خیابان آزادی")
    o = orders.get(oid)
    assert (o.customer_name, o.customer_phone, o.customer_address) == ("علی", "09120000000", "تهران، خیابان آزادی")
    orders.cancel(oid)
    with pytest.raises(OrderError, match="بسته"):
        orders.update_customer(oid, name="x")


def test_active_for_chat_lists_only_live_orders(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("گوشی", 1000, 10)
    live = orders.create("telegram", "1", [(pid, 1)])
    paid = orders.create("telegram", "1", [(pid, 1)])
    orders.mark_paid(paid, METHOD_CARD_TO_CARD)
    cancelled = orders.create("telegram", "1", [(pid, 1)])
    orders.cancel(cancelled)
    other = orders.create("telegram", "2", [(pid, 1)])
    ids = {o.id for o in orders.active_for_chat("telegram", "1")}
    assert ids == {live, paid} and other not in ids


def test_pending_gateway_orders_includes_recently_expired_within_grace(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("گوشی", 1000, 10)
    oid = orders.create("telegram", "1", [(pid, 1)])
    orders.set_payment_info(oid, METHOD_ZARINPAL, gateway_ref="A1")
    t = time.time() + 20 * 60  # ۵ دقیقه بعد از انقضا
    orders.expire_stale(now=t)
    assert [o.id for o in orders.pending_gateway_orders(METHOD_ZARINPAL, now=t)] == [oid]
    assert orders.pending_gateway_orders(METHOD_ZARINPAL, now=time.time() + 3 * 3600) == []


def test_old_database_is_migrated_in_place(tmp_path):
    """دیتابیسِ فاز ۴ اول (بدون ستون‌های رزرو) باید بدون از دست رفتن داده باز بشه."""
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT NOT NULL, chat_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending_payment', payment_method TEXT NOT NULL DEFAULT '',
            payment_reference TEXT NOT NULL DEFAULT '', total_irr INTEGER NOT NULL DEFAULT 0,
            note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE TABLE order_items (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL,
            product_id INTEGER, product_name TEXT NOT NULL, unit_price_irr INTEGER NOT NULL, quantity INTEGER NOT NULL);
        INSERT INTO orders (platform, chat_id, status, total_irr) VALUES ('telegram', '9', 'pending_payment', 5000);
        INSERT INTO order_items (order_id, product_id, product_name, unit_price_irr, quantity) VALUES (1, 1, 'قدیمی', 5000, 1);
        """
    )
    conn.commit()
    conn.close()

    products = ProductStore(db_path=tmp_path / "p.db")
    orders = OrderStore(db_path=db, product_store=products)
    old = orders.get(1)
    assert old.status == STATUS_PENDING_PAYMENT and old.expires_ts == 0
    assert old.customer_phone == "" and old.paid_late is False
    # سفارشِ قدیمیِ بدون مهلت هیچ‌وقت خودکار منقضی نمی‌شه (قبلاً مهلتی نداشت)
    assert orders.expire_stale(now=time.time() + 10**7) == []
    # و ساخت سفارش جدید روی همین دیتابیس کار می‌کنه
    pid = products.add("جدید", 1000, 4)
    assert orders.create("telegram", "1", [(pid, 1)]) > 1


# ------------------------------------------------------------ ویرایش سفارش و پرداخت دیررس


def test_replace_items_rechecks_stock_excluding_own_reservation(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("گوشی", 1000, 3)
    other = products.add("هدفون", 500, 5)
    oid = orders.create("telegram", "1", [(pid, 3)])
    # خودِ سفارش ۳ تا رزرو کرده؛ ویرایش به ۲ تا و یه قلم دیگه باید ممکن باشه (رزرو خودش مانع نمی‌شه)
    orders.replace_items(oid, [(pid, 2), (other, 1)])
    o = orders.get(oid)
    assert {(i.product_name, i.quantity) for i in o.items} == {("گوشی", 2), ("هدفون", 1)}
    assert o.total_irr == 2 * 1000 + 500
    assert orders.available_quantity(pid) == 1, "۱ تایی که از رزرو آزاد شد، قابل‌فروشه"


def test_replace_items_insufficient_stock_leaves_order_untouched(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("گوشی", 1000, 3)
    orders.create("bale", "9", [(pid, 1)])  # مشتری دیگه ۱ تا رزرو کرده
    oid = orders.create("telegram", "1", [(pid, 1)])
    with pytest.raises(OrderError, match="فقط 2 عدد"):
        orders.replace_items(oid, [(pid, 3)])
    o = orders.get(oid)
    assert [(i.product_id, i.quantity) for i in o.items] == [(pid, 1)] and o.total_irr == 1000


def test_replace_items_resets_deadline_and_forgets_the_card_choice(tmp_path):
    """کارت‌به‌کارت: مبلغِ پیامِ قبلی دیگه معتبر نیست؛ باید دوباره start_payment بشه."""
    products, orders = make_stores(tmp_path)
    pid = products.add("گوشی", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 1)], reserve_minutes=15)
    orders.set_payment_info(oid, METHOD_CARD_TO_CARD)
    orders.replace_items(oid, [(pid, 2)], reserve_minutes=15)
    o = orders.get(oid)
    assert (o.payment_method, o.gateway_ref, o.payment_url) == ("", "", "")
    assert o.total_irr == 2000 and o.seconds_left() > 14 * 60


def test_replace_items_refused_when_not_pending_or_expired(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("گوشی", 1000, 5)
    paid = orders.create("telegram", "1", [(pid, 1)])
    orders.mark_paid(paid, METHOD_CARD_TO_CARD)
    with pytest.raises(OrderError, match="قابل‌ویرایش نیست"):
        orders.replace_items(paid, [(pid, 2)])
    late = orders.create("telegram", "2", [(pid, 1)], reserve_minutes=1)
    orders.expire_stale(now=time.time() + 120)
    with pytest.raises(OrderError, match="قابل‌ویرایش نیست"):
        orders.replace_items(late, [(pid, 2)])


def test_gateway_payment_after_cancel_is_recorded_not_lost(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("گوشی", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 1)])
    orders.cancel(oid)
    orders.mark_paid(oid, METHOD_ZARINPAL, "ref-9")
    o = orders.get(oid)
    assert o.status == STATUS_PAID and o.paid_late is True
