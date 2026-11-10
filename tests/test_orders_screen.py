import asyncio

import flet as ft
from fake_page import collect_text, FakePage, find, fire

from app import theme
from app.core import report_xlsx
from app.core.bot_manager import BotManagerError
from app.core.orders import METHOD_BALE_PAY, METHOD_CARD_TO_CARD, OrderStore, STATUS_PAID
from app.core.products import ProductStore
from app.core.settings import AppSettings
from app.screens import orders as orders_screen


def make_stores(tmp_path):
    products = ProductStore(db_path=tmp_path / "p.db")
    store = OrderStore(db_path=tmp_path / "o.db", product_store=products)
    return products, store


def notice(control) -> str:
    """متنِ سبزِ نتیجه، فقط وقتی واقعاً نمایش داده شده است («چیزی نرفته» نباید «رفته» خوانده شود)."""
    box = find(control, "orders_notice")
    return box.value if box.visible else ""


def failure(control) -> str:
    box = find(control, "orders_error")
    return box.value if box.visible else ""


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
    dropdown = find(control, "status_filter")
    # قلم ۵: «همه» حالا سفارش‌های بسته‌شده را ندارد، و «Closed orders» فیلترِ جدا خودش است
    assert dropdown.label == "All except closed"
    assert [o.key for o in dropdown.options][-1] == "closed"
    assert dropdown.options[-1].text == "Closed orders"


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
    store.mark_paid(oid, METHOD_BALE_PAY, "ref-1")
    control = orders_screen.build(FakePage(), "fa", store)
    assert "بعد از پایان مهلت رزرو رسید" in find(control, f"late_{oid}").value
    assert find(control, f"confirm_{oid}") is not None, "صاحب فروشگاه هنوز می‌تونه تصمیم بگیره"
    assert "بله‌پی" in collect_text(control)


def test_no_zarinpal_left_on_the_orders_page(tmp_path):
    """۱.۰.۰: زرین‌پال وجود ندارد — نه در لیست روش‌ها، نه در کارتِ تنظیماتِ بالای صفحه."""
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 5)
    oid = store.create("telegram", "1", [(pid, 1)])
    store.mark_paid(oid, METHOD_BALE_PAY)
    settings = AppSettings()
    settings.business_mode = "store"
    control = orders_screen.build(FakePage(), "fa", store, settings=settings, save_callback=lambda: None)
    assert "زرین‌پال" not in collect_text(control)
    assert find(control, "zarinpal_enabled") is None
    assert find(control, f"order_{oid}") is not None


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


def test_confirmed_order_has_no_digital_delivery_bar(tmp_path):
    """تحویلِ خودکار از مدل رفت: نه نوارِ وضعیتِ تحویل، نه دکمه‌ی «ارسالِ دوباره»."""
    products, store = make_stores(tmp_path)
    pid = products.add("کالا", 500, 4)
    oid = store.create("telegram", "1", [(pid, 1)])
    store.mark_paid(oid, METHOD_CARD_TO_CARD, "r")
    store.confirm(oid)

    class Mgr:
        def send_message_sync(self, *a, **k):
            return None

    page = FakePage()
    control = orders_screen.build(page, "fa", store, Mgr())
    assert find(control, f"delivery_{oid}") is None and find(control, f"redeliver_{oid}") is None
    assert not hasattr(Mgr, "deliver_digital_sync")
    assert "سفارش" in collect_text(control)


# ------------------------------------------------------------------ رسیدها


def test_order_without_receipt_has_no_receipt_panel(tmp_path):
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 5)
    oid = store.create("telegram", "1", [(pid, 1)])
    store.mark_paid(oid, METHOD_CARD_TO_CARD)
    control = orders_screen.build(FakePage(), "fa", store)
    assert find(control, f"receipts_{oid}") is None
    assert find(control, f"confirm_{oid}") is not None, "بدونِ رسید هم باید شد تصمیم گرفت"


def test_text_receipt_is_readable_and_trace_code_shown(tmp_path):
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 5)
    oid = store.create("telegram", "1", [(pid, 1)])
    store.mark_paid(oid, METHOD_CARD_TO_CARD)
    store.add_receipt(oid, kind="text", body="رسید بانک: 1,000 ریال\nکد پیگیری 4512309", amount_irr=1000, trace_code="4512309", match_state="amount_ok")

    control = orders_screen.build(FakePage(), "fa", store)
    assert find(control, f"receipts_{oid}") is not None
    assert "4512309" in collect_text(find(control, f"receipt_{oid}_0"))
    verdict = find(control, f"receipt_state_{oid}_0")
    assert "می‌خونه" in verdict.value and verdict.color == theme.SUCCESS
    assert find(control, f"receipt_trace_{oid}_0").value.count("4512309") == 1
    assert find(control, f"receipt_img_{oid}_0") is None, "رسیدِ متنی عکس ندارد"


