"""
صفحه‌ی «محصولات» (فاز ۴) — فقط برای کسب‌وکارهایی که حالت فروشگاه رو انتخاب
کردن (تصمیمش توی main.py گرفته می‌شه: این صفحه اصلاً به نوار کناری اضافه
نمی‌شه اگه business_mode != "store").

فرم افزودن/ویرایش به‌صورت درون‌خطی (نه دیالوگ/صفحه‌ی جدا) بالای لیست باز
می‌شه — هم برای افزودن هم ویرایش از همون فرم استفاده می‌شه.

محصول فقط فیزیکی است: هیچ انتخابِ «نوعِ محصول» و هیچ تحویلِ خودکاری در این فرم نیست. دو دکمه‌ی
«وارداتِ دسته‌ای» هم بالای لیست هست: قالبِ اکسل را می‌سازد و فایلِ پرشده را وارد می‌کند
(``app.core.product_import``).
"""

from __future__ import annotations

from pathlib import Path

import flet as ft

from app import theme
from app.core import product_import
from app.core import report_pdf, report_xlsx
from app.core.paths import get_app_data_dir
from app.core.products import Product, ProductError, ProductStore, copy_photo_into_store, delete_photo_file
from app.i18n import t
from app.screens import common
from app.screens.common import card, get_or_create_file_picker, page_header, primary_button

_FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_DIGIT_MAP = {d: str(i) for i, d in enumerate(_FA_DIGITS)} | {d: str(i) for i, d in enumerate(_AR_DIGITS)}

# دکمه‌هایِ «گزارشِ حرفه‌ای» (دوزبانه و محلیِ همین صفحه؛ i18n دست‌نخورده می‌ماند)
_R = {
    "title": ("گزارشِ رسمیِ این بخش", "Official report for this section"),
    "xlsx": ("خروجِ اکسل", "Excel export"),
    "pdf": ("خروجِ PDF", "PDF export"),
    "done": ("✅ گزارشِ {n} سطری ساخته شد: {path}", "✅ Report with {n} rows created: {path}"),
    "failed": ("ساختنِ فایل ناموفق بود: {error}", "Could not create the file: {error}"),
}


def _r(key: str, lang: str, **kw) -> str:
    fa, en = _R[key]
    text = en if lang == "en" else fa
    return text.format(**kw) if kw else text


def _normalize_digits(s: str) -> str:
    """ارقام فارسی/عربی رو به لاتین تبدیل می‌کنه تا با کیبورد فارسی هم بشه عدد وارد کرد."""
    return "".join(_DIGIT_MAP.get(ch, ch) for ch in (s or ""))


