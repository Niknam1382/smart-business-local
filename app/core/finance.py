"""
دفترِ مالیِ سادهٔ یک‌فروشگاهی (N19). **ابزارِ کمکی است نه جایگزینِ حسابدارِ رسمی.**

جدول‌ها داخلِ ``orders.db`` (همان پشتیبان/بازیابی/مهاجرت؛ ``orders._m5_finance``).

- ``ledger_entries`` **append-only** است (تریگرِ SQLite: حذف ممنوع؛ تنها تغییرِ مجاز = زدنِ ``reversed_by_id`` برای
  یک‌بار). اصلاح = *reversal* (ردیفِ تازه با ``reverses_id``؛ علامتِ −۱ در جمع).
- ثبتِ خودکار از سفارشِ تاییدشده: ``post_order`` **idempotent** با ایندکسِ یکتای ``(ref_type, ref_id, auto_key)``،
  *خارج از ساگای موجودی*؛ شکست = ``post_missing`` (شروعِ برنامه/حلقه‌ی نگهداری) دوباره امتحان می‌کنه.
- پول فقط عددِ صحیحِ ریال (هرگز float)؛ نرخ‌ها به‌صورتِ basis point (۱٪ = ۱۰۰).
- هر آمار از داده‌ی اصلی (سفارش‌ها + دفتر) محاسبه می‌شه، نه شمارنده‌ی جدا.
"""

from __future__ import annotations

import csv
import io
import re
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Optional

from app.core import jalali

KIND_INCOME = "income"
KIND_EXPENSE = "expense"
KIND_COGS = "cogs"
KIND_REFUND = "refund"
KINDS = (KIND_INCOME, KIND_EXPENSE, KIND_COGS, KIND_REFUND)
MANUAL_KINDS = (KIND_INCOME, KIND_EXPENSE)
ACCOUNTS = ("cash", "card", "bale_pay", "zarinpal", "other")
ACCOUNT_LABEL_FA = {"cash": "نقد", "card": "کارت‌به‌کارت", "bale_pay": "بله‌پی", "zarinpal": "زرین‌پال", "other": "سایر"}
_METHOD_TO_ACCOUNT = {"card_to_card": "card", "bale_pay": "bale_pay", "zarinpal": "zarinpal"}

MAX_AMOUNT = 10**13
MAX_NOTE = 200
MAX_BP = 3000  # سقفِ کارمزد/مالیات: ۳۰٪

# (کلید، نامِ فارسی، نوع) — دسته‌های پیش‌فرض؛ ویرایش‌پذیر (نام) و قابلِ افزودن
DEFAULT_CATEGORIES = (
    ("sales", "فروش", KIND_INCOME),
    ("other_income", "درآمدِ دیگر", KIND_INCOME),
    ("cogs", "بهای کالای فروخته‌شده", KIND_COGS),
    ("refund", "برگشتیِ فروش", KIND_REFUND),
    ("shipping", "ارسال", KIND_EXPENSE),
    ("packaging", "بسته‌بندی", KIND_EXPENSE),
    ("ads", "تبلیغات", KIND_EXPENSE),
    ("gateway_fee", "کارمزدِ درگاه", KIND_EXPENSE),
    ("rent", "اجاره", KIND_EXPENSE),
    ("salary", "حقوق", KIND_EXPENSE),
    ("other_expense", "سایر هزینه‌ها", KIND_EXPENSE),
)

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS finance_categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        builtin INTEGER NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1
    )""",
    """CREATE TABLE IF NOT EXISTS ledger_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts INTEGER NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('income','expense','cogs','refund')),
        category_id INTEGER NOT NULL,
        amount_irr INTEGER NOT NULL CHECK (amount_irr > 0),
        account TEXT NOT NULL DEFAULT 'other',
        ref_type TEXT NOT NULL DEFAULT '',
        ref_id INTEGER NOT NULL DEFAULT 0,
        auto_key TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '',
        created_by TEXT NOT NULL DEFAULT '',
        reverses_id INTEGER NOT NULL DEFAULT 0,
        reversed_by_id INTEGER NOT NULL DEFAULT 0
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ledger_ts ON ledger_entries(ts)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_ledger_auto ON ledger_entries(ref_type, ref_id, auto_key) WHERE auto_key != ''",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_ledger_reverses ON ledger_entries(reverses_id) WHERE reverses_id > 0",
    """CREATE TRIGGER IF NOT EXISTS ledger_no_delete BEFORE DELETE ON ledger_entries
       BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS ledger_no_update BEFORE UPDATE ON ledger_entries
       WHEN NOT (OLD.reversed_by_id = 0 AND NEW.reversed_by_id > 0 AND NEW.id = OLD.id AND NEW.ts = OLD.ts
                 AND NEW.kind = OLD.kind AND NEW.category_id = OLD.category_id AND NEW.amount_irr = OLD.amount_irr
                 AND NEW.account = OLD.account AND NEW.ref_type = OLD.ref_type AND NEW.ref_id = OLD.ref_id
                 AND NEW.auto_key = OLD.auto_key AND NEW.note = OLD.note AND NEW.created_by = OLD.created_by
                 AND NEW.reverses_id = OLD.reverses_id)
       BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END""",
)


