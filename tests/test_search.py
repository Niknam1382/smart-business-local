"""A2 — جست‌وجوی سراسری: ناوردایی‌هایِ هسته (سفارش با شماره/نامِ مشتری/نامِ کالا + لبه‌ها) و صفحه‌ی FakePage."""

import pytest
from fake_page import FakePage, collect_text, find, fire

from app.core.bot_pipeline import IncomingMessage
from app.core.conversations import ConversationStore
from app.core.customers import CustomerStore
from app.core.orders import OrderStore
from app.core.products import ProductStore
from app.core.search import count, describe_order, describe_product, global_search
from app.screens import search as search_screen


@pytest.fixture
def stores(tmp_path):
    products = ProductStore(tmp_path / "p.db")
    orders = OrderStore(tmp_path / "o.db", product_store=products)
    headphone = products.add("هدفون بی‌سیم", 900_000, 5, category="صوتی")
    mouse = products.add("موس گیمینگ", 450_000, 3, category="لوازم")
    orders.create("telegram", "11", [(headphone, 2)], payment_method="card_to_card", customer_name="علی رضایی")
    orders.create("telegram", "22", [(mouse, 1)], payment_method="card_to_card", customer_name="مریم کاظمی")
    return products, orders


def test_search_matches_order_number_customer_and_product(stores):
    products, orders = stores
    assert any(o.id == 2 for o in global_search("2", orders=orders)["orders"])  # «۲» به‌عنوانِ شماره
    assert [o.chat_id for o in global_search("مریم", orders=orders)["orders"]] == ["22"]
    assert [p.name for p in products.search("هدفون")] == ["هدفون بی‌سیم"]
    # نامِ کالا در سبدِ سفارش هم جست‌وجو می‌شود (snapshot)، نه فقط در کاتالوگ
    assert any(o.id == 1 for o in global_search("هدفون", orders=orders)["orders"])


def test_search_edges_are_empty_not_wildcard(stores):
    products, orders = stores
    assert global_search("", orders=orders)["orders"] == []
    assert global_search("   ", orders=orders, products=products) == {"orders": [], "products": [], "customers": []}
    assert count(global_search("چیزی‌که‌نیست", orders=orders, products=products)) == 0
    # کاراکترهایِ خودِ LIKE باید مثلِ متنِ واقعی رفتار کنند، نه مثلِ «هرچیز»
    assert count(global_search("%", orders=orders, products=products)) == 0
    assert count(global_search("_", orders=orders, products=products)) == 0
    assert len(global_search("ی", orders=orders, limit=1)["orders"]) <= 1


def test_describe_lines_are_single_lines(stores):
    products, orders = stores
    line = describe_order(orders.search("مریم")[0], "۴۵۰٬۰۰۰ ریال")
    assert line.startswith("#") and "مریم کاظمی" in line and "\n" not in line
    assert describe_product(products.search("موس")[0], "۴۵۰٬۰۰۰ ریال").startswith("موس گیمینگ")
    # برچسبِ محلیِ وضعیت جایش را می‌گیرد تا مالع «pending_paymentِ» خام نبیند
    labelled = describe_order(orders.search("مریم")[0], "۴۵۰٬۰۰۰ ریال", "منتظر پرداخت")
    assert "منتظر پرداخت" in labelled and "pending_payment" not in labelled


# ================================================================ صفحه (FakePage) ====


@pytest.fixture
def ui_env(tmp_path):
    """سه گروهِ پُر با یک واژه: کالا، سفارش و مشتری همه «موس» را دارند."""
    products = ProductStore(tmp_path / "p.db")
    orders = OrderStore(tmp_path / "o.db", product_store=products)
    crm = CustomerStore(ConversationStore(tmp_path / "c.db"), orders)
    mouse = products.add("موس گیمینگ", 450_000, 3, category="لوازم")
    oid = orders.create("telegram", "77", [(mouse, 1)], customer_name="حسین موسوی")
    crm.touch(IncomingMessage(platform="telegram", chat_id="77", display_name="", text="سلام", first_name="حسین", last_name="موسوی"))
    return products, orders, crm, oid


def search_for(control, term):
    fire(find(control, "gs_field"), "on_change", term)
    fire(find(control, "gs_run"), "on_click")
    return collect_text(find(control, "gs_results"))


def test_search_screen_shows_three_groups_and_links_each_one(ui_env):
    products, orders, crm, oid = ui_env
    opened = []
    page = FakePage()
    control = search_screen.build(page, "fa", orders=orders, products=products, customers=crm, on_open=lambda key: opened.append(key))
    assert "چیزی بنویس" in collect_text(control), "پیش از جست‌وجو راهنما می‌آید، نه نتیجه"
    assert find(control, "gs_count").value == ""

    body = search_for(control, "موس")
    for group in ("سفارش‌ها", "کالاها", "مشتریان"):
        assert group in body, group
    assert f"#{oid}" in body and "منتظر پرداخت" in body and "450,000" in body
    assert "حسین موسوی" in body and find(control, "gs_count").value.startswith("3")

    for key, target in (("gs_open_orders", "orders"), ("gs_open_products", "products"), ("gs_open_customers", "customers")):
        button = find(control, key)
        assert button is not None, key
        fire(button, "on_click")
        assert opened[-1] == target
    assert opened == ["orders", "products", "customers"]
    assert page.update_count > 0

    # صفحه فقط می‌خواند: هیچ مبلغی و هیچ وضعیتی عوض نشده است
    order = orders.get(oid)
    assert order.status == "pending_payment" and order.total_irr == 450_000
    assert crm.get("telegram", "77").display_name == "حسین موسوی"


def test_search_screen_without_a_handler_and_in_english(ui_env):
    products, orders, crm, _oid = ui_env
    control = search_screen.build(FakePage(), "en", orders=orders, products=products, customers=crm)
    body = search_for(control, "موس")
    for group in ("Orders", "Products", "Customers"):
        assert group in body, group
    for key in ("gs_open_orders", "gs_open_products", "gs_open_customers"):
        assert find(control, key) is None, "بدونِ on_open هیچ دکمه‌ی پُری نیست"


def test_search_screen_reports_nothing_found_without_wildcards(ui_env):
    products, orders, crm, _oid = ui_env
    control = search_screen.build(FakePage(), "fa", orders=orders, products=products, customers=crm, on_open=lambda _k: None)
    body = search_for(control, "٪")
    assert "چیزی پیدا نشد" in body
    assert find(control, "gs_count").value.strip().startswith("0")
    assert find(control, "gs_open_orders") is None
    body = search_for(control, "موس")  # جست‌وجویِ بعدی جای قبلی را می‌گیرد، نه اینکه دو فهرست شود
    assert "مشتریان" in body and "چیزی پیدا نشد" not in body
