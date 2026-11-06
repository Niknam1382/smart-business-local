"""نگهبانِ فایلِ نصب‌کننده‌ی ویندوز (Inno Setup).

باگِ واقعیِ همین ۱.۰.۰: نامِ میان‌بُرِ «حذفِ برنامه» این‌طور نوشته شده بود —
``{autoprograms}\حذفِ برنامه / Uninstall Smart Business Local``
ویندوز ``/`` را در نامِ فایل قبول نمی‌کند و Inno آن را جداکننده‌ی پوشه می‌گیرد، پس هر نصبِ ویندوزی
با «IPersistFile::Save failed; code 0x80070003. The system cannot find the path specified.» تمام
می‌شد (فایل‌ها نصب می‌شدند، فقط میان‌بُر ساخته نمی‌شد). این فایل همین را جلو می‌گیرد — و دو قاعده‌ی
دیگرِ همین نصب‌کننده را که یک‌بار شکستنشان دردناک است: BOM برایِ متنِ فارسی، و «حذفِ برنامه هیچ
داده‌ای را پاک نمی‌کند».
"""

import re
from pathlib import Path

from scripts import package_release as pkg

ISS = Path(__file__).resolve().parent.parent / "installer" / "SmartBusinessLocal.iss"
BACKSLASH = chr(92)
ILLEGAL_IN_FILENAME = set("/" + BACKSLASH + ':*?"<>|')


def _text() -> str:
    """متنِ فایل، بدونِ BOM (که خودش در یک تستِ جداگانه پین می‌شه)."""
    return ISS.read_bytes().decode("utf-8-sig")


def _section(name: str) -> list:
    """خطوطِ واقعیِ یک بخشِ ``[name]`` — کامنت‌ها و خط‌های خالی حذف می‌شن."""
    lines, inside = [], False
    for raw in _text().splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            inside = line == f"[{name}]"
            continue
        if inside and line and not line.startswith(";") and not line.startswith("//"):
            lines.append(line)
    return lines


def test_shortcut_names_have_no_characters_windows_rejects():
    """هیچ جزءِ نامِ میان‌بُر (جزِ ثابتِ ``{...}`` اولِ مسیر) نباید کاراکترِ ممنوعه داشته باشد.
    ``/`` همان چیزی بود که نصبِ ۱.۰.۰ را خراب می‌کرد."""
    offenders = []
    for entry in _section("Icons"):
        match = re.match(r'^Name:\s*"([^"]+)"', entry)
        if not match:
            offenders.append(f"خطِ [Icons] قابل‌تحلیل نیست: {entry[:70]}")
            continue
        parts = match.group(1).split(BACKSLASH)
        tail = BACKSLASH.join(parts[1:])
        bad = sorted({c for c in tail if c in ILLEGAL_IN_FILENAME})
        if bad:
            offenders.append(f"{match.group(1)[:70]} → {bad}")
    assert not offenders, "نامِ میان‌بُرِ نصب‌کننده کاراکترِ غیرمجازِ ویندوزی دارد:\n" + "\n".join(offenders)


def test_the_uninstall_entry_still_exists_and_is_findable():
    """میان‌بُرِ حذف باید بماند (با نامِ مجاز)؛ نبودنش یعنی کاربرِ تازه راهِ ساده‌ی حذف ندارد."""
    entries = _section("Icons")
    uninstall = [e for e in entries if '"{uninstallexe}"' in e]
    assert len(uninstall) == 1, f"دقیقاً یک میان‌بُر برای {{uninstallexe}} لازم است، هست: {len(uninstall)}"
    name = re.search(r'^Name:\s*"([^"]+)"', uninstall[0]).group(1)
    assert "Uninstall" in name and "حذف" in name, f"نامِ میان‌بُرِ حذف دوزبانه نیست: {name}"


def test_the_script_is_saved_with_a_bom_or_persian_text_breaks():
    """کامپایلرِ Inno بدونِ BOM فایل را با codepageِ سیستم می‌خواند و رشته‌هایِ فارسی خراب می‌شوند."""
    assert ISS.read_bytes().startswith(b"\xef\xbb\xbf"), "installer/SmartBusinessLocal.iss باید UTF-8 با BOM باشد"


def test_install_is_per_user_and_uninstall_never_touches_user_data():
    """دو قولِ محصول در همین فایل: نصب بدونِ ادمین برایِ کاربرِ فعلی، و پاک‌نکردنِ هیچ داده‌ای."""
    setup = {}
    for line in _section("Setup"):
        match = re.match(r"^(\w+)\s*=\s*(.*)$", line)
        if match:
            setup[match.group(1).lower()] = match.group(2)
    assert setup["privilegesrequired"] == "lowest", "نصب باید per-user بماند (بی‌ادمین)"
    assert setup["defaultdirname"].startswith("{autopf}"), "پوشه‌ی پیش‌فرض باید {autopf} باشد تا کاربر بتواند عوضش کند"
    assert not _section("UninstallDelete"), "[UninstallDelete] باید خالی بماند: هیچ داده‌ی کاربری پاک نمی‌شه"


def test_the_output_name_matches_the_packaging_contract():
    """``package_release.find_windows_installer`` دقیقاً ``SmartBusinessLocal-<v>-windows-setup.exe`` را
    می‌جوید؛ اگر نامِ خروجیِ Inno عوض شود، بیلدِ ویندوز در CI بی‌صدا نصب‌کننده را گم می‌کند."""
    base = re.search(r'^OutputBaseFilename=(.+)$', _text(), re.M).group(1).strip()
    expected = f"{pkg.APP_NAME}-{{#AppVersion}}{pkg.SETUP_SUFFIX[:-4]}"
    assert base == expected, f"OutputBaseFilename باید {expected} باشد، هست: {base}"
