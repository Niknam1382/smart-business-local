"""نگهبانِ «فقط فیزیکی»: هیچ مسیری از برنامه نباید دوباره «محصولِ دیجیتال» یا تحویلِ خودکار را
بازگرداند — نه در مدل، نه در متن‌هایِ ربات، نه در راهنما. این قابلیت قبلاً در دیتابیس، ربات،
راهنما و صفحه‌ی محصولات پخش بود و حذفش یک تصمیمِ محصولی است، نه پاک‌کردنِ یک باگ."""

import importlib
import sqlite3
from pathlib import Path

import pytest
from fake_page import FakePage, find

from app import i18n
from app.core import checkout_fields as cf
from app.core import guide, quick_setup, shop_texts
from app.core.attention import TYPES as ATTENTION_TYPES
from app.core.orders import OrderStore
from app.core.products import MIGRATIONS, Product, ProductStore
from app.core.shop_flow import ShopFlow

ROOT = Path(__file__).resolve().parents[1]


def test_the_delivery_module_is_gone():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.core.delivery")


def test_product_model_has_no_type_or_delivery_fields():
    for name in ("product_type", "delivery_kind", "delivery_payload", "is_digital"):
        assert name not in Product.__dataclass_fields__, name
    for name in ("add_keys", "keys_remaining", "allocated_keys", "_validate_shop_fields"):
        assert not hasattr(ProductStore, name), name
    assert len(MIGRATIONS) == 4 and MIGRATIONS[-1].__name__ == "_m4_physical_only"


def test_no_auto_delivery_api_left_in_orders_bot_manager_or_screens():
    for name in ("mark_delivered", "pending_deliveries", "_settle_delivery_flag"):
        assert not hasattr(OrderStore, name), name
    from app.core.bot_manager import BotManager

    for name in ("_deliver_digital", "deliver_digital_sync", "_retry_deliveries"):
        assert not hasattr(BotManager, name), name
    from app.screens import orders as orders_screen

    for name in ("_delivery_label", "_redeliver_label"):
        assert not hasattr(orders_screen, name), name
    source = (ROOT / "app" / "screens" / "products.py").read_text(encoding="utf-8")
    assert "product_type" not in source and "delivery_kind" not in source and "add_keys" not in source


def test_shop_texts_have_no_digital_delivery_group():
    keys = set(shop_texts.keys())
    assert not [k for k in keys if k.startswith("deliver.")], sorted(keys)
    assert "prod.type_digital" not in keys and "prod.type_physical" not in keys
    meta = (ROOT / "app" / "core" / "shop_text_meta.py").read_text(encoding="utf-8")
    assert not [line for line in meta.splitlines() if line.startswith(("deliver.", "prod.type_"))]
    assert "تحویلِ دیجیتال" not in meta


def test_desktop_strings_have_no_digital_product_keys():
    bad = [
        key for key in i18n.STRINGS
        if key.startswith(("products.form.delivery", "products.form.payload", "products.form.type",
                           "products.form.keys", "products.badge_digital", "products.keys_left"))
    ]
    assert bad == [], bad
    assert "pick_file" not in "".join(key for key in i18n.STRINGS if key.startswith("products."))


def test_checkout_field_model_has_no_applies_to():
    assert not hasattr(cf, "APPLIES_TO")
    assert "applies_to" not in cf.CheckoutField.__dataclass_fields__
    assert not hasattr(cf, "fields_for_cart")
    assert set(cf.templates("fa")) == {"physical", "services"}
    assert set(cf.templates("en")) == {"physical", "services"}


def test_quick_setup_presets_and_attention_types_are_physical_only():
    assert [p.id for p in quick_setup.PRESETS] == ["physical", "services", "consult", "support"]
    assert "delivery_failed" not in ATTENTION_TYPES


def test_ai_catalog_and_shop_flow_have_no_product_kind():
    kit = (ROOT / "app" / "core" / "prompt_kit.py").read_text(encoding="utf-8")
    assert "is_digital" not in kit and "دیجیتال" not in kit
    flow = (ROOT / "app" / "core" / "shop_flow.py").read_text(encoding="utf-8")
    assert "💾" not in flow and "prod.type_digital" not in flow and "is_digital" not in flow
    assert not hasattr(ShopFlow, "_deliver_digital")


def test_guide_category_index_promises_bulk_import_instead_of_digital_kinds():
    titles = " ".join(title for _key, title in guide.CATEGORIES)
    assert "دیجیتال" not in titles and "کلید" not in titles
    assert "اکسل" in titles


