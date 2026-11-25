"""اجزای ظاهری مشترک کل برنامه — کارت، عنوان بخش، نشان وضعیت، دکمه‌ی انتخاب،
نشان برند، سرتیتر صفحه، نشانگر مراحل. هدف: یه زبان بصری یکسان روی همه‌ی
صفحه‌ها (آنبوردینگ، هوش مصنوعی، ربات‌ها، گفتگوها، تنظیمات)، نه فقط صفحه‌های
جدید فاز ۳."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

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
        border_radius=theme.RADIUS_CARD,
        bgcolor=theme.card_bgcolor(page),
        border=ft.Border.all(1, theme.border_color(page)),
        shadow=theme.card_shadow(page),
        content=content,
    )


def section_header(icon: str, text: str) -> ft.Control:
    return ft.Row(
        spacing=10,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Container(
                width=30,
                height=30,
                border_radius=9,
                bgcolor=theme.alpha(theme.PRIMARY, 0x14),
                alignment=ft.Alignment.CENTER,
                content=ft.Icon(icon=icon, color=theme.PRIMARY, size=17),
            ),
            ft.Text(text, size=15, weight=ft.FontWeight.W_600, expand=True),  # expand: متنِ بلند wrap می‌شود، بیرون نمی‌زند
        ],
    )


LABEL_WIDTH = 120  # عرضِ ستونِ برچسب در ردیف‌هایِ «برچسب: مقدار»؛ در همه‌ی صفحه‌ها یکسان


def label_value(page: ft.Page, label: str, value: str, selectable: bool = False, key: Optional[str] = None) -> ft.Control:
    """ردیفِ «برچسب: مقدار» کنارِ هم (۱٫۲٫۱): برچسب با عرضِ ثابت، مقدار بلافاصله کنارش و wrap‌شونده؛\n    نه دو سرِ کارت (SPACE_BETWEEN) که چشم باید میانشان بگردد."""
    return ft.Row(
        key=key,
        spacing=theme.SPACE_SM,
        vertical_alignment=ft.CrossAxisAlignment.START,
        controls=[
            ft.Container(width=LABEL_WIDTH, content=ft.Text(label, size=13, color=theme.text_secondary(page))),
            ft.Text(value, size=13, weight=ft.FontWeight.W_500, selectable=selectable, expand=True),
        ],
    )


def empty_state(page: ft.Page, icon: str, text: str, key: Optional[str] = None) -> ft.Control:
    """حالتِ «خالی» یکدست: آیکنِ کم‌رنگ + یک جمله، وسط‌چین (به‌جای ستونِ خالی)."""
    return ft.Container(
        key=key,
        padding=ft.Padding.symmetric(horizontal=theme.SPACE_LG, vertical=theme.SPACE_XL),
        alignment=ft.Alignment.CENTER,
        content=ft.Column(
            spacing=theme.SPACE_SM,
            tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Icon(icon=icon, size=34, color=theme.alpha(theme.text_secondary(page), 0x99)),
                ft.Text(text, size=theme.FONT_BODY, color=theme.text_secondary(page), text_align=ft.TextAlign.CENTER),
            ],
        ),
    )


def error_note(text: str, key: Optional[str] = None) -> ft.Control:
    """پیامِ خطای کوتاه و راست‌چین با نوارِ رنگیِ کنارش (۱٫۲٫۱)؛ متن wrap می‌شود."""
    return ft.Container(
        key=key,
        padding=ft.Padding.symmetric(horizontal=theme.SPACE_MD, vertical=theme.SPACE_SM),
        border_radius=theme.RADIUS_FIELD,
        bgcolor=theme.alpha(theme.DANGER, 0x14),
        content=ft.Row(
            spacing=theme.SPACE_SM,
            vertical_alignment=ft.CrossAxisAlignment.START,
            controls=[
                ft.Icon(icon=ft.Icons.ERROR_OUTLINE_ROUNDED, size=18, color=theme.DANGER),
                ft.Text(text, size=12.5, color=theme.DANGER, expand=True, selectable=True),
            ],
        ),
    )


def page_header(page: ft.Page, icon: str, title: str, subtitle: str = "", hero: bool = False) -> ft.Control:
    """سرتیترِ یکسانِ هر صفحه (۱٫۲٫۰، هویتِ «Aurora»).

    پیش‌فرض: ردیفِ تمیز با نشانِ گرادیانیِ آیکن‌دار، عنوانِ درشت و زیرعنوانِ کم‌رنگ (حرفه‌ای و کم‌شلوغ).
    ``hero=True`` (فقط خانه): بنرِ گرادیانیِ ایندیگو←بنفش با متنِ سفید و آیکنِ تزئینیِ بزرگ."""
    if hero:
        texts: list[ft.Control] = [ft.Text(title, size=24, weight=ft.FontWeight.W_700, color=theme.ON_SOLID)]
        if subtitle:
            texts.append(ft.Text(subtitle, size=13, color=theme.alpha(theme.ON_SOLID, 0xCC)))
        return ft.Container(
            key="page_hero",
            padding=ft.Padding.symmetric(horizontal=26, vertical=24),
            border_radius=theme.RADIUS_CARD + 4,
            gradient=theme.hero_gradient(),
            shadow=ft.BoxShadow(blur_radius=30, color=theme.alpha(theme.PRIMARY, 0x40), offset=ft.Offset(0, 12)),
            content=ft.Row(
                spacing=18,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Column(spacing=6, tight=True, expand=True, controls=texts),
                    ft.Container(
                        width=76,
                        height=76,
                        border_radius=24,
                        bgcolor=theme.alpha(theme.ON_SOLID, 0x1F),
                        border=ft.Border.all(1, theme.alpha(theme.ON_SOLID, 0x33)),
                        alignment=ft.Alignment.CENTER,
                        content=ft.Icon(icon=icon, color=theme.ON_SOLID, size=38),
                    ),
                ],
            ),
        )
    texts = [ft.Text(title, size=24, weight=ft.FontWeight.W_700, color=theme.text_primary(page))]
    if subtitle:
        texts.append(ft.Text(subtitle, size=13, color=theme.text_secondary(page)))
    return ft.Container(
        padding=ft.Padding(left=0, right=0, top=2, bottom=6),
        content=ft.Row(
            spacing=16,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Container(
                    width=52,
                    height=52,
                    border_radius=16,
                    gradient=theme.hero_gradient(),
                    shadow=ft.BoxShadow(blur_radius=16, color=theme.alpha(theme.PRIMARY, 0x33), offset=ft.Offset(0, 6)),
                    alignment=ft.Alignment.CENTER,
                    content=ft.Icon(icon=icon, color=theme.ON_SOLID, size=26),
                ),
                ft.Column(spacing=3, tight=True, expand=True, controls=texts),
            ],
        ),
    )


def _mounted(owner: ft.Control) -> bool:
    """در Flet 1.0 ``Control.page`` یک property است که پیش از mount شدن RuntimeError می‌دهد؛
    ``getattr(..., None)`` آن استثنا را نمی‌بلعد و تردِ تیکر را در اولین تیک می‌کُشت (باگِ واقعی:
    نوارِ پیشرفتِ دانلود هرگز جلو نمی‌رفت)."""
    try:
        return getattr(owner, "page", None) is not None
    except Exception:  # noqa: BLE001 — هنوز به صفحه اضافه نشده
        return False


def start_ticker(page: ft.Page, owner: ft.Control, tick: Callable[[], None], seconds: float = 15.0, sleep: Callable[[float], None] = time.sleep) -> threading.Thread:
    """بازتازه‌کنندگیِ دوره‌ایِ بخشی از صفحه (تایمرِ معکوسِ زنده).

    هر ``seconds`` ثانیه ``tick()`` را صدا می‌زنه و ``page.update()``. تا وقتی ``owner`` هنوز به صفحه
    اضافه نشده صبر می‌کنه (نه اینکه بمیره)؛ وقتی قبلاً mount شده دیده شد و حالا از صفحه برداشته شده
    (کاربر صفحه را عوض کرد) یا خطایی پیش اومد، متوقف می‌شه."""

    broken: list = []  # tickِ خراب (روی حلقه‌ی رابط) ثبت می‌شود تا تیکر متوقف شود

    def paint() -> None:
        try:
            tick()
            page.update()
        except Exception:  # noqa: BLE001
            broken.append(True)
            raise

    def loop() -> None:
        seen_mounted = False
        unmounted_ticks = 0
        while True:
            sleep(seconds)
            if broken:
                return
            try:
                if not _mounted(owner):
                    if seen_mounted:
                        return  # صفحه عوض شد
                    unmounted_ticks += 1
                    if unmounted_ticks > 60:  # حدودِ یک دقیقه فرصت برای mount شدن
                        return
                    continue
                seen_mounted = True
                unmounted_ticks = 0
                run_on_ui(page, paint)  # نقاشی روی حلقه‌ی رابط (۱٫۲٫۱)
            except Exception:  # noqa: BLE001 — کنترل حذف شده/صفحه بسته؛ بی‌صدا متوقف
                return

    thread = threading.Thread(target=loop, name="ui-ticker", daemon=True)
    thread.start()
    return thread


def screen_frame(page: ft.Page, header: ft.Control, controls: list, key: Optional[str] = None) -> ft.Control:
    """قابِ استانداردِ هر صفحه‌ی داخلِ پوسته: حاشیه‌ی یکسان + **اسکرولِ عمودیِ کامل** (محتوای بلند هیچ‌وقت بیرون نمی‌زنه).

    قبلاً بعضی صفحه‌ها (مشتریان، مدیران) بدونِ حاشیه و با ستونِ خام برگردانده می‌شدن؛ روی پنجره‌های کوچک
    «جا نمی‌شد» و اسکرول درست کار نمی‌کرد. همه‌ی صفحه‌ی جدید باید از همین استفاده کنه.

    قلم ۴ («صفحه انگار زوم شده»): روی پنجره‌ی کشیده با ``theme.content_side_gap`` حاشیه‌ی
    مساویِ دو طرف اضافه می‌شه تا محتوا تا ``theme.CONTENT_MAX_WIDTH`` وسط بایسته؛ روی پنجره‌ی
    کوچک صفر است، پس هیچ‌وقت بریدگیِ افقی نمی‌سازد.
    """
    return ft.Container(
        key=key,
        expand=True,
        padding=ft.Padding.symmetric(horizontal=theme.CONTENT_FRAME_PADDING + theme.content_side_gap(page), vertical=20),
        # قلم ۴: ALWAYS + scrollbar_themeِ خنثیِ theme.py یعنی نوارِ اسکرولِ سمتِ راست
        # همیشه دیده می‌شه؛ کاربر برای فهمیدنِ «ادامه دارد؟» نباید حدس بزند.
        # ۱٫۲٫۱: STRETCH = همه‌ی کارت‌هایِ یک ستون هم‌عرض‌اند (نه هر کدام به اندازه‌ی محتوا)
        content=ft.Column(expand=True, spacing=theme.SPACE_LG - 4, scroll=ft.ScrollMode.ALWAYS,
                          horizontal_alignment=ft.CrossAxisAlignment.STRETCH, controls=[header, *controls]),
    )


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
            colors=[theme.PRIMARY, theme.HERO_END],
        ),
        alignment=ft.Alignment.CENTER,
        content=ft.Icon(icon or ft.Icons.AUTO_AWESOME_ROUNDED, color=theme.ON_SOLID, size=size * 0.52),
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
                bgcolor=color if (is_current or is_done) else theme.STEP_DOT_IDLE,
                animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
            )
        )
    return ft.Row(spacing=6, alignment=ft.MainAxisAlignment.CENTER, controls=dots)


def run_on_ui(page: ft.Page, fn: Callable[[], None]) -> None:
    """``fn`` را روی حلقه‌ی رابط اجرا می‌کند و **هرگز استثنا نمی‌اندازد** (۱٫۲٫۱).

    علتِ «دانلودِ مدل با RuntimeError می‌ماند»: نوار/متنِ پیشرفت از تردِ دانلود دست‌کاری می‌شد و در Flet 1.0 این کار از
    بیرونِ حلقه‌ی رابط ``RuntimeError`` می‌دهد؛ خطا از callbackِ پیشرفت به خودِ دانلود می‌رسید و آن را قطع می‌کرد.
    حالا نقاشی روی حلقه‌ی رابط انجام می‌شود و خطایش فقط لاگ می‌شود، نه دانلود را می‌کُشد. در تست/وبِ بدونِ
    ``run_task``، همان‌جا (هم‌زمان) اجرا می‌شود."""

    async def _go() -> None:
        try:
            fn()
        except Exception:  # noqa: BLE001 — نقاشیِ ناموفق نباید کارِ پس‌زمینه را بشکند
            logger.warning("به‌روزرسانیِ رابط ناموفق بود", exc_info=True)

    runner = getattr(page, "run_task", None)
    if callable(runner):
        try:
            runner(_go)
            return
        except Exception:  # noqa: BLE001
            logger.warning("page.run_task ناموفق بود؛ اجرایِ مستقیم", exc_info=True)
    try:
        fn()
    except Exception:  # noqa: BLE001
        logger.warning("به‌روزرسانیِ رابط ناموفق بود", exc_info=True)


def fit_width(page: ft.Page, preferred: int, reserve: int = 300, minimum: int = 280) -> int:
    """عرضِ دلخواه را به پنجره‌ی فعلی می‌چسباند (۱٫۲٫۰): در پنجره‌ی کوچک یا مقیاسِ ۱۵۰٪ ویندوز کادرِ ثابت‌عرض از صفحه بیرون
    نمی‌زند. ``reserve`` = نوارِ کناری + حاشیه‌ها. اگر پهنای صفحه ناشناخته بود، همان مقدارِ دلخواه."""
    width = getattr(page, "width", None)
    if not isinstance(width, (int, float)) or width <= 0:
        return preferred
    return int(min(preferred, max(minimum, width - reserve)))


def _shape_style(**extra):
    """گوشه‌ی گردِ یکسان برای دکمه‌ها (۱٫۲٫۰). اگر نسخه‌ی Flet پارامتری را نپذیرد، به ظاهرِ پیش‌فرض برمی‌گردد
    تا هیچ‌وقت ساختِ دکمه نشکند."""
    try:
        return ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=theme.RADIUS_FIELD), **extra)
    except Exception:  # noqa: BLE001
        return None


def button_height(size: str) -> int:
    """ارتفاعِ یکی از سه اندازه‌ی استاندارد (``lg`` / ``md`` / ``sm``).

    صفحه‌ها عددِ دلخواه نمی‌نویسند (قلم ۱: «بعضی دکمه‌ها کوچک و بزرگ‌اند»); هر چیزِ
    ناشناخت هم به پیش‌فرضِ ``md`` برمی‌گردد تا هیچ دکمه‌ی بی‌اندازه‌ای نماند."""
    return theme.BTN_SIZES.get(size, theme.BTN_MD)


def primary(
    label: str,
    on_click=None,
    *,
    key: Optional[str] = None,
    icon: str = None,
    size: str = "md",
    width: Optional[int] = None,
    disabled: bool = False,
    visible: bool = True,
    tooltip: Optional[str] = None,
    bgcolor: Optional[str] = None,
    color: Optional[str] = None,
) -> ft.FilledButton:
    """دکمه‌ی اصلیِ اکشن: نیویِ توپُر با متنِ سفید. همان چیزی که قبلاً ``primary_button``
    بود، فقط با مقیاسِ سه‌اندازه. متن دقیقاً همان برچسبِ ارسالی است (تست‌ها با همین پیدا می‌شوند).

    ``bgcolor``/``color`` فقط برای همان معنیِ پالت است: ``theme.DANGER`` روی کنشِ مخربِ
    قطعی (ریست/حذف) — وگرنه پیش‌فرض نیویِ برند می‌ماند."""
    return ft.FilledButton(
        key=key,
        content=label,
        icon=icon,
        bgcolor=bgcolor or theme.PRIMARY,
        color=color or theme.ON_SOLID,
        style=_shape_style(),
        height=button_height(size),
        width=width,
        disabled=disabled,
        visible=visible,
        tooltip=tooltip,
        on_click=on_click,
    )


def secondary(
    label: str,
    on_click=None,
    *,
    key: Optional[str] = None,
    icon: str = None,
    size: str = "md",
    width: Optional[int] = None,
    disabled: bool = False,
    visible: bool = True,
    tooltip: Optional[str] = None,
    bgcolor: Optional[str] = None,
) -> ft.OutlinedButton:
    """دکمه‌ی دومردبی: خط‌کشدار با متنِ نیوی؛ برای «این»، «تغییر بده»، «خروجِ اکسل».
    ``bgcolor`` فقط برای وضعیتِ «انتخاب‌شده» (رنگِ برند) است."""
    return ft.OutlinedButton(
        key=key,
        content=label,
        icon=icon,
        style=_shape_style(color=theme.PRIMARY, bgcolor=bgcolor) or ft.ButtonStyle(color=theme.PRIMARY, bgcolor=bgcolor),
        height=button_height(size),
        width=width,
        disabled=disabled,
        visible=visible,
        tooltip=tooltip,
        on_click=on_click,
    )


def ghost(
    label: str,
    on_click=None,
    *,
    key: Optional[str] = None,
    icon: str = None,
    size: str = "sm",
    width: Optional[int] = None,
    disabled: bool = False,
    visible: bool = True,
    tooltip: Optional[str] = None,
) -> ft.Button:
    """دکمه‌ی بی‌قاب (کم‌اهمیت ولی با سطحِ لمسیِ کامل): بدونِ پس‌زمینه، متنِ نیوی.
    جایی که قبلاً یک ``ft.Container(ink=True)`` نقشِ دکمه را بازی می‌کرد."""
    return ft.Button(
        key=key,
        content=label,
        icon=icon,
        bgcolor=None,
        color=theme.PRIMARY,
        height=button_height(size),
        width=width,
        disabled=disabled,
        visible=visible,
        tooltip=tooltip,
        on_click=on_click,
    )


def text(
    label: str,
    on_click=None,
    *,
    key: Optional[str] = None,
    icon: str = None,
    size: str = "sm",
    width: Optional[int] = None,
    disabled: bool = False,
    visible: bool = True,
    tooltip: Optional[str] = None,
) -> ft.TextButton:
    """دکمه‌ی متنیِ کوچک (لغو، بعداً، کپی، «برو»)."""
    return ft.TextButton(
        key=key,
        content=label,
        icon=icon,
        style=ft.ButtonStyle(color=theme.PRIMARY),
        height=button_height(size),
        width=width,
        disabled=disabled,
        visible=visible,
        tooltip=tooltip,
        on_click=on_click,
    )


def primary_button(
    text: str, on_click, icon: str = None, width: Optional[int] = None, disabled: bool = False
) -> ft.Button:
    """دکمه‌ی اصلیِ بزرگِ صفحه (همان ``BTN_LG``). نگه‌داشته می‌شه چون ۱۲ جایِ برنامه و چند
    تست به نام و به ساختارِ محتوای آن (ردیفِ آیکن+متن) وابسته‌اند؛ تازه‌کاربردها ``primary``."""
    return ft.Button(
        content=ft.Row(
            tight=True,
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=8,
            controls=(
                [ft.Icon(icon, size=17, color=theme.ON_SOLID), ft.Text(text, size=14, weight=ft.FontWeight.W_600)]
                if icon
                else [ft.Text(text, size=14, weight=ft.FontWeight.W_600)]
            ),
        ),
        bgcolor=theme.PRIMARY,
        color=theme.ON_SOLID,
        width=width,
        height=theme.BTN_LG,
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
        border_radius=theme.RADIUS_CARD - 2,
        bgcolor=theme.alpha(accent, 0x0F) if is_selected else theme.card_bgcolor(page),
        border=ft.Border.all(2 if is_selected else 1, accent if is_selected else theme.border_color(page)),
        shadow=(
            ft.BoxShadow(blur_radius=16, color=theme.alpha(accent, 0x33), offset=ft.Offset(0, 4))
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
                    bgcolor=theme.alpha(accent, 0x22) if is_selected else theme.alpha(theme.PRIMARY, 0x12),
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
            bgcolor=theme.alpha(color, 0x22),
            content=ft.Row(tight=True, spacing=6, controls=[self._dot, self._text]),
        )

    def set(self, text: str, color: str) -> None:
        self._dot.color = color
        self._text.value = text
        self._text.color = color
        self.control.bgcolor = theme.alpha(color, 0x22)
