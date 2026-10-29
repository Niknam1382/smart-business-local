"""«عضویتِ اجباریِ کانال» (N13): مشتری تا عضوِ کانال(های) تعیین‌شده نشده، منو/گفتگوی ربات را نمی‌گیرد.

شفاف و بی‌خطر: ربات باید «ادمینِ کانال» باشد تا بتواند عضویت را بپرسد؛ اگه نبود یا بررسی خراب شد، مشتری هرگز قفل نمی‌شود
(مالک هشدار می‌گیرد). مالک و مدیرانِ فعال معافند. دکمه‌ی «تستِ دسترسی» از خودِ ربات می‌پرسد که در کانال ادمین هست یا نه.
"""

from __future__ import annotations

import logging

import flet as ft

from app import theme
from app.core import channel_gate as cg
from app.core.bot_manager import BotManagerError
from app.screens import common

logger = logging.getLogger(__name__)

_S = {
    "title": ("عضویتِ اجباریِ کانال", "Required channel membership"),
    "intro": (
        "مشتری باید اول در کانال(های) زیر عضو بشه، بعد می‌تونه از ربات استفاده کنه. ربات باید «ادمینِ کانال» باشه تا بتونه عضویت رو بپرسه. "
        "اگه بررسی خراب بشه (مثلاً ربات ادمین نباشه) مشتری قفل نمی‌شه و تو خبردار می‌شی. خودت و مدیرها معافید.",
        "Customers must join the channel(s) below before using the bot. The bot must be an admin of the channel so it can check membership. "
        "If the check breaks (e.g. the bot isn't an admin) customers are never locked out and you get notified. You and your managers are exempt.",
    ),
    "enable": ("عضویتِ اجباری فعال باشه", "Require membership"),
    "scope": ("کجا اعمال بشه؟", "Where to apply it?"),
    "scope.both": ("همه‌جا (منو و گفتگو با AI)", "Everywhere (menu and AI chat)"),
    "scope.shop": ("فقط منو/سبد/سفارش", "Menu, cart and orders only"),
    "scope.ai": ("فقط گفتگو با هوش مصنوعی", "AI chat only"),
    "platform": ("پیام‌رسان", "Messenger"),
    "platform.telegram": ("تلگرام", "Telegram"),
    "platform.bale": ("بله", "Bale"),
    "channel": ("کانال", "Channel"),
    "channel_hint": ("@mychannel یا لینکِ عمومی یا شناسه‌ی عددی", "@mychannel, a public link, or a numeric id"),
    "title_label": ("عنوانِ دکمه (اختیاری)", "Button title (optional)"),
    "link": ("لینکِ عضویت (اختیاری)", "Join link (optional)"),
    "link_hint": ("برای کانالِ خصوصی لازمه", "Required for private channels"),
    "add": ("افزودنِ کانال", "Add channel"),
    "test": ("تستِ دسترسی", "Test access"),
    "delete": ("حذف", "Remove"),
    "empty": ("هنوز کانالی اضافه نشده.", "No channels yet."),
    "added": ("کانال اضافه شد. حالا «تستِ دسترسی» رو بزن تا مطمئن بشی ربات ادمینه.", "Channel added. Press “Test access” to make sure the bot is an admin."),
    "removed": ("کانال حذف شد.", "Channel removed."),
    "saved": ("ذخیره شد.", "Saved."),
    "dup": ("این کانال قبلاً اضافه شده.", "This channel is already added."),
    "enabled_empty": ("فعال شد، ولی هنوز کانالی اضافه نکرده‌ای؛ تا اضافه نکنی اثری نداره.", "Turned on, but you haven't added a channel yet, so nothing changes."),
    "test_ok": ("✅ ربات در این کانال ادمین است؛ بررسیِ عضویت کار می‌کند.", "✅ The bot is an admin of this channel; membership checks will work."),
    "test_member": (
        "⚠️ ربات فقط عضوِ این کانال است؛ برای بررسیِ عضویتِ مشتری‌ها باید ادمین بشه.",
        "⚠️ The bot is only a member of this channel; it must be an admin to check customers' membership.",
    ),
    "test_bad": ("❌ ربات به این کانال دسترسی نداره: {detail}\nربات رو «ادمینِ کانال» کن و دوباره امتحان کن.", "❌ The bot cannot access this channel: {detail}\nMake the bot an admin of the channel and try again."),
    "test_no_manager": ("برای تست، اول ربات‌ها رو روشن کن.", "Turn the bots on first to test."),
    "bale_note": (
        "بله: رفتارِ بررسیِ عضویت روی بله به‌اندازه‌ی تلگرام تست نشده؛ اگه خطا بده، مشتری قفل نمی‌شه و تو پیام می‌گیری.",
        "Bale: membership checks on Bale are less battle-tested than Telegram; if they fail, customers are not locked out and you get a message.",
    ),
}


def S(key: str, lang: str, **kw) -> str:
    fa, en = _S[key]
    text = en if lang == "en" else fa
    return text.format(**kw) if kw else text


