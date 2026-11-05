"""R10-۱ — تاییدِ اتمیکِ سفارش/موجودی (saga قابل‌بازیابی): کرش، ترد، بازیابی، نامحدود، کلیدِ دیجیتال."""

import threading

import pytest

from app.core.orders import METHOD_CARD_TO_CARD, UNLIMITED, OrderError, OrderStore, STATUS_CONFIRMED, STATUS_PAID
from app.core.products import ProductStore


def make(tmp_path):
    products = ProductStore(tmp_path / "products.db")
    return products, OrderStore(tmp_path / "orders.db", product_store=products)


def paid_order(orders, pid, qty, chat="1"):
    oid = orders.create("telegram", chat, [(pid, qty)])
    orders.mark_paid(oid, METHOD_CARD_TO_CARD, "ref")
    return oid


def test_confirm_applies_stock_once_and_marks_ledger(tmp_path):
    products, orders = make(tmp_path)
    pid = products.add("کالا", 1000, 5)
    oid = paid_order(orders, pid, 2)
    orders.confirm(oid)
    order = orders.get(oid)
    assert order.status == STATUS_CONFIRMED and order.inventory_applied
    assert products.get(pid).stock_quantity == 3 and products.ledger_has(oid)
    assert orders.available_quantity(pid) == 3
    assert products.apply_order_stock(oid, [(pid, 2)]) is False  # idempotent
    assert products.get(pid).stock_quantity == 3


def test_crash_between_claim_and_stock_is_recovered(tmp_path, monkeypatch):
    products, orders = make(tmp_path)
    pid = products.add("کالا", 1000, 5)
    oid = paid_order(orders, pid, 2)

    def boom(*_a, **_k):
        raise RuntimeError("crash")

    with monkeypatch.context() as m:
        m.setattr(products, "apply_order_stock", boom)
        with pytest.raises(RuntimeError):
            orders.confirm(oid)
    order = orders.get(oid)
    assert order.status == STATUS_CONFIRMED and not order.inventory_applied
    assert products.get(pid).stock_quantity == 5
    assert orders.available_quantity(pid) == 3  # هنوز رزرو است؛ بالاتر از واقعیت نمی‌رود
    assert orders.recover_inventory() == [(oid, "recovered", "")]
    assert products.get(pid).stock_quantity == 3 and orders.get(oid).inventory_applied
    assert orders.available_quantity(pid) == 3
    assert orders.recover_inventory() == []


def test_crash_after_stock_before_flag_is_recovered_without_double_decrement(tmp_path, monkeypatch):
    products, orders = make(tmp_path)
    pid = products.add("کالا", 1000, 5)
    oid = paid_order(orders, pid, 2)
    with monkeypatch.context() as m:
        m.setattr(orders, "_mark_inventory_applied", lambda _oid: (_ for _ in ()).throw(RuntimeError("crash")))
        with pytest.raises(RuntimeError):
            orders.confirm(oid)
    assert products.get(pid).stock_quantity == 3 and not orders.get(oid).inventory_applied
    assert orders.available_quantity(pid) == 1  # محافظه‌کارانه: کمتر از واقعیت، هرگز بیشتر
    assert orders.recover_inventory() == [(oid, "already", "")]
    assert products.get(pid).stock_quantity == 3 and orders.get(oid).inventory_applied
    assert orders.available_quantity(pid) == 3


def test_recover_with_insufficient_stock_reverts_to_paid(tmp_path, monkeypatch):
    products, orders = make(tmp_path)
    pid = products.add("کالا", 1000, 5)
    oid = paid_order(orders, pid, 2)
    with monkeypatch.context() as m:
        m.setattr(products, "apply_order_stock", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("crash")))
        with pytest.raises(RuntimeError):
            orders.confirm(oid)
    products.adjust_stock(pid, -4)  # بیرون از برنامه فروخته رفت
    [(rid, outcome, detail)] = orders.recover_inventory()
    assert (rid, outcome) == (oid, "insufficient") and "موجودی کافی نیست" in detail
    assert orders.get(oid).status == STATUS_PAID and not products.ledger_has(oid)
    assert products.get(pid).stock_quantity == 1


