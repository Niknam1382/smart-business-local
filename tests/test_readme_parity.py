"""N20 — هم‌ارزیِ ۱۰۰٪ِ README دوزبانه (بخشِ انگلیسی اول، بعد فارسیِ کامل).

قرارداد: هر H3 ی انگلیسی یک جفتِ هم‌جایگاهِ فارسی دارد و هر ویژگیِ انگلیسی معادلِ فارسی. این تست‌ها با افزودنِ
ویژگیِ تازه به یک زبان و فراموشیِ زبانِ دیگر می‌شکنند.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")

_I_EN = README.index("\n## English")
_I_FA = README.index("\n## فارسی")
_I_LIC = README.index("\n## License")
EN = README[_I_EN:_I_FA]
FA = README[_I_FA:_I_LIC]

_FARSI = re.compile(r"[\u0600-\u06FF]")
_LATIN = re.compile(r"[A-Za-z]")
_ROW_SEP = re.compile(r"^\|[\s\-|:]*$")


def _h3(section: str) -> list[tuple[str, str]]:
    out = []
    for part in re.split(r"(?m)^### ", section)[1:]:
        title, _, body = part.partition("\n")
        out.append((title.strip(), body))
    return out


EN_H3, FA_H3 = _h3(EN), _h3(FA)


def _rows(body: str) -> list[str]:
    return [ln for ln in body.split("\n") if ln.startswith("|") and not _ROW_SEP.match(ln)]


def _bullets(body: str) -> list[str]:
    return [ln for ln in body.split("\n") if re.match(r"^\s*(?:[-*]|\d+\.)\s", ln)]


def _links(text: str) -> set[str]:
    out = set()
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        out.add(target.split("#")[0])
    return out


def _spans(text: str) -> set[str]:
    # جانِ‌نگهدارِ نسخه در نامِ فایل‌ها بومی‌سازی می‌شود: <version> ↔ <نسخه>
    return {s.replace("<نسخه>", "<version>") for s in re.findall(r"`([^`\n]+)`", text)}


def _prose(body: str) -> str:
    body = re.sub(r"```.*?```", "", body, flags=re.S)
    body = re.sub(r"`[^`\n]*`", "", body)
    body = re.sub(r"\]\([^)]*\)", "]", body)
    return re.sub(r"https?://\S+", "", body)


def _lead_emoji(row: str) -> str:
    first = row.strip("|").split("|")[0].strip()
    return first.split(" ")[0]


def test_sections_exist_in_order():
    assert 0 < _I_EN < _I_FA < _I_LIC
    head = README[:_I_EN]
    assert "# Smart Business" in head and "# کسب‌وکار هوشمند" in head


def test_same_number_of_h3_sections():
    assert len(EN_H3) == len(FA_H3) and len(EN_H3) >= 11


@pytest.mark.parametrize("idx", range(len(EN_H3)))
def test_each_h3_pair_has_the_same_structure(idx):
    (te, be), (tf, bf) = EN_H3[idx], FA_H3[idx]
    assert len(_rows(be)) == len(_rows(bf)), (te, tf, "table rows")
    assert len(_bullets(be)) == len(_bullets(bf)), (te, tf, "bullets")
    assert be.count("```") == bf.count("```"), (te, tf, "code fences")
    assert _links(be) == _links(bf), (te, tf, "links")


def test_highlights_and_features_tables_match_row_for_row():
    en = next(b for t, b in EN_H3 if t == "Highlights")
    fa = next(b for t, b in FA_H3 if t == "امکانات")
    re_, rf = _rows(en), _rows(fa)
    assert len(re_) == len(rf) >= 14
    # هر ردیف: یک نمادِ آغازین + دو سلولِ پر؛ ترتیبِ نمادها یکی
    assert [_lead_emoji(r) for r in re_] == [_lead_emoji(r) for r in rf]
    for r in re_ + rf:
        cells = [c.strip() for c in r.strip().strip("|").split("|")]
        assert len(cells) == 2 and all(cells), r


def test_every_relative_link_exists_and_both_languages_link_the_same_files():
    assert _links(EN) == _links(FA)
    assert any(link.startswith("docs/") for link in _links(EN))
    for link in _links(README):
        assert (ROOT / link).exists(), link


def test_inline_code_matches_between_languages():
    assert _spans(EN) == _spans(FA)


@pytest.mark.parametrize("idx", range(len(FA_H3)))
def test_persian_section_is_actually_persian(idx):
    title, body = FA_H3[idx]
    prose = _prose(body)
    farsi, latin = len(_FARSI.findall(prose)), len(_LATIN.findall(prose))
    assert farsi >= 3 * latin and farsi > 0, (title, farsi, latin)


@pytest.mark.parametrize("idx", range(len(EN_H3)))
def test_english_section_is_actually_english(idx):
    title, body = EN_H3[idx]
    prose = _prose(body)
    assert len(_FARSI.findall(prose)) <= 2, title  # نقل‌قولِ تک‌واژه‌ای مجاز؛ ترجمه‌ی نیمه‌کاره نه
