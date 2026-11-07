"""وارداتِ دسته‌ایِ محصولات از قالبِ اکسل: فایلِ قالب واقعی است، سطرهایِ خراب سطر‌به‌سطر رد می‌شوند،
هیچ تراکنشِ نیمه‌کاری نوشته نمی‌شود و سقفِ حجم/سطر از دی‌اس‌ام/zip bomb محافظت می‌کند."""

import asyncio
import csv
import zipfile

import pytest
from fake_page import FakePage, find, fire

from app.core import product_import as pi
from app.core.product_import import ImportRow, ProductImportError, RowProblemError
from app.core.products import ProductStore, ProductError

HEADERS = ["نام", "قیمت (ریال)", "موجودی", "دسته", "توضیحات", "بهای تمام‌شده (ریال)"]


def rows(*records):
    return [HEADERS, *records]


def make_store(tmp_path):
    return ProductStore(db_path=tmp_path / "products.db")


# ------------------------------------------------------------------ فایلِ قالب ----


def test_template_is_a_real_xlsx_file(tmp_path):
    path = pi.write_template(tmp_path / "q.xlsx")
    assert path.is_file()
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        assert {"[Content_Types].xml", "xl/workbook.xml", "xl/worksheets/sheet1.xml"} <= names
        assert archive.read("xl/worksheets/sheet1.xml").decode("utf-8").startswith("<?xml")
    header, first = pi.read_rows(path)[0], pi.read_rows(path)[1]
    assert [h for h in header] == list(HEADERS)
    assert first[0] == "شام‌خورِ خانوادگی" and first[1] == "450000"


def test_template_bytes_are_stable(tmp_path):
    assert pi.template_bytes() == pi.template_bytes()
    assert pi.template_bytes(sample_rows=False) != pi.template_bytes(sample_rows=True)


def test_template_without_sample_rows_starts_at_the_header(tmp_path):
    path = tmp_path / "bare.xlsx"
    path.write_bytes(pi._zip_bytes(pi._sheet_xml([list(HEADERS)])))
    assert len(pi.read_rows(path)) == 1


# ------------------------------------------------------------------ خواندنِ فایل ----


def test_numbers_from_excel_are_read_as_integers(tmp_path):
    """اکسل عددِ صحیح را «450000.0» هم می‌نویسد؛ موجودی نباید «۴۵۰۰۰۰.۰» شود."""
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        '<row r="1"><c r="A1" t="inlineStr"><is><t>نام</t></is></c>'
        '<c r="B1" t="inlineStr"><is><t>قیمت (ریال)</t></is></c>'
        '<c r="C1" t="inlineStr"><is><t>موجودی</t></is></c></row>'
        '<row r="2"><c r="A2" t="inlineStr"><is><t>چای</t></is></c>'
        '<c r="B2"><v>280000.0</v></c><c r="C2"><v>12</v></c></row>'
        "</sheetData></worksheet>"
    )
    path = tmp_path / "nums.xlsx"
    path.write_bytes(pi._zip_bytes(xml))
    clean, problems = pi.parse_table(pi.read_rows(path))
    assert problems == [] and clean[0].price_irr == 280000 and clean[0].stock_quantity == 12


def test_shared_strings_workbook_is_read(tmp_path):
    """فایل‌هایِ ساخته‌شده با بقیه‌ی ابزارها sharedStrings دارند، نه inlineStr."""
    with zipfile.ZipFile(tmp_path / "shared.xlsx", "w") as archive:
        archive.writestr(
            "xl/sharedStrings.xml",
            '<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<si><t>نام</t></si><si><t>قیمت (ریال)</t></si><si><t>شیر</t></si><si><t>لبنیات</t></si></sst>",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
            '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>35000</v></c><c r="D2" t="s"><v>3</v></c></row>'
            "</sheetData></worksheet>",
        )
    table = pi.read_rows(tmp_path / "shared.xlsx")
    clean, problems = pi.parse_table(table)
    assert problems == [] and clean[0].name == "شیر" and clean[0].price_irr == 35000
    assert clean[0].category == ""  # ستونِ D بدونِ عنوان در سطرِ اول = نادیده


