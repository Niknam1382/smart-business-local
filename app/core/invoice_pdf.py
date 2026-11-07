"""
PDFِ فارسیِ (راست‌به‌چپ) فاکتور — ``fpdf2`` + ``uharfbuzz`` (شکل‌دهی حروف فارسی) + فونت Vazirmatn (OFL).

- بدون باینری خارجی؛ همه‌ی وابستگی‌ها wheel آماده دارند. داخل exeِ PyInstaller روی ویندوز واقعی
  *تأییدنشده* است؛ هر خطا ``InvoicePdfError`` می‌شود و سرویس فاکتور به فاکتور متنی fallback می‌کند.
- خروجی **قطعی** است (تاریخ ساخت = تاریخ صدور، بدون شناسه تصادفی): از snapshot هر وقت بخواهیم
  دقیقاً همان بایت‌ها می‌سازیم، پس PDF لازم نیست در پشتیبان باشد.
- متن خریدار/فروشنده/نام کالا نامطمئن است: نویسه‌های کنترلی و bidi-override حذف و هر نویسه‌ای که
  فونت ندارد (ایموجی و…) دور ریخته می‌شود.
- چیدمان: سربرگ رنگی با لوگو، کارت شماره/تاریخ، جدول اقلام با **شکست خط نام کالا** (هیچ واژه‌ای
  بی‌صدا حذف نمی‌شود)، ردیف‌های یک‌درمیان، تکرار سرستون در صفحه بعد، کادر جمع‌ها، QR راستی‌آزمایی
  و شماره صفحه.
- **ریاضیِ فاکتور (قلم ۱۰):** قیمت‌ها «با مالیات» هستند، پس مالیات بر ارزش افزوده *جمعِ اضافه* نیست؛
  به‌صورتِ یک خطِ اطلاعاتیِ جدا زیرِ «جمع کل» نشان داده می‌شود. ترتیبِ نمایش دقیقاً همین است:
  جمع اقلام − تخفیف + ارسال = جمع کل، و «از این مبلغ، مالیات …».
"""

from __future__ import annotations

import datetime as _dt
import re
import sys
import warnings
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Optional

from app.core import jalali
from app.core.invoices import ANON_NAME, Invoice

MAX_LOGO_BYTES = 300 * 1024
_PAY_LABEL = {"card_to_card": ("کارت‌به‌کارت", "Card to card"), "bale_pay": ("بله‌پی", "Bale Pay")}
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f‪-‮⁦-⁩‎‏]")
_MUTED = (120, 120, 120)
_INK = (28, 28, 30)
_LINE = (214, 214, 214)
_ZEBRA = (247, 246, 243)


class InvoicePdfError(Exception):
    """ساختِ PDF ناموفق بود (کتابخانه/فونت/ورودی)."""


# برچسب‌هایِ فاکتور. ``Invoice.lang`` — همان ستونی که در دیتابیس بود و هیچ‌جا خوانده نمی‌شد —
# حالا تعیین می‌کند فاکتور فارسی چاپ شود یا انگلیسی.
LABELS = {
    "sale": ("فاکتور فروش", "Sales invoice"),
    "credit": ("فاکتور برگشتی", "Credit note"),
    "number": ("شماره", "No."),
    "date": ("تاریخ", "Date"),
    "order": ("سفارش", "Order"),
    "buyer": ("خریدار", "Customer"),
    "phone": ("تلفن", "Phone"),
    "address": ("نشانی", "Address"),
    "pay_method": ("روش پرداخت", "Payment method"),
    "trace": ("کد پیگیری/تراکنش", "Tracking / transaction code"),
    "ref_invoice": ("مربوط به فاکتور", "Against invoice"),
    "seller_address": ("نشانی", "Address"),
    "national_id": ("شناسه ملی/اقتصادی", "National / economic ID"),
    "col_row": ("ردیف", "No."),
    "col_item": ("شرح کالا", "Item"),
    "col_qty": ("تعداد", "Qty"),
    "col_unit": ("قیمت واحد (ریال)", "Unit price (IRR)"),
    "col_total": ("مبلغ (ریال)", "Amount (IRR)"),
    "subtotal": ("جمع اقلام", "Items total"),
    "discount": ("تخفیف", "Discount"),
    "shipping": ("هزینه ارسال", "Shipping"),
    "shipping_note": ("روش ارسال", "Shipping method"),
    "total": ("جمع کل (مبلغ قابل پرداخت)", "Total payable"),
    "final": ("مبلغ نهایی", "Final amount"),
    "refund": ("مبلغ برگشتی", "Refund amount"),
    "vat": ("که از این مبلغ، مالیات بر ارزش افزوده", "of which VAT"),
    "verify": ("راستی‌آزمایی فاکتور", "Invoice verification"),
    "page": ("صفحه", "Page"),
    "of": ("از", "of"),
    "rial": ("ریال", "IRR"),
    "disclaimer": (
        "این فاکتور با ابزار کمکی «کسب‌وکار هوشمند» ساخته شده و جایگزین سامانه مودیان یا حسابدار رسمی نیست.",
        "Produced with the Smart Business helper tool; not a tax-authority filing or a formal accounting statement.",
    ),
}

