"""صفحه‌ی سیستم پرامپت: ویرایشگر + کتابخونه‌ی نمونه‌های آماده."""

from __future__ import annotations

import flet as ft

from app import theme
from app.data.prompt_templates import default_prompt, templates_for_category
from app.i18n import t
from app.screens import common


def build(page: ft.Page, lang: str, business_mode, current_prompt: str, on_save) -> ft.Control:
    editor = ft.TextField(
        label=t("prompt.editor_label", lang),
        value=current_prompt,
        multiline=True,
        min_lines=8,
        max_lines=14,
        border_radius=10,
    )

    save_hint = ft.Row(
        spacing=6,
        visible=False,
        controls=[
            ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, size=15, color=theme.SUCCESS),
            ft.Text(t("common.saved", lang), size=12, color=theme.SUCCESS),
        ],
    )

    def handle_save(e) -> None:
        on_save(editor.value or "")
        save_hint.visible = True
        page.update()

    def handle_reset(e) -> None:
        editor.value = default_prompt(business_mode, lang)
        save_hint.visible = False
        page.update()

    def make_use_handler(body: str):
        def handler(e):
            editor.value = body
            save_hint.visible = False
            page.update()

        return handler

    template_cards = []
    for tpl in templates_for_category(business_mode):
        title = tpl["title"].get(lang, tpl["title"]["fa"])
        body = tpl["body"].get(lang, tpl["body"]["fa"])
        preview = body if len(body) <= 110 else body[:110].rstrip() + "…"
        template_cards.append(
            ft.Container(
                width=280,
                padding=16,
                border_radius=12,
                bgcolor=theme.card_bgcolor(page),
                border=ft.Border.all(1, theme.border_color(page)),
                content=ft.Column(
                    spacing=8,
                    controls=[
                        ft.Row(
                            spacing=8,
                            controls=[
                                ft.Icon(ft.Icons.DESCRIPTION_OUTLINED, size=16, color=theme.PRIMARY),
                                ft.Text(title, size=14, weight=ft.FontWeight.W_600),
                            ],
                        ),
                        ft.Text(preview, size=12, color=theme.text_secondary(page)),
                        ft.TextButton(
                            content=ft.Row(
                                tight=True,
                                spacing=4,
                                controls=[
                                    ft.Text(t("prompt.use_template", lang), size=12.5),
                                    ft.Icon(ft.Icons.CONTENT_COPY_ROUNDED, size=13),
                                ],
                            ),
                            on_click=make_use_handler(body),
                        ),
                    ],
                ),
            )
        )

    editor_card = common.card(
        page,
        ft.Column(
            spacing=14,
            controls=[
                editor,
                ft.Row(
                    spacing=12,
                    controls=[
                        common.primary_button(t("common.save", lang), handle_save, icon=ft.Icons.SAVE_ROUNDED, width=150),
                        ft.OutlinedButton(t("prompt.reset_default", lang), on_click=handle_reset),
                        save_hint,
                    ],
                ),
            ],
        ),
    )

    return ft.Container(
        expand=True,
        padding=ft.Padding.symmetric(horizontal=32, vertical=24),
        content=ft.Column(
            spacing=20,
            scroll=ft.ScrollMode.AUTO,
            controls=[
                common.page_header(page, ft.Icons.EDIT_NOTE_ROUNDED, t("prompt.title", lang), t("prompt.subtitle", lang)),
                editor_card,
                common.section_header(ft.Icons.AUTO_AWESOME_ROUNDED, t("prompt.templates_title", lang)),
                ft.Text(t("prompt.templates_subtitle", lang), size=12, color=theme.text_secondary(page)),
                ft.Row(spacing=14, wrap=True, controls=template_cards),
            ],
        ),
    )
