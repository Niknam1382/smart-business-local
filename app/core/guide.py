"""
راهنمای درونِ برنامه (N10): مقاله‌های فارسیِ مرحله‌ای + سؤالاتِ متداول + عیب‌یاب، همه آفلاین.

محتوا در ``assets/guide/fa/*.md`` است (نه ``app/content``) چون پوشه‌ی ``assets`` از قبل داخلِ exeِ PyInstaller بسته می‌شه.
هر فایل یک دسته است و می‌تونه چندین مقاله داشته باشه؛ هر مقاله با یک سطرِ عنوان شروع می‌شه::

    ## @شناسه | عنوانِ مقاله | کلیدواژه‌ها، با، ویرگول | گروهِ اختیاری (برای FAQ)

مقاله‌ها می‌تونن به هم لینک بدن: ``[متن](guide:شناسه)``. هر صفحه‌ی برنامه با ``HELP_FOR`` به یک مقاله وصله («؟» کنارِ هر صفحه).
``validate()`` در تست‌ها همه‌ی لینک‌ها/نگاشت‌ها/حداقلِ محتوا را می‌سنجه.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

# (شناسه، عنوان) به ترتیبِ نمایش؛ نامِ فایل = «<شناسه>.md»
CATEGORIES = (
    ("start", "شروع و مفاهیم"),
    ("bot", "ساختِ ربات (تلگرام/بله) و توکن"),
    ("ai", "هوش مصنوعی (API/محلی) و هزینه"),
    ("products", "محصولات (فیزیکی، دیجیتال، کلید، دسته، عکس)"),
    ("order_form", "فرمِ سفارش و تجربه‌ی ربات"),
    ("payments", "پرداخت و تأیید"),
    ("orders", "سفارش‌ها و رزرو"),
    ("support_admins", "پشتیبانی و مدیران"),
    ("marketing", "پیامِ همگانی، کمپین و تخفیف"),
    ("channel_gate", "عضویتِ اجباریِ کانال"),
    ("finance", "مالی و فاکتور"),
    ("safety", "امنیت، پشتیبان و حریمِ خصوصی"),
    ("running", "اجرا (فلش، سرور، Docker) و به‌روزرسانی"),
    ("troubleshooting", "عیب‌یابی"),
    ("faq", "سؤالاتِ متداول"),
)
CATEGORY_TITLE = dict(CATEGORIES)
MIN_TROUBLESHOOTING = 15
MIN_FAQ = 40
MIN_BODY_CHARS = 60

# کلیدِ نوارِ کناری (``shell(active, ...)`` در main) ← مقاله‌ی راهنما؛ «؟» همان صفحه را باز می‌کنه
HELP_FOR = {
    "ai": "ai-choose", "providers": "ai-failover", "usage": "ai-cost", "products": "products-basics", "orders": "orders-flow",
    "experience": "experience-overview", "prompt": "ai-prompt", "bots": "bot-token", "chats": "support-chats", "customers": "customers-book",
    "broadcast": "marketing-broadcast", "discounts": "marketing-discounts", "finance": "finance-overview", "admins": "admins-roles",
    "about": "start-updates", "settings": "safety-backup",
}

_LINK = re.compile(r"\]\(guide:([A-Za-z0-9_-]+)\)")
_HEAD = re.compile(r"^##\s+@([A-Za-z0-9_-]+)\s*\|(.*)$")


@dataclass(frozen=True)
class Article:
    id: str
    title: str
    category: str
    body: str
    keywords: tuple = ()
    group: str = ""
    order: int = 0
    links: tuple = field(default=())

    @property
    def category_title(self) -> str:
        return CATEGORY_TITLE.get(self.category, self.category)


def content_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "assets" / "guide" / "fa"
    return Path(__file__).resolve().parents[2] / "assets" / "guide" / "fa"


_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_MARKS = re.compile("[\u064b-\u065f\u0670\u0640\u200c\u200d\u200e\u200f]")


def normalize(text: str) -> str:
    """برای جستجو: ي/ك عربی ← فارسی، حذفِ اعراب/کشیده/نیم‌فاصله، ارقامِ فارسی/عربی ← لاتین، حروفِ کوچک."""
    t = str(text or "").replace("ي", "ی").replace("ك", "ک").replace("ۀ", "ه").replace("ة", "ه").translate(_DIGITS)
    return _MARKS.sub("", t).lower()


def parse_file(text: str, category: str) -> list:
    """یک فایلِ دسته ← مقاله‌ها. سطرهای قبل از اولین ``## @`` نادیده گرفته می‌شن (توضیحِ دسته)."""
    articles, current, body = [], None, []

    def flush() -> None:
        if current is not None:
            text_body = "\n".join(body).strip()
            articles.append(Article(current[0], current[1], category, text_body, current[2], current[3], len(articles), tuple(_LINK.findall(text_body))))

    for line in text.splitlines():
        m = _HEAD.match(line)
        if m:
            flush()
            parts = [p.strip() for p in m.group(2).split("|")]
            title = parts[0] if parts else ""
            kws = tuple(k.strip() for k in re.split(r"[،,]", parts[1]) if k.strip()) if len(parts) > 1 else ()
            group = parts[2] if len(parts) > 2 else ""
            current, body = (m.group(1), title, kws, group), []
        elif current is not None:
            body.append(line)
    flush()
    return articles


