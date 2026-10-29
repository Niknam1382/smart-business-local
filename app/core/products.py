"""
ذخیره‌سازی محصولات — فقط برای کسب‌وکارهایی که حالت «فروشگاه» رو انتخاب
کردن (حالت «مشاوره» اصلاً این مدل رو نمی‌بینه؛ تصمیمش توی main.py گرفته
می‌شه، نه اینجا).

مثل conversations.py از SQLite استفاده می‌کنه (همون فایل app data، جدول
جدا) — دلیلش یکیه: تعداد محصول‌ها می‌تونه رشد کنه و کوئری‌های «لیست محصولات
فعال» باید سریع باشن.

غیرفعال‌سازی به‌جای حذف واقعی: یه محصول که قبلاً توی یه سفارش بوده نباید
واقعاً حذف بشه، وگرنه تاریخچه‌ی اون سفارش بی‌معنی می‌شه («سفارش برای محصولی
که دیگه وجود نداره»). برای همین «حذف» در واقع ``active=False`` می‌کنه و از
لیست پیش‌فرض/کاتالوگ مشتری مخفی می‌شه، نه از دیتابیس.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.core import crypto, migrations
from app.core.paths import get_app_data_dir

_DB_FILE_NAME = "products.db"
_PHOTOS_DIR_NAME = "product_photos"
_ALLOWED_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def copy_photo_into_store(source_path: str) -> str:
    """عکس انتخاب‌شده رو با یه اسم یکتا توی پوشه‌ی داده‌ی خودِ برنامه کپی
    می‌کنه و مسیر مطلق جدید رو برمی‌گردونه — تا اگه کاربر فایل اصلی رو جابه‌جا
    یا پاک کنه، عکس محصول خراب نشه (خودمون یه نسخه‌ی مستقل نگه می‌داریم)."""
    src = Path(source_path)
    ext = src.suffix.lower()
    if ext not in _ALLOWED_PHOTO_EXTENSIONS:
        raise ProductError("فرمت عکس پشتیبانی نمی‌شه (jpg، png، webp یا gif بده).")
    dest_dir = get_app_data_dir() / _PHOTOS_DIR_NAME
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{uuid.uuid4().hex}{ext}"
    shutil.copyfile(src, dest)
    return str(dest)


def delete_photo_file(photo_path: str) -> None:
    """وقتی عکس یه محصول عوض/حذف می‌شه، فایل قدیمی رو از پوشه‌ی خودمون پاک
    می‌کنه تا دیسک کاربر بی‌دلیل پر نشه. خطای نبودِ فایل رو نادیده می‌گیره."""
    if not photo_path:
        return
    try:
        Path(photo_path).unlink(missing_ok=True)
    except OSError:
        pass

PRODUCT_TYPES = ("physical", "digital")
DELIVERY_KINDS = ("none", "text", "link", "file", "keys")


def _m1_baseline(conn: sqlite3.Connection) -> None:
    """وضعیتِ ۰.۵.۰ (idempotent: روی دیتابیسِ قدیمی هم بی‌خطره)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price_irr INTEGER NOT NULL,
            stock_quantity INTEGER NOT NULL DEFAULT 0,
            description TEXT NOT NULL DEFAULT '',
            photo_path TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )


