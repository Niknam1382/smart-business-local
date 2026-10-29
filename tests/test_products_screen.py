"""تست صفحه‌ی محصولات با Page جعلی.

انتخاب عکس (``pick_files``) یه دیالوگ واقعی سیستم‌عامله و دقیقاً مثل
``FilePicker.get_directory_path`` در فاز ۲، فقط روی exe دسکتاپ واقعی
قابل‌تسته — اینجا فقط مسیر «عکس از قبل موجود» (ویرایش محصولی که عکس داره،
حذف عکس) تست می‌شه که کاملاً همگام/بدون دیالوگه.
"""


from fake_page import FakePage, find, fire

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


def test_digital_keys_product_via_form(tmp_path):
    page = FakePage()
    store = make_store(tmp_path)
    control = products_screen.build(page, "fa", store)
    fire(_find_add_button(control), "on_click")
    find(control, "product_name").value = "لایسنس"
    find(control, "product_price").value = "900"
    type_dd = find(control, "product_type")
    type_dd.value = "digital"
    fire(type_dd, "on_select")
    kind = find(control, "product_delivery_kind")
    assert kind.visible is True and find(control, "product_unlimited").value is True  # دیجیتالِ غیرکلیدی: نامحدودِ پیش‌فرض
    kind.value = "keys"
    fire(kind, "on_select")
    assert find(control, "product_keys").visible and not find(control, "product_unlimited").visible and not find(control, "product_stock").visible
    find(control, "product_keys").value = "K1\n\nK2\n  K3  "
    find(control, "product_category").value = "نرم‌افزار"
    fire(_find_save_button(control), "on_click")
    product = store.list()[0]
    assert (product.product_type, product.delivery_kind, product.category) == ("digital", "keys", "نرم‌افزار")
    assert product.stock_quantity == 3 and store.keys_remaining(product.id) == 3 and not product.unlimited_stock


def test_digital_link_product_and_validation_error_shown(tmp_path):
    page = FakePage()
    store = make_store(tmp_path)
    control = products_screen.build(page, "fa", store)
    fire(_find_add_button(control), "on_click")
    find(control, "product_name").value = "دوره"
    find(control, "product_price").value = "500"
    type_dd = find(control, "product_type")
    type_dd.value = "digital"
    fire(type_dd, "on_select")
    kind = find(control, "product_delivery_kind")
    kind.value = "link"
    fire(kind, "on_select")
    find(control, "product_delivery_payload").value = "https://x.example/course"
    fire(_find_save_button(control), "on_click")
    product = store.list()[0]
    assert product.delivery_kind == "link" and product.delivery_payload == "https://x.example/course" and product.unlimited_stock
    # ویرایش: فیلدها پر می‌شن
    fire(find(control, f"edit_{product.id}"), "on_click")
    assert find(control, "product_type").value == "digital" and find(control, "product_delivery_payload").value == "https://x.example/course"


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