class FinanceError(Exception):
    """خطای قابل‌نمایش (فارسی)."""


def migrate(conn: sqlite3.Connection) -> None:
    """مهاجرتِ ۵ی ``orders.db`` (از ``orders._m5_finance``): فقط ``conn.execute`` (داخلِ تراکنشِ مهاجرت)."""
    for stmt in SCHEMA:
        conn.execute(stmt)
    for key, name, kind in DEFAULT_CATEGORIES:
        conn.execute("INSERT OR IGNORE INTO finance_categories (key, name, kind, builtin) VALUES (?,?,?,1)", (key, name, kind))


def round_div(numerator: int, denominator: int) -> int:
    """تقسیمِ صحیح با گردکردنِ «نیم به بالا» (برای اعدادِ نامنفی) — تنها روشِ گردکردنِ پولیِ پروژه."""
    if denominator <= 0 or numerator < 0:
        raise FinanceError("محاسبه‌ی نامعتبر.")
    return (2 * numerator + denominator) // (2 * denominator)


def bp_of(amount_irr: int, bp: int) -> int:
    return round_div(int(amount_irr) * int(bp), 10000)


_CTRL = re.compile(r"[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]")


def clean_text(text, limit: int = MAX_NOTE) -> str:
    return _CTRL.sub(" ", str(text or "")).strip()[:limit]


