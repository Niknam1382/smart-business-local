"""ویرایشگرِ «پیام‌های ربات» (N3) — ساده و بدونِ اصطلاحِ فنی.

* پیام‌ها با عنوانِ فارسیِ ساده و «کِی نمایش داده می‌شه» معرفی می‌شن؛ کلیدِ فنی هرگز دیده نمی‌شه.
* متغیرها «{شماره‌ی سفارش}» نشان داده می‌شن و با دکمه‌ی «درجِ متغیر» وارد می‌شن؛ پیش‌نمایشِ زنده با مقدارِ نمونه.
* فقط پیام‌های «پایه» (≈ ۱۴) پیش‌فرض دیده می‌شن؛ بقیه پشتِ سوئیچِ «پیشرفته».
"""

from __future__ import annotations

import flet as ft

from app import theme
from app.core import shop_text_meta as meta
from app.core import shop_texts
from app.screens import common

_S = {
    "title": ("پیام‌های ربات", "Bot messages"),
    "intro": (
        "پیام‌هایی که ربات به مشتری می‌ده رو اینجا با لحنِ فروشگاهِ خودت عوض کن. فقط پیام‌های مهم نمایش داده می‌شه؛ بقیه پشتِ «پیشرفته»‌ان.",
        "Change the messages the bot sends to customers into your shop's own voice. Only the important ones are shown; the rest are under “Advanced”.",
    ),
    "which": ("کدوم پیام؟", "Which message?"),
    "lang": ("زبانِ این متن", "Language of this text"),
    "advanced": ("نمایشِ همه‌ی پیام‌ها (پیشرفته)", "Show all messages (advanced)"),
    "when": ("کِی نشون داده می‌شه: {when}", "When it's shown: {when}"),
    "default": ("متنِ پیش‌فرض", "Default text"),
    "custom": ("متنِ تو (خالی = پیش‌فرض)", "Your text (empty = default)"),
    "vars": ("متغیرهای قابل‌استفاده (روی هر کدوم بزن تا وارد بشه)", "Variables you can use (tap one to insert it)"),
    "no_vars": ("این پیام متغیری نداره.", "This message has no variables."),
    "preview": ("پیش‌نمایش (با مقدارِ نمونه)", "Preview (with sample values)"),
    "save": ("ذخیره", "Save"),
    "reset": ("برگشت به پیش‌فرض", "Reset to default"),
    "saved": ("✅ ذخیره شد.", "✅ Saved."),
    "invalid": ("متن معتبر نیست.", "This text isn't valid."),
}


def S(key: str, lang: str, **kw) -> str:
    fa, en = _S[key]
    text = en if lang == "en" else fa
    return text.format(**kw) if kw else text


