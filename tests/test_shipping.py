"""روش‌هایِ ارسال با هزینه: تنظیمات (پیش‌فرضِ خاموش)، مرحله‌ی انتخابِ ربات، ناورداییِ مبلغ، فاکتور/دفتر و کارتِ مالک.

سه قانونِ که همه‌ی تست‌های این فایل حولِ آن می‌چرخن:
``total = subtotal − discount + shipping``؛ تا مالک روشی نسازد هیچ مبلغی عوض نمی‌شه و هیچ سؤالی از مشتری پرسیده نمی‌شه؛
و هزینه‌ی ارسالِ هر سفارش یک snapshot است، نه یک ارجاعِ زنده به تنظیمات.
"""

import json

import pytest
from fake_page import FakePage, collect_text, fire
from fake_page import find as widget
from shop_harness import Harness, datas, labels, texts

from app.core import settings as settings_module
from app.core.discounts import KIND_FIXED, KIND_PERCENT, DiscountCode, DiscountStore
from app.core.finance import FinanceStore
from app.core.invoice_service import invoice_text
from app.core.invoices import InvoiceStore
from app.core.orders import METHOD_CARD_TO_CARD, OrderStore, order_total_irr
from app.core.products import ProductStore
from app.core.settings import AppSettings, active_shipping_methods, find_shipping_method, load_settings, normalize_shipping_methods, save_settings, shipping_cost_irr

POST = {"id": "post", "name": "پست پیشتاز", "price_irr": 120_000, "free_over_irr": 0, "active": True}


def method(**kw) -> dict:
    return {**POST, **kw}


def target(res, prefix: str):
    """اولین callback_dataِ مرحله با این پیشوند (یا None)."""
    return next((d for d in datas(res) if d.startswith(prefix)), None)


def stores(tmp_path):
    products = ProductStore(tmp_path / "products.db")
    return products, OrderStore(tmp_path / "orders.db", product_store=products)


# ============================================================== تنظیماتِ مالک ====

def test_shipping_is_off_until_the_owner_adds_a_method():
    """پیش‌فرضِ خاموش: هیچ کلیدی، هیچ روشی، هیچ سؤالی — و هیچ مبلغِ تازه‌ای."""
    s = AppSettings()
    assert s.shipping_methods == []
    assert active_shipping_methods(s) == [] and find_shipping_method(s, "post") is None


def test_normalize_repairs_rows_that_came_from_disk_or_ui():
    raw = [
        method(),
        {"id": "post", "name": "تیپاکس", "price_irr": 80_000},  # idِ تکراری
        {"name": "   "},  # بی‌نام ⇒ بی‌فایده
        {"name": "پیک", "price_irr": -700},  # مبلغِ منفی ⇒ ۰
        "یک رشته‌ی خام",  # نه dict
        {"id": "z" * 40, "name": "ک" * 80, "price_irr": "abc"},  # سرریزِ طول + متنِ بی‌معنی
    ]
    out = normalize_shipping_methods(raw)
    assert [m["id"] for m in out] == ["post", "m4", "z" * 32]
    assert [m["name"] for m in out] == ["پست پیشتاز", "پیک", "ک" * 60]
    assert [m["price_irr"] for m in out] == [120_000, 0, 0]
    assert all(set(m) == {"id", "name", "price_irr", "free_over_irr", "active"} for m in out)
    assert out[0]["active"] is True and out[0]["free_over_irr"] == 0
    assert normalize_shipping_methods("نه فهرست") == []  # ورودیِ خرابِ کلِ فیلد


def test_only_active_methods_are_selectable():
    s = AppSettings()
    s.shipping_methods = [method(), method(id="tipax", name="تیپاکس", active=False)]
    assert [m["id"] for m in active_shipping_methods(s)] == ["post"]
    assert find_shipping_method(s, "tipax") is None, "روشِ خاموش از دستِ مشتری بیرون است"
    assert find_shipping_method(s, "post")["price_irr"] == 120_000
    assert find_shipping_method(s, "") is None and find_shipping_method(s, None) is None