def _parse_db_ts(value: str) -> int:
    try:
        import calendar

        return calendar.timegm(time.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S"))
    except (ValueError, OverflowError):
        return int(time.time())


@dataclass
class Entry:
    id: int
    ts: int
    kind: str
    category_id: int
    category: str
    amount_irr: int
    account: str
    ref_type: str
    ref_id: int
    auto_key: str
    note: str
    created_by: str
    reverses_id: int
    reversed_by_id: int

    @property
    def signed_irr(self) -> int:
        return -self.amount_irr if self.reverses_id else self.amount_irr


@dataclass
class Report:
    start_ts: int
    end_ts: int
    gross_sales: int = 0  # جمعِ اقلام قبل از تخفیف (سفارش‌های ثبت‌شده در بازه)
    discounts: int = 0
    sales_net: int = 0  # درآمدِ فروشِ ثبت‌شده در دفتر (= gross − discounts برای ثبتِ خودکار)
    other_income: int = 0
    refunds: int = 0
    cogs: int = 0
    gross_profit: int = 0
    expenses: int = 0
    net_profit: int = 0
    orders_count: int = 0
    missing_cost_orders: int = 0
    by_method: dict = field(default_factory=dict)  # حساب → درآمدِ خالص
    by_day: list = field(default_factory=list)  # [(jalali 'YYYY/MM/DD', net)]
    by_product: list = field(default_factory=list)  # [(نام، تعداد، مبلغِ قبل از تخفیف)]
    by_category: list = field(default_factory=list)  # [(نامِ دسته، مبلغ)] هزینه‌ها
    receivables_waiting: int = 0  # پرداخت‌شده و منتظرِ تایید
    receivables_pending: int = 0  # در انتظارِ پرداختِ هنوز معتبر
    top_customers: list = field(default_factory=list)  # [(platform, chat_id, نام، جمع)]
    inventory_value: int = 0


class FinanceStore:
    def __init__(self, order_store, product_store=None):
        self._orders = order_store
        self._products = product_store if product_store is not None else getattr(order_store, "_products", None)

    def _conn(self) -> sqlite3.Connection:
        return self._orders.connection()

    # ------------------------------------------------------------ دسته‌ها
    def categories(self, kind: Optional[str] = None, include_inactive: bool = False) -> list:
        q, args = "SELECT * FROM finance_categories WHERE 1=1", []
        if kind:
            q += " AND kind=?"
            args.append(kind)
        if not include_inactive:
            q += " AND active=1"
        return [dict(r) for r in self._conn().execute(q + " ORDER BY id", args).fetchall()]

    def category_id(self, key: str) -> int:
        row = self._conn().execute("SELECT id FROM finance_categories WHERE key=?", (key,)).fetchone()
        if row is None:
            raise FinanceError("این دسته وجود نداره.")
        return int(row["id"])

    def add_category(self, name: str, kind: str) -> int:
        name = clean_text(name, 40)
        if not name or kind not in MANUAL_KINDS:
            raise FinanceError("نامِ دسته خالیه یا نوعش نامعتبره.")
        conn = self._conn()
        key = f"c{int(time.time() * 1000)}"
        cur = conn.execute("INSERT INTO finance_categories (key, name, kind, builtin) VALUES (?,?,?,0)", (key, name, kind))
        conn.commit()
        return int(cur.lastrowid)

    def rename_category(self, category_id: int, name: str) -> None:
        name = clean_text(name, 40)
        if not name:
            raise FinanceError("نامِ دسته خالیه.")
        conn = self._conn()
        conn.execute("UPDATE finance_categories SET name=? WHERE id=?", (name, int(category_id)))
        conn.commit()

    # ------------------------------------------------------------ ثبت
    @staticmethod
    def _row_to_entry(r) -> Entry:
        return Entry(
            r["id"], r["ts"], r["kind"], r["category_id"], r["cat_name"] if "cat_name" in r.keys() else "", r["amount_irr"],
            r["account"], r["ref_type"], r["ref_id"], r["auto_key"], r["note"], r["created_by"], r["reverses_id"], r["reversed_by_id"],
        )

    def add_entry(
        self, kind: str, amount_irr: int, category_key: str, account: str = "cash", note: str = "", ts: Optional[int] = None,
        created_by: str = "owner",
    ) -> int:
        """ورودیِ دستیِ هزینه/درآمد (معتبرسنجی‌شده). برگشتی فقط با فاکتورِ برگشتی."""
        if kind not in MANUAL_KINDS:
            raise FinanceError("فقط «درآمد» یا «هزینه» را می‌شه دستی ثبت کرد.")
        if not isinstance(amount_irr, int) or isinstance(amount_irr, bool) or not 0 < amount_irr <= MAX_AMOUNT:
            raise FinanceError("مبلغ باید عددِ صحیحِ مثبت (ریال) باشه.")
        if account not in ACCOUNTS:
            raise FinanceError("حساب نامعتبره.")
        now = int(time.time())
        ts = now if ts is None else int(ts)
        if ts < 946684800 or ts > now + 86400:
            raise FinanceError("تاریخ نامعتبره (نه قبل از سال ۲۰۰۰ و نه در آینده).")
        category = self._conn().execute("SELECT id, kind, active FROM finance_categories WHERE key=?", (category_key,)).fetchone()
        if category is None or not category["active"] or category["kind"] != kind:
            raise FinanceError("دسته با نوعِ ثبت نمی‌خونه.")
        conn = self._conn()
        cur = conn.execute(
            "INSERT INTO ledger_entries (ts, kind, category_id, amount_irr, account, note, created_by) VALUES (?,?,?,?,?,?,?)",
            (ts, kind, category["id"], amount_irr, account, clean_text(note), clean_text(created_by, 64)),
        )
        conn.commit()
        return int(cur.lastrowid)

    def reverse(self, entry_id: int, created_by: str = "owner", note: str = "") -> int:
        """اصلاح = ردیفِ برگشتی؛ ردیفِ اصلی دست‌نخورده می‌ماند. هر ردیف فقط یک‌بار و ردیفِ برگشتی دوباره برگشت نمی‌خورد."""
        conn = self._conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT * FROM ledger_entries WHERE id=?", (int(entry_id),)).fetchone()
            if row is None:
                raise FinanceError("این ردیف وجود نداره.")
            if row["reverses_id"] or row["reversed_by_id"]:
                raise FinanceError("این ردیف قبلاً برگشت خورده یا خودش یک ردیفِ برگشتی است.")
            cur = conn.execute(
                "INSERT INTO ledger_entries (ts, kind, category_id, amount_irr, account, ref_type, ref_id, note, created_by, reverses_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (int(time.time()), row["kind"], row["category_id"], row["amount_irr"], row["account"], row["ref_type"], row["ref_id"],
                 clean_text(note) or "برگشت", clean_text(created_by, 64), row["id"]),
            )
            conn.execute("UPDATE ledger_entries SET reversed_by_id=? WHERE id=?", (cur.lastrowid, row["id"]))
            conn.commit()
            return int(cur.lastrowid)
        except Exception:
            conn.rollback()
            raise

    def get(self, entry_id: int) -> Optional[Entry]:
        r = self._conn().execute(
            "SELECT e.*, c.name AS cat_name FROM ledger_entries e JOIN finance_categories c ON c.id=e.category_id WHERE e.id=?", (int(entry_id),)
        ).fetchone()
        return self._row_to_entry(r) if r else None

    def list_entries(self, start_ts: int = 0, end_ts: int = 2**62, kind: str = "", limit: int = 500) -> list:
        q = ("SELECT e.*, c.name AS cat_name FROM ledger_entries e JOIN finance_categories c ON c.id=e.category_id "
             "WHERE e.ts >= ? AND e.ts < ?")
        args: list = [int(start_ts), int(end_ts)]
        if kind:
            q += " AND e.kind=?"
            args.append(kind)
        q += " ORDER BY e.ts DESC, e.id DESC LIMIT ?"
        args.append(max(1, min(int(limit), 5000)))
        return [self._row_to_entry(r) for r in self._conn().execute(q, args).fetchall()]

    # ------------------------------------------------------ ثبتِ خودکار
    def post_order(self, order, fee_bp: Optional[dict] = None, now: Optional[int] = None) -> int:
        """درآمدِ خالص + کارمزدِ درگاه + COGS برای یک سفارشِ *تاییدشده*؛ idempotent. تعدادِ ردیف‌های تازه را برمی‌گردونه."""
        if getattr(order, "status", "") != "confirmed" or not getattr(order, "inventory_applied", False):
            return 0
        if order.total_irr <= 0:
            return 0
        ts = _parse_db_ts(order.updated_at) if order.updated_at else int(now if now is not None else time.time())
        account = _METHOD_TO_ACCOUNT.get(order.payment_method, "other")
        conn = self._conn()
        rows = [("sale", KIND_INCOME, "sales", order.total_irr, account, f"سفارش #{order.id}")]
        bp = int((fee_bp or {}).get(order.payment_method, 0) or 0)
        if 0 < bp <= MAX_BP:
            fee = bp_of(order.total_irr, bp)
            if fee > 0:
                rows.append(("fee", KIND_EXPENSE, "gateway_fee", fee, account, f"کارمزدِ درگاه، سفارش #{order.id}"))
        cogs, incomplete = self._cogs_of(order)
        if cogs > 0:
            rows.append(("cogs", KIND_COGS, "cogs", cogs, account, f"سفارش #{order.id}" + (" (ناقص: بهای بعضی اقلام ثبت نشده)" if incomplete else "")))
        created = 0
        for auto_key, kind, cat_key, amount, acct, note in rows:
            cur = conn.execute(
                "INSERT OR IGNORE INTO ledger_entries (ts, kind, category_id, amount_irr, account, ref_type, ref_id, auto_key, note, created_by) "
                "VALUES (?,?,?,?,?,'order',?,?,?,'auto')",
                (ts, kind, self.category_id(cat_key), amount, acct, order.id, auto_key, note),
            )
            created += cur.rowcount
        conn.commit()
        return created

    def post_credit_note(self, inv, cogs_back: bool = False, now: Optional[int] = None) -> int:
        """فاکتورِ برگشتی ⇒ ردیفِ «برگشتی» (idempotent با ``(invoice, id, cn)``). ``cogs_back``: کالا برگشت داده شد ⇒ بهای
        کالای همان سفارش هم برمی‌گرده (reversalِ ردیفِ COGS). موجودیِ انبار اینجا تغییر نمی‌کنه (دستی در «محصولات»)."""
        conn = self._conn()
        ts = int(now if now is not None else time.time())
        cur = conn.execute(
            "INSERT OR IGNORE INTO ledger_entries (ts, kind, category_id, amount_irr, account, ref_type, ref_id, auto_key, note, created_by) "
            "VALUES (?,?,?,?,?,'invoice',?,'cn',?,'auto')",
            (ts, KIND_REFUND, self.category_id("refund"), int(inv.total_irr), _METHOD_TO_ACCOUNT.get(inv.pay_method, "other"), inv.id,
             f"فاکتورِ برگشتی {inv.number}"),
        )
        conn.commit()
        created = cur.rowcount
        if created and cogs_back:
            row = conn.execute(
                "SELECT id FROM ledger_entries WHERE ref_type='order' AND ref_id=? AND auto_key='cogs' AND reversed_by_id=0", (inv.order_id,)
            ).fetchone()
            if row:
                self.reverse(row["id"], created_by="auto", note=f"برگشتِ کالا، {inv.number}")
                created += 1
        return created

    def _cogs_of(self, order) -> tuple:
        total, incomplete = 0, False
        for item in order.items:
            cost = 0
            if item.product_id is not None and self._products is not None:
                product = self._products.get(item.product_id)
                cost = int(product.cost_irr) if product is not None else 0
            if cost > 0:
                total += cost * int(item.quantity)
            else:
                incomplete = True
        return total, incomplete

    def post_missing(self, fee_bp: Optional[dict] = None, limit: int = 200) -> int:
        """ترمیم: سفارش‌های تاییدشده‌ای که هنوز ردیفِ فروش ندارن (کرش/شکستِ قلاب). تعدادِ سفارشِ ترمیم‌شده."""
        rows = self._conn().execute(
            "SELECT o.id FROM orders o WHERE o.status='confirmed' AND o.inventory_applied=1 AND o.total_irr>0 AND NOT EXISTS "
            "(SELECT 1 FROM ledger_entries e WHERE e.ref_type='order' AND e.ref_id=o.id AND e.auto_key='sale') ORDER BY o.id LIMIT ?",
            (int(limit),),
        ).fetchall()
        done = 0
        for r in rows:
            order = self._orders.get(r["id"])
            if order is not None and self.post_order(order, fee_bp):
                done += 1
        return done

    # ------------------------------------------------------------ گزارش
    def report(self, start_ts: int, end_ts: int, top_n: int = 5) -> Report:
        rep = Report(int(start_ts), int(end_ts))
        conn = self._conn()
        a = (rep.start_ts, rep.end_ts)
        sums = {}
        for row in conn.execute(
            "SELECT kind, auto_key, SUM(CASE WHEN reverses_id>0 THEN -amount_irr ELSE amount_irr END) AS s "
            "FROM ledger_entries WHERE ts>=? AND ts<? GROUP BY kind, (auto_key != '')", a
        ).fetchall():
            sums[(row["kind"], bool(row["auto_key"]))] = int(row["s"] or 0)
        # ردیف‌های برگشت‌خورده‌ی ردیفِ خودکار auto_key='' دارن؛ برای تفکیکِ «فروش» از «درآمدِ دستی» از ref_type استفاده می‌کنیم
        sale = conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN reverses_id>0 THEN -amount_irr ELSE amount_irr END),0) AS s FROM ledger_entries "
            "WHERE ts>=? AND ts<? AND kind='income' AND ref_type='order'", a
        ).fetchone()["s"]
        rep.sales_net = int(sale)
        rep.other_income = sums.get((KIND_INCOME, False), 0) + sums.get((KIND_INCOME, True), 0) - rep.sales_net
        rep.refunds = sums.get((KIND_REFUND, False), 0) + sums.get((KIND_REFUND, True), 0)
        rep.cogs = sums.get((KIND_COGS, False), 0) + sums.get((KIND_COGS, True), 0)
        rep.expenses = sums.get((KIND_EXPENSE, False), 0) + sums.get((KIND_EXPENSE, True), 0)
        rep.gross_profit = rep.sales_net + rep.other_income - rep.refunds - rep.cogs
        rep.net_profit = rep.gross_profit - rep.expenses
        # از سفارش‌های اصلی (نه شمارنده): ناخالص و تخفیفِ سفارش‌هایی که در بازه فروش ثبت شدن
        base = ("FROM orders o JOIN ledger_entries e ON e.ref_type='order' AND e.ref_id=o.id AND e.auto_key='sale' "
                "WHERE e.ts>=? AND e.ts<?")
        row = conn.execute(f"SELECT COUNT(*) AS n, COALESCE(SUM(o.subtotal_irr),0) AS g, COALESCE(SUM(o.discount_irr),0) AS d {base}", a).fetchone()
        rep.orders_count, rep.gross_sales, rep.discounts = int(row["n"]), int(row["g"]), int(row["d"])
        rep.by_method = {
            r["account"]: int(r["s"])
            for r in conn.execute(
                "SELECT account, SUM(CASE WHEN reverses_id>0 THEN -amount_irr ELSE amount_irr END) AS s FROM ledger_entries "
                "WHERE ts>=? AND ts<? AND kind='income' GROUP BY account ORDER BY s DESC", a
            ).fetchall()
        }
        days: dict = {}
        for r in conn.execute(
            "SELECT ts, kind, CASE WHEN reverses_id>0 THEN -amount_irr ELSE amount_irr END AS s FROM ledger_entries "
            "WHERE ts>=? AND ts<? AND kind IN ('income','refund')", a
        ).fetchall():
            day = jalali.format_ts(r["ts"], digits="en")
            days[day] = days.get(day, 0) + (r["s"] if r["kind"] == KIND_INCOME else -r["s"])
        rep.by_day = sorted(days.items())
        rep.by_product = [
            (r["product_name"], int(r["q"]), int(r["rev"]))
            for r in conn.execute(
                "SELECT i.product_name, SUM(i.quantity) AS q, SUM(i.quantity*i.unit_price_irr) AS rev FROM order_items i "
                "JOIN orders o ON o.id=i.order_id JOIN ledger_entries e ON e.ref_type='order' AND e.ref_id=o.id AND e.auto_key='sale' "
                "WHERE e.ts>=? AND e.ts<? GROUP BY i.product_name ORDER BY rev DESC, i.product_name LIMIT 50", a
            ).fetchall()
        ]
        rep.by_category = [
            (r["name"], int(r["s"]))
            for r in conn.execute(
                "SELECT c.name, SUM(CASE WHEN e.reverses_id>0 THEN -e.amount_irr ELSE e.amount_irr END) AS s FROM ledger_entries e "
                "JOIN finance_categories c ON c.id=e.category_id WHERE e.ts>=? AND e.ts<? AND e.kind='expense' "
                "GROUP BY c.id HAVING s != 0 ORDER BY s DESC", a
            ).fetchall()
        ]
        rep.missing_cost_orders = int(conn.execute(
            "SELECT COUNT(*) AS n FROM ledger_entries s WHERE s.ts>=? AND s.ts<? AND s.ref_type='order' AND s.auto_key='sale' AND "
            "(NOT EXISTS (SELECT 1 FROM ledger_entries c WHERE c.ref_type='order' AND c.ref_id=s.ref_id AND c.auto_key='cogs') "
            " OR EXISTS (SELECT 1 FROM ledger_entries c WHERE c.ref_type='order' AND c.ref_id=s.ref_id AND c.auto_key='cogs' "
            "            AND c.note LIKE '%ناقص%'))", a
        ).fetchone()["n"])
        rep.receivables_waiting = int(conn.execute("SELECT COALESCE(SUM(total_irr),0) AS s FROM orders WHERE status='paid'").fetchone()["s"])
        rep.receivables_pending = int(conn.execute(
            "SELECT COALESCE(SUM(total_irr),0) AS s FROM orders WHERE status='pending_payment' AND expires_ts>?", (int(time.time()),)
        ).fetchone()["s"])
        rep.top_customers = [
            (r["platform"], r["chat_id"], r["name"] or "", int(r["s"]))
            for r in conn.execute(
                f"SELECT o.platform, o.chat_id, MAX(o.customer_name) AS name, SUM(o.total_irr) AS s {base} "
                "GROUP BY o.platform, o.chat_id ORDER BY s DESC LIMIT ?", (*a, int(top_n))
            ).fetchall()
        ]
        if self._products is not None:
            rep.inventory_value = sum(
                p.stock_quantity * p.cost_irr for p in self._products.list(include_inactive=True)
                if p.cost_irr > 0 and not p.unlimited_stock and p.stock_quantity > 0 and p.delivery_kind != "keys"
            )
        return rep

    # -------------------------------------------------------------- CSV
    @staticmethod
    def csv_cell(value) -> str:
        """ضدِ تزریقِ فرمول (Excel/Sheets): سلولِ متنیِ شروع‌شونده با ``= + - @`` یا tab/CR با ``'`` خنثی می‌شه."""
        text = str(value)
        if text and text[0] in "=+-@\t\r" and not re.fullmatch(r"-?\d+", text):
            return "'" + text
        return text

    def export_csv(self, start_ts: int = 0, end_ts: int = 2**62) -> str:
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(["id", "date_jalali", "kind", "category", "amount_irr", "account", "ref", "note", "reverses"])
        for e in reversed(self.list_entries(start_ts, end_ts, limit=5000)):
            ref = f"{e.ref_type}:{e.ref_id}" if e.ref_type else ""
            writer.writerow([e.id, jalali.format_ts(e.ts, with_time=True, digits="en"), e.kind, self.csv_cell(e.category),
                             e.signed_irr, e.account, ref, self.csv_cell(e.note), e.reverses_id or ""])
        return "﻿" + out.getvalue()  # BOM: Excel فارسی را درست باز کند
