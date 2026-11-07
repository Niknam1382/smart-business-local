"""
بستنِ پنجره (قلم ۱۶ مستر‌پرامپت): ✕ باید انتخابِ خودِ کاربر باشد، نه تصمیمِ برنامه.

سه رفتارِ ممکن، ذخیره‌شده در ``settings.close_action``:

* ``ask`` (پیش‌فرض): پنجره می‌پرسد «در پس‌زمینه بمونم یا کاملاً خارج شوم؟» و کاربر می‌تواند
  انتخابش را برای دفعه‌های بعد ذخیره کند.
* ``hide``: فقط کوچک می‌شه — ربات‌ها و پرداخت‌ها روشن می‌مونن و کاربر با آیکونِ برنامه در
  نوارِ ویندوز برمی‌گرده. (پنهان‌شدنِ کامل نیاز به tray داشت، یعنی وابستگیِ تازه؛ پس همین
  «کوچک‌شدنِ reversible» انتخاب شد: هیچ‌وقت پنجره‌ای که بازش نمی‌شه باقی نمی‌مونه.)
* ``quit``: خروجِ کامل، همان‌طور که قبلاً پیش می‌آمد.

منطق اینجا جدا از ``main.py`` است تا با Pageِ جعلیِ تست‌ها هم بدونِ پنجره‌ی واقعی آزموده بشه.
"""

from __future__ import annotations

from typing import Callable, Optional

import flet as ft

from app import theme
from app.i18n import t

ACTIONS = ("ask", "hide", "quit")
CLOSE_EVENT = "close"


def _event_name(event) -> str:
    """Flet 1.0 رویدادِ پنجره را با ``type`` (enum) و ``name`` (رشته) می‌فرستد؛ هر دو پذیرفته می‌شن."""
    for attribute in ("type", "event", "name"):
        raw = getattr(event, attribute, None)
        if raw:
            text = str(raw).lower()
            return text.rsplit(".", 1)[-1].replace("-", "_").rstrip("'\"")
    return ""


def apply_close(state, action: str) -> None:
    """مقدارِ ``close_action`` را اعتبارسنجی و ذخیره می‌کنه؛ هر چیزِ ناشناخت = «بپرس»."""
    state.close_action = action if action in ACTIONS else "ask"


def bind(page: ft.Page, state, save: Optional[Callable[[], None]] = None) -> None:
    """وصل‌کردنِ پنجره به این منطق: ✕ دیگر بی‌سؤال نمی‌بندد."""
    page.window.prevent_close = True
    page.window.on_event = lambda event: _on_event(page, state, save, event)


def _set_window(page: ft.Page, **values) -> None:
    for name, value in values.items():
        try:
            setattr(page.window, name, value)
        except Exception:  # noqa: BLE001 — وب/تست: پنجره‌ی واقعی نیست
            pass


def _hide(page: ft.Page) -> None:
    _set_window(page, minimized=True)


def _quit(page: ft.Page) -> None:
    """خروجِ واقعی؛ اگر پنجره‌ی بسته‌شدنی نبود (وب/تست) بی‌خطا برمی‌گرده."""
    for name in ("close", "destroy"):
        closer = getattr(page.window, name, None)
        if callable(closer):
            try:
                closer()
                return
            except Exception:  # noqa: BLE001
                continue


def _close_dialog(page: ft.Page, dialog: ft.Control) -> None:
    closer = getattr(page, "close", None)
    if callable(closer):
        try:
            closer(dialog)
            return
        except Exception:  # noqa: BLE001
            pass
    overlay = getattr(page, "overlay", None)
    if isinstance(overlay, list) and dialog in overlay:
        overlay.remove(dialog)
        page.update()


def _ask(page: ft.Page, state, save) -> None:
    lang = getattr(state, "language", "fa")
    remember = ft.Switch(key="close_remember", label=t("window.close.remember", lang), value=False)

    def choose(action: str):
        def handler(_e=None) -> None:
            _close_dialog(page, dialog)
            if bool(remember.value):
                apply_close(state, action)
                if save is not None:
                    save()
            if action == "quit":
                _quit(page)
            else:
                _hide(page)

        return handler

    def stay(_e=None) -> None:
        _close_dialog(page, dialog)

    dialog = ft.AlertDialog(
        key="close_dialog",
        modal=True,
        title=ft.Text(t("window.close.title", lang), weight=ft.FontWeight.W_700),
        content=ft.Column(
            spacing=10,
            tight=True,
            controls=[
                ft.Text(t("window.close.question", lang), size=13),
                remember,
                ft.Text(t("window.close.changed", lang), size=11.5, color=theme.text_secondary(page)),
            ],
        ),
        actions=[
            ft.FilledButton(key="close_hide", content=t("window.close.hide", lang), on_click=choose("hide")),
            ft.OutlinedButton(key="close_quit", content=t("window.close.quit", lang), on_click=choose("quit")),
            ft.TextButton(key="close_cancel", content=t("window.close.cancel", lang), on_click=stay),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    opener = getattr(page, "open", None)
    if callable(opener):
        opener(dialog)
        return
    overlay = getattr(page, "overlay", None)
    if isinstance(overlay, list):
        overlay.append(dialog)
        page.update()


def _on_event(page: ft.Page, state, save, event) -> None:
    if _event_name(event) != CLOSE_EVENT:
        return
    action = getattr(state, "close_action", "ask")
    if action == "quit":
        _quit(page)
    elif action == "hide":
        _hide(page)
    else:
        _ask(page, state, save)
