"""لایه‌ی «گزارشِ اکسلِ حرفه‌ای» — یک ``.xlsx``ِ استانداردِ آفیس فقط با کتابخانه‌ی استانداردِ پایتون.

چرا این فایل جدا از ``product_import`` است؟ آنجا فقط «قالبِ خالی» لازم بود (بدونِ سبک). گزارشِ
مدیریتی به این‌ها هم نیاز دارد، پس همین‌جا ساخته می‌شوند (همان ``zip`` + XML، بدونِ openpyxl):

* **سرِ گزارش (header block)** روی هر فایل: عنوانِ گزارش، نامِ فروشگاه، تاریخِ ساخت (جلالی +
  میلادی)، تعدادِ سطور، و خلاصه‌ی اختیاری (مثلِ KPIهایِ مالی).
* **راست‌به‌چپ**: برگه ``rightToLeft="1"`` است، ترتیبِ ستون‌ها از راست (ستون اول = مهم‌ترین) و
  متن‌ها راست‌چین‌اند؛ ستونِ اول پهن‌تر از بقیه.
* **سطرِ عنوان ثابت (frozen)**: ``<pane state="frozen">`` دقیقاً زیرِ سطرِ ستون‌ها، پس با اسکرول
  معلوم نیست کدام ستان چه بود.
* **عددِ واقعی**: پول به‌شکلِ عددِ صحیحِ ریال در سلول می‌نشیند (بدونِ جداکننده، تا اکسل بتواند
  جمع/میانگین بگیرد) و فقط *قالبِ نمایش* هزارگان جدا می‌گذارد. تاریخ جلالی متنی است و کنارش
  ستونِ میلادیِ ISO هم هست (برایِ مرتب‌سازی).
* **سقفِ ۲۰٬۰۰۰ سطر**: بیشتر از آن صادر نمی‌شود و سطرِ پایینیِ سرِ گزارش صریح می‌گوید بریده شده.
* **متنِ دشمن‌شده**: نویسه‌هایِ کنترلی وِ overrideِ جهت (``\u202e`` و…) پاک می‌شوند — همان کاری که
  ``invoice_pdf`` در PDF می‌کند — وگرنه یک نامِ آماده‌شده می‌تواند کلِ سطرِ اکسل را آینه کند.

داده را هیچ‌وقت خودش نمی‌خواند: صفحه‌ها سطرهایِ آماده را به ``*_report(...)`` می‌دهند تا این ماژول
بدونِ دیتابیس هم قابل‌تست باشد. برایِ PDFِ همین گزارش‌ها: ``app.core.report_pdf``.
"""

from __future__ import annotations

import io
import re
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from app.core import jalali
from app.core.paths import get_app_data_dir
# دو اصلِ کوچکِ xlsx که ``product_import`` قبلاً با تست پوشیده: شمارشِ ستونِ اکسل و فرارِ XML.
# اینجا دوباره نوشته نمی‌شوند (همان رفتار، همان خروجیِ آزمون‌پسند).
from app.core.product_import import _column_letters, _xml_escape

MAX_ROWS = 20000  # سقفِ هر خروجی (اکسل و PDF)
EMPTY_ERROR = "چیزی برای خروجی گرفتن نیست."
TRUNCATED_NOTE = f"⚠️ بیش از {MAX_ROWS:,} سطر بود؛ تنها {MAX_ROWS:,} سطرِ نخست صادر شده.".replace(",", "٬")
FOOTER_NOTE = "این گزارش با ابزارِ کمکیِ «کسب‌وکار هوشمند» ساخته شده و جایگزینِ سامانه‌ی مودیان یا حسابدار رسمی نیست."
DEFAULT_SHOP_NAME = "فروشگاهِ من"
REPORT_SUBDIR = "reports"

TEXT = "text"
MONEY = "money"
INT = "int"
DATE = "date"

KIND_CUSTOMERS = "customers"
KIND_ORDERS = "orders"
KIND_FINANCE = "finance"
KIND_PRODUCTS = "products"
KIND_CONVERSATIONS = "conversations"
REPORT_KINDS = (KIND_CUSTOMERS, KIND_ORDERS, KIND_FINANCE, KIND_PRODUCTS, KIND_CONVERSATIONS)

