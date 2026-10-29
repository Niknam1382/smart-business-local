"""
صفحه‌ی «راه‌اندازی و آزمایش هوش مصنوعی» (فاز ۲، با اصلاحات پس از تست واقعی).

نسخه‌ی قبلی این صفحه سه مشکل واقعی داشت که با تست روی ویندوز پیدا شدن:
مشخصات سخت‌افزار ناقص نشون داده می‌شد (مدل CPU/GPU جا افتاده بود)، فایل
دانلودشده فقط با «حداقل ۱ مگابایت» چک می‌شد که یعنی یه دانلود ناقص هم
«آماده» حساب می‌شد و بعداً موقع چت شکست می‌خورد، و برای حالت API معلوم
نبود دقیقاً کدوم مدل صدا زده می‌شه. هر سه این‌جا اصلاح شدن.
"""

from __future__ import annotations

import flet as ft

from app import theme
from app.screens import common
from app.core import ai_engine, downloader, hardware, model_catalog
from app.i18n import t
from app.screens.ai_select import build_hardware_block


def _mask_key(key: str) -> str:
    if not key:
        return "—"
    if len(key) <= 8:
        return "•" * len(key)
    return key[:4] + "•" * 6 + key[-4:]


def _section_header(icon: str, text: str) -> ft.Control:
    return ft.Row(
        spacing=8,
        controls=[
            ft.Icon(icon=icon, color=theme.PRIMARY, size=20),
            ft.Text(text, size=15, weight=ft.FontWeight.W_600),
        ],
    )


def _card(page: ft.Page, content: ft.Control) -> ft.Container:
    """کانتینر استاندارد برای هر بخش — سایه‌ی ملایم به‌جای فقط یه خط حاشیه‌ی ساده."""
    return ft.Container(
        padding=20,
        border_radius=14,
        bgcolor=theme.card_bgcolor(page),
        border=ft.Border.all(1, theme.border_color(page)),
        shadow=ft.BoxShadow(blur_radius=18, color="#00000014", offset=ft.Offset(0, 4)),
        content=content,
    )


def build(page: ft.Page, lang: str, settings, save_callback) -> ft.Control:
    section = (
        _build_local_section(page, lang, settings, save_callback)
        if settings.ai_mode == "local"
        else _build_api_section(page, lang, settings, save_callback)
    )

    return ft.Container(
        expand=True,
        padding=ft.Padding.symmetric(horizontal=32, vertical=24),
        bgcolor=theme.surface_bgcolor(page),
        content=ft.Column(
            spacing=20,
            scroll=ft.ScrollMode.AUTO,
            controls=[
                common.page_header(page, ft.Icons.SMART_TOY_ROUNDED, t("ai_setup.title", lang)),
                section,
            ],
        ),
    )


# ============================== حالت محلی ==============================


