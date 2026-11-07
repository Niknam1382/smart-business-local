"""وارداتِ دسته‌ایِ محصولات از فایلِ اکسل/CSV — بدونِ هیچِ وابستگیِ تازه.

چرا ``.xlsx``: اکسلِ فارسی وقتی «CSV» را ذخیره می‌کند معمولاً کدپیجِ ویندوز (cp1256) را می‌گذارد و
حروفِ فارسی می‌شکنند؛ فایلِ ``.xlsx`` همیشه UTF-8 است. پس برنامه یک قالبِ ``.xlsx`` می‌سازد و همان
قالب (و ``.csv``) را می‌خواند.

ستون‌هایِ قالب (نامِ ستون با فاصله/نیم‌فاصله/بزرگی‌کوچکی فرقی نمی‌کند؛ معادلِ انگلیسی هم می‌پذیرد):
    نام · قیمت (ریال) · موجودی · دسته · توضیحات · بهای تمام‌شده (ریال)

«موجودی» یا عدد است یا ``نامحدود``. محصول فقط فیزیکی است و همین شش ستون لازمِ ساختِ کاتالوگ را
پوشش می‌دهد.

هیچ سطرِ نیمه‌کاره‌ای نوشته نمی‌شود: اول همه‌ی سطرها اعتبارسنجی می‌شوند، سطرهایِ خراب با شماره و
دلیل رد می‌شوند و سطرهایِ سالم در **یک** تراکنش اضافه می‌شوند.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

MAX_FILE_BYTES = 10 * 1024 * 1024  # سقفِ فایلِ ورودی
MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024  # محافظت از zip bomb
MAX_ZIP_ENTRIES = 2000
MAX_ROWS = 5000
MAX_NAME = 200
MAX_CATEGORY = 40
MAX_DESCRIPTION = 4000
MAX_MONEY = 10**15
_UNLIMITED_WORDS = {"نامحدود", "بی‌نهایت", "بینهایت", "unlimited"}
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_DIGIT_MAP = {ord("۰۱۲۳۴۵۶۷۸۹"[i]): str(i) for i in range(10)} | {ord("٠١٢٣٤٥٦٧٨٩"[i]): str(i) for i in range(10)}

# (کلید، عنوانِ فارسی، عنوانِ انگلیسی) — همین ترتیب در فایلِ قالب نوشته می‌شه
COLUMNS = (
    ("name", "نام", "Name"),
    ("price", "قیمت (ریال)", "Price (IRR)"),
    ("stock", "موجودی", "Stock"),
    ("category", "دسته", "Category"),
    ("description", "توضیحات", "Description"),
    ("cost", "بهای تمام‌شده (ریال)", "Cost (IRR)"),
)
_ALIASES = {
    "name": {"name", "نام", "نام محصول", "product", "عنوان"},
    "price": {"price", "قیمت", "قیمت (ریال)", "price irr", "مبلغ"},
    "stock": {"stock", "موجودی", "موجودی (عدد)", "quantity", "count"},
    "category": {"category", "دسته", "دسته‌بندی", "group"},
    "description": {"description", "توضیحات", "توضیح", "desc"},
    "cost": {"cost", "بهای تمام‌شده", "بهای تمام‌شده (ریال)", "cost irr"},
}


class ProductImportError(Exception):
    """خطایِ خودِ فایل (نه یک سطر): نخوانده‌شدن، نبودنِ ستونِ لازم، عبور از سقفِ حجم یا سطر."""


class RowProblemError(Exception):
    """خطایِ یک سطر؛ شماره و دلیلش مستقیم به کاربر نشان داده می‌شود."""

    def __init__(self, row_number: int, reason: str):
        super().__init__(f"سطرِ {row_number}: {reason}")
        self.row_number = row_number
        self.reason = reason


@dataclass
class ImportRow:
    row_number: int
    name: str
    price_irr: int
    stock_quantity: int = 0
    unlimited_stock: bool = False
    category: str = ""
    description: str = ""
    cost_irr: int = 0


@dataclass
class RowProblem:
    row_number: int
    reason: str


def header_of(value: object) -> str:
    """عنوان/مقدار را برای مقایسه آماده می‌کند: نیم‌فاصله و علامتِ جهت حذف، فاصله‌ها یک‌تا،
    پرانتزِ ستون‌ها بی‌اثر، ارقام فارسی/عربی Latin، ی/ك عربی به شکلِ فارسی، و casefold.

    تبدیلِ ي→ی و ك→ک لازم است: CSVای که اکسلِ قدیمی با cp1256 ذخیره کرده همان «قيمت» را می‌نویسد
    و بی‌این تبدیل هیچ ستونی شناخته نمی‌شد."""
    text = unicodedata.normalize("NFC", str(value if value is not None else "").replace("‌", " ").replace("‎", ""))
    text = text.replace("ي", "ی").replace("ك", "ک").replace("(", " ").replace(")", " ")
    return re.sub(r"\s+", " ", text).strip().casefold().translate(_DIGIT_MAP)


def _header_key(raw: object) -> Optional[str]:
    normalized = header_of(raw)
    for key, names in _ALIASES.items():
        if normalized in {header_of(name) for name in names}:
            return key
    return None


# ------------------------------------------------------------------- قالب‌سازی ----


def _column_letters(index: int) -> str:
    """۰ ← A، ۲۵ ← Z، ۲۶ ← AA — همان شمارشِ ستونِ اکسل."""
    letters = ""
    position = index + 1
    while position:
        position, remainder = divmod(position - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _clean_cell(value: object) -> str:
    return _CTRL.sub("", str(value if value is not None else "")).strip()


def _sheet_xml(rows: list) -> str:
    xml_rows = []
    for r_index, row in enumerate(rows, start=1):
        cells = []
        for c_index, value in enumerate(row):
            ref = f"{_column_letters(c_index)}{r_index}"
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{_xml_escape(_clean_cell(value))}</t></is></c>')
        xml_rows.append(f'<row r="{r_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(xml_rows)}</sheetData></worksheet>'
    )


def template_bytes(*, sample_rows: bool = True) -> bytes:
    """یک ``.xlsx``ِ واقعی و استاندارد از zip + XMLِ استانداردِ پایتون می‌سازد.

    مقدارها ``inlineStr`` نوشته می‌شوند (نیازی به sharedStrings نیست) و قیمت/موجودی به‌شکلِ عدد،
    تا اکسل و LibreOffice هر دو همان را مثلِ فایلِ دست‌ساز باز کنند."""
    rows: list = [[fa for _key, fa, _en in COLUMNS]]
    if sample_rows:
        rows.append(["شام‌خورِ خانوادگی", 450000, 12, "خوراکی", "بسته‌ی ۴ نفره", 300000])
        rows.append(["چای ممتاز ۴۰۰ گرمی", 280000, "نامحدود", "نوشیدنی", "", 190000])
    return _zip_bytes(_sheet_xml(rows))


def _zip_bytes(sheet_xml: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
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
            '<sheets><sheet name="محصولات" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buffer.getvalue()


def write_template(path: Path) -> Path:
    """قالب را روی دیسک می‌نویسد و مسیرش را برمی‌گرداند (همان الگویِ خروجیِ مشتری و دفتر)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(template_bytes())
    return path