_UNSAFE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u202a-\u202e\u2066-\u2069\u200e\u200f\ufeff]")
_CELL_LIMIT = 8000
_STATUS_FA = {
    "pending_payment": "در انتظارِ پرداخت",
    "paid": "پرداخت‌شده (منتظرِ تایید)",
    "confirmed": "تاییدشده",
    "rejected": "ردشده",
    "cancelled": "لغوشده",
    "expired": "منقضی‌شده",
}
_METHOD_FA = {"card_to_card": "کارت‌به‌کارت", "bale_pay": "بله‌پی", "zarinpal": "زرین‌پال", "": "—", "none": "—"}
_FULFILL_FA = {"": "شروع‌نشده", "preparing": "در حال آماده‌سازی", "shipped": "ارسال شد", "delivered": "تحویل شد"}
_KIND_FA = {"income": "درآمد", "expense": "هزینه", "cogs": "بهای کالا", "refund": "برگشتی"}
_ACCOUNT_FA = {"cash": "نقد", "card": "کارت‌به‌کارت", "bale_pay": "بله‌پی", "zarinpal": "زرین‌پال", "other": "سایر"}


class ReportError(Exception):
    """خطایِ قابل‌نمایشِ فارسی (بدونِ traceback): نبودنِ داده، نشانیِ نوشتنِ خراب، شکستِ PDF."""


def yes_no(value: bool) -> str:
    return "بله" if value else "خیر"


def cell_text(value, limit: int = _CELL_LIMIT) -> str:
    """هر مقدارِ متنی ← تمیز، تک‌خطی، بدونِ نویسه‌هایِ جهت/کنترل، بریده‌شده."""
    text = _UNSAFE.sub(" ", str(value if value is not None else ""))
    text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    return text[:limit]


# ------------------------------------------------------------------ ستون و گزارش ----


@dataclass(frozen=True)
class Column:
    """یک ستونِ گزارش: عنوانِ فارسی، نوعِ داده (برایِ سبک/عدد) و پهنایِ پیشنهادیِ حرفِ اکسل."""

    title: str
    kind: str = TEXT
    width: float = 16.0


@dataclass
class ReportData:
    """همه‌چیزی که یک خروجی (اکسل یا PDF) لازم دارد: سرِ گزارش، ستون‌ها، سطور و پانوشت."""

    kind: str
    title: str
    shop_name: str
    columns: tuple
    rows: list
    generated_ts: float
    summary: tuple = ()
    truncated: bool = False
    footer: str = FOOTER_NOTE

    @property
    def count(self) -> int:
        return len(self.rows)

    @property
    def sheet_name(self) -> str:
        return cell_text(self.title, 28).removeprefix("گزارشِ ")[:28] or "گزارش"

    def jalali_stamp(self) -> str:
        return jalali.format_ts(self.generated_ts, with_time=True, digits="en")

    def iso_stamp(self) -> str:
        return jalali.tehran_dt(self.generated_ts).strftime("%Y-%m-%d %H:%M")

    def preamble(self) -> list:
        """خط‌هایِ سرِ گزارش (عنوان، فروشگاه، تاریخ، تعداد + هشدارِ برشِ سطور)."""
        lines = [
            self.title,
            f"فروشگاه: {self.shop_name}",
            f"تاریخِ ساخت: {self.jalali_stamp()} ({self.iso_stamp()} میلادی)",
            f"تعدادِ سطور: {_fa_count(self.count)}",
        ]
        if self.truncated:
            lines.append(TRUNCATED_NOTE)
        return lines

    def summary_lines(self) -> list:
        """خط‌هایِ ``برچسب: مقدار`` (KPIهایِ مالی و جمعهایِ هر بخش).

        عمداً **زیرِ جدول** نوشته می‌شوند تا سطرِ ثابتِ سرِ گزارش همیشه کوتاه بماند و
        paneِ frozen فقط سطرهایِ ۱ تا ۶ را بگیرد (وگرنه ۲۰ خطِ خلاصه نصفِ صفحه را قفل می‌کرد)."""
        return [f"{label}: {value}" for label, value in self.summary]

    def titles(self) -> tuple:
        return tuple(c.title for c in self.columns)

    def header_index(self) -> int:
        """شماره‌ی سطرِ (۱‌مبنا) ستون‌ها = بعد از سرِ گزارش و یک سطرِ خالی."""
        return len(self.preamble()) + 2

    def pdf_rows(self, cap: int = MAX_ROWS) -> list:
        """سطرهایِ صادرشده در PDF (سقفِ جداگانه برایِ خوانایی و سرعتِ شکل‌دهی حروف)."""
        return self.rows[:cap]


