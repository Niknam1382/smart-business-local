"""گزارشِ اکسلِ پنجِ بخش (``app/core/report_xlsx.py``) — فایلِ واقعی، بدونِ openpyxl.

هر پنجِ گزارش روی ``tmp_path`` نوشته می‌شوند و با **همانِ خواننده‌یِ** ``product_import.read_rows``
بازخوانی می‌شوند (چون آن خواننده ۳۰ تستِ مستقل دارد، پس «فایلِ ما واقعاً xlsx است» را مجانی می‌سنجیم):
سطرِ ستون‌ها، تعدادِ سطور، عددی‌بودنِ سلولِ پول، پاک‌سازیِ متنِ دشمن (bidi)، سطرِ ستون‌هایِ ثابت
(frozen pane)، پهنایِ ستون‌ها، سرِ گزارش، خطایِ «داده‌ای نیست» و سقفِ ۲۰٬۰۰۰ سطر.
"""

import zipfile
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from app.core import product_import as pi
from app.core import report_xlsx as rx

SHOP = "فروشگاه نمونه"


def customer(**kw):
    base = dict(platform="telegram", user_id="1", display_name="علی رضایی", username="ali_r", phone="+989120000001",
                 language_code="fa", msg_count=12, orders_count=3, total_spent_irr=1_250_000,
                 last_order_ts=1_780_000_000, last_seen_ts=1_780_100_000, first_seen_ts=1_770_000_000,
                 tags=["ویژه", "همیشگی"], notes="پرداختِ منظم", blocked=False, opted_out=False, unreachable=False)
    return NS(**{**base, **kw})


def order(**kw):
    base = dict(id=7, platform="telegram", chat_id="1", status="confirmed", payment_method="card_to_card",
                 payment_reference="rr-9", total_irr=200_000, subtotal_irr=220_000, discount_irr=20_000,
                 shipping_irr=15_000, items=[NS(product_name="شام‌خور", quantity=2)], customer_name="علی رضایی",
                 customer_phone="+989120000001", customer_address="تهران، خیابانِ تست", note="",
                 created_at="2026-06-01 10:00:00", updated_at="2026-06-02 12:00:00", fulfillment="shipped",
                 tracking_code="TR-421")
    return NS(**{**base, **kw})


def entry(**kw):
    base = dict(id=3, ts=1_779_000_000, kind="expense", category="تبلیغات", amount_irr=500_000,
                 signed_irr=-500_000, account="cash", ref_type="", ref_id=0, note="بنرِ اینستاگرام",
                 created_by="owner", reverses_id=0, reversed_by_id=0)
    return NS(**{**base, **kw})


def product(**kw):
    base = dict(id=1, name="شام‌خورِ خانوادگی", category="خوراکی", price_irr=450_000, cost_irr=300_000,
                 stock_quantity=12, unlimited_stock=False, active=True, sort_order=0, description="بسته‌ی ۴ نفره",
                 created_at="2026-01-01 08:00:00", updated_at="2026-06-01 08:00:00")
    return NS(**{**base, **kw})


def conversation(**kw):
    base = dict(platform="telegram", chat_id="1", display_name="علی رضایی", memory_enabled=True, blocked=False,
                 updated_at="2026-06-01 10:00:00", last_message_preview="سلام، وقتِ بخیر")
    return NS(**{**base, **kw})


def message(**kw):
    base = dict(role="user", content="سلام، وقتِ بخیر", created_at="2026-06-01 10:00:00")
    return NS(**{**base, **kw})


def report_stub(**kw):
    """همان ``finance.Report`` با چندِ عددِ قابل‌سنجش (تستِ UIِ واقعی در test_finance_screen.py)."""
    base = dict(start_ts=1_770_000_000, end_ts=1_780_000_000, gross_sales=1_100_000, discounts=100_000,
                 shipping_income=50_000, sales_net=1_000_000, other_income=0, refunds=0, cogs=400_000,
                 gross_profit=500_000, expenses=50_000, net_profit=450_000, orders_count=4, missing_cost_orders=0,
                 by_method={"card": 1_000_000}, by_day=[("1405/02/27", 200_000)], by_product=[("شام‌خور", 3, 600_000)],
                 by_category=[("تبلیغات", 500_000)], receivables_waiting=0, receivables_pending=10_000,
                 top_customers=[("telegram", "1", "علی رضایی", 700_000)], inventory_value=90_000)
    return NS(**{**base, **kw})


