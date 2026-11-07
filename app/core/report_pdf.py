"""PDFِ حرفه‌ایِ گزارش‌های پنجِ بخش — راست‌به‌چپ، با همان شکل‌دهیِ حروفِ ``invoice_pdf``.

چرا این فایل جدا از ``invoice_pdf`` است؟ فاکتور چیدمانِ خاصِ خودش را دارد (کارتِ شماره/تاریخ،
ردیفِ اقلام، کادر جمع‌ها، QR راستی‌آزمایی). گزارشِ مدیریتی جدولِ چندستونه با سرِ گزارش است؛ ولی
**هیچ چیزی از سختیِ فارسی دوباره نوشته نمی‌شود**:

* ``invoice_pdf.clean`` → فقط نویسه‌هایی که فونت Vazirmatn دارد (ایموجی/کنترل/overrideِ جهت می‌رود؛
  بی‌این، uharfbuzz روی متنِ آماده‌شده می‌شکند یا سطر را آینه می‌کند).
* ``invoice_pdf.wrap_lines`` → شکست خط با عرضِ واقعیِ همان فونت (نامِ بلندِ محصول نصفه نمی‌شود).
* ``invoice_pdf.money`` / ``invoice_pdf.fonts_dir`` → قالبِ پولی و همان فونتِ OFL (فونت دوم ساخته نمی‌شود).
* ``set_text_shaping(True)`` → اتصالِ حروف و نیم‌فاصله، دقیقاً مثلِ فاکتور.

چیدمان: A4 افقی (جدولهایِ ۱۰ تا ۱۸ ستونی در عمودی جا نمی‌شوند)، نوارِ رنگیِ سربرگ، بلوکِ
«عنوان/فروشگاه/تاریخ/تعداد»، جدولِ یک‌درمیان با **تکرارِ سطرِ ستون‌ها در هر صفحه**، شماره‌ی صفحه
و پانوشتِ «ساخته‌شده با برنامه». سقفِ سطورِ PDF ``PDF_MAX_ROWS`` است (اکسل سقفِ ۲۰٬۰۰۰ را دارد):
هزاران صفحه، گزارش را هم کند و هم بی‌استفاده می‌کند.
"""

from __future__ import annotations

import datetime as _dt
import warnings
from pathlib import Path
from typing import Optional

from app.core import invoice_pdf
from app.core import jalali
from app.core import report_xlsx as rx
from app.core.report_xlsx import ReportData

PDF_MAX_ROWS = 5000  # سقفِ سطورِ PDF (خوانایی + زمانِ شکل‌دهیِ حروف)

_INK = (28, 28, 30)
_MUTED = (120, 120, 120)
_LINE = (214, 214, 214)
_ZEBRA = (247, 246, 243)
_PAPER_MM = {"A4": (297.0, 210.0), "A5": (210.0, 148.0)}


class ReportPdfError(rx.ReportError):
    """ساختِ PDFِ گزارش ناموفق بود (کتابخانه/فونت/دیسک) — پیامِ فارسیِ قابل‌نمایش، بدونِ traceback."""


def _hex_rgb(color: str) -> tuple:
    try:
        return tuple(int(str(color)[i:i + 2], 16) for i in (1, 3, 5))
    except (ValueError, TypeError, IndexError):
        return (31, 111, 235)


def _num(value, digits: str) -> str:
    return jalali.fa_digits(str(value)) if digits == "fa" else str(value)