def _build_local_section(page: ft.Page, lang: str, settings, save_callback) -> ft.Control:
    hw = hardware.detect()
    recommended_id = model_catalog.recommend_tier_id(hw)
    state = {"tier_id": settings.model_tier or recommended_id}

    hw_card = _card(
        page,
        ft.Column(
            spacing=14,
            controls=[
                _section_header(ft.Icons.MEMORY_ROUNDED, t("ai_setup.local.hw_title", lang)),
                build_hardware_block(page, lang),
            ],
        ),
    )

    # --- مسیر ذخیره‌ی مدل ---
    storage_path_text = ft.Text(str(settings.get_model_storage_dir()), size=13, weight=ft.FontWeight.W_500, selectable=True)
    free_space_text = ft.Text("", size=12, color=theme.text_secondary(page))

    def refresh_free_space():
        free_gb = hardware.free_disk_gb_at(settings.get_model_storage_dir())
        free_space_text.value = (
            f"{t('ai_setup.local.free_space', lang)}: {free_gb:.1f} GB" if free_gb is not None else ""
        )

    refresh_free_space()

    file_picker = common.get_or_create_file_picker(page)

    async def handle_change_path(e):
        try:
            selected = await file_picker.get_directory_path(
                dialog_title=t("ai_setup.local.storage_change", lang)
            )
        except ft.FletUnsupportedPlatformException:
            selected = None  # حالت وب (تست) — انتخاب پوشه فقط در دسکتاپ واقعی کار می‌کنه
        if selected:
            settings.model_storage_path = selected
            save_callback()
            storage_path_text.value = selected
            refresh_free_space()
            render_tiers()
            page.update()

    storage_card = _card(
        page,
        ft.Column(
            spacing=10,
            controls=[
                _section_header(ft.Icons.FOLDER_OPEN_ROUNDED, t("ai_setup.local.storage_label", lang)),
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        storage_path_text,
                        ft.TextButton(t("ai_setup.local.storage_change", lang), on_click=handle_change_path),
                    ],
                ),
                free_space_text,
            ],
        ),
    )

    # --- انتخاب سایز مدل ---
    tiers_column = ft.Column(spacing=10)

    def current_dest_path():
        tier = model_catalog.get_tier(state["tier_id"])
        return settings.get_model_storage_dir() / tier.filename

    def size_line_for(tier: model_catalog.ModelTier) -> str:
        dest = settings.get_model_storage_dir() / tier.filename
        if dest.exists():
            actual_gb = dest.stat().st_size / (1024**3)
            return t("ai_setup.local.tier_downloaded_size", lang, size=f"{actual_gb:.2f}")
        return t("ai_setup.local.tier_size", lang, size=tier.approx_size_gb)

    def tier_row(tier: model_catalog.ModelTier) -> ft.Control:
        is_selected = state["tier_id"] == tier.id
        is_recommended = tier.id == recommended_id
        title_controls = [
            ft.Text(
                f"{tier.title.get(lang, '')} · {tier.model_name} ({tier.params})",
                size=14,
                weight=ft.FontWeight.W_600,
            )
        ]
        if is_recommended:
            title_controls.append(ft.Icon(icon=ft.Icons.STAR_ROUNDED, color=theme.ACCENT, size=17))
        return ft.Container(
            padding=16,
            border_radius=12,
            bgcolor=theme.card_bgcolor(page),
            border=ft.Border.all(2 if is_selected else 1, theme.ACCENT if is_selected else theme.border_color(page)),
            ink=True,
            on_click=lambda e, tid=tier.id: choose_tier(tid),
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.START,
                controls=[
                    ft.Column(
                        expand=True,
                        spacing=4,
                        controls=[
                            ft.Row(spacing=6, controls=title_controls),
                            ft.Text(tier.why.get(lang, ""), size=12, color=theme.text_secondary(page)),
                            ft.Text(size_line_for(tier), size=12, color=theme.text_secondary(page)),
                        ],
                    ),
                    ft.Icon(
                        icon=ft.Icons.CHECK_CIRCLE_ROUNDED if is_selected else ft.Icons.RADIO_BUTTON_UNCHECKED,
                        color=theme.ACCENT if is_selected else theme.border_color(page),
                        size=22,
                    ),
                ],
            ),
        )

    def render_tiers():
        tiers_column.controls = [tier_row(tier) for tier in model_catalog.TIERS]

    def choose_tier(tier_id: str):
        state["tier_id"] = tier_id
        settings.model_tier = tier_id
        save_callback()
        render_tiers()
        refresh_download_status()
        page.update()

    render_tiers()

    download_status_area = ft.Column(spacing=8)
    cancel_flag = {"cancelled": False}
    refresh_test_chat_availability = lambda: None  # noqa: E731 — پایین‌تر واقعی می‌شه

    def handle_delete(e=None):
        downloader.delete_model(current_dest_path())
        render_tiers()
        refresh_download_status()
        refresh_test_chat_availability()
        page.update()

    def start_download(e=None):
        tier = model_catalog.get_tier(state["tier_id"])
        dest = current_dest_path()
        cancel_flag["cancelled"] = False

        progress_bar = ft.ProgressBar(value=0, width=320, color=theme.ACCENT)
        progress_text = ft.Text(t("ai_setup.local.downloading", lang, percent=0), size=12)
        cancel_btn = ft.TextButton(
            t("ai_setup.local.cancel", lang), on_click=lambda e: cancel_flag.__setitem__("cancelled", True)
        )
        download_status_area.controls = [progress_bar, progress_text, cancel_btn]
        page.update()

        def on_progress(downloaded: int, total: int) -> None:
            pct = int(downloaded / total * 100) if total else 0
            progress_bar.value = pct / 100
            progress_text.value = t("ai_setup.local.downloading", lang, percent=pct)
            page.update()

        def show_failure(message: str) -> None:
            download_status_area.controls = [
                ft.Text(message[:250], color=theme.DANGER, size=12),
                ft.Button(content=t("ai_setup.local.retry", lang), on_click=start_download),
            ]
            page.update()

        def worker():
            try:
                downloader.download_file(
                    tier.url, dest, on_progress=on_progress, should_cancel=lambda: cancel_flag["cancelled"]
                )
            except downloader.DownloadCancelled:
                refresh_download_status()
                return
            except downloader.DownloadError as exc:
                show_failure(t("ai_setup.local.download_failed", lang) + " " + str(exc))
                return

            ok, message = downloader.verify_gguf(dest, expected_size_bytes=tier.approx_size_bytes)
            if not ok:
                downloader.delete_model(dest)
                show_failure(t("ai_setup.local.verify_failed", lang) + " " + message)
                return

            render_tiers()
            refresh_download_status()
            refresh_test_chat_availability()

        page.run_thread(worker)

    def refresh_download_status():
        dest = current_dest_path()
        tier = model_catalog.get_tier(state["tier_id"])
        ok, _ = downloader.verify_gguf(dest, expected_size_bytes=tier.approx_size_bytes) if dest.exists() else (False, "")
        if ok:
            download_status_area.controls = [
                ft.Row(
                    spacing=16,
                    controls=[
                        ft.Row(
                            spacing=6,
                            controls=[
                                ft.Icon(icon=ft.Icons.CHECK_CIRCLE_ROUNDED, color=theme.SUCCESS, size=18),
                                ft.Text(t("ai_setup.local.download_done", lang), color=theme.SUCCESS, size=13),
                            ],
                        ),
                        ft.TextButton(t("ai_setup.local.redownload", lang), on_click=start_download),
                        ft.TextButton(
                            t("ai_setup.local.delete_model", lang),
                            icon=ft.Icons.DELETE_OUTLINE_ROUNDED,
                            icon_color=theme.DANGER,
                            on_click=handle_delete,
                        ),
                    ],
                )
            ]
        else:
            download_status_area.controls = [
                ft.Button(
                    content=t("ai_setup.local.download_button", lang),
                    icon=ft.Icons.DOWNLOAD_ROUNDED,
                    bgcolor=theme.PRIMARY,
                    color="#FFFFFF",
                    on_click=start_download,
                )
            ]
        page.update()

    refresh_download_status()

    models_card = _card(
        page,
        ft.Column(
            spacing=14,
            controls=[
                _section_header(ft.Icons.SMART_TOY_ROUNDED, t("ai_setup.local.models_section_title", lang)),
                ft.Text(t("ai_setup.local.recommendation", lang) + " " + model_catalog.get_tier(recommended_id).model_name, size=12, color=theme.text_secondary(page)),
                ft.Text(t("ai_setup.local.choose_tier", lang), size=12, color=theme.text_secondary(page)),
                tiers_column,
                download_status_area,
            ],
        ),
    )

    test_chat = _build_test_chat_section(
        page, lang, settings, is_ready=lambda: downloader.verify_gguf(current_dest_path(), expected_size_bytes=model_catalog.get_tier(state["tier_id"]).approx_size_bytes)[0] if current_dest_path().exists() else False
    )
    refresh_test_chat_availability = test_chat["refresh"]

    return ft.Column(
        spacing=16,
        controls=[hw_card, storage_card, models_card, test_chat["control"]],
    )


