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
BRAND_WARM = "#B0424A"  # سرِ دیگرِ گرادیانِ برند — هم‌رنگِ پایینِ آیکنِ ۱.۰.۰ (اناری)

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
WARNING = "#B4802F"  # هشدارِ غیرخطرناک (مبلغِ رسید نمی‌خونه، موجودیِ کم)
INFO = "#3A6EA5"  # نکته‌ی خنثی (راهنمایی، وضعیتِ عادی)

# مقیاس‌هایِ طراحی — تا صفحه‌ها به‌جای عددِ دلخواه، از یک‌جا وزن/فاصله/گردی بگیرن
RADIUS_CARD = 14
RADIUS_FIELD = 12
RADIUS_PILL = 999
SPACE_XS, SPACE_SM, SPACE_MD, SPACE_LG, SPACE_XL = 6, 10, 16, 24, 32
FONT_CAPTION, FONT_BODY, FONT_SUBTITLE, FONT_TITLE, FONT_DISPLAY = 11.5, 13.5, 15, 18, 24
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


def scrollbar_theme(dark: bool = False) -> ft.ScrollbarTheme:
    """نوارِ اسکرولِ رنگی و همیشه‌دیده (قلم ۴ مستر‌پرامپت): اسکرولِ مخفیِ Material روی پنجره‌ی
    ویندوزِ راست‌چین «کجا اسکرول می‌شه؟» را بی‌جواب می‌گذاشت."""
    thumb = PRIMARY_LIGHT if dark else PRIMARY
    track = f"{PRIMARY}22" if dark else "#EDEFF7"
    return ft.ScrollbarTheme(
        thickness=10,
        radius=6,
        thumb_color=thumb,
        track_color=track,
        interactive=True,
        thumb_visibility=True,
        track_visibility=True,
    )


def build_theme() -> ft.Theme:
    return ft.Theme(
        color_scheme_seed=PRIMARY,
        font_family=FONT_FAMILY,
        use_material3=True,
        scrollbar_theme=scrollbar_theme(False),
    )


def build_dark_theme() -> ft.Theme:
    return ft.Theme(
        color_scheme_seed=PRIMARY_LIGHT,
        font_family=FONT_FAMILY,
        use_material3=True,
        scrollbar_theme=scrollbar_theme(True),
    )


def card_bgcolor(page: ft.Page) -> str:
    return CARD_DARKMODE if page.theme_mode == ft.ThemeMode.DARK else CARD_LIGHT


def surface_bgcolor(page: ft.Page) -> str:
    return SURFACE_DARKMODE if page.theme_mode == ft.ThemeMode.DARK else SURFACE_LIGHT


def border_color(page: ft.Page) -> str:
    return BORDER_DARKMODE if page.theme_mode == ft.ThemeMode.DARK else BORDER_LIGHT


def text_primary(page: ft.Page) -> str:
    """رنگِ متنِ اصلی — با تمِ روشن/تاریک عوض می‌شه (در صفحه‌ها رنگِ ثابت نگذاریم)."""
    return TEXT_PRIMARY_DARKMODE if page.theme_mode == ft.ThemeMode.DARK else TEXT_PRIMARY_LIGHT


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