def test_mismatched_receipt_shows_visible_warning(tmp_path):
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 5)
    oid = store.create("telegram", "1", [(pid, 1)])
    store.mark_paid(oid, METHOD_CARD_TO_CARD)
    store.add_receipt(oid, kind="text", body="واریز 900 ریال", amount_irr=900, trace_code="777", match_state="amount_mismatch")

    control = orders_screen.build(FakePage(), "fa", store)
    verdict = find(control, f"receipt_state_{oid}_0")
    assert verdict.color == theme.DANGER and "نمی‌خونه" in verdict.value
    assert "1,000" in verdict.value and "900" in verdict.value and "۱۰۰" not in verdict.value
    panel = collect_text(find(control, f"receipts_{oid}"))
    assert "⚠️" in panel and "قبل از تأیید" in panel, "بنرِ اختلافِ مبلغ هم روی پنل باشد"
    assert find(control, f"confirm_{oid}") is not None, "هشدار هیچ‌چیز را خودکار رد نمی‌کند"


def test_image_receipt_is_shown_from_stored_path(tmp_path):
    import flet as ft

    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 5)
    oid = store.create("telegram", "1", [(pid, 1)])
    store.mark_paid(oid, METHOD_CARD_TO_CARD)
    path = str(tmp_path / "receipts" / "shot.png")
    store.add_receipt(oid, kind="image", file_path=path, match_state="none")

    control = orders_screen.build(FakePage(), "fa", store)
    image = find(control, f"receipt_img_{oid}_0")
    assert image is not None and isinstance(image, ft.Image) and image.src == path
    assert "عکسِ رسید" in collect_text(find(control, f"receipt_{oid}_0"))


def test_newest_receipt_first_and_only_last_five_listed(tmp_path):
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 5)
    oid = store.create("telegram", "1", [(pid, 1)])
    store.mark_paid(oid, METHOD_CARD_TO_CARD)
    for i in range(7):
        store.add_receipt(oid, kind="text", body=f"رسید شماره {i}", amount_irr=1000, match_state="amount_ok")
    control = orders_screen.build(FakePage(), "fa", store)
    assert find(control, f"receipt_{oid}_4") is not None and find(control, f"receipt_{oid}_5") is None, "حداکثر پنجِ آخر"
    assert "رسید شماره 6" in find(control, f"receipt_body_{oid}_0").value, "تازه‌ترین رسید اول"


# ---------------------------------------------------- صفِ «منتظرِ بررسیِ شما»


def test_attention_section_lists_paid_orders_newest_first(tmp_path):
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 10)
    old_paid = store.create("telegram", "1", [(pid, 1)])
    store.mark_paid(old_paid, METHOD_CARD_TO_CARD)
    store.add_receipt(old_paid, kind="text", body="واریز شد", amount_irr=1000, match_state="amount_ok")
    new_paid = store.create("telegram", "2", [(pid, 1)])
    store.mark_paid(new_paid, METHOD_CARD_TO_CARD)
    store.add_receipt(new_paid, kind="text", body="کم واریز", amount_irr=500, match_state="amount_mismatch")
    store.create("telegram", "3", [(pid, 1)])  # در انتظار پرداخت — نباید در صف باشد

    control = orders_screen.build(FakePage(), "fa", store)
    box = find(control, "attention_box")
    assert box.visible is True
    assert "منتظرِ بررسیِ شما" in collect_text(box) and "2 سفارش" in find(control, "attention_summary").value
    rows = [c.key for c in find(control, "attention_rows").controls]
    assert rows[:2] == [f"attention_{new_paid}", f"attention_{old_paid}"], "تازه‌ترین اول"
    assert "attention_3" not in rows
    mismatch_line = collect_text(find(control, f"attention_{new_paid}"))
    assert "نمی‌خونه" in mismatch_line and "کارت‌به‌کارت" in mismatch_line
    ok_line = collect_text(find(control, f"attention_{old_paid}"))
    assert "می‌خونه" in ok_line


def test_attention_section_hidden_when_nothing_awaits_review(tmp_path):
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 10)
    pending = store.create("telegram", "1", [(pid, 1)])
    control = orders_screen.build(FakePage(), "fa", store)
    assert find(control, "attention_box").visible is False, "جعبه‌ی خالی بالای صفحه نشون داده نمی‌شه"
    assert find(control, f"order_{pending}") is not None


def test_attention_section_shows_missing_receipt_honestly(tmp_path):
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 10)
    card_order = store.create("telegram", "1", [(pid, 1)], customer_name="مریم")
    store.mark_paid(card_order, METHOD_CARD_TO_CARD)
    gateway_order = store.create("telegram", "2", [(pid, 1)])
    store.mark_paid(gateway_order, METHOD_BALE_PAY, payment_reference="tx-1")

    control = orders_screen.build(FakePage(), "fa", store)
    assert "رسیدی نرسیده" in collect_text(find(control, f"attention_{card_order}"))
    gateway_line = collect_text(find(control, f"attention_{gateway_order}"))
    assert "درگاه" in gateway_line and "بله‌پی" in gateway_line


def test_attention_and_list_refresh_after_confirm(tmp_path):
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 5)
    oid = store.create("telegram", "1", [(pid, 1)])
    store.mark_paid(oid, METHOD_CARD_TO_CARD)
    store.add_receipt(oid, kind="text", body="واریز 1,000", amount_irr=1000, match_state="amount_ok")
    control = orders_screen.build(FakePage(), "fa", store)
    assert find(control, "attention_box").visible is True

    fire(find(control, f"confirm_{oid}"), "on_click")
    assert find(control, "attention_box").visible is False, "بعد از تأیید، صف خالی می‌شه"
    assert find(control, f"confirm_{oid}") is None