# ============================== حالت API ==============================


def _build_api_section(page: ft.Page, lang: str, settings, save_callback) -> ft.Control:
    model_field = ft.TextField(
        label=t("ai.api.model_label", lang),
        value=settings.api_model_name or "gpt-4o-mini",
        border_radius=10,
        width=280,
    )

    def handle_model_change(e):
        settings.api_model_name = model_field.value or "gpt-4o-mini"
        save_callback()

    model_field.on_blur = handle_model_change
    model_field.on_submit = handle_model_change

    info_card = _card(
        page,
        ft.Column(
            spacing=14,
            controls=[
                _section_header(ft.Icons.CLOUD_OUTLINED, "API"),
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Text(t("ai.api.base_url_label", lang), size=13, color=theme.text_secondary(page)),
                        ft.Text(settings.api_base_url or "—", size=13, weight=ft.FontWeight.W_500),
                    ],
                ),
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Text(t("ai.api.key_label", lang), size=13, color=theme.text_secondary(page)),
                        ft.Text(_mask_key(settings.get_api_key()), size=13, weight=ft.FontWeight.W_500),
                    ],
                ),
                model_field,
                ft.Text(t("ai.api.model_note", lang), size=12, color=theme.text_secondary(page)),
            ],
        ),
    )

    test_result = ft.Text("", size=13)

    def handle_test(e):
        test_result.value = t("ai_setup.api.testing", lang)
        test_result.color = theme.text_secondary(page)
        page.update()

        def worker():
            try:
                engine = ai_engine.ApiEngine(
                    base_url=settings.api_base_url,
                    api_key=settings.get_api_key(),
                    model=settings.api_model_name or "gpt-4o-mini",
                )
                engine.chat("You are a helpful assistant.", [], "Say hello in one short sentence.")
                test_result.value = "✓ " + t("ai_setup.api.success", lang)
                test_result.color = theme.SUCCESS
            except ai_engine.AiEngineError as exc:
                test_result.value = t("ai_setup.test_chat.error_prefix", lang) + str(exc)[:200]
                test_result.color = theme.DANGER
            page.update()

        page.run_thread(worker)

    test_button = ft.Button(
        content=t("ai_setup.api.test_button", lang), bgcolor=theme.PRIMARY, color="#FFFFFF", on_click=handle_test
    )

    test_chat = _build_test_chat_section(page, lang, settings, is_ready=lambda: bool(settings.get_api_key()))

    return ft.Column(
        spacing=16,
        controls=[
            info_card,
            ft.Row(spacing=10, controls=[test_button, test_result]),
            test_chat["control"],
        ],
    )