def all_reports():
    """پنجِ بخشِ خواسته‌شده (پنجمی هم فهرستِ گفتگوهاست، هم متنِ یکِ گفتگو)."""
    return {
        "customers": rx.customers_report([customer()], shop_name=SHOP),
        "orders": rx.orders_report([order()], shop_name=SHOP),
        "finance": rx.finance_report(report_stub(), [entry()], shop_name=SHOP),
        "products": rx.products_report([product()], shop_name=SHOP),
        "conversations": rx.conversations_report([conversation()], shop_name=SHOP),
    }


def write_one(tmp_path, data) -> Path:
    return rx.write_xlsx(data, tmp_path)


# ------------------------------------------------------------------- پنجِ گزارش ----

@pytest.mark.parametrize("key", sorted(all_reports()))
def test_each_report_writes_a_real_xlsx(tmp_path, key):
    data = all_reports()[key]
    path = write_one(tmp_path, data)
    assert path.is_file() and path.suffix == ".xlsx" and path.stat().st_size > 1024
    assert path.parent == tmp_path
    preamble, header, body = rx.read_report(path, data)
    assert header == list(data.titles())
    assert len(body) == data.count == 1
    assert preamble[0] == data.title and preamble[1] == f"فروشگاه: {SHOP}"
    assert any(line.startswith("تعدادِ سطور:") for line in preamble)
    assert any("تاریخِ ساخت:" in line and "میلادی" in line for line in preamble)


def test_header_block_and_footer_are_in_every_file(tmp_path):
    for data in all_reports().values():
        xml = rx.sheet_xml_of(write_one(tmp_path, data))
        assert rx.FOOTER_NOTE[:24] in xml, data.kind
        assert data.title in xml and SHOP in xml


def test_money_cells_are_plain_numbers_and_dates_have_both_calendars(tmp_path):
    data = rx.orders_report([order()], shop_name=SHOP)
    path = write_one(tmp_path, data)
    _p, _h, body = rx.read_report(path, data)
    row = body[0]
    money_column = data.titles().index("مبلغ (ریال)")
    assert row[money_column] == "200000" and row[money_column].isdigit()  # بدونِ جداکننده ⇒ اکسل جمع می‌گیرد
    jalali_title = next(t for t in data.titles() if "جلالی" in t)
    iso_title = next(t for t in data.titles() if "میلادی" in t)
    assert row[data.titles().index(jalali_title)].startswith("1405/")
    assert row[data.titles().index(iso_title)].startswith("2026-")
    xml = rx.sheet_xml_of(path)
    assert "<v>200000</v>" in xml  # در XML هم هیچ جداکننده‌ای در عدد نیست


def test_xlsx_keeps_numbers_numeric_in_the_raw_cells(tmp_path):
    """سلولِ پولی/عددی ``<v>`` است (نه inlineStr) تا Excel/LibreOffice آن را عدد بدانند."""
    path = write_one(tmp_path, rx.products_report([product()], shop_name=SHOP))
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert '<c r="C7"><v>450000</v></c>' in xml.replace(' s="2"', "")  # ستونِ قیمت = عدد
    assert '<c r="F7" s="6"><v>12</v></c>' in xml  # موجودی = عددِ صحیح با قالبِ «0»


def test_frozen_pane_and_column_widths_and_rtl_sheet(tmp_path):
    data = rx.customers_report([customer()], shop_name=SHOP)
    path = write_one(tmp_path, data)
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert 'state="frozen"' in xml and f'ySplit="{data.header_index() - 1}"' in xml
    assert 'rightToLeft="1"' in xml  # برگه راست‌به‌چپ: ستونِ A سمتِ راست
    assert "<cols>" in xml and 'customWidth="1"' in xml and 'width="26"' in xml  # ستونِ اول پهن
    assert 't="inlineStr"' in xml and "<v>" in xml  # متن و عدد قاطی نمی‌شوند
    assert zipfile.ZipFile(path).namelist() == [
        "[Content_Types].xml", "_rels/.rels", "xl/workbook.xml", "xl/_rels/workbook.xml.rels",
        "xl/styles.xml", "xl/worksheets/sheet1.xml"]


