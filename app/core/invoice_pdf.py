"""
PDFِ فارسیِ (راست‌به‌چپ) فاکتور (N19) — ``fpdf2`` + ``uharfbuzz`` (شکل‌دهیِ حروفِ فارسی) + فونتِ Vazirmatn (مجوزِ OFL).

- بدونِ باینریِ خارجی؛ ``fpdf2``/``uharfbuzz``/``fonttools`` همه wheelِ آماده دارن (PoC: PDF با متنِ فارسی/ارقام/ترکیبِ لاتین درست رندر شد).
  داخلِ exeِ PyInstaller کار کردنش در ویندوزِ واقعی *تأییدنشده* است ⇒ هر خطا ``InvoicePdfError`` می‌شه و فاکتورِ متنی fallback است.
- خروجی **قطعی** است (تاریخِ ساخت = تاریخِ صدور) ⇒ از snapshot هر زمان دوباره ساخته می‌شه (نیازی به پشتیبان‌گیریِ PDF نیست).
- متنِ خریدار/فروشنده نامطمئن است: کاراکترهای کنترلی/bidi-override حذف و نویسه‌های خارج از فونت (مثلاً ایموجی) دور ریخته می‌شن.
"""

from __future__ import annotations

import datetime as _dt
import re
import sys
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.core import jalali
from app.core.invoices import ANON_NAME, Invoice

LICENSE_NOTE = "Vazirmatn font — SIL Open Font License 1.1"
MAX_LOGO_BYTES = 300 * 1024
_PAY_LABEL = {"card_to_card": "کارت‌به‌کارت", "bale_pay": "بله‌پی", "zarinpal": "زرین‌پال"}
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u202a-\u202e\u2066-\u2069\u200e\u200f]")


class InvoicePdfError(Exception):
    """ساختِ PDF ناموفق بود (کتابخانه/فونت/ورودی)."""


def _pyinstaller_hint() -> None:  # pragma: no cover — هرگز صدا زده نمی‌شه؛ فقط برای تحلیلِ ایستای PyInstaller (ایمپورت‌های تنبل)
    import fontTools.ttLib  # noqa: F401
    import fpdf  # noqa: F401
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
    """متنِ نامطمئن ← فقط نویسه‌هایی که فونت دارد (ZWNJ حفظ می‌شود)؛ بدونِ ایموجی/کنترل/override."""
    glyphs = _glyphs()
    out = "".join(ch for ch in _CTRL.sub(" ", str(text or "")) if ord(ch) in glyphs or ch in "\u200c\n")
    return out.strip()[:limit]


def money(n: int, digits: str = "fa") -> str:
    s = f"{int(n):,}"
    return jalali.fa_digits(s.replace(",", "٬")) if digits == "fa" else s


def _num(value, digits: str) -> str:
    return jalali.fa_digits(value) if digits == "fa" else str(value)


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


def render(inv: Invoice, ref_number: str = "", order_label: str = "") -> bytes:
    """فاکتور ← بایتِ PDF (A4 یا A5 طبقِ snapshotِ فروشنده)."""
    try:
        return _render(inv, ref_number, order_label)
    except InvoicePdfError:
        raise
    except Exception as exc:  # noqa: BLE001 — کتابخانه/فونت/ورودیِ غیرمنتظره
        raise InvoicePdfError(f"ساختِ PDF ناموفق بود: {type(exc).__name__}") from exc