def build(page: ft.Page, lang: str, settings, save_callback, manager=None) -> ft.Control:
    secondary = theme.text_secondary(page)
    note = ft.Text("", key="rc_note", size=12.5, visible=False, selectable=True)
    list_col = ft.Column(key="rc_list", spacing=6)

    def show(text: str, ok: bool = True) -> None:
        note.value, note.color, note.visible = text, theme.SUCCESS if ok else theme.DANGER, bool(text)
        page.update()

    def current() -> list:
        return cg.load(settings)  # ردیف‌های خرابِ فایل بی‌صدا کنار گذاشته می‌شن

    def store(channels: list) -> None:
        settings.required_channels = [c.as_dict() for c in channels]
        save_callback()

    # ------------------------------------------------------------ فهرست ----
    def render_list() -> None:
        rows = []
        for ch in current():
            def on_test(_e=None, ch=ch) -> None:
                test_access(ch)

            def on_delete(_e=None, ch=ch) -> None:
                store([c for c in current() if c.ref != ch.ref])
                render_list()
                show(S("removed", lang))

            rows.append(
                ft.Row(
                    key=f"rc_row_{ch.platform}_{ch.channel}",
                    spacing=8,
                    wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Text(f"{S('platform.' + ch.platform, lang)} · {ch.label} ({ch.channel})", size=13, weight=ft.FontWeight.W_600),
                        ft.Text(ch.link, size=11.5, color=secondary, selectable=True),
                        ft.OutlinedButton(key=f"rc_test_{ch.platform}_{ch.channel}", content=S("test", lang), on_click=on_test),
                        ft.TextButton(key=f"rc_del_{ch.platform}_{ch.channel}", content=S("delete", lang), on_click=on_delete),
                    ],
                )
            )
        list_col.controls = rows or [ft.Text(S("empty", lang), size=12.5, color=secondary)]

    def test_access(ch: cg.Channel) -> None:
        if manager is None:
            show(S("test_no_manager", lang), False)
            return

        def work() -> None:
            try:
                ok, detail = manager.test_channel_sync(ch.platform, ch.channel)
            except BotManagerError as exc:
                show(str(exc), False)
                return
            except Exception:  # noqa: BLE001 — UI هرگز نباید بشکنه
                logger.exception("تستِ دسترسیِ کانال ناموفق بود")
                show(S("test_bad", lang, detail="—"), False)
                return
            if not ok:
                show(S("test_bad", lang, detail=detail), False)
            elif detail in ("administrator", "creator"):
                show(S("test_ok", lang), True)
            else:
                show(S("test_member", lang), False)

        page.run_thread(work)

    # --------------------------------------------------------- تنظیمات کلی ----
    def on_enabled(_e=None) -> None:
        settings.required_channels_enabled = bool(enabled.value)
        save_callback()
        show(S("enabled_empty", lang) if enabled.value and not current() else S("saved", lang), True)

    def on_scope(_e=None) -> None:
        if scope.value in cg.SCOPES:
            settings.required_channels_scope = scope.value
            save_callback()
            show(S("saved", lang), True)

    scope_value = settings.required_channels_scope if settings.required_channels_scope in cg.SCOPES else cg.SCOPE_BOTH
    enabled = ft.Switch(key="rc_enabled", label=S("enable", lang), value=bool(settings.required_channels_enabled), on_change=on_enabled)
    scope = ft.Dropdown(
        key="rc_scope", label=S("scope", lang), border_radius=10, width=300, value=scope_value, on_select=on_scope,
        options=[ft.DropdownOption(key=k, text=S(f"scope.{k}", lang)) for k in cg.SCOPES],
    )

    # ---------------------------------------------------------- افزودنِ کانال ----
    platform_dd = ft.Dropdown(
        key="rc_platform", label=S("platform", lang), border_radius=10, width=140, value="telegram",
        options=[ft.DropdownOption(key=p, text=S(f"platform.{p}", lang)) for p in cg.PLATFORMS],
    )
    channel_tf = ft.TextField(key="rc_channel", label=S("channel", lang), hint_text=S("channel_hint", lang), border_radius=10, width=250)
    title_tf = ft.TextField(key="rc_title", label=S("title_label", lang), border_radius=10, width=200, max_length=cg.MAX_TITLE)
    link_tf = ft.TextField(key="rc_link", label=S("link", lang), hint_text=S("link_hint", lang), border_radius=10, width=280)

    def on_add(_e=None) -> None:
        try:
            ch = cg.normalize({"platform": platform_dd.value, "channel": channel_tf.value, "title": title_tf.value, "link": link_tf.value})
            existing = current()
            if any(c.ref == ch.ref for c in existing):
                raise cg.ChannelError(S("dup", lang))
            if len(existing) >= cg.MAX_CHANNELS:
                raise cg.ChannelError(f"حداکثر {cg.MAX_CHANNELS} کانال می‌شه گذاشت." if lang != "en" else f"At most {cg.MAX_CHANNELS} channels are allowed.")
        except cg.ChannelError as exc:
            show(str(exc), False)
            return
        store([*existing, ch])
        channel_tf.value = title_tf.value = link_tf.value = ""
        render_list()
        show(S("added", lang), True)

    render_list()
    return common.card(
        page,
        ft.Column(
            key="required_channels_card",
            spacing=10,
            controls=[
                ft.Text(S("title", lang), size=15, weight=ft.FontWeight.W_700),
                ft.Text(S("intro", lang), size=12.5, color=secondary),
                ft.Row(spacing=16, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[enabled, scope]),
                list_col,
                ft.Row(spacing=10, wrap=True, vertical_alignment=ft.CrossAxisAlignment.START, controls=[platform_dd, channel_tf, title_tf, link_tf]),
                ft.FilledButton(key="rc_add", content=S("add", lang), icon=ft.Icons.ADD_ROUNDED, on_click=on_add),
                ft.Text(S("bale_note", lang), size=11.5, color=secondary),
                note,
            ],
        ),
    )