def test_free_over_is_measured_on_the_discounted_subtotal():
    m = method(free_over_irr=1_000_000)
    assert shipping_cost_irr(m, 999_999) == 120_000
    assert shipping_cost_irr(m, 1_000_000) == 0, "مساوی هم رایگان حساب می‌شه"
    assert shipping_cost_irr(method(), 50_000_000) == 120_000, "بی‌آستانه همیشه مبلغِ خودِ روش"


def test_methods_survive_a_settings_roundtrip():
    s = AppSettings()
    s.shipping_methods = [method(), {"name": ""}]
    save_settings(s)
    loaded = load_settings()
    assert [m["id"] for m in loaded.shipping_methods] == ["post"]
    assert loaded.shipping_methods[0]["price_irr"] == 120_000


def test_hand_edited_json_is_repaired_on_load():
    """settings.json دست‌کاری‌شده (مبلغِ منفی، idِ تکراری) هرگز مستقیم به سبد نمی‌رسه."""
    save_settings(AppSettings())
    path = settings_module._settings_path()
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["shipping_methods"] = [{"name": "پیک", "price_irr": -5, "id": "p"}, {"id": "p", "name": "تکراری"}]
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    assert load_settings().shipping_methods == [{"id": "p", "name": "پیک", "price_irr": 0, "free_over_irr": 0, "active": True}]


# ================================================================= ناورداییِ مبلغ ====

def test_total_formula_is_items_minus_discount_plus_shipping():
    assert order_total_irr(1_000_000, 200_000, 120_000) == 920_000
    assert order_total_irr(1_000_000, 0, 0) == 1_000_000
    assert order_total_irr(1_000_000, 1_000_000, 0) == 0  # تخفیفِ کامل، بدونِ ارسال


def test_an_order_without_shipping_is_exactly_like_the_previous_version(tmp_path):
    products, orders = stores(tmp_path)
    pid = products.add("کفش", 1_000_000, 5)
    order = orders.get(orders.create("telegram", "1", [(pid, 1)]))
    assert (order.subtotal_irr, order.discount_irr, order.shipping_irr, order.total_irr) == (1_000_000, 0, 0, 1_000_000)
    assert order.shipping_method == ""


def test_shipping_is_frozen_on_the_order(tmp_path):
    products, orders = stores(tmp_path)
    pid = products.add("کفش", 1_000_000, 5)
    oid = orders.create("telegram", "1", [(pid, 1)], shipping=("پست پیشتاز", 120_000))
    order = orders.get(oid)
    assert (order.shipping_method, order.shipping_irr, order.total_irr) == ("پست پیشتاز", 120_000, 1_120_000)
    assert order.subtotal_irr - order.discount_irr + order.shipping_irr == order.total_irr
    # حتی اگر مالک فردا اسمِ روش را عوض کند/کلِ روش را حذف کند، فاکتورِ همین سفارش ثابت می‌ماند
    later = AppSettings()
    later.shipping_methods = [method(id="other", name="تیپاکس")]
    assert orders.get(oid).shipping_method == "پست پیشتاز" and orders.get(oid).shipping_irr == 120_000


def test_discount_and_shipping_are_resolved_in_the_same_transaction(tmp_path):
    products, orders = stores(tmp_path)
    DiscountStore(orders).create(DiscountCode(0, "SALE10", KIND_PERCENT, 10))
    pid = products.add("کفش", 1_000_000, 5)
    oid = orders.create("telegram", "1", [(pid, 2)], discount_code="SALE10", shipping=("پست", 120_000))
    order = orders.get(oid)
    assert (order.subtotal_irr, order.discount_irr, order.shipping_irr, order.total_irr) == (2_000_000, 200_000, 120_000, 1_920_000)
    assert order.discount_code == "SALE10"


