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

SIDEBAR_WIDTH = 232
_TEXT_DIM = "#C7CCDA"
_TEXT_FAINT = "#8B92A8"


@dataclass(frozen=True)
class NavEntry:
    key: str
    icon: str
    label: str
    on_click: Callable


def nav_item(entry: NavEntry, active: str) -> ft.Control:
    is_active = entry.key == active
    return ft.Container(
        key=f"nav_{entry.key}",
        margin=ft.Margin.symmetric(horizontal=10),
        padding=ft.Padding.symmetric(horizontal=12, vertical=9),
        border_radius=10,
        bgcolor="#FFFFFF2B" if is_active else None,
        ink=True,
        on_click=entry.on_click,
        content=ft.Row(
            spacing=11,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Icon(icon=entry.icon, size=18, color="#FFFFFF" if is_active else _TEXT_DIM),
                ft.Text(
                    entry.label,
                    size=13,
                    expand=True,
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.W_400,
                    color="#FFFFFF" if is_active else _TEXT_DIM,
                ),
                *([ft.Container(width=6, height=6, border_radius=3, bgcolor=theme.ACCENT)] if is_active else []),
            ],
        ),
    )


def group_label(text: str) -> ft.Control:
    return ft.Container(
        padding=ft.Padding(left=22, right=22, top=12, bottom=3),
        content=ft.Text(text, size=10.5, weight=ft.FontWeight.W_600, color=_TEXT_FAINT, max_lines=1),
    )


def divider() -> ft.Control:
    return ft.Container(margin=ft.Margin.symmetric(horizontal=18, vertical=6), height=1, bgcolor="#FFFFFF1F")


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
        gradient=theme.sidebar_gradient(),
        padding=ft.Padding.symmetric(vertical=16),
        content=ft.Column(
            expand=True,
            spacing=0,
            controls=[
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=18),
                    content=ft.Row(
                        spacing=10,
                        controls=[
                            common.logo_badge(38),
                            ft.Column(
                                spacing=0,
                                tight=True,
                                expand=True,
                                controls=[
                                    ft.Text(brand_title, size=13, weight=ft.FontWeight.W_700, color="#FFFFFF", max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                    ft.Text(brand_badge, size=10, color="#93E6B7", weight=ft.FontWeight.W_500, max_lines=1),
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
