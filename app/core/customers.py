"""مشتریان (N12 — CRM): پروفایلِ هر مشتری، آمارِ خرید، برچسب/یادداشت و خروجیِ CSV.

اصول:

* **فقط چیزی که خودِ پلتفرم می‌فرسته** ذخیره می‌شه (نام، یوزرنیم، زبان، پرمیوم)؛ هیچ‌چیز حدس زده یا از جای دیگه پیدا نمی‌شه.
  **شماره‌ی تلفن فقط وقتی ذخیره می‌شه که خودِ مشتری با دکمه‌ی «اشتراکِ شماره» داده باشه.**
* آمارِ خرید (تعداد/مبلغ/آخرین سفارش) ذخیره نمی‌شه؛ هر بار از دیتابیسِ سفارش‌ها محاسبه می‌شه (فقط سفارش‌های پرداخت‌شده/
  تأییدشده) تا هیچ‌وقت با سفارش‌ها ناهم‌خوان نشه.
* حریم: ``/forget`` و نگه‌داریِ محدود (retention) ردیف را در ``ConversationStore`` پاک می‌کنن.
* بلاک‌بودن در جدولِ ``conversations`` است (منبعِ حقیقتِ واحد)؛ اینجا فقط خونده می‌شه.
"""

from __future__ import annotations

import csv
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from app.core.conversations import ConversationStore

MAX_NAME = 128
MAX_USERNAME = 64
MAX_PHONE = 32
MAX_NOTES = 2000
MAX_TAGS = 20
MAX_TAG_LEN = 32

FILTER_ALL = "all"
FILTER_BUYERS = "buyers"
FILTER_NO_ORDERS = "no_orders"
FILTER_BLOCKED = "blocked"
FILTER_OPTED_OUT = "opted_out"
FILTER_UNREACHABLE = "unreachable"
FILTER_NEW = "new_7d"
FILTER_INACTIVE = "inactive_30d"
FILTERS = (FILTER_ALL, FILTER_BUYERS, FILTER_NO_ORDERS, FILTER_NEW, FILTER_INACTIVE, FILTER_BLOCKED, FILTER_OPTED_OUT, FILTER_UNREACHABLE)

SORT_LAST_SEEN = "last_seen"
SORT_FIRST_SEEN = "first_seen"
SORT_ORDERS = "orders"
SORT_SPENT = "spent"
SORT_MESSAGES = "messages"
SORT_NAME = "name"
SORTS = (SORT_LAST_SEEN, SORT_FIRST_SEEN, SORT_ORDERS, SORT_SPENT, SORT_MESSAGES, SORT_NAME)

_DAY = 86400
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_TAG_SPLIT = re.compile(r"[,،;\n]+")
_PHONE_SAFE = re.compile(r"[+\-]?[\d\s().\-]+")


def _clean(text, limit: int) -> str:
    return _CONTROL.sub(" ", str(text or "")).strip()[:limit]


def _clean_phone(text) -> str:
    return re.sub(r"[^\d+]", "", str(text or ""))[:MAX_PHONE]


def parse_tags(value) -> list:
    """برچسب‌ها را از متنِ آزاد (جداشده با ویرگول فارسی/انگلیسی، ؛ یا خطِ جدید) یا فهرست می‌سازه: بدونِ تکرار، حداکثر ۲۰ تا."""
    parts = _TAG_SPLIT.split(value) if isinstance(value, str) else [str(v) for v in (value or [])]
    seen, tags = set(), []
    for part in parts:
        tag = " ".join(_clean(part, MAX_TAG_LEN).replace(",", " ").replace("،", " ").split())
        if tag and tag.casefold() not in seen:
            seen.add(tag.casefold())
            tags.append(tag)
        if len(tags) >= MAX_TAGS:
            break
    return tags


@dataclass
class Customer:
    platform: str
    user_id: str
    first_name: str = ""
    last_name: str = ""
    username: str = ""
    language_code: str = ""
    is_premium: bool = False
    phone: str = ""
    first_seen_ts: int = 0
    last_seen_ts: int = 0
    msg_count: int = 0
    tags: list = field(default_factory=list)
    notes: str = ""
    opted_out: bool = False
    unreachable: bool = False
    blocked: bool = False
    orders_count: int = 0
    total_spent_irr: int = 0
    last_order_ts: int = 0

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p)

    @property
    def display_name(self) -> str:
        return self.full_name or (f"@{self.username}" if self.username else self.user_id)


