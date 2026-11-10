"""قلم ۸ (باگِ گزارش‌شدهٔ مالک): شخصی‌سازیِ فاکتور.

چه چیزی سنجیده می‌شود (به همان ترتیبِ خواسته):
۱) نامِ فروشگاه با زنجیره‌یِ «invoice_seller_name ← user_name ← invoice_seller_fallback ← «فروشگاه»»
   یک‌جا حل می‌شود و در نوارِ سربرگ، پابرگِ شماره‌یِ صفحه و کنارِ QR *یکی* است — هیچ‌وقت جایِ نام،
   عنوانِ «فاکتور فروش» چاپ نمی‌شود و باندِ خالی نداریم.
۲) بلوکِ «مشخصات خریدار» همیشه هست: هفتِ ردیفِ مهم با «—» برایِ مقداری که نیست، در ستونِ **چپِ**
   صفحه، و کارتِ شماره/تاریخ در ستونِ **راست** (چیدمان از رویِ مستطیلِ واقعاً کشیده‌شده سنجیده می‌شود).
۳) متن‌هایِ مهمِ فاکتور (سلبِ مسئولیت، تشکر، پاورقی و برچسب‌هایِ اصلی) قابلِ شخصی‌سازی‌اند،
   پاک‌سازی می‌شوند، در بایت‌هایِ PDF می‌نشینند، در snapshot منجمد می‌شوند و خروجی قطعی است.
۴) «فاکتورِ تستی» با همانِ مسیرِ رندرِ فاکتورِ واقعی PDF می‌سازد؛ بدونِ دیتابیس، بدونِ شمارنده،
   بدونِ هیچ پیامی به مشتری و idempotent.

سنجشِ متن همانِ روشِ ``tests/test_invoice_service.py`` است (pypdf ترتیبِ راست‌به‌چپ را کامل
نمی‌دارد، پس واژه‌ها سنجیده می‌شوند نه عبارتِ کامل)؛ سنجشِ *چیدمان* با رویشِ متدهایِ fpdf2
(«چه چیزی در کدام x/y نوشته و کشیده شد») است، نه حدسِ عددی.
"""

import io
from pathlib import Path

import fpdf as _fpdf
import pytest

from app.core import invoice_pdf, invoice_service, invoices, jalali
from app.core.invoices import ANON_NAME, invoice_labels_of, seller_name_of
from tests.test_finance import Rig
from tests.test_invoice_service import Fx
from tests.test_invoices import NOW, S

pypdf = pytest.importorskip("pypdf")

BAND_MAX_Y = 30.0  # نوارِ رنگیِ سربرگ از y=12 تا ۳۲ میلی‌متر است؛ نامِ فروشگاه باید داخلِ همین بازه باشد
MID = 12.0 + 93.0  # خطِ وسطِ ستونِ چاپِ A4 (مارجین ۱۲ + عرضِ مفید ۱۸۶ ÷ ۲)
ROWS = ("خریدار", "تلفن", "نشانی", "سفارش", "روش پرداخت", "کد پیگیری/تراکنش", "شناسه مشتری")


@pytest.fixture
def fx(tmp_path):
    return Fx(tmp_path)


def text_of(data: bytes) -> str:
    return "".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(data)).pages)


def spy_cells(monkeypatch) -> list:
    """هر ``cell``ِ رسم‌شده به شکلِ ``(متن, x, y)`` — «چه چیزی کجا نوشته شد»."""
    calls: list = []
    real = _fpdf.FPDF.cell

    def wrapper(self, *args, **kwargs):
        text = kwargs.get("text", args[2] if len(args) > 2 else "")
        calls.append((str(text), float(self.x), float(self.y)))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(_fpdf.FPDF, "cell", wrapper)
    return calls


def spy_rects(monkeypatch) -> list:
    """هر ``rect``ِ رسم‌شده به شکلِ ``(x, y, w, h)`` — مستطیلِ پنلِ خریدار و کارتِ شماره/تاریخ."""
    calls: list = []
    real = _fpdf.FPDF.rect

    def wrapper(self, *args, **kwargs):
        if len(args) >= 4:
            calls.append(tuple(float(a) for a in args[:4]))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(_fpdf.FPDF, "rect", wrapper)
    return calls


