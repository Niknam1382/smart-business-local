"""نوارِ کناریِ برنامه: گروه‌بندی‌شده، فشرده و **اسکرول‌پذیر**.

مشکلِ قبلی: ۱۵+ آیتمِ منو در یک ستونِ بدونِ اسکرول بودن و روی پنجره‌های کم‌ارتفاع (لپ‌تاپ ۷۶۸) آیتم‌های پایین
(تنظیمات، درباره) بیرون می‌افتادن و قابل‌دسترسی نبودن. حالا: سرتیترِ برند ثابت، فهرستِ وسط اسکرول‌پذیر،
آیتم‌هایِ پایین (راهنما/حمایت/درباره/تنظیمات) دیگر به تهِ نوار میخ نمی‌شن: در همان فهرستِ اسکرول‌پذیر می‌آیند، پس روی پنجره‌ی کوتاه هیچ‌وقت زیرِ لبه نمی‌مانند (قلم ۴).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import flet as ft

from app import theme
from app.screens import common

SIDEBAR_WIDTH = 248
# رنگ‌های روی نیوی از theme.py می‌آیند (قبلاً هگزِ خام بودند؛ همان مقدارها)
_TEXT_DIM = theme.SIDEBAR_TEXT_DIM
_TEXT_FAINT = theme.SIDEBAR_TEXT_FAINT


@dataclass(frozen=True)
class NavEntry:
    key: str
    icon: str
    label: str
    on_click: Callable


def nav_item(entry: NavEntry, active: str) -> ft.Control:
    """آیتمِ منو (۱٫۲٫۰): فعال = قرصِ گرادیانیِ برند با متنِ سفید و سایه؛ عادی = متنِ کم‌رنگ روی نوارِ تیره."""
    is_active = entry.key == active
    return ft.Container(
        key=f"nav_{entry.key}",
        margin=ft.Margin.symmetric(horizontal=12),
        padding=ft.Padding.symmetric(horizontal=14, vertical=11),
        border_radius=14,
        tooltip=entry.label,  # متنِ کامل (اگر در نوارِ باریک بریده شد) با نگه‌داشتنِ ماوس دیده می‌شود
        gradient=theme.hero_gradient() if is_active else None,
        shadow=ft.BoxShadow(blur_radius=18, color=theme.alpha(theme.PRIMARY, 0x66), offset=ft.Offset(0, 6)) if is_active else None,
        ink=True,
        on_click=entry.on_click,
        content=ft.Row(
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Icon(icon=entry.icon, size=19, color=theme.ON_SOLID if is_active else _TEXT_DIM),
                ft.Text(
                    entry.label,
                    size=13,
                    expand=True,
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.W_400,
                    color=theme.ON_SOLID if is_active else _TEXT_DIM,
                ),
            ],
        ),
    )


def group_label(text: str) -> ft.Control:
    return ft.Container(
        padding=ft.Padding(left=26, right=26, top=16, bottom=4),
        content=ft.Text(text, size=10.5, weight=ft.FontWeight.W_700, color=_TEXT_FAINT, max_lines=1),
    )


def divider() -> ft.Control:
    return ft.Container(margin=ft.Margin.symmetric(horizontal=22, vertical=8), height=1, bgcolor=theme.SIDEBAR_DIVIDER)


def build(
    brand_title: str,
    brand_badge: str,
    welcome: str,
    active: str,
    top: list,
    groups: list,
    bottom: list,
) -> ft.Control:
    """``top``: آیتم‌های بدونِ گروه (خانه)؛ ``groups``: ``[(عنوان, [NavEntry])]`` (گروهِ خالی نمایش داده نمی‌شه)؛
    ``bottom``: آیتم‌های ثابتِ پایین."""
    middle: list = [nav_item(e, active) for e in top]
    for title, entries in groups:
        if entries:
            middle.append(group_label(title))
            middle += [nav_item(e, active) for e in entries]
    return ft.Container(
        key="sidebar",
        width=SIDEBAR_WIDTH,
        margin=ft.Margin(left=12, right=12, top=12, bottom=12),  # نوارِ شناور با گوشه‌های گرد
        border_radius=28,
        gradient=theme.sidebar_gradient(),
        shadow=ft.BoxShadow(blur_radius=30, color=theme.alpha(theme.SIDEBAR_GRADIENT_START, 0x55), offset=ft.Offset(0, 12)),
        padding=ft.Padding.symmetric(vertical=18),
        content=ft.Column(
            expand=True,
            spacing=0,
            controls=[
                ft.Container(
                    margin=ft.Margin.symmetric(horizontal=14),
                    padding=ft.Padding.symmetric(horizontal=12, vertical=10),
                    border_radius=18,
                    bgcolor=theme.SIDEBAR_DIVIDER,
                    border=ft.Border.all(1, theme.SIDEBAR_ACTIVE_BG),
                    content=ft.Row(
                        spacing=10,
                        controls=[
                            common.logo_badge(38),
                            ft.Column(
                                spacing=0,
                                tight=True,
                                expand=True,
                                controls=[
                                    ft.Text(brand_title, size=13, weight=ft.FontWeight.W_700, color=theme.ON_SOLID, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                    ft.Text(brand_badge, size=10, color=theme.SIDEBAR_ON_DARK, weight=ft.FontWeight.W_500, max_lines=1),
                                ],
                            ),
                        ],
                    ),
                ),
                ft.Container(
                    padding=ft.Padding(left=20, right=20, top=10, bottom=0),
                    content=ft.Text(welcome, size=11.5, color=_TEXT_FAINT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ),
                divider(),
                ft.Column(
                    key="sidebar_scroll", expand=True, spacing=1, scroll=ft.ScrollMode.ADAPTIVE,
                    controls=[*middle, divider(), *[nav_item(e, active) for e in bottom]],
                ),
            ],
        ),
    )