# ------------------------------------------------------------------------ خواندن ----


def _local(tag: str) -> str:
    return tag.split("}")[-1]


# یک xlsxِ سالم هیچ‌وقتبرچسبِ DOCTYPE/ENTITY دارد؛ داشتنشان یعنی فایلِ دست‌کاری‌شده
# (هجومِ «mildly billion laughs»: چند کیلوبایت فایل، CPU و RAMِ فروشنده را قفل می‌کند).
_XML_DECL = re.compile(rb"<!(DOCTYPE|ENTITY)", re.IGNORECASE)


def xml_root(raw: bytes):
    """parseِ محافظت‌شده: هر XMLِ درونِ فایلِ اکسل اول از وجودِ برچسب‌هایِ داخلی پاس می‌شود."""
    if _XML_DECL.search(raw or b""):
        raise ProductImportError("فایلِ اکسل بخشِ داخلیِ خطرناک (ENTITY/DOCTYPE) داره؛ برای امنیتِ سیستم باز نمی‌شه.")
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ProductImportError(f"ساختارِ فایلِ اکسل خرابه: {exc}") from exc


def _shared_strings(archive: zipfile.ZipFile) -> list:
    try:
        raw = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = xml_root(raw)
    return ["".join(node.text or "" for node in si.iter() if _local(node.tag) == "t") for si in root]


def _first_sheet_name(archive: zipfile.ZipFile) -> str:
    """اولین برگه از relهایِ ورکبوک؛ نشانی پیدا نشد ← ``xl/worksheets/sheet1.xml``."""
    fallback = "xl/worksheets/sheet1.xml"
    try:
        rid = ""
        for node in xml_root(archive.read("xl/workbook.xml")).iter():
            if _local(node.tag) == "sheet":
                rid = next((v for k, v in node.attrib.items() if _local(k) == "id"), "")
                break
        target = ""
        if "xl/_rels/workbook.xml.rels" in archive.namelist():
            for item in xml_root(archive.read("xl/_rels/workbook.xml.rels")):
                if _local(item.tag) == "Relationship" and item.attrib.get("Id") == rid:
                    target = item.attrib.get("Target", "")
        joined = target.lstrip("/")
        if joined.startswith("xl/") and joined in archive.namelist():
            return joined
        joined = f"xl/{joined}" if joined and not joined.startswith("worksheets/") else (joined or fallback)
        return joined if joined in archive.namelist() else fallback
    except (KeyError, ET.ParseError):
        return fallback


