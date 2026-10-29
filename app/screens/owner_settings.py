"""کارت «کنسولِ مالک» (حالت فروشگاه): اتصالِ چتِ شخصیِ مالک روی تلگرام/بله برای اعلانِ سفارش‌ها
و فرمان‌های /confirm و /reject — بدونِ اینکه مجبور باشی اپ رو باز کنی.

جریان: «ساخت کد اتصال» ← کدِ ۱۰ دقیقه‌ایِ یک‌بارمصرف ← از چتِ شخصی‌ات به رباتِ خودت می‌فرستی:
``/owner <کد>``. (ربات‌ها باید روشن باشن.)
"""

from __future__ import annotations

import flet as ft

from app import theme
from app.i18n import t
from app.screens.common import card, section_header

PLATFORMS = ("telegram", "bale")


def _mask(chat_id: str) -> str:
    return "•••" + chat_id[-3:] if len(chat_id) > 3 else "•••"


def build(page: ft.Page, lang: str, settings, manager) -> ft.Control:
    console = manager.owner_console if manager is not None else None
    if console is None:
        return ft.Container()  # بدونِ مدیر/فروشگاه معنی نداره

    status = {p: ft.Text("", key=f"owner_status_{p}", size=12.5) for p in PLATFORMS}
    code_text = ft.Text("", key="owner_code_text", size=15, weight=ft.FontWeight.W_700, selectable=True, visible=False)
    code_help = ft.Text("", key="owner_code_help", size=12, color=theme.text_secondary(page), visible=False)
    unlink_buttons = {}

    def refresh() -> None:
        chats = console.owner_chats()
        for platform in PLATFORMS:
            name = t(f"owner.platform.{platform}", lang)
            if platform in chats:
                status[platform].value = t("owner.linked", lang, platform=name, chat=_mask(chats[platform]))
                status[platform].color = theme.SUCCESS
            else:
                status[platform].value = t("owner.not_linked", lang, platform=name)
                status[platform].color = theme.text_secondary(page)
            unlink_buttons[platform].visible = platform in chats

    def make_unlink(platform: str):
        def handler(e=None) -> None:
            console.unlink(platform)
            refresh()
            page.update()

        return handler

    def make_code(e=None) -> None:
        code = console.new_link_code()
        code_text.value = f"/owner {code}"
        code_text.visible = True
        code_help.value = t("owner.code_help", lang)
        code_help.visible = True
        page.update()

    for platform in PLATFORMS:
        unlink_buttons[platform] = ft.TextButton(
            key=f"owner_unlink_{platform}", content=t("owner.unlink", lang), on_click=make_unlink(platform), visible=False
        )
    refresh()

    return card(
        page,
        ft.Column(
            spacing=12,
            controls=[
                section_header(ft.Icons.NOTIFICATIONS_ACTIVE_ROUNDED, t("owner.title", lang)),
                ft.Text(t("owner.subtitle", lang), size=12, color=theme.text_secondary(page)),
                *[ft.Row(controls=[status[p], unlink_buttons[p]], alignment=ft.MainAxisAlignment.SPACE_BETWEEN) for p in PLATFORMS],
                ft.OutlinedButton(key="owner_link_btn", content=t("owner.make_code", lang), icon=ft.Icons.LINK_ROUNDED, on_click=make_code),
                code_text,
                code_help,
            ],
        ),
    )
