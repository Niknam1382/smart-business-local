"""N10 — محتوای راهنما: سلامتِ لینک‌ها/نگاشت‌ها، جستجوی فارسی، تعدادِ حداقلیِ عیب‌یابی/FAQ، مقاله‌های اجباری، صحتِ ادعاها."""

import re
from pathlib import Path

import pytest

from app.core import guide, jalali

REQUIRED_IDS = {
    # مقاله‌های اجباریِ تعیین‌شده
    "start-updates", "start-creator-credit", "ai-failover", "start-support-dev", "ai-savings", "ai-cache-safety", "finance-invoice", "finance-overview",
}
ROOT = Path(__file__).resolve().parents[1]


def test_content_is_valid():
    assert guide.validate() == []


def test_counts_and_required_articles():
    articles = guide.load_all()
    assert len(guide.in_category("troubleshooting")) >= 15 and len(guide.in_category("faq")) >= 40
    assert REQUIRED_IDS <= {a.id for a in articles}
    assert [c for c, _t in guide.CATEGORIES] == ["start", "bot", "ai", "products", "order_form", "payments", "orders", "support_admins", "marketing", "channel_gate", "finance", "safety", "running", "troubleshooting", "faq"]
    assert all(len(a.body) >= guide.MIN_BODY_CHARS and a.keywords for a in articles), "هر مقاله باید کلیدواژه و متنِ کامل داشته باشد"
    groups = dict(guide.faq_groups())
    assert len(groups) >= 6 and all(len(v) >= 2 for v in groups.values())


def test_every_internal_link_resolves_and_no_orphans():
    ids = {a.id for a in guide.load_all()}
    linked = set()
    for a in guide.load_all():
        for target in a.links:
            assert target in ids, f"{a.id} → {target}"
            linked.add(target)
        assert not re.search(r"\]\((?!guide:|https://)[^)]*\)", a.body), f"لینکِ نامعتبر در {a.id}"
    # هر مقاله‌ی غیرِ-FAQ از جایی قابل‌دسترسی است (دسته‌بندی همیشه هست؛ اینجا فقط «راه‌حل‌های عیب‌یاب» باید لینک بخورن)
    for needed in ("ts-token-invalid", "ts-no-connection", "ts-proxy", "ts-bot-silent", "ts-clock", "ts-webhook", "ts-ai-key", "ts-disk", "ts-pay-link", "ts-channel"):
        assert needed in ids


def test_every_sidebar_help_target_exists():
    for screen_key, article_id in guide.HELP_FOR.items():
        article = guide.help_article(screen_key)
        assert article is not None and article.id == article_id
    assert guide.help_article("unknown-screen") is None


def test_help_covers_every_sidebar_screen():
    import re as _re

    src = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    keys = set(_re.findall(r'nav_item\(\s*"([a-z_]+)"', src)) | set(_re.findall(r'nav_item\("([a-z_]+)"', src))
    assert keys, "کلیدهای ناوبری پیدا نشد"
    missing = keys - set(guide.HELP_FOR) - {"guide"}
    assert not missing, f"صفحه‌های بدونِ «؟»: {sorted(missing)}"


@pytest.mark.parametrize("query,expect", [
    ("توکن", "bot-token"), ("وب‌هوک", "ts-webhook"), ("وبهوک", "ts-webhook"), ("webhook", "ts-webhook"), ("كارت به كارت", "payments-card"),
    ("مالیات", "finance-vat"), ("پروكسی", "bot-proxy"), ("پشتیبان", "safety-backup"), ("فاکتور برگشتی", "finance-credit-note"),
    ("۴۰۹", "ts-webhook"), ("بله پی", "payments-bale-pay"), ("کش", "ai-savings"),
])
def test_search_finds_the_right_article_near_the_top(query, expect):
    found = [a.id for a in guide.search(query, limit=8)]
    assert expect in found, (query, found)


def test_search_edge_cases():
    assert guide.search("") == [] and guide.search("   ") == [] and guide.search("!!!") == []
    assert guide.search("xyzzy-no-such-thing") == []
    assert len(guide.search("ربات", limit=5)) == 5
    # همه‌ی واژه‌ها باید باشن (AND)
    both = guide.search("بله‌پی زرین‌پال")
    assert both and all("زرین" in guide.normalize(a.title + a.body) and "بله" in guide.normalize(a.title + a.body) for a in both)
    # نرمال‌سازی
    assert guide.normalize("كارتِ ي ۱۲٣") == guide.normalize("کارتِ ی 123")
    assert guide.normalize("می‌کنه") == guide.normalize("میکنه")


def test_parse_file_format():
    arts = guide.parse_file("intro\n## @a-1 | عنوان | x، y | گروه\nمتنِ اول\n\n## @b_2 | دوم\nمتن", "faq")
    assert [a.id for a in arts] == ["a-1", "b_2"] and arts[0].keywords == ("x", "y") and arts[0].group == "گروه" and arts[1].keywords == ()
    assert arts[0].body == "متنِ اول" and arts[0].category_title == guide.CATEGORY_TITLE["faq"]
    assert guide.parse_file("بدونِ مقاله", "faq") == []


def test_validate_catches_problems(tmp_path):
    (tmp_path / "start.md").write_text(
        "## @x | عنوان | k\nکوتاه\n\n## @x | دوباره | k\nیک متنِ به‌اندازه‌ی کافی بلند که از حداقل بیشتر باشد و [شکسته](guide:nope) را دارد.", encoding="utf-8")
    problems = " | ".join(guide.validate(guide.load_all(str(tmp_path))))
    for expected in ("شناسه‌ی تکراری: x", "x: متنِ خیلی کوتاه", "لینکِ شکسته → nope", "HELP_FOR[", "عیب‌یابی کمتر", "FAQ کمتر", "دسته‌ی خالی: bot"):
        assert expected in problems, expected
    assert guide.validate() == []  # محتوای واقعی دست‌نخورده


def test_claims_in_guide_match_the_product():
    """ادعاهای حساسِ مقاله‌ها با واقعیتِ کد/تنظیمات یکی باشند (تا راهنما دروغ نگوید)."""
    from app.core import finance, settings as settings_module

    s = settings_module.AppSettings()
    vat = guide.by_id("finance-vat").body
    assert f"{jalali.fa_digits(s.invoice_vat_rate_bp // 100)}٪" in vat  # نرخِ پیش‌فرضِ ذکرشده = پیش‌فرضِ تنظیمات
    assert s.invoice_auto_send == "off" and "خاموش" in guide.by_id("finance-invoice").body
    assert "۲۰۰ نویسه" in guide.by_id("finance-ledger").body and finance.MAX_NOTE == 200
    assert "۵۰ مگابایت" in guide.by_id("products-delivery").body
    assert "۳ " in guide.by_id("marketing-broadcast").body and "۲۴ ساعت" in guide.by_id("marketing-broadcast").body
    assert s.quickstart_dismissed is False


def test_content_ships_inside_assets_for_pyinstaller():
    assert guide.content_dir() == ROOT / "assets" / "guide" / "fa" and all((guide.content_dir() / f"{c}.md").is_file() for c, _t in guide.CATEGORIES)
