"""نگهبانِ عددِ نسخه.

خطایی که این فایل جلو می‌گیره: عددِ نسخه در چند جایِ مستندات hard-code می‌شه (badge ریدمی،
سرِجُلفه‌ی CHANGELOG، راهنماهایِ انتشار و متن‌هایِ داخلِ برنامه) و جاهایِ فراموش‌شده بعداً
تاریخچه‌ای می‌سازن که وجود خارجی نداره — مثلاً «از نسخه‌ی ۱.۱.۰» در حالی که مخزن فقط یک انتشار
داره. قاعده‌ی پروژه: ``app/version.py`` تنها جایی است که عدد را **تعریف** می‌کنه، و هر عددِ
نسخه‌نمایِ دیگری در مخزن باید یا همان ``__version__`` باشد یا صراحتاً استثنا شده باشد.
"""

import re
import subprocess
from pathlib import Path

from app.version import __version__

ROOT = Path(__file__).resolve().parent.parent
PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩"
LATIN_DIGITS = "01234567890123456789"

# عددِ نسخه‌نما: سه گروهِ رقم با نقطه — هم لاتین و هم فارسی/عربی.
ASCII_VERSION = re.compile(r"(?<![\d.\w/])(\d+\.\d+\.\d+)(?![\d.\w])")
PERSIAN_VERSION = re.compile(r"(?<![\d.\w/])([۰-۹٠-٩]+(?:\.[۰-۹٠-٩]+){2})(?![\d.\w])")

# چیزی که «غیرکد» حساب می‌شه: مستندات، راهنما، CI، بسته‌بندی.
DOC_SUFFIXES = {".md", ".txt", ".yml", ".yaml", ".iss", ".ini", ".toml", ".cfg", ".dockerignore", ".gitattributes", ".editorconfig"}
DOC_NAMES = {"Dockerfile", "docker-compose.yml", "LICENSE"}

# یک ``name==1.2.3`` عددِ خودِ برنامه نیست — پس پین‌ها (حتی داخلِ کامنتِ «این بسته را اضافه
# نکن») از خودِ خطوطِ فایلِ الزامات خوانده می‌شن و لازم نیست دستی فهرست شوند.
REQUIREMENT_PIN = re.compile(r"[A-Za-z0-9_.\-]+ *(?:==|>=|<=|~=|!=) *(\d+\.\d+\.\d+)")

# استثناهایِ عددِ کتابخانه/ابزار در جاهایِ دیگر، با دلیلِ صریح. عددِ تازه‌ای که اینجا لازم شود
# یعنی یک تصمیمِ آگاهانه: پینِ یک ابزار عوض شده، نه نسخه‌ی برنامه.
LIBRARY_VERSIONS: dict[str, tuple[str, set[str]]] = {
    ".github/workflows/ci.yml": ("پینِ ruff در CI", {"0.17.1"}),
    ".github/workflows/release.yml": ("پینِ ابزارِ بیلد در کامنتها (flet-cli 1.0.1، fpdf2، uharfbuzz، segno)", {"0.40.0", "1.0.1", "1.6.0", "1.7.2", "2.8.5"}),
    "docs/RELEASING.md": ("نسخه‌ی fpdfِ قدیمی و پینِ fpdf2 در دستورِ تعمیرِ وابستگی", {"1.7.2", "2.8.5"}),
    "installer/SmartBusinessLocal.iss": ("پیش‌فرضِ ``AppVersion`` که با ``/DAppVersion`` پر می‌شه", {"0.0.0"}),
}

# فایل‌هایی که عددِ نسخه در آن‌ها **دیتایِ تست** است (مقایسه‌ی نسخه، نامِ آرشیو، تاریخِ جلالی،
# مبلغِ هزارتایی) — نه ادعایی درباره‌ی نسخه‌ی برنامه.
TEST_DATA_FILES: dict[str, str] = {
    "tests/test_about_screen.py": "دیتایِ صفحه‌ی «درباره»",
    "tests/test_i18n_keys.py": "دیتایِ کلیدهایِ i18n",
    "tests/test_jalali.py": "تاریخِ جلالیِ ۱۴۰۵.۰۲.۱۵، نه نسخه",
    "tests/test_package_release.py": "نامِ آرشیوِ ساختگیِ بیلد",
    "tests/test_receipts.py": "مبلغِ ۱.۲۵۰.۰۰۰ ریال در متنِ رسید",
    "tests/test_update_apply.py": "منطقِ مقایسه‌ی نسخه",
    "tests/test_update_banner_install.py": "منطقِ مقایسه‌ی نسخه",
    "tests/test_update_install.py": "منطقِ مقایسه‌ی نسخه",
    "tests/test_updater.py": "منطقِ مقایسه‌ی نسخه",
    "app/screens/live.py": "کامنتِ «سورس Flet 1.0.1» — عددِ کتابخانه",
    "tests/test_version_consistency.py": "خودِ جدولِ استثنا (پینِ کتابخانه‌ها را به‌عنوانِ داده نگه می‌دارد)",
}

QUOTED_VERSION = re.compile(r"[\"']((?:\d+\.){2}\d+)[\"']|[\"']([۰-۹]+(?:\.[۰-۹]+){2})[\"']")


def _latin(text: str) -> str:
    return text.translate(str.maketrans(PERSIAN_DIGITS, LATIN_DIGITS))