# عرضِ ستون‌ها به نسبتِ عرضِ مفید؛ جمعشان باید ۱ شود (فاصله‌ها داخلِ cell مدیریت می‌شوند).
_COLUMN_RATIOS = (0.055, 0.43, 0.09, 0.205, 0.22)
_COLUMN_KEYS = ("col_row", "col_item", "col_qty", "col_unit", "col_total")
_BOTTOM_GUARD = 22.0  # میلی‌مترِ امنِ پایینِ صفحه — هیچ کادری روی پابرگ نمی‌افتد


def label(key: str, lang: str) -> str:
    fa, en = LABELS[key]
    return en if lang == "en" else fa


def _pyinstaller_hint() -> None:  # pragma: no cover — فقط برای تحلیل ایستای PyInstaller (ایمپورت تنبل)
    import fontTools.ttLib  # noqa: F401
    import fpdf  # noqa: F401
    import segno  # noqa: F401
    import uharfbuzz  # noqa: F401


def _fonts_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "assets" / "fonts"
    return Path(__file__).resolve().parents[2] / "assets" / "fonts"


@lru_cache(maxsize=1)
def _glyphs() -> frozenset:
    from fontTools.ttLib import TTFont

    return frozenset(TTFont(str(_fonts_dir() / "Vazirmatn-Regular.ttf")).getBestCmap().keys())


def clean(text, limit: int = 300) -> str:
    """متن نامطمئن ← فقط نویسه‌هایی که فونت دارد (ZWNJ می‌ماند)؛ بدون ایموجی/کنترل/override."""
    glyphs = _glyphs()
    out = "".join(ch for ch in _CTRL.sub(" ", str(text or "")) if ord(ch) in glyphs or ch in "‌\n")
    return out.strip()[:limit]


def money(n: int, digits: str = "fa") -> str:
    s = f"{int(n):,}"
    return jalali.fa_digits(s.replace(",", "٬")) if digits == "fa" else s


def _num(value, digits: str) -> str:
    return jalali.fa_digits(str(value)) if digits == "fa" else str(value)


def _hex_rgb(color: str):
    try:
        return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    except (ValueError, TypeError):
        return (31, 111, 235)


def _load_logo(path: str) -> Optional[bytes]:
    if not path:
        return None
    try:
        p = Path(path)
        if not p.is_file() or p.stat().st_size > MAX_LOGO_BYTES:
            return None
        data = p.read_bytes()
    except OSError:
        return None
    return data if data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff" else None


def wrap_lines(pdf, text: str, width: float, max_lines: int = 3) -> list:
    """شکست متن به خط‌ها با عرض واقعیِ همان فونت (بدونِ APIهای نسخه‌به‌نسخه‌ای fpdf).

    دو قولِ سخت: (۱) تا جا باشد هیچ واژه‌ای حذف نمی‌شود؛ (۲) اگر جا نبود، خطِ آخر با «…» بسته
    می‌شود — پس نامِ کالا هرگز نصفه‌ی بی‌علامت روی فاکتور نمی‌آید."""
    words = (text or "").split(" ")
    lines: list = []
    current = ""
    overflow = False
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or pdf.get_string_width(candidate) <= width:
            current = candidate
            continue
        if len(lines) >= max_lines - 1:  # خطِ آخر پر است؛ برش را علامت می‌زنیم
            overflow = True
            break
        lines.append(current)
        current = word
    if current and len(lines) < max_lines:
        lines.append(current)
    if lines and (overflow or pdf.get_string_width(lines[-1]) > width):
        clipped = lines[-1]
        while clipped and pdf.get_string_width(clipped + "…") > width:
            clipped = clipped[:-1]
        lines[-1] = (clipped.rstrip() + "…") if clipped else "…"
    return [ln for ln in lines if ln] or ["—"]