def _fa_count(value: int) -> str:
    return jalali.fa_digits(f"{int(value):,}".replace(",", "٬"))


# ------------------------------------------------------------------ ساختِ گزارش ----


def _dataset(kind: str, title: str, columns: tuple, rows: list, shop_name: str, now: Optional[float],
             summary: tuple = ()) -> ReportData:
    if not rows:
        raise ReportError(EMPTY_ERROR)
    truncated = len(rows) > MAX_ROWS
    return ReportData(
        kind=kind, title=title, shop_name=shop_name or DEFAULT_SHOP_NAME, columns=columns,
        rows=list(rows[:MAX_ROWS]), generated_ts=float(now if now is not None else time.time()),
        summary=tuple(summary), truncated=truncated,
    )


def _ts(value) -> float:
    """unix ثانیه، یا رشته‌ی ``YYYY-MM-DD HH:MM:SS`` (UTC دیتابیس) ← unix؛ هیچ‌چیز ← ۰."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return 0.0
    import calendar

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return float(calendar.timegm(time.strptime(text[:19], fmt)))
        except (ValueError, OverflowError):
            continue
    return 0.0


# سقفِ منطقیِ زمان: بازه‌های «همه‌ی دوره‌ها» با sentinelهایِ بزرگ (۲**۴۰ و…) ساخته می‌شن که برای
# مقایسه در SQL درست‌اند ولی تبدیلِ آنها به تاریخ روی ویندوز با OSError می‌شکند.
_TS_MAX = 4102444800.0  # ۲۱۰۰-۰۱-۰۱


def _dates(value) -> tuple:
    """یک زمانِ دیتابیس ← ``(جلالی، میلادیِ ISO)``؛ هر دو ستونِ متنی (تاریخِ جلالی قابل‌مرتب‌سازی نیست).

    زمانِ ۰ یا.sentinelِ بازه «بدونِ انتها» تاریخ نمی‌گیرد و سلول خالی می‌ماند."""
    ts = _ts(value)
    if not ts or not 0 < ts <= _TS_MAX:
        return "", ""
    return jalali.format_ts(ts, with_time=True, digits="en"), jalali.tehran_dt(ts).strftime("%Y-%m-%d %H:%M")


def _money(value) -> int:
    """پولِ خامِ ریال (عددِ صحیح؛ هیچ جداکننده‌ای در سلول نمی‌نشیند)."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _count(value) -> int:
    return _money(value)


def customers_report(customers: Iterable, *, shop_name: str = "", now: Optional[float] = None) -> ReportData:
    """مشتریان (CRM): همان سطرهایِ ``CustomerStore.list`` (با جست‌وجو/فیلترِ فعالِ صفحه)."""
    columns = (
        Column("نام", TEXT, 26), Column("پلتفرم", TEXT, 12), Column("شناسه‌ی کاربری", TEXT, 16),
        Column("یوزرنیم", TEXT, 16), Column("تلفن", TEXT, 15), Column("زبان", TEXT, 8),
        Column("پیام‌ها", INT, 10), Column("سفارش‌ها", INT, 10), Column("جمعِ خرید (ریال)", MONEY, 16),
        Column("آخرینِ خرید (جلالی)", DATE, 18), Column("آخرینِ بازدید (جلالی)", DATE, 18),
        Column("نخستینِ بازدید (جلالی)", DATE, 18), Column("آخرینِ بازدید (میلادی)", DATE, 18),
        Column("برچسب‌ها", TEXT, 20), Column("یادداشت", TEXT, 32), Column("بلاک", TEXT, 8),
        Column("لغوِ پیام", TEXT, 10), Column("دسترس‌ناپذیر", TEXT, 12),
    )
    rows = []
    for c in customers:
        bought_j, bought_i = _dates(getattr(c, "last_order_ts", 0))
        seen_j, seen_i = _dates(getattr(c, "last_seen_ts", 0))
        first_j, _first_i = _dates(getattr(c, "first_seen_ts", 0))
        rows.append([
            cell_text(c.display_name), cell_text(c.platform), cell_text(c.user_id),
            cell_text(f"@{c.username}" if c.username else ""), cell_text(c.phone), cell_text(c.language_code),
            _count(c.msg_count), _count(c.orders_count), _money(c.total_spent_irr),
            bought_j or "", seen_j, first_j, seen_i or "",
            cell_text("، ".join(c.tags)), cell_text(c.notes), yes_no(c.blocked), yes_no(c.opted_out),
            yes_no(c.unreachable),
        ])
    summary = (
        ("خریدار", _fa_count(sum(1 for r in rows if _count(r[7]) > 0))),
        ("جمعِ خریدِ کل (ریال)", _fa_count(sum(_count(r[8]) for r in rows))),
    )
    return _dataset(KIND_CUSTOMERS, "گزارشِ مشتریان", columns, rows, shop_name, now, summary)