@lru_cache(maxsize=1)
def load_all(directory: Optional[str] = None) -> tuple:
    root = Path(directory) if directory else content_dir()
    items: list = []
    for cat, _title in CATEGORIES:
        path = root / f"{cat}.md"
        if path.is_file():
            items.extend(parse_file(path.read_text(encoding="utf-8"), cat))
    return tuple(items)


def by_id(article_id: str) -> Optional[Article]:
    return next((a for a in load_all() if a.id == article_id), None)


def in_category(category: str) -> list:
    return [a for a in load_all() if a.category == category]


def help_article(screen_key: str) -> Optional[Article]:
    aid = HELP_FOR.get(screen_key)
    return by_id(aid) if aid else None


def search(query: str, limit: int = 30) -> list:
    """همه‌ی واژه‌ها باید در مقاله باشن (AND)؛ امتیاز: عنوان ۶، کلیدواژه ۳، بدنه ۱ (+ ۲ اگه عبارتِ کامل در عنوان باشه)."""
    q = normalize(query).strip()
    tokens = [t for t in re.split(r"[^\w]+", q) if t]
    if not tokens:
        return []
    scored = []
    for a in load_all():
        title, kws, body = normalize(a.title), normalize(" ".join(a.keywords)), normalize(a.body)
        score = 0
        for t in tokens:
            s = (6 if t in title else 0) + (3 if t in kws else 0) + (1 if t in body else 0)
            if not s:
                score = 0
                break
            score += s
        if score and q in title:
            score += 2
        if score:
            scored.append((-score, a.order, a.id, a))
    scored.sort(key=lambda x: x[:3])
    return [x[3] for x in scored[:limit]]


def faq_groups() -> list:
    """گروه‌های FAQ به ترتیبِ ظهور: ``[(گروه, [مقاله])]``."""
    groups: dict = {}
    for a in in_category("faq"):
        groups.setdefault(a.group or "عمومی", []).append(a)
    return list(groups.items())


def validate(articles: Optional[tuple] = None) -> list:
    """فهرستِ مشکلاتِ محتوا (خالی = سالم): تکراری، لینکِ شکسته، «؟»ِ بی‌مقاله، متنِ خیلی کوتاه، کمبودِ عیب‌یابی/FAQ.
    ``articles`` فقط برای تست (محتوای جایگزین)."""
    articles = tuple(articles) if articles is not None else load_all()
    problems, seen = [], set()
    ids = {a.id for a in articles}
    for a in articles:
        if a.id in seen:
            problems.append(f"شناسه‌ی تکراری: {a.id}")
        seen.add(a.id)
        if not a.title or a.category not in CATEGORY_TITLE:
            problems.append(f"{a.id}: عنوان/دسته نامعتبر")
        if len(a.body) < MIN_BODY_CHARS:
            problems.append(f"{a.id}: متنِ خیلی کوتاه")
        problems += [f"{a.id}: لینکِ شکسته → {t}" for t in a.links if t not in ids]
    problems += [f"HELP_FOR[{k}] → {v} وجود ندارد" for k, v in HELP_FOR.items() if v not in ids]
    count = lambda cat: sum(1 for a in articles if a.category == cat)  # noqa: E731
    if count("troubleshooting") < MIN_TROUBLESHOOTING:
        problems.append(f"عیب‌یابی کمتر از {MIN_TROUBLESHOOTING} مورد")
    if count("faq") < MIN_FAQ:
        problems.append(f"FAQ کمتر از {MIN_FAQ} مورد")
    problems += [f"دسته‌ی خالی: {cat}" for cat, _t in CATEGORIES if not count(cat)]
    return problems
