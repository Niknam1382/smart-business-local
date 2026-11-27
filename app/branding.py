"""برندِ برنامه — همه‌ی مقدارهای عمومیِ سازنده یک‌جا (لینک‌ها، اعتبار، کلیدِ عمومیِ به‌روزرسانی).

این مقدارها را خودِ مالک برای نمایش داده؛ تنها داده‌ی «شخصی»ِ مجاز در مخزن هستن (``tests/test_repo_hygiene.py``
فقط همین‌ها را مجاز می‌داند و توکن/کارت/تلفنِ ناشناخته را همچنان رد می‌کند).

اگه نامِ ریپوی GitHub فرق کرد فقط ``GITHUB_REPO`` را عوض کن؛ بقیه‌ی آدرس‌ها از روی آن ساخته می‌شن.
"""

import os
import re

APP_NAME_FA = "کسب‌وکار هوشمند"
APP_NAME_EN = "Smart Business"
APP_NAME_LOCAL_EN = "Smart Business Local"

CREATOR_NAME_FA = "محمد مهدی"
CREATOR_NAME_EN = "Mohammad Mahdi"
GITHUB_PROFILE = "https://github.com/niknam1382"
GITHUB_REPO = "niknam1382/smart-business-local"
# فقط برای آزمونِ آپدیت روی یک مخزنِ جدا (۱٫۲٫۰): متغیرِ محیطیِ SMART_BUSINESS_UPDATE_REPO=<owner>/<repo> مخزنِ بررسیِ
# به‌روزرسانی را عوض می‌کند. فقط قالبِ «نام/نام» پذیرفته می‌شود؛ هر چیزِ دیگر نادیده گرفته می‌شود.
_REPO_OVERRIDE = os.environ.get("SMART_BUSINESS_UPDATE_REPO", "").strip()
if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}", _REPO_OVERRIDE or ""):
    GITHUB_REPO = _REPO_OVERRIDE
INSTAGRAM = "https://www.instagram.com/mohammad_mahdi_niknam"
CONTACT_EMAIL = "niknam151412@gmail.com"

DARAMET_USERNAME = "Niknam1382"
DARAMET_WEBINTENT_ENABLED = True
DARAMET_MESSAGE_MAX = 100

# نشانِ کوچکِ سازنده در بیوگرافیِ ربات (N17) — فقط همین یک جا؛ بدونِ متن در پیام‌ها/سفارش/پرداخت
# ۱٫۲٫۱: فقط لینکِ مخزن (بدونِ متنِ فارسی/انگلیسیِ همراه)؛ برایِ هر دو زبان یکی است.
CREDIT_FA = "github.com/Niknam1382/smart-business-local"
CREDIT_EN = CREDIT_FA
CREDIT_SEPARATOR = " · "
# شکل‌هایِ قدیمیِ خطِ اعتبار که ممکن است از قبل روی بیوگرافیِ ربات‌ها نشسته باشد؛ فقط برایِ شناختن/برداشتن و جایگزینی.
LEGACY_CREDITS = (
    "ساخته‌شده با کسب‌وکار هوشمند · github.com/Niknam1382/smart-business-local",
    "Made with Smart Business · github.com/Niknam1382/smart-business-local",
    "ساخته‌شده با کسب‌وکار هوشمند · github.com/niknam1382",
    "Made with Smart Business · github.com/niknam1382",
)

# کلیدِ عمومیِ Ed25519 برای اعتبارِ فایلِ به‌روزرسانی؛ بعد از اجرای scripts/make_signing_key.py پر می‌شه.
# خالی = نصبِ یک‌کلیکی غیرفعال و فقط دانلودِ دستی از GitHub.
UPDATE_PUBLIC_KEY_B64 = "agBBOXMUkod3D7aQRuBFq/iNp3SKN3UeO3HAaqKOCwc="


def github_repo_url() -> str:
    return f"https://github.com/{GITHUB_REPO}"


def github_releases_url() -> str:
    return f"{github_repo_url()}/releases"


def github_latest_release_api() -> str:
    return f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def github_issues_url() -> str:
    return f"{github_repo_url()}/issues/new"


def daramet_profile_url() -> str:
    return f"https://daramet.com/{DARAMET_USERNAME}"


def credit_for(lang: str) -> str:
    return CREDIT_EN if lang == "en" else CREDIT_FA