def orders_report(orders: Iterable, *, shop_name: str = "", now: Optional[float] = None) -> ReportData:
    """سفارش‌ها (همان فیلترِ وضعیتِ فعالِ صفحه)."""
    columns = (
        Column("شماره", INT, 10), Column("وضعیت", TEXT, 18), Column("مبلغ (ریال)", MONEY, 16),
        Column("جمعِ اقلام (ریال)", MONEY, 16), Column("تخفیف (ریال)", MONEY, 14), Column("ارسال (ریال)", MONEY, 14),
        Column("اقلام", TEXT, 40), Column("مشتری", TEXT, 22), Column("تلفن", TEXT, 15), Column("نشانی", TEXT, 30),
        Column("پلتفرم", TEXT, 12), Column("شناسه‌ی گفتگو", TEXT, 16), Column("روشِ پرداخت", TEXT, 14),
        Column("کدِ رهگیری", TEXT, 16), Column("وضعیتِ ارسال", TEXT, 16), Column("تاریخ (جلالی)", DATE, 18),
        Column("تاریخ (میلادی)", DATE, 18),
    )
    rows = []
    for o in orders:
        created_j, created_i = _dates(getattr(o, "created_at", "") or getattr(o, "updated_at", ""))
        rows.append([
            _count(o.id), cell_text(_STATUS_FA.get(o.status, o.status)), _money(o.total_irr),
            _money(o.subtotal_irr), _money(o.discount_irr), _money(o.shipping_irr),
            cell_text("، ".join(f"{i.product_name} ×{i.quantity}" for i in (o.items or []))),
            cell_text(o.customer_name), cell_text(o.customer_phone), cell_text(o.customer_address),
            cell_text(o.platform), cell_text(o.chat_id), cell_text(_METHOD_FA.get(o.payment_method, o.payment_method)),
            cell_text(o.tracking_code), cell_text(_FULFILL_FA.get(o.fulfillment, o.fulfillment)), created_j, created_i,
        ])
    summary = (
        ("تعدادِ سفارش", _fa_count(len(rows))),
        ("جمعِ مبلغ (ریال)", _fa_count(sum(_count(r[2]) for r in rows))),
        ("جمعِ تخفیف (ریال)", _fa_count(sum(_count(r[4]) for r in rows))),
    )
    return _dataset(KIND_ORDERS, "گزارشِ سفارش‌ها", columns, rows, shop_name, now, summary)