def test_csv_is_read_with_persian_text_in_every_encoding():
    fa = "نام,قیمت (ریال),موجودی\nشیر,۳۵۰۰۰,۴\n"
    assert pi._csv_rows(fa.encode("utf-8-sig"))[1] == ["شیر", "۳۵۰۰۰", "۴"]
    assert pi._csv_rows("نام;قیمت (ریال)\nشیر;35000\n".encode("utf-8"))[1] == ["شیر", "35000"]
    # اکسلِ قدیمی CSV را با cp1256 و «ي» عربی ذخیره می‌کند؛ باید همان ستون‌ها را بشناسیم
    legacy = "نام,قيمت (ريال)\nنان,12000\n".encode("cp1256")
    clean, problems = pi.parse_table(pi._csv_rows(legacy))
    assert problems == [] and clean[0].name == "نان" and clean[0].price_irr == 12000


def test_unknown_extension_is_refused(tmp_path):
    path = tmp_path / "products.xls"
    path.write_bytes(b"\xd0\xcf\x11\xe0old excel")
    with pytest.raises(ProductImportError, match="پشتیبانی"):
        pi.read_rows(path)


def test_a_truncated_xlsx_gives_a_clean_message(tmp_path):
    path = tmp_path / "broken.xlsx"
    path.write_bytes(pi.template_bytes()[:120])
    with pytest.raises(ProductImportError, match="xlsx معتبر"):
        pi.read_rows(path)


# ------------------------------------------------------------------ سطر و خطا ----


def test_english_headers_are_accepted_too():
    clean, problems = pi.parse_table([["Name", "Price (IRR)", "Stock", "Category"], ["Tea", "280000", "3", "Drink"]])
    assert problems == [] and clean[0].name == "Tea" and clean[0].category == "Drink"


def test_header_matching_ignores_spacing_and_half_space():
    assert pi.header_of("  بهای\u200c تمام\u2000شده ( ریال )  ") == pi.header_of("بهای تمام‌شده (ریال)")
    assert pi._header_key(" قيمت (ریال) ") == "price"


def test_missing_name_column_is_a_file_error():
    with pytest.raises(ProductImportError, match="«نام»"):
        pi.parse_table([["قیمت (ریال)"], ["1000"]])


def test_missing_price_column_is_a_file_error():
    with pytest.raises(ProductImportError, match="«قیمت"):
        pi.parse_table([["نام"], ["چای"]])


def test_empty_file_is_a_file_error():
    with pytest.raises(ProductImportError, match="خالیه"):
        pi.parse_table([])


def test_bad_cells_are_rejected_row_by_row():
    clean, problems = pi.parse_table(
        rows(
            ["چای", "280000", "3", "نوشیدنی", "", ""],
            ["", "10", "1"],  # بی‌نام
            ["رب", "متن", "2"],  # قیمتِ غیرعددی
            ["شیر", "-500", "1"],  # قیمتِ منفی
            ["کره", "12000", "سه"],  # موجودیِ غیرعددی
            ["ق" * 250, "90000", "2"],  # نامِ خیلی بلند
        )
    )
    assert [c.name for c in clean] == ["چای"]
    assert [p.row_number for p in problems] == [3, 4, 5, 6, 7]
    assert "قیمت" in problems[1].reason and "منفی" in problems[2].reason and "موجودی" in problems[3].reason
    assert "200" in problems[4].reason


def test_blank_rows_are_skipped_not_reported():
    clean, problems = pi.parse_table(rows(["چای", "280000", "1"], ["", "", "", "", "", ""], []))
    assert len(clean) == 1 and problems == []


def test_unlimited_stock_word_is_understood():
    clean, problems = pi.parse_table(rows(["چای", "280000", "نامحدود"], ["شیر", "35000", "UNLIMITED"]))
    assert problems == [] and all(row.unlimited_stock and row.stock_quantity == 0 for row in clean)


def test_price_of_one_is_rial_not_tomani_confusion():
    clean, _problems = pi.parse_table(rows(["چای", "1", "1"]))
    assert clean[0].price_irr == 1
    clean, _ = pi.parse_table(rows(["چای", "۴۵۰٬۰۰۰", "۱۲"]))
    assert clean[0].price_irr == 450000 and clean[0].stock_quantity == 12


