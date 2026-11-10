"""صفحه‌ی «مدیران» (N11): افزودنِ کارمند با لینکِ دعوت/QR یا شناسه‌ی عددی، نقش‌ها، فعال/غیرفعال/حذف و تاریخچه‌ی کارها.

مالک همان حسابی است که با کدِ «تنظیماتِ ربات» ثبت شده و اینجا فقط نمایش داده می‌شه. هر مدیر از داخلِ تلگرام با ``/admin`` به
پنلِ دکمه‌ایِ مخصوصِ نقشش می‌رسه؛ همه‌ی کنترل‌های دسترسی سمتِ سرورِ ربات انجام می‌شه (``app/core/admin_panel.py``).
مدیر را می‌توان روی هر دو پیام‌رسان اضافه کرد (تلگرام یا بله): همان شناسه‌ی عددی، همان دعوتِ یک‌بارمصرف،و `/admin` روی همان پیام‌رسان پنلِ دکمه‌ایِ مخصوصِ نقشش را می‌دهد.
"""

from __future__ import annotations


import flet as ft

from app import theme
from app.core import jalali
from app.core import admins as am
from app.core import qr
from app.i18n import STRINGS, t
from app.screens import common
from app.screens.common import card, page_header, screen_frame

PLATFORMS = ("telegram", "bale")  # هر دو پیام‌رسانِ گفتگو; کلیدِ جدولِ مدیران (پلتفرم، شناسه) است
_LEGACY_LABELS = {"telegram": "chats.platform.telegram", "bale": "chats.platform.bale"}  # برچسبِ داده‌هایِ قدیمی
_AUDIT_ROWS = 30


def _stamp(ts: int, lang: str) -> str:
    return jalali.format_dt(ts) if ts else t("admins.never", lang)


