"""
طرح رنگی و تایپوگرافی «کسب‌وکار هوشمند» (نسخه محلی).

پالت به‌جای آبی/سبز پیش‌فرض معمول ابزارهای SaaS، حول یک نیوی تیره
(اعتماد و ثبات) و یک کهربایی گرم (فقط برای اکشن‌های اصلی) ساخته شده تا
هم حرفه‌ای باشد و هم با فضای یک ابزار کسب‌وکار کوچک ایرانی بیگانه نباشد.
فونت هر دو زبان: Vazirmatn (طراحی‌شده برای فارسی و لاتین با هم).
"""

import flet as ft

# --- پالت ---
PRIMARY = "#1F2D50"
PRIMARY_LIGHT = "#33456F"
ACCENT = "#C68E3D"
ACCENT_DARK = "#9C6F2C"

SURFACE_LIGHT = "#F6F5F2"
SURFACE_DARKMODE = "#15130F"
CARD_LIGHT = "#FFFFFF"
CARD_DARKMODE = "#211F1A"

TEXT_PRIMARY_LIGHT = "#1C1B18"
TEXT_PRIMARY_DARKMODE = "#F1EFE9"
TEXT_SECONDARY_LIGHT = "#6B6862"
TEXT_SECONDARY_DARKMODE = "#A9A69D"

SUCCESS = "#3B7A57"
DANGER = "#B4432F"
BORDER_LIGHT = "#E4E1D8"
BORDER_DARKMODE = "#3A382F"

# نیوی تیره‌تر برای گرادیان نوار کناری — همون PRIMARY ولی با عمق، نه یه رنگ تخت
SIDEBAR_GRADIENT_END = "#121A30"

FONT_FAMILY = "Vazirmatn"

FONT_PATHS = {
    "Vazirmatn": "fonts/Vazirmatn-Regular.ttf",
    "Vazirmatn Medium": "fonts/Vazirmatn-Medium.ttf",
    "Vazirmatn Bold": "fonts/Vazirmatn-Bold.ttf",
}


def build_theme() -> ft.Theme:
    return ft.Theme(
        color_scheme_seed=PRIMARY,
        font_family=FONT_FAMILY,
        use_material3=True,
    )


def build_dark_theme() -> ft.Theme:
    return ft.Theme(
        color_scheme_seed=PRIMARY_LIGHT,
        font_family=FONT_FAMILY,
        use_material3=True,
    )


def card_bgcolor(page: ft.Page) -> str:
    return CARD_DARKMODE if page.theme_mode == ft.ThemeMode.DARK else CARD_LIGHT


def surface_bgcolor(page: ft.Page) -> str:
    return SURFACE_DARKMODE if page.theme_mode == ft.ThemeMode.DARK else SURFACE_LIGHT


def border_color(page: ft.Page) -> str:
    return BORDER_DARKMODE if page.theme_mode == ft.ThemeMode.DARK else BORDER_LIGHT


def text_secondary(page: ft.Page) -> str:
    return TEXT_SECONDARY_DARKMODE if page.theme_mode == ft.ThemeMode.DARK else TEXT_SECONDARY_LIGHT


def sidebar_gradient() -> ft.LinearGradient:
    """گرادیان ظریف نیوی برای نوار کناری — یه رنگ تخت خیلی «فلت»/جنریک به
    نظر می‌رسه؛ یه گرادیان خیلی کم‌جزئیات همون پالت رو عمیق‌تر نشون می‌ده."""
    return ft.LinearGradient(
        begin=ft.Alignment.TOP_CENTER,
        end=ft.Alignment.BOTTOM_CENTER,
        colors=[PRIMARY, SIDEBAR_GRADIENT_END],
    )
