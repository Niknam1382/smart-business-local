"""R11 — مهاجرتِ نسخه‌دارِ اسکیما: ارتقا از ۰.۵.۰، idempotency، دیتابیسِ جدیدتر، بازگردانیِ پشتیبانِ قدیمی."""

import sqlite3
import zipfile

import pytest

from app.core import backup, migrations
from app.core.conversations import ConversationStore
from app.core.migrations import MigrationError, SchemaTooNewError
from app.core.orders import OrderStore
from app.core.products import ProductStore

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
    assert (p.name, p.stock_quantity, p.product_type, p.unlimited_stock, p.delivery_kind) == ("هدفون", 7, "physical", False, "none")
    o1, o2 = orders.get(1), orders.get(2)
    assert o1.customer_name == "علی" and o1.items[0].product_name == "هدفون"
    assert o1.inventory_applied is True  # تاییدشده‌ی قدیمی = اعمال‌شده
    assert o2.inventory_applied is False and o2.status == "paid"
    assert conv.get_history("telegram", "5", limit=10)[0].content == "سلام"
    assert conv.get_display_name("telegram", "5") == "علی"
    for name, store_file in (("products.db", "products.db"), ("orders.db", "orders.db"), ("conversations.db", "conversations.db")):
        expected = {"conversations.db": 6, "orders.db": 5, "products.db": 3}.get(name, 2)  # مکالمه‌ها: customers (N12) + admins (N11) + broadcasts (N7) + ai_calls (N1)؛ سفارش‌ها: confirmed_by (N11) + تخفیف (N8)
        assert migrations.file_version(tmp_path / store_file) == migrations.latest_version(name) == expected


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
    assert migrations.apply_migrations(conn, __import__("app.core.products", fromlist=["MIGRATIONS"]).MIGRATIONS) == 3
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
    assert migrations.file_version(live / "products.db") == 3

    backup.restore_backup(zip_path, data_dir=live)
    assert migrations.file_version(live / "products.db") == 3
    restored = products.list()  # همون اتصالِ باز، بدونِ خطا، با ستون‌های جدید
    assert [p.name for p in restored] == ["هدفون"] and restored[0].product_type == "physical"


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
