"""R11 — مهاجرتِ نسخه‌دارِ اسکیما: ارتقا از ۰.۵.۰ و از ۵ (پیشِ ۱.۰.۰)، idempotency، دیتابیسِ جدیدتر،
بازگردانیِ پشتیبانِ قدیمی، و جدول‌هایِ رسید/تراکنشِ نسخه‌ی ۱.۰.۰."""

import sqlite3
import zipfile

import pytest

from app.core import backup, migrations
from app.core.conversations import ConversationStore
from app.core.migrations import MigrationError, SchemaTooNewError
from app.core.orders import MIGRATIONS as ORDERS_MIGRATIONS, OrderStore
from app.core.products import ProductStore

# نسخه‌هایِ میخ‌کوب‌شده: هر افزایشِ عمدی باید این‌جا ثبت بشه، وگرنه مهاجرت‌هایِ بی‌سروصدا رد می‌شن
LATEST = {"products.db": 4, "orders.db": 8, "conversations.db": 6}

# ---- اسکیمای دقیقِ ۰.۵.۰ (inline، مستقل از کدِ فعلی) ----
V05_PRODUCTS = """
CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, price_irr INTEGER NOT NULL,
    stock_quantity INTEGER NOT NULL DEFAULT 0, description TEXT NOT NULL DEFAULT '', photo_path TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')));
"""
V05_ORDERS = """
CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT NOT NULL, chat_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_payment', payment_method TEXT NOT NULL DEFAULT '', payment_reference TEXT NOT NULL DEFAULT '',
    total_irr INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_ts INTEGER NOT NULL DEFAULT 0, customer_name TEXT NOT NULL DEFAULT '', customer_phone TEXT NOT NULL DEFAULT '',
    customer_address TEXT NOT NULL DEFAULT '', gateway_ref TEXT NOT NULL DEFAULT '', payment_url TEXT NOT NULL DEFAULT '',
    paid_late INTEGER NOT NULL DEFAULT 0);
CREATE TABLE order_items (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, product_id INTEGER,
    product_name TEXT NOT NULL, unit_price_irr INTEGER NOT NULL, quantity INTEGER NOT NULL);
"""
V05_CONVERSATIONS = """
CREATE TABLE conversations (platform TEXT NOT NULL, chat_id TEXT NOT NULL, display_name TEXT NOT NULL DEFAULT '',
    memory_enabled INTEGER NOT NULL DEFAULT 1, blocked INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY (platform, chat_id));
CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT NOT NULL, chat_id TEXT NOT NULL, role TEXT NOT NULL,
    content TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')));
"""


@pytest.fixture(autouse=True)
def _fresh_backup_registry(monkeypatch):
    monkeypatch.setattr(migrations, "_backed_up_dirs", set())


def make_v05_data(folder):
    folder.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(folder / "products.db")
    c.executescript(V05_PRODUCTS)
    c.execute("INSERT INTO products (name, price_irr, stock_quantity) VALUES ('هدفون', 1000000, 7)")
    c.commit(); c.close()
    c = sqlite3.connect(folder / "orders.db")
    c.executescript(V05_ORDERS)
    c.execute("INSERT INTO orders (platform, chat_id, status, total_irr, customer_name) VALUES ('telegram','5','confirmed',1000000,'علی')")
    c.execute("INSERT INTO orders (platform, chat_id, status, total_irr) VALUES ('bale','6','paid',2000000)")
    c.execute("INSERT INTO order_items (order_id, product_id, product_name, unit_price_irr, quantity) VALUES (1,1,'هدفون',1000000,1)")
    c.commit(); c.close()
    c = sqlite3.connect(folder / "conversations.db")
    c.executescript(V05_CONVERSATIONS)
    c.execute("INSERT INTO conversations (platform, chat_id, display_name) VALUES ('telegram','5','علی')")
    c.execute("INSERT INTO messages (platform, chat_id, role, content) VALUES ('telegram','5','user','سلام')")
    c.commit(); c.close()