def finance_report(report, entries: Iterable, *, shop_name: str = "", now: Optional[float] = None) -> ReportData:
    """مالی: سطرهایِ دفترِ آن بازه + خلاصه‌ی KPIِ داشبورد (از ``FinanceStore.report``)."""
    columns = (
        Column("شناسه", INT, 10), Column("نوع", TEXT, 12), Column("دسته", TEXT, 20), Column("مبلغ (ریال)", MONEY, 16),
        Column("حساب", TEXT, 14), Column("توضیح", TEXT, 34), Column("مستند", TEXT, 16),
        Column("برگشت‌خورده", TEXT, 12), Column("تاریخ (جلالی)", DATE, 18), Column("تاریخ (میلادی)", DATE, 18),
    )
    rows = []
    for e in entries:
        signed = int(getattr(e, "signed_irr", e.amount_irr) or 0)
        jal, iso = _dates(e.ts)
        rows.append([
            _count(e.id), cell_text(_KIND_FA.get(e.kind, e.kind)), cell_text(e.category), signed,
            cell_text(_ACCOUNT_FA.get(e.account, e.account)), cell_text(e.note),
            cell_text(f"{e.ref_type}:{e.ref_id}" if e.ref_type else ""),
            yes_no(bool(e.reversed_by_id or e.reverses_id)), jal, iso,
        ])
    period_j, period_i = _dates(getattr(report, "start_ts", 0)) if report is not None else ("", "")
    end_j, _end_i = _dates(getattr(report, "end_ts", 0)) if report is not None else ("", "")
    summary = ()
    if report is not None:
        summary = (
            ("بازه", cell_text(f"{period_j} تا {end_j}")),
            ("فروشِ خالص (ریال)", _fa_count(report.sales_net)),
            ("فروشِ ناخالص (ریال)", _fa_count(report.gross_sales)),
            ("تخفیف‌ها (ریال)", _fa_count(report.discounts)),
            ("کرایه‌ی ارسال (ریال)", _fa_count(report.shipping_income)),
            ("برگشتی (ریال)", _fa_count(report.refunds)),
            ("بهای کالای فروخته‌شده (ریال)", _fa_count(report.cogs)),
            ("سودِ ناخالص (ریال)", _fa_count(report.gross_profit)),
            ("هزینه‌ها (ریال)", _fa_count(report.expenses)),
            ("سودِ خالص (ریال)", _fa_count(report.net_profit)),
            ("سفارش‌هایِ ثبت‌شده", _fa_count(report.orders_count)),
            ("منتظرِ تایید (ریال)", _fa_count(report.receivables_waiting)),
            ("در انتظارِ پرداخت (ریال)", _fa_count(report.receivables_pending)),
            ("ارزشِ موجودی (ریال)", _fa_count(report.inventory_value)),
            ("پرفروش‌ترین‌ها", cell_text(" | ".join(f"{n} ×{q}: {_fa_count(v)}" for n, q, v in report.by_product[:5]))),
            ("بهترینِ مشتری‌ها", cell_text(" | ".join(f"{nm}: {_fa_count(v)}" for _p, _c, nm, v in report.top_customers[:5]))),
            ("میلادیِ بازه", cell_text(f"{period_i} تا {_dates(getattr(report, 'end_ts', 0))[1]}")),
        )
    return _dataset(KIND_FINANCE, "گزارشِ مالی و دفتر", columns, rows, shop_name, now, summary)


def products_report(products: Iterable, *, shop_name: str = "", now: Optional[float] = None) -> ReportData:
    """محصولات/انبار (``ProductStore.list``؛ با «نمایشِ غیرفعال‌ها» همان چیزی است که کاربر می‌بیند)."""
    columns = (
        Column("نام", TEXT, 28), Column("دسته", TEXT, 16), Column("قیمت (ریال)", MONEY, 15),
        Column("بهای تمام‌شده (ریال)", MONEY, 18), Column("سودِ هر واحد (ریال)", MONEY, 16),
        Column("موجودی", INT, 12), Column("موجودیِ نامحدود", TEXT, 14), Column("ارزشِ موجودی (ریال)", MONEY, 18),
        Column("فعال", TEXT, 10), Column("ترتیب", INT, 8), Column("توضیحات", TEXT, 40),
        Column("ساخته‌شده (جلالی)", DATE, 18), Column("ساخته‌شده (میلادی)", DATE, 18),
    )
    rows = []
    for p in products:
        created_j, created_i = _dates(getattr(p, "created_at", ""))
        unlimited = bool(p.unlimited_stock)
        stock = 0 if unlimited else _count(p.stock_quantity)
        rows.append([
            cell_text(p.name), cell_text(p.category), _money(p.price_irr), _money(p.cost_irr),
            _money(p.price_irr) - _money(p.cost_irr), "" if unlimited else stock, yes_no(unlimited),
            _money(p.cost_irr) * stock, yes_no(p.active), _count(p.sort_order), cell_text(p.description),
            created_j, created_i,
        ])
    summary = (
        ("تعدادِ کالا", _fa_count(len(rows))),
        ("موجودیِ کل (عدد)", _fa_count(sum(_count(r[5]) for r in rows))),
        ("ارزشِ انبار به بها (ریال)", _fa_count(sum(_count(r[7]) for r in rows))),
    )
    return _dataset(KIND_PRODUCTS, "گزارشِ محصولات و انبار", columns, rows, shop_name, now, summary)


