"""R1 — فروشگاهِ دکمه‌ای: کاتالوگ، سبد، چک‌اوت، پرداخت، پیگیری (بدونِ پلتفرم)."""

import pytest

from app.core.orders import STATUS_CANCELLED, STATUS_PAID, STATUS_PENDING_PAYMENT
from tests.shop_harness import Harness, datas, find, labels, texts


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


def add_products(h, n, **kw):
    return [h.products.add(f"کالا {i + 1}", 1000 * (i + 1), 5, **kw) for i in range(n)]


def test_catalog_pagination_boundaries(h):
    add_products(h, 13)
    h.settings.catalog_page_size = 6
    p1 = h.tap("c:l:-:1")
    assert sum(1 for d in datas(p1) if d.startswith("c:p:")) == 6
    assert "c:l:-:2" in datas(p1) and not any(d == "c:l:-:0" for d in datas(p1))
    assert p1.messages[0].edit is True
    p3 = h.tap("c:l:-:3")
    assert sum(1 for d in datas(p3) if d.startswith("c:p:")) == 1
    assert "c:l:-:2" in datas(p3) and "c:l:-:4" not in datas(p3)
    assert "3/3" in labels(p3)
    assert h.tap("c:l:-:99").messages[0].rows[-2][1].label == "3/3"  # صفحه‌ی بیرون از محدوده به آخر کلمپ می‌شه
    assert "1/3" in labels(h.tap("c:l:-:0"))


def test_page_size_is_clamped_and_all_callback_data_within_64_bytes(h):
    add_products(h, 30)
    h.settings.catalog_page_size = 500
    res = h.tap("c:l:-:1")
    assert sum(1 for d in datas(res) if d.startswith("c:p:")) == 12
    for d in datas(res):
        assert len(d.encode()) <= 64


def test_products_menu_text_and_empty_catalog(h):
    res = h.say("🛍 محصولات")
    assert res.consumed and "محصولی" in texts(res)
    add_products(h, 2)
    assert find(h.say("🛍 محصولات"), "c:p:")


def test_cart_add_is_idempotent_and_set_semantics(h):
    [pid] = add_products(h, 1)
    h.tap(f"c:a:{pid}:3:-:1")
    h.tap(f"c:a:{pid}:3:-:1")  # دابل‌تپ
    assert h.flow.carts.get("telegram", "1") == [(pid, 3)]
    h.tap(f"c:s:{pid}:4")
    h.tap(f"c:s:{pid}:4")
    assert h.flow.carts.quantity("telegram", "1", pid) == 4
    h.tap(f"c:s:{pid}:0")
    assert h.flow.carts.get("telegram", "1") == []
    h.tap(f"c:a:{pid}:2:-:1")
    confirm = h.tap("c:cl")
    assert "c:cl:y" in datas(confirm) and h.flow.carts.count("telegram", "1") == 2  # بدونِ تأیید خالی نمی‌شه
    h.tap("c:cl:y")
    h.tap("c:cl:y")
    assert h.flow.carts.count("telegram", "1") == 0


def test_quantity_is_capped_by_available_and_per_item_limit(h):
    pid = h.products.add("محدود", 1000, 3)
    h.tap(f"c:a:{pid}:50:-:1")
    assert h.flow.carts.quantity("telegram", "1", pid) == 3
    big = h.products.add("زیاد", 1000, 100)
    h.settings.max_qty_per_item = 4
    h.tap(f"c:a:{big}:50:-:1")
    assert h.flow.carts.quantity("telegram", "1", big) == 4


def test_qty_buttons_edit_keyboard_only(h):
    [pid] = add_products(h, 1)
    res = h.tap(f"c:p:{pid}:-:1")
    assert f"c:q:{pid}:2:-:1" in datas(res)
    res = h.tap(f"c:q:{pid}:2:-:1")
    m = res.messages[0]
    assert m.keyboard_only and m.edit
    assert f"c:a:{pid}:2:-:1" in datas(res)


@pytest.mark.parametrize("data", ["x", "c", "c:", "c:zzz", "c:p", "c:p:abc:-:1", "c:l:-:x", "c:q:1", "c:a:1:2", "c:ck:", "c:od:abc", "c:ck:p:99", "z:1:2", "c:cl:" + "y" * 10])
def test_garbage_callbacks_never_raise(h, data):
    res = h.tap(data)
    assert res.messages, data  # همیشه یه پاسخ/منو برمی‌گرده


