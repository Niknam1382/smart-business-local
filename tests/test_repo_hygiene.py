"""«از صفر شروع» (۱.۰.۰ ← بازخوردِ مالک): مخزن/زیپِ تحویلی هرگز نباید داده‌ی شخصی، توکن یا فایلِ داده داشته باشه، و
نصبِ تازه باید کاملاً خام باشه."""

import dataclasses
import re
import subprocess
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


def _git(*args):
    """خروجیِ git، یا None اگر git روی این ماشین نباشد/مخزن نباشد."""
    try:
        done = subprocess.run(("git",) + args, cwd=str(ROOT), capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return done.stdout.splitlines()


def _tracked_files():
    lines = _git("ls-files")
    if lines is None:
        return None
    return [Path(ROOT / line.strip()) for line in lines if line.strip()]


def _walk_all():
    for path in ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        yield path


def repo_files():
    """فایل‌هایِ واقعِ مخزن. اگر git نبود، به پیمایشِ فایل‌سیستمی برمی‌گردد — تورِ امنیتی
    هرگز نباید با «skip» خوابیده باشد (بیلد از سورس‌تارب یا یک کپیِ بدونِ .git)."""
    tracked = _tracked_files()
    if tracked is None:
        yield from (p for p in _walk_all() if p.is_file())
        return
    for path in tracked:
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        yield path


def _loose_files():
    """چیزی که روی دیسک هست ولی هنوز tracked نیست — همان چیزی که `git add -A` واردِ مخزن می‌کنه."""
    rows = _git("status", "--porcelain", "--untracked-files=all")
    if rows is None:
        return
    for row in rows:
        if not row.startswith("?? "):
            continue
        path = Path(ROOT / row[3:].strip().strip('"'))
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        yield path


def test_loose_data_or_secret_files_would_not_be_committed():
    """هشدارِ پیش از Staging: یک `settings.json`/`secret.key`/`*.db` که در پوشه افتاده، قبل از
    اینکه کسی با «add all» آن را واردِ مخزن کند، همین‌جا لو می‌رود. (تستِ فایل‌های tracked این را
    نمی‌بیند، چون هنوز tracked نیستند.)"""
    bad = []
    for path in _loose_files():
        if path.name in FORBIDDEN_NAMES or path.name.endswith(FORBIDDEN_SUFFIXES) or path.suffix == ".zip":
            bad.append(str(path.relative_to(ROOT)))
    assert not bad, f"فایلِ داده/راز در پوشه رها شده و با `git add -A` واردِ مخزن می‌شود: {bad}"


CJK_RANGES = ("\u3000-\u303f", "\u3040-\u30ff", "\u3400-\u4dbf", "\u4e00-\u9fff", "\uf900-\ufaff")


def test_no_cjk_characters_crept_into_persian_or_english_text():
    """کامنت‌ها و متن‌های این پروژه فارسی/انگلیسی‌اند. یک نویسه‌ی چینیِ جا‌مانده (اشتباهِ واقعیِ
    چندباره در توسعه) در فایلِ منتشرشده معنی‌دار نیست و نباید به مخزن عمومی برسد."""
    pattern = re.compile("[" + "".join(CJK_RANGES) + "]")
    offenders = []
    for path in repo_files():
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for number, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{number}")
    assert not offenders, f"نویسه‌ی چینی در متنِ مخزن: {offenders}"


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
    assert s.bot_bio_text == "" and s.bot_bio_confirmed is False
    assert s.update_dismissed_version == "" and s.update_last_check_ts == 0 and s.data_acknowledged is False
    assert s.update_check_enabled is True  # فقط یک GET ساده به GitHub؛ کاربر می‌تونه خاموشش کنه
    # ۱.۰.۰: بله فقط درگاهِ پرداخت است ⇒ هر دو توکن و خودِ درگاه باید خاموش/خالی شروع بشن
    assert s.bale_pay_enabled is False and s.bale_pay_bot_token_encrypted == "" and s.bale_pay_provider_token_encrypted == ""
    assert s.bale_pay_link_mode == "auto"
    # فاکتورِ PDF نباید بی‌اجازه‌ی مالک برای مشتری برود؛ رسید/هشدارِ پرداخت هم پیش‌فرضِ امن‌اند
    assert s.invoice_auto_send == "after_confirm"
    assert s.receipt_check_enabled is True and s.receipt_amount_check is True and s.alert_on_payment_claim is True


DELETED_MODULES = ("app.core.bale_client", "bale_client", "app.core.bale_adapter", "bale_adapter",
                   "app.core.ai_providers", "ai_providers", "app.core.ai_cache", "ai_cache", "zarinpal")
# فایل‌هایی که هنوز به دستِ عاملِ دیگرِ همین بازآرایی پیوت نشده‌اند. هر یک باید «واقعا» متخلف باشد
# (تا به‌محضِ اصلاح، این فهرست پیر شود و تست بفهمد) و هیچ فایلِ تازه‌ای نباید به آن اضافه شود.
PENDING_PIVOT_BY_OTHER_AGENTS: set = set()


def test_deleted_modules_are_never_imported_again():
    """۱.۰.۰ این ماژول‌ها را کُشت؛ هر وارداتِ باقی‌مانده یعنی یا فایلِ مرده‌ای هست یا import خطادار."""
    offenders = []
    for path in repo_files():
        if not path.is_file() or path.suffix != ".py":
            continue
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name in DELETED_MODULES:
            if re.search(rf"(?:import|from)\s+[\w.]*\b{re.escape(name)}\b", text):
                offenders.append((rel, name))
    real = [f"{rel}: {name}" for rel, name in offenders if rel not in PENDING_PIVOT_BY_OTHER_AGENTS]
    assert not real, f"وارداتِ ماژولِ حذف‌شده: {real}"
    # فهرستِ استثنا نباید از خودِ فایل‌ها جا بیفتد (هرگز به «تسهیلِ» تست منجر نشه)
    stale = sorted(PENDING_PIVOT_BY_OTHER_AGENTS - {rel for rel, _ in offenders})
    assert not stale, f"استثنایِ منقضی‌شده را حذف کن: {stale}"


def test_no_bale_messenger_or_remote_ai_or_portable_keys_remain_in_shipped_code():
    """نه «حالتِ قابل‌حمل»، نه «APIِ هوش مصنوعی»، نه «رباتِ گفتگویِ بله» — این نام‌ها نباید در
    کدِ عرضه‌شده (برنامه/اسکریپت‌ها/نصب‌کننده) زنده باشند (جلوگیری از بازگشتِ تصادفیِ رفتارِ حذف‌شده)."""
    forbidden = ("bale_enabled", "bale_bot_token_encrypted", "bale_bio_supported", "zarinpal_",
                 "api_base_url", "api_key_encrypted", "api_model_name", "ai_providers", "portable_dir",
                 "find_portable_dir", "is_portable", "PORTABLE_ROOT")
    allowed = {"app/core/settings.py"}  # فهرستِ کلیدهایِ قدیمیِ حذف‌شده عمداً فقط همان‌جا می‌آید
    offenders = []
    roots = [ROOT / "app", ROOT / "scripts", ROOT / "installer"] + [p for p in ROOT.glob("*.py")]
    for root in roots:
        files = [root] if root.is_file() else list(root.rglob("*"))
        for path in files:
            if not path.is_file() or path.suffix not in {".py", ".iss", ".txt", ".toml"}:
                continue
            rel = path.relative_to(ROOT).as_posix()
            if rel in allowed or "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for word in forbidden:
                if word in text:
                    offenders.append(f"{rel}: {word}")
    assert not offenders, f"کلید/رفتارِ حذف‌شده هنوز در کدِ عرضه‌شده: {offenders}"