def conversations_report(conversations: Iterable, *, shop_name: str = "", now: Optional[float] = None) -> ReportData:
    """فهرستِ گفتگوها (``ConversationStore.list_conversations``)."""
    columns = (
        Column("نام", TEXT, 26), Column("پلتفرم", TEXT, 12), Column("شناسه‌ی گفتگو", TEXT, 18),
        Column("بلاک", TEXT, 8), Column("حافظه", TEXT, 10), Column("آخرینِ فعالیت (جلالی)", DATE, 18),
        Column("آخرینِ فعالیت (میلادی)", DATE, 18), Column("پیش‌نمایشِ آخرینِ پیام", TEXT, 46),
    )
    rows = []
    for c in conversations:
        act_j, act_i = _dates(getattr(c, "updated_at", ""))
        rows.append([
            cell_text(c.display_name or c.chat_id), cell_text(c.platform), cell_text(c.chat_id),
            yes_no(c.blocked), yes_no(c.memory_enabled), act_j, act_i, cell_text(c.last_message_preview, 200),
        ])
    summary = (("تعدادِ گفتگو", _fa_count(len(rows))), ("بلاک‌شده", _fa_count(sum(1 for r in rows if r[3] == "بله"))))
    return _dataset(KIND_CONVERSATIONS, "گزارشِ گفتگوها", columns, rows, shop_name, now, summary)


def transcript_report(messages: Iterable, *, conversation=None, shop_name: str = "",
                      now: Optional[float] = None) -> ReportData:
    """تاریخچه‌ی یک گفتگو (``get_messages``/``get_history``): نقش، زمانِ جلالی + میلادی، متن."""
    who = cell_text(getattr(conversation, "display_name", "") or getattr(conversation, "chat_id", "") or "")
    columns = (
        Column("نقش", TEXT, 12), Column("فرستاده (جلالی)", DATE, 18), Column("فرستاده (میلادی)", DATE, 18),
        Column("متنِ پیام", TEXT, 90),
    )
    rows = []
    for m in messages:
        act_j, act_i = _dates(getattr(m, "created_at", ""))
        rows.append([cell_text(_ROLE_FA.get(getattr(m, "role", ""), getattr(m, "role", ""))), act_j, act_i,
                     cell_text(getattr(m, "content", ""), 1200)])
    title = f"گزارشِ گفتگو{(' — ' + who) if who else ''}"
    return _dataset(KIND_CONVERSATIONS, title, columns, rows, shop_name, now, (("گفتگو", who or "—"),))


_ROLE_FA = {"user": "مشتری", "assistant": "ربات", "owner": "شما", "system": "سیستم", "tool": "ابزار"}


# ------------------------------------------------------------------ نوشتنِ اکسل ----


def reports_dir() -> Path:
    """پوشه‌ی خروجیِ گزارش‌ها: ``<داده‌ی برنامه>/reports`` (دقیقاً مثلِ ``exports``ِ قالبِ محصولات)."""
    folder = get_app_data_dir() / REPORT_SUBDIR
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def file_stem(kind: str, ts: float) -> str:
    """نامِ فایلِ بی‌خطر و خوانا: ``customers-20261108-183012-421`` (ارقامِ لاتین، بدونِ فاصله/کاراکترِ ممنوع).

    میلی‌ثانیه لازم است تا دو خروجیِ همانِ‌ثانیه (مثلاً «اکسل» و بعد «PDF»ِ همان بخش) روی هم نوشته نشوند."""
    stamp = jalali.tehran_dt(ts).strftime("%Y%m%d-%H%M%S")
    return f"{re.sub(r'[^a-z_]', '', kind.lower()) or 'report'}-{stamp}-{int((ts % 1) * 1000):03d}"


_STYLE_TITLE, _STYLE_META, _STYLE_HEADER, _STYLE_MONEY, _STYLE_TEXT, _STYLE_INT = 4, 5, 1, 2, 3, 6

