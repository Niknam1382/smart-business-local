"""کدِ تخفیف و کمپین (N8) — محاسبه فقط سمتِ برنامه و **داخلِ تراکنشِ ساختِ سفارش** (ناوردایی ۸).

* همه‌ی جدول‌ها روی ``orders.db`` هستن (تا ساختِ سفارش + مصرفِ کد یک تراکنشِ تفکیک‌ناپذیر باشه).
* پول = عددِ صحیحِ ریال؛ درصد با ``//`` (floor)؛ هرگز float. مبلغِ نهایی هرگز زیرِ ``MIN_FINAL_IRR`` (حداقلِ پرداختِ
  زرین‌پال طبقِ مستنداتِ رسمی ۱۰٬۰۰۰ ریال) و هرگز منفی نیست؛ تخفیفِ ۱۰۰٪ مجاز نیست.
* مصرفِ کد با ساختِ سفارش شمرده می‌شه و با لغو/انقضا/ردِ سفارش آزاد (``released``)؛ پرداختِ دیرهنگام دوباره می‌شمردش.
* ورودیِ مشتری (متنِ کد) نامطمئنه: ``normalize_code`` + ضدِ brute-force (۵ کدِ اشتباه در ساعت ← قفل).
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Optional

MIN_FINAL_IRR = 10_000
KIND_PERCENT, KIND_FIXED = "percent", "fixed"
KINDS = (KIND_PERCENT, KIND_FIXED)
APPLIES_ALL, APPLIES_PRODUCTS, APPLIES_CATEGORIES = "all", "products", "categories"
APPLIES = (APPLIES_ALL, APPLIES_PRODUCTS, APPLIES_CATEGORIES)
WRONG_ATTEMPT_LIMIT = 5
ATTEMPT_WINDOW_SECONDS = 3600
CODE_MIN, CODE_MAX = 3, 32
MAX_TARGETS = 200

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_CODE_RE = re.compile(r"^[A-Z0-9_-]+$")

# پیامِ فارسی برای مالک (در UI)؛ مشتری با کلیدهای ``disc.err.<code>`` در shop_texts پیام می‌گیره
ERRORS_FA = {
    "unknown": "این کد معتبر نیست.",
    "inactive": "این کد غیرفعاله.",
    "not_started": "این کد هنوز شروع نشده.",
    "expired": "مهلتِ این کد تموم شده.",
    "min_subtotal": "جمعِ سبد به حداقلِ لازم برای این کد نرسیده.",
    "not_applicable": "این کد روی محصولاتِ سبدِ تو اعمال نمی‌شه.",
    "first_only": "این کد فقط برای اولین خریده.",
    "min_prev": "این کد برای مشتریانِ قدیمی‌تر فعاله.",
    "platform": "این کد برای این پیام‌رسان فعال نیست.",
    "per_customer": "قبلاً از این کد استفاده کرده‌ای.",
    "exhausted": "ظرفیتِ این کد پر شده.",
    "locked": "تلاشِ ناموفقِ زیاد؛ کمی بعد دوباره امتحان کن.",
    "too_low": "با این تخفیف مبلغ از حداقلِ قابل‌پرداخت کمتر می‌شه.",
}


class DiscountError(Exception):
    """خطای کدِ تخفیف؛ ``code`` یکی از کلیدهای ``ERRORS_FA``."""

    def __init__(self, code: str, retry_after: int = 0):
        super().__init__(ERRORS_FA.get(code, code))
        self.code = code
        self.retry_after = retry_after


class DiscountConfigError(ValueError):
    """خطای تعریفِ کد (ورودیِ مالک) — پیامِ فارسی."""


def normalize_code(raw) -> str:
    """ارقامِ فارسی/عربی ← لاتین، حذفِ فاصله/نیم‌فاصله/علائمِ جهت، بزرگ‌حروف. نامعتبر = ``\"\"``."""
    text = str(raw or "").translate(_DIGITS)
    text = "".join(ch for ch in text if not ch.isspace() and ch not in "\u200c\u200d\u200e\u200f\u202a\u202b\u202c\ufeff").upper()
    if not (CODE_MIN <= len(text) <= CODE_MAX) or not _CODE_RE.match(text):
        return ""
    return text


