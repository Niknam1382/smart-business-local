"""صفحه‌ی «سیستم پرامپت» — قلبِ هوشِ ربات، یک‌جا و شفاف.

چهار بخش: شخصیتِ ربات (ویرایش‌پذیر) · قالب‌های آماده · قوانینی که برنامه همیشه اضافه می‌کند
(فقط‌خواندنی، تا مالک بداند چه چیزی تضمین شده) · پیش‌نمایشِ همان چیزی که مدل واقعاً می‌گیرد.
"""

from __future__ import annotations

import flet as ft

from app import theme
from app.core import prompt_kit
from app.data.prompt_templates import default_prompt, templates_for_category
from app.i18n import t
from app.screens import common

PREVIEW_LIMIT = 1400


def build(page: ft.Page, lang: str, settings, on_save, product_store=None, order_store=None) -> ft.Control:
    store_mode = getattr(settings, "business_mode", "") == "store"
    initial = getattr(settings, "system_prompt", "") or ""
    editor = ft.TextField(
        key="ps_editor",
        label=t("prompt.editor_label", lang),
        value=initial,
        multiline=True,
        min_lines=10,
        max_lines=20,
        border_radius=12,
        max_length=prompt_kit.MAX_OWNER_PROMPT,
        on_change=lambda e: refresh(),
    )
    counter = ft.Text("", key="ps_counter", size=11.5, color=theme.text_secondary(page))
    warnings_box = ft.Column(spacing=6, key="ps_warnings", visible=False)
    saved = ft.Text("", key="ps_saved", size=12, color=theme.SUCCESS, visible=False)
    preview = ft.Markdown("", key="ps_preview", selectable=True)
    state = {"full": False}

    def owner_text() -> str:
        return editor.value or ""

    def assembled() -> str:
        text = prompt_kit.build_system_prompt(
            settings,
            store_mode=store_mode,
            product_store=product_store,
            order_store=order_store,
            display_name="",
            owner_prompt=owner_text(),
        )
        if state["full"] or len(text) <= PREVIEW_LIMIT:
            return text
        return text[:PREVIEW_LIMIT].rstrip() + "\n\n…"

    def refresh() -> None:
        text = owner_text()
        counter.value = f"{len(text)} / {prompt_kit.MAX_OWNER_PROMPT}"
        found = prompt_kit.owner_prompt_warnings(text, lang)
        warnings_box.controls = [
            ft.Row(
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.START,
                controls=[
                    ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, size=15, color=theme.WARNING),
                    ft.Text(warn, size=11.5, color=theme.text_secondary(page), expand=True),
                ],
            )
            for warn in found
        ]
        warnings_box.visible = bool(found)
        preview.value = assembled()
        saved.visible = False
        page.update()

    def handle_save(e) -> None:
        on_save(owner_text())
        saved.value = t("common.saved", lang)
        saved.visible = True
        refresh()
        saved.visible = True
        page.update()

    def handle_reset(e) -> None:
        editor.value = default_prompt(getattr(settings, "business_mode", "") or "consultant", lang)
        refresh()

    def use_template(body: str):
        def handler(e) -> None:
            editor.value = body
            refresh()

        return handler

    def toggle_preview(e) -> None:
        state["full"] = not state["full"]
        preview_button.text = t("prompt.show_short", lang) if state["full"] else t("prompt.show_full", lang)
        refresh()

    preview_button = common.text(t("prompt.show_full", lang), key="ps_toggle", on_click=toggle_preview)

    template_cards = []
    for tpl in templates_for_category(getattr(settings, "business_mode", "")):
        title = tpl["title"].get(lang, tpl["title"]["fa"])
        body = tpl["body"].get(lang, tpl["body"]["fa"])
        blurb = (tpl.get("blurb") or {}).get(lang, (tpl.get("blurb") or {}).get("fa", ""))
        short = body if len(body) <= 150 else body[:150].rstrip() + "…"
        template_cards.append(
            ft.Container(
                key=f"ps_tpl_{tpl['id']}",
                width=300,
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
                                ft.Text(title, size=14, weight=ft.FontWeight.W_600, expand=True),
                            ],
                        ),
                        ft.Text(blurb, size=11.5, color=theme.text_secondary(page)),
                        ft.Text(short, size=11.5, color=theme.text_secondary(page)),
                        ft.TextButton(
                            height=theme.BTN_SM,
                            key=f"ps_use_{tpl['id']}",
                            content=ft.Row(
                                tight=True,
                                spacing=4,
                                controls=[
                                    ft.Text(t("prompt.use_template", lang), size=12.5),
                                    ft.Icon(ft.Icons.ARROW_FORWARD_ROUNDED, size=13),
                                ],
                            ),
                            on_click=use_template(body),
                        ),
                    ],
                ),
            )
        )

    rules_rows = [
        ft.Row(
            key=f"ps_rule_{item['id']}",
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.START,
            controls=[
                ft.Icon(ft.Icons.LOCK_OUTLINED, size=14, color=theme.text_secondary(page)),
                ft.Column(
                    spacing=2,
                    expand=True,
                    controls=[
                        ft.Text(item["title"], size=13, weight=ft.FontWeight.W_600),
                        ft.Text(item["why"], size=11.5, color=theme.text_secondary(page)),
                    ],
                ),
            ],
        )
        for item in prompt_kit.segment_summary(lang)
    ]

    editor_card = common.card(
        page,
        ft.Column(
            spacing=12,
            controls=[
                ft.Text(t("prompt.persona_title", lang), size=14, weight=ft.FontWeight.W_600),
                ft.Text(t("prompt.persona_hint", lang), size=11.5, color=theme.text_secondary(page)),
                editor,
                ft.Row(spacing=10, controls=[counter, saved]),
                warnings_box,
                ft.Row(
                    spacing=12,
                    controls=[
                        common.primary_button(t("common.save", lang), handle_save, icon=ft.Icons.SAVE_ROUNDED, width=150),
                        common.secondary(t("prompt.reset_default", lang), key="ps_reset", on_click=handle_reset),
                    ],
                ),
            ],
        ),
    )

    return common.screen_frame(
        page,
        common.page_header(page, ft.Icons.EDIT_NOTE_ROUNDED, t("prompt.title", lang), t("prompt.subtitle", lang)),
        [
            editor_card,
            common.section_header(ft.Icons.AUTO_AWESOME_ROUNDED, t("prompt.templates_title", lang)),
            ft.Text(t("prompt.templates_subtitle", lang), size=12, color=theme.text_secondary(page)),
            ft.Row(spacing=14, wrap=True, controls=template_cards),
            common.section_header(ft.Icons.SHIELD_OUTLINED, t("prompt.rules_title", lang)),
            ft.Text(t("prompt.rules_subtitle", lang), size=11.5, color=theme.text_secondary(page)),
            common.card(page, ft.Column(spacing=12, controls=rules_rows)),
            common.section_header(ft.Icons.VISIBILITY_OUTLINED, t("prompt.preview_title", lang)),
            ft.Text(t("prompt.preview_subtitle", lang), size=11.5, color=theme.text_secondary(page)),
            common.card(page, ft.Column(spacing=10, controls=[ft.Row([preview_button]), preview])),
        ],
    )