def test_upgrade_from_v05_keeps_all_data(tmp_path):
    make_v05_data(tmp_path)
    products = ProductStore(tmp_path / "products.db")
    orders = OrderStore(tmp_path / "orders.db", product_store=products)
    conv = ConversationStore(tmp_path / "conversations.db")

    p = products.list()[0]
    assert (p.name, p.stock_quantity, p.unlimited_stock, p.in_stock) == ("هدفون", 7, False, True)
    assert not hasattr(p, "product_type") and not hasattr(p, "delivery_kind")  # مدلِ فیزیکیِ خالص
    o1, o2 = orders.get(1), orders.get(2)
    assert o1.customer_name == "علی" and o1.items[0].product_name == "هدفون"
    assert o1.inventory_applied is True  # تاییدشده‌ی قدیمی = اعمال‌شده
    assert o2.inventory_applied is False and o2.status == "paid"
    assert conv.get_history("telegram", "5", limit=10)[0].content == "سلام"
    assert conv.get_display_name("telegram", "5") == "علی"
    for name, store_file in (("products.db", "products.db"), ("orders.db", "orders.db"), ("conversations.db", "conversations.db")):
        assert migrations.file_version(tmp_path / store_file) == migrations.latest_version(name) == LATEST[name]


def test_schema_versions_are_pinned():
    """هر مهاجرتِ تازه باید همین‌جا اعلام بشه. محصولات ۴ است (مهاجرتِ ۴: خروجِ کاملِ محصولِ دیجیتال
    از مدل) و سفارش‌ها ۸ (رسیدِ کارت‌به‌کارت + یکتاییِ شناسهٔ تراکنشِ درگاه + وضعیتِ ارسال + روش/هزینه‌ی ارسال)."""
    assert migrations.latest_version("products.db") == LATEST["products.db"] == 4
    assert migrations.latest_version("conversations.db") == LATEST["conversations.db"]
    assert len(ORDERS_MIGRATIONS) == migrations.latest_version("orders.db") == LATEST["orders.db"] == 8


def test_very_old_orders_table_without_phase4_columns_upgrades(tmp_path):
    c = sqlite3.connect(tmp_path / "orders.db")
    c.executescript("""CREATE TABLE orders (id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT NOT NULL, chat_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending_payment', payment_method TEXT NOT NULL DEFAULT '', payment_reference TEXT NOT NULL DEFAULT '',
        total_irr INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE TABLE order_items (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, product_id INTEGER,
        product_name TEXT NOT NULL, unit_price_irr INTEGER NOT NULL, quantity INTEGER NOT NULL);
        INSERT INTO orders (platform, chat_id, status) VALUES ('telegram','1','pending_payment');""")
    c.commit(); c.close()
    orders = OrderStore(tmp_path / "orders.db", product_store=ProductStore(tmp_path / "products.db"))
    order = orders.get(1)
    assert order is not None and order.expires_ts == 0 and order.customer_info == {}


def build_v5_orders_db(path) -> int:
    """دیتابیسِ سفارش‌هایِ نسخه‌ی ۱.x (user_version=5) با داده‌ی واقعی: مهاجرتِ ۱ تا ۵ اجرا
    می‌شه و بعد ردیف‌ها می‌آیند — همان چیزی که کاربرِ موجود بعد از نصبِ ۱.۰.۰ پیدا می‌کند."""
    conn = sqlite3.connect(path)
    assert migrations.apply_migrations(conn, ORDERS_MIGRATIONS[:5], name="orders.db") == 5
    conn.executescript(
        """
        INSERT INTO orders (id, platform, chat_id, status, payment_method, payment_reference, total_irr, note,
                            expires_ts, customer_name, customer_phone, gateway_ref, payment_url, confirmed_by)
        VALUES (1,'telegram','11','confirmed','card_to_card','ref-old',250000,'دیت',0,'علی','09121234567','abc','',1),
               (2,'telegram','22','pending_payment','bale_pay','',200000,'',4102444800,'مریم','','code-2','https://bale.ai/pay/2','');
        INSERT INTO order_items (order_id, product_id, product_name, unit_price_irr, quantity)
        VALUES (1,7,'هدفون',250000,1),(2,7,'هدفون',100000,2);
        INSERT INTO carts (platform, chat_id, product_id, quantity, updated_ts) VALUES ('telegram','22',7,1,1);
        """
    )
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    conn.close()
    return count


