"""صفحه‌ی انتخاب نوع هوش مصنوعی: API یا محلی."""

from __future__ import annotations

import flet as ft

from app import theme
from app.core import hardware
from app.i18n import t
from app.screens import common

def _keyed(key: str, control):
    control.key = key
    return control


_ICONS = {"api": ft.Icons.CLOUD_QUEUE_ROUNDED, "local": ft.Icons.COMPUTER_ROUNDED}


def _hw_row_inline(page: ft.Page, label: str, value: str) -> ft.Control:
    """ردیف برای مقادیر کوتاه (رم، هسته، فضای دیسک) — کنار هم."""
    return ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        controls=[
            ft.Text(label, size=13, color=theme.text_secondary(page)),
            ft.Text(value, size=13, weight=ft.FontWeight.W_500),
        ],
    )


def _hw_row_stacked(page: ft.Page, label: str, value: str) -> ft.Control:
    """ردیف برای مقادیر بلند (مدل CPU/GPU) — زیر هم تا شکسته نشه."""
    return ft.Column(
        spacing=2,
        controls=[
            ft.Text(label, size=13, color=theme.text_secondary(page)),
            ft.Text(value, size=13, weight=ft.FontWeight.W_500),
        ],
    )


def build_hardware_block(page: ft.Page, lang: str) -> ft.Control:
    hw = hardware.detect()
    ram = f"{hw.ram_gb:.1f} GB" if hw.ram_gb is not None else "—"
    cores = str(hw.cpu_cores) if hw.cpu_cores else "—"
    cpu_model = hw.cpu_model or "—"
    if hw.gpu_model:
        gpu = f"{hw.gpu_model} ({hw.gpu_vram_gb:.1f} GB VRAM)" if hw.gpu_vram_gb is not None else hw.gpu_model
    else:
        gpu = t("ai.local.hw_gpu_none", lang)
    disk = f"{hw.free_disk_gb:.1f} GB" if hw.free_disk_gb is not None else "—"

    return ft.Column(
        spacing=10,
        controls=[
            _hw_row_inline(page, t("ai.local.hw_ram", lang), ram),
            _hw_row_inline(page, t("ai.local.hw_cpu", lang), cores),
            _hw_row_stacked(page, t("ai.local.hw_cpu_model", lang), cpu_model),
            _hw_row_stacked(page, t("ai.local.hw_gpu", lang), gpu),
            _hw_row_inline(page, t("ai.local.hw_disk", lang), disk),
        ],
    )


def build(
    page: ft.Page,
    lang: str,
    initial_mode,
    initial_base_url: str,
    initial_api_key: str,
    initial_model_name: str,
    on_next,
    on_back,
) -> ft.Control:
    selected = {"value": initial_mode}

    base_url_field = ft.TextField(
        key="base_url_field",
        label=t("ai.api.base_url_label", lang),
        hint_text=t("ai.api.base_url_hint", lang),
        value=initial_base_url,
        border_radius=10,
        prefix_icon=ft.Icons.LINK_ROUNDED,
    )
    api_key_field = ft.TextField(
        key="api_key_field",
        label=t("ai.api.key_label", lang),
        hint_text=t("ai.api.key_hint", lang),
        value=initial_api_key,
        password=True,
        can_reveal_password=True,
        border_radius=10,
        prefix_icon=ft.Icons.VPN_KEY_ROUNDED,
    )
    model_name_field = ft.TextField(
        key="model_name_field",
        label=t("ai.api.model_label", lang),
        hint_text=t("ai.api.model_hint", lang),
        value=initial_model_name or "gpt-4o-mini",
        border_radius=10,
        prefix_icon=ft.Icons.SMART_TOY_OUTLINED,
    )
    api_fields = common.card(
        page,
        ft.Column(
            visible=initial_mode == "api",
            spacing=10,
            controls=[
                base_url_field,
                api_key_field,
                model_name_field,
                ft.Text(t("ai.api.model_note", lang), size=12, color=theme.text_secondary(page)),
                ft.Text(t("ai.api.key_saved_note", lang), size=12, color=theme.text_secondary(page)),
            ],
        ),
        padding=18,
    )
    api_fields.key = "api_fields"
    api_fields.width = 340
    api_fields.visible = initial_mode == "api"

    local_info = common.card(
        page,
        ft.Column(
            visible=initial_mode == "local",
            spacing=6,
            controls=[
                build_hardware_block(page, lang),
                ft.Container(height=4),
                ft.Text(t("ai.local.note", lang), size=12, color=theme.text_secondary(page), italic=True),
            ],
        ),
        padding=18,
    )
    local_info.key = "local_info"
    local_info.width = 340
    local_info.visible = initial_mode == "local"

    def render_cards() -> list:
        return [
            _keyed(
                "ai_card_api",
                common.option_card(
                    page,
                    _ICONS["api"],
                    t("ai.api.title", lang),
                    t("ai.api.desc", lang),
                    selected["value"] == "api",
                    lambda e: choose("api"),
                ),
            ),
            _keyed(
                "ai_card_local",
                common.option_card(
                    page,
                    _ICONS["local"],
                    t("ai.local.title", lang),
                    t("ai.local.desc", lang),
                    selected["value"] == "local",
                    lambda e: choose("local"),
                ),
            ),
        ]

    cards_row = ft.Row(spacing=16, wrap=True, alignment=ft.MainAxisAlignment.CENTER, controls=render_cards())

    def choose(mode: str) -> None:
        selected["value"] = mode
        cards_row.controls = render_cards()
        api_fields.visible = mode == "api"
        local_info.visible = mode == "local"
        next_btn.disabled = False
        page.update()

    def handle_next(e) -> None:
        on_next(
            selected["value"],
            base_url_field.value or "",
            api_key_field.value or "",
            model_name_field.value or "gpt-4o-mini",
        )

    next_btn = common.primary_button(t("common.next", lang), handle_next, width=200, disabled=initial_mode is None)
    next_btn.key = "next_button"

    header = ft.Column(
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=6,
        controls=[
            ft.Text(t("ai.title", lang), size=22, weight=ft.FontWeight.W_700),
            ft.Container(
                width=420,
                content=ft.Text(
                    t("ai.subtitle", lang), size=13, color=theme.text_secondary(page), text_align=ft.TextAlign.CENTER
                ),
            ),
        ],
    )

    footer = ft.Row(
        alignment=ft.MainAxisAlignment.CENTER,
        spacing=12,
        controls=[ft.TextButton(key="back_button", content=t("common.back", lang), on_click=lambda e: on_back()), next_btn],
    )

    return common.onboarding_frame(page, 2, 3, [header, cards_row, api_fields, local_info, footer])