def seller_name(seller: dict) -> str:
    return clean(seller.get("name", ""), 40)


def _verify_payload(inv: Invoice) -> str:
    return f"sbl-invoice|{inv.number}|{int(inv.total_irr)}|{inv.issued_ts}"


def _qr_png(text: str) -> Optional[bytes]:
    try:
        import segno

        buffer = BytesIO()
        segno.make(text, error="M").save(buffer, kind="png", scale=4, border=1)
        return buffer.getvalue()
    except Exception:  # noqa: BLE001 — نبود QR یعنی فاکتور ساخته می‌شود
        return None


class _PageStampPDFMixin:
    """`footer()` فاکتور: نامِ فروشگاه سمتِ چپ و «صفحه X از N» سمتِ راست، روی هر صفحه.

    fpdf2 تعدادِ نهاییِ صفحه‌ها را با جایگزینِ ``{nb}`` در پایانِ ساخت می‌نویسد، پس این تنها
    راهِ شماره‌گذاریِ چندصفحه‌ای است (در fpdf2 متدِ go_to_page وجود ندارد)."""

    stamp_ctx: dict = None

    def footer(self) -> None:
        ctx = self.stamp_ctx
        if not ctx:
            return
        self.set_y(-12)
        self.set_font("V", "", 7.5)
        self.set_text_color(*_MUTED)
        lang = ctx.get("lang", "fa")
        # self.w خودش «عرضِ مفید» (پنجره منهای مارجین) است؛ کم‌کردنِ دوباره‌ی مارجین، متن را ۱۲ میلی‌متر جابه‌جا می‌کرد
        half = self.w / 2
        self.cell(half, 5, ctx.get("name", ""), align="L", new_x="RIGHT", new_y="TOP")
        counter = f"{label('page', lang)} {_num(self.page_no(), ctx['digits'])} {label('of', lang)} {_num('{nb}', ctx['digits'])}"
        self.cell(half, 5, counter, align="R", new_x="LMARGIN", new_y="NEXT")