# ------------------------------------------------------- وضعیتِ «ارسال» (مالک)


class RecorderMgr:
    """مدیر ربات جعلی: فقط ضبط می‌کند چه متنی قرار بود به کدام مشتری برود. کارت‌های تنظیماتِ
    بالای صفحه هم با `owner_console=None` و `payment_last_errors={}` بی‌مصرف رد می‌شوند."""

    owner_console = None

    def __init__(self):
        self.sent: list = []

    def send_message_sync(self, platform, chat_id, text, **kw):
        self.sent.append((platform, chat_id, text))

    def is_running(self):
        return False

    def payment_last_errors(self):
        return {}


def confirmed_order(tmp_path, chat="1"):
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 5)
    oid = store.create("telegram", chat, [(pid, 1)])
    store.mark_paid(oid, METHOD_CARD_TO_CARD)
    store.confirm(oid)
    return products, store, oid


def test_non_confirmed_order_has_no_fulfillment_controls(tmp_path):
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 5)
    oid = store.create("telegram", "1", [(pid, 1)])
    store.mark_paid(oid, METHOD_CARD_TO_CARD)
    control = orders_screen.build(FakePage(), "fa", store)
    assert find(control, f"fulfill_{oid}") is None, "وضعیتِ ارسال فقط روی سفارشِ تأییدشده"


def test_fulfillment_buttons_walk_forward(tmp_path):
    products, store, oid = confirmed_order(tmp_path)
    page = FakePage()
    control = orders_screen.build(page, "fa", store)
    assert find(control, f"fulfill_preparing_{oid}") is not None, "اولین قدم = آماده‌سازی"

    fire(find(control, f"fulfill_preparing_{oid}"), "on_click")
    assert store.get(oid).fulfillment == "preparing" and store.get(oid).status == "confirmed"
    assert find(control, f"fulfill_shipped_{oid}") is not None and find(control, f"fulfill_clear_{oid}") is not None

    fire(find(control, f"fulfill_shipped_{oid}"), "on_click")
    assert store.get(oid).fulfillment == "shipped"
    fire(find(control, f"fulfill_delivered_{oid}"), "on_click")
    assert store.get(oid).fulfillment == "delivered"
    assert "تحویل داده شد" in find(control, f"fulfill_state_{oid}").value
    assert find(control, f"fulfill_delivered_{oid}") is None, "بعد از تحویل، دکمه‌ی دیگری برای فشاردن نیست"
    assert products.get(products.list()[0].id).stock_quantity == 4, "وضعیتِ ارسال به موجودی/پول دست نمی‌زنه"


def test_tracking_field_is_saved_and_shown_in_state_line(tmp_path):
    products, store, oid = confirmed_order(tmp_path)
    page = FakePage()
    control = orders_screen.build(page, "fa", store)

    field = find(control, f"tracking_{oid}")
    field.value = "  IR-77  "
    fire(find(control, f"fulfill_preparing_{oid}"), "on_click")
    assert store.get(oid).tracking_code == "IR-77"
    assert "IR-77" in find(control, f"fulfill_state_{oid}").value

    # اصلاحِ کد بدونِ تغییرِ وضعیت (دکمه‌ی «ذخیره» همان وضعیت را دوباره ثبت می‌کند)
    find(control, f"tracking_{oid}").value = "IR-78"
    fire(find(control, f"tracking_save_{oid}"), "on_click")
    assert store.get(oid).tracking_code == "IR-78" and store.get(oid).fulfillment == "preparing"

    fire(find(control, f"fulfill_clear_{oid}"), "on_click")  # پاک‌کردنِ همه‌چیز (کد هم می‌ره)
    order = store.get(oid)
    assert order.fulfillment == "" and order.tracking_code == ""


def test_state_line_shows_jalali_updated_date(tmp_path):
    products, store, oid = confirmed_order(tmp_path)
    store.set_fulfillment(oid, "preparing")
    control = orders_screen.build(FakePage(), "fa", store)
    line = find(control, f"fulfill_state_{oid}").value
    assert "آخرین تغییر: ۱۴" in line, "تاریخِ جلالی (سال ۱۴xx) بدونِ رقمِ میلادی"


def test_every_fulfillment_change_is_sent_to_the_customer(tmp_path):
    """۷: فقط «ارسال شد» نبود — حالا هر سه وضعیت (آماده‌سازی / ارسال شد / تحویل شد) برای
    مشتری می‌رود و سوییچِ صفحه پیش‌فرض روشن است."""
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 5)
    oid = store.create("telegram", "1", [(pid, 1)])
    store.mark_paid(oid, METHOD_CARD_TO_CARD)
    store.confirm(oid)

    settings = AppSettings()
    settings.business_mode = "store"
    mgr = RecorderMgr()
    page = FakePage()
    control = orders_screen.build(page, "fa", store, mgr, settings, save_callback=lambda: None)
    assert find(control, "notify_on_fulfillment").value is True, "پیش‌فرض روشن است"

    find(control, f"tracking_{oid}").value = "TG-9"
    fire(find(control, f"fulfill_preparing_{oid}"), "on_click")
    fire(find(control, f"fulfill_shipped_{oid}"), "on_click")
    fire(find(control, f"fulfill_delivered_{oid}"), "on_click")
    assert [t for _p, _c, t in mgr.sent] and store.get(oid).fulfillment == "delivered"
    texts = [t for _p, _c, t in mgr.sent]
    assert len(texts) == 3
    assert "آماده‌سازی" in texts[0] and f"#{oid}" in texts[0]
    assert "ارسال شد" in texts[1] and "TG-9" in texts[1]
    assert "تحویل" in texts[2]

    # اصلاحِ کد رهگیری روی همان وضعیت، پیامِ دوباره نمی‌فرستد
    before = len(mgr.sent)
    fire(find(control, f"tracking_save_{oid}"), "on_click")
    assert len(mgr.sent) == before


