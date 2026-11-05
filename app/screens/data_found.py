"""صفحه‌ی «داده‌ی قبلی پیدا شد» (N2) — فقط وقتی نمایش داده می‌شه که پوشه‌ی داده از قبل استفاده شده و کاربر هنوز انتخاب نکرده.

دو انتخابِ روشن: «ادامه با داده‌ی قبلی» (هیچ‌چیز تغییر نمی‌کنه) یا «شروعِ تازه» (اول یک پشتیبانِ کامل گرفته می‌شه، بعد همه‌چیز
پاک می‌شه و برنامه از معرفی شروع می‌کنه؛ مدل‌های دانلودشده نگه داشته می‌شن). فقط تعدادها نشان داده می‌شه، نه محتوا.
"""

from __future__ import annotations

import flet as ft

from app import theme
from app.core.data_probe import DataFootprint
from app.i18n import t
from app.screens import common


def build(page: ft.Page, lang: str, footprint: DataFootprint, on_continue, on_fresh_start) -> ft.Control:
    """``on_fresh_start(set_status)`` کارِ سنگین را انجام می‌ده و با ``set_status(text, ok)`` پیام می‌ده."""
    status = ft.Text("", key="found_status", size=12.5, visible=False)
    buttons: list = []

    def set_status(text: str, ok: bool = True) -> None:
        status.value = text
        status.color = theme.SUCCESS if ok else theme.DANGER
        status.visible = bool(text)
        page.update()

    def lock(disabled: bool) -> None:
        for b in buttons:
            b.disabled = disabled

    def handle_continue(e=None) -> None:
        on_continue()

    def handle_fresh(e=None) -> None:
        lock(True)
        set_status(t("found.working", lang), ok=True)

        def work() -> None:
            try:
                on_fresh_start(set_status)
            except Exception as exc:  # noqa: BLE001 — پیامِ روشن، نه کرش
                lock(False)
                set_status(t("found.error", lang, error=str(exc)[:160]), ok=False)

        page.run_thread(work)

    keep = common.primary_button(t("found.continue", lang), handle_continue, width=None)
    keep.key = "found_continue"
    fresh = ft.OutlinedButton(key="found_fresh", content=t("found.fresh", lang), icon=ft.Icons.RESTART_ALT_ROUNDED, on_click=handle_fresh)
    buttons.extend([keep, fresh])

    counts = ", ".join(
        part
        for part in (
            t("found.count_products", lang, n=footprint.products) if footprint.products else "",
            t("found.count_orders", lang, n=footprint.orders) if footprint.orders else "",
            t("found.count_chats", lang, n=footprint.conversations) if footprint.conversations else "",
        )
        if part
    )
    body = common.card(
        page,
        ft.Column(
            spacing=14,
            width=420,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[
                ft.Text(t("found.title", lang), key="found_title", size=17, weight=ft.FontWeight.W_700),
                ft.Text(t("found.body", lang), size=13, color=theme.text_secondary(page)),
                ft.Text(counts or t("found.settings_only", lang), key="found_counts", size=13, weight=ft.FontWeight.W_600),
                ft.Text(str(footprint.data_dir), key="found_path", size=11.5, selectable=True, color=theme.text_secondary(page)),
                keep,
                fresh,
                ft.Text(t("found.fresh_hint", lang), size=11.5, color=theme.text_secondary(page)),
                status,
            ],
        ),
        padding=26,
    )
    hero = ft.Column(horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8, controls=[common.logo_badge(56), ft.Text(t("app.title", lang), size=22, weight=ft.FontWeight.W_800)])
    return common.onboarding_frame(page, 0, 3, [hero, body])