def _parse_int(raw: str) -> int:
    cleaned = _normalize_digits(raw)
    for separator in (",", "،", "٬", "_"):  # جداکننده‌ی هزارگانِ فارسی/عربی که کاربر از اکسل می‌آید
        cleaned = cleaned.replace(separator, "")
    cleaned = cleaned.strip()
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
    form_error = ft.Text("", key="product_form_error", size=12, color=theme.DANGER, visible=False)
    form_title = ft.Text("", size=16, weight=ft.FontWeight.W_600)

    # ---- دسته / ترتیب / موجودی ----
    category_field = ft.TextField(key="product_category", label=t("products.form.category_label", lang), border_radius=10, width=200)
    sort_field = ft.TextField(key="product_sort", label=t("products.form.sort_label", lang), border_radius=10, width=200, keyboard_type=ft.KeyboardType.NUMBER)

    def sync_visibility() -> None:
        # «نامحدود» یعنی عددِ موجودی معنا ندارد؛ فیلد پنهان می‌شه تا کاربر عددِ الکی وارد نکنه
        stock_field.visible = not bool(unlimited_switch.value)

    unlimited_switch = ft.Switch(key="product_unlimited", label=t("products.form.unlimited", lang), value=False,
                                 on_change=lambda e: (sync_visibility(), page.update()))

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
            common.secondary(
                t("products.form.change_photo", lang) if ui["photo_path"] else t("products.form.add_photo", lang),
                icon=ft.Icons.IMAGE_OUTLINED, size="sm", on_click=handle_pick_photo,
            )
        ]
        if ui["photo_path"]:
            buttons.append(
                common.text(t("products.form.remove_photo", lang), icon=ft.Icons.DELETE_OUTLINE_ROUNDED, on_click=handle_remove_photo)
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
        category_field.value, sort_field.value = "", "0"
        unlimited_switch.value = False
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
        category_field.value, sort_field.value = product.category, str(product.sort_order)
        unlimited_switch.value = product.unlimited_stock
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
        try:
            sort = _parse_int(sort_field.value or "0")
        except ValueError:
            form_error.value = "ترتیبِ نمایش باید عدد باشه."
            form_error.visible = True
            page.update()
            return
        shop = dict(category=category_field.value or "", unlimited_stock=bool(unlimited_switch.value), sort_order=sort)
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
                ft.Row(spacing=10, wrap=True, controls=[category_field, sort_field]),
                unlimited_switch,
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
                        common.text(
                            t("products.form.cancel", lang), key="product_form_cancel",
                            on_click=lambda e: (close_form(), render_list(), page.update()),
                        ),
                    ],
                ),
            ],
        ),
        padding=20,
    )

    # --------------------------------------------------------- وارداتِ دسته‌ای
    import_note = ft.Text("", key="product_import_note", size=12, color=theme.text_secondary(page), visible=False)

    def show_note(text: str, ok: bool) -> None:
        import_note.value = text
        import_note.color = theme.SUCCESS if ok else theme.DANGER
        import_note.visible = bool(text)
        page.update()

    def do_template(e=None) -> None:
        """قالب را در پوشه‌ی exportsِ خودِ برنامه می‌سازد (همان جایی که خروجیِ مشتری و دفتر می‌رود)."""
        path = get_app_data_dir() / "exports" / "products-template.xlsx"

        def work() -> None:
            try:
                product_import.write_template(path)
            except OSError as exc:
                show_note(f"قالب ساخته نشد: {exc}", False)
                return
            show_note(t("products.import.template_done", lang, path=str(path)), True)

        page.run_thread(work)

    def do_import(path: Path) -> None:
        def work() -> None:
            try:
                added, problems = product_import.import_file(store, path)
            except product_import.ProductImportError as exc:
                show_note(str(exc), False)
                return
            except (OSError, ProductError) as exc:
                show_note(f"واردات نشد: {exc}", False)
                return
            render_list()
            show_note(product_import.import_summary(lang, added, problems), not problems)
            page.update()

        page.run_thread(work)

    async def on_import_file(e=None) -> None:
        picker = get_or_create_file_picker(page)
        try:
            picked = await picker.pick_files(
                dialog_title=t("products.import.pick", lang),
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["xlsx", "csv"],
                allow_multiple=False,
            )
        except ft.FletUnsupportedPlatformException:
            picked = None  # حالت وب/تست — انتخاب فایل فقط توی دسکتاپ واقعی هست
        if picked:
            do_import(Path(picked[0].path))

    import_row = ft.Row(
        spacing=10,
        wrap=True,
        controls=[
            ft.Text(t("products.import.title", lang), size=13, weight=ft.FontWeight.W_600),
            common.secondary(t("products.import.template", lang), key="product_template",
                             icon=ft.Icons.DOWNLOAD_ROUNDED, size="sm", on_click=do_template),
            common.secondary(t("products.import.run", lang), key="product_import",
                             icon=ft.Icons.UPLOAD_FILE_ROUNDED, size="sm", on_click=on_import_file),
        ],
    )

    # --------------------------------------------------- گزارشِ اکسل/PDF (بخش ۸)
    def do_report(fmt: str, _e=None) -> None:
        """کارنامه‌ی محصولات/انبار (همان لیستِ فعال/غیرفعالِ روی صفحه) را به فایلِ اکسل یا PDF
        تبدیل می‌کند؛ فایل در ``<داده>/reports`` می‌نشیند و پوشه‌اش باز می‌شود — مثلِ فاکتور."""

        def work() -> None:
            try:
                data = report_xlsx.products_report(store.list(include_inactive=ui["show_inactive"]),
                                                   shop_name=report_xlsx.shop_name_of(settings))
                path = report_pdf.write_pdf(data) if fmt == "pdf" else report_xlsx.write_xlsx(data)
            except report_xlsx.ReportError as exc:  # «چیزی برای خروجی گرفتن نیست» / شکستِ PDF
                show_note(str(exc), False)
                return
            except OSError as exc:
                show_note(_r("failed", lang, error=str(exc)), False)
                return
            show_note(_r("done", lang, n=data.count, path=str(path)), True)
            common.open_folder(path.parent)

        page.run_thread(work)

    report_row = ft.Row(
        spacing=10,
        wrap=True,
        controls=[
            ft.Text(_r("title", lang), size=13, weight=ft.FontWeight.W_600),
            common.secondary(_r("xlsx", lang), key="product_export_xlsx",
                             icon=ft.Icons.TABLE_VIEW, size="sm", on_click=lambda e: do_report("xlsx")),
            common.secondary(_r("pdf", lang), key="product_export_pdf",
                             icon=ft.Icons.PICTURE_AS_PDF_ROUNDED, size="sm", on_click=lambda e: do_report("pdf")),
        ],
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
        elif product.in_stock:
            stock_chip = ft.Text(
                t("products.in_stock_count", lang, count=product.stock_quantity), size=12, color=theme.SUCCESS
            )
        else:
            stock_chip = ft.Text(t("products.out_of_stock", lang), size=12, color=theme.DANGER)

        badges = [stock_chip]
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
                    common.secondary(t("products.edit", lang), key=f"edit_{product.id}",
                                     icon=ft.Icons.EDIT_OUTLINED, size="sm", on_click=lambda e, p=product: open_edit_form(p)),
                    common.text(t("products.activate", lang) if not product.active else t("products.deactivate", lang),
                                key=f"toggle_active_{product.id}", on_click=lambda e, p=product: handle_toggle_active(p)),
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
                            common.text(t("products.sample.button", lang), key="product_add_sample", on_click=handle_add_sample),
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

    return common.screen_frame(
        page,
        ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.START,
            controls=[
                page_header(page, ft.Icons.INVENTORY_2_ROUNDED, t("products.title", lang), t("products.subtitle", lang)),
                primary_button(t("products.add_new", lang), lambda e: open_add_form(), icon=ft.Icons.ADD_ROUNDED, width=170),
            ],
        ),
        [
            *low_stock_controls(),
            import_row,
            import_note,
            report_row,
            ft.Row(controls=[ft.Switch(key="show_inactive_switch", label=t("products.show_inactive", lang), value=ui["show_inactive"], on_change=handle_toggle_show_inactive)]),
            ft.Text(t("products.deactivate_note", lang), size=11, color=theme.text_secondary(page)),
            form_container,
            list_column,
        ],
        key="products_page",
    )