@dataclass(frozen=True)
class CartLine:
    product_id: int
    name: str
    category: str
    unit_price_irr: int
    quantity: int

    @property
    def subtotal_irr(self) -> int:
        return self.unit_price_irr * self.quantity


@dataclass
class DiscountCode:
    id: int
    code: str
    kind: str
    value: int
    max_discount_irr: int = 0
    min_subtotal_irr: int = 0
    applies: str = APPLIES_ALL
    targets: list = field(default_factory=list)  # شناسه‌ی محصول‌ها (int) یا نامِ دسته‌ها (str)
    first_order_only: bool = False
    min_prev_orders: int = 0
    per_customer_limit: int = 0
    total_limit: int = 0
    used_count: int = 0
    starts_ts: int = 0
    ends_ts: int = 0
    platforms: list = field(default_factory=list)  # خالی = همه
    stackable: bool = False
    auto_apply: bool = False
    active: bool = True
    note: str = ""
    created_ts: int = 0


@dataclass
class Resolution:
    subtotal: int
    discount: int
    applied: list  # [(DiscountCode, amount_irr)]

    @property
    def final(self) -> int:
        return self.subtotal - self.discount

    @property
    def codes_text(self) -> str:
        return ",".join(c.code for c, _a in self.applied)


# ------------------------------------------------------------------------------ اسکیما ----

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS discount_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL UNIQUE COLLATE NOCASE,
        kind TEXT NOT NULL,
        value INTEGER NOT NULL,
        max_discount_irr INTEGER NOT NULL DEFAULT 0,
        min_subtotal_irr INTEGER NOT NULL DEFAULT 0,
        applies TEXT NOT NULL DEFAULT 'all',
        target_json TEXT NOT NULL DEFAULT '[]',
        first_order_only INTEGER NOT NULL DEFAULT 0,
        min_prev_orders INTEGER NOT NULL DEFAULT 0,
        per_customer_limit INTEGER NOT NULL DEFAULT 0,
        total_limit INTEGER NOT NULL DEFAULT 0,
        used_count INTEGER NOT NULL DEFAULT 0,
        starts_ts INTEGER NOT NULL DEFAULT 0,
        ends_ts INTEGER NOT NULL DEFAULT 0,
        platforms TEXT NOT NULL DEFAULT '',
        stackable INTEGER NOT NULL DEFAULT 0,
        auto_apply INTEGER NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1,
        note TEXT NOT NULL DEFAULT '',
        created_ts INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS discount_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code_id INTEGER NOT NULL,
        order_id INTEGER NOT NULL,
        platform TEXT NOT NULL,
        chat_id TEXT NOT NULL,
        amount_irr INTEGER NOT NULL,
        released INTEGER NOT NULL DEFAULT 0,
        created_ts INTEGER NOT NULL,
        UNIQUE(order_id, code_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_usage_code ON discount_usage(code_id)",
    "CREATE INDEX IF NOT EXISTS idx_usage_chat ON discount_usage(platform, chat_id)",
    """CREATE TABLE IF NOT EXISTS cart_discounts (
        platform TEXT NOT NULL,
        chat_id TEXT NOT NULL,
        code TEXT NOT NULL,
        updated_ts INTEGER NOT NULL,
        PRIMARY KEY (platform, chat_id)
    )""",
    """CREATE TABLE IF NOT EXISTS discount_attempts (
        platform TEXT NOT NULL,
        chat_id TEXT NOT NULL,
        ts INTEGER NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_attempts_chat ON discount_attempts(platform, chat_id, ts)",
    """CREATE TABLE IF NOT EXISTS campaigns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'announce',
        code_id INTEGER NOT NULL DEFAULT 0,
        text TEXT NOT NULL DEFAULT '',
        photo TEXT NOT NULL DEFAULT '',
        button_label TEXT NOT NULL DEFAULT '',
        button_url TEXT NOT NULL DEFAULT '',
        audience_json TEXT NOT NULL DEFAULT '{}',
        start_ts INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'scheduled',
        broadcast_id INTEGER NOT NULL DEFAULT 0,
        error TEXT NOT NULL DEFAULT '',
        created_ts INTEGER NOT NULL DEFAULT 0,
        launched_ts INTEGER NOT NULL DEFAULT 0
    )""",
)
ORDER_COLUMNS = {
    "subtotal_irr": "INTEGER NOT NULL DEFAULT 0",
    "discount_irr": "INTEGER NOT NULL DEFAULT 0",
    "discount_code": "TEXT NOT NULL DEFAULT ''",
}


def migrate(conn: sqlite3.Connection) -> None:
    """مهاجرتِ ۴ی ``orders.db`` (فراخوانی از ``orders._m4_discounts``)."""
    for stmt in SCHEMA:
        conn.execute(stmt)
    have = {row[1] for row in conn.execute("PRAGMA table_info(orders)").fetchall()}
    for name, decl in ORDER_COLUMNS.items():
        if name not in have:
            conn.execute(f"ALTER TABLE orders ADD COLUMN {name} {decl}")
    conn.execute("UPDATE orders SET subtotal_irr = total_irr WHERE subtotal_irr = 0")  # سفارش‌های قبلی: بدونِ تخفیف


# ------------------------------------------------------------------------------ ردیف ⇄ مدل ----


def _row_to_code(r: sqlite3.Row) -> DiscountCode:
    try:
        targets = json.loads(r["target_json"] or "[]")
    except ValueError:
        targets = []
    return DiscountCode(
        id=r["id"], code=r["code"], kind=r["kind"], value=int(r["value"]), max_discount_irr=int(r["max_discount_irr"]),
        min_subtotal_irr=int(r["min_subtotal_irr"]), applies=r["applies"], targets=targets if isinstance(targets, list) else [],
        first_order_only=bool(r["first_order_only"]), min_prev_orders=int(r["min_prev_orders"]),
        per_customer_limit=int(r["per_customer_limit"]), total_limit=int(r["total_limit"]), used_count=int(r["used_count"]),
        starts_ts=int(r["starts_ts"]), ends_ts=int(r["ends_ts"]),
        platforms=[p for p in (r["platforms"] or "").split(",") if p], stackable=bool(r["stackable"]),
        auto_apply=bool(r["auto_apply"]), active=bool(r["active"]), note=r["note"], created_ts=int(r["created_ts"]),
    )


def validate_code(code: DiscountCode) -> DiscountCode:
    """تعریفِ معتبر یا ``DiscountConfigError`` (فارسی). مقدارها همه ریالِ صحیح‌اند."""
    norm = normalize_code(code.code)
    if not norm:
        raise DiscountConfigError(f"کد باید {CODE_MIN} تا {CODE_MAX} نویسه و فقط حروفِ انگلیسی، عدد، «-» یا «_» باشه.")
    if code.kind not in KINDS:
        raise DiscountConfigError("نوعِ تخفیف معتبر نیست.")
    if not isinstance(code.value, int) or isinstance(code.value, bool) or code.value <= 0:
        raise DiscountConfigError("مقدارِ تخفیف باید عددِ مثبت باشه.")
    if code.kind == KIND_PERCENT and not (1 <= code.value <= 99):
        raise DiscountConfigError("درصدِ تخفیف باید بین ۱ تا ۹۹ باشه (تخفیفِ ۱۰۰٪ مجاز نیست).")
    for label, v in (("سقفِ تخفیف", code.max_discount_irr), ("حداقلِ سبد", code.min_subtotal_irr), ("تعدادِ خریدِ قبلی", code.min_prev_orders),
                     ("سقفِ هر مشتری", code.per_customer_limit), ("سقفِ کل", code.total_limit)):
        if not isinstance(v, int) or v < 0:
            raise DiscountConfigError(f"{label} نمی‌تونه منفی باشه.")
    if code.applies not in APPLIES:
        raise DiscountConfigError("محدوده‌ی تخفیف معتبر نیست.")
    if code.applies != APPLIES_ALL and not code.targets:
        raise DiscountConfigError("برای این محدوده حداقل یک محصول یا دسته انتخاب کن.")
    if len(code.targets) > MAX_TARGETS:
        raise DiscountConfigError("تعدادِ محصول/دسته‌ی انتخاب‌شده زیاده.")
    if code.starts_ts and code.ends_ts and code.ends_ts <= code.starts_ts:
        raise DiscountConfigError("پایانِ بازه باید بعد از شروعش باشه.")
    if any(p not in ("telegram", "bale") for p in code.platforms):
        raise DiscountConfigError("پیام‌رسانِ انتخاب‌شده معتبر نیست.")
    code.code = norm
    code.note = " ".join(str(code.note or "").split())[:200]
    return code


# ------------------------------------------------------------------------------ محاسبه (خالص) ----


def _eligible_base(code: DiscountCode, lines: list) -> int:
    if code.applies == APPLIES_ALL:
        return sum(l.subtotal_irr for l in lines)
    if code.applies == APPLIES_PRODUCTS:
        ids = {int(t) for t in code.targets if str(t).lstrip("-").isdigit()}
        return sum(l.subtotal_irr for l in lines if l.product_id in ids)
    cats = {str(t).strip().lower() for t in code.targets}
    return sum(l.subtotal_irr for l in lines if l.category.strip().lower() in cats)


def raw_amount(code: DiscountCode, lines: list) -> int:
    """مبلغِ تخفیفِ خام (قبل از سقفِ حداقلِ پرداخت)؛ ۰ اگه محصولِ مشمول نباشه."""
    base = _eligible_base(code, lines)
    if base <= 0:
        return 0
    if code.kind == KIND_PERCENT:
        amount = base * code.value // 100
        if code.max_discount_irr:
            amount = min(amount, code.max_discount_irr)
    else:
        amount = min(code.value, base)
    return max(0, amount)


def _usage_counts(conn: sqlite3.Connection, code_id: int, platform: str, chat_id: str) -> int:
    return int(conn.execute(
        "SELECT COUNT(*) FROM discount_usage WHERE code_id=? AND platform=? AND chat_id=? AND released=0", (code_id, platform, str(chat_id))
    ).fetchone()[0])


def _prior_paid_orders(conn: sqlite3.Connection, platform: str, chat_id: str) -> int:
    return int(conn.execute(
        "SELECT COUNT(*) FROM orders WHERE platform=? AND chat_id=? AND status IN ('paid','confirmed')", (platform, str(chat_id))
    ).fetchone()[0])


def check_conditions(conn: sqlite3.Connection, code: DiscountCode, platform: str, chat_id: str, lines: list, now: float) -> int:
    """شرط‌ها را می‌سنجه (``DiscountError``) و مبلغِ خامِ تخفیف را برمی‌گردونه."""
    if not code.active:
        raise DiscountError("inactive")
    if code.starts_ts and now < code.starts_ts:
        raise DiscountError("not_started")
    if code.ends_ts and now >= code.ends_ts:
        raise DiscountError("expired")
    if code.platforms and platform not in code.platforms:
        raise DiscountError("platform")
    if code.total_limit and code.used_count >= code.total_limit:
        raise DiscountError("exhausted")
    subtotal = sum(l.subtotal_irr for l in lines)
    if code.min_subtotal_irr and subtotal < code.min_subtotal_irr:
        raise DiscountError("min_subtotal")
    if code.first_order_only or code.min_prev_orders:
        prior = _prior_paid_orders(conn, platform, chat_id)
        if code.first_order_only and prior > 0:
            raise DiscountError("first_only")
        if code.min_prev_orders and prior < code.min_prev_orders:
            raise DiscountError("min_prev")
    if code.per_customer_limit and _usage_counts(conn, code.id, platform, chat_id) >= code.per_customer_limit:
        raise DiscountError("per_customer")
    amount = raw_amount(code, lines)
    if amount <= 0:
        raise DiscountError("not_applicable")
    return amount


def get_by_code(conn: sqlite3.Connection, raw: str) -> Optional[DiscountCode]:
    norm = normalize_code(raw)
    if not norm:
        return None
    row = conn.execute("SELECT * FROM discount_codes WHERE code=? COLLATE NOCASE", (norm,)).fetchone()
    return _row_to_code(row) if row else None


def _clamp(candidates: list, subtotal: int) -> list:
    """تخفیف‌ها را پشتِ‌هم اعمال می‌کنه تا مبلغِ نهایی هرگز از ``MIN_FINAL_IRR`` کمتر نشه."""
    room = subtotal - MIN_FINAL_IRR
    out = []
    for code, amount in candidates:
        if room <= 0:
            break
        take = min(amount, room)
        if take > 0:
            out.append((code, take))
            room -= take
    return out


def resolve(conn: sqlite3.Connection, platform: str, chat_id: str, lines: list, manual: Optional[str] = None,
            auto: bool = True, now: Optional[float] = None) -> Resolution:
    """تخفیفِ نهایی. کدِ دستی نامعتبر ⇒ ``DiscountError``؛ کدهای خودکارِ نامعتبر بی‌صدا کنار می‌رن.

    قاعده: اگه کدِ دستی هست همان (با خودکارهای ``stackable`` اگه خودش هم stackable باشه)؛ وگرنه بهترین گزینه بینِ
    «جمعِ خودکارهای stackable» و «بهترین خودکارِ غیر-stackable».
    """
    now = time.time() if now is None else now
    subtotal = sum(l.subtotal_irr for l in lines)
    manual_pair = None
    if manual:
        code = get_by_code(conn, manual)
        if code is None:
            raise DiscountError("unknown")
        manual_pair = (code, check_conditions(conn, code, platform, chat_id, lines, now))
    autos = []
    if auto:
        for row in conn.execute("SELECT * FROM discount_codes WHERE active=1 AND auto_apply=1 ORDER BY id").fetchall():
            c = _row_to_code(row)
            if manual_pair and c.id == manual_pair[0].id:
                continue
            try:
                autos.append((c, check_conditions(conn, c, platform, chat_id, lines, now)))
            except DiscountError:
                continue
    stack_autos = [p for p in autos if p[0].stackable]
    if manual_pair:
        chosen = [manual_pair] + (stack_autos if manual_pair[0].stackable else [])
    else:
        single = max((p for p in autos if not p[0].stackable), key=lambda p: p[1], default=None)
        stack_total = sum(a for _c, a in stack_autos)
        chosen = stack_autos if (single is None or stack_total >= single[1]) else [single]
    applied = _clamp(chosen, subtotal)
    if manual_pair and not any(c.id == manual_pair[0].id for c, _a in applied):
        raise DiscountError("too_low")
    return Resolution(subtotal=subtotal, discount=sum(a for _c, a in applied), applied=applied)


# ------------------------------------------------------------------------------ مصرف (داخلِ تراکنش) ----


def consume(conn: sqlite3.Connection, order_id: int, platform: str, chat_id: str, res: Resolution, now: Optional[float] = None) -> None:
    """مصرفِ اتمیکِ کدها؛ سقفِ کل با ``UPDATE ... WHERE used_count < total_limit`` (هم‌زمانی امن). ``DiscountError('exhausted')`` ⇒ تراکنش رولبک."""
    ts = int(time.time() if now is None else now)
    for code, amount in res.applied:
        cur = conn.execute(
            "UPDATE discount_codes SET used_count = used_count + 1 WHERE id=? AND (total_limit = 0 OR used_count < total_limit)", (code.id,)
        )
        if cur.rowcount != 1:
            raise DiscountError("exhausted")
        conn.execute(
            "INSERT INTO discount_usage (code_id, order_id, platform, chat_id, amount_irr, created_ts) VALUES (?, ?, ?, ?, ?, ?)",
            (code.id, order_id, platform, str(chat_id), amount, ts),
        )


def release(conn: sqlite3.Connection, order_id: int) -> int:
    """آزادسازیِ مصرف (لغو/انقضا/رد). idempotent."""
    rows = conn.execute("SELECT id, code_id FROM discount_usage WHERE order_id=? AND released=0", (order_id,)).fetchall()
    for r in rows:
        conn.execute("UPDATE discount_usage SET released=1 WHERE id=?", (r["id"],))
        conn.execute("UPDATE discount_codes SET used_count = MAX(0, used_count - 1) WHERE id=?", (r["code_id"],))
    return len(rows)


def reclaim(conn: sqlite3.Connection, order_id: int) -> int:
    """پرداختِ دیرهنگامِ سفارشِ منقضی/لغوشده: پولِ واقعی رسیده ⇒ مصرف دوباره شمرده می‌شه (بدونِ چکِ سقف)."""
    rows = conn.execute("SELECT id, code_id FROM discount_usage WHERE order_id=? AND released=1", (order_id,)).fetchall()
    for r in rows:
        conn.execute("UPDATE discount_usage SET released=0 WHERE id=?", (r["id"],))
        conn.execute("UPDATE discount_codes SET used_count = used_count + 1 WHERE id=?", (r["code_id"],))
    return len(rows)


def on_transition(conn: sqlite3.Connection, order_id: int, old: str, new: str) -> None:
    if new in ("cancelled", "expired", "rejected"):
        release(conn, order_id)
    elif new == "paid" and old in ("cancelled", "expired"):
        reclaim(conn, order_id)


# ------------------------------------------------------------------------------ مدیریت (UI/ربات) ----


@dataclass
class Preview:
    subtotal: int
    discount: int
    applied: list  # [(DiscountCode, amount)]
    manual_code: str = ""  # کدِ دستیِ ذخیره‌شده در سبد
    manual_error: str = ""  # اگه کدِ دستی دیگه معتبر نیست: کدِ خطا

    @property
    def final(self) -> int:
        return self.subtotal - self.discount


@dataclass
class CodeStats:
    uses: int = 0
    revenue_irr: int = 0
    discount_irr: int = 0


class DiscountStore:
    def __init__(self, order_store, clock=time.time):
        self._orders = order_store
        self._clock = clock

    def _conn(self) -> sqlite3.Connection:
        return self._orders.connection()

    # ---------- CRUD
    def create(self, code: DiscountCode) -> int:
        validate_code(code)
        conn = self._conn()
        try:
            cur = conn.execute(
                """INSERT INTO discount_codes (code, kind, value, max_discount_irr, min_subtotal_irr, applies, target_json,
                   first_order_only, min_prev_orders, per_customer_limit, total_limit, starts_ts, ends_ts, platforms,
                   stackable, auto_apply, active, note, created_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (code.code, code.kind, code.value, code.max_discount_irr, code.min_subtotal_irr, code.applies,
                 json.dumps(code.targets, ensure_ascii=False), int(code.first_order_only), code.min_prev_orders,
                 code.per_customer_limit, code.total_limit, code.starts_ts, code.ends_ts, ",".join(code.platforms),
                 int(code.stackable), int(code.auto_apply), int(code.active), code.note, int(self._clock())),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise DiscountConfigError("این کد قبلاً ساخته شده.") from exc
        return cur.lastrowid

    def get(self, code_id: int) -> Optional[DiscountCode]:
        row = self._conn().execute("SELECT * FROM discount_codes WHERE id=?", (code_id,)).fetchone()
        return _row_to_code(row) if row else None

    def find(self, raw: str) -> Optional[DiscountCode]:
        return get_by_code(self._conn(), raw)

    def list(self, only_active: bool = False) -> list:
        sql = "SELECT * FROM discount_codes" + (" WHERE active=1" if only_active else "") + " ORDER BY id DESC"
        return [_row_to_code(r) for r in self._conn().execute(sql).fetchall()]

    def set_active(self, code_id: int, active: bool) -> bool:
        conn = self._conn()
        cur = conn.execute("UPDATE discount_codes SET active=? WHERE id=?", (int(active), code_id))
        conn.commit()
        return cur.rowcount == 1

    def delete(self, code_id: int) -> bool:
        """فقط کدِ بدونِ مصرف؛ وگرنه فقط غیرفعال می‌شه (آمارِ قدیمی گم نشه)."""
        conn = self._conn()
        used = conn.execute("SELECT COUNT(*) FROM discount_usage WHERE code_id=?", (code_id,)).fetchone()[0]
        if used:
            return False
        cur = conn.execute("DELETE FROM discount_codes WHERE id=?", (code_id,))
        conn.commit()
        return cur.rowcount == 1

    def has_manual_codes(self) -> bool:
        """آیا کدی هست که مشتری بتونه تایپ کنه؟ (برای نمایشِ دکمه‌ی «🎟» فقط وقتی لازمه)"""
        now = self._clock()
        row = self._conn().execute(
            "SELECT 1 FROM discount_codes WHERE active=1 AND auto_apply=0 AND (ends_ts=0 OR ends_ts>?) LIMIT 1", (now,)
        ).fetchone()
        return row is not None

    def stats(self, code_id: int) -> CodeStats:
        """آمار از دادهٔ اصلی (ناوردایی ۲۲): فقط سفارش‌های paid/confirmed."""
        row = self._conn().execute(
            """SELECT COUNT(*) AS n, COALESCE(SUM(o.total_irr), 0) AS rev, COALESCE(SUM(u.amount_irr), 0) AS disc
               FROM discount_usage u JOIN orders o ON o.id = u.order_id
               WHERE u.code_id=? AND u.released=0 AND o.status IN ('paid','confirmed')""",
            (code_id,),
        ).fetchone()
        return CodeStats(uses=int(row["n"]), revenue_irr=int(row["rev"]), discount_irr=int(row["disc"]))

    # ---------- سبدِ مشتری
    def lines_for(self, items: list) -> list:
        """``[(product_id, qty)]`` ← ``CartLine``ها (از محصولاتِ فعلی)."""
        out = []
        for pid, qty in items:
            p = self._orders._products.get(pid)
            if p is not None and qty > 0:
                out.append(CartLine(p.id, p.name, p.category or "", p.price_irr, int(qty)))
        return out

    def cart_code(self, platform: str, chat_id: str) -> str:
        row = self._conn().execute("SELECT code FROM cart_discounts WHERE platform=? AND chat_id=?", (platform, str(chat_id))).fetchone()
        return row["code"] if row else ""

    def clear_cart_code(self, platform: str, chat_id: str) -> None:
        conn = self._conn()
        conn.execute("DELETE FROM cart_discounts WHERE platform=? AND chat_id=?", (platform, str(chat_id)))
        conn.commit()

    def forget_chat(self, platform: str, chat_id: str) -> None:
        """``/forget``: کدِ سبد و تلاش‌های اشتباه پاک می‌شن. ردیفِ مصرف (بدونِ نام/تلفن) می‌مونه تا سقفِ هر مشتری دور زده نشه."""
        conn = self._conn()
        conn.execute("DELETE FROM cart_discounts WHERE platform=? AND chat_id=?", (platform, str(chat_id)))
        conn.execute("DELETE FROM discount_attempts WHERE platform=? AND chat_id=?", (platform, str(chat_id)))
        conn.commit()

    def preview(self, platform: str, chat_id: str, items: list) -> Preview:
        """تخفیفِ فعلیِ سبد (برای نمایش). کدِ دستیِ ناکارآمد کنار گذاشته می‌شه و علتش در ``manual_error`` می‌آد."""
        lines = self.lines_for(items)
        conn = self._conn()
        manual = self.cart_code(platform, chat_id)
        err = ""
        try:
            res = resolve(conn, platform, chat_id, lines, manual or None, now=self._clock())
        except DiscountError as exc:
            err = exc.code
            res = resolve(conn, platform, chat_id, lines, None, now=self._clock())
        return Preview(res.subtotal, res.discount, res.applied, manual_code=manual if not err else "", manual_error=err)

    # ---------- ضدِ brute-force
    def _recent_failures(self, platform: str, chat_id: str, now: float) -> list:
        rows = self._conn().execute(
            "SELECT ts FROM discount_attempts WHERE platform=? AND chat_id=? AND ts>? ORDER BY ts", (platform, str(chat_id), int(now - ATTEMPT_WINDOW_SECONDS))
        ).fetchall()
        return [r["ts"] for r in rows]

    def _record_failure(self, platform: str, chat_id: str, now: float) -> None:
        conn = self._conn()
        conn.execute("INSERT INTO discount_attempts (platform, chat_id, ts) VALUES (?,?,?)", (platform, str(chat_id), int(now)))
        conn.execute("DELETE FROM discount_attempts WHERE ts<=?", (int(now - ATTEMPT_WINDOW_SECONDS),))
        conn.commit()

    def try_set_code(self, platform: str, chat_id: str, raw: str, items: list) -> Preview:
        """کدِ تایپ‌شده‌ی مشتری را اعتبارسنجی و روی سبد می‌گذارد؛ ``DiscountError`` اگه معتبر نباشه."""
        now = self._clock()
        failures = self._recent_failures(platform, chat_id, now)
        if len(failures) >= WRONG_ATTEMPT_LIMIT:
            raise DiscountError("locked", retry_after=max(1, int(failures[0] + ATTEMPT_WINDOW_SECONDS - now)))
        conn = self._conn()
        code = get_by_code(conn, raw)
        if code is None or not code.active:
            self._record_failure(platform, chat_id, now)
            raise DiscountError("unknown")
        lines = self.lines_for(items)
        resolve(conn, platform, chat_id, lines, code.code, auto=False, now=now)  # خطاها (شرط‌ها) بالا می‌رن
        conn.execute(
            "INSERT INTO cart_discounts (platform, chat_id, code, updated_ts) VALUES (?,?,?,?) "
            "ON CONFLICT(platform, chat_id) DO UPDATE SET code=excluded.code, updated_ts=excluded.updated_ts",
            (platform, str(chat_id), code.code, int(now)),
        )
        conn.commit()
        return self.preview(platform, chat_id, items)

    def purge_old(self) -> None:
        conn = self._conn()
        now = int(self._clock())
        conn.execute("DELETE FROM discount_attempts WHERE ts<=?", (now - ATTEMPT_WINDOW_SECONDS,))
        conn.execute("DELETE FROM cart_discounts WHERE updated_ts<=?", (now - 7 * 24 * 3600,))
        conn.commit()


# ------------------------------------------------------------------------------ پیش‌تنظیم‌ها ----


def presets(now: Optional[float] = None) -> list:
    """قالب‌های آماده (``id، عنوانِ فارسی، DiscountCode`` با ``code=''``) — مالک فقط کد/مقدار را تنظیم می‌کند."""
    now = int(time.time() if now is None else now)
    return [
        ("first10", "۱۰٪ اولین خرید", DiscountCode(0, "", KIND_PERCENT, 10, first_order_only=True)),
        ("fixed50k", "۵۰ هزار تومان برای خریدِ بالای ۵۰۰ هزار", DiscountCode(0, "", KIND_FIXED, 500_000, min_subtotal_irr=5_000_000)),
        ("limit100", "کدِ محدود به ۱۰۰ نفر", DiscountCode(0, "", KIND_PERCENT, 15, total_limit=100, per_customer_limit=1)),
        ("weekend", "تخفیفِ خودکارِ آخرِ هفته (۷ روز)", DiscountCode(0, "", KIND_PERCENT, 10, auto_apply=True, starts_ts=now, ends_ts=now + 7 * 86400)),
    ]
