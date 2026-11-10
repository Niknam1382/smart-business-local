"""نگهبانِ نظمِ ظاهری (قلم ۱ِ باگ‌هایِ گزارش‌شدهٔ مالک).

سه چیزی که مالک دید: دکمه‌هایِ بی‌اندازه، قهوه‌ایِ بی‌مورد برای جلبِ توجه، و اسکرولِ نامتناسب با UI.
هر سه به عدد/قاعده‌یِ ثابتِ ``app/theme.py`` و ``app/screens/common.py`` میخ می‌شوند، پس بازگشتِ
«هر صفحه یک ارتفاعِ دلخواه» یا «قابِ دست‌سازِ هر صفحه» قرمز می‌شود.
"""

import re
from pathlib import Path

from app import theme
from app.screens import common

SCREENS = Path(__file__).resolve().parents[1] / "app" / "screens"

# صفحه‌هایِ واقعیِ منو (کارت‌هایِ داخلِ صفحه‌ها اینجا نیستند؛ آن‌ها card می‌سازند)
PAGES = ["home", "orders", "settings_screen", "broadcast", "products", "customers", "finance", "chat_view",
         "about", "admins", "bot_experience", "guide", "search", "prompt_studio", "mode_select", "welcome"]


def test_one_button_scale_is_defined_once():
    assert (theme.BTN_LG, theme.BTN_MD, theme.BTN_SM) == (46, 40, 34)
    assert theme.BTN_SIZES == {"lg": theme.BTN_LG, "md": theme.BTN_MD, "sm": theme.BTN_SM}
    assert common.button_height("lg") == theme.BTN_LG
    assert common.button_height("هرچیزِ ناشناخته") == theme.BTN_MD  # بی‌اندازه نماند


def test_the_shared_builders_honour_the_scale():
    noop = lambda *_: None  # noqa: E731
    assert common.primary("ذخیره", noop).height == theme.BTN_MD
    assert common.primary("ذخیره", noop, size="lg").height == theme.BTN_LG
    assert common.secondary("ادامه", noop, size="lg").height == theme.BTN_LG
    assert common.ghost("بعدا", noop).height == theme.BTN_SM
    assert common.text("لغو", noop).height == theme.BTN_SM
    assert common.primary_button("آزمایش", noop).height == theme.BTN_LG  # مسیرِ قدیمیِ ۱۲ صفحه


def test_the_scrollbar_is_neutral_not_the_brand_navy():
    light, dark = theme.scrollbar_theme(dark=False), theme.scrollbar_theme(dark=True)
    assert light.thumb_color == theme.SCROLL_THUMB_LIGHT and light.thumb_color != theme.PRIMARY
    assert dark.thumb_color == theme.SCROLL_THUMB_DARK and dark.thumb_color != theme.PRIMARY_LIGHT
    assert light.thickness == 8 and light.radius == 6
    assert light.thumb_visibility is True  # قلم ۴: کاربر برای «ادامه دارد؟» حدس نمی‌زند
    assert light.track_color == theme.SCROLL_TRACK_LIGHT and light.track_color != theme.SURFACE_LIGHT


def test_home_spreads_its_cards_instead_of_overflowing():
    """قلم ۱/۴: «صفحه انگار زوم شده و از کادر بیرون رفته» — کارت‌ها باید شبکه‌ایِ پاسخگو باشند
    (۱۲ ستون در تنگ، ۳ ستون در کشیده)، نه چهار کارتِ ۲۱۰ پیکسلیِ ثابت که رویِ پنجره‌ی ۹۶۰
    تا لبه‌یِ چپ بیرون بزنند."""
    src = (SCREENS / "home.py").read_text(encoding="utf-8")
    assert "width=210" not in src
    assert re.search(r"col=\{[^}]*\"xs\": *12", src), "کارتِ KPI باید با شبکه‌یِ پاسخگو چیده بشه"
    assert src.count("alignment=ft.MainAxisAlignment.START") >= 2, "ردیفِ wrap در RTL بی‌تراز، خطِ آخر را به چپ پرت می‌کنه"


def test_every_menu_page_uses_the_shared_frame():
    """قابِ هر صفحه = حاشیه + اسکرولِ همیشه‌دیده + وسط‌چینیِ محتوا؛ دوباره‌سازیِ آن یعنی همان
    «صفحه انگار زوم شده و از کادر بیرون رفته» که مالک گزارش کرد."""
    missing = []
    for name in PAGES:
        path = SCREENS / f"{name}.py"
        assert path.is_file(), f"{name}.py رفته از بین رفته"
        text = path.read_text(encoding="utf-8")
        if "screen_frame(" not in text and "onboarding_frame(" not in text:
            missing.append(name + ".py")
    assert not missing, f"این صفحه‌ها قابِ مشترک ندارند: {missing}"


def test_the_brown_brand_colour_is_not_the_attention_colour():
    """هشدارِ واقعی رنگِ WARNING/DANGER را دارد؛ ACCENT فقط برند و انتخابِ فعال است.
    یک ``DANGER if … else ACCENT`` که شاخه‌یِ خطر را درست رنگ می‌کند، تخلف نیست."""
    offenders = []
    for path in sorted(SCREENS.glob("*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if re.search(r"(error|warn|note|danger|هشدار|خطر)", line, re.I) and "theme.ACCENT" in line:
                if re.search(r"theme\.(DANGER|WARNING)", line):
                    continue
                offenders.append(f"{path.name}:{line.strip()[:88]}")
    assert not offenders, "جلبِ توجه باید رنگِ معنایی داشته باشه، نه قهوه‌ایِ برند:\n" + "\n".join(offenders)


def test_the_warning_colour_is_actually_used():
    """پیش از این WARNING فقط دو جا به کار می‌رفت و بقیه قهوه‌ای بودند؛ حالا رنگِ معناییِ خودش جا افتاده."""
    users = [p.name for p in SCREENS.glob("*.py") if "theme.WARNING" in p.read_text(encoding="utf-8")]
    assert len(users) >= 5, f"رنگِ هشدار فقط در {len(users)} صفحه به کار رفته: {users}"
