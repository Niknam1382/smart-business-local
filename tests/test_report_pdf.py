"""PDFِ گزارشِ پنجِ بخش (``app/core/report_pdf.py``).

سنجش با همانِ روشِ ``tests/test_invoice_service.py``: بایتِ خروجی ``%PDF`` است، با ``pypdf`` باز
می‌شود و متنِ استخراج‌شده بررسی می‌شود (pypdf ترتیبِ راست‌به‌چپ را برعکس/ناقص درمی‌آورد، پس واژه‌ها
سنجیده می‌شوند نه عبارتِ کامل). مهم‌ترینِ خواسته: **متنِ فارسیِ آماده‌شده (ایموجی/کنترل/override)
شکل‌دهنده‌ی حروف را نمی‌شکند**.
"""

from types import SimpleNamespace as NS

import pytest

from app.core import invoice_pdf
from app.core import report_pdf as rp
from app.core import report_xlsx as rx

pypdf = pytest.importorskip("pypdf")

SHOP = "فروشگاه نمونه"


def text_of(path) -> str:
    return "".join(page.extract_text() or "" for page in pypdf.PdfReader(str(path)).pages)


def customers():
    return [NS(platform="telegram", user_id="1", display_name="علی رضایی", username="ali_r", phone="+989120000001",
               language_code="fa", msg_count=12, orders_count=3, total_spent_irr=1_250_000, last_order_ts=1_780_000_000,
               last_seen_ts=1_780_100_000, first_seen_ts=1_770_000_000, tags=["ویژه"], notes="یادداشت",
               blocked=False, opted_out=False, unreachable=False)]


def orders():
    return [NS(id=7, platform="telegram", chat_id="1", status="confirmed", payment_method="card_to_card",
               total_irr=200_000, subtotal_irr=220_000, discount_irr=20_000, shipping_irr=15_000,
               items=[NS(product_name="شام‌خورِ خانوادگی", quantity=2)], customer_name="علی رضایی",
               customer_phone="+989120000001", customer_address="تهران، خیابانِ تست", fulfillment="shipped",
               tracking_code="TR-421", created_at="2026-06-01 10:00:00", updated_at="2026-06-02 12:00:00")]


def entries():
    return [NS(id=3, ts=1_779_000_000, kind="expense", category="تبلیغات", amount_irr=500_000, signed_irr=-500_000,
               account="cash", ref_type="", ref_id=0, note="بنرِ اینستاگرام", reverses_id=0, reversed_by_id=0)]


def report_stub():
    return NS(start_ts=1_770_000_000, end_ts=1_780_000_000, gross_sales=1_100_000, discounts=100_000,
              shipping_income=50_000, sales_net=1_000_000, other_income=0, refunds=0, cogs=400_000,
              gross_profit=500_000, expenses=50_000, net_profit=450_000, orders_count=4, missing_cost_orders=0,
              by_method={"card": 1_000_000}, by_day=[], by_product=[("شام‌خور", 3, 600_000)],
              by_category=[], receivables_waiting=0, receivables_pending=10_000,
              top_customers=[("telegram", "1", "علی رضایی", 700_000)], inventory_value=90_000)


def products():
    return [NS(id=1, name="شام‌خورِ خانوادگی", category="خوراکی", price_irr=450_000, cost_irr=300_000,
               stock_quantity=12, unlimited_stock=False, active=True, sort_order=0, description="بسته‌ی ۴ نفره",
               created_at="2026-01-01 08:00:00", updated_at="2026-06-01 08:00:00")]


def conversations():
    return [NS(platform="telegram", chat_id="1", display_name="علی رضایی", memory_enabled=True, blocked=False,
               updated_at="2026-06-01 10:00:00", last_message_preview="سلام، وقتِ بخیر")]


def messages():
    return [NS(role="user", content="سلام، وقتِ بخیر", created_at="2026-06-01 10:00:00"),
            NS(role="assistant", content="پاسخ: سلام", created_at="2026-06-01 10:00:05")]


def five_reports():
    """پنجِ بخشِ خواسته‌شده؛ «گفتگوها» هم فهرست دارد هم متنِ یکِ گفتگو (هر دو تست می‌شوند)."""
    return {
        "customers": rx.customers_report(customers(), shop_name=SHOP),
        "orders": rx.orders_report(orders(), shop_name=SHOP),
        "finance": rx.finance_report(report_stub(), entries(), shop_name=SHOP),
        "products": rx.products_report(products(), shop_name=SHOP),
        "conversations": rx.conversations_report(conversations(), shop_name=SHOP),
    }


