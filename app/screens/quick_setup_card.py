"""کارتِ «راه‌اندازیِ سریع» (N3): نوعِ کسب‌وکار را انتخاب کن، پیش‌فرض‌های درستِ ربات یک‌جا اعمال می‌شه."""

from __future__ import annotations

import flet as ft

from app import theme
from app.core import quick_setup
from app.screens import common

_S = {
    "title": ("راه‌اندازیِ سریع", "Quick setup"),
    "intro": ("نوعِ کسب‌وکارت رو انتخاب کن تا تنظیماتِ ربات یک‌جا درست بشه. بعداً هر چیزی رو می‌تونی از تب‌ها عوض کنی.", "Pick your kind of business and the bot is set up in one go. You can change anything later from the tabs."),
    "type": ("کسب‌وکارت چه جوریه؟", "What kind of business is it?"),
    "apply": ("اعمالِ تنظیمات", "Apply settings"),
    "done": ("✅ انجام شد:", "✅ Done:"),
    "same": ("✅ همین الان هم همین‌طور تنظیم شده.", "✅ It's already set up this way."),
    "keeps": ("به توکن‌ها، پرداخت، سؤالات متداول، متن‌ها و بیوگرافی دست نمی‌زنه.", "Tokens, payments, FAQ, messages and the bio are not touched."),
}


def S(key: str, lang: str) -> str:
    fa, en = _S[key]
    return en if lang == "en" else fa


def build(page: ft.Page, lang: str, settings, save_callback, on_applied=None) -> ft.Control:
    secondary = theme.text_secondary(page)
    presets = quick_setup.available(settings)
    current = presets[0]
    dd = ft.Dropdown(
        key="qs_type", label=S("type", lang), border_radius=10, width=380, value=current,
        options=[ft.DropdownOption(key=p, text=quick_setup.title(p, lang)) for p in presets],
    )
    desc = ft.Text(quick_setup.description(current, lang), key="qs_desc", size=12.5, color=secondary)
    note = ft.Text("", key="qs_note", size=12.5, visible=False)

    def on_select(e=None) -> None:
        desc.value = quick_setup.description(dd.value or current, lang)
        note.visible = False
        page.update()

    def on_apply(e=None) -> None:
        choice = dd.value or current
        try:
            changes = quick_setup.apply(settings, choice, lang)
        except ValueError as exc:
            note.value, note.color, note.visible = str(exc), theme.DANGER, True
            page.update()
            return
        save_callback()
        note.value = (S("done", lang) + "\n" + "\n".join("• " + c for c in changes)) if changes else S("same", lang)
        note.color, note.visible = theme.SUCCESS, True
        if on_applied is not None:
            on_applied()
        page.update()

    dd.on_select = on_select
    controls = [
        ft.Text(S("intro", lang), key="qs_intro", size=12.5, color=secondary),
        dd,
        desc,
        ft.Button(key="qs_apply", content=S("apply", lang), icon=ft.Icons.AUTO_FIX_HIGH_ROUNDED, on_click=on_apply),
        note,
        ft.Text(S("keeps", lang), size=11.5, color=secondary),
    ]
    return common.card(
        page,
        ft.ExpansionTile(
            key="sec_quick",
            expanded=True,
            title=ft.Text(S("title", lang), size=14.5, weight=ft.FontWeight.W_600),
            controls=[ft.Container(padding=ft.Padding.only(left=6, right=6, bottom=12), content=ft.Column(spacing=10, controls=controls))],
        ),
        padding=6,
    )
