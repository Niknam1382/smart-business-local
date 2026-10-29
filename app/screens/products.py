"""
صفحه‌ی «محصولات» (فاز ۴) — فقط برای کسب‌وکارهایی که حالت فروشگاه رو انتخاب
کردن (تصمیمش توی main.py گرفته می‌شه: این صفحه اصلاً به نوار کناری اضافه
نمی‌شه اگه business_mode != "store").

فرم افزودن/ویرایش به‌صورت درون‌خطی (نه دیالوگ/صفحه‌ی جدا) بالای لیست باز
می‌شه — هم برای افزودن هم ویرایش از همون فرم استفاده می‌شه.
"""

from __future__ import annotations

import flet as ft

from app import theme
from app.core.products import Product, ProductError, ProductStore, copy_photo_into_store, delete_photo_file
from app.i18n import t
from app.screens.common import card, get_or_create_file_picker, page_header, primary_button

_FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_DIGIT_MAP = {d: str(i) for i, d in enumerate(_FA_DIGITS)} | {d: str(i) for i, d in enumerate(_AR_DIGITS)}


def _normalize_digits(s: str) -> str:
    """ارقام فارسی/عربی رو به لاتین تبدیل می‌کنه تا با کیبورد فارسی هم بشه عدد وارد کرد."""
    return "".join(_DIGIT_MAP.get(ch, ch) for ch in (s or ""))


def _parse_int(raw: str) -> int:
    cleaned = _normalize_digits(raw).replace(",", "").replace("،", "").strip()
    if not cleaned:
        return 0
    return int(cleaned)


def _format_price(amount: int, lang: str) -> str:
    return f"{amount:,} {t('products.price_suffix', lang)}"