# ------------------------------------------------------------------ پنجِ گزارش ----

@pytest.mark.parametrize("key", sorted(five_reports()))
def test_each_report_is_a_valid_pdf_with_the_header_block(tmp_path, key):
    data = five_reports()[key]
    path = rp.write_pdf(data, tmp_path)
    raw = path.read_bytes()
    assert path.suffix == ".pdf" and raw.startswith(b"%PDF-") and len(raw) > 1024
    text = text_of(path)
    assert "گزارش" in text and "فروشگاه" in text  # عنوانِ گزارش + نامِ فروشگاه در سرِ گزارش
    assert SHOP.replace(" ", "") in text.replace(" ", ""), SHOP
    assert "تاریخِ" in text and "تعدادِ" in text
    assert "میلادی" in text  # تاریخِ ساخت جلالی + میلادی هر دو چاپ می‌شوند


def test_title_and_body_words_are_extractable(tmp_path):
    data = rx.products_report(products(), shop_name=SHOP)
    text = text_of(rp.write_pdf(data, tmp_path))
    for word in ("محصولات", "انبار", "شام", "خانوادگی", "قیمت", "موجودی"):
        assert word in text, word


def test_money_and_dates_are_printed_with_separators_but_irs_is_the_unit(tmp_path):
    text = text_of(rp.write_pdf(rx.orders_report(orders(), shop_name=SHOP), tmp_path))
    assert "ریال" in text
    digits = invoice_pdf.money(200_000, "fa")  # همان قالبِ پولیِ فاکتور (فارسی)
    assert digits in text or digits[::-1] in text  # pypdf ترتیبِ راست‌به‌چپ را برعکس هم درمی‌آورد


def test_metadata_and_landscape_geometry(tmp_path):
    data = rx.customers_report(customers(), shop_name=SHOP)
    reader = pypdf.PdfReader(str(rp.write_pdf(data, tmp_path)))
    assert reader.metadata.title == data.title
    box = reader.pages[0].mediabox
    assert float(box.width) > float(box.height)  # افقی: جدولِ ۱۸ ستونی در عمودی جا نمی‌شود


def test_digits_and_paper_and_brand_settings_are_honoured(tmp_path):
    data = rx.orders_report(orders(), shop_name=SHOP)
    path = rp.write_pdf(data, tmp_path, digits="en", paper="A5", brand="بدونِ‌رنگ")
    reader = pypdf.PdfReader(str(path))
    box = reader.pages[0].mediabox
    assert abs(float(box.width) - 595.3) < 3 and abs(float(box.height) - 419.5) < 3  # A5 افقی
    assert "200,000" in text_of(path)  # ارقامِ لاتین با جداکننده


def test_long_table_spawns_more_pages_with_a_repeated_header(tmp_path):
    many = [NS(**{**vars(products()[0]), "id": i, "name": f"کالایِ {i}"}) for i in range(120)]
    reader = pypdf.PdfReader(str(rp.write_pdf(rx.products_report(many, shop_name=SHOP), tmp_path)))
    assert len(reader.pages) >= 3
    text = "".join(page.extract_text() or "" for page in reader.pages)
    assert text.count("ارزشِ") >= 3 or text.count("قیمت") >= 3  # سطرِ ستون‌ها در هر صفحه تکرار می‌شود


# ------------------------------------------------------------- متنِ دشمنِ فارسی ----

def test_hostile_text_does_not_crash_the_shaper(tmp_path):
    hostile = [NS(**{**vars(products()[0]), "name": "😀\u202eکالایِ فوق‌العاده", "category": "🧪",
                     "description": "<b> HTML \x00 ‎\u206b", })]
    data = rx.products_report(hostile, shop_name="فروشگاهِ 😀 واقعی")
    text = text_of(rp.write_pdf(data, tmp_path, digits="en"))
    for bad in ("😀", "🧪", "\u202e", "\u200e", "\u206b", "\x00"):
        assert bad not in text, bad
    assert "کالایِ" in text and "فوق‌العاده" in text  # حروفِ فارسی و نیم‌فاصله سرِ جایشان می‌مانند
    assert "HTML" in text  # متنِ معمولی (حتی با تگ) سانسور نمی‌شود؛ فقط نویسه‌ی بی‌گلیف می‌رود