def test_row_count_cap():
    big = [HEADERS] + [["محصول", "1000", "1"] for _ in range(pi.MAX_ROWS + 2)]
    with pytest.raises(ProductImportError, match="تقسیم"):
        pi.parse_table(big)


def test_control_characters_are_stripped_from_text():
    clean, problems = pi.parse_table(rows(["چا\x00ی", "280000", "1", "دسته\x07", "ت\x01ویض"]))
    assert problems == [] and clean[0].name == "چای" and clean[0].category == "دسته" and clean[0].description == "تویض"


def test_money_over_the_cap_is_refused():
    with pytest.raises(RowProblemError):
        pi._money("9" * 20, "قیمت", 2)


# -------------------------------------------------------------------- نوشتن ----


def test_add_many_writes_in_one_transaction(tmp_path):
    store = make_store(tmp_path)
    clean, problems = pi.parse_table(rows(["چای", "280000", "12", "نوشیدنی", "درجه یک", "190000"], ["شیر", "35000", "نامحدود"]))
    assert problems == [] and len(clean) == 2
    added, _ = pi.import_file(store, _write_table(tmp_path, [HEADERS, ["چای", "280000", "12", "نوشیدنی", "درجه یک", "190000"], ["شیر", "35000", "نامحدود"]]))
    assert len(added) == 2
    by_name = {p.name: p for p in store.list()}
    tea = by_name["چای"]
    assert (tea.price_irr, tea.stock_quantity, tea.category, tea.description, tea.cost_irr) == (
        280000, 12, "نوشیدنی", "درجه یک", 190000)
    milk = by_name["شیر"]
    assert (milk.unlimited_stock, milk.in_stock, milk.stock_quantity) == (True, True, 0)


def test_add_many_rolls_back_every_row_when_one_is_bad(tmp_path):
    store = make_store(tmp_path)
    store.add("قبلی", 1000, 1)
    good = {"name": "چای", "price_irr": 280000, "stock_quantity": 12}
    bad = {"name": "   ", "price_irr": 10, "stock_quantity": 1}
    with pytest.raises(ProductError):
        store.add_many([good, bad])
    assert [p.name for p in store.list()] == ["قبلی"]  # سطرِ سالم هم نوشته نشد


def test_missing_sheet_gives_a_clean_message(tmp_path):
    """فایلی که برگه‌ی اولش نیست (یا با ابزارِ دیگری ساخته شده) نباید با KeyError بترکد."""
    path = tmp_path / "nosheet.xlsx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
    with pytest.raises(ProductImportError, match="برگه‌ی اول"):
        pi.read_rows(path)


def test_zip_entry_limits_are_enforced(tmp_path, monkeypatch):
    payload = pi.template_bytes()
    monkeypatch.setattr(pi, "MAX_ZIP_ENTRIES", 2)
    with pytest.raises(ProductImportError, match="بخشِ داخلی"):
        pi._xlsx_rows(payload)
    monkeypatch.setattr(pi, "MAX_ZIP_ENTRIES", 2000)
    monkeypatch.setattr(pi, "MAX_UNCOMPRESSED_BYTES", 128)
    with pytest.raises(ProductImportError, match="بزرگ می‌شه"):
        pi._xlsx_rows(payload)


def test_import_rejects_an_oversized_file(tmp_path):
    path = tmp_path / "big.csv"
    path.write_bytes(b"\xef\xbb\xbf" + b"a,1\n" * 20 + b"x" * (pi.MAX_FILE_BYTES + 1))
    with pytest.raises(ProductImportError, match="مگابایت"):
        pi.read_rows(path)


def _write_table(tmp_path, table):
    path = tmp_path / "in.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.writer(handle).writerows(table)
    return path


# ------------------------------------------------------------------ صفحه ----


