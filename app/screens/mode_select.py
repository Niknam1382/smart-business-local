"""صفحه‌ی انتخاب نوع کسب‌وکار: فروشگاه یا مشاوره."""

from __future__ import annotations

import flet as ft

from app import theme
from app.i18n import t
from app.screens import common

def _keyed(key: str, control):
    control.key = key
    return control


_ICONS = {"store": ft.Icons.STOREFRONT_ROUNDED, "consultant": ft.Icons.SUPPORT_AGENT_ROUNDED}


def build(page: ft.Page, lang: str, initial_mode, on_next, on_back) -> ft.Control:
    selected = {"value": initial_mode}

    def render_cards() -> list:
        return [
            _keyed(
                "mode_card_store",
                common.option_card(
                    page,
                    _ICONS["store"],
                    t("mode.store.title", lang),
                    t("mode.store.desc", lang),
                    selected["value"] == "store",
                    lambda e: choose("store"),
                ),
            ),
            _keyed(
                "mode_card_consultant",
                common.option_card(
                    page,
                    _ICONS["consultant"],
                    t("mode.consultant.title", lang),
                    t("mode.consultant.desc", lang),
                    selected["value"] == "consultant",
                    lambda e: choose("consultant"),
                ),
            ),
        ]

    cards_row = ft.Row(spacing=16, wrap=True, alignment=ft.MainAxisAlignment.CENTER, controls=render_cards())

    def choose(mode: str) -> None:
        selected["value"] = mode
        cards_row.controls = render_cards()
        next_btn.disabled = False
        page.update()

    next_btn = common.primary_button(
        t("common.next", lang), lambda e: on_next(selected["value"]), width=200, disabled=initial_mode is None
    )
    next_btn.key = "next_button"

    header = ft.Column(
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=6,
        controls=[
            ft.Text(t("mode.title", lang), size=22, weight=ft.FontWeight.W_700),
            ft.Container(
                width=420,
                content=ft.Text(
                    t("mode.subtitle", lang),
                    size=13,
                    color=theme.text_secondary(page),
                    text_align=ft.TextAlign.CENTER,
                ),
            ),
        ],
    )

    footer = ft.Row(
        alignment=ft.MainAxisAlignment.CENTER,
        spacing=12,
        controls=[ft.TextButton(key="back_button", content=t("common.back", lang), on_click=lambda e: on_back()), next_btn],
    )

    return common.onboarding_frame(page, 1, 3, [header, cards_row, footer])