def _row_to_customer(row, stats: dict) -> Customer:
    n, total, last = stats.get((row["platform"], row["user_id"]), (0, 0, 0))
    return Customer(
        platform=row["platform"], user_id=row["user_id"], first_name=row["first_name"], last_name=row["last_name"],
        username=row["username"], language_code=row["language_code"], is_premium=bool(row["is_premium"]), phone=row["phone"],
        first_seen_ts=int(row["first_seen_ts"]), last_seen_ts=int(row["last_seen_ts"]), msg_count=int(row["msg_count"]),
        tags=parse_tags(row["tags"]), notes=row["notes"], opted_out=bool(row["opted_out"]), unreachable=bool(row["unreachable"]),
        blocked=bool(row["blocked"]), orders_count=n, total_spent_irr=total, last_order_ts=last,
    )


_SELECT = (
    "SELECT cu.*, COALESCE(co.blocked, 0) AS blocked FROM customers cu "
    "LEFT JOIN conversations co ON co.platform = cu.platform AND co.chat_id = cu.user_id"
)


class CustomerStore:
    """یک نمونه برای کلِ برنامه؛ از اتصالِ هر تردِ ``ConversationStore`` استفاده می‌کنه (جدولِ ``customers`` در همان دیتابیس)."""

    def __init__(self, store: ConversationStore, order_store=None):
        self._store = store
        self._orders = order_store

    def _conn(self):
        return self._store.connection()

    def _stats(self) -> dict:
        if self._orders is None:
            return {}
        try:
            return self._orders.customer_stats()
        except Exception:  # noqa: BLE001 — خرابیِ آمار نباید CRM را از کار بندازه
            return {}

    # ---------------------------------------------------------------- ثبت ----

    def touch(self, message, *, now: Optional[float] = None) -> None:
        """هر پیامِ ورودی: ردیف را می‌سازه/به‌روز می‌کنه. هویتِ خالی (مثلاً کلیکِ دکمه بدونِ نام) مقدارِ قبلی را پاک نمی‌کنه؛
        ولی اگه پلتفرم هویت فرستاده باشه، هر سه (نام/نام‌خانوادگی/یوزرنیم) همان‌طور که هست جایگزین می‌شن (کاربر می‌تونه حذفشان کند).
        فقط پیام‌ها (نه کلیکِ دکمه) به شمارنده‌ی پیام اضافه می‌شن؛ شماره فقط اگه خودِ مشتری داده باشه."""
        platform, user_id = str(message.platform), str(message.chat_id)
        first, last = _clean(getattr(message, "first_name", ""), MAX_NAME), _clean(getattr(message, "last_name", ""), MAX_NAME)
        username = _clean(getattr(message, "username", ""), MAX_USERNAME).lstrip("@")
        if not (first or last):  # پلتفرم/مسیری که فقط «نامِ نمایشی» داره
            shown = _clean(getattr(message, "display_name", ""), MAX_NAME)
            if shown and shown != user_id and shown.lstrip("@").lower() != username.lower():
                first = shown
        ts = int(now if now is not None else time.time())
        is_message = not getattr(message, "callback_data", "")
        self._conn().execute(
            """
            INSERT INTO customers (platform, user_id, first_name, last_name, username, language_code, is_premium, phone,
                                   first_seen_ts, last_seen_ts, msg_count)
            VALUES (:platform, :user_id, :first, :last, :username, :lang, :premium, :phone, :ts, :ts, :inc)
            ON CONFLICT(platform, user_id) DO UPDATE SET
                first_name = CASE WHEN :ident THEN :first ELSE customers.first_name END,
                last_name = CASE WHEN :ident THEN :last ELSE customers.last_name END,
                username = CASE WHEN :ident THEN :username ELSE customers.username END,
                is_premium = CASE WHEN :ident THEN :premium ELSE customers.is_premium END,
                language_code = CASE WHEN :lang != '' THEN :lang ELSE customers.language_code END,
                phone = CASE WHEN :phone != '' THEN :phone ELSE customers.phone END,
                first_seen_ts = CASE WHEN customers.first_seen_ts = 0 THEN :ts ELSE customers.first_seen_ts END,
                last_seen_ts = :ts,
                msg_count = customers.msg_count + :inc,
                unreachable = 0
            """,
            {
                "platform": platform, "user_id": user_id, "first": first, "last": last, "username": username,
                "lang": _clean(getattr(message, "language_code", ""), 16), "premium": 1 if getattr(message, "is_premium", False) else 0,
                "phone": _clean_phone(getattr(message, "phone", "")), "ts": ts, "inc": 1 if is_message else 0,
                "ident": 1 if (first or last or username) else 0,
            },
        )
        self._conn().commit()

    # --------------------------------------------------------------- خواندن ----

    def get(self, platform: str, user_id: str) -> Optional[Customer]:
        row = self._conn().execute(_SELECT + " WHERE cu.platform = ? AND cu.user_id = ?", (platform, str(user_id))).fetchone()
        return _row_to_customer(row, self._stats()) if row else None

    def count(self) -> int:
        return int(self._conn().execute("SELECT COUNT(*) FROM customers").fetchone()[0])

    def list(
        self,
        search: str = "",
        flt: str = FILTER_ALL,
        sort: str = SORT_LAST_SEEN,
        platform: Optional[str] = None,
        tag: Optional[str] = None,
        now: Optional[float] = None,
    ) -> list:
        """فهرستِ مشتریان با جست‌وجو (همه‌ی کلمات باید باشن: نام/یوزرنیم/شماره/شناسه/برچسب/یادداشت)، فیلتر و مرتب‌سازی."""
        stats, current = self._stats(), now if now is not None else time.time()
        rows = self._conn().execute(_SELECT + (" WHERE cu.platform = ?" if platform else ""), (platform,) if platform else ()).fetchall()
        customers = [_row_to_customer(r, stats) for r in rows]
        if tag:
            wanted = tag.casefold()
            customers = [c for c in customers if any(x.casefold() == wanted for x in c.tags)]
        keep = {
            FILTER_BUYERS: lambda c: c.orders_count > 0,
            FILTER_NO_ORDERS: lambda c: c.orders_count == 0,
            FILTER_BLOCKED: lambda c: c.blocked,
            FILTER_OPTED_OUT: lambda c: c.opted_out,
            FILTER_UNREACHABLE: lambda c: c.unreachable,
            FILTER_NEW: lambda c: current - c.first_seen_ts <= 7 * _DAY,
            FILTER_INACTIVE: lambda c: current - c.last_seen_ts > 30 * _DAY,
        }.get(flt)
        if keep is not None:
            customers = [c for c in customers if keep(c)]
        tokens = [tok.lstrip("@") for tok in search.casefold().split() if tok.lstrip("@")]
        if tokens:
            def haystack(c: Customer) -> str:
                return " ".join([c.full_name, c.username, c.user_id, c.phone, re.sub(r"\D", "", c.phone), " ".join(c.tags), c.notes]).casefold()

            customers = [c for c in customers if all(tok in haystack(c) for tok in tokens)]
        order = {
            SORT_FIRST_SEEN: lambda c: (-c.first_seen_ts,),
            SORT_ORDERS: lambda c: (-c.orders_count, -c.total_spent_irr),
            SORT_SPENT: lambda c: (-c.total_spent_irr, -c.orders_count),
            SORT_MESSAGES: lambda c: (-c.msg_count,),
            SORT_NAME: lambda c: (c.display_name.casefold(),),
        }.get(sort, lambda c: (-c.last_seen_ts,))
        return sorted(customers, key=lambda c: (*order(c), -c.last_seen_ts, c.platform, c.user_id))

    def token_usage(self, platform: str, user_id: str) -> tuple:
        """``(تعدادِ فراخوانیِ AI، توکنِ تخمینی)`` در کلِ روزها (از جدولِ مصرفِ روزانه)."""
        row = self._conn().execute(
            "SELECT COALESCE(SUM(ai_calls), 0), COALESCE(SUM(tokens_est), 0) FROM usage WHERE platform = ? AND chat_id = ?",
            (platform, str(user_id)),
        ).fetchone()
        return int(row[0]), int(row[1])

    def all_tags(self) -> list:
        """``[(برچسب, تعداد)]`` مرتب بر اساس تعدادِ مشتری."""
        counts: dict = {}
        for row in self._conn().execute("SELECT tags FROM customers WHERE tags != ''").fetchall():
            for tag in parse_tags(row["tags"]):
                key = tag.casefold()
                shown, n = counts.get(key, (tag, 0))
                counts[key] = (shown, n + 1)
        return sorted(counts.values(), key=lambda item: (-item[1], item[0].casefold()))

    # --------------------------------------------------------------- ویرایش ----

    def _update(self, platform: str, user_id: str, column: str, value) -> bool:
        cur = self._conn().execute(f"UPDATE customers SET {column} = ? WHERE platform = ? AND user_id = ?", (value, platform, str(user_id)))  # noqa: S608 — column فقط از کدِ خودمونه
        self._conn().commit()
        return cur.rowcount > 0

    def set_tags(self, platform: str, user_id: str, tags) -> list:
        clean = parse_tags(tags)
        self._update(platform, user_id, "tags", ", ".join(clean))
        return clean

    def set_notes(self, platform: str, user_id: str, notes: str) -> bool:
        return self._update(platform, user_id, "notes", str(notes or "").replace("\x00", "").strip()[:MAX_NOTES])

    def set_opted_out(self, platform: str, user_id: str, value: bool = True) -> bool:
        return self._update(platform, user_id, "opted_out", 1 if value else 0)

    def mark_unreachable(self, platform: str, user_id: str, value: bool = True) -> bool:
        """وقتی ارسال به مشتری شکست می‌خوره (ربات را بلاک کرده/حسابش بسته شده). با اولین پیامِ بعدیِ خودش برمی‌گرده."""
        return self._update(platform, user_id, "unreachable", 1 if value else 0)

    def delete(self, platform: str, user_id: str) -> bool:
        cur = self._conn().execute("DELETE FROM customers WHERE platform = ? AND user_id = ?", (platform, str(user_id)))
        self._conn().commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------ CSV ----

    CSV_COLUMNS = (
        "platform", "user_id", "name", "username", "phone", "language", "first_seen", "last_seen", "messages", "orders",
        "total_spent", "last_order", "tags", "notes", "blocked", "opted_out", "unreachable",
    )

    @staticmethod
    def csv_safe(value) -> str:
        """جلوگیری از «تزریقِ فرمول» در Excel: سلول‌هایی که با = @ تب/CR شروع می‌شن (و + یا - که شماره‌ی تلفن/عدد نیست) پیشوندِ ' می‌گیرن."""
        text = "" if value is None else str(value)
        if text[:1] in ("=", "@", "\t", "\r") or (text[:1] in ("+", "-") and not _PHONE_SAFE.fullmatch(text)):
            return "'" + text
        return text

    @staticmethod
    def _stamp(ts: int) -> str:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else ""

    def export_rows(self, customers: Iterable[Customer]) -> list:
        return [
            [
                c.platform, c.user_id, c.full_name, c.username, c.phone, c.language_code, self._stamp(c.first_seen_ts),
                self._stamp(c.last_seen_ts), c.msg_count, c.orders_count, c.total_spent_irr, self._stamp(c.last_order_ts),
                ", ".join(c.tags), c.notes.replace("\r", " ").replace("\n", " "), int(c.blocked), int(c.opted_out), int(c.unreachable),
            ]
            for c in customers
        ]

    def export_csv(self, path, customers: Iterable[Customer], headers=None) -> int:
        """CSV (UTF-8 با BOM تا Excel فارسی را درست بخونه). تعدادِ ردیف‌ها را برمی‌گردونه."""
        rows = self.export_rows(customers)
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([self.csv_safe(h) for h in (headers or self.CSV_COLUMNS)])
            for row in rows:
                writer.writerow([self.csv_safe(cell) for cell in row])
        return len(rows)
