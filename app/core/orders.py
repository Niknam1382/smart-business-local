"""
ذخیره‌سازی سفارش‌ها — فقط برای حالت «فروشگاه». هر سفارش می‌تونه چند قلم
کالا داشته باشه (``order_items``)، هر قلم با اسم/قیمت لحظه‌ی سفارش ذخیره
می‌شه (نه ارجاع زنده به جدول محصولات) — چون اگه بعداً قیمت محصول عوض بشه یا
محصول غیرفعال/حذف بشه، فاکتور سفارش‌های قبلی نباید تغییر کنه.

جریان وضعیت:

    pending_payment -> paid -> confirmed   (تایید -> موجودی واقعاً کم می‌شه)
                            -> rejected    (صاحب فروشگاه رد کرد -> موجودی دست‌نخورده)
    pending_payment -> cancelled           (قبل از پرداخت لغو شد)
    pending_payment -> expired             (مهلت رزرو تموم شد، پرداخت نشد)
    expired         -> paid                (فقط پرداختِ تاییدشده‌ی درگاه که دیر رسید)

**رزرو موجودی (مهلت پیش‌فرض ۱۵ دقیقه):** از لحظه‌ی ساخته‌شدن سفارش تا
``expires_ts``، تعدادِ سفارش‌شده از «موجودیِ قابل‌فروش» کم حساب می‌شه، بدون این
که ``stock_quantity`` واقعیِ محصول دست بخوره — موجودی واقعی فقط با تایید
کم می‌شه. موجودیِ قابل‌فروش = موجودی − (سفارش‌های pending_payment که هنوز
مهلت دارن + سفارش‌های paid که منتظر تاییدِ صاحب فروشگاهن). ساختنِ سفارش با
تراکنش ``BEGIN IMMEDIATE`` انجام می‌شه تا دو مشتری هم‌زمان نتونن آخرین
قطعه رو هم‌زمان رزرو کنن.

«paid» یعنی پرداخت انجام شده (چه با تایید واقعی API بله‌پی، چه با ادعای
مشتری برای کارت‌به‌کارت) — ولی موجودی هنوز کم نمی‌شه؛ کم‌شدن موجودی فقط با
تایید صریح صاحب فروشگاه (``confirmed``) اتفاق می‌افته، دقیقاً طبق چیزی که
توی MASTER_PROMPT بود، حتی برای بله‌پیِ تایید‌شده — یه گیت دستی نهایی قبل
از کم‌شدن موجودی.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.core import discounts, finance, invoices, migrations
from app.core.paths import get_app_data_dir
from app.core.products import Product, ProductError, ProductStore
from app.core.shop_texts import t

_DB_FILE_NAME = "orders.db"

logger = logging.getLogger(__name__)

STATUS_PENDING_PAYMENT = "pending_payment"
STATUS_PAID = "paid"
STATUS_CONFIRMED = "confirmed"
STATUS_REJECTED = "rejected"
STATUS_CANCELLED = "cancelled"
STATUS_EXPIRED = "expired"

METHOD_BALE_PAY = "bale_pay"
METHOD_CARD_TO_CARD = "card_to_card"
METHOD_ZARINPAL = "zarinpal"

DEFAULT_RESERVE_MINUTES = 15

# ستون‌های اضافه‌شده بعد از فاز ۴ اول — برای دیتابیس‌هایی که قبلاً ساخته شدن (بخشی از مهاجرتِ ۱)
_V05_COLUMNS = {
    "expires_ts": "INTEGER NOT NULL DEFAULT 0",
    "customer_name": "TEXT NOT NULL DEFAULT ''",
    "customer_phone": "TEXT NOT NULL DEFAULT ''",
    "customer_address": "TEXT NOT NULL DEFAULT ''",
    "gateway_ref": "TEXT NOT NULL DEFAULT ''",
    "payment_url": "TEXT NOT NULL DEFAULT ''",
    "paid_late": "INTEGER NOT NULL DEFAULT 0",
}

# موجودیِ «نامحدود» (محصولِ دیجیتال) — هرگز به مشتری نشون داده نمی‌شه
UNLIMITED = 10**9


def _m1_baseline(conn: sqlite3.Connection) -> None:
    """وضعیتِ ۰.۵.۰ (idempotent: روی دیتابیسِ قدیمی هم بی‌خطره)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending_payment',
            payment_method TEXT NOT NULL DEFAULT '',
            payment_reference TEXT NOT NULL DEFAULT '',
            total_irr INTEGER NOT NULL DEFAULT 0,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    for column, ddl in _V05_COLUMNS.items():
        migrations.add_column(conn, "orders", column, ddl)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER,
            product_name TEXT NOT NULL,
            unit_price_irr INTEGER NOT NULL,
            quantity INTEGER NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_chat ON orders(platform, chat_id)")