def test_unknown_product_or_order_callback_is_friendly(h):
    assert "دیگه" in h.tap("c:p:999:-:1").answer
    assert h.tap("c:od:999").answer  # سفارشِ ناموجود/متعلق به دیگری → stale
    assert h.tap("c:a:999:1:-:1").answer


def test_product_sold_out_between_clicks_gives_clean_message(h):
    [pid] = add_products(h, 2)[:1]
    h.tap(f"c:p:{pid}:-:1")
    h.products.set_active(pid, False)
    res = h.tap(f"c:a:{pid}:1:-:1")
    assert "دیگه موجود نیست" in res.answer and h.flow.carts.count("telegram", "1") == 0
    assert res.messages and "c:cart" in datas(res)


def test_cart_warns_and_fix_repairs(h):
    a = h.products.add("الف", 1000, 5)
    b = h.products.add("ب", 1000, 5)
    h.tap(f"c:a:{a}:4:-:1")
    h.tap(f"c:a:{b}:2:-:1")
    h.products.adjust_stock(a, -3)  # فقط ۲ تا مونده
    h.products.set_active(b, False)
    cart = h.tap("c:cart")
    assert "فقط 2" in texts(cart) and "دیگه موجود نیست" in texts(cart) and "c:fix" in datas(cart)
    h.tap("c:fix")
    assert h.flow.carts.get("telegram", "1") == [(a, 2)]


def start_checkout(h, pid, qty=1):
    h.tap(f"c:a:{pid}:{qty}:-:1")
    return h.tap("c:co")


def answer_all(h, name="علی رضایی", phone="۰۹۱۲۳۴۵۶۷۸۹", address="تهران، خیابان آزادی، پلاک ۱۲"):
    h.say(name)
    h.say(phone)
    return h.say(address)


def test_physical_checkout_wizard_end_to_end(h):
    [pid] = add_products(h, 1)
    res = start_checkout(h, pid, 2)
    assert "نام" in texts(res) and "c:ck:x" in datas(res) and "c:ck:s" not in datas(res)
    bad = h.say("0")  # نامِ خیلی کوتاه
    assert "⚠️" in texts(bad)
    h.say("علی رضایی")
    bad = h.say("12345")
    assert "موبایل" in texts(bad)
    res = h.say("۰۹۱۲۳۴۵۶۷۸۹")
    assert "آدرس" in texts(res)
    res = h.say("تهران، خیابان آزادی، پلاک ۱۲")
    assert "کدپستی" in texts(res) and "c:ck:s" in datas(res)  # فیلدِ اختیاری
    res = h.tap("c:ck:s")  # رد کردنِ کدپستی
    res = h.tap("c:ck:s")  # رد کردنِ توضیحات → خلاصه
    assert "خلاصه" in texts(res) and "09123456789" in texts(res) and "c:ck:ok" in datas(res)
    res = h.tap("c:ck:ok")
    assert "c:pm:card_to_card" in datas(res)
    res = h.tap("c:pm:card_to_card")
    order = h.orders.list()[0]
    assert order.status == STATUS_PENDING_PAYMENT and order.total_irr == 2000
    assert order.customer_name == "علی رضایی" and order.customer_phone == "09123456789" and "پلاک" in order.customer_address
    assert order.customer_info["phone"] == "09123456789" and order.payment_method == "card_to_card"
    assert "6037991234567890" in texts(res) and f"c:paid:{order.id}" in datas(res)
    assert h.flow.carts.count("telegram", "1") == 0 and h.flow.sessions.get("telegram", "1") is None


def test_double_tap_on_pay_method_creates_one_order(h):
    [pid] = add_products(h, 1)
    start_checkout(h, pid)
    answer_all(h)
    h.tap("c:ck:s"); h.tap("c:ck:s"); h.tap("c:ck:ok")
    h.tap("c:pm:card_to_card")
    again = h.tap("c:pm:card_to_card")
    assert len(h.orders.list()) == 1
    assert "جریان نیست" in texts(again)