def _cell_text(column: rx.Column, value, digits: str) -> str:
    """یک سلول ← متنِ آماده‌ی چاپ: پول جداکننده‌دار، شمارۀ عددی، متنِ تمیزِ محدودشده."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if column.kind == rx.MONEY:
            return invoice_pdf.money(int(value), digits) + " ریال"
        return _num(int(value) if float(value).is_integer() else value, digits)
    return invoice_pdf.clean(value, 600)


class _ReportPDF:
    """سازنده‌ی صفحه‌های گزارش؛ هندسه و رنگ یک‌جا، تا خروجی حدس‌زدنی و قطعی بماند."""

    def __init__(self, data: ReportData, *, paper: str = "A4", digits: str = "fa", brand: str = "#1F6FEB"):
        from fpdf import FPDF

        class _Pdf(FPDF):
            stamp_ctx: dict = None

            def footer(self) -> None:  # fpdf2 اینِ متد را برای هر صفحه صدا می‌زند
                ctx = self.stamp_ctx
                if not ctx:
                    return
                self.set_y(-11)
                self.set_font("V", "", 7.5)
                self.set_text_color(*_MUTED)
                half = (self.w - 24) / 2
                self.cell(half, 5, ctx.get("shop", ""), align="L", new_x="RIGHT", new_y="TOP")
                self.cell(half, 5, f"صفحه {_num(self.page_no(), ctx['digits'])} از {_num('{nb}', ctx['digits'])}",
                          align="R", new_x="LMARGIN", new_y="NEXT")

        self.data = data
        self.digits = digits if digits in ("fa", "en") else "fa"
        self.brand = _hex_rgb(brand)
        self.paper = paper if paper in _PAPER_MM else "A4"
        with warnings.catch_warnings():  # fpdf2 برای A5 هشدار «ابعاد اصلاح شد» می‌دهد؛ همان اصلاحِ ماست
            warnings.simplefilter("ignore", UserWarning)
            self.pdf = _Pdf(orientation="L", format=self.paper, unit="mm")
        pdf = self.pdf
        pdf.alias_nb_pages()
        pdf.set_margins(12, 12, 12)
        pdf.set_auto_page_break(True, 16)
        fonts = invoice_pdf.fonts_dir()
        pdf.add_font("V", "", str(fonts / "Vazirmatn-Regular.ttf"))
        pdf.add_font("V", "B", str(fonts / "Vazirmatn-Bold.ttf"))
        pdf.set_text_shaping(True)
        pdf.set_creation_date(_dt.datetime.fromtimestamp(data.generated_ts, tz=_dt.timezone.utc))
        pdf.set_creator("Smart Business Local")
        pdf.set_title(invoice_pdf.clean(data.title, 60))
        pdf.set_subject(invoice_pdf.clean(f"{data.shop_name} — {data.kind}", 80))
        self.w = pdf.w - 24
        self.small = 8.0
        self.line_h = 4.6
        self.widths = self._column_widths()

    # ------------------------------------------------------------------ هندسه ----

    def _column_widths(self) -> list:
        """پهنای ستون‌ها از پهنایِ پیشنهادیِ اکسل می‌آید (نسبتی)، با کفِ ۱۲mm تا هیچ ستونی ناپدید نشود.

        بعد از کف، همه دوباره به عرضِ کاغذ مقیاس می‌شوند: جدول هرگز از صفحه بیرون نمی‌زند و
        به‌جایِ بریده‌شدن، ستون‌هایِ پهن‌تر کمی تنگ‌تر می‌شوند."""
        wanted = [max(float(c.width), 6.0) for c in self.data.columns]
        total = sum(wanted) or 1.0
        widths = [self.w * (value / total) for value in wanted]
        minimum = 12.0
        if min(widths) < minimum:
            widths = [max(value, minimum) for value in widths]
            scale = self.w / (sum(widths) or 1.0)
            widths = [value * scale for value in widths]
        return widths

    def _x_of(self, index: int) -> float:
        """xِ سلولِ ``index`` در چیدمانِ راست‌به‌چپ: ستونِ اول به چسبیده به لبه‌ی راست."""
        return 12.0 + self.w - sum(self.widths[: index + 1])

    # ------------------------------------------------------------------ primitives ----

    def _text(self, content: str, size: float = 9.5, *, bold: bool = False, color: tuple = _INK, height: float = 5.6) -> None:
        pdf = self.pdf
        pdf.set_font("V", "B" if bold else "", size)
        pdf.set_text_color(*color)
        pdf.cell(self.w, height, invoice_pdf.clean(content), align="R", new_x="LMARGIN", new_y="NEXT")

    def _rule(self, color: tuple = None) -> None:
        pdf = self.pdf
        pdf.set_draw_color(*(color or _LINE))
        pdf.set_line_width(0.4)
        pdf.line(12, pdf.get_y(), 12 + self.w, pdf.get_y())

    # ------------------------------------------------------------------ سرجداول ----

    def letterhead(self) -> None:
        pdf, data = self.pdf, self.data
        pdf.add_page()
        top = pdf.get_y()
        pdf.set_fill_color(*self.brand)
        pdf.rect(12, top, self.w, 16, style="F")
        pdf.set_xy(14, top + 3.5)
        pdf.set_font("V", "B", 14)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(self.w - 4, 9, invoice_pdf.clean(f"{data.title} — {data.shop_name}"), align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.set_y(top + 19)
        self._text(f"تاریخِ ساخت: {data.jalali_stamp()} ({data.iso_stamp()} میلادی)", self.small, color=_MUTED, height=5.0)
        self._text(f"تعدادِ سطور: {_num(data.count, self.digits)}"
                   + (f" — ⚠️ بیش از {_num(rx.MAX_ROWS, self.digits)} سطر بود؛ تنها {_num(rx.MAX_ROWS, self.digits)} سطرِ نخست صادر شده."
                      if data.truncated else ""), self.small, color=_MUTED, height=5.0)
        if data.summary:
            pdf.set_y(pdf.get_y() + 1)
            for line in data.summary_lines():
                self._text(line, self.small, color=_INK, height=4.6)
        pdf.ln(1)
        self._rule(self.brand)
        pdf.ln(3)

    def table_header(self) -> None:
        pdf = self.pdf
        pdf.set_font("V", "B", self.small)
        pdf.set_fill_color(*self.brand)
        pdf.set_text_color(255, 255, 255)
        lines = [invoice_pdf.wrap_lines(pdf, invoice_pdf.clean(c.title, 60), self.widths[i] - 2, max_lines=2)
                 for i, c in enumerate(self.data.columns)]
        height = max(len(x) for x in lines) * self.line_h
        y0 = pdf.get_y()
        for index, texts in enumerate(lines):
            x = self._x_of(index)
            pdf.set_xy(x, y0)
            pdf.cell(self.widths[index], height, "", fill=True)
            for row, text in enumerate(texts):
                pdf.set_xy(x + 1, y0 + row * self.line_h)
                pdf.cell(self.widths[index] - 2, self.line_h, text, align="R")
        pdf.set_x(12)
        pdf.set_y(y0 + height + 0.6)

    def table(self) -> None:
        pdf, columns = self.pdf, self.data.columns
        rows = self.data.pdf_rows(PDF_MAX_ROWS)
        self.table_header()
        for position, row in enumerate(rows):
            cells = [_cell_text(columns[i], row[i] if i < len(row) else "", self.digits) for i in range(len(columns))]
            wrapped = [invoice_pdf.wrap_lines(pdf, cell, self.widths[i] - 2, max_lines=2 if i else 3)
                       for i, cell in enumerate(cells)]
            height = max(len(x) for x in wrapped) * self.line_h
            if pdf.get_y() + height > pdf.h - 20:
                pdf.add_page()
                self.table_header()
            y0 = pdf.get_y()
            if position % 2 == 0:
                pdf.set_fill_color(*_ZEBRA)
                pdf.rect(12, y0, self.w, height, style="F")
            pdf.set_draw_color(*_LINE)
            pdf.set_line_width(0.2)
            pdf.set_font("V", "", self.small)
            pdf.set_text_color(*_INK)
            for index, texts in enumerate(wrapped):
                x = self._x_of(index)
                pdf.set_xy(x, y0)
                pdf.cell(self.widths[index], height, "", border="B")
                for row, text in enumerate(texts):
                    pdf.set_xy(x + 1, y0 + row * self.line_h)
                    pdf.cell(self.widths[index] - 2, self.line_h, text, align="R")
            pdf.set_x(12)
            pdf.set_y(y0 + height)
        if len(self.data.rows) > PDF_MAX_ROWS:
            self._text(f"⚠️ تنها {_num(PDF_MAX_ROWS, self.digits)} سطرِ نخست در PDF چاپ شد (فایلِ اکسل همه را دارد).",
                       self.small, color=_MUTED)

    def closing(self) -> None:
        pdf = self.pdf
        if pdf.get_y() > pdf.h - 34:
            pdf.add_page()
        pdf.ln(3)
        self._rule(_LINE)
        pdf.ln(2)
        self._text(invoice_pdf.clean(self.data.footer, 300), 7.5, color=_MUTED, height=5)

    def build(self) -> bytes:
        self.letterhead()
        self.table()
        self.closing()
        self.pdf.stamp_ctx = {"shop": invoice_pdf.clean(self.data.shop_name, 40), "digits": self.digits}
        return bytes(self.pdf.output())


def pdf_bytes(data: ReportData, *, paper: str = "A4", digits: str = "fa", brand: str = "#1F6FEB") -> bytes:
    """گزارش ← بایت PDF (A4/A5 افقی). هر خطا به ``ReportPdfErrorِ`` فارسی تبدیل می‌شود."""
    if data is None or not data.rows:
        raise ReportPdfError(rx.EMPTY_ERROR)
    try:
        return _ReportPDF(data, paper=paper, digits=digits, brand=brand).build()
    except ReportPdfError:
        raise
    except Exception as exc:  # noqa: BLE001 — fpdf/فونت/ورودیِ غیرمنتظره؛ هرگز traceback به UI نرود
        raise ReportPdfError(f"ساختِ PDF ناموفق بود: {type(exc).__name__}") from exc


def write_pdf(data: ReportData, folder=None, *, paper: str = "A4", digits: str = "fa",
              brand: str = "#1F6FEB", now: Optional[float] = None) -> Path:
    """گزارش ← فایلِ ``<داده>/reports/<kind>-<تاریخ>.pdf`` (مسیرِ نوشته‌شده را برمی‌گرداند)."""
    payload = pdf_bytes(data, paper=paper, digits=digits, brand=brand)
    target = Path(folder) if folder is not None else rx.reports_dir()
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{rx.file_stem(data.kind, now if now is not None else data.generated_ts)}.pdf"
    path.write_bytes(payload)
    return path


def export_kind(data: ReportData, kind: str, folder=None, **kw) -> Path:
    """یکِ درِ ورودی برایِ صفحه‌ها: ``kind`` یکی از ``"xlsx"`` / ``"pdf"``."""
    if kind == "pdf":
        return write_pdf(data, folder, **kw)
    return rx.write_xlsx(data, folder)