def band_texts(cells: list) -> list:
    return [text for text, _x, y in cells if y < BAND_MAX_Y]


def row_values(inv, order_label: str = "", ref_number: str = "") -> dict:
    return {name: value for name, value, _bold in invoice_pdf._InvoicePDF(inv).buyer_rows(order_label, ref_number)}


# ═══════════════════════════ ۱) نامِ فروشگاه: یک زنجیره، یک نتیجه ═══════════════════════════


def test_seller_name_chain_resolves_in_one_function():
    assert seller_name_of(S(invoice_seller_name="فروشگاه نمونه", user_name="مریم")) == "فروشگاه نمونه"
    assert seller_name_of(S(invoice_seller_name="", user_name="فروشگاهِ مریم")) == "فروشگاهِ مریم"
    assert seller_name_of(S(invoice_seller_name="", user_name="", invoice_seller_fallback="خانه‌یِ چوب")) == "خانه‌یِ چوب"
    # همه خالی ⇒ نوشتهٔ صریحِ «فروشگاه» (نه عنوانِ فاکتور، نه رشتهٔ خالی)
    assert seller_name_of(S(invoice_seller_name="", user_name="", invoice_seller_fallback="")) == "فروشگاه"
    assert seller_name_of(S()) == "فروشگاه نمونه"  # تنظیماتِ بدونِ user_name هم کار می‌کند
    assert seller_name_of(None) == "فروشگاه"  # هیچ تنظیماتی نباشد هم باند خالی نمی‌ماند


def test_pdf_seller_name_never_leaves_an_empty_band():
    assert invoice_pdf.seller_name({"name": "فروشگاهِ علی"}) == "فروشگاهِ علی"
    assert invoice_pdf.seller_name({"name": "\U0001F600"}) == "فروشگاه"  # چیزی که فونت ندارد چاپ شدنی نیست
    assert invoice_pdf.seller_name({"name": "\u202e"}) == "فروشگاه"  # فقط نویسهٔ جهتِ مخرب
    assert invoice_pdf.seller_name({"name": "", "fallback_name": "نامِ جایگزین"}) == "نامِ جایگزین"
    assert invoice_pdf.seller_name({"name": "\U0001F600", "fallback_name": "نامِ جایگزین"}) == "نامِ جایگزین"
    assert invoice_pdf.seller_name({}) == "فروشگاه"
    assert invoice_pdf.seller_name({"name": "فروشگاهِ علی", "fallback_name": "بی‌استفاده"}) == "فروشگاهِ علی"


@pytest.mark.parametrize(
    "settings,expected",
    [
        ({"invoice_seller_name": "", "user_name": "فروشگاهِ مریم"}, "فروشگاهِ مریم"),
        ({"invoice_seller_name": "", "user_name": "", "invoice_seller_fallback": "خانه‌یِ چوب"}, "خانه‌یِ چوب"),
        ({"invoice_seller_name": "", "user_name": "", "invoice_seller_fallback": ""}, "فروشگاه"),
    ],
)
def test_brand_band_page_stamp_and_qr_all_use_the_resolved_name(tmp_path, monkeypatch, settings, expected):
    """باگِ مالک: «اسمِ فروشگاه خالی است» — جایِ نام، «فاکتور فروش» در نوارِ رنگی می‌نشست."""
    fx = Fx(tmp_path, **settings)
    inv = fx.svc.issue(fx.order())
    cells = spy_cells(monkeypatch)
    data = invoice_pdf.render(fx.svc.store.get(inv.id))
    assert expected in band_texts(cells), band_texts(cells)
    assert not any("فاکتور فروش" in text for text in band_texts(cells))  # عنوان جایِ نام نمی‌آید
    full = text_of(data)
    assert full.count(expected) >= 3  # نوارِ سربرگ + کنارِ QR + پابرگِ شماره‌یِ صفحه
    assert expected in text_of(fx.svc.path_of(inv).read_bytes())  # همان نام در فایلِ سرویس هم هست


# ═══════════════════ ۲) بلوکِ «مشخصات خریدار»: همیشه مرئی، همیشه در ستونِ چپ ═══════════════════


def buyer_only_phone(fx):
    pid = fx.rig.product("کفشِ نمونه", 100_000, 10)
    oid = fx.rig.confirmed([(pid, 1)], chat="55", name="", customer_phone="09120000000")
    return fx.svc.issue(fx.rig.orders.get(oid))


