"""اجزای ظاهری مشترک کل برنامه — کارت، عنوان بخش، نشان وضعیت، دکمه‌ی انتخاب،
نشان برند، سرتیتر صفحه، نشانگر مراحل. هدف: یه زبان بصری یکسان روی همه‌ی
صفحه‌ها (آنبوردینگ، هوش مصنوعی، ربات‌ها، گفتگوها، تنظیمات)، نه فقط صفحه‌های
جدید فاز ۳."""

from __future__ import annotations

import logging
from typing import Optional

import flet as ft

from app import theme

logger = logging.getLogger(__name__)


def _spawn(page: ft.Page, coro_func, *args) -> bool:
    runner = getattr(page, "run_task", None)
    if not callable(runner):
        return False
    try:
        runner(coro_func, *args)
        return True
    except Exception:  # noqa: BLE001 — باز نشدنِ لینک/کپی هرگز نباید برنامه را بشکند
        logger.warning("اجرای کارِ async روی صفحه ناموفق بود", exc_info=True)
        return False


def open_url(page: ft.Page, url: str) -> bool:
    """باز کردنِ لینک در مرورگرِ سیستم. در Flet 1.0 ``Page.launch_url`` نیست و باید از سرویسِ ``UrlLauncher`` رفت؛
    اگه نسخه‌ای ``launch_url`` داشته باشه همان استفاده می‌شه. فقط http/https."""
    url = (url or "").strip()
    if not url.lower().startswith(("https://", "http://", "mailto:")):
        return False
    legacy = getattr(page, "launch_url", None)
    if callable(legacy):
        try:
            legacy(url)
            return True
        except Exception:  # noqa: BLE001
            logger.warning("page.launch_url ناموفق بود", exc_info=True)

    async def _go(target: str) -> None:
        await ft.UrlLauncher().launch_url(target)

    return _spawn(page, _go, url)