def _m2_shop_schema(conn: sqlite3.Connection) -> None:
    """۱.۰.۰: اطلاعاتِ چک‌اوتِ قابل‌تنظیم، saga موجودی، تحویلِ دیجیتال، سبد و نشستِ چک‌اوت."""
    migrations.add_column(conn, "orders", "customer_info", "TEXT NOT NULL DEFAULT ''")
    if migrations.add_column(conn, "orders", "inventory_applied", "INTEGER NOT NULL DEFAULT 0"):
        # در ۰.۵.۰ موجودی بلافاصله بعد از تایید کم می‌شد؛ سفارش‌های تاییدشده‌ی قدیمی «اعمال‌شده» حساب می‌شن
        conn.execute("UPDATE orders SET inventory_applied=1 WHERE status='confirmed'")
    if migrations.add_column(conn, "orders", "delivered_ts", "INTEGER NOT NULL DEFAULT 0"):
        conn.execute("UPDATE orders SET delivered_ts=-1 WHERE status='confirmed'")  # قبل از ۱.۰.۰ تحویلِ دیجیتالی نبود
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS carts (
            platform TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            updated_ts INTEGER NOT NULL,
            PRIMARY KEY (platform, chat_id, product_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS checkout_sessions (
            platform TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            step TEXT NOT NULL,
            data_json TEXT NOT NULL DEFAULT '{}',
            expires_ts INTEGER NOT NULL,
            PRIMARY KEY (platform, chat_id)
        )
        """
    )


def _m3_confirmed_by(conn: sqlite3.Connection) -> None:
    """N11: چه کسی سفارش را تأیید کرد (برچسبِ ``نقش:پلتفرم:شناسه``، ``app`` یا ``auto:…``)."""
    if "confirmed_by" not in {row[1] for row in conn.execute("PRAGMA table_info(orders)").fetchall()}:
        conn.execute("ALTER TABLE orders ADD COLUMN confirmed_by TEXT NOT NULL DEFAULT ''")


def _m4_discounts(conn: sqlite3.Connection) -> None:
    """N8: کدِ تخفیف، مصرف، کدِ سبد، ضدِ brute-force، کمپین و ستون‌های مبلغِ سفارش."""
    discounts.migrate(conn)


def _m5_finance(conn: sqlite3.Connection) -> None:
    """N19: دفترِ مالیِ append-only، دسته‌ها، فاکتورها و شمارنده‌ی فاکتور."""
    finance.migrate(conn)
    invoices.migrate(conn)


MIGRATIONS = [_m1_baseline, _m2_shop_schema, _m3_confirmed_by, _m4_discounts, _m5_finance]

_VALID_TRANSITIONS = {
    STATUS_PENDING_PAYMENT: {STATUS_PAID, STATUS_CANCELLED, STATUS_EXPIRED},
    STATUS_PAID: {STATUS_CONFIRMED, STATUS_REJECTED},
    STATUS_CONFIRMED: set(),
    STATUS_REJECTED: set(),
    # پولِ واقعی هیچ‌وقت نباید «گم» بشه: پرداختِ تاییدشده‌ی درگاه/کارت که بعد از
    # لغو یا انقضا می‌رسه روی سفارش ثبت می‌شه (paid_late) تا صاحب فروشگاه
    # تصمیم بگیره (تایید، یا رد + برگشتِ پول).
    STATUS_CANCELLED: {STATUS_PAID},
    STATUS_EXPIRED: {STATUS_PAID},
}


class OrderError(Exception):
    """خطای قابل‌نمایش (فارسی) — مثلاً تغییر وضعیت نامعتبر یا سفارش خالی."""


@dataclass
class OrderItem:
    product_id: Optional[int]
    product_name: str
    unit_price_irr: int
    quantity: int

    @property
    def subtotal_irr(self) -> int:
        return self.unit_price_irr * self.quantity


@dataclass
class Order:
    id: int
    platform: str
    chat_id: str
    status: str
    payment_method: str
    payment_reference: str
    total_irr: int
    note: str
    created_at: str
    updated_at: str
    items: list = field(default_factory=list)  # list[OrderItem]
    expires_ts: int = 0  # زمان یونیکسِ پایانِ رزرو؛ ۰ = بدون مهلت (سفارش‌های قدیمی)
    customer_name: str = ""
    customer_phone: str = ""
    customer_address: str = ""
    gateway_ref: str = ""  # مثلاً authority زرین‌پال
    payment_url: str = ""
    paid_late: bool = False
    customer_info: dict = field(default_factory=dict)  # پاسخ‌های چک‌اوتِ قابل‌تنظیم {id: مقدار}
    inventory_applied: bool = False
    delivered_ts: int = 0
    subtotal_irr: int = 0  # جمعِ اقلام قبل از تخفیف (``total_irr`` = آنچه مشتری می‌پردازه)
    discount_irr: int = 0
    discount_code: str = ""

    def seconds_left(self, now: Optional[float] = None) -> int:
        if self.status != STATUS_PENDING_PAYMENT or not self.expires_ts:
            return 0
        return max(0, int(self.expires_ts - (now if now is not None else time.time())))


def _load_info(raw: str) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _row_to_order(r: sqlite3.Row, items: list) -> Order:
    return Order(
        id=r["id"],
        platform=r["platform"],
        chat_id=r["chat_id"],
        status=r["status"],
        payment_method=r["payment_method"],
        payment_reference=r["payment_reference"],
        total_irr=r["total_irr"],
        note=r["note"],
        created_at=r["created_at"],
        updated_at=r["updated_at"],
        items=items,
        expires_ts=r["expires_ts"],
        customer_name=r["customer_name"],
        customer_phone=r["customer_phone"],
        customer_address=r["customer_address"],
        gateway_ref=r["gateway_ref"],
        payment_url=r["payment_url"],
        paid_late=bool(r["paid_late"]),
        customer_info=_load_info(r["customer_info"]),
        inventory_applied=bool(r["inventory_applied"]),
        delivered_ts=int(r["delivered_ts"]),
        subtotal_irr=int(r["subtotal_irr"]) or int(r["total_irr"]),
        discount_irr=int(r["discount_irr"]),
        discount_code=r["discount_code"],
    )


class OrderStore:
    def __init__(self, db_path: Optional[Path] = None, product_store: Optional[ProductStore] = None):
        self.db_path = db_path or (get_app_data_dir() / _DB_FILE_NAME)
        self._local = threading.local()
        self._products = product_store or ProductStore()
        self._create_lock = threading.Lock()
        self._confirm_listeners: list = []  # N19: بعد از اعمالِ موجودی (دفترِ مالی/فاکتور)؛ خطایشان تایید را خراب نمی‌کند
        self._anonymize_listeners: list = []  # N19: بعد از ناشناس‌سازیِ فاکتورها؛ ورودی = شماره‌ی فاکتورها (حذفِ PDF)

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

    def connection(self) -> sqlite3.Connection:
        """اتصالِ همین تردِ دیتابیسِ سفارش‌ها (برای ماژول‌های هم‌خانواده مثلِ سبد/چک‌اوت)."""
        return self._connection()

    # ---------------------------------------------------------------- ساخت

    # ------------------------------------------------------- موجودیِ قابل‌فروش

    def reserved_quantity(self, product_id: int, exclude_order_id: Optional[int] = None, now: Optional[float] = None) -> int:
        """مجموعِ تعدادِ رزروشده‌ی این محصول: سفارش‌های pending_payment که
        مهلتشون تموم نشده + سفارش‌های paid (پرداخت‌شده، منتظر تایید) + سفارش‌های
        confirmed که saga هنوز موجودی‌شون رو اعمال نکرده (پنجره‌ی «موجودیِ دوبرابر» بسته می‌شه).
        سفارش‌های قدیمی بدون مهلت (``expires_ts=0``) هم تا وقتی pending هستن رزرو حساب می‌شن."""
        now = time.time() if now is None else now
        row = self._connection().execute(
            """
            SELECT COALESCE(SUM(i.quantity), 0) AS q
            FROM order_items i JOIN orders o ON o.id = i.order_id
            WHERE i.product_id = ?
              AND (o.status = 'paid'
                   OR (o.status = 'confirmed' AND o.inventory_applied = 0)
                   OR (o.status = 'pending_payment' AND (o.expires_ts = 0 OR o.expires_ts > ?)))
              AND (? IS NULL OR o.id != ?)
            """,
            (product_id, now, exclude_order_id, exclude_order_id),
        ).fetchone()
        return int(row["q"])

    def available_quantity(self, product_id: int, now: Optional[float] = None) -> int:
        """موجودیِ واقعاً قابل‌فروش (موجودی − رزروها)؛ ۰ اگه محصول نباشه/غیرفعال."""
        product = self._products.get(product_id)
        if product is None:
            return 0
        return self._sellable(product, now=now)

    def _sellable(self, product: Product, exclude_order_id: Optional[int] = None, now: Optional[float] = None) -> int:
        """موجودیِ قابل‌فروشِ یه محصول: نامحدود = ``UNLIMITED``؛ وگرنه موجودی − رزروها."""
        if product.unlimited_stock:
            return UNLIMITED
        return max(0, product.stock_quantity - self.reserved_quantity(product.id, exclude_order_id=exclude_order_id, now=now))

    # ---------------------------------------------------------------- ساخت

    def create(
        self,
        platform: str,
        chat_id: str,
        items: list,
        payment_method: str = "",
        note: str = "",
        reserve_minutes: int = DEFAULT_RESERVE_MINUTES,
        customer_name: str = "",
        customer_phone: str = "",
        customer_address: str = "",
        customer_info: Optional[dict] = None,
        discount_code: str = "",
        auto_discounts: bool = False,
    ) -> int:
        """``items``: لیستی از (product_id, quantity). اسم/قیمت از خودِ محصول
        در همین لحظه کپی می‌شه (snapshot) و تعداد برای ``reserve_minutes``
        دقیقه رزرو می‌شه. اگه موجودیِ قابل‌فروشِ هر قلم کافی نباشه، ``OrderError``
        (فارسی، با عددِ موجودی) می‌ده و هیچ سفارشی ساخته نمی‌شه.

        N8: ``discount_code`` (کدِ دستیِ مشتری) و/یا ``auto_discounts`` داخلِ *همین* تراکنش اعمال و مصرف می‌شن؛
        ``total_irr`` مبلغِ نهایی (بعد از تخفیف) است. خطای کد ⇒ ``DiscountError`` و هیچ سفارشی ساخته نمی‌شه."""
        if not items:
            raise OrderError("سفارش نمی‌تونه خالی باشه.")
        # یه محصول ممکنه دو بار تو لیست بیاد — ادغامش می‌کنیم تا چکِ موجودی دقیق باشه
        merged: dict = {}
        for product_id, quantity in items:
            if quantity <= 0:
                raise OrderError("تعداد باید حداقل ۱ باشه.")
            merged[product_id] = merged.get(product_id, 0) + quantity

        conn = self._connection()
        with self._create_lock:
            conn.execute("BEGIN IMMEDIATE")  # قفلِ نوشتن: چکِ موجودی و درج، یک مرحله‌ی تفکیک‌ناپذیرن
            try:
                resolved = []
                cart_lines = []
                total = 0
                for product_id, quantity in merged.items():
                    product = self._products.get(product_id)
                    if product is None:
                        raise OrderError("یکی از محصول‌های انتخاب‌شده دیگه وجود نداره.")
                    available = self._sellable(product)
                    if quantity > available:
                        if available == 0:
                            raise OrderError(f"«{product.name}» الان موجود نیست (یا کاملاً برای مشتری‌های دیگه رزرو شده).")
                        raise OrderError(f"از «{product.name}» فقط {available} عدد قابل سفارشه.")
                    resolved.append((product.id, product.name, product.price_irr, quantity))
                    cart_lines.append(discounts.CartLine(product.id, product.name, product.category or "", product.price_irr, quantity))
                    total += product.price_irr * quantity

                subtotal = total
                resolution = None
                if discount_code or auto_discounts:
                    resolution = discounts.resolve(conn, platform, chat_id, cart_lines, discount_code or None, auto=auto_discounts)
                    total = resolution.final
                expires_ts = int(time.time() + reserve_minutes * 60) if reserve_minutes and reserve_minutes > 0 else 0
                cur = conn.execute(
                    """
                    INSERT INTO orders (platform, chat_id, status, payment_method, total_irr, note,
                                        expires_ts, customer_name, customer_phone, customer_address, customer_info,
                                        subtotal_irr, discount_irr, discount_code)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (platform, chat_id, STATUS_PENDING_PAYMENT, payment_method, total, note,
                     expires_ts, customer_name, customer_phone, customer_address,
                     json.dumps(customer_info, ensure_ascii=False) if customer_info else "",
                     subtotal, resolution.discount if resolution else 0, resolution.codes_text if resolution else ""),
                )
                order_id = cur.lastrowid
                conn.executemany(
                    """
                    INSERT INTO order_items (order_id, product_id, product_name, unit_price_irr, quantity)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [(order_id, pid, name, price, qty) for pid, name, price, qty in resolved],
                )
                if resolution is not None and resolution.applied:
                    discounts.consume(conn, order_id, platform, str(chat_id), resolution)
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return order_id

    # -------------------------------------------------------------- خواندن

    def get(self, order_id: int) -> Optional[Order]:
        conn = self._connection()
        row = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if row is None:
            return None
        item_rows = conn.execute(
            "SELECT product_id, product_name, unit_price_irr, quantity FROM order_items WHERE order_id=?",
            (order_id,),
        ).fetchall()
        items = [
            OrderItem(
                product_id=r["product_id"],
                product_name=r["product_name"],
                unit_price_irr=r["unit_price_irr"],
                quantity=r["quantity"],
            )
            for r in item_rows
        ]
        return _row_to_order(row, items)

    def list(self, status: Optional[str] = None, platform: Optional[str] = None) -> list:
        query = "SELECT id FROM orders"
        clauses, params = [], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if platform:
            clauses.append("platform = ?")
            params.append(platform)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id DESC"
        ids = [r["id"] for r in self._connection().execute(query, params).fetchall()]
        return [self.get(i) for i in ids]

    def set_confirmed_by(self, order_id: int, who: str) -> None:
        conn = self._connection()
        conn.execute("UPDATE orders SET confirmed_by = ? WHERE id = ?", (str(who)[:96], int(order_id)))
        conn.commit()

    def confirmed_by(self, order_id: int) -> str:
        row = self._connection().execute("SELECT confirmed_by FROM orders WHERE id = ?", (int(order_id),)).fetchone()
        return row["confirmed_by"] if row else ""

    def customer_stats(self) -> dict:
        """``{(platform, chat_id): (تعدادِ سفارشِ معتبر، جمعِ مبلغ، زمانِ آخرین سفارش)}`` — فقط سفارش‌های پرداخت‌شده/تأییدشده.
        (در انتظارِ پرداخت، ردشده، لغو و منقضی جزوِ خریدِ مشتری حساب نمی‌شن.)"""
        rows = self._connection().execute(
            "SELECT platform, chat_id, COUNT(*) AS n, COALESCE(SUM(total_irr), 0) AS total, "
            "COALESCE(MAX(CAST(strftime('%s', created_at) AS INTEGER)), 0) AS last "
            "FROM orders WHERE status IN (?, ?) GROUP BY platform, chat_id",
            (STATUS_PAID, STATUS_CONFIRMED),
        ).fetchall()
        return {(r["platform"], r["chat_id"]): (int(r["n"]), int(r["total"]), int(r["last"])) for r in rows}

    def list_for_chat(self, platform: str, chat_id: str) -> list:
        ids = [
            r["id"]
            for r in self._connection()
            .execute(
                "SELECT id FROM orders WHERE platform=? AND chat_id=? ORDER BY id DESC", (platform, chat_id)
            )
            .fetchall()
        ]
        return [self.get(i) for i in ids]

    # ------------------------------------------------------------- وضعیت

    def _transition(self, order_id: int, new_status: str, **extra_columns) -> None:
        """تغییرِ وضعیت به‌صورت **اتمیک**: ``UPDATE ... WHERE status = <وضعیت فعلی>``. اگه
        بین چک و نوشتن، کسِ دیگه‌ای (مثلاً رسیدنِ پرداخت هم‌زمان با لغوِ مشتری) وضعیت رو
        عوض کرده باشه، هیچی نوشته نمی‌شه و ``OrderError`` می‌ده — نه اینکه وضعیتِ
        تازه بی‌صدا رونویسی بشه."""
        conn = self._connection()
        row = conn.execute("SELECT status FROM orders WHERE id=?", (order_id,)).fetchone()
        if row is None:
            raise OrderError("این سفارش دیگه وجود نداره.")
        current = row["status"]
        if new_status not in _VALID_TRANSITIONS.get(current, set()):
            raise OrderError(f"نمی‌شه سفارش رو از «{current}» به «{new_status}» برد.")
        set_clause = ", ".join([*(f"{k}=?" for k in extra_columns), "status=?", "updated_at=datetime('now')"])
        cur = conn.execute(
            f"UPDATE orders SET {set_clause} WHERE id=? AND status=?",
            (*extra_columns.values(), new_status, order_id, current),
        )
        if cur.rowcount == 1:
            discounts.on_transition(conn, order_id, current, new_status)  # N8: مصرفِ کد با لغو/انقضا/رد آزاد می‌شه
        conn.commit()
        if cur.rowcount != 1:
            raise OrderError("وضعیتِ این سفارش همین الان تغییر کرد؛ دوباره نگاه کن.")

    def mark_paid(self, order_id: int, payment_method: str, payment_reference: str = "") -> None:
        """سفارش رو «پرداخت‌شده» می‌کنه. اگه سفارش قبلاً منقضی شده بود (پرداختِ
        تاییدشده‌ی درگاه که بعد از پایان مهلت رسید)، علامت ``paid_late`` هم
        می‌خوره تا صاحب فروشگاه بدونه موجودی ممکنه دیگه کافی نباشه."""
        current = self.get(order_id)
        extra = {}
        if current is not None and current.status in (STATUS_EXPIRED, STATUS_CANCELLED):
            extra["paid_late"] = 1
        self._transition(
            order_id, STATUS_PAID, payment_method=payment_method, payment_reference=payment_reference, **extra
        )

    def replace_items(self, order_id: int, items: list, reserve_minutes: int = DEFAULT_RESERVE_MINUTES) -> None:
        """اقلام یه سفارشِ هنوز-پرداخت‌نشده رو (یکجا، تراکنشی) عوض می‌کنه: موجودی با
        حذفِ رزروِ خودِ همین سفارش دوباره چک می‌شه، مبلغ بازمحاسبه و مهلتِ رزرو
        از نو شروع می‌شه. روش/لینکِ پرداختِ قبلی باطل می‌شه (مبلغ عوض شده — لینکِ
        قدیمی نباید با مبلغِ قدیمی قابل‌پرداخت بمونه). اگه موجودی کافی نباشه،
        ``OrderError`` می‌ده و سفارش دست‌نخورده می‌مونه."""
        if not items:
            raise OrderError("سفارش نمی‌تونه خالی باشه.")
        merged: dict = {}
        for product_id, quantity in items:
            if quantity <= 0:
                raise OrderError("تعداد باید حداقل ۱ باشه.")
            merged[product_id] = merged.get(product_id, 0) + quantity

        conn = self._connection()
        with self._create_lock:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT status, expires_ts, payment_url, gateway_ref FROM orders WHERE id=?", (order_id,)).fetchone()
                if row is None:
                    raise OrderError("این سفارش دیگه وجود نداره.")
                if row["status"] != STATUS_PENDING_PAYMENT or (row["expires_ts"] and row["expires_ts"] <= time.time()):
                    raise OrderError("این سفارش دیگه قابل‌ویرایش نیست (پرداخت‌شده، لغو، یا مهلتش تموم شده).")
                if (row["payment_url"] or row["gateway_ref"]):
                    raise OrderError(
                        "برای این سفارش لینک پرداخت آنلاین ساخته شده و با تغییرِ مبلغ، لینکِ قبلی همچنان "
                        "قابل‌پرداخته؛ برای تغییر، اول این سفارش رو لغو کن و سفارشِ جدید ثبت کن."
                    )
                resolved, total = [], 0
                for product_id, quantity in merged.items():
                    product = self._products.get(product_id)
                    if product is None:
                        raise OrderError("یکی از محصول‌های انتخاب‌شده دیگه وجود نداره.")
                    available = self._sellable(product, exclude_order_id=order_id)
                    if quantity > available:
                        if available == 0:
                            raise OrderError(f"«{product.name}» الان موجود نیست (یا کاملاً برای مشتری‌های دیگه رزرو شده).")
                        raise OrderError(f"از «{product.name}» فقط {available} عدد قابل سفارشه.")
                    resolved.append((product.id, product.name, product.price_irr, quantity))
                    total += product.price_irr * quantity
                expires_ts = int(time.time() + reserve_minutes * 60) if reserve_minutes and reserve_minutes > 0 else 0
                conn.execute("DELETE FROM order_items WHERE order_id=?", (order_id,))
                conn.executemany(
                    "INSERT INTO order_items (order_id, product_id, product_name, unit_price_irr, quantity) VALUES (?, ?, ?, ?, ?)",
                    [(order_id, pid, name, price, qty) for pid, name, price, qty in resolved],
                )
                discounts.release(conn, order_id)  # اقلام عوض شد؛ تخفیفِ قبلی دیگه معتبر نیست
                conn.execute(
                    """UPDATE orders SET total_irr=?, subtotal_irr=?, discount_irr=0, discount_code='', expires_ts=?, payment_method='',
                       gateway_ref='', payment_url='', updated_at=datetime('now') WHERE id=?""",
                    (total, total, expires_ts, order_id),
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def set_payment_info(
        self, order_id: int, payment_method: str, gateway_ref: str = "", payment_url: str = ""
    ) -> None:
        """روش پرداختِ انتخاب‌شده (و authority/لینکِ درگاه) رو روی سفارش ثبت
        می‌کنه، بدون تغییر وضعیت. فقط برای سفارش‌های هنوز-پرداخت‌نشده."""
        order = self.get(order_id)
        if order is None:
            raise OrderError("این سفارش دیگه وجود نداره.")
        if order.status != STATUS_PENDING_PAYMENT:
            raise OrderError(f"این سفارش «{order.status}» هست و دیگه روش پرداختش قابل‌تغییر نیست.")
        conn = self._connection()
        conn.execute(
            "UPDATE orders SET payment_method=?, gateway_ref=?, payment_url=?, updated_at=datetime('now') WHERE id=?",
            (payment_method, gateway_ref, payment_url, order_id),
        )
        conn.commit()

    _CLOSED = (STATUS_CONFIRMED, STATUS_REJECTED, STATUS_CANCELLED, STATUS_EXPIRED)
    _PII_PRESENT = "(customer_name != '' OR customer_phone != '' OR customer_address != '' OR customer_info != '' OR note != '')"

    def anonymize_closed(self, days: int) -> int:
        """نگه‌داریِ محدود: مشخصاتِ مشتری (نام/موبایل/آدرس/اطلاعاتِ چک‌اوت/توضیحات) سفارش‌های *بسته‌شده*‌ی قدیمی‌تر از
        ``days`` روز پاک می‌شه؛ مبالغ/اقلام برای حسابداری می‌مونن. سفارش‌های باز دست‌نخورده‌ان."""
        if days <= 0:
            return 0
        marks = ", ".join("?" for _ in self._CLOSED)
        conn = self._connection()
        ids = [r["id"] for r in conn.execute(
            f"SELECT id FROM orders WHERE status IN ({marks}) AND {self._PII_PRESENT} AND updated_at < datetime('now', ?)",
            (*self._CLOSED, f"-{int(days)} day"),
        ).fetchall()]
        cur = conn.execute(
            f"UPDATE orders SET customer_name='', customer_phone='', customer_address='', customer_info='', note='' "
            f"WHERE status IN ({marks}) AND {self._PII_PRESENT} AND updated_at < datetime('now', ?)",
            (*self._CLOSED, f"-{int(days)} day"),
        )
        conn.commit()
        self._anonymize_invoices(ids)
        return cur.rowcount

    def anonymize_chat(self, platform: str, chat_id: str) -> int:
        """``/forget``: مشخصاتِ شخصیِ سفارش‌های *بسته‌شده*‌ی همین چت پاک می‌شه (سفارش‌های باز دست‌نخورده)."""
        marks = ", ".join("?" for _ in self._CLOSED)
        conn = self._connection()
        # فاکتورها را برای *همه‌ی* سفارش‌های همین چت ناشناس می‌کنیم (فاکتور فقط برای سفارشِ تاییدشده/بسته است)
        ids = [r["id"] for r in conn.execute(
            f"SELECT id FROM orders WHERE platform=? AND chat_id=? AND status IN ({marks})", (platform, str(chat_id), *self._CLOSED)
        ).fetchall()]
        cur = conn.execute(
            f"UPDATE orders SET customer_name='', customer_phone='', customer_address='', customer_info='', note='' "
            f"WHERE platform=? AND chat_id=? AND status IN ({marks}) AND {self._PII_PRESENT}",
            (platform, str(chat_id), *self._CLOSED),
        )
        conn.commit()
        self._anonymize_invoices(ids)
        return cur.rowcount

    def set_reference(self, order_id: int, reference: str) -> bool:
        """شماره پیگیری/۴ رقم آخرِ کارتِ واریز (متنِ مشتری؛ کوتاه و بدونِ کاراکترِ کنترلی) روی سفارشِ در انتظار/پرداخت‌شده."""
        clean = "".join(ch for ch in (reference or "") if ch >= " ").strip()[:100]
        if not clean:
            return False
        conn = self._connection()
        cur = conn.execute(
            "UPDATE orders SET payment_reference=?, updated_at=datetime('now') WHERE id=? AND status IN (?, ?, ?)",
            (clean, order_id, STATUS_PENDING_PAYMENT, STATUS_PAID, STATUS_EXPIRED),
        )
        conn.commit()
        return cur.rowcount == 1

    def update_customer(self, order_id: int, name: str = "", phone: str = "", address: str = "", note: str = "") -> None:
        """مشخصاتِ تحویل (هر چی خالی نباشه جایگزین می‌شه). روی هر وضعیتی جز
        لغو/رد/منقضی مجازه — مثلاً مشتری بعد از پرداخت آدرسش رو کامل می‌کنه."""
        order = self.get(order_id)
        if order is None:
            raise OrderError("این سفارش دیگه وجود نداره.")
        if order.status in (STATUS_CANCELLED, STATUS_REJECTED, STATUS_EXPIRED):
            raise OrderError("این سفارش بسته شده و مشخصاتش قابل‌تغییر نیست.")
        fields = {"customer_name": name, "customer_phone": phone, "customer_address": address, "note": note}
        fields = {k: v.strip() for k, v in fields.items() if v and v.strip()}
        if not fields:
            return
        conn = self._connection()
        set_clause = ", ".join(f"{k}=?" for k in fields)
        conn.execute(
            f"UPDATE orders SET {set_clause}, updated_at=datetime('now') WHERE id=?", (*fields.values(), order_id)
        )
        conn.commit()

    def expire_stale(self, now: Optional[float] = None) -> list:
        """همه‌ی سفارش‌های pending_payment که مهلتشون تموم شده رو «منقضی» می‌کنه
        (رزروشون آزاد می‌شه) و لیستشون رو برمی‌گردونه تا مشتری مطلع بشه. امنِ
        صدازدنِ مکرر و از چند ترد."""
        now = time.time() if now is None else now
        rows = self._connection().execute(
            "SELECT id FROM orders WHERE status=? AND expires_ts > 0 AND expires_ts <= ?",
            (STATUS_PENDING_PAYMENT, now),
        ).fetchall()
        expired = []
        for r in rows:
            try:
                self._transition(r["id"], STATUS_EXPIRED)
            except OrderError:
                continue  # هم‌زمان پرداخت/لغو شده
            order = self.get(r["id"])
            if order is not None:
                expired.append(order)
        return expired

    def recent_activity(self, platform: str, chat_id: str, now: Optional[float] = None) -> tuple:
        """(تعداد سفارش ساخته‌شده در ۱ ساعتِ اخیر، تعداد سفارشِ بدونِ پرداختِ منقضی‌شده در ۲۴ ساعتِ
        اخیر) برای این مشتری — پایه‌ی محدودیتِ «احتکارِ موجودی» (ساختنِ پیاپیِ سفارش برای
        بلوکه‌کردنِ موجودی بدونِ هیچ قصدِ خرید)."""
        now = time.time() if now is None else now
        conn = self._connection()
        hour = conn.execute(
            "SELECT COUNT(*) AS n FROM orders WHERE platform=? AND chat_id=? AND created_at >= datetime(?, 'unixepoch')",
            (platform, chat_id, now - 3600),
        ).fetchone()["n"]
        day = conn.execute(
            """SELECT COUNT(*) AS n FROM orders WHERE platform=? AND chat_id=? AND status='expired'
               AND payment_reference='' AND created_at >= datetime(?, 'unixepoch')""",
            (platform, chat_id, now - 86400),
        ).fetchone()["n"]
        return int(hour), int(day)

    def active_for_chat(self, platform: str, chat_id: str, now: Optional[float] = None) -> list:
        """سفارش‌های «زنده»‌ی این مشتری: pending با مهلتِ باقی‌مانده + paid."""
        now = time.time() if now is None else now
        return [
            o
            for o in self.list_for_chat(platform, chat_id)
            if o.status == STATUS_PAID
            or (o.status == STATUS_PENDING_PAYMENT and (o.expires_ts == 0 or o.expires_ts > now))
        ]

    def pending_gateway_orders(self, method: str, grace_seconds: int = 3600, now: Optional[float] = None) -> list:
        """سفارش‌های درگاهیِ هنوز-پرداخت‌نشده که باید استعلام بشن: pending، و حتی اگه
        تازه منقضی یا **لغو** شده، تا ``grace_seconds`` — مشتری ممکنه دقیقه‌ی آخر (یا بعد از
        لغو، با لینکی که هنوز دستشه) پرداخت کرده باشه و پولِ واقعی نباید گم بشه."""
        now = time.time() if now is None else now
        rows = self._connection().execute(
            """
            SELECT id FROM orders
            WHERE payment_method=? AND gateway_ref != ''
              AND status IN ('pending_payment', 'expired', 'cancelled')
              AND (expires_ts = 0 OR expires_ts > ?)
            ORDER BY id
            """,
            (method, now - grace_seconds),
        ).fetchall()
        return [self.get(r["id"]) for r in rows]

    def confirm(self, order_id: int) -> None:
        """تایید صاحب فروشگاه — تنها جایی که موجودی واقعاً کم می‌شه. اگه موجودیِ هر قلم
        کافی نباشه، کل تایید لغو می‌شه (هیچ موجودی‌ای کم نمی‌شه، وضعیت به «پرداخت‌شده»
        برمی‌گرده) و خطا می‌ده — نه نصفه‌کاره.

        **اتمیک و امن در برابر تاییدِ هم‌زمان:** اول سفارش با یه ``UPDATE ... WHERE
        status='paid'`` «ادعا» می‌شه؛ فقط یکی از چند تاییدِ هم‌زمان (دابل‌کلیک، تایید
        خودکار + تایید دستی، فرمانِ مالک) برنده‌ست و بقیه خطا می‌گیرن *قبل از* اینکه به
        موجودی دست بزنن."""
        order = self.get(order_id)
        if order is None:
            raise OrderError("این سفارش دیگه وجود نداره.")
        if order.status != STATUS_PAID:
            raise OrderError(f"فقط سفارش «پرداخت‌شده» قابل تاییده (وضعیت فعلی: {order.status}).")
        conn = self._connection()
        # (الف) ادعای اتمیکِ وضعیت — فقط یکی از چند تاییدِ هم‌زمان برنده‌ست
        claim = conn.execute(
            "UPDATE orders SET status=?, inventory_applied=0, updated_at=datetime('now') WHERE id=? AND status=?",
            (STATUS_CONFIRMED, order_id, STATUS_PAID),
        )
        conn.commit()
        if claim.rowcount != 1:
            raise OrderError("این سفارش همین الان توسط کسِ دیگه‌ای تایید یا تغییر داده شد.")
        # (ب) موجودی + دفتر (ledger) در *یک* تراکنشِ products.db — دوبار اعمال نمی‌شه (یکتا به ازای سفارش)
        try:
            self._products.apply_order_stock(order_id, self._stock_lines(order))
        except ProductError as exc:
            self._revert_to_paid(order_id)  # جبران: هیچ موجودی‌ای کم نشده (rollback)
            raise OrderError(str(exc)) from exc
        # (پ) علامت‌گذاریِ پایانِ saga. اگه اینجا کرش شه، recover_inventory() (ledger) کار رو کامل می‌کنه
        self._mark_inventory_applied(order_id)
        self._notify_confirmed(order_id)

    def add_confirm_listener(self, fn) -> None:
        """N19: ``fn(order)`` بعد از تاییدِ کاملِ سفارش (خارج از ساگا). ترمیمِ شکست‌ها با ``finance.post_missing`` است."""
        self._confirm_listeners.append(fn)

    def add_anonymize_listener(self, fn) -> None:
        self._anonymize_listeners.append(fn)

    def _notify_confirmed(self, order_id: int) -> None:
        if not self._confirm_listeners:
            return
        order = self.get(order_id)
        if order is None:
            return
        for fn in list(self._confirm_listeners):
            try:
                fn(order)
            except Exception:  # noqa: BLE001 — دفتر/فاکتور نباید تاییدِ انجام‌شده را خراب کنه
                logger.exception("شنونده‌ی تاییدِ سفارش %s", order_id)

    def _anonymize_invoices(self, order_ids: list) -> None:
        if not order_ids:
            return
        numbers = invoices.InvoiceStore(self).anonymize_orders(order_ids)
        for fn in list(self._anonymize_listeners):
            try:
                fn(numbers)
            except Exception:  # noqa: BLE001
                logger.exception("حذفِ PDFِ فاکتورهای ناشناس‌شده")

    @staticmethod
    def _stock_lines(order: Order) -> list:
        return [(i.product_id, i.quantity) for i in order.items if i.product_id is not None]

    def _mark_inventory_applied(self, order_id: int) -> None:
        conn = self._connection()
        conn.execute("UPDATE orders SET inventory_applied=1, updated_at=datetime('now') WHERE id=?", (order_id,))
        conn.commit()
        self._settle_delivery_flag(order_id)

    def _settle_delivery_flag(self, order_id: int) -> None:
        """سفارشی که چیزِ دیجیتالی برای تحویل نداره ``delivered_ts=-1`` می‌گیره تا حلقه‌ی تلاشِ مجدد اسکنش نکنه."""
        order = self.get(order_id)
        if order is None:
            return
        for item in order.items:
            product = self._products.get(item.product_id) if item.product_id is not None else None
            if product is not None and product.delivery_kind != "none":
                return
        conn = self._connection()
        conn.execute("UPDATE orders SET delivered_ts=-1 WHERE id=? AND delivered_ts=0", (order_id,))
        conn.commit()

    def pending_deliveries(self, min_age_seconds: int = 0) -> list:
        """شناسه‌ی سفارش‌های تاییدشده‌ای که تحویلِ دیجیتالشون هنوز انجام نشده (برای تلاشِ مجدد)."""
        rows = self._connection().execute(
            "SELECT id FROM orders WHERE status=? AND inventory_applied=1 AND delivered_ts=0 "
            "AND CAST(strftime('%s', updated_at) AS INTEGER) <= CAST(strftime('%s','now') AS INTEGER) - ? ORDER BY id LIMIT 50",
            (STATUS_CONFIRMED, int(min_age_seconds)),
        ).fetchall()
        return [r["id"] for r in rows]

    def _revert_to_paid(self, order_id: int) -> bool:
        conn = self._connection()
        cur = conn.execute(
            "UPDATE orders SET status=?, updated_at=datetime('now') WHERE id=? AND status=? AND inventory_applied=0",
            (STATUS_PAID, order_id, STATUS_CONFIRMED),
        )
        conn.commit()
        return cur.rowcount == 1

    def recover_inventory(self, min_age_seconds: int = 0) -> list:
        """سفارش‌های ``confirmed`` که saga‌شون وسطِ راه قطع شده (کرش بینِ تایید و اعمالِ موجودی) رو کامل
        می‌کنه — idempotent (دفترِ ledger). هنگامِ شروعِ برنامه و در حلقه‌ی نگهداری صدا زده می‌شه.
        ``[(order_id, outcome, detail)]`` برمی‌گردونه؛ ``outcome``: ``recovered`` | ``already`` |
        ``insufficient`` (موجودی کافی نبود → سفارش به «پرداخت‌شده» برگشت؛ مالک باید تصمیم بگیره)."""
        conn = self._connection()
        rows = conn.execute(
            "SELECT id FROM orders WHERE status=? AND inventory_applied=0 "
            "AND CAST(strftime('%s', updated_at) AS INTEGER) <= CAST(strftime('%s','now') AS INTEGER) - ? ORDER BY id",
            (STATUS_CONFIRMED, int(min_age_seconds)),
        ).fetchall()
        results: list = []
        for r in rows:
            order = self.get(r["id"])
            if order is None or order.status != STATUS_CONFIRMED or order.inventory_applied:
                continue
            try:
                applied = self._products.apply_order_stock(order.id, self._stock_lines(order))
            except ProductError as exc:
                if self._revert_to_paid(order.id):
                    results.append((order.id, "insufficient", str(exc)))
                continue
            self._mark_inventory_applied(order.id)
            self._notify_confirmed(order.id)
            results.append((order.id, "recovered" if applied else "already", ""))
        return results

    def count_by_status(self, status: str) -> int:
        """تعدادِ سفارش‌های یه وضعیت (مثلاً ``paid`` = منتظرِ تاییدِ مالک) — برای نشانگرِ «نیاز به توجه»."""
        row = self._connection().execute("SELECT COUNT(*) AS n FROM orders WHERE status=?", (status,)).fetchone()
        return int(row["n"])

    def mark_delivered(self, order_id: int) -> bool:
        """علامتِ «تحویلِ دیجیتال انجام شد» — ``True`` فقط برای بارِ اول (idempotent)."""
        conn = self._connection()
        cur = conn.execute(
            "UPDATE orders SET delivered_ts=?, updated_at=datetime('now') WHERE id=? AND delivered_ts=0",
            (int(time.time()), order_id),
        )
        conn.commit()
        return cur.rowcount == 1

    def update_customer_info(self, order_id: int, info: dict) -> None:
        """پاسخ‌های چک‌اوت رو با اطلاعاتِ قبلی ادغام می‌کنه (روی سفارش‌های بسته مجاز نیست)."""
        order = self.get(order_id)
        if order is None:
            raise OrderError("این سفارش دیگه وجود نداره.")
        if order.status in (STATUS_CANCELLED, STATUS_REJECTED, STATUS_EXPIRED):
            raise OrderError("این سفارش بسته شده و مشخصاتش قابل‌تغییر نیست.")
        merged = {**order.customer_info, **info}
        conn = self._connection()
        conn.execute(
            "UPDATE orders SET customer_info=?, updated_at=datetime('now') WHERE id=?",
            (json.dumps(merged, ensure_ascii=False), order_id),
        )
        conn.commit()

    def reject(self, order_id: int) -> None:
        self._transition(order_id, STATUS_REJECTED)

    def cancel(self, order_id: int) -> None:
        self._transition(order_id, STATUS_CANCELLED)


def build_order_summary_text(order: Order) -> str:
    """متن فارسیِ خلاصه‌ی سفارش — هم توی پیام تاییدِ خودکار به مشتری استفاده
    می‌شه، هم می‌شه برای نمایش/کپی جای دیگه به کار برد."""
    lines = [t("order.head", order_id=order.id)]
    for item in order.items:
        lines.append(t("order.item", name=item.product_name, qty=item.quantity, amount=f"{item.subtotal_irr:,}"))
    if order.discount_irr > 0:
        lines.append(t("order.subtotal", amount=f"{order.subtotal_irr:,}"))
        lines.append(t("order.discount", amount=f"{order.discount_irr:,}"))
    lines.append(t("order.total", amount=f"{order.total_irr:,}"))
    return "\n".join(lines)


def build_order_rejected_text(order: Order) -> str:
    """پیامِ خودکار وقتی صاحب فروشگاه سفارشِ *پرداخت‌شده* رو رد می‌کنه. مشتری پول داده؛ بی‌خبر
    گذاشتنش بدترین حالته، پس حتماً می‌فهمه چی شده و تکلیفِ پولش چیه."""
    return (
        t("order.rejected_head", order_id=order.id) + "\n\n" + build_order_summary_text(order) + "\n\n" + t("order.rejected_tail")
    )


def build_order_confirmed_text(order: Order) -> str:
    """پیامی که بعد از تاییدِ صاحب فروشگاه خودکار برای مشتری فرستاده می‌شه —
    صرف‌نظر از روش پرداخت (کارت‌به‌کارت یا بله‌پی)، چون این لحظه (تاییدِ
    دستی) همیشه یکیه."""
    return t("order.confirmed_head") + "\n\n" + build_order_summary_text(order) + "\n\n" + t("order.confirmed_tail")