def build(page: ft.Page, lang: str, settings, save_callback) -> ft.Control:
    secondary = theme.text_secondary(page)
    state = {"advanced": False}

    def option_keys() -> list:
        return meta.all_keys(None if state["advanced"] else meta.LEVEL_BASIC)

    def options() -> list:
        return [ft.DropdownOption(key=k, text=f"{meta.group_title(meta.meta(k).group, lang)} — {meta.meta(k, lang).title}") for k in option_keys()]

    first = option_keys()[0]
    key_dd = ft.Dropdown(key="txt_key", label=S("which", lang), border_radius=10, width=440, value=first, options=options())
    lang_dd = ft.Dropdown(
        key="txt_lang", label=S("lang", lang), border_radius=10, width=180, value="en" if lang == "en" else "fa",
        options=[ft.DropdownOption(key="fa", text="فارسی"), ft.DropdownOption(key="en", text="English")],
    )
    adv = ft.Switch(key="txt_advanced", label=S("advanced", lang), value=False)
    title = ft.Text("", key="txt_title", size=14, weight=ft.FontWeight.W_700)
    when = ft.Text("", key="txt_when", size=12, color=secondary)
    default_text = ft.Text("", key="txt_default", size=12.5, selectable=True, color=secondary)
    hint = ft.Text("", key="txt_hint", size=11.5, color=secondary)
    var_row = ft.Row(key="txt_vars", spacing=6, wrap=True)
    override = ft.TextField(key="txt_override", label=S("custom", lang), border_radius=10, multiline=True, min_lines=2, max_lines=8)
    preview = ft.Text("", key="txt_preview", size=13, selectable=True)
    note = ft.Text("", key="txt_note", size=12, visible=False)

    def cur_key() -> str:
        return key_dd.value or first

    def cur_lang() -> str:
        return lang_dd.value or "fa"

    def show_note(text: str, ok: bool) -> None:
        note.value, note.color, note.visible = text, (theme.SUCCESS if ok else theme.DANGER), bool(text)

    def render_preview() -> None:
        key = cur_key()
        text = (override.value or "").strip()
        shown = text or meta.to_display(key, shop_texts.default(key, cur_lang()), lang)
        error = meta.friendly_error(key, shown, lang)
        if error:
            preview.value, preview.color = error, theme.DANGER
        else:
            preview.value, preview.color = meta.preview(key, shown, lang) or "", None

    def insert_var(label: str) -> None:
        override.value = (override.value or "") + "{" + label + "}"
        render_preview()
        page.update()

    def load(e=None) -> None:
        key, text_lang = cur_key(), cur_lang()
        m = meta.meta(key, lang)
        title.value = m.title
        when.value = S("when", lang, when=m.when)
        default_text.value = meta.to_display(key, shop_texts.default(key, text_lang), lang)
        variables = meta.vars_for(key, lang)
        hint.value = S("vars", lang) if variables else S("no_vars", lang)
        var_row.controls = [
            ft.OutlinedButton(key=f"txt_var_{v.name}", content="{" + v.label + "}", tooltip=f"{v.example}", on_click=lambda e, label=v.label: insert_var(label))
            for v in variables
        ]
        stored = ((settings.bot_texts or {}).get(text_lang) or {}).get(key, "")
        override.value = meta.to_display(key, stored, lang) if stored else ""
        show_note("", True)
        render_preview()
        page.update()

    def on_toggle_advanced(e=None) -> None:
        state["advanced"] = bool(adv.value)
        key_dd.options = options()
        if cur_key() not in option_keys():
            key_dd.value = option_keys()[0]
        load()

    def on_override_change(e=None) -> None:
        render_preview()
        page.update()

    def save(e=None) -> None:
        key, text_lang = cur_key(), cur_lang()
        display = (override.value or "").strip()
        if display:
            error = meta.friendly_error(key, display, lang)
            if error:
                show_note(error, False)
                page.update()
                return
        try:
            shop_texts.set_override(settings, key, text_lang, meta.from_display(key, display, lang))
        except shop_texts.TextError as exc:
            show_note(str(exc) or S("invalid", lang), False)
            page.update()
            return
        save_callback()
        show_note(S("saved", lang), True)
        render_preview()
        page.update()

    def reset(e=None) -> None:
        override.value = ""
        save()

    key_dd.on_select = lang_dd.on_select = load
    adv.on_change = on_toggle_advanced
    override.on_change = on_override_change
    load_controls = [
        ft.Text(S("intro", lang), key="txt_intro", size=12.5, color=secondary),
        ft.Row(spacing=10, wrap=True, controls=[key_dd, lang_dd]),
        adv,
        title,
        when,
        ft.Text(S("default", lang), size=12, weight=ft.FontWeight.W_600),
        default_text,
        hint,
        var_row,
        override,
        ft.Text(S("preview", lang), size=12, weight=ft.FontWeight.W_600),
        preview,
        ft.Row(spacing=8, controls=[ft.Button(key="txt_save", content=S("save", lang), on_click=save), ft.TextButton(key="txt_reset", content=S("reset", lang), on_click=reset)]),
        note,
    ]
    load()
    return common.card(
        page,
        ft.ExpansionTile(
            key="sec_texts",
            expanded=False,
            title=ft.Text(S("title", lang), size=14.5, weight=ft.FontWeight.W_600),
            controls=[ft.Container(padding=ft.Padding.only(left=6, right=6, bottom=12), content=ft.Column(spacing=10, controls=load_controls))],
        ),
        padding=6,
    )
