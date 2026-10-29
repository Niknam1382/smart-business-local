"""دکمه‌های سفارشیِ منوی ربات (R5): مدل، اعتبارسنجی، بارگذاریِ امن.

⚠️ تلگرام/بله دکمه‌ی URL با ``tel:`` رو رد می‌کنن و *کلِ پیام* نمی‌ره؛ پس «تماس» = پیامِ شماره + ``sendContact``.
URL فقط ``http(s)://`` (بدونِ ``javascript:``/``tel:``/…) پذیرفته می‌شه.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from app.core.ui import safe_url

ACTIONS = (
    "url", "text", "phone", "support", "open_catalog", "open_cart", "open_orders", "checkout", "ask_ai", "share_contact",
)
MAX_BUTTONS = 8
_ID = re.compile(r"^[a-z][a-z0-9_]{0,15}$")
_PHONE_OK = re.compile(r"^\+?[0-9][0-9\-\s()]{3,20}$")
PLATFORMS = ("telegram", "bale")


@dataclass
class CustomButton:
    id: str
    label: str
    action: str
    emoji: str = ""
    config: dict = field(default_factory=dict)
    platforms: list = field(default_factory=lambda: list(PLATFORMS))
    row: int = 0

    @property
    def display(self) -> str:
        return f"{self.emoji} {self.label}".strip()


def validate(raw: dict) -> Optional[str]:
    if not isinstance(raw, dict):
        return "تعریفِ دکمه باید یک شیء باشه."
    if not _ID.match(str(raw.get("id", ""))):
        return "شناسه‌ی دکمه باید با حرفِ انگلیسی شروع بشه (حروف کوچک/عدد/_ ، حداکثر ۱۶)."
    label = str(raw.get("label", "")).strip()
    if not label or len(label) > 30:
        return "برچسبِ دکمه لازمه (حداکثر ۳۰ کاراکتر)."
    if len(str(raw.get("emoji", ""))) > 8:
        return "ایموجی خیلی بلنده."
    action = raw.get("action")
    if action not in ACTIONS:
        return "نوعِ عملِ دکمه نامعتبره."
    config = raw.get("config") or {}
    if not isinstance(config, dict):
        return "تنظیماتِ دکمه نامعتبره."
    if action == "url" and not safe_url(str(config.get("url", ""))):
        return "لینک باید با http:// یا https:// شروع بشه (tel: و javascript: مجاز نیست؛ برای تماس از «تماس» استفاده کن)."
    if action == "phone" and not _PHONE_OK.match(str(config.get("phone", "")).strip()):
        return "شماره‌ی تماس معتبر نیست."
    if action == "text":
        text = str(config.get("text", "")).strip()
        if not text or len(text) > 1500:
            return "متنِ پاسخ لازمه (حداکثر ۱۵۰۰ کاراکتر)."
    if action == "ask_ai":
        question = str(config.get("question", "")).strip()
        if not question or len(question) > 300:
            return "متنِ پرسش لازمه (حداکثر ۳۰۰ کاراکتر)."
    plats = raw.get("platforms", list(PLATFORMS))
    if not isinstance(plats, list) or not plats or any(p not in PLATFORMS for p in plats):
        return "پلتفرم‌ها باید از telegram/bale باشن."
    return None


def validate_all(raw_list: list) -> Optional[str]:
    if not isinstance(raw_list, list):
        return "لیستِ دکمه‌ها نامعتبره."
    if len(raw_list) > MAX_BUTTONS:
        return f"حداکثر {MAX_BUTTONS} دکمه‌ی سفارشی مجازه."
    seen_ids: set = set()
    seen_labels: set = set()
    for raw in raw_list:
        error = validate(raw)
        if error:
            return error
        if raw["id"] in seen_ids:
            return f"شناسه‌ی «{raw['id']}» تکراریه."
        seen_ids.add(raw["id"])
        display = f"{raw.get('emoji', '')} {raw['label']}".strip()
        if display in seen_labels:
            return f"برچسبِ «{display}» تکراریه."
        seen_labels.add(display)
    return None


def load(settings) -> list:
    """دکمه‌های معتبر؛ مورد معیوب نادیده گرفته می‌شه (هرگز exception نمی‌ده)."""
    raw = getattr(settings, "custom_buttons", None)
    out: list = []
    if not isinstance(raw, list):
        return out
    for item in raw[:MAX_BUTTONS]:
        if validate(item) is None:
            out.append(
                CustomButton(
                    id=item["id"], label=item["label"].strip(), action=item["action"], emoji=str(item.get("emoji", "")).strip(),
                    config=dict(item.get("config") or {}), platforms=list(item.get("platforms", PLATFORMS)), row=int(item.get("row", 0) or 0),
                )
            )
    return out


def visible(settings, platform: str) -> list:
    return [b for b in load(settings) if platform in b.platforms]
