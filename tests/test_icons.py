"""N9: آیکنِ برنامه — اسکریپتِ ساخت، فایل‌های commit‌شده، و اتصال به UI/installer/CI."""

import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "assets" / "icons"


@pytest.fixture(scope="module")
def maker():
    spec = importlib.util.spec_from_file_location("make_icons", ROOT / "scripts" / "make_icons.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def built(maker, tmp_path_factory):
    out = tmp_path_factory.mktemp("icons")
    return out, maker.build(out)


def test_build_creates_every_expected_file(built):
    out, created = built
    names = {p.name for p in created}
    expected = {"app-icon.svg", "app.ico", "app.icns", "android-adaptive-foreground.png", "android-adaptive-background.png", "android-adaptive-monochrome.png"}
    expected |= {f"app-icon-{s}.png" for s in (1024, 512, 256, 128, 64, 48, 32, 16)}
    assert expected <= names
    for p in created:
        assert p.stat().st_size > 100


@pytest.mark.parametrize("size", [1024, 512, 256, 128, 64, 48, 32, 16])
def test_png_sizes_and_rounded_transparent_corners(built, size):
    out, _ = built
    image = Image.open(out / f"app-icon-{size}.png").convert("RGBA")
    assert image.size == (size, size)
    assert image.getpixel((0, 0))[3] == 0  # گوشه‌ی گرد = شفاف
    assert image.getpixel((size // 2, size // 8))[3] == 255  # بدنه کاملاً مات


def test_icon_is_a_blue_to_green_gradient_with_a_white_bag_and_amber_bubble(built):
    out, _ = built
    image = Image.open(out / "app-icon-512.png").convert("RGB")
    top_left, bottom_right = image.getpixel((70, 70)), image.getpixel((440, 440))
    assert top_left[2] > top_left[1] and bottom_right[1] > bottom_right[2]  # بالا آبی، پایین سبز
    colors = {image.getpixel((x, y)) for x in range(0, 512, 8) for y in range(0, 512, 8)}
    assert any(r > 240 and g > 240 and b > 240 for r, g, b in colors)  # کیفِ سفید
    assert any(r > 220 and 150 < g < 210 and b < 110 for r, g, b in colors)  # حبابِ کهربایی


def test_ico_has_all_windows_sizes_and_icns_opens(built, maker):
    out, _ = built
    ico = Image.open(out / "app.ico")
    assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= set(ico.info["sizes"])
    icns = Image.open(out / "app.icns")
    assert icns.format == "ICNS" and max(icns.size) >= 256


def test_android_adaptive_layers_follow_the_safe_zone_rule(built):
    out, _ = built
    fg = Image.open(out / "android-adaptive-foreground.png")
    bg = Image.open(out / "android-adaptive-background.png")
    mono = Image.open(out / "android-adaptive-monochrome.png")
    assert fg.size == bg.size == mono.size == (432, 432)
    assert bg.convert("RGBA").getextrema()[3] == (255, 255)  # پس‌زمینه کاملاً مات
    assert fg.getpixel((0, 0))[3] == 0 and fg.getpixel((431, 431))[3] == 0
    left, top, right, bottom = fg.getbbox()
    assert left >= 432 * 0.15 and right <= 432 * 0.85 and top >= 432 * 0.15 and bottom <= 432 * 0.85  # ناحیه‌ی امنِ ۶۶٪ + حاشیه
    raw = mono.convert("RGBA").tobytes()
    pixels = [raw[i : i + 4] for i in range(0, len(raw), 4) if raw[i + 3] > 0]
    assert pixels and all(tuple(p[:3]) == (255, 255, 255) for p in pixels)  # تک‌رنگ = فقط سفید


def test_svg_is_valid_xml_and_matches_the_png_geometry(built, maker):
    out, _ = built
    root = ET.fromstring((out / "app-icon.svg").read_text(encoding="utf-8"))
    assert root.tag.endswith("svg") and root.attrib["viewBox"] == "0 0 1024 1024"
    text = (out / "app-icon.svg").read_text(encoding="utf-8")
    for token in (f'rx="{maker.CORNER}"', "linearGradient", f"scale({maker.GLYPH_SCALE})"):
        assert token in text


def test_build_is_deterministic_for_geometry_and_svg(maker, tmp_path):
    a = maker.svg_text()
    assert a == maker.svg_text()
    assert maker.glyph_bounds()[0] < maker.glyph_center()[0] < maker.glyph_bounds()[2]


def test_committed_icons_exist_and_have_the_right_sizes():
    assert (ICONS / "app-icon.svg").is_file() and (ICONS / "app.ico").is_file() and (ICONS / "app.icns").is_file()
    for size in (1024, 512, 256, 128, 64, 48, 32, 16):
        assert Image.open(ICONS / f"app-icon-{size}.png").size == (size, size)
    for layer in ("foreground", "background", "monochrome"):
        assert Image.open(ICONS / f"android-adaptive-{layer}.png").size == (432, 432)


def test_icon_is_wired_into_ui_installer_and_release_workflow():
    from app.screens import common

    badge = common.logo_badge(44)
    assert badge.key == "app_logo" and badge.content.src == common.APP_ICON_ASSET
    assert (ROOT / "assets" / common.APP_ICON_ASSET).is_file()
    assert common.logo_badge(44, icon="x").key != "app_logo"  # مسیرِ قدیمیِ نشانِ آیکنی هنوز هست
    iss = (ROOT / "installer" / "SmartBusinessLocal.iss").read_text(encoding="utf-8")
    assert "SetupIconFile=..\\assets\\icons\\app.ico" in iss
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert '--icon "${{ matrix.icon }}"' in workflow and "app.ico" in workflow and "app.icns" in workflow
    assert "Pillow" in (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")


def test_app_does_not_depend_on_pillow_at_runtime():
    runtime = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "pillow" not in runtime