def test_fulfillment_notifications_stop_when_the_switch_is_off(tmp_path):
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 5)
    oid = store.create("telegram", "7", [(pid, 1)])
    store.mark_paid(oid, METHOD_CARD_TO_CARD)
    store.confirm(oid)
    settings = AppSettings()
    settings.business_mode = "store"
    settings.notify_on_fulfillment = False
    mgr = RecorderMgr()
    control = orders_screen.build(FakePage(), "fa", store, mgr, settings, save_callback=lambda: None)
    fire(find(control, f"fulfill_preparing_{oid}"), "on_click")
    fire(find(control, f"fulfill_shipped_{oid}"), "on_click")
    assert store.get(oid).fulfillment == "shipped" and mgr.sent == []


def test_ship_notice_skipped_silently_without_manager(tmp_path):
    """ربات/سرویسِ متصل نیست (manager=None): تغییرِ وضعیت باید موفق بمونه، بدونِ هیچ خطا."""
    products, store, oid = confirmed_order(tmp_path)
    settings = AppSettings()
    settings.notify_on_fulfillment = True
    control = orders_screen.build(FakePage(), "fa", store, None, settings)
    fire(find(control, f"fulfill_preparing_{oid}"), "on_click")
    fire(find(control, f"fulfill_shipped_{oid}"), "on_click")
    assert store.get(oid).fulfillment == "shipped"
    assert "ثبت نشد" not in collect_text(control)


# -------------------------------------------------- کارتِ «وضعیتِ پرداخت» (فقط خواندنی)


def test_payment_status_card_shows_mismatch_loudly_and_paid_unconfirmed(tmp_path):
    """یک سفارشِ کارت‌به‌کارت با رسیدِ نامطابق (هنوز تأییدنشده = «پرداخت‌شده» در صفِ بررسی) و
    یک سفارشِ «پرداخت‌شده» بی‌رسید — هر دو باید کارتِ وضعیتِ پرداخت را نشان بدهند، بدونِ
    نوشتنِ هیچ چیزِ تازه‌ای (فقط خواندنِ همان داده‌هایی که از قبل ثبت شده)."""
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 5)

    mismatched = store.create("telegram", "1", [(pid, 1)], customer_name="مریم")
    store.mark_paid(mismatched, METHOD_CARD_TO_CARD)
    store.add_receipt(mismatched, kind="text", body="واریز 900 ریال", amount_irr=900, trace_code="777", match_state="amount_mismatch")

    no_receipt = store.create("telegram", "2", [(pid, 1)])
    store.mark_paid(no_receipt, METHOD_CARD_TO_CARD)

    control = orders_screen.build(FakePage(), "fa", store)

    card = find(control, f"paystat_{mismatched}")
    assert card is not None, "کارتِ وضعیتِ پرداخت باید روی سفارشِ پرداخت‌شده باشد"
    assert find(control, f"paystat_method_{mismatched}").value.count("کارت‌به‌کارت") == 1
    assert "1,000" in find(control, f"paystat_total_{mismatched}").value
    assert "900" in find(control, f"paystat_receipt_{mismatched}").value
    assert "777" in find(control, f"paystat_trace_{mismatched}").value
    loud = find(control, f"paystat_match_{mismatched}")
    assert loud.color == theme.DANGER and loud.weight == ft.FontWeight.W_700, "اختلاف باید بلند و قرمز گفته بشه"
    assert "نمی‌خونه" in loud.value and "100" in loud.value, "باید بگوید چقدر اختلاف است"
    assert "نمی‌خونه" in collect_text(card)

    bare = find(control, f"paystat_{no_receipt}")
    assert bare is not None and "رسیدی در دسترس نیست" in find(control, f"paystat_receipt_{no_receipt}").value
    assert find(control, f"paystat_match_{no_receipt}") is None, "بی‌رسید ⇒ خطِ تطابق نیست"
    assert find(control, f"paystat_decision_{no_receipt}") is None, "هنوز تأیید/رد نشده ⇒ خطِ تأییدکننده نیست"
    assert store.get(no_receipt).status == "paid", "این کارت هیچ‌چیز را تأیید یا تغییر نمی‌دهد"
    assert find(control, f"paystat_{no_receipt}").content.controls[0].value.startswith("💳")