def test_a_floor_deep_discount_never_swallows_the_shipping_cost(tmp_path):
    """تخفیف تا کفِ پرداختِ مجاز می‌ره، ولی هزینه‌ی ارسال روی همانِ کف سوار می‌شه — مبلغ هیچ‌وقت منفی نمی‌شه."""
    products, orders = stores(tmp_path)
    DiscountStore(orders).create(DiscountCode(0, "HUGE", KIND_FIXED, 5_000_000))
    pid = products.add("کفش", 1_000_000, 5)
    oid = orders.create("telegram", "1", [(pid, 1)], discount_code="HUGE", shipping=("پست", 120_000))
    order = orders.get(oid)
    assert (order.subtotal_irr, order.discount_irr, order.shipping_irr, order.total_irr) == (1_000_000, 990_000, 120_000, 130_000)


def test_replacing_items_clears_shipping_and_rekeeps_the_formula(tmp_path):
    """مالک اقلامِ سفارشِ پرداخت‌نشده را عوض می‌کند: ارسالِ قبلی بی‌اعتبار است (شاید کالای فیزیکی نمانده باشد)."""
    products, orders = stores(tmp_path)
    a = products.add("کفش", 1_000_000, 5)
    b = products.add("جوراب", 100_000, 5)
    oid = orders.create("telegram", "1", [(a, 1)], shipping=("پیک", 30_000))
    orders.replace_items(oid, [(b, 2)])
    order = orders.get(oid)
    assert (order.subtotal_irr, order.discount_irr, order.shipping_method, order.shipping_irr, order.total_irr) == (200_000, 0, "", 0, 200_000)


# ====================================================== مسیرِ ربات (فروشگاهِ دکمه‌ای) ====


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


NAME_ONLY = [{
    "id": "name", "label": "نام", "prompt": "اسمت؟", "type": "text", "required": True,
    "applies_to": "all", "regex": "", "choices": [], "min_len": 2, "max_len": 50,
}]


def enable(h, *methods):
    h.settings.shipping_methods = [dict(m) for m in methods]


def to_summary_end(h, pid, qty=1, code=None):
    """سبد ← (کدِ تخفیف) ← چک‌اوت ← فرمِ پیش‌فرض (نام/موبایل/آدرس + دو اختیاری) ← «تأیید و پرداخت»."""
    h.tap(f"c:a:{pid}:{qty}:-:1")
    if code:
        h.tap("c:dc")
        h.say(code)
    h.tap("c:co")
    h.say("علی رضایی")
    h.say("۰۹۱۲۳۴۵۶۷۸۹")
    h.say("تهران، خیابان آزادی، پلاک ۱۲")
    h.tap("c:ck:s")
    h.tap("c:ck:s")
    return h.tap("c:ck:ok")


def test_with_no_method_the_checkout_is_byte_for_byte_the_old_one(h):
    pid = h.products.add("کفش", 1_000_000, 5)
    res = to_summary_end(h, pid)
    assert target(res, "c:sp:") is None, "ارسال خاموش ⇒ هیچ مرحله‌ی انتخابی نیست"
    assert "c:pm:card_to_card" in datas(res)
    assert "ارسال" not in texts(res)
    h.tap("c:pm:card_to_card")
    order = h.orders.get(h.orders.list()[0].id)
    assert (order.total_irr, order.shipping_irr, order.shipping_method) == (1_000_000, 0, "")


def test_physical_cart_asks_once_and_the_order_charges_it(h):
    enable(h, method(), method(id="tipax", name="تیپاکس", price_irr=80_000))
    pid = h.products.add("کفش", 1_000_000, 5)
    res = to_summary_end(h, pid)
    step = target(res, "c:sp:")
    assert step in ("c:sp:post", "c:sp:tipax")
    assert "روشِ ارسال" in texts(res)
    assert any("120,000" in label for label in labels(res)) and any("80,000" in label for label in labels(res))

    pay = h.tap(step)
    assert "🚚 ارسال: پست پیشتاز · 120,000" in texts(pay)
    assert target(pay, "c:ck:sh") == "c:ck:sh"

    h.tap("c:pm:card_to_card")
    order = h.orders.get(h.orders.list()[0].id)
    assert (order.shipping_method, order.shipping_irr, order.total_irr) == ("پست پیشتاز", 120_000, 1_120_000)
    assert "1,120,000" in texts(h.tap(f"c:od:{order.id}")), "مشتری در جزئیاتِ سفارش همان مبلغِ کل را می‌بیند"
    assert order.payment_method == METHOD_CARD_TO_CARD