def test_header_row_is_bold_styled_and_body_uses_money_style(tmp_path):
    data = rx.orders_report([order()], shop_name=SHOP)
    xml = rx.sheet_xml_of(write_one(tmp_path, data))
    header = xml.split('<row r="6"')[1].split("</row>")[0]
    assert header.count('s="1"') == len(data.columns)  # تمامِ ستون‌ها سبکِ سرستون (پررنگ + رنگِ برند)
    assert 's="2"' in xml and 's="3"' in xml  # سبکِ پولی و سبکِ متنِ راست‌چین در سطورِ گزارش
    styles = zipfile.ZipFile(rx.write_xlsx(data, tmp_path)).read("xl/styles.xml").decode("utf-8")
    assert "<b/>" in styles and 'numFmtId="164"' in styles and 'horizontal="right"' in styles


# ------------------------------------------------------------------ متنِ دشمن ----

def test_bidi_override_and_control_characters_never_reach_the_file(tmp_path):
    """سطرِ آلوده به ``\u202e`` در اکسل کل ردیف را آینه می‌کند؛ جای آن فاصله می‌نشیند (نه حذف،
    تا حروف به هم نچسبند). ایموجی برعکسِ PDF اینجا **می‌ماند**: اکسل خودش فونت دارد و عدد/متن نمی‌شکند."""
    hostile = rx.customers_report(
        [customer(display_name="علی\u202e\u202d رضایی", notes="=HYPERLINK(\"http://evil\")\x00😀",
                  username="a\u200eb", tags=["😀ویژه"])], shop_name="فروشگاه\u202eِ نمونه")
    path = write_one(tmp_path, hostile)
    _p, _h, body = rx.read_report(path, hostile)
    joined = "".join(body[0]) + "".join(rx.read_report(path)[0])
    for bad in ("\u202e", "\u202d", "\u200e", "\x00"):
        assert bad not in joined, bad
    assert "😀" in joined  # همان‌طور که در فایلِ اکسلِ دست‌ساز هم می‌ماند
    assert "علی" in joined and "رضایی" in joined  # خودِ نام سالم می‌ماند
    assert "ویژه" in joined


def test_zwj_and_persian_letters_survive(tmp_path):
    """نیم‌فاصله (ZWNJ) و حروفِ فارسی نباید حذف شوند، وگرنه «شناسه‌ی کاربری» می‌شود «شناسه کاربری»."""
    data = rx.products_report([product(name="چایِ ممتاز ۴۰۰ گرمی", description="بسته‌بندیِ خلأ")], shop_name=SHOP)
    _p, header, body = rx.read_report(write_one(tmp_path, data), data)
    assert "\u200c" in header[3] and body[0][0].startswith("چایِ")  # «بهای تمام‌شده»
    assert "بسته‌بندی" in body[0][10] and "خلأ" in body[0][10]


def test_persian_text_survives_the_round_trip(tmp_path):
    data = rx.products_report([product(name="چایِ ممتازِ ۴۰۰ گرمی", description="بسته‌بندیِ خلأ")], shop_name=SHOP)
    _p, _h, body = rx.read_report(write_one(tmp_path, data), data)
    assert body[0][0] == "چایِ ممتازِ ۴۰۰ گرمی" and "خلأ" in body[0][10]


# ------------------------------------------------------------- خطا و سقفِ سطور ----

def test_empty_section_raises_one_clear_persian_error(tmp_path):
    builders = [
        lambda: rx.customers_report([], shop_name=SHOP),
        lambda: rx.orders_report([], shop_name=SHOP),
        lambda: rx.finance_report(report_stub(), [], shop_name=SHOP),
        lambda: rx.products_report([], shop_name=SHOP),
        lambda: rx.conversations_report([], shop_name=SHOP),
        lambda: rx.transcript_report([], conversation=conversation(), shop_name=SHOP),
    ]
    for build in builders:
        with pytest.raises(rx.ReportError) as caught:
            build()
        assert str(caught.value) == rx.EMPTY_ERROR == "چیزی برای خروجی گرفتن نیست."
        assert not list(tmp_path.glob("*.xlsx"))  # فایلی نیمه‌کاره نمی‌ماند


