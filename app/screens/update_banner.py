"""بنرِ غیرمزاحمِ «نسخه‌ی تازه منتشر شده» (N14a) + نصبِ یک‌کلیکی (N14b).

نوارِ باریکِ بالای صفحه؛ «بعداً» تا نسخه‌ی بعدی پنهانش می‌کنه. اگه نصبِ خودکار ممکن باشه («نصبِ به‌روزرسانی»)،
همین نوار مراحل را نشون می‌ده (تأیید ← پیشرفت ← بازراه‌اندازی) بدونِ پنجره‌ی جداگانه:

    idle ──نصب──▶ confirm ──بله──▶ working ──▶ restarting (برنامه بسته می‌شه)
                     │                 ├──▶ downloaded (فقط macOS/لینوکس: فایلِ تأییدشده در Downloads)
                     └─انصراف─▶ idle    └──▶ error (دوباره / دانلودِ دستی / بستن)

بدونِ ``installer`` (یا وقتی حالت «دستی» است) دقیقاً همان بنرِ N14a نشون داده می‌شه: «تغییرات و دانلود» + «بعداً».
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import flet as ft

from app import theme
from app.core import update_install
from app.core.updater import UpdateInfo
from app.i18n import STRINGS, t
from app.screens import common

_RETRYABLE = {"network", "size_mismatch", "disk", "busy", "launch", "backup", "unexpected"}


def _bar(key: str, color: str, content: ft.Control) -> ft.Container:
    return ft.Container(
        key=key,
        padding=ft.Padding.symmetric(horizontal=18, vertical=6),
        bgcolor=f"{color}22",
        border=ft.Border(bottom=ft.BorderSide(1, f"{color}66")),
        content=content,
    )


def _line(icon: str, icon_color: str, message: str, buttons: list) -> ft.Row:
    return ft.Row(
        spacing=8,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Icon(icon, size=18, color=icon_color),
            ft.Text(message, size=12.5, weight=ft.FontWeight.W_600, expand=True),
            *buttons,
        ],
    )


def build(
    page: ft.Page,
    lang: str,
    info: UpdateInfo,
    on_later: Callable[[str], None],
    *,
    installer=None,
    on_restart: Optional[Callable[[], None]] = None,
    before_handoff: Optional[Callable[[], None]] = None,
    on_resume: Optional[Callable[[], None]] = None,
    start_in_confirm: bool = False,
) -> ft.Control:
    availability = installer.availability(info) if installer is not None else None
    can_install = availability is not None and availability.mode in (update_install.MODE_AUTO, update_install.MODE_DOWNLOAD)
    download_only = availability is not None and availability.mode == update_install.MODE_DOWNLOAD
    state = {"step": "confirm" if (start_in_confirm and can_install) else "idle", "phase": "", "fraction": None, "error": "", "path": ""}
    holder = _bar("update_banner", theme.ACCENT, ft.Container())

    def refresh() -> None:
        try:
            page.update()
        except Exception:  # noqa: BLE001 — پیشرفتِ بنر هرگز نباید برنامه را بشکند
            pass

    def goto(step: str, **extra) -> None:
        state.update(step=step, **extra)
        render()

    # ---- کنش‌ها
    def on_install(_e=None) -> None:
        if can_install and state["step"] == "idle":
            goto("confirm")

    def on_back(_e=None) -> None:
        goto("idle", error="")

    def on_cancel(_e=None) -> None:
        if installer is not None:
            installer.cancel()

    def on_confirm(_e=None) -> None:
        if installer is None or state["step"] == "working" or installer.busy:
            return  # قفل در برابرِ دوکلیک
        goto("working", phase=update_install.PHASE_SIGNATURE, fraction=None, error="")
        page.run_thread(worker)

    def resume() -> None:
        if on_resume is not None:
            try:
                on_resume()
            except Exception:  # noqa: BLE001
                pass

    def worker() -> None:
        def progress(phase: str, fraction: Optional[float]) -> None:
            state.update(phase=phase, fraction=fraction)
            render()

        try:
            result = installer.install(info, progress, before_handoff=before_handoff)
        except update_install.InstallError as exc:
            resume()
            if exc.code == "cancelled":
                goto("idle", error="")
            else:
                goto("error", error=exc.code)
            return
        except Exception:  # noqa: BLE001 — هیچ خطایی بنر را در حالتِ «در حال نصب» گیر نمی‌اندازه
            resume()
            goto("error", error="unexpected")
            return
        if result.status == "restart":
            goto("restarting")
            if on_restart is not None:
                on_restart()
        else:
            goto("downloaded", path=result.path)

    def on_reveal(_e=None) -> None:
        common.open_folder(Path(state["path"]).parent)

    # ---- ساختِ ظاهر
    def phase_text() -> str:
        phase, fraction = state["phase"], state["fraction"]
        if phase == update_install.PHASE_DOWNLOAD and fraction is not None:
            return t("update.phase.download_pct", lang, percent=int(max(0.0, min(1.0, fraction)) * 100))
        return t(f"update.phase.{phase}", lang)

    def body() -> ft.Control:
        step = state["step"]
        later = ft.TextButton(key="update_later", content=t("update.later", lang), on_click=lambda e: on_later(info.version))
        changes = ft.TextButton(key="update_changes", content=t("update.changes", lang), on_click=lambda e: common.open_url(page, info.html_url))
        if step == "confirm":
            message = t("update.confirm_download" if download_only else "update.confirm", lang, version=info.version)
            return _line(
                ft.Icons.SYSTEM_UPDATE_ALT_ROUNDED, theme.ACCENT_DARK, message,
                [
                    ft.OutlinedButton(key="update_confirm_yes", content=t("update.confirm_yes", lang), on_click=on_confirm),
                    ft.TextButton(key="update_confirm_no", content=t("update.confirm_no", lang), on_click=on_back),
                ],
            )
        if step == "working":
            line = _line(ft.Icons.DOWNLOAD_ROUNDED, theme.ACCENT_DARK, phase_text(), [ft.TextButton(key="update_cancel", content=t("update.cancel", lang), on_click=on_cancel)])
            bar = ft.ProgressBar(key="update_progress", value=state["fraction"], bar_height=4, color=theme.ACCENT, bgcolor=f"{theme.ACCENT}33")
            return ft.Column(spacing=4, controls=[line, bar])
        if step == "restarting":
            return _line(ft.Icons.SYSTEM_UPDATE_ALT_ROUNDED, theme.ACCENT_DARK, t("update.phase.handoff", lang), [])
        if step == "downloaded":
            return _line(
                ft.Icons.CHECK_CIRCLE_ROUNDED, theme.SUCCESS, t("update.downloaded", lang, path=state["path"]),
                [
                    ft.OutlinedButton(key="update_reveal", content=t("update.reveal", lang), icon=ft.Icons.FOLDER_OPEN_ROUNDED, on_click=on_reveal),
                    ft.TextButton(key="update_back", content=t("update.close", lang), on_click=on_back),
                ],
            )
        if step == "error":
            code = state["error"] if f"update.error.{state['error']}" in STRINGS else "unexpected"
            buttons: list = []
            if code in _RETRYABLE:
                buttons.append(ft.OutlinedButton(key="update_retry", content=t("update.retry", lang), on_click=on_confirm))
            buttons.append(ft.TextButton(key="update_manual", content=t("update.manual", lang), on_click=lambda e: common.open_url(page, info.html_url)))
            buttons.append(ft.TextButton(key="update_back", content=t("update.close", lang), on_click=on_back))
            return _line(ft.Icons.WARNING_AMBER_ROUNDED, theme.DANGER, t(f"update.error.{code}", lang), buttons)
        # idle — همان بنرِ N14a (+ دکمه‌ی نصب وقتی ممکنه)
        buttons = [changes]
        if can_install:
            label = "update.download_verified" if download_only else "update.install"
            buttons.append(ft.OutlinedButton(key="update_install", content=t(label, lang), on_click=on_install))
        buttons.append(later)
        return _line(ft.Icons.SYSTEM_UPDATE_ALT_ROUNDED, theme.ACCENT_DARK, t("update.banner", lang, version=info.version), buttons)

    def render() -> None:
        holder.content = body()
        refresh()

    holder.content = body()
    return holder


def build_notice(page: ft.Page, lang: str, result: dict, on_dismiss: Callable[[], None]) -> ft.Control:
    """پیامِ یک‌باره‌ی نتیجه‌ی آخرین به‌روزرسانی (انجام شد / برگشت داده شد)."""
    status = result.get("status", "failed")
    ok = status == "ok"
    color = theme.SUCCESS if ok else theme.DANGER
    key = f"update.result.{status}" if f"update.result.{status}" in STRINGS else "update.result.failed"
    return _bar(
        "update_notice",
        color,
        _line(
            ft.Icons.CHECK_CIRCLE_ROUNDED if ok else ft.Icons.WARNING_AMBER_ROUNDED,
            color,
            t(key, lang, version=result.get("to", "")),
            [ft.TextButton(key="update_notice_dismiss", content=t("update.result.dismiss", lang), on_click=lambda e: on_dismiss())],
        ),
    )