def test_payment_status_card_is_read_only_for_gateway_orders(tmp_path):
    """بله‌پیِ پرداخت‌شده باید نتیجه‌ی راستی‌آزماییِ درگاه را بگوید؛ کارت هیچ مقدارِ تازه‌ای
    نمی‌نویسد و هیچ مبلغی را دوباره حساب نمی‌کند."""
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 5)
    oid = store.create("telegram", "1", [(pid, 1)])
    store.mark_paid(oid, METHOD_BALE_PAY, payment_reference="charge-1")

    control = orders_screen.build(FakePage(), "fa", store)
    assert "راستی‌آزمایی" in find(control, f"paystat_gateway_{oid}").value
    store.set_confirmed_by(oid, "owner:telegram:1")
    store.confirm(oid)
    control = orders_screen.build(FakePage(), "fa", store)
    decision = find(control, f"paystat_decision_{oid}")
    assert "owner:telegram:1" in decision.value and "آخرین تغییر: ۱۴" in decision.value, "تأییدکننده + تاریخِ جلالی"
    assert store.get(oid).status == "confirmed"  # فقط نمایش داده شد؛ چیزی عوض نشد که خودِ تست تأیید کرد


def test_pending_payment_order_without_method_has_no_payment_status_card(tmp_path):
    """سفارشِ «در انتظارِ پرداخت» که هنوز هیچ روشی انتخاب نکرده و رسیدی ندارد: کارتِ
    وضعیتِ پرداخت نباید نمایش داده شود."""
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 5)
    oid = store.create("telegram", "1", [(pid, 1)])
    control = orders_screen.build(FakePage(), "fa", store)
    assert find(control, f"paystat_{oid}") is None, "هیچ داده‌یِ پرداختی نیست؛ کارتِ خالی نشان نده"


# ------------------------------------------------- گزارشِ اکسل/PDF (بخش ۸ِ master prompt) ----

def test_excel_and_pdf_report_buttons_write_files(tmp_path, monkeypatch):
    """«خروجِ اکسل»/«خروجِ PDF» همان فهرستِ سفارش‌ها را در ``<داده>/reports`` می‌نویسند، پوشه را باز
    می‌کنند و پیامِ تایید را نشان می‌دهند — هیچ سفارشی را عوض نمی‌کنند."""
    products, store = make_stores(tmp_path)
    pid = products.add("شام‌خور", 100_000, 5)
    oid = store.create("telegram", "1", [(pid, 2)], payment_method=METHOD_CARD_TO_CARD, customer_name="علی رضایی")
    store.mark_paid(oid, METHOD_CARD_TO_CARD)
    store.confirm(oid)
    before = store.get(oid).status
    opened: list = []
    monkeypatch.setattr("app.screens.orders.open_folder", lambda p: opened.append(str(p)) or True)
    page = FakePage()
    control = orders_screen.build(page, "fa", store)
    for key, suffix in (("orders_export_xlsx", ".xlsx"), ("orders_export_pdf", ".pdf")):
        button = find(control, key)
        assert button is not None, key
        fire(button, "on_click")
        assert any(p.suffix == suffix for p in report_xlsx.reports_dir().glob("*")), key
    assert opened == [str(report_xlsx.reports_dir())] * 2 and page.run_thread_calls >= 2
    assert store.get(oid).status == before  # خروجی فقط می‌خواند
    text = collect_text(control)
    assert "سطری ساخته شد" in text and str(report_xlsx.reports_dir()) in text
    path = sorted(report_xlsx.reports_dir().glob("*.xlsx"))[-1]
    _p, _h, body = report_xlsx.read_report(path)
    assert len(body) == 1 and body[0][0] == str(oid) and body[0][2] == "200000" and body[0][1] == "تاییدشده"


def test_report_export_follows_the_status_filter(tmp_path, monkeypatch):
    """فیلترِ وضعیتِ صفحه در فایل هم اعمال می‌شود (بخش ۸: «هر بخش» با همان دیدِ کاربر)."""
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 9)
    store.create("telegram", "1", [(pid, 1)])
    monkeypatch.setattr("app.screens.orders.open_folder", lambda p: True)
    control = orders_screen.build(FakePage(), "fa", store)
    fire(find(control, "status_filter"), "on_select", "cancelled")
    before = len(list(report_xlsx.reports_dir().glob("*.xlsx")))
    fire(find(control, "orders_export_xlsx"), "on_click")
    assert len(list(report_xlsx.reports_dir().glob("*.xlsx"))) == before  # فایلی ساخته نشد
    assert report_xlsx.EMPTY_ERROR in collect_text(control)  # خطایِ فارسی، بدونِ traceback


# ============================== قلم ۵: «میزِ سفارش» — پیام/فایل/کد رهگیری/بستنِ سفارش


class DeskMgr:
    """مدیرِ جعلی با هر دو مسیرِ «سخت»: متنِ ادمین (``send_to_customer_sync``، همان قوانینِ
    صفحه‌ی گفتگوها + ثبت در تاریخچه) و فایل (``send_file_to_customer_sync``، همان مسیرِ فاکتور).
    ``fail`` هر چی باشد همان خطا بالا می‌آید و هیچ چیزی ثبت/برگشت داده نمی‌شود."""

    owner_console = None

    def __init__(self, fail=None):
        self.texts: list = []
        self.files: list = []
        self.notices: list = []  # اعلان‌هایِ خودکارِ وضعیتِ ارسال (send_message_sync)
        self.fail = fail

    def send_to_customer_sync(self, platform, chat_id, text, **kw):
        if self.fail is not None:
            raise self.fail
        self.texts.append((platform, chat_id, text))

    def send_file_to_customer_sync(self, platform, chat_id, path, caption="", **kw):
        if self.fail is not None:
            raise self.fail
        self.files.append((platform, chat_id, str(path), caption))
        return "sent"

    def send_message_sync(self, platform, chat_id, text, **kw):
        self.notices.append((platform, chat_id, text))

    def is_running(self):
        return self.fail is None

    def payment_last_errors(self):
        return {}


