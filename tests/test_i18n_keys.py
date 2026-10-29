"""هیچ کلیدِ خامِ i18n (مثلِ «about.title») نباید به کاربر نشون داده بشه: هر t("...") در صفحه‌ها باید دو زبانه تعریف شده باشه."""

import re
from pathlib import Path

from app import i18n

APP = Path(__file__).resolve().parents[1] / "app"


def used_keys():
    files = list((APP / "screens").glob("*.py")) + [APP / "main.py"]
    found = {}
    for path in files:
        for m in re.finditer(r'(?<![\w.])t\(\s*"([a-zA-Z0-9_.]+)"', path.read_text(encoding="utf-8")):
            found.setdefault(m.group(1), path.name)
    return found


def test_every_key_used_by_screens_exists():
    missing = {k: f for k, f in used_keys().items() if k not in i18n.STRINGS}
    assert not missing, f"کلیدِ i18nِ تعریف‌نشده: {missing}"


def test_every_string_has_both_languages_and_no_stray_braces_in_plain_texts():
    for key, entry in i18n.STRINGS.items():
        assert entry.get("fa") and entry.get("en"), key
        for lang in ("fa", "en"):
            names = re.findall(r"\{(\w*)\}", entry[lang])
            assert all(names), (key, lang)  # آکولادِ خالی ممنوع
    # متن‌های تازه با پارامترِ درست رندر می‌شن
    for key, kw in (("about.version", {"version": "1.1.0"}), ("update.banner", {"version": "1.2.0"}), ("found.count_products", {"n": 3})):
        for lang in ("fa", "en"):
            assert "{" not in i18n.t(key, lang, **kw)
