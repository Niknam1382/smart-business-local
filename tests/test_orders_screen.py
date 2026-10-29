from fake_page import collect_text, FakePage, find, fire

from app.core.orders import METHOD_BALE_PAY, METHOD_CARD_TO_CARD, OrderStore
from app.core.products import ProductStore
from app.screens import orders as orders_screen


def make_stores(tmp_path):
    products = ProductStore(db_path=tmp_path / "p.db")
    store = OrderStore(db_path=tmp_path / "o.db", product_store=products)
    return products, store


def test_build_empty_no_crash(tmp_path):
    _, store = make_stores(tmp_path)
    page = FakePage()
    control = orders_screen.build(page, "fa", store)
    assert control is not None


def test_pending_order_has_no_confirm_reject_buttons(tmp_path):
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 5)
    oid = store.create("telegram", "1", [(pid, 1)])
    page = FakePage()
    control = orders_screen.build(page, "fa", store)
    assert find(control, f"order_{oid}") is not None
    assert find(control, f"confirm_{oid}") is None
    assert find(control, f"reject_{oid}") is None


def test_paid_order_shows_confirm_and_reject(tmp_path):
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 5)
    oid = store.create("telegram", "1", [(pid, 2)])
    store.mark_paid(oid, METHOD_BALE_PAY, payment_reference="ref-1")
    page = FakePage()
    control = orders_screen.build(page, "fa", store)
    assert find(control, f"confirm_{oid}") is not None
    assert find(control, f"reject_{oid}") is not None


def test_confirm_button_deducts_stock_and_updates_view(tmp_path):
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 5)
    oid = store.create("telegram", "1", [(pid, 2)])
    store.mark_paid(oid, METHOD_CARD_TO_CARD)
    page = FakePage()
    control = orders_screen.build(page, "fa", store)

    fire(find(control, f"confirm_{oid}"), "on_click")
    assert store.get(oid).status == "confirmed"
    assert products.get(pid).stock_quantity == 3
    assert find(control, f"confirm_{oid}") is None, "بعد از تایید دیگه دکمه نباید باشه"


def test_reject_button_leaves_stock_untouched(tmp_path):
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 5)
    oid = store.create("telegram", "1", [(pid, 2)])
    store.mark_paid(oid, METHOD_BALE_PAY)
    page = FakePage()
    control = orders_screen.build(page, "fa", store)

    fire(find(control, f"reject_{oid}"), "on_click")
    assert store.get(oid).status == "rejected"
    assert products.get(pid).stock_quantity == 5


def test_confirm_failure_shows_persian_error(tmp_path):
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 2)
    o1 = store.create("telegram", "1", [(pid, 1)])
    o2 = store.create("telegram", "2", [(pid, 1)])
    store.mark_paid(o1, METHOD_BALE_PAY)
    store.mark_paid(o2, METHOD_BALE_PAY)
    products.adjust_stock(pid, -1)  # یکی بیرون از برنامه فروخته رفت
    page = FakePage()
    control = orders_screen.build(page, "fa", store)

    fire(find(control, f"confirm_{o1}"), "on_click")
    fire(find(control, f"confirm_{o2}"), "on_click")  # موجودی دیگه کافی نیست
    assert store.get(o1).status == "confirmed"
    assert store.get(o2).status == "paid"  # ناموفق موند
    assert "تایید نشد" in collect_text(control)


def test_filter_by_status(tmp_path):
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 10)
    pending = store.create("telegram", "1", [(pid, 1)])
    paid = store.create("telegram", "2", [(pid, 1)])
    store.mark_paid(paid, METHOD_BALE_PAY)

    page = FakePage()
    control = orders_screen.build(page, "fa", store)
    assert find(control, f"order_{pending}") is not None and find(control, f"order_{paid}") is not None

    fire(find(control, "status_filter"), "on_select", value="paid")
    assert find(control, f"order_{paid}") is not None
    assert find(control, f"order_{pending}") is None


def test_builds_in_english(tmp_path):
    _, store = make_stores(tmp_path)
    page = FakePage()
    control = orders_screen.build(page, "en", store)
    assert find(control, "status_filter").label == "All"


# ------------------------------------------------ رزرو، انقضا، پرداخت دیررس، مشخصات تحویل