def test_confirm_insufficient_stock_leaves_everything_untouched(tmp_path):
    products, orders = make(tmp_path)
    a = products.add("الف", 1000, 5)
    b = products.add("ب", 1000, 5)
    oid = orders.create("telegram", "1", [(a, 2), (b, 3)])
    orders.mark_paid(oid, METHOD_CARD_TO_CARD)
    products.adjust_stock(b, -4)
    with pytest.raises(OrderError, match="موجودی کافی نیست"):
        orders.confirm(oid)
    assert orders.get(oid).status == STATUS_PAID
    assert (products.get(a).stock_quantity, products.get(b).stock_quantity) == (5, 1)  # الف هم دست‌نخورده (rollback)
    assert not products.ledger_has(oid)


def test_twelve_concurrent_confirms_apply_exactly_once(tmp_path):
    products, orders = make(tmp_path)
    pid = products.add("کالا", 1000, 10)
    oid = paid_order(orders, pid, 4)
    barrier = threading.Barrier(12)
    outcomes: list = []

    def worker():
        barrier.wait()
        try:
            orders.confirm(oid)
            outcomes.append("ok")
        except OrderError:
            outcomes.append("err")

    threads = [threading.Thread(target=worker) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert outcomes.count("ok") == 1 and outcomes.count("err") == 11
    assert products.get(pid).stock_quantity == 6 and orders.get(oid).inventory_applied


def test_unlimited_digital_product_never_decrements_or_shows_fake_numbers(tmp_path):
    products, orders = make(tmp_path)
    pid = products.add("دوره", 500, product_type="digital", delivery_kind="link", delivery_payload="https://x.example/d")
    assert products.get(pid).unlimited_stock and products.get(pid).delivery_payload == "https://x.example/d"
    assert orders.available_quantity(pid) == UNLIMITED
    oid = paid_order(orders, pid, 3)
    orders.confirm(oid)
    assert products.get(pid).stock_quantity == 0 and orders.available_quantity(pid) == UNLIMITED


def test_digital_keys_are_allocated_atomically_and_never_shared(tmp_path):
    products, orders = make(tmp_path)
    pid = products.add("لایسنس", 900, product_type="digital", delivery_kind="keys")
    assert products.add_keys(pid, ["K1", "K2", "K3", " ", ""]) == 3
    assert products.get(pid).stock_quantity == 3 and products.keys_remaining(pid) == 3
    o1 = paid_order(orders, pid, 2, chat="1")
    with pytest.raises(OrderError, match="فقط 1 عدد"):
        orders.create("telegram", "2", [(pid, 2)])  # کلیدِ سوم برای دو نفر نیست
    orders.confirm(o1)
    assert [k for _pid, k in products.allocated_keys(o1)] == ["K1", "K2"]
    assert products.keys_remaining(pid) == 1 and products.get(pid).stock_quantity == 1
    orders.recover_inventory()
    assert [k for _pid, k in products.allocated_keys(o1)] == ["K1", "K2"]  # تحویلِ دوباره = همان کلیدها
    o2 = paid_order(orders, pid, 1, chat="3")
    orders.confirm(o2)
    assert [k for _pid, k in products.allocated_keys(o2)] == ["K3"] and products.keys_remaining(pid) == 0


def test_mark_delivered_is_idempotent_and_info_roundtrip(tmp_path):
    products, orders = make(tmp_path)
    pid = products.add("کالا", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 1)], customer_info={"name": "مریم", "city": "شیراز"})
    orders.update_customer_info(oid, {"postal": "123"})
    assert orders.get(oid).customer_info == {"name": "مریم", "city": "شیراز", "postal": "123"}
    assert orders.mark_delivered(oid) is True and orders.mark_delivered(oid) is False
