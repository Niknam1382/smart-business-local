import threading

import pytest

from app.core.orders import (
    METHOD_BALE_PAY,
    METHOD_CARD_TO_CARD,
    OrderError,
    OrderStore,
    STATUS_CANCELLED,
    STATUS_CONFIRMED,
    STATUS_PAID,
    STATUS_PENDING_PAYMENT,
    STATUS_REJECTED,
)
from app.core.products import ProductStore


def make_stores(tmp_path):
    products = ProductStore(db_path=tmp_path / "products.db")
    orders = OrderStore(db_path=tmp_path / "orders.db", product_store=products)
    return products, orders


def test_create_order_computes_total_and_snapshots_items(tmp_path):
    products, orders = make_stores(tmp_path)
    p1 = products.add("گوشی", 10_000_000, 5)
    p2 = products.add("قاب", 200_000, 20)

    oid = orders.create("telegram", "1", [(p1, 1), (p2, 2)])
    order = orders.get(oid)
    assert order.status == STATUS_PENDING_PAYMENT
    assert order.total_irr == 10_000_000 + 2 * 200_000
    names = {i.product_name for i in order.items}
    assert names == {"گوشی", "قاب"}


def test_order_snapshot_survives_later_price_change(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 2)])
    products.update(pid, "محصول", 5000, 5)  # قیمت بعداً عوض شد
    order = orders.get(oid)
    assert order.total_irr == 2000, "فاکتور سفارش قدیمی نباید با تغییر قیمت بعدی عوض بشه"
    assert order.items[0].unit_price_irr == 1000


def test_create_order_validation_errors(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 5)
    with pytest.raises(OrderError, match="خالی"):
        orders.create("telegram", "1", [])
    with pytest.raises(OrderError, match="تعداد"):
        orders.create("telegram", "1", [(pid, 0)])
    with pytest.raises(OrderError, match="وجود نداره"):
        orders.create("telegram", "1", [(9999, 1)])


def test_full_happy_path_confirm_deducts_stock(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 10)
    oid = orders.create("telegram", "1", [(pid, 3)])

    orders.mark_paid(oid, METHOD_BALE_PAY, payment_reference="charge_123")
    order = orders.get(oid)
    assert order.status == STATUS_PAID and order.payment_method == METHOD_BALE_PAY
    assert products.get(pid).stock_quantity == 10, "فقط پرداخت -> هنوز نباید موجودی کم بشه"

    orders.confirm(oid)
    assert orders.get(oid).status == STATUS_CONFIRMED
    assert products.get(pid).stock_quantity == 7, "تایید صاحب فروشگاه -> حالا موجودی کم می‌شه"


def test_reject_after_paid_does_not_touch_stock(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 10)
    oid = orders.create("telegram", "1", [(pid, 3)])
    orders.mark_paid(oid, METHOD_CARD_TO_CARD)
    orders.reject(oid)
    assert orders.get(oid).status == STATUS_REJECTED
    assert products.get(pid).stock_quantity == 10


def test_cancel_before_payment(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 10)
    oid = orders.create("telegram", "1", [(pid, 1)])
    orders.cancel(oid)
    assert orders.get(oid).status == STATUS_CANCELLED


def test_invalid_transitions_are_rejected(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 10)
    oid = orders.create("telegram", "1", [(pid, 1)])

    with pytest.raises(OrderError):
        orders.confirm(oid)  # هنوز پرداخت نشده
    with pytest.raises(OrderError):
        orders.reject(oid)  # هنوز پرداخت نشده

    orders.mark_paid(oid, METHOD_BALE_PAY)
    with pytest.raises(OrderError):
        orders.cancel(oid)  # دیگه قابل‌لغو نیست، پرداخت شده

    orders.confirm(oid)
    with pytest.raises(OrderError):
        orders.confirm(oid)  # دوبار تایید
    with pytest.raises(OrderError):
        orders.reject(oid)  # بعد از تایید دیگه رد نمی‌شه