def test_orders_v5_with_data_upgrades_to_v6_and_is_idempotent(tmp_path):
    """ارتقا از ۵ به آخرین نسخه: هیچ ردیفِ از دست نمی‌ره، جدول‌ها/نمایه‌هایِ تازه ساخته می‌شن و اجرایِ
    دوباره‌ی مهاجرت بی‌خطر است (idempotent) — چون برنامه ممکن است چند بار بالا بیاید."""
    db = tmp_path / "orders.db"
    assert build_v5_orders_db(db) == 2

    products = ProductStore(tmp_path / "products.db")
    products.add("هدفون", 100000, 5)
    orders = OrderStore(db, product_store=products)
    assert orders.get(1).customer_name == "علی"  # مهاجرت روی اتصالِ فروشگاه اجرا شده و داده سالمه

    conn = sqlite3.connect(db)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'")}
    assert {"payment_receipts", "payment_charges"} <= names
    assert {"idx_receipts_order", "idx_receipts_new", "idx_charges_order", "idx_order_items_product",
            "idx_orders_payment_reference"} <= indexes
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM order_items").fetchone()[0] == 2
    assert conn.execute("SELECT quantity FROM carts WHERE chat_id='22'").fetchone()[0] == 1
    conn.close()

    got = orders.get(2)
    assert (got.status, got.total_irr, got.gateway_ref, got.customer_name) == ("pending_payment", 200000, "code-2", "مریم")
    assert [i.product_name for i in got.items] == ["هدفون"]
    assert orders.confirmed_by(1)  # ستونِ ۱.x دست‌نخورده موند

    # اجرایِ دوباره و سه‌بارهٔ مهاجرت: نه خطا، نه تغییرِ اسکیمای tables/indexes
    def shape():
        c = sqlite3.connect(db)
        out = sorted((r[0], r[1]) for r in c.execute("SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
        c.close()
        return out

    shape_latest = shape()
    conn = sqlite3.connect(db)
    assert migrations.apply_migrations(conn, ORDERS_MIGRATIONS, name="orders.db") == 8
    assert migrations.apply_migrations(conn, ORDERS_MIGRATIONS, name="orders.db") == 8
    conn.close()
    assert shape() == shape_latest
    assert migrations.file_version(db) == 8
    assert orders.get(1).customer_name == "علی" and orders.get(2).gateway_ref == "code-2"


def build_v6_orders_db(path) -> None:
    """دیتابیسِ سفارش‌هایِ نسخه‌ی پیشین (user_version=6، بدونِ وضعیتِ ارسال) با یک سفارشِ تأییدشده."""
    conn = sqlite3.connect(path)
    assert migrations.apply_migrations(conn, ORDERS_MIGRATIONS[:6], name="orders.db") == 6
    conn.execute(
        "INSERT INTO orders (id, platform, chat_id, status, inventory_applied, total_irr, customer_name) "
        "VALUES (1,'telegram','11','confirmed',1,250000,'علی')"
    )
    conn.commit()
    conn.close()


def test_orders_v6_upgrades_to_v7_with_empty_fulfillment(tmp_path):
    """مهاجرتِ ۷ دو ستونِ تازه می‌آورد و مقدارِ هیچ سفارشِ تأییدشده‌ی قدیمی را عوض نمی‌کند:
    «''» یعنی شروع‌نشده — مالک خودش تصمیم می‌گیره، برنامه بی‌صدا «آماده‌سازی» نمی‌چسبونه.
    (فروشگاه همان‌جا مهاجرتِ ۸ را هم اجرا می‌کند، پس ``user_version``ِ نهایی ۸ است نه ۷.)"""
    db = tmp_path / "orders.db"
    build_v6_orders_db(db)
    orders = OrderStore(db, product_store=ProductStore(tmp_path / "products.db"))

    order = orders.get(1)
    assert order.status == "confirmed" and order.fulfillment == "" and order.tracking_code == ""

    conn = sqlite3.connect(db)
    assert {"fulfillment", "tracking_code"} <= migrations.table_columns(conn, "orders")
    assert conn.execute("SELECT fulfillment, tracking_code, status FROM orders WHERE id=1").fetchone() == ("", "", "confirmed")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 8
    conn.close()

    orders.set_fulfillment(1, "preparing", tracking_code="TG-9")  # ستون‌هایِ تازه واقعاً قابل‌نوشتن‌اند
    fresh = orders.get(1)
    assert (fresh.fulfillment, fresh.tracking_code, fresh.status) == ("preparing", "TG-9", "confirmed")


def build_v7_orders_db(path) -> None:
    """دیتابیسِ سفارش‌هایِ نسخه‌ی پیشین (user_version=7، بدونِ ستون‌هایِ ارسال) با یک سفارشِ تأییدشده."""
    conn = sqlite3.connect(path)
    assert migrations.apply_migrations(conn, ORDERS_MIGRATIONS[:7], name="orders.db") == 7
    conn.execute(
        "INSERT INTO orders (id, platform, chat_id, status, inventory_applied, total_irr, customer_name) "
        "VALUES (1,'telegram','11','confirmed',1,250000,'علی')"
    )
    conn.commit()
    conn.close()


def test_orders_v7_upgrades_to_v8_with_empty_shipping(tmp_path):
    """مهاجرتِ ۸ دو ستونِ «روشِ ارسال/هزینه» را اضافه می‌کند و هیچ سفارشِ قدیمی را دست نمی‌زند:
    «''» و ``0`` یعنی ارسال ندارد — با «پیش‌فرضِ خاموشِ» این قابلیت، مبلغِ هیچ سفارشِ قبلی عوض نمی‌شود."""
    db = tmp_path / "orders.db"
    build_v7_orders_db(db)
    orders = OrderStore(db, product_store=ProductStore(tmp_path / "products.db"))

    order = orders.get(1)
    assert order.status == "confirmed" and order.shipping_method == "" and order.shipping_irr == 0
    assert order.total_irr == order.subtotal_irr == 250000  # ناورداییِ مبلغ برای سفارشِ قدیمی برقرار می‌ماند

    conn = sqlite3.connect(db)
    assert {"shipping_method", "shipping_irr"} <= migrations.table_columns(conn, "orders")
    assert conn.execute("SELECT shipping_method, shipping_irr FROM orders WHERE id=1").fetchone() == ("", 0)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 8
    conn.close()


def test_v6_matches_a_brand_new_database(tmp_path):
    """دیتابیسِ ارتقایافته و دیتابیسِ تازه باید اسکیمایِ یکی داشته باشن (تا restore و
    نصبِ تازه یک رفتار بدهند)."""
    old = tmp_path / "old" / "orders.db"
    old.parent.mkdir()
    build_v5_orders_db(old)
    products = ProductStore(tmp_path / "products.db")
    OrderStore(old, product_store=products).list()
    fresh = tmp_path / "fresh" / "orders.db"
    OrderStore(fresh, product_store=products).list()

    def shape(path):
        c = sqlite3.connect(path)
        tables = sorted((r[0], r[1]) for r in c.execute("SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
        cols = {t: [r[1] for r in c.execute(f'PRAGMA table_info("{t}")')] for t, _ in tables if t == "orders"}
        c.close()
        return tables, cols

    assert shape(old) == shape(fresh)


def test_payment_charges_key_is_unique_at_database_level(tmp_path):
    """یک شناسهٔ تراکنش نمی‌تواند دو سفارش را تأیید کند — یکتایی در خودِ SQLite گنجانده شده،
    نه فقط در حافظهٔ یک پردازش (پس دو اجرا/دو ترد هم امن است)."""
    products = ProductStore(tmp_path / "products.db")
    pid = products.add("هدفون", 100000, 50)
    orders = OrderStore(tmp_path / "orders.db", product_store=products)
    oid_a = orders.create("telegram", "31", [(pid, 1)])
    oid_b = orders.create("telegram", "32", [(pid, 1)])
    assert orders.claim_payment_charge("CH-1", oid_a, "bale_pay") is True
    assert orders.claim_payment_charge(" CH-1 ", oid_b, "bale_pay") is False  # با trim هم همان کلید
    assert orders.charge_owner("CH-1") == oid_a and orders.charge_owner("CH-2") is None
    conn = sqlite3.connect(tmp_path / "orders.db")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO payment_charges (charge_id, order_id) VALUES ('CH-1', ?)", (oid_b,))
    conn.close()
    assert orders.claim_payment_charge("", oid_b) is False  # شناسهٔ خالی هرگز حقِ تأیید نمی‌دهد


def test_receipt_rows_are_recorded_and_read_back(tmp_path):
    """رسیدِ کارت‌به‌کارت فقط «ثبت» می‌شه (تأییدِ نهایی دستی است) و صفِ «برو چک کن» فقط
    سفارش‌هایِ پرداخت‌شدهٔ تأییدنشده را نشان می‌دهد."""
    products = ProductStore(tmp_path / "products.db")
    pid = products.add("هدفون", 100000, 50)
    orders = OrderStore(tmp_path / "orders.db", product_store=products)
    oid = orders.create("telegram", "41", [(pid, 1)])
    orders.mark_paid(oid, "card_to_card", "ref-1")
    rid = orders.add_receipt(oid, body="رسید ۲۵۰۰۰۰ ریال", amount_irr=250000, match_state="amount_ok", trace_code="T-9")
    assert rid and orders.receipts_for(oid)[0]["id"] == rid
    assert orders.receipts_for(oid)[0]["body"] == "رسید ۲۵۰۰۰۰ ریال"
    assert orders.receipts_for(oid)[0]["match_state"] == "amount_ok"
    assert orders.add_receipt(oid, kind="image", file_path="") is None  # عکسِ بی‌فایل ثبت نمی‌شه
    assert orders.add_receipt(oid, body="   ") is None  # متنِ خالی هم نه
    assert [r["order_id"] for r in orders.receipts_needing_attention()] == [oid]
    assert orders.get(oid).receipts  # Order.receipts از همین جدول پر می‌شه
    orders.confirm(oid)
    assert orders.receipts_needing_attention() == []



def test_rerun_is_noop_and_fresh_db_reaches_same_schema(tmp_path):
    make_v05_data(tmp_path / "old")
    ProductStore(tmp_path / "old" / "products.db").list()
    fresh = ProductStore(tmp_path / "fresh" / "products.db")
    fresh.list()

    def shape(path):
        c = sqlite3.connect(path)
        rows = sorted((r[0], r[1]) for r in c.execute("SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
        cols = sorted(r[1] for r in c.execute("PRAGMA table_info(products)"))
        c.close()
        return rows, cols

    assert shape(tmp_path / "old" / "products.db") == shape(tmp_path / "fresh" / "products.db")
    conn = sqlite3.connect(tmp_path / "old" / "products.db")
    assert migrations.apply_migrations(conn, __import__("app.core.products", fromlist=["MIGRATIONS"]).MIGRATIONS) == 4
    conn.close()


def test_db_newer_than_app_is_rejected(tmp_path):
    c = sqlite3.connect(tmp_path / "products.db")
    c.execute("PRAGMA user_version = 99")
    c.close()
    with pytest.raises(SchemaTooNewError, match="به‌روز"):
        ProductStore(tmp_path / "products.db").list()


def test_failing_migration_rolls_back_completely(tmp_path):
    conn = sqlite3.connect(tmp_path / "x.db")

    def m1(c):
        c.execute("CREATE TABLE a (id INTEGER)")

    def m2(c):
        c.execute("CREATE TABLE b (id INTEGER)")
        c.execute("ALTER TABLE a ADD COLUMN x INTEGER")
        raise RuntimeError("boom")

    with pytest.raises(MigrationError, match="هیچ تغییری"):
        migrations.apply_migrations(conn, [m1, m2], name="x.db")
    assert migrations.current_version(conn) == 1
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert names == {"a"} and "x" not in migrations.table_columns(conn, "a")
    conn.close()


def test_backup_is_taken_before_upgrading_a_db_with_data(tmp_path):
    make_v05_data(tmp_path)
    ProductStore(tmp_path / "products.db").list()
    zips = list((tmp_path / "backups").glob("before-upgrade-*.zip"))
    assert len(zips) == 1
    with zipfile.ZipFile(zips[0]) as zf:
        assert "products.db" in zf.namelist()
    # فقط یک پشتیبان به ازای هر پوشه‌ی داده (نه یکی برای هر دیتابیس)
    OrderStore(tmp_path / "orders.db", product_store=ProductStore(tmp_path / "products.db")).list()
    assert len(list((tmp_path / "backups").glob("before-upgrade-*.zip"))) == 1


def test_no_backup_for_brand_new_or_empty_db(tmp_path):
    ProductStore(tmp_path / "products.db").list()
    assert not (tmp_path / "backups").exists()


def test_restore_older_backup_runs_migrations_on_open_stores(tmp_path):
    old, live = tmp_path / "old", tmp_path / "live"
    make_v05_data(old)
    zip_path = backup.create_backup(tmp_path / "old-backup.zip", data_dir=old)

    live.mkdir()
    products = ProductStore(live / "products.db")
    products.add("جدید", 5, 1)  # اتصالِ بازِ فروشگاه با اسکیمای جدید
    assert migrations.file_version(live / "products.db") == 4

    backup.restore_backup(zip_path, data_dir=live)
    assert migrations.file_version(live / "products.db") == 4
    restored = products.list()  # همون اتصالِ باز، بدونِ خطا، با ستون‌های جدید
    assert [p.name for p in restored] == ["هدفون"] and restored[0].unlimited_stock is False


def test_restore_newer_backup_is_refused_and_live_data_untouched(tmp_path):
    src, live = tmp_path / "src", tmp_path / "live"
    src.mkdir(); live.mkdir()
    ProductStore(src / "products.db").add("از آینده", 1, 1)
    c = sqlite3.connect(src / "products.db")
    c.execute("PRAGMA user_version = 99")
    c.close()
    zip_path = backup.create_backup(tmp_path / "future.zip", data_dir=src)

    products = ProductStore(live / "products.db")
    products.add("فعلی", 10, 2)
    with pytest.raises(backup.BackupError, match="به‌روز کن"):
        backup.restore_backup(zip_path, data_dir=live)
    assert [p.name for p in products.list()] == ["فعلی"]


@pytest.mark.parametrize("store_name", ["products", "orders", "conversations"])
def test_first_touch_from_a_new_thread_while_a_writer_holds_the_lock_does_not_crash(tmp_path, store_name):
    """``PRAGMA journal_mode=WAL`` روی فایلی که تردِ دیگری وسطِ تراکنشِ نوشتن است «database is locked»
    می‌دهد. هر سه فروشگاه کانکشنِ *هر ترد* را همین‌طور باز می‌کردند، پس اولین برخوردِ یک تردِ تازه
    (سفارشِ مشتری هم‌زمان با تردِ نگهداری) با sqlite3.OperationalError می‌ترکید — باگِ واقعی
    که در ۱۲ سفارشِ هم‌زمان حدوداً یکی‌درپنج اجرا دیده می‌شد."""
    import threading

    path = tmp_path / f"{store_name}.db"
    store = {"products": lambda: ProductStore(path), "orders": lambda: OrderStore(db_path=path), "conversations": lambda: ConversationStore(path)}[store_name]()
    store._connection().execute("SELECT 1").fetchone()  # noqa: SLF001 — دیتابیس یک‌بار ساخته/مهاجرت شده باشد
    out: list = []

    def worker():
        try:
            conn = store._connection()  # noqa: SLF001 — همان نقطه‌ی تماسِ اولینِ استفاده در تردِ تازه
            out.append(conn.execute("SELECT 1").fetchone()[0])
        except BaseException as exc:  # noqa: BLE001 — تست دقیقاً نوعِ خطا را می‌سنجد
            out.append(exc)

    blocker = sqlite3.connect(str(path), timeout=1)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout=30)
        assert not thread.is_alive(), "ترد روی قفلِ WAL گیر کرد"
        assert not any(isinstance(x, BaseException) for x in out), f"خطا از تردِ تازه نشت کرد: {out}"
    finally:
        blocker.rollback()
        blocker.close()


def test_wal_pragma_is_what_used_to_break_the_new_thread(tmp_path, monkeypatch):
    """اثباتِ اینکه تستِ بالا همان باگ را می‌گیرد، نه شانسِ زمانبندی را.

    باگ فقط وقتی رخ می‌دهد که pragma باید حالتِ فایل را *تغییر* بدهد (اولین مقداردهی):
    همان لحظه اگر نوشتنِ دیگری قفل داشته باشد SQLite «database is locked» می‌دهد و
    بیرون‌آمدنِ آن یعنی سفارشِ مشتری با OperationalError می‌افتد."""
    import threading

    path = tmp_path / "orders.db"
    store = OrderStore(db_path=path)
    store._connection().execute("SELECT 1").fetchone()  # noqa: SLF001 — مهاجرت انجام شده

    def touch_new_thread(collector):
        def worker():
            try:
                collector.append(store._connection().execute("SELECT 1").fetchone()[0])  # noqa: SLF001
            except BaseException as exc:  # noqa: BLE001
                collector.append(type(exc).__name__)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout=60)
        assert not thread.is_alive()
        return collector

    def reset_to_delete_mode():
        old = getattr(store._local, "conn", None)  # noqa: SLF001
        if old is not None:
            old.close()  # خارجِ WAL رفتن فقط وقتی هیچ اتصالِ باز دیگری نباشد ممکن است
            store._local.conn = None  # noqa: SLF001
        other = sqlite3.connect(str(path), timeout=5)
        other.execute("PRAGMA journal_mode=DELETE")
        other.commit()
        other.close()

    blocker = sqlite3.connect(str(path), timeout=1)
    try:
        # ۱) با pragmaِ بی‌تحملِ قبلی: باید بشکنیم
        reset_to_delete_mode()
        monkeypatch.setattr(migrations, "ensure_wal", lambda conn, **_kw: conn.execute("PRAGMA journal_mode=WAL"))
        blocker.execute("BEGIN IMMEDIATE")
        try:
            assert touch_new_thread([]) == ["OperationalError"], "تستِ باگ باید همان خطا را ببیند"
        finally:
            blocker.rollback()

        # ۲) با کدِ فعلی (تحمل/تلاش): تردِ تازه نمی‌شکند، حتی اگر فایل فعلاً قفل باشد
        monkeypatch.undo()  # نسخه‌ی بی‌تحملِ مرحله‌ی قبل دیگر نباید در کار باشد
        reset_to_delete_mode()
        blocker.execute("BEGIN IMMEDIATE")
        try:
            assert touch_new_thread([]) == [1], "تردِ تازه نباید بشکند"
        finally:
            blocker.rollback()

        # ۳) بعد از آزادشدنِ قفل، همان فایل WAL می‌شود (تحمل یعنی انصراف، نه جاودانه بی‌WAL ماندن)
        old = getattr(store._local, "conn", None)
        if old is not None:
            old.close()
            store._local.conn = None
        assert touch_new_thread([]) == [1]
        check = sqlite3.connect(str(path), timeout=5)
        assert check.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        check.close()
    finally:
        blocker.close()