# ========================== جعبه‌ی تست مشترک ==========================


def _build_test_chat_section(page: ft.Page, lang: str, settings, is_ready) -> dict:
    history: list = []
    conversation = ft.Column(spacing=10)

    message_field = ft.TextField(
        hint_text=t("ai_setup.test_chat.placeholder", lang), expand=True, border_radius=10
    )
    send_button = ft.Button(
        content=t("ai_setup.test_chat.send", lang), icon=ft.Icons.SEND_ROUNDED, bgcolor=theme.PRIMARY, color="#FFFFFF"
    )
    not_ready_note = ft.Text(t("ai_setup.test_chat.not_ready", lang), size=12, color=theme.text_secondary(page))

    row = ft.Row(spacing=10, controls=[message_field, send_button])

    def refresh():
        ready = is_ready()
        message_field.disabled = not ready
        send_button.disabled = not ready
        not_ready_note.visible = not ready
        page.update()

    def handle_send(e):
        user_text = (message_field.value or "").strip()
        if not user_text or send_button.disabled:
            return
        message_field.value = ""
        conversation.controls.append(ft.Text(f"🧑 {user_text}", size=13, weight=ft.FontWeight.W_500))
        thinking = ft.Text(
            t("ai_setup.test_chat.thinking", lang), size=13, italic=True, color=theme.text_secondary(page)
        )
        conversation.controls.append(thinking)
        page.update()

        def worker():
            try:
                engine = ai_engine.build_engine_from_settings(settings)
                answer = engine.chat(settings.system_prompt or "You are a helpful assistant.", history, user_text)
                thinking.value = f"🤖 {answer}"
                thinking.italic = False
                thinking.color = None
                history.append(ai_engine.ChatMessage("user", user_text))
                history.append(ai_engine.ChatMessage("assistant", answer))
            except ai_engine.AiEngineError as exc:
                thinking.value = t("ai_setup.test_chat.error_prefix", lang) + str(exc)[:300]
                thinking.color = theme.DANGER
                thinking.italic = False
            page.update()

        page.run_thread(worker)

    send_button.on_click = handle_send
    message_field.on_submit = handle_send

    refresh()

    control = _card(
        page,
        ft.Column(
            spacing=12,
            controls=[
                _section_header(ft.Icons.CHAT_BUBBLE_OUTLINE_ROUNDED, t("ai_setup.test_chat.title", lang)),
                conversation,
                not_ready_note,
                row,
            ],
        ),
    )
    return {"control": control, "refresh": refresh}