def test_confirm_with_insufficient_stock_rolls_back_fully(tmp_path):
    """دو قلم کالا؛ قلم اول موجودی کافی داره، دومی نداره — نباید اولی هم کم بشه."""
    products, orders = make_stores(tmp_path)
    p1 = products.add("کافی", 1000, 10)
    p2 = products.add("کم", 1000, 3)
    oid = orders.create("telegram", "1", [(p1, 2), (p2, 2)])
    orders.mark_paid(oid, METHOD_BALE_PAY)
    products.adjust_stock(p2, -2)  # صاحب فروشگاه بعد از ثبت سفارش، بیرون از برنامه فروخته -> فقط ۱ تا مونده

    with pytest.raises(OrderError, match="موجودی کافی نیست"):
        orders.confirm(oid)

    assert products.get(p1).stock_quantity == 10, "نباید نصفه‌کاره کم بشه"
    assert products.get(p2).stock_quantity == 1
    assert orders.get(oid).status == STATUS_PAID, "تایید ناموفق -> وضعیت نباید عوض بشه"


def test_list_filters_by_status_and_platform(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 100)
    o1 = orders.create("telegram", "1", [(pid, 1)])
    o2 = orders.create("bale", "2", [(pid, 1)])
    orders.mark_paid(o2, METHOD_CARD_TO_CARD)

    assert {o.id for o in orders.list()} == {o1, o2}
    assert [o.id for o in orders.list(status=STATUS_PAID)] == [o2]
    assert [o.id for o in orders.list(platform="telegram")] == [o1]


def test_list_for_chat(tmp_path):
    products, orders = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 100)
    mine = orders.create("telegram", "1", [(pid, 1)])
    orders.create("telegram", "2", [(pid, 1)])
    assert [o.id for o in orders.list_for_chat("telegram", "1")] == [mine]


def test_missing_order_operations_raise_clear_error(tmp_path):
    _, orders = make_stores(tmp_path)
    assert orders.get(999) is None
    with pytest.raises(OrderError):
        orders.mark_paid(999, METHOD_BALE_PAY)
    with pytest.raises(OrderError):
        orders.confirm(999)


def test_concurrent_confirm_only_one_succeeds_when_stock_is_tight(tmp_path):
    """دو سفارش جدا برای همون محصول، هر دو paid، فقط موجودی برای یکی کافیه."""
    products, orders = make_stores(tmp_path)
    pid = products.add("کالای کمیاب", 1000, 2)
    o1 = orders.create("telegram", "1", [(pid, 1)])
    o2 = orders.create("telegram", "2", [(pid, 1)])
    orders.mark_paid(o1, METHOD_BALE_PAY)
    orders.mark_paid(o2, METHOD_BALE_PAY)
    products.adjust_stock(pid, -1)  # یکی بیرون از برنامه فروخته رفت -> برای هر دو سفارش کافی نیست

    results = []
    lock = threading.Lock()

    def try_confirm(oid):
        try:
            orders.confirm(oid)
            with lock:
                results.append(("ok", oid))
        except OrderError as exc:
            with lock:
                results.append(("err", oid, str(exc)))

    threads = [threading.Thread(target=try_confirm, args=(o1,)), threading.Thread(target=try_confirm, args=(o2,))]
    [t.start() for t in threads]
    [t.join() for t in threads]

    oks = [r for r in results if r[0] == "ok"]
    errs = [r for r in results if r[0] == "err"]
    assert len(oks) == 1 and len(errs) == 1
    assert products.get(pid).stock_quantity == 0


def test_build_order_summary_and_confirmed_text(tmp_path):
    from app.core.orders import build_order_confirmed_text, build_order_summary_text

    products, orders = make_stores(tmp_path)
    p1 = products.add("گوشی", 10_000_000, 5)
    p2 = products.add("قاب", 200_000, 20)
    oid = orders.create("telegram", "1", [(p1, 1), (p2, 2)])
    order = orders.get(oid)

    summary = build_order_summary_text(order)
    assert f"سفارش #{oid}" in summary
    assert "گوشی ×1 = 10,000,000 ریال" in summary
    assert "قاب ×2 = 400,000 ریال" in summary
    assert "جمع کل: 10,400,000 ریال" in summary

    confirmed = build_order_confirmed_text(order)
    assert "تایید شد" in confirmed and summary in confirmed