def test_buyer_rows_keep_every_important_field_even_when_empty(tmp_path):
    fx = Fx(tmp_path)
    inv = buyer_only_phone(fx)
    assert inv.buyer["name"] == ""  # خریدار بی‌نام است — همان حالتِ گزارش‌شده
    assert list(row_values(inv, f"سفارش #{inv.order_id}")) == list(ROWS)
    values = row_values(inv, f"سفارش #{inv.order_id}")
    assert values["تلفن"] == jalali.fa_digits("09120000000")  # فقط تلفن را داریم، و همان کامل چاپ می‌شود
    assert values["خریدار"] == "—" and values["نشانی"] == "—"  # ردیف حذف نشده، «—» خورده است
    assert values["سفارش"] == f"سفارش #{inv.order_id}" and values["روش پرداخت"] == "کارت‌به‌کارت"
    assert values["شناسه مشتری"] == jalali.fa_digits("55")  # ارقام هم مثلِ بقیهٔ فاکتور فارسی‌اند
    text = text_of(invoice_pdf.render(inv))
    assert "مشخصات خریدار" in text and text.count("—") >= 3
    for caption in ROWS:
        assert caption.split("/")[0] in text, caption


def test_missing_snapshot_fields_still_print_placeholder_rows(tmp_path):
    """فاکتورهایِ قدیمی که snapshotشان این کلیدها را ندارد هم ردیفِ کامل دارند (نه حذفِ ردیف)."""
    fx = Fx(tmp_path)
    inv = fx.svc.issue(fx.order())
    inv.buyer = {"name": "علی رضایی"}  # snapshotِ نسخهٔ ۱: فقط نام
    values = row_values(inv)
    assert values["خریدار"] == "علی رضایی"
    assert values["روش پرداخت"] == "کارت‌به‌کارت"  # روشِ پرداخت از ستونِ خودِ فاکتور می‌آید، نه از خریدار
    for caption in ROWS[1:]:
        if caption == "روش پرداخت":
            continue
        assert values[caption] == "—", caption


def test_buyer_panel_is_the_left_half_and_the_number_card_the_right(tmp_path, monkeypatch):
    """باگِ مالک: «مشخصات کاربر در بالا سمتِ چپ نوشته نمی‌شود» — چیدمانِ واقعی سنجیده می‌شود."""
    fx = Fx(tmp_path)
    inv = buyer_only_phone(fx)
    drawer = invoice_pdf._InvoicePDF(inv)
    geo, width = drawer.meta_geometry(), drawer.w
    rects = spy_rects(monkeypatch)
    invoice_pdf.render(inv)
    panel = [r for r in rects if r[0] == pytest.approx(geo["panel_x"]) and r[2] == pytest.approx(geo["panel_w"])]
    card = [r for r in rects if r[0] == pytest.approx(geo["card_x"]) and r[2] == pytest.approx(geo["card_w"])]
    assert panel and card, rects
    px, py, pw, ph = panel[0]
    cx, cy, cw, ch = card[0]
    assert py == cy  # هر دو از یک ارتفاع شروع می‌شوند: یکِ بلوک، دو ستون
    assert px == pytest.approx(12.0) and pw < width / 2  # پنل از مارجینِ چپ و کم‌تر از نصفِ عرضِ مفید
    assert px + pw < MID <= cx  # تماماً در نیمهٔ چپ؛ کارت از خطِ وسط به بعد (نیمهٔ راست)
    assert cx + cw == pytest.approx(12.0 + width) and cx + cw < 210.0  # تا لبهٔ راستِ ستونِ چاپ
    assert ph > 0 and ch == pytest.approx(invoice_pdf._META_MIN_H)
    # برچسب به لبهٔ راستِ پنل چسبیده و مقدار در سمتِ چپِ آن (ترتیبِ راست‌به‌چپِ خواندن)
    assert geo["label_x"] + geo["label_w"] == pytest.approx(px + pw - invoice_pdf._META_PAD)
    assert geo["value_x"] + geo["value_w"] < geo["label_x"]  # ستونِ مقدار هیچ‌وقت زیرِ برچسب نمی‌رود