def stub_picker(monkeypatch, path):
    """دیالوگِ انتخاب فایلِ سیستم‌عامل در تست نیست: همان «یک فایل انتخاب شد» را جا می‌زند."""

    class Picked:
        pass

    Picked.path = str(path)

    class Picker:
        async def pick_files(self, **kw):
            return [Picked()]

    monkeypatch.setattr(orders_screen, "get_or_create_file_picker", lambda page: Picker())


def pick_and_send(control, oid, key="desk_file"):
    asyncio.run(find(control, f"{key}_{oid}").on_click(None))


def test_desk_block_is_only_on_confirmed_orders(tmp_path):
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 5)
    oid = store.create("telegram", "1", [(pid, 1)])
    store.mark_paid(oid, METHOD_CARD_TO_CARD)
    control = orders_screen.build(FakePage(), "fa", store, DeskMgr())
    assert find(control, f"desk_{oid}") is None, "«میزِ سفارش» فقط برایِ سفارشِ تأییدشده است"

    store.confirm(oid)
    control = orders_screen.build(FakePage(), "fa", store, DeskMgr())
    assert find(control, f"desk_{oid}") is not None
    for key in ("desk_msg", "desk_send", "desk_file", "desk_tracking", "desk_close"):
        assert find(control, f"{key}_{oid}") is not None, key
    assert "telegram · 1" in find(control, f"desk_target_{oid}").value, "کجا می‌رود باید پیدا باشد"
    assert find(control, f"desk_delivered_{oid}") is None, "«تحویل شد» فقط از «ارسال شد» مجاز است"


def test_desk_text_message_goes_to_this_orders_customer(tmp_path):
    products, store, oid = confirmed_order(tmp_path, chat="42")
    mgr = DeskMgr()
    control = orders_screen.build(FakePage(), "fa", store, mgr)
    find(control, f"desk_msg_{oid}").value = "  بارنامه‌ات را می‌فرستم  "
    fire(find(control, f"desk_send_{oid}"), "on_click")
    assert mgr.texts == [("telegram", "42", "بارنامه‌ات را می‌فرستم")], "پلتفرم/چتِ خودِ سفارش، بدونِ تغییرِ متن"
    assert mgr.files == [] and mgr.notices == []
    assert f"#{oid}" in notice(control) and failure(control) == ""
    assert find(control, f"desk_msg_{oid}").value == "", "بعد از ارسالِ موفق فیلد خالی می‌شود"


def test_desk_file_send_uses_the_strict_path_and_the_caption(tmp_path, monkeypatch):
    products, store, oid = confirmed_order(tmp_path, chat="42")
    doc = tmp_path / "barename.pdf"
    doc.write_bytes(b"%PDF-1.7 fake invoice")
    mgr = DeskMgr()
    control = orders_screen.build(FakePage(), "fa", store, mgr)
    stub_picker(monkeypatch, doc)
    find(control, f"desk_msg_{oid}").value = "بارنامه‌ات"
    pick_and_send(control, oid)
    assert mgr.files == [("telegram", "42", str(doc), "بارنامه‌ات")], "همان فیلد، کپشنِ فایل است"
    assert mgr.texts == [], "فایل از مسیرِ سختِ فایل می‌رود، نه پیامِ متنی"
    assert "barename.pdf" in notice(control) and failure(control) == ""


def test_desk_file_validation_stops_bad_file_before_any_send(tmp_path, monkeypatch):
    """هیچ فایلِ بی‌اعتباری «فرستاده شد» حساب نمی‌شود: نه نوعِ مجاز، نه خوانا، نه زیرِ سقفِ حجم."""
    products, store, oid = confirmed_order(tmp_path)
    exe = tmp_path / "invoice.exe"
    exe.write_bytes(b"MZ\x90\x00")
    big = tmp_path / "huge.pdf"
    with big.open("wb") as handle:
        handle.truncate(orders_screen.MAX_FILE_BYTES + 1)
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    gone = tmp_path / "gone.pdf"

    for path, pattern in ((exe, "نوعِ فایل"), (big, "مگابایت"), (empty, "پیدا نشد"), (gone, "پیدا نشد")):
        mgr = DeskMgr()
        control = orders_screen.build(FakePage(), "fa", store, mgr)
        stub_picker(monkeypatch, path)
        pick_and_send(control, oid)
        assert mgr.files == [] and mgr.texts == [], path
        assert pattern in failure(control) and notice(control) == "", path


