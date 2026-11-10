import logging
import threading

import pytest

from app.core.orders import (
    METHOD_BALE_PAY,
    METHOD_CARD_TO_CARD,
    OrderError,
    OrderStore,
    STATUS_CANCELLED,
    STATUS_CLOSED,
    STATUS_CONFIRMED,
    STATUS_EXPIRED,
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


# ------------------------------------------------------------ وضعیتِ «ارسال»


def confirmed_order(tmp_path, chat="1"):
    """سفارشِ تأییدشده‌ی آماده — نقطه‌ی شروعِ همه‌ی تست‌های وضعیتِ ارسال."""
    products, orders = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 10)
    oid = orders.create("telegram", chat, [(pid, 1)])
    orders.mark_paid(oid, METHOD_BALE_PAY)
    orders.confirm(oid)
    return products, orders, oid


def test_fulfillment_starts_empty_on_confirmed_orders(tmp_path):
    _, orders, oid = confirmed_order(tmp_path)
    order = orders.get(oid)
    assert order.fulfillment == "" and order.tracking_code == ""


def test_fulfillment_moves_forward_only(tmp_path):
    """قاعده‌ی اصلی: آماده‌سازی ← ارسال ← تحویل؛ هیچ برگشتی جز پاک‌کردنِ آماده‌سازی مجاز نیست."""
    _, orders, oid = confirmed_order(tmp_path)
    assert orders.set_fulfillment(oid, "preparing").fulfillment == "preparing"
    assert orders.set_fulfillment(oid, "shipped").fulfillment == "shipped"
    with pytest.raises(OrderError):
        orders.set_fulfillment(oid, "preparing")  # عقب‌گرد
    assert orders.set_fulfillment(oid, "delivered").fulfillment == "delivered"
    with pytest.raises(OrderError):
        orders.set_fulfillment(oid, "shipped")  # از تحویل هم نمی‌شه برگشت
    with pytest.raises(OrderError):
        orders.set_fulfillment(oid, "")  # پاک‌کردن فقط موقعِ آماده‌سازی مجازه


def test_fulfillment_clears_back_to_empty_while_preparing(tmp_path):
    _, orders, oid = confirmed_order(tmp_path)
    orders.set_fulfillment(oid, "preparing", tracking_code="IR-7")
    order = orders.set_fulfillment(oid, "")
    assert order.fulfillment == "" and order.tracking_code == ""  # «کلِ ماجرا» پاک می‌شه
    assert orders.set_fulfillment(oid, "preparing").fulfillment == "preparing"  # و دوباره می‌شه شروع کرد


def test_fulfillment_rejects_unknown_states(tmp_path):
    _, orders, oid = confirmed_order(tmp_path)
    with pytest.raises(OrderError, match="وضعیت"):
        orders.set_fulfillment(oid, "flying")


def test_fulfillment_requires_confirmed_status(tmp_path):
    """سفارشِ تأییدنشده وضعیتِ ارسال نمی‌گیره — مسیرِ پول دست‌نخورده می‌مونه."""
    products, orders = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 10)
    pending = orders.create("telegram", "1", [(pid, 1)])
    with pytest.raises(OrderError, match="تأییدشده"):
        orders.set_fulfillment(pending, "preparing")
    orders.mark_paid(pending, METHOD_CARD_TO_CARD)
    with pytest.raises(OrderError, match="تأییدشده"):
        orders.set_fulfillment(pending, "preparing")
    with pytest.raises(OrderError):
        orders.set_fulfillment(999, "preparing")  # سفارشِ ناموجود


def test_fulfillment_clamps_tracking_code(tmp_path):
    _, orders, oid = confirmed_order(tmp_path)
    order = orders.set_fulfillment(oid, "preparing", tracking_code="  " + "ک" * 100 + "  ")
    assert order.tracking_code == "ک" * 64  # استریپ + سقفِ ۶۴ — همان سبکِ [:96] در set_confirmed_by
    assert orders.get(oid).tracking_code == "ک" * 64


def test_fulfillment_never_touches_money_state_or_stock(tmp_path):
    """تازه‌ترینِ تضمینِ سخت: این فیلدِ تازه هیچ‌وقت به وضعیت/مبلغِ پول ربطی نداره."""
    products, orders, oid = confirmed_order(tmp_path)
    before = orders.get(oid)
    orders.set_fulfillment(oid, "preparing", tracking_code="TG-1", by="owner")
    after = orders.get(oid)
    assert after.status == before.status == "confirmed"
    assert after.total_irr == before.total_irr and after.updated_at >= before.updated_at
    assert products.get(products.list()[0].id).stock_quantity == 9  # موجودی همان‌جا که تایید کمش کرد می‌مونه


def test_fulfillment_message_for_each_state(tmp_path):
    """۷: سه وضعیتِ ارسال سه پیامِ متفاوت دارند (پیش‌تر فقط «ارسال شد» پیام می‌داد)."""
    from app.core import orders as orders_module

    products, store = make_stores(tmp_path)
    pid = products.add("کالا", 1000, 5)
    oid = store.create("telegram", "1", [(pid, 1)])
    store.mark_paid(oid, "card_to_card", "r")
    store.confirm(oid)

    preparing = store.set_fulfillment(oid, "preparing")
    assert "آماده" in orders_module.build_order_fulfillment_text(preparing)
    shipped = store.set_fulfillment(oid, "shipped", tracking_code="TG-7")
    shipped_text = orders_module.build_order_fulfillment_text(shipped)
    assert "ارسال شد" in shipped_text and "TG-7" in shipped_text
    delivered = store.set_fulfillment(oid, "delivered")
    assert "تحویل" in orders_module.build_order_fulfillment_text(delivered)
    assert orders_module.build_order_shipped_text(shipped) == shipped_text