def test_chosen_method_can_be_changed_before_the_order_exists(h):
    enable(h, method(), method(id="tipax", name="تیپاکس", price_irr=80_000))
    pid = h.products.add("کفش", 1_000_000, 5)
    res = to_summary_end(h, pid)
    assert target(res, "c:sp:")
    h.tap("c:sp:post")
    assert h.flow.sessions.get("telegram", "1").step == "pay"
    back = h.tap("c:ck:sh")
    assert target(back, "c:sp:") in ("c:sp:post", "c:sp:tipax"), "دکمه‌ی «تغییرِ روشِ ارسال» همان انتخابِ قبلی را باز می‌کند"
    changed = h.tap("c:sp:tipax")
    assert "تیپاکس · 80,000" in texts(changed)
    h.tap("c:pm:card_to_card")
    order = h.orders.get(h.orders.list()[0].id)
    assert (order.shipping_method, order.shipping_irr, order.total_irr) == ("تیپاکس", 80_000, 1_080_000)


def test_cancel_inside_the_shipping_step_makes_no_order(h):
    enable(h, method())
    pid = h.products.add("کفش", 1_000_000, 5)
    to_summary_end(h, pid)
    res = h.tap("c:sp:x")
    assert h.orders.list() == [] and h.flow.sessions.get("telegram", "1") is None
    assert texts(res)


def test_an_unlimited_stock_cart_still_pays_shipping(h):
    """«نامحدود» فقط معنیِ موجودی است؛ ارسال مثلِ هر کالای فیزیکی محاسبه می‌شود."""
    enable(h, method())
    pid = h.products.add("نان", 200_000, 0, unlimited_stock=True)
    res = to_summary_end(h, pid)
    assert target(res, "c:sp:") == "c:sp:post"
    h.tap("c:sp:post")
    h.tap("c:pm:card_to_card")
    order = h.orders.get(h.orders.list()[0].id)
    assert (order.shipping_irr, order.total_irr) == (120_000, 320_000)


def test_a_two_item_cart_asks_for_shipping_once(h):
    enable(h, method())
    first = h.products.add("کفش", 1_000_000, 5)
    second = h.products.add("جوراب", 200_000, 30)
    h.settings.checkout_fields = [dict(f) for f in NAME_ONLY]
    h.tap(f"c:a:{first}:1:-:1")
    h.tap(f"c:a:{second}:1:-:1")
    h.tap("c:co")
    h.say("علی رضایی")
    res = h.tap("c:ck:ok")
    assert target(res, "c:sp:") == "c:sp:post"


def test_free_over_is_measured_on_the_discounted_cart(h):
    enable(h, method(free_over_irr=1_000_000))
    pid = h.products.add("کفش", 1_000_000, 5)

    res = to_summary_end(h, pid)  # سبد = دقیقاً آستانه ⇒ رایگان
    assert "پست پیشتاز — 0" in labels(res)[0], "بالایِ آستانه، هزینه‌ی صفر پیشنهاد می‌شه"
    pay = h.tap("c:sp:post")
    assert "ارسال: پست پیشتاز · 0" in texts(pay), "خطِ خلاصه هم صفر می‌گوید، نه ۱۲۰٬۰۰۰"
    h.tap("c:pm:card_to_card")
    free = h.orders.get(h.orders.list()[0].id)
    assert (free.shipping_irr, free.total_irr) == (0, 1_000_000)

    # با کدِ ۱۰٪ جمعِ سبد ۹۰۰٬۰۰۰ می‌شه — زیرِ آستانه ⇒ ارسال گرفته می‌شه
    # (اولِ سفارشِ قبلی تسویه می‌شه، وگرنه چک‌اوتِ دوم به «سفارشِ پرداخت‌نشده داری» می‌خوره)
    first = h.orders.list()[0]
    h.orders.mark_paid(first.id, METHOD_CARD_TO_CARD)
    h.orders.confirm(first.id)
    h.flow.discounts.create(DiscountCode(0, "SALE10", KIND_PERCENT, 10))
    priced = to_summary_end(h, pid, code="SALE10")
    assert "پست پیشتاز — 120,000" in labels(priced)[0]
    h.tap("c:sp:post")
    h.tap("c:pm:card_to_card")
    paid = h.orders.get(h.orders.list()[0].id)
    assert (paid.subtotal_irr, paid.discount_irr, paid.shipping_irr, paid.total_irr) == (1_000_000, 100_000, 120_000, 1_020_000)