def _m2_shop_schema(conn: sqlite3.Connection) -> None:
    """۱.۰.۰: نوعِ محصول (فیزیکی/دیجیتال)، دسته، موجودیِ نامحدود، تحویلِ دیجیتال، ترتیب؛
    جدولِ کلیدهای دیجیتال و دفترِ موجودی (ledger) برای saga تاییدِ سفارش."""
    migrations.add_column(conn, "products", "product_type", "TEXT NOT NULL DEFAULT 'physical'")
    migrations.add_column(conn, "products", "category", "TEXT NOT NULL DEFAULT ''")
    migrations.add_column(conn, "products", "unlimited_stock", "INTEGER NOT NULL DEFAULT 0")
    migrations.add_column(conn, "products", "delivery_kind", "TEXT NOT NULL DEFAULT 'none'")
    migrations.add_column(conn, "products", "delivery_payload_encrypted", "TEXT NOT NULL DEFAULT ''")
    migrations.add_column(conn, "products", "sort_order", "INTEGER NOT NULL DEFAULT 0")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS digital_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            secret_encrypted TEXT NOT NULL,
            consumed_order_id INTEGER,
            consumed_ts INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_digital_items_product ON digital_items(product_id, consumed_order_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_digital_items_order ON digital_items(consumed_order_id)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_ledger (
            order_id INTEGER PRIMARY KEY,
            applied_ts INTEGER NOT NULL,
            lines_json TEXT NOT NULL DEFAULT '[]'
        )
        """
    )


def _m3_cost(conn: sqlite3.Connection) -> None:
    """N19: بهای تمام‌شده‌ی هر واحد (اختیاری؛ ۰ = ثبت‌نشده ← COGS صفر + هشدارِ «بهای کالا ثبت نشده»)."""
    migrations.add_column(conn, "products", "cost_irr", "INTEGER NOT NULL DEFAULT 0")


MIGRATIONS = [_m1_baseline, _m2_shop_schema, _m3_cost]


class ProductError(Exception):
    """خطای قابل‌نمایش (فارسی) — مثلاً موجودی منفی یا قیمت نامعتبر."""


@dataclass
class Product:
    id: int
    name: str
    price_irr: int
    stock_quantity: int
    description: str = ""
    photo_path: str = ""
    active: bool = True
    created_at: str = ""
    updated_at: str = ""
    product_type: str = "physical"  # physical | digital
    category: str = ""
    unlimited_stock: bool = False
    delivery_kind: str = "none"  # none | text | link | file | keys
    delivery_payload: str = ""  # متن/لینک/مسیرِ فایل (روی دیسک رمزنگاری‌شده؛ این‌جا رمزگشایی‌شده)
    sort_order: int = 0
    cost_irr: int = 0  # N19: بهای تمام‌شده‌ی هر واحد؛ ۰ = ثبت نشده

    @property
    def is_digital(self) -> bool:
        return self.product_type == "digital"

    @property
    def in_stock(self) -> bool:
        return self.unlimited_stock or self.stock_quantity > 0


def _row_to_product(r: sqlite3.Row) -> Product:
    payload_enc = r["delivery_payload_encrypted"]
    return Product(
        id=r["id"],
        name=r["name"],
        price_irr=r["price_irr"],
        stock_quantity=r["stock_quantity"],
        description=r["description"],
        photo_path=r["photo_path"],
        active=bool(r["active"]),
        created_at=r["created_at"],
        updated_at=r["updated_at"],
        product_type=r["product_type"],
        category=r["category"],
        unlimited_stock=bool(r["unlimited_stock"]),
        delivery_kind=r["delivery_kind"],
        delivery_payload=crypto.decrypt(payload_enc) if payload_enc else "",
        sort_order=r["sort_order"],
        cost_irr=int(r["cost_irr"]),
    )


class ProductStore:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (get_app_data_dir() / _DB_FILE_NAME)
        self._local = threading.local()

    def _connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.db_path), timeout=15)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            migrations.prepare(conn, self.db_path, MIGRATIONS)
            self._local.conn = conn
        return conn

    @staticmethod
    def _validate(name: str, price_irr: int, stock_quantity: int) -> None:
        if not name or not name.strip():
            raise ProductError("اسم محصول نمی‌تونه خالی باشه.")
        if price_irr < 0:
            raise ProductError("قیمت نمی‌تونه منفی باشه.")
        if stock_quantity < 0:
            raise ProductError("موجودی نمی‌تونه منفی باشه.")

    @staticmethod
    def _validate_shop_fields(product_type: str, delivery_kind: str, unlimited_stock: bool) -> None:
        if product_type not in PRODUCT_TYPES:
            raise ProductError("نوعِ محصول باید «فیزیکی» یا «دیجیتال» باشه.")
        if delivery_kind not in DELIVERY_KINDS:
            raise ProductError("نوعِ تحویل نامعتبره.")
        if product_type == "physical" and delivery_kind != "none":
            raise ProductError("تحویلِ خودکار فقط برای محصولِ دیجیتاله.")
        if delivery_kind == "keys" and unlimited_stock:
            raise ProductError("محصولِ «کلید/لایسنس» موجودیِ نامحدود نداره (موجودی = تعدادِ کلیدها).")

    def add(
        self,
        name: str,
        price_irr: int,
        stock_quantity: int = 0,
        description: str = "",
        photo_path: str = "",
        *,
        product_type: str = "physical",
        category: str = "",
        unlimited_stock: Optional[bool] = None,
        delivery_kind: str = "none",
        delivery_payload: str = "",
        sort_order: int = 0,
    ) -> int:
        self._validate(name, price_irr, stock_quantity)
        if unlimited_stock is None:  # دیجیتالِ غیرکلیدی پیش‌فرض نامحدوده
            unlimited_stock = product_type == "digital" and delivery_kind != "keys"
        self._validate_shop_fields(product_type, delivery_kind, bool(unlimited_stock))
        conn = self._connection()
        cur = conn.execute(
            """
            INSERT INTO products (name, price_irr, stock_quantity, description, photo_path,
                                  product_type, category, unlimited_stock, delivery_kind,
                                  delivery_payload_encrypted, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name.strip(), price_irr, 0 if delivery_kind == "keys" else stock_quantity, description.strip(), photo_path,
                product_type, category.strip()[:40], 1 if unlimited_stock else 0, delivery_kind,
                crypto.encrypt(delivery_payload) if delivery_payload else "", int(sort_order),
            ),
        )
        conn.commit()
        return cur.lastrowid

    def update(
        self,
        product_id: int,
        name: str,
        price_irr: int,
        stock_quantity: int,
        description: str = "",
        photo_path: Optional[str] = None,
        *,
        product_type: Optional[str] = None,
        category: Optional[str] = None,
        unlimited_stock: Optional[bool] = None,
        delivery_kind: Optional[str] = None,
        delivery_payload: Optional[str] = None,
        sort_order: Optional[int] = None,
    ) -> None:
        self._validate(name, price_irr, stock_quantity)
        current = self.get(product_id)
        if current is None:
            raise ProductError("این محصول دیگه وجود نداره.")
        ptype = product_type if product_type is not None else current.product_type
        kind = delivery_kind if delivery_kind is not None else current.delivery_kind
        unlimited = unlimited_stock if unlimited_stock is not None else current.unlimited_stock
        if ptype == "physical":
            kind = "none"
        self._validate_shop_fields(ptype, kind, bool(unlimited))
        sets = ["name=?", "price_irr=?", "description=?", "product_type=?", "delivery_kind=?", "unlimited_stock=?"]
        args: list = [name.strip(), price_irr, description.strip(), ptype, kind, 1 if unlimited else 0]
        if kind != "keys":  # برای محصولِ کلیدی موجودی = تعدادِ کلیدهای مصرف‌نشده (فقط از add_keys/saga تغییر می‌کنه)
            sets.append("stock_quantity=?")
            args.append(stock_quantity)
        if photo_path is not None:
            sets.append("photo_path=?")
            args.append(photo_path)
        if category is not None:
            sets.append("category=?")
            args.append(category.strip()[:40])
        if delivery_payload is not None:
            sets.append("delivery_payload_encrypted=?")
            args.append(crypto.encrypt(delivery_payload) if delivery_payload else "")
        if sort_order is not None:
            sets.append("sort_order=?")
            args.append(int(sort_order))
        conn = self._connection()
        conn.execute(f"UPDATE products SET {', '.join(sets)}, updated_at=datetime('now') WHERE id=?", (*args, product_id))
        conn.commit()

    def set_active(self, product_id: int, active: bool) -> None:
        conn = self._connection()
        conn.execute(
            "UPDATE products SET active=?, updated_at=datetime('now') WHERE id=?",
            (1 if active else 0, product_id),
        )
        conn.commit()

    def set_cost(self, product_id: int, cost_irr: int) -> None:
        """N19: بهای تمام‌شده‌ی هر واحد (ریال؛ ۰ = پاک‌کردن). فقط روی سفارش‌های *بعدی* اثر دارد؛ COGSِ ثبت‌شده عوض نمی‌شه."""
        if not isinstance(cost_irr, int) or isinstance(cost_irr, bool) or cost_irr < 0 or cost_irr > 10**12:
            raise ProductError("بهای تمام‌شده باید عددِ صحیحِ غیرمنفی باشه.")
        conn = self._connection()
        conn.execute("UPDATE products SET cost_irr=?, updated_at=datetime('now') WHERE id=?", (cost_irr, product_id))
        conn.commit()

    def adjust_stock(self, product_id: int, delta: int) -> None:
        """موجودی رو کم/زیاد می‌کنه (برای تاییدشدن سفارش: delta منفی). اگه
        موجودی کافی نباشه (نتیجه منفی بشه)، خطا می‌ده و چیزی تغییر نمی‌کنه —
        دو سفارش هم‌زمان نباید بتونن موجودی رو منفی کنن."""
        conn = self._connection()
        cur = conn.execute(
            "UPDATE products SET stock_quantity = stock_quantity + ?, updated_at = datetime('now') "
            "WHERE id = ? AND stock_quantity + ? >= 0",
            (delta, product_id, delta),
        )
        conn.commit()
        if cur.rowcount == 0:
            product = self.get(product_id)
            if product is None:
                raise ProductError("این محصول دیگه وجود نداره.")
            raise ProductError(f"موجودی کافی نیست (موجودی فعلی: {product.stock_quantity}).")

    def get(self, product_id: int) -> Optional[Product]:
        row = self._connection().execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        return _row_to_product(row) if row else None

    def list(self, include_inactive: bool = False) -> list[Product]:
        query = "SELECT * FROM products"
        if not include_inactive:
            query += " WHERE active = 1"
        query += " ORDER BY sort_order ASC, id DESC"
        rows = self._connection().execute(query).fetchall()
        return [_row_to_product(r) for r in rows]

    def categories(self) -> list:
        """دسته‌های غیرخالیِ محصولاتِ فعال، با تعداد: ``[(نام، تعداد), ...]`` به ترتیبِ الفبا."""
        rows = self._connection().execute(
            "SELECT category, COUNT(*) AS n FROM products WHERE active=1 AND category != '' GROUP BY category ORDER BY category"
        ).fetchall()
        return [(r["category"], int(r["n"])) for r in rows]

    # ---------------------------------------------------- کلیدهای دیجیتال (R4)

    def add_keys(self, product_id: int, keys: list) -> int:
        """کلید/لایسنس‌های جدید برای یه محصولِ ``delivery_kind='keys'`` اضافه می‌کنه (رمزنگاری‌شده)
        و موجودی رو به‌اندازه‌ی تعدادشون بالا می‌بره. تعدادِ اضافه‌شده رو برمی‌گردونه."""
        product = self.get(product_id)
        if product is None:
            raise ProductError("این محصول دیگه وجود نداره.")
        if product.delivery_kind != "keys":
            raise ProductError("این محصول از نوعِ «کلید/لایسنس» نیست.")
        clean = [k.strip() for k in keys if k and k.strip()]
        if not clean:
            return 0
        conn = self._connection()
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.executemany(
                "INSERT INTO digital_items (product_id, secret_encrypted) VALUES (?, ?)",
                [(product_id, crypto.encrypt(k)) for k in clean],
            )
            conn.execute(
                "UPDATE products SET stock_quantity = stock_quantity + ?, updated_at=datetime('now') WHERE id=?",
                (len(clean), product_id),
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        return len(clean)

    def keys_remaining(self, product_id: int) -> int:
        row = self._connection().execute(
            "SELECT COUNT(*) AS n FROM digital_items WHERE product_id=? AND consumed_order_id IS NULL", (product_id,)
        ).fetchone()
        return int(row["n"])

    def allocated_keys(self, order_id: int) -> list:
        """کلیدهایی که saga برای این سفارش اختصاص داده: ``[(product_id, کلید), ...]`` (تحویلِ دوباره = همان کلیدها)."""
        rows = self._connection().execute(
            "SELECT product_id, secret_encrypted FROM digital_items WHERE consumed_order_id=? ORDER BY id", (order_id,)
        ).fetchall()
        return [(r["product_id"], crypto.decrypt(r["secret_encrypted"])) for r in rows]

    # ------------------------------------------- اعمالِ موجودیِ سفارش (saga، R10-۱)

    def apply_order_stock(self, order_id: int, lines: list) -> bool:
        """موجودیِ یه سفارشِ تاییدشده رو **دقیقاً یک‌بار** اعمال می‌کنه: در *یک* تراکنش، ردیفِ دفتر
        (``stock_ledger``، یکتا به ازای سفارش) + کم‌کردنِ موجودی (محصولاتِ نامحدود رد می‌شن) +
        اختصاصِ کلیدهای دیجیتال. ``lines`` = ``[(product_id, quantity), ...]``.

        ``True`` اگه همین الان اعمال شد؛ ``False`` اگه قبلاً اعمال شده بود (idempotent). موجودیِ
        ناکافی/محصولِ حذف‌شده = ``ProductError`` و *هیچ* تغییری ثبت نمی‌شه (rollback)."""
        conn = self._connection()
        conn.execute("BEGIN IMMEDIATE")
        try:
            if conn.execute("SELECT 1 FROM stock_ledger WHERE order_id=?", (order_id,)).fetchone():
                conn.rollback()
                return False
            conn.execute(
                "INSERT INTO stock_ledger (order_id, applied_ts, lines_json) VALUES (?, ?, ?)",
                (order_id, int(time.time()), json.dumps([[pid, qty] for pid, qty in lines])),
            )
            for product_id, quantity in lines:
                if product_id is None:
                    continue
                row = conn.execute(
                    "SELECT name, stock_quantity, unlimited_stock, delivery_kind FROM products WHERE id=?", (product_id,)
                ).fetchone()
                if row is None:
                    raise ProductError("یکی از محصول‌های سفارش دیگه وجود نداره.")
                if row["unlimited_stock"]:
                    continue
                if row["stock_quantity"] < quantity:
                    raise ProductError(f"«{row['name']}»: موجودی کافی نیست (موجودی فعلی: {row['stock_quantity']}).")
                conn.execute(
                    "UPDATE products SET stock_quantity = stock_quantity - ?, updated_at=datetime('now') WHERE id=?",
                    (quantity, product_id),
                )
                if row["delivery_kind"] == "keys":
                    cur = conn.execute(
                        "UPDATE digital_items SET consumed_order_id=?, consumed_ts=? WHERE id IN "
                        "(SELECT id FROM digital_items WHERE product_id=? AND consumed_order_id IS NULL ORDER BY id LIMIT ?)",
                        (order_id, int(time.time()), product_id, quantity),
                    )
                    if cur.rowcount != quantity:
                        raise ProductError(f"«{row['name']}»: کلیدهای دیجیتالِ باقی‌مانده کافی نیست.")
            conn.commit()
            return True
        except BaseException:
            conn.rollback()
            raise

    def ledger_has(self, order_id: int) -> bool:
        return self._connection().execute("SELECT 1 FROM stock_ledger WHERE order_id=?", (order_id,)).fetchone() is not None
