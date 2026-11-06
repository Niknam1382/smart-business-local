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


def test_unlimited_product_never_decrements_or_shows_fake_numbers(tmp_path):
    products, orders = make(tmp_path)
    pid = products.add("نان", 500, 0, unlimited_stock=True)
    assert products.get(pid).unlimited_stock and products.get(pid).stock_quantity == 0
    assert orders.available_quantity(pid) == UNLIMITED
    oid = paid_order(orders, pid, 3)
    orders.confirm(oid)
    assert products.get(pid).stock_quantity == 0 and orders.available_quantity(pid) == UNLIMITED


def test_physical_products_have_no_auto_delivery_api(tmp_path):
    products, _orders = make(tmp_path)
    pid = products.add("کتاب", 900, 4)
    product = products.get(pid)
    assert not hasattr(product, "delivery_kind") and not hasattr(product, "product_type")
    assert not any(hasattr(products, name) for name in ("add_keys", "keys_remaining", "allocated_keys"))


def test_customer_info_roundtrip_survives_confirm(tmp_path):
    products, orders = make(tmp_path)
    pid = products.add("کالا", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 1)], customer_info={"name": "مریم", "city": "شیراز"})
    orders.update_customer_info(oid, {"postal": "123"})
    assert orders.get(oid).customer_info == {"name": "مریم", "city": "شیراز", "postal": "123"}
    orders.mark_paid(oid, "card_to_card", "ref-1")
    orders.confirm(oid)
    assert orders.get(oid).inventory_applied is True and orders.get(oid).customer_info["postal"] == "123"