def build(page: ft.Page, lang: str, manager, state) -> ft.Control:
    admins = manager.admins
    secondary = theme.text_secondary(page)
    ui = {"platform": "telegram", "role": am.ROLE_MANAGER, "invite": None, "notice": "", "ok": True, "armed": None}
    body = ft.Column(spacing=theme.SPACE_MD)

    def platform_label(platform: str) -> str:
        key = _LEGACY_LABELS.get(platform)
        return t(key, lang) if key else platform

    def refresh() -> None:
        body.controls = view()
        try:
            page.update()
        except Exception:  # noqa: BLE001
            pass

    def say(message: str, ok: bool = True) -> None:
        ui["notice"], ui["ok"] = message, ok

    def dropdown(key: str, label: str, options: list, value: str, handler, width: int = 260) -> ft.Dropdown:
        return ft.Dropdown(key=key, label=label, border_radius=10, width=width, value=value, on_select=handler, options=[ft.DropdownOption(key=k, text=txt) for k, txt in options])

    # ------------------------------------------------------------- افزودن ----

    def on_role(e) -> None:
        ui["role"] = e.control.value if e.control.value in am.ASSIGNABLE_ROLES else am.ROLE_MANAGER
        ui["invite"] = None
        refresh()

    def on_platform(e) -> None:
        ui["platform"] = e.control.value if e.control.value in PLATFORMS else "telegram"
        ui["invite"] = None
        refresh()

    def bot_username(platform: str) -> str:
        try:
            status = manager.get_status().platforms.get(platform)
            return (status.username or "") if status is not None else ""
        except Exception:  # noqa: BLE001
            return ""

    def on_invite(_e=None) -> None:
        username = bot_username(ui["platform"])
        if not username:
            ui["invite"] = None
            say(t("admins.invite_need_bot", lang), ok=False)
            refresh()
            return
        token = admins.create_invite(ui["platform"], ui["role"])
        link = am.invite_link(ui["platform"], username, token)
        ui["invite"] = {"link": link, "cmd": am.start_command(token), "qr": qr.png_bytes(link)}
        say("")
        refresh()

    def copier(text: str):
        def on_click(_e=None) -> None:
            say(t("admins.copied", lang) if common.copy_text(page, text) else "")
            refresh()

        return on_click

    id_field = ft.TextField(key="admins_id", label=t("admins.id", lang), border_radius=10, width=200, keyboard_type=ft.KeyboardType.NUMBER)
    name_field = ft.TextField(key="admins_id_name", label=t("admins.id_name", lang), border_radius=10, width=200)

    def on_add_id(_e=None) -> None:
        try:
            admins.add_by_id(ui["platform"], (id_field.value or "").strip(), ui["role"], (name_field.value or "").strip())
        except ValueError:
            say(t("admins.id_invalid", lang), ok=False)
        else:
            id_field.value = name_field.value = ""
            say(t("admins.added_pending", lang))
        refresh()

    def add_card() -> ft.Control:
        invite = ui["invite"]
        controls: list = [
            common.section_header(ft.Icons.PERSON_ADD_ROUNDED, t("admins.add_title", lang)),
            ft.Row(
                wrap=True, spacing=theme.SPACE_MD, run_spacing=theme.SPACE_MD,
                controls=[
                    dropdown("admins_platform", t("admins.platform", lang),
                             [(p, platform_label(p)) for p in PLATFORMS], ui["platform"], on_platform, width=200),
                    dropdown("admins_role", t("admins.role", lang), [(r, t(f"admins.role.{r}", lang)) for r in am.ASSIGNABLE_ROLES], ui["role"], on_role),
                    common.secondary(t("admins.invite", lang), key="admins_invite", icon=ft.Icons.QR_CODE_2_ROUNDED, size="sm", on_click=on_invite),
                ],
            ),
        ]
        if invite:
            controls += [
                ft.Text(t("admins.invite_hint", lang), size=12, color=secondary),
                ft.Row(
                    spacing=16, vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[
                        ft.Image(key="admins_qr", src=invite["qr"], width=170, height=170),
                        ft.Column(
                            expand=True, spacing=6,
                            controls=[
                                ft.Text(t("admins.invite_link", lang), size=12, color=secondary),
                                ft.Text(invite["link"], key="admins_invite_link", size=12.5, selectable=True),
                                common.secondary(t("admins.copy", lang), key="admins_copy_link", icon=ft.Icons.CONTENT_COPY_ROUNDED, size="sm", on_click=copier(invite["link"])),
                                ft.Text(t("admins.invite_cmd", lang), size=12, color=secondary),
                                ft.Text(invite["cmd"], key="admins_invite_cmd", size=12.5, selectable=True),
                                common.secondary(t("admins.copy", lang), key="admins_copy_cmd", icon=ft.Icons.CONTENT_COPY_ROUNDED, size="sm", on_click=copier(invite["cmd"])),
                            ],
                        ),
                    ],
                ),
            ]
        controls += [
            ft.Divider(),
            ft.Text(t("admins.by_id", lang), size=14, weight=ft.FontWeight.W_600),
            ft.Text(t("admins.by_id_hint", lang), size=12, color=secondary),
            ft.Row(wrap=True, spacing=10, alignment=ft.MainAxisAlignment.START, controls=[id_field, name_field, common.secondary(t("admins.add_id", lang), key="admins_add_id", icon=ft.Icons.PERSON_ADD_ROUNDED, size="sm", on_click=on_add_id)]),
        ]
        return card(page, ft.Column(spacing=10, controls=controls))

    # ----------------------------------------------------------------- فهرست ----

    def owner_card() -> ft.Control:
        chats = dict(getattr(state, "owner_chats", {}) or {})
        lines = [f"{platform_label(p)}: {chat}" for p, chat in chats.items()]
        text = " · ".join(lines) if lines else t("admins.owner_none", lang)
        return card(page, ft.Column(spacing=4, controls=[ft.Text(t("admins.owner", lang), size=14, weight=ft.FontWeight.W_700), ft.Text(text, key="admins_owner", size=12.5, color=secondary if not lines else None)]))

    def admin_row(a: am.Admin) -> ft.Control:
        tag = f"{a.platform}_{a.user_id}"

        def on_role_change(e, a=a) -> None:
            if e.control.value in am.ASSIGNABLE_ROLES:
                admins.set_role(a.platform, a.user_id, e.control.value)
            refresh()

        def on_toggle(_e=None, a=a) -> None:
            admins.set_active(a.platform, a.user_id, a.status != am.STATUS_ACTIVE)
            refresh()

        def on_remove(_e=None, a=a) -> None:
            if ui["armed"] != (a.platform, a.user_id):
                ui["armed"] = (a.platform, a.user_id)
            else:
                admins.remove(a.platform, a.user_id)
                ui["armed"] = None
            refresh()

        sub = " · ".join(p for p in ((f"@{a.username}" if a.username else ""), a.user_id, platform_label(a.platform)) if p)
        buttons: list = []
        if a.status != am.STATUS_PENDING:
            buttons.append(common.text(t("admins.disable" if a.status == am.STATUS_ACTIVE else "admins.enable", lang), key=f"admin_toggle_{tag}", on_click=on_toggle))
        buttons.append(common.text(t("admins.remove_confirm" if ui["armed"] == (a.platform, a.user_id) else "admins.remove", lang), key=f"admin_remove_{tag}", on_click=on_remove))
        return ft.Container(
            key=f"admin_row_{tag}", padding=ft.Padding.symmetric(horizontal=14, vertical=10), border_radius=12,
            bgcolor=theme.card_bgcolor(page), border=ft.Border.all(1, theme.border_color(page)),
            content=ft.Row(
                wrap=True, spacing=12, run_spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Column(expand=True, spacing=2, tight=True, controls=[
                        ft.Text(a.display_name, size=14, weight=ft.FontWeight.W_600),
                        ft.Text(sub, size=12, color=secondary),
                        ft.Text(t(f"admins.status.{a.status}", lang) + " · " + t("admins.last_active", lang, when=_stamp(a.last_active_ts, lang)), key=f"admin_status_{tag}", size=12, color=theme.SUCCESS if a.status == am.STATUS_ACTIVE else secondary),
                    ]),
                    dropdown(f"admin_role_{tag}", t("admins.role", lang), [(r, t(f"admins.role_short.{r}", lang)) for r in am.ASSIGNABLE_ROLES], a.role, on_role_change, 150),
                    *buttons,
                ],
            ),
        )

    def audit_card() -> ft.Control:
        rows = admins.recent_audit(_AUDIT_ROWS)
        controls: list = [ft.Text(t("admins.audit_title", lang), size=14, weight=ft.FontWeight.W_700)]
        if not rows:
            controls.append(ft.Text(t("admins.audit_empty", lang), size=12.5, color=secondary))
        for row in rows:
            label = t(f"admins.audit.{row['action']}", lang) if f"admins.audit.{row['action']}" in STRINGS else row["action"]
            who = row["actor"] or "—"
            controls.append(ft.Text(f"{_stamp(row['ts'], lang)} · {who} · {label}" + (f" · {row['detail']}" if row["detail"] else ""), size=12, color=secondary))
        return card(page, ft.Column(spacing=4, controls=controls))

    def view() -> list:
        listed = admins.list()
        out: list = [owner_card(), add_card()]
        if ui["notice"]:
            out.append(ft.Text(ui["notice"], key="admins_notice", size=12.5, color=theme.SUCCESS if ui["ok"] else theme.DANGER))
        out.append(ft.Text(t("admins.list_title", lang), size=15, weight=ft.FontWeight.W_700))
        out.extend([admin_row(a) for a in listed] or [ft.Text(t("admins.empty", lang), key="admins_empty", size=12.5, color=secondary)])
        out.append(audit_card())
        return out

    body.controls = view()
    return screen_frame(page, page_header(page, ft.Icons.ADMIN_PANEL_SETTINGS_ROUNDED, t("admins.title", lang), t("admins.subtitle", lang)), [body])
