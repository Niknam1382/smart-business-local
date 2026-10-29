"""«از صفر شروع» (۱.۰.۰ ← بازخوردِ مالک): مخزن/زیپِ تحویلی هرگز نباید داده‌ی شخصی، توکن یا فایلِ داده داشته باشه، و
نصبِ تازه باید کاملاً خام باشه."""

import dataclasses
import re
from pathlib import Path

from app.core.settings import AppSettings

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__", ".ruff_cache", ".pytest_cache", ".venv", "build", "dist", "node_modules"}
FORBIDDEN_NAMES = {"settings.json", "secret.key", "heartbeat.json", "portable.flag", ".env"}
FORBIDDEN_SUFFIXES = (".db", ".db-wal", ".db-shm", ".db-journal", ".sqlite", ".sqlite3", ".log", ".key", ".pem")
FORBIDDEN_DIRS = {"SmartBusinessData", "product_photos", "backups", "logs"}
# مقدارهای نمونه‌ی مجاز (ساختگی) در مستندات/متن‌های راهنما
FAKE_PHONES = {"09123456789", "09121234567", "09120000000", "09121111111"}
FAKE_CARDS = {"6037991234567890", "6219861012345678", "6037991100000000", "6219861000000000", "6037-9912-3456-7890", "6219-8610-1234-5678", "6219-8610-0000-0000", "1111111111111111", "۱۲۳۴-۵۶۷۸-۹۰۱۲-۳۴۵۶"}
TEXT_SUFFIXES = {".py", ".md", ".txt", ".yml", ".yaml", ".json", ".toml", ".iss", ".sh", ".bat", ".ini", ".cfg", ".html", ".css", ".js"}


def repo_files():
    for path in ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        yield path


def test_no_data_files_or_data_folders_in_the_repository():
    bad = []
    for path in repo_files():
        rel = path.relative_to(ROOT)
        if path.is_dir() and path.name in FORBIDDEN_DIRS:
            bad.append(str(rel))
        elif path.is_file() and (path.name in FORBIDDEN_NAMES or path.name.endswith(FORBIDDEN_SUFFIXES) or path.suffix == ".zip"):
            bad.append(str(rel))
    assert not bad, f"فایل/پوشه‌ی داده یا حساس در مخزن: {bad}"


def test_no_real_looking_secrets_or_personal_numbers_in_text_files():
    problems = []
    token = re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")  # توکنِ ربات
    api_key = re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")
    phone = re.compile(r"(?<!\d)09\d{9}(?!\d)")
    card = re.compile(r"(?<!\d)(?:\d{4}-){3}\d{4}(?!\d)|(?<!\d)\d{16}(?!\d)")
    for path in repo_files():
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES or "tests" in path.relative_to(ROOT).parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = str(path.relative_to(ROOT))
        for rx, name in ((token, "bot token"), (api_key, "api key")):
            if rx.search(text):
                problems.append(f"{rel}: {name}")
        problems += [f"{rel}: phone {m}" for m in phone.findall(text) if m not in FAKE_PHONES]
        problems += [f"{rel}: card {m}" for m in card.findall(text) if m not in FAKE_CARDS]
    assert not problems, problems


def test_default_settings_are_completely_empty_so_first_run_starts_from_zero():
    d = dataclasses.asdict(AppSettings())
    assert d["onboarding_complete"] is False and d["business_mode"] is None and d["user_name"] == ""
    secrets = [k for k, v in d.items() if k.endswith("_encrypted") and v]
    assert not secrets, f"مقدارِ پیش‌فرضِ حساس: {secrets}"
    assert not d["owner_chats"] and not d["custom_buttons"] and not d["faq_items"] and not d["checkout_fields"] and not d["bot_texts"]


def test_welcome_placeholder_is_a_neutral_sample_not_a_real_person():
    from app.i18n import t

    for lang in ("fa", "en"):
        assert t("welcome.name_hint", lang) in {"مثلاً علی", "e.g. Alex"}


def test_creator_identity_lives_only_in_branding_py_among_source_files():
    """هویتِ سازنده (لینک/ایمیل/نام‌کاربری) تنها داده‌ی شخصیِ مجازه و فقط در ``app/branding.py`` تعریف می‌شه؛
    بقیه‌ی کد باید از همان بخونه — تا جایی ناخواسته (مثلاً داخلِ پیامِ ربات) پخش نشه."""
    allowed = {Path("app/branding.py")}
    offenders = []
    for path in (ROOT / "app").rglob("*.py"):
        rel = path.relative_to(ROOT)
        if rel in allowed:
            continue
        text = path.read_text(encoding="utf-8").lower()
        if "niknam" in text or "mohammad_mahdi" in text:
            offenders.append(str(rel))
    assert not offenders, f"هویتِ سازنده خارج از branding.py: {offenders}"


def test_new_settings_fields_default_to_empty_and_safe_values():
    s = AppSettings()
    assert s.bot_bio_text == "" and s.bot_bio_confirmed is False and s.bale_bio_supported is None
    assert s.update_dismissed_version == "" and s.update_last_check_ts == 0 and s.data_acknowledged is False
    assert s.update_check_enabled is True  # فقط یک GET ساده به GitHub؛ کاربر می‌تونه خاموشش کنه
