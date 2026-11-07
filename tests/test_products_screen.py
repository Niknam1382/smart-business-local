"""تست صفحه‌ی محصولات با Page جعلی.

انتخاب عکس (``pick_files``) یه دیالوگ واقعی سیستم‌عامله و دقیقاً مثل
``FilePicker.get_directory_path`` در فاز ۲، فقط روی exe دسکتاپ واقعی
قابل‌تسته — اینجا فقط مسیر «عکس از قبل موجود» (ویرایش محصولی که عکس داره،
حذف عکس) تست می‌شه که کاملاً همگام/بدون دیالوگه.
"""


from fake_page import FakePage, find, fire

from app import theme
from app.core import report_xlsx
from app.core.products import ProductStore
from app.screens import products as products_screen


def make_store(tmp_path):
    return ProductStore(db_path=tmp_path / "p.db")


def test_build_empty_store_no_crash(tmp_path):
    page = FakePage()
    control = products_screen.build(page, "fa", make_store(tmp_path))
    assert control is not None


def test_add_product_flow(tmp_path):
    page = FakePage()
    store = make_store(tmp_path)
    control = products_screen.build(page, "fa", store)

    add_btn = _find_add_button(control)
    fire(add_btn, "on_click")
    assert find(control, "product_form").visible is True

    find(control, "product_name").value = "گوشی تست"
    find(control, "product_price").value = "150000"
    find(control, "product_stock").value = "5"
    find(control, "product_description").value = "توضیح تست"
    save_btn = _find_save_button(control)
    fire(save_btn, "on_click")

    assert find(control, "product_form").visible is False
    products = store.list()
    assert len(products) == 1
    assert products[0].name == "گوشی تست" and products[0].price_irr == 150000 and products[0].stock_quantity == 5


def test_price_accepts_persian_digits_and_commas(tmp_path):
    page = FakePage()
    store = make_store(tmp_path)
    control = products_screen.build(page, "fa", store)
    fire(_find_add_button(control), "on_click")
    find(control, "product_name").value = "محصول"
    find(control, "product_price").value = "۱۵۰,۰۰۰"  # ارقام فارسی + کاما
    find(control, "product_stock").value = "۳"
    fire(_find_save_button(control), "on_click")
    product = store.list()[0]
    assert product.price_irr == 150000 and product.stock_quantity == 3


def test_invalid_price_shows_error_and_keeps_form_open(tmp_path):
    page = FakePage()
    store = make_store(tmp_path)
    control = products_screen.build(page, "fa", store)
    fire(_find_add_button(control), "on_click")
    find(control, "product_name").value = "محصول"
    find(control, "product_price").value = "قیمت نامعتبر"
    find(control, "product_stock").value = "1"
    fire(_find_save_button(control), "on_click")
    assert find(control, "product_form").visible is True
    assert store.list() == []


def test_empty_name_shows_product_error(tmp_path):
    page = FakePage()
    store = make_store(tmp_path)
    control = products_screen.build(page, "fa", store)
    fire(_find_add_button(control), "on_click")
    find(control, "product_name").value = "   "
    find(control, "product_price").value = "1000"
    find(control, "product_stock").value = "1"
    fire(_find_save_button(control), "on_click")
    assert find(control, "product_form").visible is True
    assert store.list() == []


def test_cancel_closes_form_without_saving(tmp_path):
    page = FakePage()
    store = make_store(tmp_path)
    control = products_screen.build(page, "fa", store)
    fire(_find_add_button(control), "on_click")
    find(control, "product_name").value = "نیمه‌کاره"
    fire(find(control, "product_form_cancel"), "on_click")
    assert find(control, "product_form").visible is False
    assert store.list() == []


def test_edit_prefills_form_and_saves_changes(tmp_path):
    page = FakePage()
    store = make_store(tmp_path)
    pid = store.add("اسم قدیمی", 1000, 5, description="قدیمی")
    control = products_screen.build(page, "fa", store)

    fire(find(control, f"edit_{pid}"), "on_click")
    assert find(control, "product_form").visible is True
    assert find(control, "product_name").value == "اسم قدیمی"
    assert find(control, "product_price").value == "1000"
    assert find(control, "product_stock").value == "5"

    find(control, "product_name").value = "اسم جدید"
    find(control, "product_price").value = "2000"
    fire(_find_save_button(control), "on_click")

    updated = store.get(pid)
    assert updated.name == "اسم جدید" and updated.price_irr == 2000