def test_emoji_is_dropped_because_the_font_has_no_glyph(tmp_path):
    """برخلافِ اکسل، PDF باید نویسه‌ی بدونِ گلیف را دور بریزد (سازنده‌ی فونت Vazirmatn است)."""
    assert "😀" not in invoice_pdf.clean("سلام 😀")
    data = rx.transcript_report([NS(role="user", content="سلام 😀", created_at="2026-06-01 10:00:00")],
                                conversation=conversations()[0], shop_name=SHOP)
    assert "😀" not in text_of(rp.write_pdf(data, tmp_path))


def test_reuses_the_invoice_pdf_helpers_not_a_second_shaper(monkeypatch, tmp_path):
    """هیچ کدِ شکل‌دهیِ دومی نوشته نشده: همان ``clean``/``wrap_lines``/``fonts_dir`` صدا زده می‌شوند."""
    calls = {"clean": 0, "wrap": 0, "fonts": 0}
    real_clean, real_wrap, real_fonts = invoice_pdf.clean, invoice_pdf.wrap_lines, invoice_pdf.fonts_dir

    def clean(text, limit=300):
        calls["clean"] += 1
        return real_clean(text, limit)

    def wrap(pdf, text, width, max_lines=3):
        calls["wrap"] += 1
        return real_wrap(pdf, text, width, max_lines)

    def fonts():
        calls["fonts"] += 1
        return real_fonts()

    monkeypatch.setattr(invoice_pdf, "clean", clean)
    monkeypatch.setattr(invoice_pdf, "wrap_lines", wrap)
    monkeypatch.setattr(invoice_pdf, "fonts_dir", fonts)
    assert rp.pdf_bytes(rx.customers_report(customers(), shop_name=SHOP)).startswith(b"%PDF-")
    assert calls["fonts"] == 1 and calls["clean"] > 0 and calls["wrap"] > 0


# ------------------------------------------------------------------ خطا و سقف ----

def test_empty_rows_raise_a_persian_error(tmp_path):
    folder = tmp_path / "out"
    folder.mkdir()
    with pytest.raises(rx.ReportError) as caught:
        rp.write_pdf(rx.products_report([], shop_name=SHOP), folder)
    assert str(caught.value) == rx.EMPTY_ERROR
    assert list(folder.iterdir()) == []  # فایلی نیمه‌کاره نمی‌ماند


def test_report_pdf_error_is_a_report_error():
    assert issubclass(rp.ReportPdfError, rx.ReportError)  # صفحه‌ها فقط ReportError می‌گیرند


def test_broken_library_input_becomes_a_friendly_error(monkeypatch, tmp_path):
    def explode(*a, **kw):
        raise RuntimeError("fpdf crash")

    folder = tmp_path / "out"
    folder.mkdir()
    monkeypatch.setattr(rp, "_ReportPDF", explode)
    with pytest.raises(rp.ReportPdfError) as caught:
        rp.write_pdf(rx.products_report(products(), shop_name=SHOP), folder)
    assert "ساختِ PDF ناموفق" in str(caught.value) and "RuntimeError" in str(caught.value)
    assert list(folder.iterdir()) == []


def test_pdf_row_cap_is_lower_than_xlsx_and_says_so(tmp_path, monkeypatch):
    many = [NS(**{**vars(products()[0]), "id": i, "name": f"کالایِ {i}"}) for i in range(rp.PDF_MAX_ROWS + 4)]
    data = rx.products_report(many, shop_name=SHOP)
    assert rp.PDF_MAX_ROWS < rx.MAX_ROWS
    assert len(data.pdf_rows(rp.PDF_MAX_ROWS)) == rp.PDF_MAX_ROWS
    monkeypatch.setattr(rp, "PDF_MAX_ROWS", 3)  # رندرِ ۵۰۰۰ سطر در تست منطقی نیست: منطقِ سقف سنجیده می‌شود
    text = text_of(rp.write_pdf(data, tmp_path))
    assert "PDF" in text and "اکسل" in text


def test_write_pdf_uses_the_reports_folder_of_app_data(tmp_path, monkeypatch):
    monkeypatch.setattr(rx, "get_app_data_dir", lambda: tmp_path / "appdata")
    path = rp.write_pdf(rx.orders_report(orders(), shop_name=SHOP))
    assert path.parent == tmp_path / "appdata" / "reports" and path.is_file()
    assert path.name.startswith("orders-") and "\\" not in path.name and "/" not in path.name