def open_folder(path) -> bool:
    """پوشه را در مدیرِ فایلِ سیستم باز می‌کند (ویندوز/مک/لینوکس). هرگز exception نمی‌دهد."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    folder = Path(path)
    if not folder.is_dir():
        return False
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(folder))  # noqa: S606 — پوشه‌ی داده‌ی خودِ برنامه
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])  # noqa: S603, S607
        else:
            subprocess.Popen(["xdg-open", str(folder)])  # noqa: S603, S607
        return True
    except (OSError, ValueError):
        logger.warning("باز کردنِ پوشه ناموفق بود", exc_info=True)
        return False


def copy_text(page: ft.Page, text: str) -> bool:
    """کپی در کلیپ‌بورد (Flet 1.0: سرویسِ ``Clipboard``)."""
    legacy = getattr(page, "set_clipboard", None)
    if callable(legacy):
        try:
            legacy(text)
            return True
        except Exception:  # noqa: BLE001
            logger.warning("page.set_clipboard ناموفق بود", exc_info=True)

    async def _copy(value: str) -> None:
        await ft.Clipboard().set(value)

    return _spawn(page, _copy, text)


def get_or_create_file_picker(page: ft.Page) -> ft.FilePicker:
    """یه FilePicker رو روی خودِ page کش می‌کنه — چند صفحه‌ی مختلف (تنظیمات
    محلی هوش مصنوعی، عکس محصول) می‌تونن همین یکی رو دوباره استفاده کنن به‌جای
    ساختن چندتا FilePicker جدا."""
    picker = getattr(page, "_sbl_file_picker", None)
    if picker is None:
        picker = ft.FilePicker()
        page.services.append(picker)
        page._sbl_file_picker = picker
    return picker


def card(page: ft.Page, content: ft.Control, padding: int = 20) -> ft.Container:
    return ft.Container(
        padding=padding,
        border_radius=14,
        bgcolor=theme.card_bgcolor(page),
        border=ft.Border.all(1, theme.border_color(page)),
        shadow=ft.BoxShadow(blur_radius=18, color="#00000014", offset=ft.Offset(0, 4)),
        content=content,
    )


def section_header(icon: str, text: str) -> ft.Control:
    return ft.Row(
        spacing=8,
        controls=[
            ft.Icon(icon=icon, color=theme.PRIMARY, size=20),
            ft.Text(text, size=15, weight=ft.FontWeight.W_600),
        ],
    )


def page_header(page: ft.Page, icon: str, title: str, subtitle: str = "") -> ft.Control:
    """سرتیتر یکسان برای هر صفحه‌ی داخل پوسته: نشان آیکون‌دار + عنوان + زیرعنوان."""
    controls: list[ft.Control] = [
        ft.Row(
            spacing=12,
            controls=[
                ft.Container(
                    width=40,
                    height=40,
                    border_radius=11,
                    bgcolor=f"{theme.PRIMARY}12",
                    alignment=ft.Alignment.CENTER,
                    content=ft.Icon(icon=icon, color=theme.PRIMARY, size=21),
                ),
                ft.Text(title, size=23, weight=ft.FontWeight.W_700),
            ],
        )
    ]
    if subtitle:
        controls.append(ft.Text(subtitle, size=13, color=theme.text_secondary(page)))
    return ft.Column(spacing=6, controls=controls)


APP_ICON_ASSET = "icons/app-icon-256.png"  # assets/icons/ (ساخته‌ی scripts/make_icons.py)


def logo_badge(size: int = 44, icon: str = None) -> ft.Control:
    """نشان برند: خودِ آیکنِ برنامه (N9) — روی نوار کناری، خوش‌آمدگویی و «درباره»، تا یه هویت بصری ثابت باشه.
    اگه ``icon`` داده بشه همان مربعِ گردِ گرادیانی با آیکنِ متریال نشون داده می‌شه (برای استفاده‌های خاص)."""
    if icon is None:
        return ft.Container(
            key="app_logo",
            width=size,
            height=size,
            content=ft.Image(src=APP_ICON_ASSET, width=size, height=size, fit=ft.BoxFit.CONTAIN),
        )
    return ft.Container(
        width=size,
        height=size,
        border_radius=size * 0.28,
        gradient=ft.LinearGradient(
            begin=ft.Alignment.TOP_LEFT,
            end=ft.Alignment.BOTTOM_RIGHT,
            colors=[theme.ACCENT, theme.ACCENT_DARK],
        ),
        alignment=ft.Alignment.CENTER,
        content=ft.Icon(icon or ft.Icons.AUTO_AWESOME_ROUNDED, color="#FFFFFF", size=size * 0.52),
    )


def onboarding_frame(page: ft.Page, step: int, total: int, content: list) -> ft.Control:
    """قاب یکسان برای صفحه‌های آنبوردینگ: پس‌زمینه‌ی سطحی، نشانگر مرحله، و
    وسط‌چین با اسکرول برای پنجره‌های کوچیک."""
    return ft.Container(
        expand=True,
        alignment=ft.Alignment.CENTER,
        bgcolor=theme.surface_bgcolor(page),
        padding=32,
        content=ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=20,
            scroll=ft.ScrollMode.AUTO,
            controls=[step_dots(step, total), *content],
        ),
    )


def step_dots(current: int, total: int, active_color: str = None) -> ft.Control:
    """نشانگر مراحل آنبوردینگ (۱ از ۳ و ...) — دایره‌های کوچیک، مرحله‌ی فعلی
    پررنگ و بلندتر."""
    color = active_color or theme.ACCENT
    dots = []
    for i in range(total):
        is_done = i < current
        is_current = i == current
        dots.append(
            ft.Container(
                width=22 if is_current else 8,
                height=8,
                border_radius=4,
                bgcolor=color if (is_current or is_done) else "#D8D4C8",
                animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
            )
        )
    return ft.Row(spacing=6, alignment=ft.MainAxisAlignment.CENTER, controls=dots)


def primary_button(
    text: str, on_click, icon: str = None, width: Optional[int] = None, disabled: bool = False
) -> ft.Button:
    return ft.Button(
        content=ft.Row(
            tight=True,
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=8,
            controls=(
                [ft.Icon(icon, size=17, color="#FFFFFF"), ft.Text(text, size=14, weight=ft.FontWeight.W_600)]
                if icon
                else [ft.Text(text, size=14, weight=ft.FontWeight.W_600)]
            ),
        ),
        bgcolor=theme.PRIMARY,
        color="#FFFFFF",
        width=width,
        height=46,
        disabled=disabled,
        on_click=on_click,
    )


def option_card(
    page: ft.Page,
    icon: str,
    title: str,
    desc: str,
    selected: bool,
    on_click,
    width: int = 320,
) -> ft.Control:
    """کارت انتخاب دوگزینه‌ای (نوع کسب‌وکار، نوع هوش مصنوعی، ...) — یه بار
    درست پیاده شده، همه‌جا همینه (قبلاً هر صفحه نسخه‌ی خودش رو داشت)."""
    is_selected = bool(selected)
    accent = theme.ACCENT
    return ft.Container(
        width=width,
        padding=18,
        border_radius=14,
        bgcolor=f"{accent}0F" if is_selected else theme.card_bgcolor(page),
        border=ft.Border.all(2 if is_selected else 1, accent if is_selected else theme.border_color(page)),
        shadow=(
            ft.BoxShadow(blur_radius=16, color=f"{accent}33", offset=ft.Offset(0, 4))
            if is_selected
            else None
        ),
        ink=True,
        on_click=on_click,
        animate=ft.Animation(150, ft.AnimationCurve.EASE_OUT),
        content=ft.Row(
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.START,
            controls=[
                ft.Container(
                    width=38,
                    height=38,
                    border_radius=10,
                    bgcolor=f"{accent}22" if is_selected else f"{theme.PRIMARY}12",
                    alignment=ft.Alignment.CENTER,
                    content=ft.Icon(icon, size=19, color=accent if is_selected else theme.PRIMARY),
                ),
                ft.Column(
                    expand=True,
                    spacing=4,
                    controls=[
                        ft.Text(title, size=15, weight=ft.FontWeight.W_600),
                        ft.Text(desc, size=12, color=theme.text_secondary(page)),
                    ],
                ),
                ft.Icon(
                    ft.Icons.CHECK_CIRCLE_ROUNDED if is_selected else ft.Icons.RADIO_BUTTON_UNCHECKED,
                    size=20,
                    color=accent if is_selected else theme.border_color(page),
                ),
            ],
        ),
    )


class StatusChip:
    """نشان رنگی کوچک با نقطه + متن؛ با set() بدون ساخت دوباره به‌روز می‌شه."""

    def __init__(self, text: str, color: str):
        self._dot = ft.Icon(icon=ft.Icons.CIRCLE, size=9, color=color)
        self._text = ft.Text(text, size=12, color=color, weight=ft.FontWeight.W_500)
        self.control = ft.Container(
            padding=ft.Padding.symmetric(horizontal=10, vertical=4),
            border_radius=20,
            bgcolor=f"{color}22",
            content=ft.Row(tight=True, spacing=6, controls=[self._dot, self._text]),
        )

    def set(self, text: str, color: str) -> None:
        self._dot.color = color
        self._text.value = text
        self._text.color = color
        self.control.bgcolor = f"{color}22"