def test_digital_only_cart_skips_address_and_mixed_cart_asks_union(tmp_path):
    digital = Harness(tmp_path / "d")
    d = digital.products.add("دوره", 500, product_type="digital", delivery_kind="link", delivery_payload="https://x.example")
    digital.tap(f"c:a:{d}:1:-:1")
    digital.tap("c:co")
    assert digital.flow.sessions.get("telegram", "1").data["fields"] == ["name", "phone", "notes"]  # بدونِ آدرس/کدپستی
    digital.say("مریم")
    assert "(3/3)" in texts(digital.say("09121234567"))

    mixed = Harness(tmp_path / "m")
    d2 = mixed.products.add("دوره", 500, product_type="digital", delivery_kind="link", delivery_payload="https://x.example")
    p2 = mixed.products.add("کالا", 700, 5)
    mixed.tap(f"c:a:{d2}:1:-:1")
    mixed.tap(f"c:a:{p2}:1:-:1")
    mixed.tap("c:co")
    assert mixed.flow.sessions.get("telegram", "1").data["fields"] == ["name", "phone", "address", "postal", "notes"]


def test_back_skip_cancel_and_resume_after_restart(h):
    [pid] = add_products(h, 1)
    start_checkout(h, pid)
    h.say("علی رضایی")
    res = h.tap("c:ck:b")
    assert "نام" in texts(res)
    h.say("علی رضایی")
    flow2 = h.new_flow()  # ری‌استارتِ ربات
    h.flow = flow2
    res = h.say("09123456789")  # همون مرحله‌ی «موبایل» ادامه پیدا می‌کنه
    assert "آدرس" in texts(res)
    res = h.tap("c:ck:x")
    assert "لغو" in texts(res) and h.flow.sessions.get("telegram", "1") is None
    assert h.flow.carts.count("telegram", "1") == 1  # سبد سر جاشه
    assert h.tap("c:ck:ok").answer  # بدونِ نشست: پیامِ تمیز


def test_menu_tap_inside_wizard_asks_to_continue_or_cancel(h):
    [pid] = add_products(h, 1)
    start_checkout(h, pid)
    res = h.say("🧺 سبد خرید (1)")
    assert "c:ck:r" in datas(res) and "c:ck:x" in datas(res)
    res = h.tap("c:ck:r")
    assert "نام" in texts(res)


def test_free_text_outside_wizard_goes_to_ai(h):
    res = h.say("قیمت ارسال چنده؟")
    assert res.consumed is False
    assert h.say("سلام").consumed is False


def test_choice_field_and_regex_field_validation(h):
    h.settings.checkout_fields = [
        {"id": "name", "label": "نام", "prompt": "نام؟", "type": "text", "required": True},
        {"id": "city", "label": "شهر", "prompt": "شهر؟", "type": "choice", "choices": ["تهران", "شیراز"], "required": True},
        {"id": "code", "label": "کد", "prompt": "کد؟", "type": "text", "regex": r"^[A-Z]{3}\d{2}$", "required": True},
    ]
    [pid] = add_products(h, 1)
    start_checkout(h, pid)
    h.say("علی")
    res = h.say("اصفهان")
    assert "⚠️" in texts(res)
    h.tap("c:ck:p:1")
    assert "⚠️" in texts(h.say("abc"))
    res = h.say("ABC12")
    assert "شیراز" in texts(res) and "ABC12" in texts(res)


def test_no_payment_method_blocks_checkout(tmp_path):
    h = Harness(tmp_path, card=False)
    [pid] = add_products(h, 1)
    res = start_checkout(h, pid)
    assert "روش پرداختی" in texts(res) and h.flow.sessions.get("telegram", "1") is None


def test_existing_pending_order_blocks_second_checkout(h):
    [pid] = add_products(h, 1)
    oid = h.orders.create("telegram", "1", [(pid, 1)])
    h.tap(f"c:a:{pid}:1:-:1")
    res = h.tap("c:co")
    assert f"#{oid}" in texts(res) and h.flow.sessions.get("telegram", "1") is None