def test_desk_send_failure_shows_the_reason_and_marks_nothing_sent(tmp_path):
    products, store, oid = confirmed_order(tmp_path, chat="42")
    cases = (
        (BotManagerError("این مشتری بلاک شده؛ اول از بلاک درش بیار."), "بلاک"),
        (BotManagerError("این مشتری ربات رو بلاک کرده یا حسابش بسته شده؛ دیگه نمی‌شه بهش پیام داد."), "بلاک کرده"),
        (BotManagerError("ربات‌ها خاموشن؛ اول از صفحه‌ی «ربات‌ها» روشنشون کن."), "خاموشن"),
        (RuntimeError("boom"), "boom"),
    )
    for exc, pattern in cases:
        mgr = DeskMgr(fail=exc)
        control = orders_screen.build(FakePage(), "fa", store, mgr)
        find(control, f"desk_msg_{oid}").value = "سلام"
        fire(find(control, f"desk_send_{oid}"), "on_click")
        assert mgr.texts == [], exc
        assert "پیام نرفت" in failure(control) and pattern in failure(control)
        assert notice(control) == "", "شکست هرگز «رفته» نشان داده نمی‌شود"
        assert find(control, f"desk_msg_{oid}").value == "سلام", "متنِ تایپ‌شده با شکست پاک نمی‌شود"


def test_desk_file_failure_shows_the_reason_and_marks_nothing_sent(tmp_path, monkeypatch):
    products, store, oid = confirmed_order(tmp_path)
    doc = tmp_path / "invoice.pdf"
    doc.write_bytes(b"%PDF-1.7")
    mgr = DeskMgr(fail=BotManagerError("ربات این پلتفرم الان روشن/وصل نیست؛ اول ربات رو روشن کن."))
    control = orders_screen.build(FakePage(), "fa", store, mgr)
    stub_picker(monkeypatch, doc)
    pick_and_send(control, oid)
    assert mgr.files == []
    assert "فایل نرفت" in failure(control) and "روشن" in failure(control)
    assert notice(control) == ""


def test_desk_without_a_working_bot_says_so_instead_of_a_silent_success(tmp_path, monkeypatch):
    """``manager=None`` (ربات اصلاً نیست) و مدیرِ ناقص (فقط ``send_message_sync`` را دارد — مثلِ
    نسخه‌ی قبلی): هر دو باید صادقانه بگویند چیزی نرفته است، نه اینکه دکمه بی‌صدا برود."""
    products, store, oid = confirmed_order(tmp_path)
    doc = tmp_path / "invoice.pdf"
    doc.write_bytes(b"%PDF-1.7")
    for mgr in (None, RecorderMgr()):
        control = orders_screen.build(FakePage(), "fa", store, mgr)
        find(control, f"desk_msg_{oid}").value = "سلام"
        fire(find(control, f"desk_send_{oid}"), "on_click")
        assert "ربات روشن/وصل نیست" in failure(control), mgr
        stub_picker(monkeypatch, doc)
        pick_and_send(control, oid)
        assert "ربات روشن/وصل نیست" in failure(control), mgr
        assert notice(control) == ""


def test_desk_tracking_quick_action_uses_the_existing_customer_text(tmp_path):
    """«فرستادنِ کد رهگیری» همان متنِ همیشگیِ ربات (``ord.tracking``) را می‌فرستد، نه متنِ تازه."""
    products, store, oid = confirmed_order(tmp_path, chat="42")
    store.set_fulfillment(oid, "preparing", tracking_code="IR-77")
    store.set_fulfillment(oid, "shipped", tracking_code="IR-77")
    mgr = DeskMgr()
    control = orders_screen.build(FakePage(), "fa", store, mgr)
    fire(find(control, f"desk_tracking_{oid}"), "on_click")
    assert mgr.texts == [("telegram", "42", "🔎 کد رهگیری: IR-77")]
    assert f"#{oid}" in notice(control) and "نرفت" not in notice(control)


def test_desk_tracking_without_a_code_refuses_honestly(tmp_path):
    products, store, oid = confirmed_order(tmp_path)
    mgr = DeskMgr()
    control = orders_screen.build(FakePage(), "fa", store, mgr)
    fire(find(control, f"desk_tracking_{oid}"), "on_click")
    assert mgr.texts == [] and mgr.notices == []
    assert "کد رهگیری ثبت نشده" in failure(control) and notice(control) == ""


def test_desk_delivered_quick_action_walks_the_existing_fulfilment_control(tmp_path):
    products, store, oid = confirmed_order(tmp_path)
    pid = products.list()[0].id
    store.set_fulfillment(oid, "preparing", tracking_code="IR-9")
    settings = AppSettings()
    settings.business_mode = "store"
    mgr = DeskMgr()
    control = orders_screen.build(FakePage(), "fa", store, mgr, settings, save_callback=lambda: None)
    assert find(control, f"desk_delivered_{oid}") is None, "پرش از «آماده‌سازی» به «تحویل» مجاز نیست"

    fire(find(control, f"fulfill_shipped_{oid}"), "on_click")
    assert find(control, f"desk_delivered_{oid}") is not None
    fire(find(control, f"desk_delivered_{oid}"), "on_click")
    order = store.get(oid)
    assert order.fulfillment == "delivered" and order.status == "confirmed"
    assert products.get(pid).stock_quantity == 4, "تحویل/بستن به موجودی دست نمی‌زند"
    assert mgr.notices and mgr.notices[-1][:2] == ("telegram", "1") and "تحویل" in mgr.notices[-1][2]
    assert mgr.notices[-1][2] != "🔎 کد رهگیری: IR-9", "دکمه‌ی تحویل همان مسیرِ اعلانِ وضعیتِ ارسال می‌رود"


