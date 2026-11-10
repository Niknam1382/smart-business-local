"""
فاکتورِ فروش و فاکتورِ برگشتی (N19) — جدول‌ها داخلِ ``orders.db`` (``orders._m5_finance``).

- **snapshot و تغییرناپذیر:** فروشنده/خریدار/اقلام/مبالغ در لحظه‌ی صدور ذخیره می‌شه؛ تریگرِ SQLite هر تغییرِ ستون‌های مالی را
  رد می‌کنه (تنها مجاز: ``pdf_sha256``، ``sent_json`` و ناشناس‌سازیِ خریدار برای ``/forget``). اصلاح = فاکتورِ برگشتی.
- **شماره‌گذاریِ اتمیک و بی‌شکاف:** شمارنده و ردیفِ فاکتور داخلِ *یک* تراکنشِ ``BEGIN IMMEDIATE``؛ شکستِ صدور = بدونِ مصرفِ شماره.
- **ریاضی:** جمعِ سطرها − تخفیف + ارسال = جمعِ کل = مبلغِ سفارش (آنچه مشتری پرداخت). مالیات بر ارزش افزوده (اگه روشن) از
  مبلغِ کل *استخراج* می‌شه (قیمت‌ها «با مالیات»)؛ گردکردنِ یکنواخت (نیم به بالا، یک‌بار روی جمعِ کل).
- صدور idempotent است و خارج از ساگای موجودی (فقط روی سفارشِ ``confirmed`` با ``inventory_applied``).
- **متن‌هایِ شخصی‌سازی‌شده (قلم ۸):** نامِ فروشگاه یک‌جا با زنجیره‌ی
  ``invoice_seller_name → user_name → invoice_seller_fallback → «فروشگاه»`` حل می‌شود (هرگز نامِ خالی
  روی فاکتور نمی‌آید)؛ متنِ تشکر و سلبِ مسئولیت از تنظیمات می‌آیند و برچسب‌هایِ مهمِ فاکتور از
  ``settings.bot_texts`` (کلیدهایِ ``invoice.label.*``). همه داخلِ *snapshotِ* فاکتور منجمد می‌شن،
  پس فاکتورِ صادرشده با عوض‌شدنِ تنظیمات عوض نمی‌شود و PDF همچنان قطعی است.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Optional

from app.core import jalali
from app.core.finance import MAX_BP, clean_text, round_div

KIND_SALE = "sale"
KIND_CREDIT = "credit_note"
ANON_NAME = "حذف‌شده به درخواستِ مشتری"
# آخرینِ لایه‌یِ نامِ فروشگاه روی فاکتور — هرگز جایِ نام، عنوانِ «فاکتور فروش» چاپ نمی‌شود.
DEFAULT_SELLER_NAME = "فروشگاه"

# «متن‌هایِ مهمِ فاکتور» که مالک می‌تواند عوض کند (کلیدهایِ ``LABELS`` در ``app.core.invoice_pdf``).
EDITABLE_LABEL_KEYS = ("sale", "credit", "buyer", "col_item", "final", "date", "number")
# برچسب‌هایِ سفارشی در همان ``settings.bot_texts`` (تنها جاودانهِ قابل‌ویرایشِ متن در این نسخه) می‌نشینند؛
# پیشوندِ ``invoice.label.`` هیچ‌وقت با کلیدِ پیامِ ربات قاطی نمی‌شود (``shop_texts`` فقط کلیدهایِ ثبت‌شده را می‌خواند).
LABEL_PREFIX = "invoice.label."
MAX_LABEL_LEN = 60
MAX_THANKS_LEN = 200
MAX_DISCLAIMER_LEN = 300
MAX_NAME_LEN = 40

_IMMUTABLE_COLUMNS = (
    "number", "kind", "order_id", "ref_invoice_id", "issued_ts", "seller_json", "lines_json", "subtotal_irr", "discount_irr",
    "shipping_irr", "tax_irr", "total_irr", "pay_method", "pay_status", "lang",
)

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        number TEXT NOT NULL UNIQUE,
        kind TEXT NOT NULL CHECK (kind IN ('sale','credit_note')),
        order_id INTEGER NOT NULL,
        ref_invoice_id INTEGER NOT NULL DEFAULT 0,
        issued_ts INTEGER NOT NULL,
        seller_json TEXT NOT NULL,
        buyer_json TEXT NOT NULL,
        lines_json TEXT NOT NULL,
        subtotal_irr INTEGER NOT NULL,
        discount_irr INTEGER NOT NULL DEFAULT 0,
        shipping_irr INTEGER NOT NULL DEFAULT 0,
        tax_irr INTEGER NOT NULL DEFAULT 0,
        total_irr INTEGER NOT NULL,
        pay_method TEXT NOT NULL DEFAULT '',
        pay_status TEXT NOT NULL DEFAULT 'paid',
        pdf_sha256 TEXT NOT NULL DEFAULT '',
        lang TEXT NOT NULL DEFAULT 'fa',
        sent_json TEXT NOT NULL DEFAULT '{}'
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_invoice_sale_order ON invoices(order_id) WHERE kind='sale'",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_invoice_credit_ref ON invoices(ref_invoice_id) WHERE kind='credit_note'",
    "CREATE INDEX IF NOT EXISTS idx_invoices_order ON invoices(order_id)",
    "CREATE TABLE IF NOT EXISTS invoice_counters (series TEXT PRIMARY KEY, last INTEGER NOT NULL)",
    "CREATE TRIGGER IF NOT EXISTS invoices_no_delete BEFORE DELETE ON invoices BEGIN SELECT RAISE(ABORT, 'invoice is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS invoices_immutable BEFORE UPDATE ON invoices WHEN "
    + " OR ".join(f"NEW.{c} != OLD.{c}" for c in _IMMUTABLE_COLUMNS)
    + """ OR (NEW.buyer_json != OLD.buyer_json AND NEW.buyer_json NOT LIKE '%"anonymized": true%')
       BEGIN SELECT RAISE(ABORT, 'invoice is immutable'); END""",
)


class InvoiceError(Exception):
    """خطای قابل‌نمایش (فارسی)."""


def migrate(conn: sqlite3.Connection) -> None:
    for stmt in SCHEMA:
        conn.execute(stmt)


@dataclass
class Invoice:
    id: int
    number: str
    kind: str
    order_id: int
    ref_invoice_id: int
    issued_ts: int
    seller: dict
    buyer: dict
    lines: list
    subtotal_irr: int
    discount_irr: int
    shipping_irr: int
    tax_irr: int
    total_irr: int
    pay_method: str
    pay_status: str
    pdf_sha256: str
    lang: str
    sent: dict = field(default_factory=dict)

    @property
    def is_credit(self) -> bool:
        return self.kind == KIND_CREDIT

    @property
    def anonymized(self) -> bool:
        return bool(self.buyer.get("anonymized"))


def _loads(raw: str, default):
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


def _row_to_invoice(r) -> Invoice:
    return Invoice(
        r["id"], r["number"], r["kind"], r["order_id"], r["ref_invoice_id"], r["issued_ts"], _loads(r["seller_json"], {}),
        _loads(r["buyer_json"], {}), _loads(r["lines_json"], []), r["subtotal_irr"], r["discount_irr"], r["shipping_irr"],
        r["tax_irr"], r["total_irr"], r["pay_method"], r["pay_status"], r["pdf_sha256"], r["lang"], _loads(r["sent_json"], {}),
    )


def compute_totals(lines: list, total_irr: int, declared_discount: int = 0, vat_enabled: bool = False, vat_bp: int = 0) -> dict:
    """جمعِ سطرها − تخفیف + ارسال = ``total_irr`` (همیشه). تفاوتِ مثبت = «ارسال/سایر»؛ تخفیفِ بیش‌ازحد نادیده گرفته می‌شه."""
    subtotal = sum(int(i["total_irr"]) for i in lines)
    discount = int(declared_discount) if 0 <= int(declared_discount) <= subtotal else 0  # تخفیفِ بی‌معنی نادیده گرفته می‌شه
    shipping = int(total_irr) - (subtotal - discount)
    if shipping < 0:  # مبلغِ پرداختی کمتر از اقلام−تخفیف: تفاوت همه تخفیف حساب می‌شه
        discount = subtotal - int(total_irr)
        shipping = 0
    tax = 0
    if vat_enabled and 0 < int(vat_bp) <= MAX_BP and total_irr > 0:
        tax = int(total_irr) - round_div(int(total_irr) * 10000, 10000 + int(vat_bp))
    return {"subtotal_irr": subtotal, "discount_irr": discount, "shipping_irr": shipping, "tax_irr": tax, "total_irr": int(total_irr)}


def seller_name_of(settings) -> str:
    """نامِ فروشندهٔ فاکتور — **یک‌جا، با یک زنجیره:** ``invoice_seller_name → user_name →
    invoice_seller_fallback → «فروشگاه»``.

    چرا زنجیره؟ «نامِ فروشگاه» در تنظیماتِ فاکتور خیلی‌ها خالی است (مالک فقط نامِ خود را در
    «آغازِ سریع» نوشته)، و قبلاً در آن حالت جایِ نام، عنوانِ «فاکتور فروش» در نوارِ رنگی چاپ
    می‌شد — یعنی سربرگِ بی‌نام. هرگز رشته‌یِ خالی برنمی‌گرداند، پس هیچ باندی خالی نمی‌ماند."""
    for value in (getattr(settings, "invoice_seller_name", ""), getattr(settings, "user_name", ""),
                  getattr(settings, "invoice_seller_fallback", "")):
        name = clean_text(value, MAX_NAME_LEN)
        if name:
            return name
    return DEFAULT_SELLER_NAME


def invoice_labels_of(settings) -> dict:
    """overrideِ برچسب‌هایِ مهمِ فاکتور، به شکلِ ``{زبان: {کلیدِ LABELS: متن}}`` (خالی = پیش‌فرض).

    متن‌ها نامطمئن‌اند (از ``settings.json`` و از پشتیبانِ بازگردانده‌شده هم می‌آیند): نویسه‌های
    کنترلی/bidi دور ریخته می‌شوند، طول کران‌دار است و فقط کلیدهایِ ``EDITABLE_LABEL_KEYS`` —
    پس چیدمانِ فاکتور با متنِ دلخواه نمی‌شکند."""
    table = getattr(settings, "bot_texts", None)
    out: dict = {}
    if not isinstance(table, dict):
        return out
    for lang in ("fa", "en"):
        raw = table.get(lang)
        if not isinstance(raw, dict):
            continue
        texts: dict = {}
        for key in EDITABLE_LABEL_KEYS:
            value = raw.get(LABEL_PREFIX + key)
            text = clean_text(value, MAX_LABEL_LEN) if isinstance(value, str) else ""
            if text:
                texts[key] = text
        if texts:
            out[lang] = texts
    return out


def seller_snapshot(settings) -> dict:
    g = lambda name, default="": getattr(settings, name, default)  # noqa: E731
    logo = str(g("invoice_logo_path"))
    return {
        "name": seller_name_of(settings),
        # نامِ صریحِ جایگزین هم در snapshot می‌ماند تا اگر «نام» به هر دلیلی چاپ‌شدنی نبود، همین نشان داده شود
        "fallback_name": clean_text(g("invoice_seller_fallback"), MAX_NAME_LEN),
        "legal_name": clean_text(g("invoice_seller_legal_name"), 80),
        "national_id": clean_text(g("invoice_seller_national_id"), 20),
        "address": clean_text(g("invoice_seller_address"), 200),
        "phone": clean_text(g("invoice_seller_phone"), 30),
        "logo_path": logo,
        "color": g("invoice_color") if re.fullmatch(r"#[0-9a-fA-F]{6}", str(g("invoice_color"))) else "#1F6FEB",
        "footer": clean_text(g("invoice_footer"), 200),
        # متن‌هایِ قابلِ شخصی‌سازیِ فاکتور (قلم ۸): خالی ⇒ متنِ پیش‌فرضِ خودِ برنامه
        "thanks": clean_text(g("invoice_thanks"), MAX_THANKS_LEN),
        "disclaimer": clean_text(g("invoice_disclaimer"), MAX_DISCLAIMER_LEN),
        "labels": invoice_labels_of(settings),
        "vat_enabled": bool(g("invoice_vat_enabled", False)),
        "vat_rate_bp": int(g("invoice_vat_rate_bp", 0) or 0),
        "paper": g("invoice_paper", "A4") if g("invoice_paper", "A4") in ("A4", "A5") else "A4",
        "digits": "en" if g("invoice_digits", "fa") == "en" else "fa",
    }


def _prefix(settings) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(getattr(settings, "invoice_number_prefix", "F") or ""))[:6]


class InvoiceStore:
    def __init__(self, order_store):
        self._orders = order_store

    def _conn(self) -> sqlite3.Connection:
        return self._orders.connection()

    # ------------------------------------------------------------ خواندن
    def get(self, invoice_id: int) -> Optional[Invoice]:
        r = self._conn().execute("SELECT * FROM invoices WHERE id=?", (int(invoice_id),)).fetchone()
        return _row_to_invoice(r) if r else None

    def get_by_number(self, number: str) -> Optional[Invoice]:
        r = self._conn().execute("SELECT * FROM invoices WHERE number=?", (str(number),)).fetchone()
        return _row_to_invoice(r) if r else None

    def for_order(self, order_id: int, kind: str = KIND_SALE) -> Optional[Invoice]:
        r = self._conn().execute("SELECT * FROM invoices WHERE order_id=? AND kind=? ORDER BY id LIMIT 1", (int(order_id), kind)).fetchone()
        return _row_to_invoice(r) if r else None

    def return_note_for(self, invoice_id: int) -> Optional[Invoice]:
        r = self._conn().execute("SELECT * FROM invoices WHERE ref_invoice_id=? AND kind='credit_note'", (int(invoice_id),)).fetchone()
        return _row_to_invoice(r) if r else None

    def list(self, query: str = "", kind: str = "", limit: int = 200) -> list:
        sql, args = "SELECT * FROM invoices WHERE 1=1", []
        if kind in (KIND_SALE, KIND_CREDIT):
            sql += " AND kind=?"
            args.append(kind)
        q = clean_text(query, 40)
        if q:
            sql += " AND (number LIKE ? OR buyer_json LIKE ? OR CAST(order_id AS TEXT)=?)"
            esc = q.replace("%", "").replace("_", "")
            args += [f"%{esc}%", f"%{esc}%", esc.lstrip("#")]
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(max(1, min(int(limit), 1000)))
        return [_row_to_invoice(r) for r in self._conn().execute(sql, args).fetchall()]

    def sale_missing_for_confirmed(self, limit: int = 100) -> list:
        """شناسه‌ی سفارش‌های تاییدشده‌ای که هنوز فاکتور ندارن (برای صدورِ دوباره/ترمیم)."""
        rows = self._conn().execute(
            "SELECT o.id FROM orders o WHERE o.status='confirmed' AND o.inventory_applied=1 AND o.total_irr>0 AND NOT EXISTS "
            "(SELECT 1 FROM invoices i WHERE i.order_id=o.id AND i.kind='sale') ORDER BY o.id LIMIT ?", (int(limit),)
        ).fetchall()
        return [r["id"] for r in rows]

    # -------------------------------------------------------------- صدور
    def _next_number(self, conn, kind: str, settings, issued_ts: int) -> str:
        use_year = bool(getattr(settings, "invoice_number_use_year", True))
        year = jalali.ts_to_jalali(issued_ts)[0] if use_year else 0
        series = f"{kind}:{year}"
        prefix = _prefix(settings) if kind == KIND_SALE else "CN" + _prefix(settings)
        row = conn.execute("SELECT last FROM invoice_counters WHERE series=?", (series,)).fetchone()
        start = max(1, int(getattr(settings, "invoice_number_start", 1) or 1))
        seq = (int(row["last"]) + 1) if row else start
        conn.execute("INSERT INTO invoice_counters (series, last) VALUES (?, ?) ON CONFLICT(series) DO UPDATE SET last=excluded.last", (series, seq))
        return f"{prefix}{year or ''}{seq:05d}"

    def _insert(self, conn, kind, order_id, ref_id, settings, seller, buyer, lines, totals, pay_method, lang, now) -> Invoice:
        number = self._next_number(conn, kind, settings, now)
        cur = conn.execute(
            "INSERT INTO invoices (number, kind, order_id, ref_invoice_id, issued_ts, seller_json, buyer_json, lines_json, subtotal_irr, "
            "discount_irr, shipping_irr, tax_irr, total_irr, pay_method, pay_status, lang) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (number, kind, order_id, ref_id, now, json.dumps(seller, ensure_ascii=False), json.dumps(buyer, ensure_ascii=False),
             json.dumps(lines, ensure_ascii=False), totals["subtotal_irr"], totals["discount_irr"], totals["shipping_irr"],
             totals["tax_irr"], totals["total_irr"], pay_method, "paid" if kind == KIND_SALE else "refunded", lang),
        )
        return self.get_unlocked(conn, cur.lastrowid)

    @staticmethod
    def get_unlocked(conn, invoice_id: int) -> Invoice:
        return _row_to_invoice(conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone())

    def issue_sale(self, order, settings, lang: str = "fa", now: Optional[int] = None) -> Invoice:
        """فاکتورِ فروشِ سفارشِ تاییدشده؛ idempotent (دوباره‌صدا زدن همان فاکتور را برمی‌گردونه)."""
        if order.status != "confirmed" or not order.inventory_applied:
            raise InvoiceError("فاکتور فقط برای سفارشِ تاییدشده صادر می‌شه.")
        if order.total_irr <= 0:
            raise InvoiceError("سفارشِ رایگان فاکتور نمی‌گیره.")
        existing = self.for_order(order.id)
        if existing is not None:
            return existing
        now = int(now if now is not None else time.time())
        lines = [
            {"name": clean_text(i.product_name, 120), "qty": int(i.quantity), "unit_irr": int(i.unit_price_irr), "total_irr": int(i.subtotal_irr)}
            for i in order.items
        ]
        seller = seller_snapshot(settings)
        totals = compute_totals(lines, order.total_irr, order.discount_irr, seller["vat_enabled"], seller["vat_rate_bp"])
        buyer = {"name": clean_text(order.customer_name, 80), "phone": clean_text(order.customer_phone, 30),
                 "address": clean_text(order.customer_address, 300),
                 # کدِ پیگیری/تراکنش روی فاکتور چاپ می‌شه؛ بخشی از snapshot است، نه داده‌ی هویتی
                 "trace": clean_text(order.payment_reference, 40),
                 # کدِ رهگیریِ مرسوله و شناسهٔ مشتری هم روی فاکتور می‌آیند (بلوکِ «مشخصات خریدار» همیشه پُره)
                 "tracking": clean_text(getattr(order, "tracking_code", ""), 40),
                 "buyer_id": clean_text(getattr(order, "chat_id", ""), 40),
                 # روشِ ارسالِ انتخابیِ مشتری هم روی فاکتور می‌آید (برچسبِ غیرهویتی؛ با /forget پاک می‌شه)
                 "shipping_method": clean_text(getattr(order, "shipping_method", ""), 60)}
        conn = self._conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            dup = conn.execute("SELECT id FROM invoices WHERE order_id=? AND kind='sale'", (order.id,)).fetchone()
            if dup:  # رقیبِ هم‌زمان زودتر صادر کرد
                conn.rollback()
                return self.get(dup["id"])
            inv = self._insert(conn, KIND_SALE, order.id, 0, settings, seller, buyer, lines, totals, order.payment_method, lang, now)
            conn.commit()
            return inv
        except Exception:
            conn.rollback()
            raise

    def issue_credit_note(self, sale_id: int, settings, now: Optional[int] = None) -> Invoice:
        """فاکتورِ برگشتیِ کامل برای یک فاکتورِ فروش (فقط یک‌بار). ریاضیِ فاکتور از snapshotِ اصلی کپی می‌شه."""
        sale = self.get(sale_id)
        if sale is None or sale.kind != KIND_SALE:
            raise InvoiceError("فاکتورِ فروشِ مرجع پیدا نشد.")
        if self.return_note_for(sale.id) is not None:
            raise InvoiceError("برای این فاکتور قبلاً فاکتورِ برگشتی صادر شده.")
        totals = {k: getattr(sale, k) for k in ("subtotal_irr", "discount_irr", "shipping_irr", "tax_irr", "total_irr")}
        conn = self._conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            if conn.execute("SELECT 1 FROM invoices WHERE ref_invoice_id=? AND kind='credit_note'", (sale.id,)).fetchone():
                raise InvoiceError("برای این فاکتور قبلاً فاکتورِ برگشتی صادر شده.")
            inv = self._insert(conn, KIND_CREDIT, sale.order_id, sale.id, settings, sale.seller, sale.buyer, sale.lines, totals,
                               sale.pay_method, sale.lang, int(now if now is not None else time.time()))
            conn.commit()
            return inv
        except Exception:
            conn.rollback()
            raise

    # ------------------------------------------------- فیلدهای قابل‌تغییر
    def set_pdf_hash(self, invoice_id: int, sha256: str) -> None:
        conn = self._conn()
        conn.execute("UPDATE invoices SET pdf_sha256=? WHERE id=?", (str(sha256)[:64], int(invoice_id)))
        conn.commit()

    def record_send(self, invoice_id: int, target: str, ok: bool, detail: str = "", now: Optional[int] = None) -> dict:
        """وضعیتِ ارسال به ``customer``/``owner``: ``{ok, ts, attempts, error}``؛ شمارنده‌ی تلاش‌ها حفظ می‌شه."""
        conn = self._conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            raw = conn.execute("SELECT sent_json FROM invoices WHERE id=?", (int(invoice_id),)).fetchone()
            sent = _loads(raw["sent_json"], {}) if raw else {}
            prev = sent.get(target, {}) if isinstance(sent.get(target), dict) else {}
            sent[target] = {"ok": bool(ok), "ts": int(now if now is not None else time.time()), "attempts": int(prev.get("attempts", 0)) + 1,
                            "error": "" if ok else clean_text(detail, 160)}
            conn.execute("UPDATE invoices SET sent_json=? WHERE id=?", (json.dumps(sent, ensure_ascii=False), int(invoice_id)))
            conn.commit()
            return sent[target]
        except Exception:
            conn.rollback()
            raise

    def anonymize_orders(self, order_ids: list) -> list:
        """``/forget``/retention: نام/تلفن/آدرسِ خریدار در snapshot ناشناس می‌شه؛ مبالغ و سطرها می‌مونن (سابقه‌ی مالی).
        شماره‌ی فاکتورهایی که PDFشان باید پاک بشه را برمی‌گردونه."""
        numbers: list = []
        conn = self._conn()
        anon = json.dumps({"anonymized": True, "name": ANON_NAME, "phone": "", "address": "", "trace": "",
                           "tracking": "", "buyer_id": "", "shipping_method": ""}, ensure_ascii=False)
        for oid in order_ids:
            for r in conn.execute("SELECT number FROM invoices WHERE order_id=?", (int(oid),)).fetchall():
                numbers.append(r["number"])
            conn.execute("UPDATE invoices SET buyer_json=? WHERE order_id=?", (anon, int(oid)))
        conn.commit()
        return numbers