def test_toggle_active_updates_list_and_label(tmp_path):
    page = FakePage()
    store = make_store(tmp_path)
    pid = store.add("محصول", 1000, 5)
    control = products_screen.build(page, "fa", store)

    toggle_btn = find(control, f"toggle_active_{pid}")
    assert toggle_btn.content == "غیرفعال کن"
    fire(toggle_btn, "on_click")
    assert store.get(pid).active is False
    # با show_inactive خاموش، محصول دیگه توی لیست نیست
    assert find(control, f"product_{pid}") is None


def test_show_inactive_switch_reveals_inactive_products(tmp_path):
    page = FakePage()
    store = make_store(tmp_path)
    pid = store.add("محصول", 1000, 5)
    store.set_active(pid, False)
    control = products_screen.build(page, "fa", store)
    assert find(control, f"product_{pid}") is None

    fire(find(control, "show_inactive_switch"), "on_change", value=True)
    assert find(control, f"product_{pid}") is not None
    assert find(control, f"toggle_active_{pid}").content == "فعال کن"


def test_editing_product_with_photo_shows_preview_and_remove_button(tmp_path):
    page = FakePage()
    store = make_store(tmp_path)
    photo = tmp_path / "x.jpg"
    photo.write_bytes(b"fake")
    pid = store.add("محصول", 1000, 5, photo_path=str(photo))
    control = products_screen.build(page, "fa", store)

    fire(find(control, f"edit_{pid}"), "on_click")
    preview = find(control, "photo_preview")
    assert preview.content.src == str(photo)
    assert _find_remove_photo_button(control) is not None


def test_remove_photo_clears_preview_and_deletes_file_on_save(tmp_path, monkeypatch):
    from app.core import products as products_mod

    monkeypatch.setattr(products_mod, "get_app_data_dir", lambda: tmp_path)
    page = FakePage()
    store = make_store(tmp_path)
    photo = tmp_path / "product_photos" / "existing.jpg"
    photo.parent.mkdir(parents=True, exist_ok=True)
    photo.write_bytes(b"fake")
    pid = store.add("محصول", 1000, 5, photo_path=str(photo))

    control = products_screen.build(page, "fa", store)
    fire(find(control, f"edit_{pid}"), "on_click")

    import flet as ft

    remove_btn = _find_remove_photo_button(control)
    assert remove_btn is not None
    fire(remove_btn, "on_click")
    assert isinstance(find(control, "photo_preview").content, ft.Icon), "بعد از حذف باید آیکون جایگزین عکس بشه"
    assert _find_remove_photo_button(control) is None, "دیگه نباید دکمه‌ی حذف عکس نشون داده بشه"

    fire(_find_save_button(control), "on_click")
    assert store.get(pid).photo_path == ""
    assert not photo.exists(), "عکس قدیمی باید از دیسک پاک بشه، نه فقط از رکورد دیتابیس"


def test_builds_in_english(tmp_path):
    page = FakePage()
    store = make_store(tmp_path)
    control = products_screen.build(page, "en", store)
    assert find(control, "product_name").label == "Product name"


# ------------------------------------------------------------------ کمکی


def _find_add_button(control):
    import flet as ft

    found = []

    def walk(c):
        if isinstance(c, ft.Button) and getattr(c, "content", None) is not None:
            inner = c.content
            if hasattr(inner, "controls"):
                for sub in inner.controls:
                    if getattr(sub, "value", None) == "محصول جدید":
                        found.append(c)
        for attr in ("controls", "content"):
            v = getattr(c, attr, None)
            if v is None or isinstance(v, str):
                continue
            for item in v if isinstance(v, list) else [v]:
                walk(item)

    walk(control)
    assert found, "دکمه‌ی «محصول جدید» پیدا نشد"
    return found[0]


def _find_save_button(control):
    import flet as ft

    found = []

    def walk(c):
        if isinstance(c, ft.Button) and getattr(c, "content", None) is not None:
            inner = c.content
            if hasattr(inner, "controls"):
                for sub in inner.controls:
                    if getattr(sub, "value", None) in ("ذخیره کن", "Save"):
                        found.append(c)
        for attr in ("controls", "content"):
            v = getattr(c, attr, None)
            if v is None or isinstance(v, str):
                continue
            for item in v if isinstance(v, list) else [v]:
                walk(item)

    walk(control)
    assert found, "دکمه‌ی ذخیره پیدا نشد"
    return found[0]