_STYLES_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<numFmts count="2"><numFmt numFmtId="164" formatCode="#,##0"/><numFmt numFmtId="165" formatCode="0"/></numFmts>'
    '<fonts count="4">'
    '<font><sz val="11"/><color rgb="FF1C1C1E"/><name val="Tahoma"/></font>'
    '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Tahoma"/></font>'
    '<font><b/><sz val="14"/><color rgb="FF1F6FEB"/><name val="Tahoma"/></font>'
    '<font><sz val="10"/><color rgb="FF787878"/><name val="Tahoma"/></font>'
    "</fonts>"
    '<fills count="3">'
    "<fill><patternFill patternType=\"none\"/></fill>"
    "<fill><patternFill patternType=\"gray125\"/></fill>"
    '<fill><patternFill patternType="solid"><fgColor rgb="FF1F6FEB"/><bgColor indexed="64"/></patternFill></fill>'
    "</fills>"
    '<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>'
    '<border><left/><right/><top/><bottom style="thin"><color rgb="FFD6D6D6"/></bottom><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="7">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"'
    ' applyAlignment="1"><alignment horizontal="right" vertical="center" wrapText="1"/></xf>'
    '<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"'
    ' applyAlignment="1"><alignment horizontal="right"/></xf>'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1"'
    ' applyAlignment="1"><alignment horizontal="right" vertical="center" wrapText="1"/></xf>'
    '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '<xf numFmtId="165" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"'
    ' applyAlignment="1"><alignment horizontal="right"/></xf>'
    "</cellXfs>"
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    "</styleSheet>"
)


def _style_of(column: Column) -> int:
    return {MONEY: _STYLE_MONEY, INT: _STYLE_INT}.get(column.kind, _STYLE_TEXT)


def _cell_xml(ref: str, value, style: int) -> str:
    if isinstance(value, bool):
        value = yes_no(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = int(value) if float(value).is_integer() else value
        return f'<c r="{ref}" s="{style}"><v>{number}</v></c>'
    text = cell_text(value)
    if not text:
        return f'<c r="{ref}" s="{style}"/>'
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{_xml_escape(text)}</t></is></c>'


def _row_xml(index: int, values: list, style: int, *, height: float = 0.0) -> str:
    cells = "".join(_cell_xml(f"{_column_letters(pos)}{index}", value, style) for pos, value in enumerate(values))
    attrs = f' ht="{height:g}" customHeight="1"' if height else ""
    return f'<row r="{index}"{attrs}>{cells}</row>'


def _sheet_xml(data: ReportData) -> str:
    """یک برگه: سرِ گزارش، ستون‌ها (ثابت/فrozen)، سطورِ راست‌به‌چپ و پانوشت."""
    preamble = data.preamble()
    xml_rows: list = []
    index = 1
    for line_no, line in enumerate(preamble):
        xml_rows.append(_row_xml(index, [line], _STYLE_TITLE if line_no == 0 else _STYLE_META,
                                 height=22 if line_no == 0 else 15))
        index += 1
    xml_rows.append(f'<row r="{index}"/>')
    index += 1
    header_row = index
    xml_rows.append(_row_xml(index, list(data.titles()), _STYLE_HEADER, height=20))
    index += 1
    styles = [_style_of(c) for c in data.columns]
    for row in data.rows:
        cells = "".join(_cell_xml(f"{_column_letters(pos)}{index}", value, styles[pos] if pos < len(styles) else _STYLE_TEXT)
                        for pos, value in enumerate(row))
        xml_rows.append(f'<row r="{index}">{cells}</row>')
        index += 1
    xml_rows.append(f'<row r="{index}"/>')
    index += 1
    if data.summary:
        for line in data.summary_lines():
            xml_rows.append(_row_xml(index, [line], _STYLE_META, height=15))
            index += 1
        xml_rows.append(f'<row r="{index}"/>')
        index += 1
    xml_rows.append(_row_xml(index, [data.footer], _STYLE_META))
    width = len(data.columns)
    cols = []
    for pos, column in enumerate(data.columns):
        first = pos == 0
        size = max(float(column.width), 26.0 if first else 9.0)
        cols.append(f'<col min="{pos + 1}" max="{pos + 1}" width="{size:g}" bestFit="1" customWidth="1"/>')
    freeze = header_row
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<dimension ref="A1:{_column_letters(max(width, 1) - 1)}{index}"/>'
        '<sheetViews><sheetView tabSelected="1" rightToLeft="1" workbookViewId="0">'
        f'<pane ySplit="{freeze - 1}" topLeftCell="A{freeze}" activePane="bottomLeft" state="frozen"/>'
        f'<selection pane="bottomLeft" activeCell="A{freeze}" sqref="A{freeze}"/>'
        "</sheetView></sheetViews>"
        '<sheetFormatPr defaultRowHeight="15" baseColWidth="12"/>'
        f'<cols>{"".join(cols)}</cols>'
        f'<sheetData>{"".join(xml_rows)}</sheetData>'
        "</worksheet>"
    )