class _InvoicePDF:
    """سازندهٔ صفحهٔ فاکتور؛ geometry و رنگ‌ها یک‌جا، تا چیدمان قابل‌حدس‌زدن و قطعی بماند."""

    def __init__(self, inv: Invoice):
        self.inv = inv
        self.digits = "en" if inv.seller.get("digits") == "en" else "fa"
        self.lang = "en" if getattr(inv, "lang", "fa") == "en" else "fa"
        self.brand = _hex_rgb(inv.seller.get("color", ""))
        paper = inv.seller.get("paper") if inv.seller.get("paper") in ("A4", "A5") else "A4"
        self.paper = paper
        from fpdf import FPDF

        class _Pdf(_PageStampPDFMixin, FPDF):
            pass

        with warnings.catch_warnings():  # fpdf2 برای A5 هشدار «ابعاد اصلاح شد» می‌دهد؛ همان اصلاحِ ماست
            warnings.simplefilter("ignore", UserWarning)
            self.pdf = _Pdf(format=paper, unit="mm")
        self.pdf.alias_nb_pages()
        pdf = self.pdf
        pdf.set_margins(12, 12, 12)
        pdf.set_auto_page_break(True, 18)
        fonts = _fonts_dir()
        pdf.add_font("V", "", str(fonts / "Vazirmatn-Regular.ttf"))
        pdf.add_font("V", "B", str(fonts / "Vazirmatn-Bold.ttf"))
        pdf.set_text_shaping(True)
        pdf.set_creation_date(_dt.datetime.fromtimestamp(inv.issued_ts, tz=_dt.timezone.utc))
        pdf.set_creator("Smart Business Local")
        pdf.set_title(clean(inv.number, 40) or "invoice")
        self.w = pdf.w - 24
        self.small = 8 if paper == "A5" else 9
        self.body = 9.5 if paper == "A5" else 10.5
        self.row_h = 6.4 if paper == "A5" else 7.0
        self.columns = [(label(key, self.lang), self.w * ratio) for key, ratio in zip(_COLUMN_KEYS, _COLUMN_RATIOS, strict=True)]
        self.widths = [width for _label, width in self.columns]

    # ------------------------------------------------------------------ helpers

    def _l(self, key: str) -> str:
        return label(key, self.lang)

    def _money_line(self, value: int) -> str:
        return f"{money(value, self.digits)} {self._l('rial')}"

    def _room_left(self, needed: float) -> bool:
        return self.pdf.get_y() + needed <= self.pdf.h - _BOTTOM_GUARD

    def _need_page(self, needed: float, repeat_header: bool = False) -> None:
        if self._room_left(needed):
            return
        self.pdf.add_page()
        if repeat_header:
            self.table_header()

    # ------------------------------------------------------------------ primitives

    def text(self, content, size=None, bold=False, align="R", color=_INK, height=None):
        pdf = self.pdf
        pdf.set_font("V", "B" if bold else "", size or self.body)
        pdf.set_text_color(*color)
        pdf.cell(self.w, height or 5.8, clean(content), align=align, new_x="LMARGIN", new_y="NEXT")

    def rule(self, color=None, width=0.5):
        pdf = self.pdf
        pdf.set_draw_color(*(color or self.brand))
        pdf.set_line_width(width)
        pdf.line(12, pdf.get_y(), 12 + self.w, pdf.get_y())

    def band(self, height, color):
        pdf = self.pdf
        pdf.set_fill_color(*color)
        pdf.rect(12, pdf.get_y(), self.w, height, style="F")

    # -------------------------------------------------------------------- header

    def letterhead(self):
        pdf, seller = self.pdf, self.inv.seller
        pdf.add_page()
        top = pdf.get_y()
        self.band(20, self.brand)
        logo = _load_logo(seller.get("logo_path", ""))
        if logo:
            try:
                pdf.image(BytesIO(logo), x=15, y=top + 2.5, h=15)
            except Exception:  # noqa: BLE001 — لوگوی خراب فاکتور را نمی‌اندازد
                pass
        pdf.set_xy(12, top + 4.5)
        pdf.set_font("V", "B", 15 if self.paper == "A4" else 13)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(self.w - 6, 8, clean(seller.get("name", "") or self._l("sale")), align="R", new_x="LMARGIN", new_y="NEXT")
        sub = " · ".join(clean(x, 60) for x in (seller.get("legal_name", ""), seller.get("phone", "")) if x)
        if sub:
            pdf.set_xy(12, top + 13)
            pdf.set_font("V", "", self.small)
            pdf.cell(self.w - 6, 5, sub, align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.set_y(top + 23)
        details = [(self._l("seller_address"), seller.get("address", "")),
                   (self._l("national_id"), _num(seller.get("national_id", ""), self.digits) if seller.get("national_id") else "")]
        for name, value in details:
            if value:
                self.text(f"{name}: {clean(value, 120)}", self.small, color=_MUTED, height=5.4)
        pdf.ln(1)

    # ---------------------------------------------------------------- meta cards

    def meta_block(self, order_label: str, ref_number: str):
        pdf, inv, _seller = self.pdf, self.inv, self.inv.seller
        title = self._l("credit" if inv.is_credit else "sale")
        card_w = self.w * 0.38
        info_w = self.w - card_w - 5
        y0 = pdf.get_y()
        card_x = 12 + info_w + 5
        pdf.set_fill_color(*_ZEBRA)
        pdf.set_draw_color(*_LINE)
        pdf.rect(card_x, y0, card_w, 25, style="FD")
        pdf.set_xy(card_x + 4, y0 + 3)
        pdf.set_font("V", "B", 12)
        pdf.set_text_color(*self.brand)
        pdf.cell(card_w - 8, 6, clean(title), align="R")
        pdf.set_xy(card_x + 4, y0 + 11)
        pdf.set_font("V", "", self.small)
        pdf.set_text_color(*_INK)
        pdf.cell(card_w - 8, 5, f"{self._l('number')}: {clean(inv.number, 32)}", align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.set_xy(card_x + 4, y0 + 17)
        pdf.cell(card_w - 8, 5, f"{self._l('date')}: " + jalali.format_ts(inv.issued_ts, with_time=True, digits=self.digits),
                 align="R", new_x="LMARGIN", new_y="NEXT")

        buyer = inv.buyer or {}
        name = ANON_NAME if buyer.get("anonymized") else (buyer.get("name") or "")
        rows = []
        if order_label:
            rows.append((self._l("order"), clean(order_label, 60)))
        rows.append((self._l("buyer"), clean(name, 80) or "—"))
        if buyer.get("phone"):
            rows.append((self._l("phone"), _num(clean(buyer["phone"], 30), self.digits)))
        if buyer.get("address"):
            rows.append((self._l("address"), clean(buyer["address"], 120)))
        shipping_note = clean(buyer.get("shipping_method", ""), 40)
        if shipping_note:
            rows.append((self._l("shipping_note"), shipping_note))
        method = _PAY_LABEL.get(inv.pay_method)
        if method:
            rows.append((self._l("pay_method"), method[1] if self.lang == "en" else method[0]))
        if buyer.get("trace"):
            rows.append((self._l("trace"), _num(clean(buyer["trace"], 40), self.digits)))
        if inv.is_credit and ref_number:
            rows.append((self._l("ref_invoice"), clean(ref_number, 40)))

        yy = y0 + 2
        for field_name, value in rows:
            if not value:
                continue
            pdf.set_xy(12, yy)
            pdf.set_font("V", "", self.small)
            pdf.set_text_color(*_MUTED)
            pdf.cell(info_w * 0.34, 5.4, clean(field_name, 32), align="R", new_x="RIGHT", new_y="TOP")
            pdf.set_font("V", "B" if field_name == self._l("buyer") else "", self.small)
            pdf.set_text_color(*_INK)
            pdf.cell(info_w * 0.66, 5.4, value, align="R", new_x="LMARGIN", new_y="NEXT")
            yy += 5.6
        pdf.set_y(max(y0 + 25, yy) + 3)
        self.rule(_LINE)
        pdf.ln(3)

    # ---------------------------------------------------------------- items table

    def table_header(self):
        pdf = self.pdf
        pdf.set_font("V", "B", self.small)
        pdf.set_fill_color(*self.brand)
        pdf.set_text_color(255, 255, 255)
        x = 12 + self.w
        for index, (caption, width) in enumerate(self.columns):
            x -= width
            pdf.set_xy(x, pdf.get_y())
            pdf.cell(width, self.row_h, clean(caption, 40), align="R" if index == 1 else "C", fill=True)
        pdf.set_x(12)
        pdf.set_y(pdf.get_y() + self.row_h)

    def item_row(self, index: int, item: dict):
        pdf = self.pdf
        description = clean(item.get("name", ""), 200)
        lines = wrap_lines(pdf, description, self.widths[1] - 4)
        height = self.row_h * len(lines)
        self._need_page(height + self.row_h, repeat_header=True)
        y_row = pdf.get_y()
        if index % 2 == 0:  # ردیف‌های یک‌درمیان؛ چشم خط را گم نکند
            pdf.set_fill_color(*_ZEBRA)
            pdf.rect(12, y_row, self.w, height, style="F")
        pdf.set_draw_color(*_LINE)
        pdf.set_font("V", "", self.small)
        pdf.set_text_color(*_INK)
        values = [_num(index, self.digits), "", _num(item.get("qty", 0), self.digits),
                  money(item.get("unit_irr", 0), self.digits), money(item.get("total_irr", 0), self.digits)]
        x = 12 + self.w
        for column, (_caption, width) in enumerate(self.columns):
            x -= width
            pdf.set_xy(x, y_row)
            pdf.cell(width, height, values[column], align="R" if column == 1 else "C", border="B")
        for line_index, line_text in enumerate(lines):
            pdf.set_xy(12 + self.w - self.widths[0] - self.widths[1] + 2, y_row + self.row_h * line_index)
            pdf.set_font("V", "", self.small)
            pdf.set_text_color(*_INK)
            pdf.cell(self.widths[1] - 4, self.row_h, line_text, align="R")
        pdf.set_x(12)
        pdf.set_y(y_row + height)

    # ------------------------------------------------------------------- totals

    def total_rows(self) -> list:
        """سطرهایِ جمع. ترتیب و معنا با ریاضیِ ``compute_totals`` یکی است:
        جمع اقلام − تخفیف + ارسال = جمع کل؛ مالیات *زیرِ* جمع کل و فقط اطلاع‌رسانی."""
        inv, seller = self.inv, self.inv.seller
        rows = [(self._l("subtotal"), inv.subtotal_irr, False)]
        if inv.discount_irr:
            rows.append((self._l("discount"), -abs(int(inv.discount_irr)), False))
        if inv.shipping_irr:
            rows.append((self._l("shipping"), inv.shipping_irr, False))
        rows.append(((self._l("refund") if inv.is_credit else self._l("final")), inv.total_irr, True))
        if inv.tax_irr:
            rate = (seller.get("vat_rate_bp", 0) or 0) / 100
            vat = f"{self._l('vat')} {_num(f'{rate:g}', self.digits)}٪: {money(inv.tax_irr, self.digits)}"
            rows.append((vat, None, False))  # value=None یعنی «خطِ اطلاع‌رسانی»، نه جمعِ جدید
        return rows

    def totals(self):
        pdf = self.pdf
        rows = self.total_rows()
        box_h = 6.6 * (len(rows) - 1) + 8.5
        self._need_page(box_h + 6)
        pdf.ln(1)
        top = pdf.get_y()
        pdf.set_draw_color(*_LINE)
        pdf.rect(12 + self.w - 92, top, 92, box_h, style="D")
        y = top + 1.4
        for index, (caption, value, final) in enumerate(rows):
            pdf.set_xy(12 + self.w - 90, y)
            if final:
                pdf.set_fill_color(*self.brand)
                pdf.set_text_color(255, 255, 255)
                pdf.cell(88, 8.0, "", fill=True)
                pdf.set_xy(12 + self.w - 90, y + 1.4)
                pdf.set_font("V", "B", self.body)
                pdf.set_text_color(255, 255, 255)
                pdf.cell(46, 5.4, clean(caption, 48), align="R", new_x="RIGHT", new_y="TOP")
                pdf.cell(40, 5.4, self._money_line(value), align="C", new_x="LMARGIN", new_y="NEXT")
                y += 8.5
                continue
            pdf.set_font("V", "", self.small + 0.5)
            pdf.set_text_color(*(_MUTED if value is None else _INK))
            if value is None:  # خطِ اطلاع‌رسانی (مالیات): متن کامل، یک‌جا
                pdf.cell(86, 5.4, clean(caption, 120), align="R")
            else:
                pdf.cell(46, 5.4, clean(caption, 48), align="R", new_x="RIGHT", new_y="TOP")
                pdf.cell(40, 5.4, self._money_line(value), align="C", new_x="LMARGIN", new_y="NEXT")
            y += 6.6
        pdf.set_y(top + box_h + 4)

    # ------------------------------------------------------------------- footer

    def closing(self):
        pdf, seller = self.pdf, self.inv.seller
        self._need_page(24)
        footer_top = pdf.get_y()
        qr = _qr_png(_verify_payload(self.inv))
        if qr:
            try:
                pdf.image(BytesIO(qr), x=12, y=footer_top, h=19)
                pdf.set_xy(33, footer_top + 3)
                pdf.set_font("V", "", 7.5)
                pdf.set_text_color(*_MUTED)
                pdf.cell(60, 4, self._l("verify"), new_x="LMARGIN", new_y="NEXT")
                pdf.set_xy(33, footer_top + 8)
                pdf.cell(60, 4, clean(self.inv.number, 40), new_x="LMARGIN", new_y="NEXT")
                pdf.set_y(footer_top + 21)
            except Exception:  # noqa: BLE001
                pdf.set_y(footer_top)
        if seller.get("footer"):
            self.text(seller["footer"], self.small, color=_MUTED, height=5.4)
        self.text(self._l("disclaimer"), 7.5, color=_MUTED, height=5)

    # --------------------------------------------------------------------- build

    def build(self, ref_number: str, order_label: str) -> bytes:
        self.letterhead()
        self.meta_block(order_label, ref_number)
        self.table_header()
        for index, item in enumerate(self.inv.lines, 1):
            self.item_row(index, item)
        self.pdf.ln(3)
        self.totals()
        self.closing()
        self.pdf.stamp_ctx = {"name": clean(seller_name(self.inv.seller), 40), "digits": self.digits, "lang": self.lang}
        return bytes(self.pdf.output())


def render(inv: Invoice, ref_number: str = "", order_label: str = "") -> bytes:
    """فاکتور ← بایت PDF (A4 یا A5 طبق snapshot فروشنده)."""
    try:
        return _InvoicePDF(inv).build(ref_number, order_label)
    except InvoicePdfError:
        raise
    except Exception as exc:  # noqa: BLE001 — کتابخانه/فونت/ورودی غیرمنتظره
        raise InvoicePdfError(f"ساختِ PDF ناموفق بود: {type(exc).__name__}") from exc


# ------------------------------------------------------------------ یارِ عمومی ----
# افزودنِ صرفِ یکِ نامِ عمومی (بدونِ هیچ تغییری در چیدمان/رفتارِ فاکتور): ``report_pdf``
# همان پوشه‌ی فونت را می‌خواهد و کپی‌کردنِ مسیریابیِ PyInstaller دو نسخه می‌ساخت.


def fonts_dir() -> Path:
    """پوشه‌ی فونتِ Vazirmatn (همان ``_fonts_dir``) — برایِ گزارش‌های PDFِ ``app.core.report_pdf``."""
    return _fonts_dir()