def test_max_rows_cap_truncates_and_says_so(tmp_path):
    many = [product(id=i, name=f"کالایِ {i}") for i in range(rx.MAX_ROWS + 7)]
    data = rx.products_report(many, shop_name=SHOP)
    assert data.count == rx.MAX_ROWS and data.truncated is True
    path = write_one(tmp_path, data)
    preamble, _h, body = rx.read_report(path, data)
    assert len(body) == rx.MAX_ROWS
    assert any(rx.TRUNCATED_NOTE[:18] in line for line in preamble)
    assert rx.TRUNCATED_NOTE[:18] in rx.sheet_xml_of(path)


def test_no_truncation_below_the_cap():
    data = rx.products_report([product(id=i) for i in range(rx.MAX_ROWS)], shop_name=SHOP)
    assert data.count == rx.MAX_ROWS and data.truncated is False


def test_summary_block_is_written_under_the_table(tmp_path):
    data = rx.finance_report(report_stub(), [entry()], shop_name=SHOP)
    xml = rx.sheet_xml_of(write_one(tmp_path, data))
    assert "سودِ خالص (ریال):" in xml and "فروشِ خالص (ریال):" in xml
    assert data.header_index() == 6  # سرِ گزارش کوتاه می‌ماند تا paneِ frozen نصفِ صفحه را نگیرد


def test_transcript_report_labels_roles_and_times(tmp_path):
    data = rx.transcript_report([message(), message(role="assistant", content="پاسخ: سلام"),
                                 message(role="owner", content="بفرستید")], conversation=conversation(), shop_name=SHOP)
    _p, header, body = rx.read_report(write_one(tmp_path, data), data)
    assert header[0] == "نقش" and [row[0] for row in body] == ["مشتری", "ربات", "شما"]
    assert body[0][2].startswith("2026-")  # ستونِ میلادی هم هست


# ------------------------------------------------- سرویسِ فایل و نامِ فروشگاه ----

def test_reports_dir_is_under_app_data_and_created(tmp_path, monkeypatch):
    monkeypatch.setattr(rx, "get_app_data_dir", lambda: tmp_path / "appdata")
    folder = rx.reports_dir()
    assert folder == tmp_path / "appdata" / "reports" and folder.is_dir()
    path = rx.write_xlsx(rx.products_report([product()], shop_name=SHOP))
    assert path.parent == folder and path.name.startswith("products-")


def test_file_stem_is_path_safe():
    name = rx.file_stem("ConvERSATIONS", 1_780_000_000.5)
    assert "/" not in name and "\\" not in name and " " not in name and ".." not in name
    assert name.startswith("conversations-")


def test_shop_name_resolution_prefers_the_invoice_shop_name():
    assert rx.shop_name_of(None) == rx.DEFAULT_SHOP_NAME
    assert rx.shop_name_of(NS(invoice_seller_name="فروشگاهِ مریم", user_name="مریم")) == "فروشگاهِ مریم"
    assert rx.shop_name_of(NS(user_name="مریم")) == "مریم"
    assert rx.shop_name_of(NS(_settings=NS(invoice_seller_name="از مدیر"))) == "از مدیر"  # manager
    assert rx.shop_name_of(NS(settings=NS(invoice_seller_name="از manager.make"))) == "از manager.make"
    assert rx.shop_name_of(NS(invoice_seller_name="ن\u202e\u202dاف")) == "ن اف"  # جای override فاصله می‌نشیند


def test_default_shop_name_used_when_settings_are_empty():
    data = rx.products_report([product()], shop_name="")
    assert data.shop_name == rx.DEFAULT_SHOP_NAME
    assert data.preamble()[1] == f"فروشگاه: {rx.DEFAULT_SHOP_NAME}"


def test_read_report_without_the_object_still_finds_the_table(tmp_path):
    """بلوکِ خلاصه/پانوشتِ زیرِ جدول با heuristic کنار گذاشته می‌شود (دسترسیِ سریعِ عادی‌سازی‌شده)."""
    data = rx.finance_report(report_stub(), [entry(), entry(id=4, kind="income", amount_irr=20_000)], shop_name=SHOP)
    _p, header, body = rx.read_report(write_one(tmp_path, data))
    assert header == list(data.titles()) and len(body) == 2


def test_rejects_a_handmade_file(tmp_path):
    path = tmp_path / "handmade.xlsx"
    pi.write_template(path)  # قالبِ وارداتِ محصولات: سطرهایِ تک‌سلولی نیست ولی ستون‌هایِ ما را ندارد
    _p, header, body = rx.read_report(path)
    assert header and header[0] == "نام" and body