def test_anonymized_buyer_prints_the_forgotten_marker_explicitly(tmp_path):
    fx = Fx(tmp_path)
    inv = fx.svc.issue(fx.order(name="مریم"))
    fx.rig.orders.anonymize_chat("telegram", "1")
    gone = fx.svc.store.get(inv.id)
    assert gone.anonymized and gone.buyer["name"] == ANON_NAME
    values = row_values(gone)
    assert values["خریدار"] == ANON_NAME
    for caption in ROWS[1:]:
        if caption == "روش پرداخت":  # روشِ پرداخت دادهٔ هویتی نیست و با /forget می‌ماند
            continue
        assert values[caption] == "—", caption  # /forget هیچ ردیفی را از پنل بیرون نمی‌اندازد
    text = text_of(invoice_pdf.render(gone))
    assert "مشخصات خریدار" in text and "حذف‌شده" in text


def test_snapshot_carries_the_extra_buyer_fields_and_anonymize_blanks_them(tmp_path):
    """ردیف‌ها باید دادهٔ واقعی داشته باشند: کد رهگیریِ مرسوله و شناسهٔ مشتری هم در snapshot می‌آیند."""
    rig = Rig(tmp_path)
    pid = rig.product("کتاب", 50_000, 5)
    oid = rig.confirmed([(pid, 1)], chat="77", name="رضا", shipping=("پست پیشتاز", 12_000))
    rig.orders.set_fulfillment(oid, "preparing", tracking_code="TR-9")  # حرکتِ وضعیتِ ارسال رو به جلو است
    store = invoice_service.InvoiceStore(rig.orders)
    inv = store.issue_sale(rig.orders.get(oid), S(), now=NOW)
    assert inv.buyer["tracking"] == "TR-9" and inv.buyer["buyer_id"] == "77"
    assert inv.buyer["shipping_method"] == "پست پیشتاز"
    values = row_values(inv)
    assert list(values) == list(ROWS) + ["کد رهگیری مرسوله", "روش ارسال"]  # ردیف‌هایِ زمینه‌ای فقط وقتی هستن که مقدار باشن
    assert values["کد رهگیری مرسوله"] == jalali.fa_digits("TR-9") and values["روش ارسال"] == "پست پیشتاز"
    store.anonymize_orders([oid])
    gone = store.get(inv.id)
    assert gone.buyer["name"] == ANON_NAME
    assert all(not gone.buyer.get(key) for key in ("tracking", "buyer_id", "shipping_method", "phone"))
    assert list(row_values(gone)) == list(ROWS)  # پنل بعد از /forget هم کامل و بدونِ دادهٔ هویتی است
    assert "مشخصات خریدار" in text_of(invoice_pdf.render(gone))


# ═════════════════════════════ ۳) متن‌هایِ مالک ═════════════════════════════


def test_only_the_important_labels_are_editable():
    """سقفِ شخصی‌سازی = «متن‌هایِ مهم»؛ بقیهٔ برچسب‌ها (ستون‌هایِ جدول، مالیات، …) دست‌نخورده می‌مانند."""
    assert set(invoices.EDITABLE_LABEL_KEYS) == {"sale", "credit", "buyer", "col_item", "final", "date", "number"}
    assert all(key in invoice_pdf.LABELS for key in invoices.EDITABLE_LABEL_KEYS)
    overrides = {invoices.LABEL_PREFIX + key: "متنِ مالک" for key in invoices.EDITABLE_LABEL_KEYS}
    overrides[invoices.LABEL_PREFIX + "subtotal"] = "دست‌کاریِ جمع"
    labels = invoice_labels_of(S(bot_texts={"fa": overrides}))
    assert set(labels["fa"]) == set(invoices.EDITABLE_LABEL_KEYS)  # کلیدِ غیرمجاز رد می‌شود
    assert all(labels["fa"][key] == "متنِ مالک" for key in labels["fa"])


def personalized_fx(tmp_path, **extra):
    texts = {"fa": {"invoice.label.sale": "صورتحسابِ فروش", "invoice.label.final": "مبلغ قابل پرداخت",
                    "invoice.label.buyer": "مشتری", "invoice.label.number": "کد فاکتور", "invoice.label.date": "روز",
                    "invoice.label.col_item": "شرح سفارش", "invoice.label.credit": "صورتحسابِ برگشتی"},
             "en": {"invoice.label.sale": "Custom receipt"}}
    return Fx(tmp_path, bot_texts=texts, invoice_disclaimer="این برگه فقط سرگرم‌کننده است.",
              invoice_thanks="ممنون از خرید شما!", invoice_footer="پاورقیِ فروشگاه", **extra)