def _find_remove_photo_button(control):
    import flet as ft

    found = []

    def walk(c):
        if isinstance(c, ft.TextButton) and getattr(c, "content", None) in ("حذف عکس", "Remove photo"):
            found.append(c)
        for attr in ("controls", "content"):
            v = getattr(c, attr, None)
            if v is None or isinstance(v, str):
                continue
            for item in v if isinstance(v, list) else [v]:
                walk(item)

    walk(control)
    return found[0] if found else None


def test_form_has_no_product_type_and_no_delivery_controls(tmp_path):
    """مدلِ فیزیکیِ خالص: هیچ انتخابِ «نوعِ محصول» و هیچ فیلدِ تحویل/کلیدی در فرم نیست."""
    page = FakePage()
    store = make_store(tmp_path)
    control = products_screen.build(page, "fa", store)
    fire(_find_add_button(control), "on_click")
    for key in ("product_type", "product_delivery_kind", "product_delivery_payload", "product_keys",
                "product_keys_info", "product_pick_file"):
        assert find(control, key) is None, f"کلیدِ {key} هنوز در فرم است"
    for key in ("product_name", "product_price", "product_stock", "product_cost", "product_category", "product_sort"):
        assert find(control, key) is not None


def test_add_and_edit_a_physical_product_with_category_and_sort(tmp_path):
    page = FakePage()
    store = make_store(tmp_path)
    control = products_screen.build(page, "fa", store)
    fire(_find_add_button(control), "on_click")
    find(control, "product_name").value = "چای"
    find(control, "product_price").value = "۲۸۰٬۰۰۰"
    find(control, "product_stock").value = "12"
    find(control, "product_category").value = "نوشیدنی"
    find(control, "product_sort").value = "3"
    find(control, "product_cost").value = "190000"
    fire(_find_save_button(control), "on_click")
    product = store.list()[0]
    assert (product.name, product.price_irr, product.stock_quantity, product.category, product.sort_order, product.cost_irr) == (
        "چای", 280000, 12, "نوشیدنی", 3, 190000)

    fire(find(control, f"edit_{product.id}"), "on_click")
    assert (find(control, "product_name").value, find(control, "product_category").value,
            find(control, "product_sort").value) == ("چای", "نوشیدنی", "3")


def test_unlimited_switch_hides_the_stock_field_and_saves_unlimited(tmp_path):
    page = FakePage()
    store = make_store(tmp_path)
    control = products_screen.build(page, "fa", store)
    fire(_find_add_button(control), "on_click")
    find(control, "product_name").value = "نان"
    find(control, "product_price").value = "45000"
    unlimited = find(control, "product_unlimited")
    fire(unlimited, "on_change", True)
    assert find(control, "product_stock").visible is False
    fire(_find_save_button(control), "on_click")
    [product] = [p for p in store.list() if p.name == "نان"]
    assert product.unlimited_stock is True and product.stock_quantity == 0 and product.in_stock


def test_bad_sort_number_is_shown_and_nothing_is_saved(tmp_path):
    page = FakePage()
    store = make_store(tmp_path)
    control = products_screen.build(page, "fa", store)
    fire(_find_add_button(control), "on_click")
    find(control, "product_name").value = "چای"
    find(control, "product_price").value = "280000"
    find(control, "product_sort").value = "سه"
    fire(_find_save_button(control), "on_click")
    assert store.list() == []
    assert "ترتیبِ نمایش" in find(control, "product_form_error").value


# ---------------------------------------------------- N2: محصولِ نمونه فقط opt-in ----