def test_a_method_deactivated_midway_stops_the_order_instead_of_guessing(h):
    enable(h, method(), method(id="tipax", name="تیپاکس", price_irr=80_000))
    pid = h.products.add("کفش", 1_000_000, 5)
    to_summary_end(h, pid)
    h.tap("c:sp:post")
    enable(h, method(active=False), method(id="tipax", name="تیپاکس", price_irr=80_000))
    res = h.tap("c:pm:card_to_card")
    assert h.orders.list() == [], "هیچ سفارشی با حدسِ هزینه ساخته نمی‌شه"
    assert "اول یک روشِ ارسال انتخاب کن" in texts(res)
    assert target(res, "c:sp:") == "c:sp:tipax", "مشتری به همان مرحله‌ی انتخاب برمی‌گرده"
    h.tap("c:sp:tipax")
    h.tap("c:pm:card_to_card")
    order = h.orders.get(h.orders.list()[0].id)
    assert (order.shipping_method, order.total_irr) == ("تیپاکس", 1_080_000)


def test_all_methods_off_means_no_shipping_question_at_all(h):
    """اگر بینِ دو مرحله همه‌ی روش‌ها خاموش شوند، سبدِ فیزیکی مثلِ نسخه‌ی پیشین پرداخت می‌شه (بدونِ مرحله‌ی ارسال)."""
    enable(h, method())
    pid = h.products.add("کفش", 1_000_000, 5)
    to_summary_end(h, pid)
    h.tap("c:sp:post")
    h.settings.shipping_methods = []
    h.tap("c:pm:card_to_card")
    order = h.orders.get(h.orders.list()[0].id)
    assert (order.shipping_irr, order.total_irr) == (0, 1_000_000)


# ============================================================== فاکتور و دفتر ====


def confirmed_with_shipping(tmp_path, **create_kw):
    products, orders = stores(tmp_path)
    pid = products.add("کفش", 1_000_000, 5)
    oid = orders.create("telegram", "1", [(pid, 1)], payment_method=METHOD_CARD_TO_CARD, shipping=("پست پیشتاز", 120_000), **create_kw)
    orders.mark_paid(oid, METHOD_CARD_TO_CARD)
    orders.confirm(oid)
    return products, orders, orders.get(oid)


def test_invoice_carries_the_shipping_line(tmp_path):
    _products, orders, order = confirmed_with_shipping(tmp_path)
    invoice = InvoiceStore(orders).issue_sale(order, AppSettings())
    assert (invoice.subtotal_irr, invoice.discount_irr, invoice.shipping_irr, invoice.total_irr) == (1_000_000, 0, 120_000, 1_120_000)
    assert invoice.subtotal_irr - invoice.discount_irr + invoice.shipping_irr == invoice.total_irr
    body = invoice_text(invoice, digits="en")
    assert "هزینه ارسال: 120,000 ریال" in body and "مبلغ نهایی: 1,120,000 ریال" in body


def test_ledger_income_equals_the_order_total(tmp_path):
    products, orders, order = confirmed_with_shipping(tmp_path)
    finance = FinanceStore(orders, products)
    assert finance.post_order(order) == 1
    rows = orders.connection().execute("SELECT auto_key, amount_irr FROM ledger_entries ORDER BY id").fetchall()
    assert [(r["auto_key"], r["amount_irr"]) for r in rows] == [("sale", 1_120_000)]
    rep = finance.report(0, 2**40)
    assert (rep.gross_sales, rep.discounts, rep.shipping_income, rep.sales_net) == (1_000_000, 0, 120_000, 1_120_000)
    assert rep.gross_sales - rep.discounts + rep.shipping_income == rep.sales_net