# «دیجیتال» در این دو عبارت به چیزِ دیگری اشاره دارد و مجاز است:
# «امضای دیجیتال» = امضایِ فایلِ نصب، «لوازم دیجیتال» = قالبِ پرامپتِ فروشگاهِ کالایِ الکترونیک.
ALLOWED_DIGITAL = ("امضای دیجیتال", "امضای دیجیتال", "لوازمِ دیجیتال", "لوازم دیجیتال")


@pytest.mark.parametrize("article", sorted(path.stem for path in (ROOT / "assets" / "guide" / "fa").glob("*.md")))
def test_help_articles_talk_about_physical_products_only(article):
    text = (ROOT / "assets" / "guide" / "fa" / f"{article}.md").read_text(encoding="utf-8")
    without_allowed = text
    for phrase in ALLOWED_DIGITAL:
        without_allowed = without_allowed.replace(phrase, "")
    assert "دیجیتال" not in without_allowed, article
    assert "لایسنس" not in text and "کلید/لایسنس" not in text, article


def test_products_screen_offers_the_template_and_import_buttons(tmp_path):
    from app.screens import products as products_screen

    store = ProductStore(db_path=tmp_path / "products.db")
    control = products_screen.build(FakePage(), "fa", store)
    assert find(control, "product_template") is not None and find(control, "product_import") is not None
    assert find(control, "product_import_note") is not None


# ------------------------------------------------------------ مهاجرتِ ۴ (داده‌یِ زنده) ----


def build_v3_products_db(path):
    """دیتابیسِ محصولاتِ نسخه‌ی پیشین (user_version=3) با یک ردیفِ دیجیتالِ لینکی، یک
    کلید/لایسنسِ انبارشده و یک کالای فیزیکی — همان چیزی که کاربرِ موجود دارد."""
    from app.core.products import MIGRATIONS as PRODUCT_MIGRATIONS
    from app.core.products import crypto

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    for step in PRODUCT_MIGRATIONS[:3]:
        step(conn)
    conn.execute("PRAGMA user_version = 3")
    conn.execute(
        "INSERT INTO products (name, price_irr, stock_quantity, description, product_type, unlimited_stock,"
        " delivery_kind, delivery_payload_encrypted) VALUES ('دوره', 500, 0, 'ویدیوهایِ آموزشی',"
        " 'digital', 1, 'link', ?)",
        (crypto.encrypt("https://x.example/course"),),
    )
    conn.execute(
        "INSERT INTO products (name, price_irr, stock_quantity, product_type, unlimited_stock, delivery_kind)"
        " VALUES ('کلید', 900, 2, 'digital', 0, 'keys')"
    )
    conn.execute("INSERT INTO products (name, price_irr, stock_quantity) VALUES ('کفش', 1000, 4)")
    conn.execute("INSERT INTO digital_items (product_id, secret_encrypted) VALUES (2, ?)", (crypto.encrypt("K-1"),))
    conn.commit()
    conn.close()


def test_migration_4_keeps_every_row_and_folds_the_old_payload(tmp_path):
    from app.core.products import crypto

    db = tmp_path / "products.db"
    build_v3_products_db(db)
    store = ProductStore(db)
    rows = {p.name: p for p in store.list(include_inactive=True)}

    assert set(rows) == {"دوره", "کلید", "کفش"}
    course = rows["دوره"]
    assert "https://x.example/course" in course.description and "تحویلِ پیشین:" in course.description
    assert course.unlimited_stock is True and course.in_stock is True  # فروشِش نمی‌شکند
    assert rows["کلید"].stock_quantity == 2 and rows["کفش"].stock_quantity == 4

    conn = sqlite3.connect(db)
    assert conn.execute("SELECT product_type, delivery_kind, delivery_payload_encrypted FROM products").fetchall() == [
        ("physical", "none", "")] * 3
    assert conn.execute("SELECT COUNT(*) FROM digital_items").fetchone()[0] == 1  # کلیدها پاک نشدند
    secret = conn.execute("SELECT secret_encrypted FROM digital_items").fetchone()[0]
    assert crypto.decrypt(secret) == "K-1"
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
    conn.close()


def test_migration_4_is_idempotent_and_never_repeats_the_note(tmp_path):
    from app.core import migrations
    from app.core.products import MIGRATIONS as PRODUCT_MIGRATIONS

    db = tmp_path / "products.db"
    build_v3_products_db(db)
    ProductStore(db).list()
    conn = sqlite3.connect(db)
    assert migrations.apply_migrations(conn, PRODUCT_MIGRATIONS, name="products.db") == 4
    conn.close()
    [course] = [p for p in ProductStore(db).list() if p.name == "دوره"]
    assert course.description.count("تحویلِ پیشین:") == 1