def _column_index(ref: str) -> int:
    letters = "".join(ch for ch in (ref or "") if ch.isalpha()).upper()
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch) - 64)
    return max(0, index - 1)


def _number_text(raw: str) -> str:
    """«1200.0» که اکسل برای عددِ صحیح می‌نویسد ← «1200» (وگرنه موجودی «۱۲۰۰.۰» ذخیره می‌شد)."""
    return raw.split(".")[0] if re.fullmatch(r"-?\d+\.0+", raw or "") else (raw or "")


def _check_size(data: bytes) -> None:
    if len(data) > MAX_FILE_BYTES:
        raise ProductImportError(f"فایل بیشتر از {MAX_FILE_BYTES // (1024 * 1024)} مگابایته؛ کوچکش کن.")


def _xlsx_rows(data: bytes) -> list:
    _check_size(data)
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ProductImportError("این فایل یک xlsx معتبر نیست (شاید CSV باشد یا نسخه‌ی قدیمیِ اکسل).") from exc
    with archive:
        entries = archive.infolist()
        if len(entries) > MAX_ZIP_ENTRIES:
            raise ProductImportError("فایلِ اکسل بیش از حد بخشِ داخلی داره؛ فقط یک برگه‌ی ساده بده.")
        if sum(int(info.file_size) for info in entries) > MAX_UNCOMPRESSED_BYTES:
            raise ProductImportError("فایلِ اکسل هنگامِ باز شدن بیش از حد بزرگ می‌شه؛ نسخه‌ی کوچک‌تر بده.")
        shared = _shared_strings(archive)
        try:
            sheet = _first_sheet_name(archive)
        except ET.ParseError as exc:
            raise ProductImportError(f"ساختارِ فایلِ اکسل خرابه: {exc}") from exc
        raw = archive.read(sheet) if sheet in archive.namelist() else None
        if raw is None:
            raise ProductImportError("برگه‌ی اولِ فایلِ اکسل پیدا نشد؛ فایلِ قالبِ خودِ برنامه را باز کن.")
        root = xml_root(raw)
        rows: list = []
        for element in root.iter():
            if _local(element.tag) != "row":
                continue
            cells: dict = {}
            for cell in element:
                if _local(cell.tag) != "c":
                    continue
                kind = cell.get("t") or ""
                value = ""
                if kind == "inlineStr":
                    value = "".join(node.text or "" for node in cell.iter() if _local(node.tag) == "t")
                else:
                    for node in cell:
                        if _local(node.tag) == "v":
                            value = node.text or ""
                            break
                    if kind == "s":
                        position = int(value.strip()) if value.strip().isdigit() else -1
                        value = shared[position] if 0 <= position < len(shared) else ""
                    else:
                        value = _number_text(value)
                cells[_column_index(cell.get("r") or "")] = _CTRL.sub("", value).strip()
            width = max(cells) + 1 if cells else 0
            rows.append([cells.get(i, "") for i in range(width)])
    return rows


