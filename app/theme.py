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

# ---- قاعده‌ی رنگِ «توجه» (قلم ۳ — شکایتِ مالک: «قهوه‌ایِ بی‌مورد برای جلبِ توجه») ----
# ACCENT / ACCENT_DARK فقط هویتِ برند و وضعیتِ «انتخاب‌شده» هستند: لوگو، نقطه‌ی آیتمِ
# فعالِ منو، کارتِ برگزیده، زبانِ فعال، سِریِ اصلیِ نمودار.
# هر چیزِ دیگری که معنی‌اش از پالتِ معنایی می‌آید، رنگِ معنایی خودش را می‌گیرد:
#   WARNING  ← هشدارِ غیرخطرناک و «در انتظارِ بررسی» (تأییدِ سفارش، رباتِ خاموش، تأییدِ ارسال)
#   DANGER   ← خطر/خرابی/ردِ عملیات (خطای شبکه، مبلغِ نمی‌خونه، حذف)
#   SUCCESS  ← موفقیت و انجام‌شده
#   INFO     ← نکته‌ی خنثی (بنرِ «نسخه‌ی تازه»، راهنما، وضعیتِ عادی)
# پس هیچ صفحه‌ای برای «باید دیده بشه چون مشکلی هست» حق ندارد از ACCENT استفاده کند.

# مقیاس‌هایِ طراحی — تا صفحه‌ها به‌جای عددِ دلخواه، از یک‌جا وزن/فاصله/گردی بگیرن
RADIUS_CARD = 14
RADIUS_FIELD = 12
RADIUS_PILL = 999
SPACE_XS, SPACE_SM, SPACE_MD, SPACE_LG, SPACE_XL = 6, 10, 16, 24, 32
FONT_CAPTION, FONT_BODY, FONT_SUBTITLE, FONT_TITLE, FONT_DISPLAY = 11.5, 13.5, 15, 18, 24
BORDER_LIGHT = "#E4E1D8"
BORDER_DARKMODE = "#3A382F"

# رنگِ روشنی که روی آن متنِ سفید می‌نشیند (دکمه‌ی توپُر، بنرهای تیره) — تا #FFFFFF
# در هر صفحه‌ای جدا نوشته نشه و یک‌جا عوض بشه
ON_SOLID = "#FFFFFF"

# خنثی‌هایِ بی‌رنگِ همان پالتِ کاغذی (قهوه‌ایِ روشنِ بسیار کم‌اشباع) — قبلاً همین
# مقدارها به‌صورت هگزِ خام در home/common/sidebar نوشته شده بود
CHART_BAR_EMPTY = "#D8D5CC"  # ستونِ خالیِ نمودارِ فروش (روزِ بی‌فروش)
STEP_DOT_IDLE = "#D8D4C8"  # نقطه‌ی مرحله‌ی «هنوز نرسیده» در آنبوردینگ
SIDEBAR_ON_DARK = "#93E6B7"  # نشانِ نسخه روی نوارِ کناریِ نیوی
SIDEBAR_TEXT_DIM = "#C7CCDA"  # متن/آیکنِ آیتمِ عادیِ منو
SIDEBAR_TEXT_FAINT = "#8B92A8"  # سرتیترِ گروه و زیرنویسِ منو
SIDEBAR_ACTIVE_BG = "#FFFFFF2B"  # پس‌زمینه‌ی نیمه‌شفافِ آیتمِ فعالِ منو
SIDEBAR_DIVIDER = "#FFFFFF1F"  # خطِ جداکننده‌ی گروه‌ها روی نیوی

# ---- مقیاسِ دکمه (قلم ۱ — شکایتِ مالک: «بعضی دکمه‌ها کوچک و بزرگ‌اند») ----
# فقط همین سه ارتفاع در کل برنامه وجود دارد؛ صفحه‌ها عددِ دلخواه نمی‌نویسند
BTN_LG = 46  # اکشنِ اصلیِ صفحه (ذخیره/ارسال/ادامه) — همان ارتفاعِ primary_buttonِ قدیم
BTN_MD = 40  # پیش‌فرضِ بقیه‌ی دکمه‌ها (فیلدِ اکشنِ کارت، ردیفِ ابزار)
BTN_SM = 34  # کنشِ کمکیِ متنی داخلِ ردیف/کارت (لغو، بعداً، کپی)
BTN_SIZES = {"lg": BTN_LG, "md": BTN_MD, "sm": BTN_SM}