def test_screen_template_button_creates_the_file(tmp_path, monkeypatch):
    from app.screens import products as screen
    from app.core import paths

    monkeypatch.setattr(paths, "get_app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(screen, "get_app_data_dir", lambda: tmp_path)
    page = FakePage()
    root = screen.build(page, "fa", make_store(tmp_path))
    fire(find(root, "product_template"), "on_click")
    written = tmp_path / "exports" / "products-template.xlsx"
    assert written.is_file()
    assert str(written) in find(root, "product_import_note").value


def test_screen_import_adds_products_and_reports_problems(tmp_path, monkeypatch):
    from app.screens import products as screen

    store = make_store(tmp_path)
    table = _write_table(tmp_path, rows(["چای", "280000", "12"], ["", "10", "1"]))

    class Picker:
        async def pick_files(self, **_kwargs):
            class Chosen:
                path = str(table)

            return [Chosen()]

    monkeypatch.setattr(screen, "get_or_create_file_picker", lambda page: Picker())
    page = FakePage()
    root = screen.build(page, "fa", store)
    asyncio.run(find(root, "product_import").on_click(None))
    assert [p.name for p in store.list()] == ["چای"]
    note = find(root, "product_import_note").value
    assert "1 محصول اضافه شد" in note and "سطرِ 3" in note


def test_screen_import_shows_a_file_level_error(tmp_path, monkeypatch):
    from app.screens import products as screen

    broken = tmp_path / "bad.xlsx"
    broken.write_bytes(b"not a zip at all")

    class Picker:
        async def pick_files(self, **_kwargs):
            class Chosen:
                path = str(broken)

            return [Chosen()]

    monkeypatch.setattr(screen, "get_or_create_file_picker", lambda page: Picker())
    page = FakePage()
    root = screen.build(page, "fa", make_store(tmp_path))
    asyncio.run(find(root, "product_import").on_click(None))
    assert "xlsx معتبر" in find(root, "product_import_note").value


def test_summary_wording_for_both_languages():
    added = [ImportRow(row_number=2, name="چای", price_irr=1)]
    problems = [pi.RowProblem(row_number=3, reason="قیمت عدد نیست")]
    fa = pi.import_summary("fa", added, problems)
    assert "1 محصول اضافه شد" in fa and "سطرِ 3" in fa and "1 سطر وارد نشد" in fa
    assert "Added 1 products" in pi.import_summary("en", added, [])
    assert "nothing to import" in pi.import_summary("en", [], []).lower()


def test_summary_lists_at_most_five_problems():
    problems = [pi.RowProblem(row_number=2 + i, reason="بی‌نام") for i in range(9)]
    text = pi.import_summary("fa", [], problems)
    assert "9 سطر وارد نشد" in text and "4 سطرِ دیگر" in text and text.count("بی‌نام") == 5


# ═════════════════════ بازبینیِ امنیت: ENTITY/DOCTYPE در فایلِ اکسل هرگز parse نمی‌شود ═════════════════════


def _hostile_workbook(tmp_path):
    """قالبِ واقعیِ برنامه را می‌گیرد و XMLِ برگه‌اش را با یک entityِ بزرگ عوض می‌کند."""
    import io

    raw = io.BytesIO(pi.template_bytes())
    buffer = io.BytesIO()
    with zipfile.ZipFile(raw) as source, zipfile.ZipFile(buffer, "w") as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                data = (b'<?xml version="1.0"?>'
                        b'<!DOCTYPE x [<!ENTITY a "' + b"A" * 20000 + b'">]>'
                        b'<worksheet><row r="1"><c r="A1"><v>1</v></c></row></worksheet>')
            target.writestr(item, data)
    path = tmp_path / "evil.xlsx"
    path.write_bytes(buffer.getvalue())
    return path


def test_a_workbook_with_entity_declarations_is_refused_before_parsing(tmp_path):
    """«billion laughs»: چند کیلوبایت فایل می‌توانست CPU و RAMِ فروشنده را قفل کند."""
    path = _hostile_workbook(tmp_path)
    with pytest.raises(ProductImportError) as caught:
        pi.import_file(ProductStore(tmp_path / "p.db"), path)
    assert "ENTITY" in str(caught.value) or "خطرناک" in str(caught.value)


def test_xml_root_rejects_declarations_and_accepts_clean_xml():
    with pytest.raises(ProductImportError):
        pi.xml_root(b'<!DOCTYPE x [<!ENTITY a "b">]><x/>')
    with pytest.raises(ProductImportError):
        pi.xml_root(b'<!ENTITY a "b"><x/>')
    assert pi.xml_root(b"<x><a>1</a></x>").tag == "x"