def test_owner_texts_replace_the_built_in_wording(tmp_path):
    fx = personalized_fx(tmp_path)
    inv = fx.svc.issue(fx.order())
    assert inv.seller["labels"]["fa"]["sale"] == "صورتحسابِ فروش"  # در snapshot منجمد شد
    assert (inv.seller["thanks"], inv.seller["disclaimer"], inv.seller["footer"]) == (
        "ممنون از خرید شما!", "این برگه فقط سرگرم‌کننده است.", "پاورقیِ فروشگاه")
    text = text_of(fx.svc.path_of(inv).read_bytes())
    for wanted in ("صورتحسابِ فروش", "مبلغ قابل پرداخت", "شرح سفارش", "کد فاکتور", "روز",
                   "ممنون از خرید شما", "پاورقیِ فروشگاه", "این برگه فقط سرگرم‌کننده است"):
        assert wanted in text, wanted
    assert "فاکتور فروش" not in text  # عنوانِ جایگزین‌شده دیگر جایی نمی‌آید
    assert "مودیان" not in text  # سلبِ مسئولیتِ پیش‌فرض با متنِ مالک عوض شد


def test_empty_personal_texts_keep_the_default_wording(tmp_path):
    fx = Fx(tmp_path)
    inv = fx.svc.issue(fx.order())
    body = fx.svc.store.get(inv.id)
    assert (body.seller["thanks"], body.seller["disclaimer"], body.seller["labels"]) == ("", "", {})
    text = text_of(fx.svc.path_of(inv).read_bytes())
    assert "فاکتور فروش" in text and "مودیان" in text  # خالی = همان متنِ امنِ برنامه


def test_personal_texts_are_deterministic_and_frozen_in_the_snapshot(tmp_path):
    fx = personalized_fx(tmp_path)
    first = fx.svc.issue(fx.order())
    data = invoice_pdf.render(fx.svc.store.get(first.id))
    assert data == invoice_pdf.render(fx.svc.store.get(first.id))  # همان ورودی ⇒ همان بایت
    assert data.startswith(b"%PDF-")
    # تغییرِ تنظیمات بعد از صدور، فاکتورِ صادرشده را عوض نمی‌کند (snapshot یخ‌زده است)
    fx.settings.invoice_thanks, fx.settings.invoice_disclaimer = "متنِ تازه", "متنِ تازه‌یِ دیگر"
    fx.settings.bot_texts = {"fa": {"invoice.label.sale": "صورتحسابِ جدید"}}
    assert invoice_pdf.render(fx.svc.store.get(first.id)) == data
    # و فاکتورِ *بعدی* همان متنِ تازه را می‌گیرد
    second = fx.svc.issue(fx.order(chat="2"))
    assert second.seller["labels"]["fa"]["sale"] == "صورتحسابِ جدید"
    second_text = text_of(invoice_pdf.render(fx.svc.store.get(second.id)))
    assert "متنِ تازه" in second_text and "صورتحسابِ جدید" in second_text
    assert "ممنون از خرید شما" not in second_text


def test_unprintable_personal_texts_are_cleaned_not_trusted(tmp_path):
    fx = Fx(tmp_path, invoice_seller_name="فروشگاه\u202e نمونه \U0001F600", invoice_thanks="ممنون\u202c \x00",
            invoice_disclaimer="متن\x00ِ خراب\u202e", bot_texts={"fa": {"invoice.label.buyer": "خرید\u202eار \U0001F600"}})
    issued = fx.svc.issue(fx.order())
    seller = fx.svc.store.get(issued.id).seller
    for value in (seller["name"], seller["thanks"], seller["disclaimer"], seller["labels"]["fa"]["buyer"]):
        assert "\x00" not in value and "\u202e" not in value and "\u202c" not in value  # کنترلی/bidi در snapshot نمی‌ماند
    text = text_of(invoice_pdf.render(fx.svc.store.get(issued.id)))
    assert "\U0001F600" not in text and "\x00" not in text  # ایموجیِ متنِ مالک در PDF جایی ندارد
    name = invoice_pdf.seller_name(seller)
    assert "فروشگاه" in name and "\U0001F600" not in name  # و باند هم خالی/بی‌نام نمی‌ماند