def _decode_csv(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1256", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ProductImportError("رمزنگاریِ فایلِ CSV خوانا نیست؛ در اکسل «CSV UTF-8» را انتخاب کن.")


def _csv_rows(data: bytes) -> list:
    _check_size(data)
    text = _decode_csv(data)
    first_line = text.splitlines()[0] if text.splitlines() else ""
    delimiter = max((",", ";", "\t"), key=first_line.count)
    return [list(row) for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


def read_rows(path: Path) -> list:
    """سطرهایِ خامِ فایل (لیستِ لیست)، بدونِ توجه به نوعِ فایل."""
    path = Path(path)
    data = path.read_bytes()
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        return _xlsx_rows(data)
    if suffix in (".csv", ".txt"):
        return _csv_rows(data)
    raise ProductImportError("فقط فایلِ .xlsx یا .csv پشتیبانی می‌شه؛ قالبِ خودِ برنامه را باز کن و پرش کن.")


# ------------------------------------------------------------- تبدیل و اعتبارسنجی ----


def _plain_number(raw: object, field: str, row_number: int) -> int:
    text = header_of(raw)
    for separator in (",", "،", "٬", "_", "ریال"):
        text = text.replace(separator, "")
    text = text.strip()
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError as exc:
        raise RowProblemError(row_number, f"«{field}» عدد نیست: {_clean_cell(raw)!r}") from exc


def _money(raw: object, field: str, row_number: int) -> int:
    value = _plain_number(raw, field, row_number)
    if value < 0:
        raise RowProblemError(row_number, f"«{field}» نمی‌تونه منفی باشه: {_clean_cell(raw)!r}")
    if value > MAX_MONEY:
        raise RowProblemError(row_number, f"«{field}» منطقی نیست (خیلی بزرگه): {_clean_cell(raw)!r}")
    return value


def _stock(raw: object, row_number: int) -> tuple:
    text = header_of(raw)
    if text in _UNLIMITED_WORDS:
        return 0, True
    value = _money(raw, "موجودی", row_number)
    return value, False


def parse_table(rows: list) -> tuple:
    """``([ImportRow], [RowProblem])`` — عنوان‌ها (فارسی یا انگلیسی) را جای‌شان را پیدا می‌کند،
    سطرِ کاملاً خالی را نادیده می‌گیرد و هر سطرِ خراب را با شماره و دلیل برمی‌گرداند."""
    if not rows:
        raise ProductImportError("فایل خالیه.")
    positions: dict = {}
    for index, cell in enumerate(rows[0]):
        key = _header_key(cell)
        if key and key not in positions:
            positions[key] = index
    if "name" not in positions:
        raise ProductImportError("ستونِ «نام» در سطرِ اول فایل نیست؛ با دکمه‌ی «قالبِ اکسل» فایلِ درست را بساز.")
    if "price" not in positions:
        raise ProductImportError("ستونِ «قیمت (ریال)» در سطرِ اول فایل نیست؛ قیمت را کنارِ اسم بگذار.")
    if len(rows) - 1 > MAX_ROWS:
        raise ProductImportError(f"بیش از {MAX_ROWS} سطر هست؛ فایل را تقسیم کن.")

    clean: list = []
    problems: list = []
    for number, raw in enumerate(rows[1:], start=2):
        if not any(_clean_cell(cell) for cell in raw):
            continue
        values = {key: (raw[index] if index < len(raw) else "") for key, index in positions.items()}
        name = _clean_cell(values.get("name", ""))
        if not name:
            problems.append(RowProblem(number, "ستونِ «نام» خالیه."))
            continue
        if len(name) > MAX_NAME:
            problems.append(RowProblem(number, f"نام از {MAX_NAME} حرف بلندتره."))
            continue
        try:
            price = _money(values.get("price", ""), "قیمت", number)
            stock_quantity, unlimited = _stock(values.get("stock", ""), number)
            cost = _money(values.get("cost", ""), "بهای تمام‌شده", number)
        except RowProblemError as exc:
            problems.append(RowProblem(exc.row_number, exc.reason))
            continue
        clean.append(
            ImportRow(
                row_number=number,
                name=name,
                price_irr=price,
                stock_quantity=stock_quantity,
                unlimited_stock=unlimited,
                category=_clean_cell(values.get("category", ""))[:MAX_CATEGORY],
                description=_clean_cell(values.get("description", ""))[:MAX_DESCRIPTION],
                cost_irr=cost,
            )
        )
    return clean, problems


def import_file(store, path: Path) -> tuple:
    """کلِ مسیر: خواندن فایل → اعتبارسنجی → نوشتنِ سطرهایِ سالم. ``([ImportRow], [RowProblem])``."""
    clean, problems = parse_table(read_rows(path))
    if clean:
        store.add_many([
            {"name": row.name, "price_irr": row.price_irr, "stock_quantity": row.stock_quantity,
             "description": row.description, "category": row.category,
             "unlimited_stock": row.unlimited_stock, "cost_irr": row.cost_irr}
            for row in clean
        ])
    return clean, problems


def import_summary(lang: str, added: list, problems: list) -> str:
    """یک خطِ فارسی/انگلیسی برایِ پیامِ پایانیِ واردات."""
    fa = lang != "en"
    if not added and not problems:
        return "هیچ سطری برای وارد کردن نبود." if fa else "There was nothing to import."
    parts = [f"{len(added)} محصول اضافه شد." if fa else f"Added {len(added)} products."]
    if problems:
        shown = "؛ ".join(f"سطرِ {p.row_number}: {p.reason}" for p in problems[:5])
        more = f" (و {len(problems) - 5} سطرِ دیگر)" if len(problems) > 5 else ""
        parts.append((f"{len(problems)} سطر وارد نشد: {shown}{more}") if fa
                     else f"{len(problems)} rows skipped: {shown}{more}")
    return " ".join(parts)
