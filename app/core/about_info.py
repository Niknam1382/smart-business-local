"""اطلاعاتِ صفحه‌ی «درباره»: لینکِ گزارشِ مشکل (فقط نسخه و سیستم‌عامل — هیچ داده‌ی خصوصی) و ایمیلِ تماس."""

from __future__ import annotations

import platform
from urllib.parse import quote

from app import branding


def os_label() -> str:
    """«Windows 10» / «Linux 6.x»؛ فقط نامِ سیستم‌عامل و نسخه‌اش — نه نامِ کاربر، نه نامِ رایانه، نه آدرس."""
    system = platform.system() or "Unknown"
    release = platform.release() or ""
    return f"{system} {release}".strip()


def issue_url(version: str, os_text: str = "") -> str:
    """صفحه‌ی «Issue جدید» در GitHub با متنِ از پیش‌پُرشده (نسخه/سیستم‌عامل)."""
    body = (
        f"**نسخه / Version:** {version}\n"
        f"**سیستم‌عامل / OS:** {os_text or os_label()}\n\n"
        "### مشکل چیه؟ / What's wrong?\n\n\n"
        "### چطور تکرارش کنم؟ / Steps to reproduce\n\n\n"
        "> ⚠️ توکنِ ربات، کلیدِ API و اطلاعاتِ مشتری‌ها رو اینجا نذار. / "
        "Never paste bot tokens, API keys or customer data here.\n"
    )
    return f"{branding.github_issues_url()}?body={quote(body, safe='')}"


def mailto_url() -> str:
    return f"mailto:{branding.CONTACT_EMAIL}"