def test_pending_order_shows_remaining_hold_time_and_customer_details(tmp_path):
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 5)
    oid = store.create("telegram", "1", [(pid, 1)], customer_name="مریم", customer_phone="09121234567", customer_address="تهران، ولیعصر")
    control = orders_screen.build(FakePage(), "fa", store)
    assert "دقیقه از رزرو موجودی مونده" in find(control, f"reserve_{oid}").value
    assert find(control, f"customer_{oid}").value == "مریم · 09121234567 · تهران، ولیعصر"


def test_expired_order_is_listed_with_its_status_and_filterable(tmp_path):
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 5)
    oid = store.create("telegram", "1", [(pid, 1)])
    other = store.create("telegram", "2", [(pid, 1)])
    import time

    store.expire_stale(now=time.time() + 16 * 60)
    store.mark_paid(other, METHOD_CARD_TO_CARD)  # بعد از انقضا پرداخت شد (دیررس)
    page = FakePage()
    control = orders_screen.build(page, "fa", store)
    text = collect_text(control)
    assert "منقضی‌شده" in text and find(control, f"reserve_{oid}") is None, "منقضی‌شده شمارش معکوس نداره"
    dropdown = find(control, "status_filter")
    assert "expired" in [o.key for o in dropdown.options]
    fire(dropdown, "on_select" if hasattr(dropdown, "on_select") and dropdown.on_select else "on_change", value="expired")
    assert find(control, f"order_{oid}") is not None and find(control, f"order_{other}") is None


def test_late_paid_order_shows_warning_to_owner(tmp_path):
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 5)
    oid = store.create("telegram", "1", [(pid, 1)])
    import time

    store.expire_stale(now=time.time() + 16 * 60)
    store.mark_paid(oid, "zarinpal", "ref-1")
    control = orders_screen.build(FakePage(), "fa", store)
    assert "بعد از پایان مهلت رزرو رسید" in find(control, f"late_{oid}").value
    assert find(control, f"confirm_{oid}") is not None, "صاحب فروشگاه هنوز می‌تونه تصمیم بگیره"
    assert "زرین‌پال" in collect_text(control)


def test_checkout_extra_fields_and_owner_text_show_all_answers(tmp_path):
    from app.core.owner_console import order_details, set_label_provider

    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 5)
    oid = store.create(
        "telegram", "1", [(pid, 1)], customer_name="مریم", customer_phone="09121234567", customer_address="شیراز",
        customer_info={"name": "مریم", "phone": "09121234567", "address": "شیراز", "postal": "1234567890", "city": "شیراز", "gift": "کارت تبریک"},
    )
    set_label_provider(lambda: {"city": "شهر", "gift": "پیامِ هدیه"})
    try:
        text = order_details(store.get(oid))
        assert "کدپستی: 1234567890" in text and "پیامِ هدیه: کارت تبریک" in text
        assert text.count("شیراز") == 2  # آدرس + «شهر»؛ فیلدهای تکراری (نام/موبایل/آدرس) دوباره نمایش داده نمی‌شن
        control = orders_screen.build(FakePage(), "fa", store)
        assert "پیامِ هدیه: کارت تبریک" in collect_text(find(control, f"extra_{oid}"))
    finally:
        set_label_provider(None)


def test_confirmed_digital_order_shows_delivery_status_and_redeliver(tmp_path):
    products, store = make_stores(tmp_path)
    pid = products.add("دوره", 500, product_type="digital", delivery_kind="link", delivery_payload="https://x.example")
    oid = store.create("telegram", "1", [(pid, 1)])
    store.mark_paid(oid, METHOD_CARD_TO_CARD, "r")
    store.confirm(oid)
    calls = []

    class Mgr:
        def deliver_digital_sync(self, order_id):
            calls.append(order_id)
            store.mark_delivered(order_id)
            return "delivered"

        def send_message_sync(self, *a, **k):
            return None

    page = FakePage()
    control = orders_screen.build(page, "fa", store, Mgr())
    assert "هنوز نرسیده" in collect_text(find(control, f"delivery_{oid}"))
    fire(find(control, f"redeliver_{oid}"), "on_click")
    assert calls == [oid] and "ارسال شد" in collect_text(find(control, f"delivery_{oid}")) and find(control, f"redeliver_{oid}") is None
    physical = products.add("کالا", 100, 5)
    po = store.create("telegram", "2", [(physical, 1)])
    store.mark_paid(po, METHOD_CARD_TO_CARD, "r"); store.confirm(po)
    assert find(orders_screen.build(page, "fa", store, Mgr()), f"delivery_{po}") is None  # سفارشِ فیزیکی: بدونِ نوارِ تحویل