def zip_bytes(sheet_xml: str, sheet_name: str) -> bytes:
    """``.xlsx`` واقعی از zip + XMLِ استانداردِ پایتون (برگه‌ی سفارشی + styles)."""
    buffer = io.BytesIO()
    safe = _xml_escape(sheet_name[:31] or "گزارش")
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets><sheet name="{safe}" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            "</Relationships>",
        )
        archive.writestr("xl/styles.xml", _STYLES_XML)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buffer.getvalue()


def xlsx_bytes(data: ReportData) -> bytes:
    return zip_bytes(_sheet_xml(data), data.sheet_name)


def write_xlsx(data: ReportData, folder=None) -> Path:
    """گزارش ← فایلِ ``<داده>/reports/<kind>-<تاریخ>.xlsx`` (مسیرِ نوشته‌شده را برمی‌گرداند)."""
    target = Path(folder) if folder is not None else reports_dir()
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{file_stem(data.kind, data.generated_ts)}.xlsx"
    path.write_bytes(xlsx_bytes(data))
    return path


def sheet_xml_of(path) -> str:
    """XMLِ برگه‌ی اول (برایِ بازرسیِ styleها در تست‌ها: pane/cols/s)."""
    with zipfile.ZipFile(io.BytesIO(Path(path).read_bytes())) as archive:
        return archive.read("xl/worksheets/sheet1.xml").decode("utf-8")


def read_report(path, data=None, titles=None) -> tuple:
    """فایلِ ساخته‌شده را با همان خواننده‌ی ``product_import`` می‌خواند: ``(سرِ گزارش، ستون‌ها، سطور)``.

    ``data`` (همان ``ReportData`` که فایل را ساخته) تعدادِ دقیقِ سطور را می‌دهد؛ بی‌آن اولین سطرِ
    چندسلولی را سطرِ ستون‌ها می‌گیرد و سطرهایِ تک‌سلولیِ پایانی (خلاصه/پانوشت) را کنار می‌گذارد."""
    from app.core import product_import

    rows = product_import.read_rows(Path(path))
    wanted = [cell_text(t) for t in (tuple(titles) if titles is not None else (data.titles() if data else ()))]
    index = None
    if wanted:
        for position, row in enumerate(rows):
            if [cell_text(c) for c in row[:len(wanted)]] == wanted:
                index = position
                break
    else:
        index = next((i for i, row in enumerate(rows) if sum(1 for c in row if c) > 1), len(rows))
    if index is None:
        raise ReportError("سطرِ عنوانِ ستون‌ها در فایلِ اکسل پیدا نشد؛ فایلِ دست‌ساز نیست.")
    header = [cell_text(c) for c in rows[index]]
    preamble = [cell_text(row[0]) for row in rows[:index] if row and cell_text(row[0])]
    if data is not None:
        return preamble, header, [list(row) for row in rows[index + 1: index + 1 + data.count]]
    return preamble, header, _strip_tail([list(row) for row in rows[index + 1:]])


def _strip_tail(body: list) -> list:
    """بلوکِ پایانی (سطرِ خالی + خلاصه + پانوشت) همه تک‌سلولی‌اند؛ سطورِ گزارش نه."""
    while body and sum(1 for cell in body[-1] if cell_text(cell)) < 2:
        body.pop()
    return body


def shop_name_of(source=None) -> str:
    """نامِ فروشگاه برایِ سرِ گزارش: تنظیماتِ خودشان یا هر شیءِ دارایِ ``settings``/``_settings``.

    صفحه‌ها یکی از این دو را دارند (مالی «تنظیمات» می‌گیرد، گفتگوها فقط ``manager``) — پس همین‌جا
    یک‌بار حل می‌شود و هیچ صفحه‌ای به کلیدهایِ تنظیمات وابسته نمی‌شود."""
    settings = _settings_of(source)
    for key in ("invoice_seller_name", "shop_name", "user_name"):
        value = cell_text(getattr(settings, key, ""), 60)
        if value:
            return value
    return DEFAULT_SHOP_NAME


def _settings_of(source):
    if source is None:
        return None
    if any(hasattr(source, key) for key in ("invoice_seller_name", "shop_name", "user_name")):
        return source
    for attr in ("settings", "_settings"):
        nested = getattr(source, attr, None)
        if nested is not None:
            return _settings_of(nested)
    return None
