"""صفحه‌ی خوش‌آمدگویی و دریافت اسم کاربر (اولین قدم آنبوردینگ)."""

from __future__ import annotations

import flet as ft

from app import theme
from app.i18n import t
from app.screens import common


def build(page: ft.Page, lang: str, initial_name: str, on_next) -> ft.Control:
    error_text = ft.Text("", color=theme.DANGER, size=12, visible=False)

    name_field = ft.TextField(
        key="name_field",
        label=t("welcome.name_label", lang),
        hint_text=t("welcome.name_hint", lang),
        value=initial_name,
        autofocus=True,
        border_radius=10,
        prefix_icon=ft.Icons.PERSON_OUTLINE_ROUNDED,
    )

    def handle_next(e) -> None:
        name = (name_field.value or "").strip()
        if not name:
            error_text.value = t("welcome.name_error", lang)
            error_text.visible = True
            page.update()
            return
        on_next(name)

    name_field.on_submit = handle_next

    hero = ft.Column(
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=8,
        controls=[
            common.logo_badge(64),
            ft.Container(height=2),
            ft.Text(t("app.title", lang), size=26, weight=ft.FontWeight.W_800),
            ft.Container(
                width=360,
                content=ft.Text(
                    t("app.tagline", lang),
                    size=13,
                    color=theme.text_secondary(page),
                    text_align=ft.TextAlign.CENTER,
                ),
            ),
        ],
    )

    body_card = common.card(
        page,
        ft.Column(
            spacing=14,
            width=340,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[
                ft.Text(t("welcome.title", lang), size=17, weight=ft.FontWeight.W_600),
                ft.Text(t("welcome.intro_body", lang), size=13, color=theme.text_secondary(page)),
                ft.Container(height=2),
                name_field,
                error_text,
                common.primary_button(t("common.next", lang), handle_next, width=None),
            ],
        ),
        padding=26,
    )

    return common.onboarding_frame(page, 0, 3, [hero, body_card])