def test_report_and_ledger_stay_equal_when_shipping_is_free(tmp_path):
    """ارسالِ رایگان هیچ عددِ تازه‌ای به دفتر اضافه نمی‌کند — همان یک ردیفِ فروش."""
    products, orders = stores(tmp_path)
    pid = products.add("کفش", 1_000_000, 5)
    oid = orders.create("telegram", "1", [(pid, 1)], payment_method=METHOD_CARD_TO_CARD, shipping=("پست پیشتاز", 0))
    orders.mark_paid(oid, METHOD_CARD_TO_CARD)
    orders.confirm(oid)
    order = orders.get(oid)
    assert order.total_irr == 1_000_000
    finance = FinanceStore(orders, products)
    finance.post_order(order)
    rep = finance.report(0, 2**40)
    assert rep.shipping_income == 0 and rep.sales_net == 1_000_000
    assert InvoiceStore(orders).issue_sale(order, AppSettings()).shipping_irr == 0


# ============================================================ کارتِ «روش‌هایِ ارسال» ====


def make_card(settings=None, lang="fa"):
    settings = settings or AppSettings()
    saves = {"n": 0}

    def save():
        saves["n"] += 1
        settings_module.save_settings(settings)

    page = FakePage()
    from app.screens import payment_settings

    control = payment_settings.build(page, lang, settings, save, None)
    return settings, control, saves


def add_method(control, name, price="", free_over=""):
    widget(control, "ship_name").value = name
    widget(control, "ship_price").value = price
    widget(control, "ship_free_over").value = free_over
    fire(widget(control, "ship_add"), "on_click")


def test_card_is_empty_and_says_shipping_is_off():
    settings, control, saves = make_card()
    assert settings.shipping_methods == [] and saves["n"] == 0
    assert "هنوز روشی اضافه نشده" in collect_text(control)


def test_card_adds_a_method_and_persists_it():
    settings, control, saves = make_card()
    add_method(control, "پست پیشتاز", "۱۲۰۰۰۰")
    assert saves["n"] == 1
    assert [m["name"] for m in settings.shipping_methods] == ["پست پیشتاز"]
    assert settings.shipping_methods[0]["price_irr"] == 120_000, "عددِ فارسیِ فیلد درست خوانده می‌شه"
    assert "پست پیشتاز · 120,000 ریال" in collect_text(control)

    add_method(control, "تیپاکس", "80000", "1000000")
    assert len(settings.shipping_methods) == 2
    assert "رایگان بالای 1,000,000" in collect_text(control)


def test_card_refuses_an_unnamed_or_garbage_price_method():
    settings, control, saves = make_card()
    add_method(control, "  ", "120000")
    assert "اول یک نام" in collect_text(control) and settings.shipping_methods == [] and saves["n"] == 0
    add_method(control, "پست", "دویست هزار")
    assert "عددِ ریالیِ صحیح" in collect_text(control) and settings.shipping_methods == [] and saves["n"] == 0
    add_method(control, "پست", "")
    assert settings.shipping_methods[0]["price_irr"] == 0, "فیلدِ خالی = رایگان، نه عددِ حدسی"


def test_card_toggles_and_deletes_a_method():
    settings, control, _saves = make_card()
    settings.shipping_methods = [method(), method(id="tipax", name="تیپاکس", active=False)]
    control = make_card(settings)[1]
    assert "(خاموش)" in collect_text(control)
    fire(widget(control, "ship_active_post"), "on_change", False)
    assert [m["active"] for m in settings.shipping_methods] == [False, False]
    control = make_card(settings)[1]
    fire(widget(control, "ship_del_tipax"), "on_click")
    assert [m["id"] for m in settings.shipping_methods] == ["post"]
    control = make_card(settings)[1]
    assert "تیپاکس" not in collect_text(widget(control, "ship_rows"))