def test_hostile_label_overrides_are_dropped_or_cleaned(tmp_path):
    hostile = S(bot_texts={"fa": {"invoice.label.buyer": "خرید\u202eار \U0001F600", "invoice.label.vat": "دست‌کاریِ مالیات",
                                  "invoice.label.number": 123, "cart.empty": "متنِ ربات",
                                  "invoice.label.sale": "ب" * 200},
                            "en": "خراب", "xx": {"invoice.label.sale": "زبانِ نامعلوم"}})
    labels = invoice_labels_of(hostile)
    assert list(labels) == ["fa"]  # زبانِ ناشناخته/قالبِ غلط دور ریخته می‌شود
    assert set(labels["fa"]) == {"buyer", "sale"}  # کلیدِ غیرمجازِ برچسب و مقدارِ غیررشته‌ای رد می‌شوند
    assert labels["fa"]["buyer"] == "خرید ار \U0001F600"  # جایِ نویسهٔ جهت فاصله می‌نشیند
    assert len(labels["fa"]["sale"]) == 60  # طول کران‌دار است
    assert invoice_pdf.label("buyer", "fa", labels) == "خرید ار"  # فونتِ Vazirmatn ایموجی را چاپ نمی‌کند
    assert invoice_pdf.label("vat", "fa", labels) == "که از این مبلغ، مالیات بر ارزش افزوده"  # پیش‌فرض می‌ماند
    assert invoice_pdf.label("sale", "en", labels) == "Sales invoice"  # overrideِ فارسی رویِ انگلیسی اثر ندارد
    fx = Fx(tmp_path)
    inv = fx.svc.issue(fx.order())
    inv.seller = dict(inv.seller, labels=labels)
    assert "خرید ار" in text_of(invoice_pdf.render(inv))  # رندر با snapshotِ دشمن نمی‌شکند


def test_personal_texts_keep_the_bilingual_behaviour(tmp_path):
    fx = personalized_fx(tmp_path, language="en")
    inv = fx.svc.issue(fx.order(name="Mary"))
    assert inv.lang == "en"
    text = text_of(invoice_pdf.render(inv))
    assert "Custom receipt" in text and "Sales invoice" not in text  # overrideِ همان زبان
    assert "صورتحسابِ فروش" not in text  # فارسی جایی نمی‌آید
    assert "Items total" in text and "Final amount" in text  # بقیه دوزبانه می‌ماند
    fa_dir = tmp_path / "fa"
    fa_dir.mkdir()
    fx_fa = personalized_fx(fa_dir)
    assert "صورتحسابِ فروش" in text_of(fx_fa.svc.path_of(fx_fa.svc.issue(fx_fa.order())).read_bytes())


def test_english_invoice_without_overrides_uses_english_defaults(tmp_path):
    fx = Fx(tmp_path, language="en")
    inv = fx.svc.issue(fx.order(name="Mary"))
    text = text_of(invoice_pdf.render(inv))
    assert "Sales invoice" in text and "Customer details" in text and "مشخصات خریدار" not in text


def test_invoice_text_copy_follows_the_personalized_labels_and_name(tmp_path):
    fx = personalized_fx(tmp_path, invoice_seller_name="", user_name="فروشگاهِ مریم")
    inv = fx.svc.issue(fx.order())
    message = invoice_service.invoice_text(fx.svc.store.get(inv.id))
    assert "صورتحسابِ فروش" in message and "مبلغ قابل پرداخت" in message
    assert "فروشگاهِ مریم" in message and "فاکتور فروش" not in message
    assert "ممنون از خرید شما" in message  # نسخهٔ متنی هم متنِ تشکرِ مالک را می‌گیرد


# ══════════════════════════════ ۴) فاکتورِ تستی ══════════════════════════════