# ---- مقیاسِ محتوا ----
CONTENT_MAX_WIDTH = 1040  # سقفِ عرضِ ستونِ محتوا؛ پنجره‌ی بزرگ‌شده متن را لبه‌به‌لبه نکِشَد
CONTENT_SIDE_CHROME = 288  # نوارِ کناری (۲۳۲) + حاشیه‌ی قابِ صفحه (۲×۲۸)
CONTENT_FRAME_PADDING = 28  # حاشیه‌ی پیش‌فرضِ screen_frame در هر طرف

# نیوی تیره‌تر برای گرادیان نوار کناری — همون PRIMARY ولی با عمق، نه یه رنگ تخت
SIDEBAR_GRADIENT_END = "#121A30"

FONT_FAMILY = "Vazirmatn"

FONT_PATHS = {
    "Vazirmatn": "fonts/Vazirmatn-Regular.ttf",
    "Vazirmatn Medium": "fonts/Vazirmatn-Medium.ttf",
    "Vazirmatn Bold": "fonts/Vazirmatn-Bold.ttf",
}


# ---- پالتِ خنثیِ نوارِ اسکرول (قلم ۱/۴ — شکایتِ مالک: «رنگِ اسکرول‌ها به UI نمی‌خورد») ----
# thumb دیگر PRIMARY (نیویِ تقریباً مشکی) نیست: از میانه‌ی BORDER_* و TEXT_SECONDARY_*
# می‌آید، یعنی همان خاکستریِ گرمِ سطحِ کارت، فقط کمی تیره‌تر تا دیده شود.
SCROLL_THUMB_LIGHT = "#B7B3A8"
SCROLL_THUMB_DARK = "#6E6B61"
SCROLL_TRACK_LIGHT = f"{BORDER_LIGHT}33"  # نیمه‌شفاف: بک‌گراندِ کاغذی از زیرش معلوم باشه
SCROLL_TRACK_DARK = f"{BORDER_DARKMODE}4D"


def scrollbar_theme(dark: bool = False) -> ft.ScrollbarTheme:
    """نوارِ اسکرولِ باریک، خنثی و همیشه‌دیده.

    دو چیز لازم بود: (۱) مخفی نبودن — قلم ۴: کاربر برای فهمیدنِ «ادامه دارد؟» نباید حدس بزند؛
    (۲) هم‌خانواده بودن با سطحِ کارت — قبلاً thumb با PRIMARY (نیویِ تقریباً مشکی) رنگ می‌شد،
    پس روی کاغذِ کرم یک میله‌ی تیره‌ی بیگانه می‌خوابید. حالا thumb از میانه‌ی BORDER و
    TEXT_SECONDARY می‌آید (خاکستریِ ملایمِ همان پالت) و track نیمه‌شفاف است.
    """
    return ft.ScrollbarTheme(
        thickness=8,
        radius=6,
        thumb_color=SCROLL_THUMB_DARK if dark else SCROLL_THUMB_LIGHT,
        track_color=SCROLL_TRACK_DARK if dark else SCROLL_TRACK_LIGHT,
        interactive=True,
        thumb_visibility=True,  # ALWAYS در screen_frame + این = همیشه دیده می‌شه
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


def content_side_gap(page: ft.Page) -> float:
    """فاصله‌ی اضافیِ هر دو طرفِ محتوا، فقط روی پنجره‌ی کشیده (قلم ۴: «صفحه انگار زوم شده»).

    روی پنجره‌ی بزرگ‌شده متن و کارت نباید لبه‌به‌لبه کشیده شود؛ روی پنجره‌ی کوچک هیچ
    فاصله‌ی اضافه‌ای نمی‌شه، چون باعثِ اسکرول/بریدگیِ افقی می‌شه. وسط‌چین با حاشیه‌ی مساوی
    انجام می‌شه (نه ``width`` روی ستون) تا ``expand`` و اسکرولِ عمودیِ قاب نشکنن.
    ``page.width`` فقط روی صفحه‌ی واقعی هست؛ در تست‌های FakePage نبودش یعنی «سقفی لازم نیست».
    """
    total = getattr(page, "width", None) or 0
    try:
        available = float(total) - CONTENT_SIDE_CHROME
    except (TypeError, ValueError):  # pragma: no cover — مقدارِ عجیب از میزبان
        return 0.0
    if available <= CONTENT_MAX_WIDTH:
        return 0.0
    return (available - CONTENT_MAX_WIDTH) / 2


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
