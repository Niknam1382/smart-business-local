"""برندِ برنامه — همه‌ی مقدارهای عمومیِ سازنده یک‌جا (لینک‌ها، اعتبار، کلیدِ عمومیِ به‌روزرسانی).

این مقدارها را خودِ مالک برای نمایش داده؛ تنها داده‌ی «شخصی»ِ مجاز در مخزن هستن (``tests/test_repo_hygiene.py``
فقط همین‌ها را مجاز می‌داند و توکن/کارت/تلفنِ ناشناخته را همچنان رد می‌کند).

اگه نامِ ریپوی GitHub فرق کرد فقط ``GITHUB_REPO`` را عوض کن؛ بقیه‌ی آدرس‌ها از روی آن ساخته می‌شن.
"""

APP_NAME_FA = "کسب‌وکار هوشمند"
APP_NAME_EN = "Smart Business"
APP_NAME_LOCAL_EN = "Smart Business Local"

CREATOR_NAME_FA = "محمد مهدی"
CREATOR_NAME_EN = "Mohammad Mahdi"
GITHUB_PROFILE = "https://github.com/niknam1382"
GITHUB_REPO = "niknam1382/smart-business-local"
INSTAGRAM = "https://www.instagram.com/mohammad_mahdi_niknam"
CONTACT_EMAIL = "niknam151412@gmail.com"

DARAMET_USERNAME = "Niknam1382"
DARAMET_WEBINTENT_ENABLED = True
DARAMET_MESSAGE_MAX = 100

# نشانِ کوچکِ سازنده در بیوگرافیِ ربات (N17) — فقط همین یک جا؛ بدونِ متن در پیام‌ها/سفارش/پرداخت
CREDIT_FA = "ساخته‌شده با کسب‌وکار هوشمند · github.com/niknam1382"
CREDIT_EN = "Made with Smart Business · github.com/niknam1382"
CREDIT_SEPARATOR = " · "

# کلیدِ عمومیِ Ed25519 برای اعتبارِ فایلِ به‌روزرسانی؛ بعد از اجرای scripts/make_signing_key.py پر می‌شه.
# خالی = نصبِ یک‌کلیکی غیرفعال و فقط دانلودِ دستی از GitHub.
UPDATE_PUBLIC_KEY_B64 = ""


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
