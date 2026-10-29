"""صفحه‌ی تنظیمات: زبان، نوع کسب‌وکار، نوع هوش مصنوعی، و «داده و ایمنی» (پشتیبان/ریست)."""

from __future__ import annotations

import flet as ft

from app import theme
from app.i18n import t
from app.screens import common, data_safety

_MODE_ICON = {"store": ft.Icons.STOREFRONT_ROUNDED, "consultant": ft.Icons.SUPPORT_AGENT_ROUNDED}
_AI_ICON = {"api": ft.Icons.CLOUD_QUEUE_ROUNDED, "local": ft.Icons.COMPUTER_ROUNDED}


def _row(page: ft.Page, icon: str, title: str, value: str, button_text: str, on_click) -> ft.Control:
    return ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Row(
                spacing=12,
                controls=[
                    ft.Container(
                        width=38,
                        height=38,
                        border_radius=10,
                        bgcolor=f"{theme.PRIMARY}12",
                        alignment=ft.Alignment.CENTER,
                        content=ft.Icon(icon, size=19, color=theme.PRIMARY),
                    ),
                    ft.Column(
                        spacing=2,
                        controls=[
                            ft.Text(title, size=13, color=theme.text_secondary(page)),
                            ft.Text(value, size=14.5, weight=ft.FontWeight.W_600),
                        ],
                    ),
                ],
            ),
            ft.OutlinedButton(button_text, on_click=on_click),
        ],
    )


def build(
    page: ft.Page,
    lang: str,
    state,
    on_change_mode,
    on_change_ai,
    on_change_language,
    on_data_changed=None,
    manager=None,
    notice: str = "",
) -> ft.Control:
    business_mode = state.business_mode
    ai_mode = state.ai_mode
    mode_label = t(f"mode.{business_mode}.title", lang) if business_mode else "—"
    ai_label = t(f"ai.{ai_mode}.title", lang) if ai_mode else "—"

    language_card = common.card(
        page,
        ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Row(
                    spacing=12,
                    controls=[
                        ft.Container(
                            width=38,
                            height=38,
                            border_radius=10,
                            bgcolor=f"{theme.PRIMARY}12",
                            alignment=ft.Alignment.CENTER,
                            content=ft.Icon(ft.Icons.LANGUAGE_ROUNDED, size=19, color=theme.PRIMARY),
                        ),
                        ft.Column(
                            spacing=2,
                            controls=[
                                ft.Text(t("settings.language", lang), size=13, color=theme.text_secondary(page)),
                                ft.Text("فارسی" if lang == "fa" else "English", size=14.5, weight=ft.FontWeight.W_600),
                            ],
                        ),
                    ],
                ),
                ft.Row(
                    spacing=6,
                    controls=[
                        ft.OutlinedButton(
                            "فارسی",
                            style=ft.ButtonStyle(bgcolor=f"{theme.ACCENT}22" if lang == "fa" else None),
                            on_click=lambda e: on_change_language("fa"),
                        ),
                        ft.OutlinedButton(
                            "English",
                            style=ft.ButtonStyle(bgcolor=f"{theme.ACCENT}22" if lang == "en" else None),
                            on_click=lambda e: on_change_language("en"),
                        ),
                    ],
                ),
            ],
        ),
    )

    mode_card = common.card(
        page,
        _row(
            page,
            _MODE_ICON.get(business_mode, ft.Icons.STOREFRONT_ROUNDED),
            t("settings.business_mode", lang),
            mode_label,
            t("common.change", lang),
            lambda e: on_change_mode(),
        ),
    )

    ai_card = common.card(
        page,
        _row(
            page,
            _AI_ICON.get(ai_mode, ft.Icons.SMART_TOY_OUTLINED),
            t("settings.ai_mode", lang),
            ai_label,
            t("common.change", lang),
            lambda e: on_change_ai(),
        ),
    )

    controls = [
        common.page_header(page, ft.Icons.SETTINGS_OUTLINED, t("settings.title", lang)),
        language_card,
        mode_card,
        ai_card,
    ]
    if on_data_changed is not None:  # کارتِ داده‌وایمنی فقط وقتی که main.py بتونه بعدِ ریست/بازگردانی صفحه رو نو کنه
        controls.append(
            data_safety.build(page, lang, state, on_data_changed=on_data_changed, manager=manager, notice=notice)
        )

    return ft.Container(
        expand=True,
        padding=ft.Padding.symmetric(horizontal=32, vertical=24),
        content=ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=18, controls=controls),
    )