def _render(inv: Invoice, ref_number: str, order_label: str) -> bytes:
    from io import BytesIO

    from fpdf import FPDF

    seller, digits = inv.seller, ("en" if inv.seller.get("digits") == "en" else "fa")
    paper = seller.get("paper") if seller.get("paper") in ("A4", "A5") else "A4"
    with warnings.catch_warnings():  # fpdf2≥2.8.5 برای A5 هشدارِ «ابعاد اصلاح شد» می‌دهد؛ برای ما همان اصلاح مطلوب است
        warnings.simplefilter("ignore", UserWarning)
        pdf = FPDF(format=paper, unit="mm")
    pdf.set_margins(12, 12, 12)
    pdf.set_auto_page_break(True, 14)
    fonts = _fonts_dir()
    pdf.add_font("V", "", str(fonts / "Vazirmatn-Regular.ttf"))
    pdf.add_font("V", "B", str(fonts / "Vazirmatn-Bold.ttf"))
    pdf.set_text_shaping(True)
    pdf.set_creation_date(_dt.datetime.fromtimestamp(inv.issued_ts, tz=_dt.timezone.utc))
    pdf.set_creator("Smart Business Local")
    pdf.set_title(clean(f"{inv.number}", 40) or "invoice")
    pdf.add_page()
    r, g, b = _hex_rgb(seller.get("color", ""))
    w = pdf.w - 24
    small = 8 if paper == "A5" else 9

    def line(text, size=10, bold=False, align="R", color=(30, 30, 30), h=6):
        pdf.set_font("V", "B" if bold else "", size)
        pdf.set_text_color(*color)
        pdf.cell(w, h, clean(text), align=align, new_x="LMARGIN", new_y="NEXT")

    logo = _load_logo(seller.get("logo_path", ""))
    top = pdf.get_y()
    if logo:
        try:
            pdf.image(BytesIO(logo), x=12, y=top, h=16)
        except Exception:  # noqa: BLE001 — لوگوی خراب فاکتور را نمی‌اندازد
            pass
    line(seller.get("name", ""), 15, True, color=(r, g, b), h=8)
    for key in ("legal_name", "address", "phone"):
        if seller.get(key):
            line(seller[key], small)
    if seller.get("national_id"):
        line(("شناسه‌ی ملی/اقتصادی: " + _num(seller["national_id"], digits)), small)
    pdf.ln(2)
    pdf.set_draw_color(r, g, b)
    pdf.set_line_width(0.6)
    pdf.line(12, pdf.get_y(), 12 + w, pdf.get_y())
    pdf.ln(3)

    title = "فاکتور برگشتی" if inv.is_credit else "فاکتور فروش"
    line(title, 13, True, color=(r, g, b), h=8)
    line(f"شماره: {inv.number}", 10, True)
    line("تاریخ: " + jalali.format_ts(inv.issued_ts, with_time=True, digits=digits), small)
    if inv.is_credit and ref_number:
        line(f"مربوط به فاکتورِ شماره: {ref_number}", small)
    if order_label:
        line(order_label, small)
    method = _PAY_LABEL.get(inv.pay_method, "")
    if method:
        line("روشِ پرداخت: " + method, small)
    pdf.ln(2)
    buyer = inv.buyer
    name = ANON_NAME if buyer.get("anonymized") else (buyer.get("name") or "—")
    line("خریدار: " + name, 10, True)
    for label, key in (("تلفن", "phone"), ("نشانی", "address")):
        if buyer.get(key):
            value = _num(buyer[key], digits) if key == "phone" else buyer[key]
            line(f"{label}: {value}", small)
    pdf.ln(3)

    # جدولِ اقلام — ستون‌ها چپ→راست: مبلغ | قیمتِ واحد | تعداد | شرح | ردیف
    cols = [("مبلغ (ریال)", 0.22), ("قیمتِ واحد", 0.2), ("تعداد", 0.1), ("شرح کالا", 0.42), ("ردیف", 0.06)]
    widths = [w * c[1] for c in cols]

    def row(cells, bold=False, fill=False):
        pdf.set_font("V", "B" if bold else "", small)
        pdf.set_text_color(*((255, 255, 255) if fill else (30, 30, 30)))
        if fill:
            pdf.set_fill_color(r, g, b)
        else:
            pdf.set_draw_color(210, 210, 210)
        for i, (text, width) in enumerate(zip(cells, widths)):
            pdf.cell(width, 7, text, border=0 if fill else "B", align="R" if i == 3 else "C", fill=fill,
                     new_x="RIGHT" if i < len(cells) - 1 else "LMARGIN", new_y="TOP" if i < len(cells) - 1 else "NEXT")

    row([c[0] for c in cols], bold=True, fill=True)
    for idx, item in enumerate(inv.lines, 1):
        name_text = clean(item.get("name", ""), 120)
        pdf.set_font("V", "", small)
        while name_text and pdf.get_string_width(name_text) > widths[3] - 2:
            name_text = name_text[:-1]
        row([money(item.get("total_irr", 0), digits), money(item.get("unit_irr", 0), digits), _num(item.get("qty", 0), digits), name_text,
             _num(idx, digits)])
    pdf.ln(3)

    def total(label, amount, bold=False):
        pdf.set_font("V", "B" if bold else "", 10 if bold else small + 1)
        pdf.set_text_color(30, 30, 30)
        half = w * 0.5
        pdf.set_x(12)
        pdf.cell(half, 7, money(amount, digits) + " ریال", align="L", new_x="RIGHT", new_y="TOP")
        pdf.cell(half, 7, label, align="R", new_x="LMARGIN", new_y="NEXT")

    total("جمعِ اقلام", inv.subtotal_irr)
    if inv.discount_irr:
        total("تخفیف", inv.discount_irr)
    if inv.shipping_irr:
        total("ارسال / سایر", inv.shipping_irr)
    if inv.tax_irr:
        rate = seller.get("vat_rate_bp", 0) / 100
        pct = _num(f"{rate:g}", digits)
        total(f"شاملِ مالیات بر ارزش افزوده ({pct}٪)", inv.tax_irr)
    total("مبلغِ نهایی" if not inv.is_credit else "مبلغِ برگشتی", inv.total_irr, bold=True)
    pdf.ln(4)
    if seller.get("footer"):
        line(seller["footer"], small)
    pdf.set_text_color(130, 130, 130)
    pdf.set_font("V", "", 7)
    pdf.cell(w, 5, "ابزارِ کمکی است و جایگزینِ سامانه‌ی مودیان/حسابدارِ رسمی نیست.", align="R", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