def test_preview_invoice_is_synthetic_but_uses_the_real_math():
    settings = S(invoice_vat_enabled=True, invoice_vat_rate_bp=900, invoice_seller_name="فروشگاهِ آزمون")
    inv = invoice_service.preview_invoice(settings, issued_ts=NOW)
    assert inv.number == invoice_service.PREVIEW_NUMBER and inv.id == 0 and inv.seller["preview"] is True
    assert inv.lines and all(int(i["total_irr"]) == int(i["qty"]) * int(i["unit_irr"]) for i in inv.lines)
    assert inv.subtotal_irr - inv.discount_irr + inv.shipping_irr == inv.total_irr  # همان هویتِ ریاضی
    assert inv.discount_irr == invoice_service.PREVIEW_DISCOUNT_IRR
    assert inv.shipping_irr == invoice_service.PREVIEW_SHIPPING_IRR
    assert inv.tax_irr > 0 and inv.tax_irr < inv.total_irr  # مالیات روشن ⇒ خطِ اطلاع‌رسانی
    assert inv.seller["name"] == "فروشگاهِ آزمون" and "نمونه" in inv.buyer["name"]
    assert all("نمونه" in item["name"] for item in inv.lines)  # اقلام هم نمونه‌اند
    assert invoice_service.preview_invoice(S(), lang="en").lang == "en"
    assert invoice_service.preview_invoice(S(language="en")).lang == "en"
    assert invoice_service.preview_invoice(S()).seller["preview"] is True


def test_preview_writes_a_pdf_without_databases_or_sending_anything(fx, tmp_path):
    assert fx.svc.store.list() == []
    docs_before, texts_before = len(fx.docs), len(fx.texts)
    path = fx.svc.preview()
    data = path.read_bytes()
    assert path == Path(tmp_path) / "inv" / "TEST-000001.pdf"  # همان پوشهٔ PDFها، نامِ بی‌خطر
    assert data.startswith(b"%PDF-") and len(data) > 2000
    text = text_of(data)
    assert "نمونه" in text and "مشتریِ" in text  # علامتِ «نمونه» رویِ فاکتور و در نامِ خریدار
    assert "فروشگاه نمونه" in text  # هویتِ فروشگاه از تنظیماتِ جاری
    assert "هزینه ارسال" in text and "جمع اقلام" in text and "مبلغ نهایی" in text
    assert fx.svc.store.list() == []  # هیچ ردیفی در دیتابیس ساخته نشد
    assert len(fx.docs) == docs_before and len(fx.texts) == texts_before and fx.att == []  # هیچ پیامی نرفت
    assert fx.svc.store.sale_missing_for_confirmed() == []  # صفِ صدور هم دست‌نخورده
    assert fx.rig.orders.connection().execute("SELECT COUNT(*) n FROM invoice_counters").fetchone()["n"] == 0


def test_preview_is_idempotent_and_deterministic(fx):
    data = fx.svc.preview_bytes(now=NOW)
    first = fx.svc.preview(now=NOW)
    second = fx.svc.preview(now=NOW)
    assert first == second and first.read_bytes() == data == fx.svc.preview_bytes(now=NOW)
    assert list(first.parent.glob("TEST-000001.pdf")) == [first]  # یکی می‌ماند، فایلِ تکراری ساخته نمی‌شود
    assert not list(first.parent.glob("*.tmp"))  # فایلِ موقتِ نوشتن روی دیسک نمی‌ماند
    assert fx.docs == [] and fx.texts == []
    real = fx.svc.ensure_pdf(fx.svc.issue(fx.order()))  # فاکتورِ واقعیِ همان مشتری
    assert real != first and real.name.startswith("F1405")
    assert fx.svc.preview(now=NOW).read_bytes() == data  # فاکتورِ واقعی، پیش‌نمایش را عوض نکرد
    assert fx.svc.store.list()[0].seller.get("preview") is None  # فاکتورِ واقعی علامتِ نمونه ندارد


def test_preview_respects_the_owners_personal_texts(fx):
    fx.settings.invoice_thanks, fx.settings.invoice_disclaimer = "خوشحال شدیم", "سلبِ مسئولیتِ من"
    fx.settings.bot_texts = {"fa": {"invoice.label.sale": "صورتحساب"}}
    fx.settings.invoice_vat_enabled, fx.settings.invoice_vat_rate_bp = True, 1000
    text = text_of(fx.svc.preview_bytes())
    for wanted in ("خوشحال شدیم", "سلبِ مسئولیتِ من", "صورتحساب", "که از این مبلغ، مالیات"):
        assert wanted in text, wanted
    assert "فاکتور فروش" not in text and "مودیان" not in text