def build(page: ft.Page, lang: str, store: ProductStore, settings=None, save=None) -> ft.Control:
    ui = {"mode": None, "show_inactive": False, "error": "", "photo_path": ""}

    list_column = ft.Column(spacing=12)
    form_container = ft.Container(visible=False)

    # ------------------------------------------------------------- فرم
    name_field = ft.TextField(key="product_name", label=t("products.form.name_label", lang), border_radius=10)
    price_field = ft.TextField(
        key="product_price",
        label=t("products.form.price_label", lang),
        border_radius=10,
        keyboard_type=ft.KeyboardType.NUMBER,
    )
    cost_field = ft.TextField(
        key="product_cost",
        label=t("products.form.cost_label", lang),
        border_radius=10,
        keyboard_type=ft.KeyboardType.NUMBER,
    )
    stock_field = ft.TextField(
        key="product_stock",
        label=t("products.form.stock_label", lang),
        border_radius=10,
        keyboard_type=ft.KeyboardType.NUMBER,
    )
    description_field = ft.TextField(
        key="product_description",
        label=t("products.form.description_label", lang),
        multiline=True,
        min_lines=2,
        max_lines=4,
        border_radius=10,
    )
    form_error = ft.Text("", size=12, color=theme.DANGER, visible=False)
    form_title = ft.Text("", size=16, weight=ft.FontWeight.W_600)

    # ---- محصولِ دیجیتال / دسته / ترتیب (R4) ----
    def _dd(key, label, options, value, width=None, on_select=None):
        return ft.Dropdown(
            key=key, label=label, border_radius=10, width=width, value=value, on_select=on_select,
            options=[ft.DropdownOption(key=k, text=text) for k, text in options],
        )

    def on_shape_change(e=None) -> None:
        if e is not None and getattr(e, "control", None) is type_dropdown and type_dropdown.value == "digital" and (delivery_dropdown.value or "none") != "keys":
            unlimited_switch.value = True  # دیجیتالِ غیرکلیدی پیش‌فرض نامحدوده
        sync_visibility()
        page.update()

    type_dropdown = _dd(
        "product_type", t("products.form.type_label", lang),
        [("physical", t("products.form.type_physical", lang)), ("digital", t("products.form.type_digital", lang))], "physical", 230, on_shape_change,
    )
    category_field = ft.TextField(key="product_category", label=t("products.form.category_label", lang), border_radius=10, width=200)
    sort_field = ft.TextField(key="product_sort", label=t("products.form.sort_label", lang), border_radius=10, width=200, keyboard_type=ft.KeyboardType.NUMBER)
    unlimited_switch = ft.Switch(key="product_unlimited", label=t("products.form.unlimited", lang), value=False, on_change=on_shape_change)
    delivery_dropdown = _dd(
        "product_delivery_kind", t("products.form.delivery_label", lang),
        [(k, t(f"products.form.delivery_{k}", lang)) for k in ("none", "text", "link", "file", "keys")], "none", 330, on_shape_change,
    )
    payload_field = ft.TextField(key="product_delivery_payload", label="", multiline=True, min_lines=1, max_lines=4, border_radius=10, visible=False)
    keys_field = ft.TextField(key="product_keys", label=t("products.form.keys_label", lang), multiline=True, min_lines=3, max_lines=8, border_radius=10, visible=False)
    keys_info = ft.Text("", key="product_keys_info", size=12, color=theme.text_secondary(page), visible=False)

    async def handle_pick_delivery_file(e) -> None:
        try:
            result = await get_or_create_file_picker(page).pick_files(dialog_title=t("products.form.pick_file", lang), allow_multiple=False)
        except ft.FletUnsupportedPlatformException:
            result = None
        if result:
            payload_field.value = result[0].path
            page.update()

    pick_file_button = ft.OutlinedButton(key="product_pick_file", content=t("products.form.pick_file", lang), icon=ft.Icons.ATTACH_FILE_ROUNDED,
                                         on_click=handle_pick_delivery_file, visible=False)

    def sync_visibility() -> None:
        digital = type_dropdown.value == "digital"
        kind = (delivery_dropdown.value or "none") if digital else "none"
        delivery_dropdown.visible = digital
        payload_field.visible = digital and kind in ("text", "link", "file")
        payload_field.label = t(f"products.form.payload_{kind}", lang) if kind in ("text", "link", "file") else ""
        pick_file_button.visible = digital and kind == "file"
        keys_field.visible = digital and kind == "keys"
        keys_info.visible = digital and kind == "keys"
        unlimited_switch.visible = not (digital and kind == "keys")
        stock_field.visible = not (unlimited_switch.visible and unlimited_switch.value) and not (digital and kind == "keys")

    photo_preview = ft.Container(
        key="photo_preview",
        width=72,
        height=72,
        border_radius=10,
        bgcolor=f"{theme.PRIMARY}12",
        alignment=ft.Alignment.CENTER,
        content=ft.Icon(ft.Icons.IMAGE_OUTLINED, color=theme.text_secondary(page), size=26),
    )

    def render_photo_preview() -> None:
        if ui["photo_path"]:
            photo_preview.content = ft.Image(
                src=ui["photo_path"], width=72, height=72, fit=ft.BoxFit.COVER, border_radius=10
            )
        else:
            photo_preview.content = ft.Icon(ft.Icons.IMAGE_OUTLINED, color=theme.text_secondary(page), size=26)

    file_picker = get_or_create_file_picker(page)

    async def handle_pick_photo(e) -> None:
        try:
            result = await file_picker.pick_files(
                dialog_title=t("products.form.add_photo", lang),
                file_type=ft.FilePickerFileType.IMAGE,
                allow_multiple=False,
            )
        except ft.FletUnsupportedPlatformException:
            result = None  # حالت وب (تست) — انتخاب فایل فقط در دسکتاپ واقعی کار می‌کنه
        if result:
            try:
                new_path = copy_photo_into_store(result[0].path)
            except ProductError as exc:
                form_error.value = str(exc)
                form_error.visible = True
                page.update()
                return
            ui["photo_path"] = new_path
            render_photo_preview()
            photo_buttons_row.controls = build_photo_buttons()
            page.update()

    def handle_remove_photo(e) -> None:
        ui["photo_path"] = ""
        render_photo_preview()
        photo_buttons_row.controls = build_photo_buttons()
        page.update()

    def build_photo_buttons() -> list:
        buttons = [
            ft.OutlinedButton(
                t("products.form.change_photo", lang) if ui["photo_path"] else t("products.form.add_photo", lang),
                icon=ft.Icons.IMAGE_OUTLINED,
                on_click=handle_pick_photo,
            )
        ]
        if ui["photo_path"]:
            buttons.append(
                ft.TextButton(
                    t("products.form.remove_photo", lang), icon=ft.Icons.DELETE_OUTLINE_ROUNDED, on_click=handle_remove_photo
                )
            )
        return buttons

    photo_buttons_row = ft.Row(spacing=8, controls=build_photo_buttons())

    def close_form() -> None:
        ui["mode"] = None
        ui["error"] = ""
        form_container.visible = False

    def open_add_form() -> None:
        ui["mode"] = "add"
        ui["photo_path"] = ""
        name_field.value = ""
        price_field.value = ""
        cost_field.value = ""
        stock_field.value = ""
        description_field.value = ""
        type_dropdown.value, category_field.value, sort_field.value = "physical", "", "0"
        unlimited_switch.value, delivery_dropdown.value = False, "none"
        payload_field.value, keys_field.value, keys_info.value = "", "", ""
        sync_visibility()
        form_error.visible = False
        form_title.value = t("products.form.title_add", lang)
        render_photo_preview()
        photo_buttons_row.controls = build_photo_buttons()
        form_container.visible = True
        page.update()

    def open_edit_form(product: Product) -> None:
        ui["mode"] = ("edit", product.id)
        ui["photo_path"] = product.photo_path
        name_field.value = product.name
        price_field.value = str(product.price_irr)
        cost_field.value = str(product.cost_irr) if product.cost_irr else ""
        stock_field.value = str(product.stock_quantity)
        description_field.value = product.description
        type_dropdown.value, category_field.value, sort_field.value = product.product_type, product.category, str(product.sort_order)
        unlimited_switch.value, delivery_dropdown.value = product.unlimited_stock, product.delivery_kind
        payload_field.value, keys_field.value = product.delivery_payload, ""
        keys_info.value = t("products.form.keys_info", lang, count=product.stock_quantity) if product.delivery_kind == "keys" else ""
        sync_visibility()
        form_error.visible = False
        form_title.value = t("products.form.title_edit", lang)
        render_photo_preview()
        photo_buttons_row.controls = build_photo_buttons()
        form_container.visible = True
        page.update()

    def handle_save(e) -> None:
        try:
            price = _parse_int(price_field.value)
            stock = _parse_int(stock_field.value)
        except ValueError:
            form_error.value = "قیمت و موجودی باید عدد باشن."
            form_error.visible = True
            page.update()
            return
        try:
            cost = _parse_int(cost_field.value) if (cost_field.value or "").strip() else 0
            if cost < 0:
                raise ValueError
        except ValueError:
            form_error.value = "بهای تمام‌شده باید عددِ صحیحِ غیرمنفی باشه (یا خالی)."
            form_error.visible = True
            page.update()
            return
        digital = type_dropdown.value == "digital"
        kind = (delivery_dropdown.value or "none") if digital else "none"
        try:
            sort = _parse_int(sort_field.value or "0")
        except ValueError:
            form_error.value = "ترتیبِ نمایش باید عدد باشه."
            form_error.visible = True
            page.update()
            return
        shop = dict(
            product_type=type_dropdown.value or "physical", category=category_field.value or "",
            unlimited_stock=bool(unlimited_switch.value) and kind != "keys", delivery_kind=kind,
            delivery_payload=(payload_field.value or "").strip() if kind in ("text", "link", "file") else "", sort_order=sort,
        )
        new_keys = [line for line in (keys_field.value or "").splitlines() if line.strip()] if kind == "keys" else []
        if shop["unlimited_stock"]:
            stock = 0
        try:
            saved_id = None
            if ui["mode"] == "add":
                saved_id = store.add(
                    name_field.value or "",
                    price,
                    stock,
                    description=description_field.value or "",
                    photo_path=ui["photo_path"],
                    **shop,
                )
            else:
                _, product_id = ui["mode"]
                old = store.get(product_id)
                if old and old.photo_path and old.photo_path != ui["photo_path"]:
                    delete_photo_file(old.photo_path)
                store.update(
                    product_id,
                    name_field.value or "",
                    price,
                    stock,
                    description=description_field.value or "",
                    photo_path=ui["photo_path"],
                    **shop,
                )
                saved_id = product_id
            if saved_id is not None:
                store.set_cost(saved_id, cost)  # N19: بهای تمام‌شده (فقط روی فروش‌های بعدی اثر دارد)
            if new_keys and saved_id is not None:
                store.add_keys(saved_id, new_keys)
        except ProductError as exc:
            form_error.value = str(exc)
            form_error.visible = True
            page.update()
            return
        close_form()
        render_list()
        page.update()

    form_container.key = "product_form"
    form_container.content = card(
        page,
        ft.Column(
            spacing=12,
            controls=[
                form_title,
                name_field,
                ft.Row(controls=[price_field, stock_field]),
                cost_field,
                description_field,
                ft.Row(spacing=10, wrap=True, controls=[type_dropdown, category_field, sort_field]),
                unlimited_switch,
                delivery_dropdown,
                ft.Row(spacing=10, controls=[ft.Container(expand=True, content=payload_field), pick_file_button]),
                keys_field,
                keys_info,
                ft.Column(
                    spacing=6,
                    controls=[
                        ft.Text(t("products.form.photo_label", lang), size=12, color=theme.text_secondary(page)),
                        ft.Row(spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[photo_preview, photo_buttons_row]),
                    ],
                ),
                form_error,
                ft.Row(
                    spacing=10,
                    controls=[
                        primary_button(t("products.form.save", lang), handle_save, width=140),
                        ft.TextButton(
                            key="product_form_cancel",
                            content=t("products.form.cancel", lang),
                            on_click=lambda e: (close_form(), render_list(), page.update()),
                        ),
                    ],
                ),
            ],
        ),
        padding=20,
    )

    # ------------------------------------------------------------- لیست
    def product_card(product: Product) -> ft.Control:
        thumb = (
            ft.Image(src=product.photo_path, width=56, height=56, fit=ft.BoxFit.COVER, border_radius=10)
            if product.photo_path
            else ft.Container(
                width=56,
                height=56,
                border_radius=10,
                bgcolor=f"{theme.PRIMARY}12",
                alignment=ft.Alignment.CENTER,
                content=ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, color=theme.PRIMARY, size=24),
            )
        )
        if product.unlimited_stock:
            stock_chip = ft.Text(t("products.badge_unlimited", lang), size=12, color=theme.SUCCESS)
        elif product.delivery_kind == "keys" and product.in_stock:
            stock_chip = ft.Text(t("products.keys_left", lang, count=product.stock_quantity), size=12, color=theme.SUCCESS)
        elif product.in_stock:
            stock_chip = ft.Text(
                t("products.in_stock_count", lang, count=product.stock_quantity), size=12, color=theme.SUCCESS
            )
        else:
            stock_chip = ft.Text(t("products.out_of_stock", lang), size=12, color=theme.DANGER)

        badges = [stock_chip]
        if product.is_digital:
            badges.append(ft.Text("💾 " + t("products.badge_digital", lang), size=12, color=theme.text_secondary(page)))
        if product.category:
            badges.append(ft.Text("🗂 " + product.category, size=12, color=theme.text_secondary(page)))
        if not product.active:
            badges.append(
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=8, vertical=1),
                    border_radius=20,
                    bgcolor=f"{theme.text_secondary(page)}22",
                    content=ft.Text(t("products.inactive_badge", lang), size=11, color=theme.text_secondary(page)),
                )
            )

        return ft.Container(
            key=f"product_{product.id}",
            padding=14,
            border_radius=12,
            bgcolor=theme.card_bgcolor(page),
            border=ft.Border.all(1, theme.border_color(page)),
            content=ft.Row(
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    thumb,
                    ft.Column(
                        expand=True,
                        spacing=3,
                        controls=[
                            ft.Text(product.name, size=14.5, weight=ft.FontWeight.W_600),
                            ft.Text(_format_price(product.price_irr, lang), size=13, color=theme.text_secondary(page)),
                            ft.Row(spacing=8, controls=badges),
                        ],
                    ),
                    ft.OutlinedButton(
                        key=f"edit_{product.id}",
                        content=t("products.edit", lang),
                        icon=ft.Icons.EDIT_OUTLINED,
                        on_click=lambda e, p=product: open_edit_form(p),
                    ),
                    ft.TextButton(
                        key=f"toggle_active_{product.id}",
                        content=t("products.activate", lang) if not product.active else t("products.deactivate", lang),
                        on_click=lambda e, p=product: handle_toggle_active(p),
                    ),
                ],
            ),
        )

    def handle_toggle_active(product: Product) -> None:
        store.set_active(product.id, not product.active)
        render_list()
        page.update()

    def handle_add_sample(e=None) -> None:
        store.add(t("products.sample.name", lang), 100_000 * 10, 10, description=t("products.sample.description", lang))  # ۱۰۰٬۰۰۰ تومان = ۱٬۰۰۰٬۰۰۰ ریال
        render_list()
        page.update()

    def render_list() -> None:
        products = store.list(include_inactive=ui["show_inactive"])
        if not products:
            list_column.controls = [
                ft.Container(
                    padding=30,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=8,
                        controls=[
                            ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, size=34, color=theme.text_secondary(page)),
                            ft.Text(
                                t("products.empty", lang), size=13, color=theme.text_secondary(page), text_align=ft.TextAlign.CENTER
                            ),
                            # N2: برنامه کاملاً خالی شروع می‌شه؛ محصولِ نمونه فقط وقتی ساخته می‌شه که خودِ کاربر بخواد
                            ft.TextButton(key="product_add_sample", content=t("products.sample.button", lang), on_click=handle_add_sample),
                        ],
                    ),
                )
            ]
        else:
            list_column.controls = [product_card(p) for p in products]

    def handle_toggle_show_inactive(e) -> None:
        ui["show_inactive"] = e.control.value
        render_list()
        page.update()

    sync_visibility()
    def low_stock_controls() -> list:
        """A7: آستانه‌ی «موجودی کم» (۰ = خاموش)؛ فقط وقتی تنظیمات به صفحه داده شده باشه."""
        if settings is None:
            return []
        note = ft.Text("", key="low_stock_note", size=12, visible=False)

        def commit(e) -> None:
            raw = (e.control.value or "").strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
            if not raw.isdigit() or int(raw) > 100000:
                note.value, note.color, note.visible = "عددِ صحیحِ ۰ تا ۱۰۰۰۰۰ بنویس.", theme.DANGER, True
            else:
                settings.low_stock_threshold = int(raw)
                if save:
                    save()
                note.value, note.color, note.visible = "✅ ذخیره شد.", theme.SUCCESS, True
            page.update()

        field = ft.TextField(key="low_stock_field", label="هشدارِ موجودیِ کم (۰ = خاموش)", width=240, border_radius=10, value=str(settings.low_stock_threshold),
                             on_submit=commit, on_blur=commit)
        return [ft.Row(spacing=10, wrap=True, controls=[field, note])]

    render_photo_preview()
    render_list()

    return ft.Container(
        expand=True,
        padding=ft.Padding.symmetric(horizontal=32, vertical=24),
        content=ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=18,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[
                        page_header(page, ft.Icons.INVENTORY_2_ROUNDED, t("products.title", lang), t("products.subtitle", lang)),
                        primary_button(
                            t("products.add_new", lang), lambda e: open_add_form(), icon=ft.Icons.ADD_ROUNDED, width=170
                        ),
                    ],
                ),
                *low_stock_controls(),
                ft.Row(
                    controls=[
                        ft.Switch(
                            key="show_inactive_switch",
                            label=t("products.show_inactive", lang),
                            value=ui["show_inactive"],
                            on_change=handle_toggle_show_inactive,
                        )
                    ]
                ),
                ft.Text(t("products.deactivate_note", lang), size=11, color=theme.text_secondary(page)),
                form_container,
                list_column,
            ],
        ),
    )
