"""صفحه‌ی «درباره» (N15 + N14a): نسخه و بررسیِ به‌روزرسانی، سازنده، گزارشِ مشکل و فرمِ کوچکِ حمایتِ اختیاری.

فرمِ حمایت فقط همین‌جاست (نه در رباتِ مشتری): مبلغِ «تومان» و پیام را کاربر خودش تایپ می‌کنه (بدونِ مبلغ/پیامِ آماده)،
لینکِ وب‌اینتنتِ دارمت ساخته و در مرورگر باز می‌شه؛ برنامه هیچ داده‌ای نمی‌فرسته و توکنِ API ای ندارد.
"""

from __future__ import annotations

import flet as ft

from app import branding, theme
from app.core import about_info, support_link, updater
from app.i18n import t
from app.screens import common
from app.version import __version__


def build(page: ft.Page, lang: str, state, save, checker=None, version: str = __version__, can_install=None, on_install=None) -> ft.Control:
    secondary = theme.text_secondary(page)

    # ------------------------------------------------------------ نسخه و به‌روزرسانی ----
    check_result = ft.Text("", key="about_check_result", size=12.5, color=secondary, visible=False)
    update_link = ft.TextButton(
        key="about_update_link", content=t("about.update_open", lang), visible=False,
        on_click=lambda e: common.open_url(page, str(update_link.data or "")),
    )

    install_btn = ft.OutlinedButton(
        key="about_update_install", content=t("update.install", lang), visible=False,
        on_click=lambda e: on_install(install_btn.data) if on_install is not None and install_btn.data is not None else None,
    )

    def show_result(text: str, ok: bool = True) -> None:
        check_result.value = text
        check_result.color = theme.SUCCESS if ok else secondary
        check_result.visible = True

    def on_check(e=None) -> None:
        if checker is None:
            return
        show_result(t("about.checking", lang), ok=False)
        update_link.visible = False
        install_btn.visible = False
        page.update()

        def work() -> None:
            result = checker.check(force=True)
            if result.status == updater.STATUS_UPDATE and result.info is not None:
                show_result(t("about.update_available", lang, version=result.info.version))
                update_link.data = result.info.html_url
                update_link.visible = True
                install_btn.data = result.info
                install_btn.visible = bool(on_install is not None and can_install is not None and can_install(result.info))  # N14b
            elif result.status == updater.STATUS_CURRENT:
                show_result(t("about.up_to_date", lang, version=version))
            else:
                show_result(t("about.check_failed", lang), ok=False)
            page.update()

        page.run_thread(work)

    def on_auto(e) -> None:
        state.update_check_enabled = bool(auto_switch.value)
        save()

    auto_switch = ft.Switch(
        key="about_auto_check", label=t("about.auto_check", lang), value=bool(getattr(state, "update_check_enabled", True)), on_change=on_auto
    )

    version_card = common.card(
        page,
        ft.Column(
            spacing=10,
            controls=[
                ft.Row(
                    spacing=12,
                    controls=[
                        common.logo_badge(44),
                        ft.Column(
                            spacing=2,
                            tight=True,
                            controls=[
                                ft.Text(t("app.title", lang), size=17, weight=ft.FontWeight.W_700),
                                ft.Text(t("about.version", lang, version=version), key="about_version", size=13, color=secondary),
                            ],
                        ),
                    ],
                ),
                ft.Text(t("about.license", lang), size=12.5, color=secondary),
                ft.Row(
                    spacing=10,
                    wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.OutlinedButton(key="about_check", content=t("about.check", lang), icon=ft.Icons.REFRESH_ROUNDED, on_click=on_check, disabled=checker is None),
                        check_result,
                        update_link,
                        install_btn,
                    ],
                ),
                auto_switch,
                ft.Text(t("about.auto_check_hint", lang), size=11.5, color=secondary),
            ],
        ),
    )

    # ------------------------------------------------------------------- سازنده ----
    copied = ft.Text(t("about.email_copied", lang), key="about_email_copied", size=12, color=theme.SUCCESS, visible=False)

    def on_copy_email(e=None) -> None:
        if common.copy_text(page, branding.CONTACT_EMAIL):
            copied.visible = True
            page.update()

    creator_name = branding.CREATOR_NAME_EN if lang == "en" else branding.CREATOR_NAME_FA
    creator_card = common.card(
        page,
        ft.Column(
            spacing=10,
            controls=[
                common.section_header(ft.Icons.PERSON_OUTLINE_ROUNDED, t("about.creator", lang)),
                ft.Text(t("about.creator_line", lang, name=creator_name), size=13.5),
                ft.Row(
                    spacing=8,
                    wrap=True,
                    controls=[
                        ft.OutlinedButton(key="about_github", content=t("about.github", lang), icon=ft.Icons.CODE_ROUNDED, on_click=lambda e: common.open_url(page, branding.GITHUB_PROFILE)),
                        ft.OutlinedButton(key="about_instagram", content=t("about.instagram", lang), icon=ft.Icons.OPEN_IN_NEW_ROUNDED, on_click=lambda e: common.open_url(page, branding.INSTAGRAM)),
                        ft.OutlinedButton(key="about_email_copy", content=t("about.email_copy", lang), icon=ft.Icons.CONTENT_COPY_ROUNDED, on_click=on_copy_email),
                        ft.OutlinedButton(
                            key="about_report", content=t("about.report", lang), icon=ft.Icons.BUG_REPORT_OUTLINED,
                            on_click=lambda e: common.open_url(page, about_info.issue_url(version)),
                        ),
                    ],
                ),
                ft.Text(branding.CONTACT_EMAIL, key="about_email", size=12.5, color=secondary, selectable=True),
                copied,
                ft.Text(t("about.report_hint", lang), size=11.5, color=secondary),
            ],
        ),
    )

    # --------------------------------------------------------- حمایت (کوچک و اختیاری) ----
    amount = ft.TextField(key="support_amount", label=t("support.amount", lang), border_radius=10, width=220, keyboard_type=ft.KeyboardType.NUMBER)
    message = ft.TextField(key="support_message", label=t("support.message", lang), border_radius=10, expand=True)
    counter = ft.Text(support_link.message_counter(""), key="support_counter", size=11.5, color=secondary)
    error = ft.Text("", key="support_error", size=12.5, color=theme.DANGER, visible=False)
    link_ready = ft.Text(t("support.link_ready", lang), key="support_link_ready", size=12, color=theme.SUCCESS, visible=False)
    link_text = ft.Text("", key="support_link_text", size=11, color=secondary, selectable=True, visible=False)
    copy_link = ft.TextButton(key="support_copy", content=t("support.copy_link", lang), visible=False, on_click=lambda e: common.copy_text(page, str(link_text.value or "")))

    def on_message_change(e=None) -> None:
        counter.value = support_link.message_counter(message.value)
        counter.color = theme.DANGER if support_link.utf16_len(message.value or "") > branding.DARAMET_MESSAGE_MAX else secondary
        page.update()

    message.on_change = on_message_change

    def on_make(e=None) -> None:
        try:
            url = support_link.build_support_link(amount.value or "", message.value or "")
        except support_link.SupportLinkError as exc:
            error.value = str(exc)
            error.visible = True
            link_ready.visible = link_text.visible = copy_link.visible = False
            page.update()
            return
        error.visible = False
        link_text.value = url
        link_ready.visible = link_text.visible = copy_link.visible = True
        common.open_url(page, url)
        page.update()

    if branding.DARAMET_WEBINTENT_ENABLED:
        support_controls: list = [
            ft.Text(t("support.note", lang), key="support_note", size=12.5, color=secondary),
            ft.Row(spacing=10, vertical_alignment=ft.CrossAxisAlignment.START, controls=[amount, message]),
            counter,
            error,
            ft.Button(key="support_make", content=t("support.make", lang), icon=ft.Icons.FAVORITE_BORDER_ROUNDED, on_click=on_make),
            link_ready,
            link_text,
            copy_link,
        ]
    else:  # دارمت وب‌اینتنت را نپذیرفت ⇒ فقط پروفایل
        support_controls = [
            ft.Text(t("support.note", lang), key="support_note", size=12.5, color=secondary),
            ft.Button(key="support_profile", content=t("support.profile", lang), icon=ft.Icons.OPEN_IN_NEW_ROUNDED, on_click=lambda e: common.open_url(page, branding.daramet_profile_url())),
        ]
    support_tile = common.card(
        page,
        ft.ExpansionTile(
            key="support_tile",
            expanded=False,
            title=ft.Text(t("support.title", lang), size=13.5, weight=ft.FontWeight.W_600),
            controls=[ft.Container(padding=ft.Padding.only(left=6, right=6, bottom=12), content=ft.Column(spacing=10, controls=support_controls))],
        ),
        padding=6,
    )

    return ft.Container(
        expand=True,
        padding=28,
        content=ft.Column(
            spacing=18,
            scroll=ft.ScrollMode.AUTO,
            controls=[
                common.page_header(page, ft.Icons.INFO_OUTLINE_ROUNDED, t("about.title", lang), t("about.subtitle", lang)),
                version_card,
                creator_card,
                support_tile,
            ],
        ),
    )