def test_closing_an_order_needs_the_arm_click_then_leaves_the_working_list(tmp_path):
    products, store, oid = confirmed_order(tmp_path, chat="42")
    pid = products.list()[0].id
    before_stock, before_total = products.get(pid).stock_quantity, store.get(oid).total_irr
    mgr = DeskMgr()
    control = orders_screen.build(FakePage(), "fa", store, mgr)

    fire(find(control, f"desk_close_{oid}"), "on_click")  # کلیکِ اول فقط آماده می‌کند
    assert store.get(oid).status == "confirmed", "یک کلیک هیچ چیزی را نمی‌بندد"
    assert "مطمئنم" in find(control, f"desk_close_{oid}").content
    assert "یک بارِ دیگر" in notice(control)

    fire(find(control, f"desk_close_{oid}"), "on_click")
    assert store.get(oid).status == "closed"
    assert find(control, f"order_{oid}") is None, "سفارشِ بسته از فهرستِ پیش‌فرض بیرون می‌رود"
    assert "بسته شد" in notice(control) and failure(control) == ""
    assert products.get(pid).stock_quantity == before_stock and store.get(oid).total_irr == before_total
    assert mgr.texts == [] and mgr.files == [], "بستن خودش هیچ پیامی به مشتری نمی‌فرستد"


def test_closing_an_order_that_is_not_confirmed_is_refused_with_a_visible_reason(tmp_path):
    """مسابقه‌ی واقعی: بینِ دو کلیک، سفارش جای دیگر به «پرداخت‌شده» برمی‌گردد ⇒ ``close`` رد می‌شود،
    دلیلِ فارسیِ فروشگاه نمایش داده می‌شود و وضعیتِ واقعی بازمی‌ماند."""
    products, store, oid = confirmed_order(tmp_path)
    control = orders_screen.build(FakePage(), "fa", store, DeskMgr())
    fire(find(control, f"desk_close_{oid}"), "on_click")
    conn = store._connection()
    conn.execute("UPDATE orders SET status=? WHERE id=?", (STATUS_PAID, oid))
    conn.commit()

    fire(find(control, f"desk_close_{oid}"), "on_click")
    assert store.get(oid).status == STATUS_PAID, "ردشدنِ بستن نباید وضعیت را عوض کند"
    assert "بستنِ سفارش انجام نشد" in failure(control) and "نمی‌شه سفارش" in failure(control)
    assert notice(control) == ""
    assert find(control, f"confirm_{oid}") is not None, "کارت از نو ساخته شد و دوباره تصمیم‌پذیر است"


def test_the_arm_step_does_not_survive_a_filter_change(tmp_path):
    products, store, oid = confirmed_order(tmp_path)
    control = orders_screen.build(FakePage(), "fa", store, DeskMgr())
    fire(find(control, f"desk_close_{oid}"), "on_click")
    assert "مطمئنم" in find(control, f"desk_close_{oid}").content
    fire(find(control, "status_filter"), "on_select", value="confirmed")
    assert "مطمئنم" not in find(control, f"desk_close_{oid}").content, "آمادگیِ بستن مالِ آن نما بود"
    fire(find(control, f"desk_close_{oid}"), "on_click")
    assert store.get(oid).status == "confirmed", "کلیکِ بعدی از نو فقط آماده می‌کند"


def test_closed_orders_are_hidden_by_default_and_read_only_under_their_own_filter(tmp_path):
    products, store = make_stores(tmp_path)
    pid = products.add("محصول", 1000, 5)
    a = store.create("telegram", "1", [(pid, 1)])
    store.mark_paid(a, METHOD_CARD_TO_CARD)
    store.confirm(a)
    b = store.create("telegram", "2", [(pid, 1)])
    store.mark_paid(b, METHOD_CARD_TO_CARD)
    store.confirm(b)
    store.close(a, by="app")

    control = orders_screen.build(FakePage(), "fa", store, DeskMgr())
    assert find(control, f"order_{b}") is not None and find(control, f"order_{a}") is None

    dropdown = find(control, "status_filter")
    assert "closed" in [o.key for o in dropdown.options]
    fire(dropdown, "on_select", value="closed")
    assert find(control, f"order_{a}") is not None and find(control, f"order_{b}") is None
    text = collect_text(find(control, f"order_{a}"))
    assert "بسته‌شده" in text and "هیچ راهِ بازکردنِ خودکار" in text
    assert find(control, f"closed_note_{a}") is not None
    for key in (f"desk_{a}", f"desk_close_{a}", f"fulfill_{a}", f"confirm_{a}", f"reject_{a}"):
        assert find(control, key) is None, f"{key}: آرشیو فقط خواندنی است"
    assert store.get(a).status == "closed"

    fire(dropdown, "on_select", value="confirmed")  # معنایِ بقیه‌ی فیلترها عوض نشده
    assert find(control, f"order_{b}") is not None and find(control, f"order_{a}") is None


def test_desk_block_renders_in_english(tmp_path):
    products, store, oid = confirmed_order(tmp_path)
    control = orders_screen.build(FakePage(), "en", store, DeskMgr())
    text = collect_text(find(control, f"desk_{oid}"))
    assert "🗂 Order desk" in text and "🔒 Close the order" in text and "📎 Send a file" in text