def _repo_paths():
    """فایل‌هایِ مخزن؛ اگر git نبود پیمایشِ فایل‌سیستمی (تا کپیِ بدونِ ``.git`` هم بگیری می‌شه)."""
    try:
        done = subprocess.run(("git", "ls-files"), cwd=str(ROOT), capture_output=True, text=True, check=True)
        return [ROOT / line.strip() for line in done.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.CalledProcessError):
        skip = {".git", ".pytest_cache", ".ruff_cache", "__pycache__", "dist", "build", "node_modules"}
        return [p for p in ROOT.rglob("*") if p.is_file() and not (skip & set(p.relative_to(ROOT).parts))]


def _numbers(text: str) -> set:
    return set(ASCII_VERSION.findall(text)) | set(PERSIAN_VERSION.findall(text))


def _doc_files():
    for path in _repo_paths():
        if not path.is_file():
            continue
        if path.suffix == ".py" or path.name.startswith("."):
            continue
        if path.suffix not in DOC_SUFFIXES and path.name not in DOC_NAMES:
            continue
        yield path


def _line_of(text: str, number: str) -> int:
    for line, row in enumerate(text.splitlines(), 1):
        if number in row:
            return line
    return 0


def test_version_py_is_the_single_source_of_the_version():
    """``app/version.py`` تنها فایلِ تعریف‌کننده و تنها فایلِ غیرتستی است که عددِ نسخه را داخلِ
    یک رشته نگه می‌دارد؛ هر جایِ دیگر باید آن را با import بگیرد."""
    definitions, literals = [], []
    for path in _repo_paths():
        if path.suffix != ".py" or not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"^\s*__version__\s*=", text, re.M):
            definitions.append(rel)
        for match in QUOTED_VERSION.finditer(text):
            literals.append((rel, match.group(1) or match.group(2)))
    assert definitions == ["app/version.py"], f"عددِ نسخه در بیش از یک فایل تعریف شده: {definitions}"
    strays = sorted({(rel, number) for rel, number in literals if rel != "app/version.py" and rel not in TEST_DATA_FILES})
    assert not strays, f"عددِ نسخه بیرونِ app/version.py و بیرونِ دیتایِ تست hard-code شده: {strays}"


def test_shipped_code_never_claims_another_version():
    """هیچ فایلِ ``app/`` یا ``scripts/`` عددِ نسخه‌ی دیگری (لاتین یا فارسی) در خود ندارد، پس
    نه صفحه‌ی «درباره»، نه راهنما و نه بسته‌بندی می‌توانند نسخه‌ای جز ``app/version.py`` بگویند."""
    offenders = []
    for folder in ("app", "scripts"):
        for path in (ROOT / folder).rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if rel in TEST_DATA_FILES:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for number in _numbers(text):
                if _latin(number) != __version__:
                    offenders.append(f"{rel}:{_line_of(text, number)} → {number}")
    assert not offenders, "عددِ نسخه‌ی دیگری در کدِ منتشرشده:\n" + "\n".join(sorted(offenders))


def test_readme_badge_release_names_and_changelog_follow_the_version():
    """badge نسخه، نامِ فایل‌هایِ Release نوشته‌شده در README و همه‌ی سِرجُلفه‌هایِ ``## [x]``
    در CHANGELOG باید همان ``__version__`` را بخوانند."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    badges = re.findall(r"img\.shields\.io/badge/version-([^)-]+)-", readme)
    assert badges, "badgeِ نسخه در README پیدا نمی‌شه"
    assert set(badges) == {__version__}, f"badgeهایِ README با {__version__} نمی‌خوانن: {sorted(set(badges))}"

    docs_text = readme + "\n" + "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in _doc_files() if path.suffix in {".md", ".txt"})
    names = re.findall(r"SmartBusinessLocal-(?!<)[\w.\u06f0-\u06f9]+-(?:windows|linux)", docs_text)
    wrong = sorted({name.split("-")[1] for name in names if _latin(name.split("-")[1]) != __version__})
    assert not wrong, f"نامِ فایلِ Release با عددِ نوشته‌شده در version.py نمی‌خونه: {wrong}"

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## \[([^\]]+)\]", changelog, re.M)
    assert headings, "هیچ سِرجُلفه‌ی ``## [x.y.z]`` در CHANGELOG نیست"
    wrong_headings = [head for head in headings if head != __version__]
    assert not wrong_headings, f"CHANGELOG بخش‌هایِ دیگری دارد (تاریخچه‌ی ساختگی؟): {wrong_headings}"


def test_no_document_hard_codes_another_app_version():
    """در همه‌ی فایل‌هایِ غیرکد (مستندات، راهنما، CI، نصب‌کننده) هر عددِ نسخه‌نما یا
    ``__version__`` است یا یک پینِ کتابخانه است — پینِ الزامات از خودِ خطوطِ ``name==x.y.z``
    خوانده می‌شه و بقیه در ``LIBRARY_VERSIONS`` با دلیلِ صریح آمده‌اند."""
    offenders = []
    for path in _doc_files():
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        allowed = {_latin(number) for number in REQUIREMENT_PIN.findall(text)}
        allowed |= {_latin(number) for number in LIBRARY_VERSIONS.get(rel, ("", set()))[1]}
        for number in _numbers(text):
            if _latin(number) in allowed or _latin(number) == __version__:
                continue
            offenders.append(f"{rel}:{_line_of(text, number)} → {number}")
    assert not offenders, (
        "عددِ نسخه‌ی برنامه در فایلِ غیرکدِ دیگری hard-code شده (یا یک پینِ تازه بیونِ ثبتِ صریح): \n"
        + "\n".join(sorted(offenders))
        + f"\nاگر عددِ نسخه عوض شده: همه‌جا را با همین نسخه‌ی جاری ({__version__}) هم‌خوان کن."
    )