def test_app_starts_with_no_products_and_sample_is_only_added_on_request(tmp_path):
    store = make_store(tmp_path)
    page = FakePage()
    control = products_screen.build(page, "fa", store)
    assert store.list() == []  # نصبِ تازه کاملاً خالی است؛ هیچ محصولی خودکار ساخته نمی‌شه
    button = find(control, "product_add_sample")
    assert button is not None and "نمونه" in button.content
    fire(button, "on_click")
    [sample] = store.list()
    assert sample.name == "محصولِ نمونه" and sample.price_irr == 1_000_000 and sample.stock_quantity == 10
    assert find(control, "product_add_sample") is None  # دیگه خالی نیست ⇒ دکمه برداشته می‌شه
    fire(button, "on_click")  # کلیکِ بیات هم فقط یک محصولِ دیگه می‌سازه؛ هیچ داده‌ی پنهانی نیست
    assert len(store.list()) == 2


def test_sample_button_is_not_shown_when_products_exist(tmp_path):
    store = make_store(tmp_path)
    store.add("کالا", 1000, 1)
    control = products_screen.build(FakePage(), "fa", store)
    assert find(control, "product_add_sample") is None


def test_sample_product_is_localized(tmp_path):
    store = make_store(tmp_path)
    control = products_screen.build(FakePage(), "en", store)
    fire(find(control, "product_add_sample"), "on_click")
    assert store.list()[0].name == "Sample product"


# ------------------------------------------------- گزارشِ اکسل/PDF (بخش ۸ِ master prompt) ----

def test_excel_and_pdf_report_buttons_write_files(tmp_path, monkeypatch):
    """«خروجِ اکسل»/«خروجِ PDF» کارنامه‌ی انبار را در ``<داده>/reports`` می‌سازند، پوشه را باز
    می‌کنند و یادداشتِ پایینی را نشان می‌دهند (همان جایی که قالبِ اکسل پیام می‌دهد)."""
    store = make_store(tmp_path)
    store.add("شام‌خورِ خانوادگی", 450_000, 12)
    opened: list = []
    monkeypatch.setattr("app.screens.products.common.open_folder", lambda p: opened.append(str(p)) or True)
    control = products_screen.build(FakePage(), "fa", store)
    for key, suffix in (("product_export_xlsx", ".xlsx"), ("product_export_pdf", ".pdf")):
        button = find(control, key)
        assert button is not None, key
        fire(button, "on_click")
        assert any(p.suffix == suffix for p in report_xlsx.reports_dir().glob("*")), key
    assert opened == [str(report_xlsx.reports_dir())] * 2
    note = find(control, "product_import_note")
    assert note.visible and "سطری ساخته شد" in note.value and str(report_xlsx.reports_dir()) in note.value
    path = sorted(report_xlsx.reports_dir().glob("*.xlsx"))[-1]
    _p, header, body = report_xlsx.read_report(path)
    assert len(body) == 1 and header[0] == "نام" and body[0][2] == "450000"  # پولِ خامِ عددی در اکسل


def test_report_buttons_respect_show_inactive_switch(tmp_path, monkeypatch):
    """سوییچِ «نمایشِ غیرفعال‌ها» همان چیزی است که کاربر می‌بیند؛ گزارش هم همان را می‌فرستد."""
    monkeypatch.setattr("app.screens.products.common.open_folder", lambda p: True)
    store = make_store(tmp_path)
    pid = store.add("فعال", 1000, 2)
    store.add("دیگر", 2000, 3)
    store.set_active(pid, False)
    control = products_screen.build(FakePage(), "fa", store)
    fire(find(control, "product_export_xlsx"), "on_click")
    _p, _h, body = report_xlsx.read_report(sorted(report_xlsx.reports_dir().glob("*.xlsx"))[-1])
    assert [row[0] for row in body] == ["دیگر"]
    fire(find(control, "show_inactive_switch"), "on_change", True)
    fire(find(control, "product_export_xlsx"), "on_click")
    _p, _h, body = report_xlsx.read_report(sorted(report_xlsx.reports_dir().glob("*.xlsx"))[-1])
    assert sorted(row[0] for row in body) == ["دیگر", "فعال"]


def test_report_button_without_products_shows_persian_error(tmp_path, monkeypatch):
    monkeypatch.setattr("app.screens.products.common.open_folder", lambda p: True)
    control = products_screen.build(FakePage(), "fa", make_store(tmp_path))
    fire(find(control, "product_export_xlsx"), "on_click")
    note = find(control, "product_import_note")
    assert note.value == report_xlsx.EMPTY_ERROR and note.visible and note.color == theme.DANGER
    assert list(report_xlsx.reports_dir().glob("*.xlsx")) == []