# ------------------------------------------------- قلم ۵: بستنِ سفارشِ تأییدشده (OrderStore.close)


def test_close_moves_a_confirmed_order_out_of_the_working_state(tmp_path):
    """بستن = فقط «از لیستِ کاری بیرون». نه پولی جابه‌جا می‌شود، نه موجودی‌ای کم/زیاد می‌شود،
    نه داده‌ای پاک می‌شود؛ وضعیت به ``closed`` می‌رود (``inventory_applied`` هم دست‌نخورده می‌ماند)."""
    products, orders, oid = confirmed_order(tmp_path)
    before = orders.get(oid)
    orders.close(oid)
    after = orders.get(oid)
    assert after.status == STATUS_CLOSED
    assert after.total_irr == before.total_irr and after.inventory_applied is True
    assert products.get(products.list()[0].id).stock_quantity == 9, "بستن نباید موجودی را لمس کند"


def test_close_is_only_valid_from_confirmed(tmp_path):
    """«بسته‌شده» فقط از «تأییدشده» reachable است: هیچ سفارشِ دیگری بسته نمی‌شود و وضعیتش عوض
    نمی‌شود (پول و رزروِ آن‌ها معنا ندارد آرشیوی شود)."""
    import time

    from app.core.orders import _VALID_TRANSITIONS

    products, orders = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 10)
    expired = orders.create("telegram", "5", [(pid, 1)])
    orders.expire_stale(now=time.time() + 16 * 60)  # تنها سفارشِ موجود = همین، پس فقط این منقضی می‌شود
    pending = orders.create("telegram", "1", [(pid, 1)])
    paid = orders.create("telegram", "2", [(pid, 1)])
    orders.mark_paid(paid, METHOD_CARD_TO_CARD)
    rejected = orders.create("telegram", "3", [(pid, 1)])
    orders.mark_paid(rejected, METHOD_CARD_TO_CARD)
    orders.reject(rejected)
    cancelled = orders.create("telegram", "4", [(pid, 1)])
    orders.cancel(cancelled)

    for oid, status in ((pending, STATUS_PENDING_PAYMENT), (paid, STATUS_PAID), (rejected, STATUS_REJECTED),
                        (cancelled, STATUS_CANCELLED), (expired, STATUS_EXPIRED)):
        with pytest.raises(OrderError, match="نمی‌شه سفارش"):
            orders.close(oid, by="manager:telegram:9")
        assert orders.get(oid).status == status, "ردشدنِ بستن هیچ چیزی را عوض نمی‌کند"
    with pytest.raises(OrderError):
        orders.close(999, by="app")  # سفارشِ ناموجود
    assert _VALID_TRANSITIONS[STATUS_CONFIRMED] == {STATUS_CLOSED}, "درگاهِ بستن فقط از تأییدشده باز است"


def test_closed_order_has_no_way_back(tmp_path):
    """عمداً هیچگذارِ خروجیِ از ``closed`` تعریف نشده (پول/موجودیِ دوباره‌اعمال‌شدنی) — پس «بازکردن»
    در UI هم وجود ندارد، نه اینکه پنهان باشد."""
    from app.core.orders import _VALID_TRANSITIONS

    _, orders, oid = confirmed_order(tmp_path)
    orders.close(oid)
    assert _VALID_TRANSITIONS.get(STATUS_CLOSED, set()) == set()
    for target in (STATUS_CONFIRMED, STATUS_PAID, STATUS_REJECTED, STATUS_CANCELLED):
        with pytest.raises(OrderError, match="نمی‌شه سفارش"):
            orders._transition(oid, target)
    assert orders.get(oid).status == STATUS_CLOSED


def test_close_records_the_actor_in_the_audit_log(tmp_path, caplog):
    """ستونِ ``closed_by`` عمداً اضافه نشده (نسخه‌ی اسکیمای میخ‌کوب‌شده می‌شکست)؛ کنشگر در لاگِ
    ساختاریافته‌ی ``app.core.orders`` می‌ماند — همان قراردادی که ``set_fulfillment`` استفاده می‌کند."""
    with caplog.at_level(logging.INFO, logger="app.core.orders"):
        _, orders, oid = confirmed_order(tmp_path, chat="7")
        orders.set_fulfillment(oid, "preparing", by="app")
        caplog.clear()
        orders.close(oid, by="manager:telegram:44")
    line = next(r.getMessage() for r in caplog.records if "بسته شد" in r.getMessage())
    assert f"#{oid}" in line and "manager:telegram:44" in line


def test_closed_orders_leave_the_default_list_but_survive_the_status_filter(tmp_path):
    """``list(status=None)`` مثلِ همیشه «همه» می‌دهد (کاهشِ معنایِ آن کارِ صفحه است، نه فروشگاه)؛
    فیلترِ ``closed`` همان‌ها را جدا می‌آورد."""
    products, orders, oid = confirmed_order(tmp_path, chat="7")
    other = orders.create("telegram", "8", [(products.list()[0].id, 1)])
    orders.close(oid)
    assert {o.id for o in orders.list()} == {oid, other}
    assert [o.id for o in orders.list(status=STATUS_CLOSED)] == [oid]
    assert [o.id for o in orders.list(status=STATUS_CONFIRMED)] == []
    assert [o.id for o in orders.list(status=STATUS_CLOSED, platform="telegram")] == [oid]