def test_card_claim_marks_paid_alerts_owner_and_saves_reference(h):
    [pid] = add_products(h, 1)
    start_checkout(h, pid)
    answer_all(h); h.tap("c:ck:s"); h.tap("c:ck:s"); h.tap("c:ck:ok"); h.tap("c:pm:card_to_card")
    oid = h.orders.list()[0].id
    res = h.tap(f"c:paid:{oid}")
    assert h.orders.get(oid).status == STATUS_PAID and h.owner_alerts and f"/confirm {oid}" in h.owner_alerts[-1]
    assert "منتظر" in texts(res)
    res = h.say("پیگیری 123456")
    assert h.orders.get(oid).payment_reference == "پیگیری 123456" and "ثبت شد" in texts(res)
    assert h.say("سلام دوباره").consumed is False  # نشستِ مرجع تمام شد
    assert h.tap(f"c:paid:{oid}").answer  # دوباره زدن بی‌خطره


def test_tracking_cancel_and_ownership(h):
    [pid] = add_products(h, 1)
    oid = h.orders.create("telegram", "1", [(pid, 2)])
    h.orders.set_payment_info(oid, "card_to_card")
    lst = h.say("📦 پیگیری سفارش")
    assert f"c:od:{oid}" in datas(lst)
    detail = h.tap(f"c:od:{oid}")
    assert f"c:oc:{oid}" in datas(detail) and "در انتظار پرداخت" in texts(detail) and "دقیقه" in texts(detail)
    assert f"c:oc:{oid}:y" in datas(h.tap(f"c:oc:{oid}"))
    assert h.orders.get(oid).status == STATUS_PENDING_PAYMENT
    h.tap(f"c:oc:{oid}:y")
    assert h.orders.get(oid).status == STATUS_CANCELLED
    assert "قابل‌لغو نیست" in h.tap(f"c:oc:{oid}:y").answer
    assert h.tap(f"c:od:{oid}", chat="2").answer  # مالکِ دیگه: stale، نه نشتِ اطلاعات
    assert "سفارشی نداری" in texts(h.say("📦 پیگیری سفارش", chat="2"))


def test_unavailable_stock_at_final_step_is_handled(h):
    [pid] = add_products(h, 1)
    start_checkout(h, pid, 3)
    answer_all(h); h.tap("c:ck:s"); h.tap("c:ck:s")
    h.products.adjust_stock(pid, -4)  # بینِ دو کلیک تموم شد
    res = h.tap("c:ck:ok")
    assert "⚠️" in texts(res) and h.orders.list() == [] and h.flow.sessions.get("telegram", "1") is None


def test_welcome_menu_rows_and_cart_counter(h):
    res = h.say("/start")
    menu = res.messages[0].menu
    assert menu[0][0] == "🛍 محصولات" and menu[1] == ["📦 سفارش‌هام", "ℹ️ راهنما"]  # ۱.۱ (N5): «نهایی کردن» داخلِ سبد است
    [pid] = add_products(h, 1)
    h.tap(f"c:a:{pid}:2:-:1")
    assert h.say("/menu").messages[0].menu[0][1] == "🧺 سبد خرید (2)"
    assert h.say("🧺 سبد خرید (2)").consumed  # برچسبِ شمارنده‌دار هم تشخیص داده می‌شه


def test_english_labels_and_texts(h):
    h.settings.bot_language = "en"
    [pid] = add_products(h, 1)
    assert h.say("/start").messages[0].menu[0][0] == "🛍 Products"
    assert "Your cart is empty" in texts(h.say("🧺 Cart"))
    assert h.say("🛍 محصولات").consumed  # برچسبِ زبانِ دیگه هم کار می‌کنه


def test_payment_instruction_failure_is_friendly_and_lands_in_attention_inbox(h, tmp_path):
    from app.core.attention import AttentionInbox
    from app.core.conversations import ConversationStore
    from app.core.payments import PaymentError

    h.flow.attention = AttentionInbox(ConversationStore(tmp_path / "c.db"))

    async def boom(*_a, **_k):
        raise PaymentError("روش پرداخت دیگه‌ای پیشنهاد بده (متنِ مخصوصِ مدل)")

    h.payments.build_instruction = boom
    [pid] = add_products(h, 1)
    start_checkout(h, pid)
    answer_all(h); h.tap("c:ck:s"); h.tap("c:ck:s"); h.tap("c:ck:ok")
    res = h.tap("c:pm:card_to_card")
    assert "ثبت شده" in texts(res) and "مخصوصِ مدل" not in texts(res)  # متنِ خطای مخصوصِ مدل هرگز به مشتری نمی‌رسه
    [item] = h.flow.attention.list_open()
    assert item.type == "payment_failed" and item.ref == str(h.orders.list()[0].id)
