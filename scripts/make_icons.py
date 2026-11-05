#!/usr/bin/env python3
"""ساختِ آیکنِ برنامه (N9) — یک منبعِ هندسی ⇒ SVG + PNG (۱۶…۱۰۲۴) + ICO + ICNS + لایه‌های آیکنِ تطبیقیِ اندروید.

    python scripts/make_icons.py            # خروجی: assets/icons/
    python scripts/make_icons.py --out /tmp/icons

طرح (۱.۰.۰): مربعِ گردِ گرادیانِ شبِ نیلی→اناری، کیسه‌ی خریدِ سفید با دسته‌ی حلقه‌ای، و یک جرقه‌ی
چهارپرِ اناری داخلِ کیسه — «کسب‌وکارِ هوشمند». (طرحِ پیشین سه ستونِ رو‌به‌رشد با جرقه‌ی کهربایی بود.)
فقط به Pillow نیاز داره (``pip install -r requirements-dev.txt``)؛ خودِ برنامه به Pillow وابسته نیست و خروجی‌ها در مخزن
commit شده‌اند، پس کاربر/CI نیازی به اجرای این اسکریپت ندارن.
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "assets" / "icons"

SIZE = 1024
SS = 2  # ابرنمونه‌برداری برای لبه‌های نرم
# پالتِ ۱.۰.۰: شبِ نیلی ← اناریِ گرم (طرحِ پیشین آبی←سبز بود)
BG_FROM = (30, 32, 72)  # #1E2048 — بالا-چپ
BG_TO = (176, 66, 74)  # #B0424A — پایین-راست
WHITE = (255, 255, 255)
AMBER = (198, 60, 66)  # #C63C42 — جرقه‌ی «هوشمند» داخلِ کیسه
NAVY = (27, 43, 85)  # #1B2B55
CORNER = 230  # شعاعِ گوشه‌ی مربعِ گرد

# هندسه (روی بومِ ۱۰۲۴) — همین اعداد هم برای SVG و هم برای Pillow استفاده می‌شن
# طرح: کیسه‌ی خرید (بدنه + دسته‌ی حلقه‌ای) با یک جرقه‌ی چهارپر داخلش = «کسب‌وکارِ هوشمند»
RINGS = (  # دستهٔ کیسه؛ *پیش از* بدنه کشیده می‌شه تا نیمهٔ پایینش پشتِ بدنه پنهان بشه
    dict(cx=512, cy=404, r=168, width=58),
)
RECTS = (  # بدنهٔ کیسه
    dict(x0=236, y0=396, x1=788, y1=836, r=72),
)
SPARKLES = (  # جرقه‌ی «هوشمند»: (مرکز x, مرکز y, شعاع)
    (512, 616, 136),
)
SPARKLE_POWER = 2.6  # ۲ = لوزی، ۳ = ستاره‌ی نازکِ astroid
GLYPH_SCALE = 1.15  # گلیف کمی بزرگ‌تر از بومِ خام تا در ۳۲/۱۶ پیکسل هم خوانا بمونه
ICON_SIZES = (1024, 512, 256, 128, 64, 48, 32, 16)
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def hex_color(rgb) -> str:
    return "#%02X%02X%02X" % rgb


def sparkle_points(cx: float, cy: float, radius: float, power: float = SPARKLE_POWER, steps: int = 96) -> list:
    """جرقه‌ی چهارپرِ مقعر (astroid تعمیم‌یافته) به‌صورتِ چندضلعی؛ همان نقاط برای SVG و Pillow."""
    import math

    pts = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        c, s = math.cos(t), math.sin(t)
        pts.append((cx + radius * math.copysign(abs(c) ** power, c), cy + radius * math.copysign(abs(s) ** power, s)))
    return pts


def glyph_bounds():
    """کادر پیرامونِ گلیف (حلقه‌ها + مستطیل‌ها + جرقه‌ها) در واحد بومِ ۱۰۲۴."""
    xs, ys = [], []
    for ring in RINGS:
        outer = ring["r"] + ring["width"] / 2
        xs += [ring["cx"] - outer, ring["cx"] + outer]
        ys += [ring["cy"] - outer, ring["cy"] + outer]
    for b in RECTS:
        xs += [b["x0"], b["x1"]]
        ys += [b["y0"], b["y1"]]
    for cx, cy, radius in SPARKLES:
        xs += [cx - radius, cx + radius]
        ys += [cy - radius, cy + radius]
    return min(xs), min(ys), max(xs), max(ys)
def glyph_center():
    left, top, right, bottom = glyph_bounds()
    return (left + right) / 2, (top + bottom) / 2


# ------------------------------------------------------------------- SVG ----

def svg_text() -> str:
    gx, gy = glyph_center()
    rings = "".join(
        f'<circle cx="{ring["cx"]}" cy="{ring["cy"]}" r="{ring["r"]}" fill="none" stroke="#FFFFFF" stroke-width="{ring["width"]}"/>' for ring in RINGS
    )
    rects = "".join(
        f'<rect x="{b["x0"]}" y="{b["y0"]}" width="{b["x1"] - b["x0"]}" height="{b["y1"] - b["y0"]}" rx="{b["r"]}" fill="#FFFFFF"/>' for b in RECTS
    )
    stars = "".join(
        f'<polygon points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in sparkle_points(cx, cy, r))}" fill="{hex_color(AMBER)}"/>' for cx, cy, r in SPARKLES
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}" width="{SIZE}" height="{SIZE}">
  <title>Smart Business Local</title>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{hex_color(BG_FROM)}"/>
      <stop offset="1" stop-color="{hex_color(BG_TO)}"/>
    </linearGradient>
  </defs>
  <rect width="{SIZE}" height="{SIZE}" rx="{CORNER}" fill="url(#bg)"/>
  <g transform="translate({SIZE // 2} {SIZE // 2}) scale({GLYPH_SCALE}) translate({-gx:g} {-gy:g})">
  {rings}
  {rects}
  {stars}
  </g>
</svg>
"""
# ---------------------------------------------------------------- Pillow ----

def _pillow():
    try:
        from PIL import Image, ImageChops, ImageDraw
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("Pillow نصب نیست: pip install -r requirements-dev.txt") from exc
    return Image, ImageChops, ImageDraw


def _gradient(size: int):
    Image, ImageChops, _ = _pillow()
    vertical = Image.linear_gradient("L").resize((size, size), Image.BILINEAR)  # بالا تیره ← پایین روشن
    horizontal = vertical.transpose(Image.Transpose.TRANSPOSE)  # قطری
    mix = ImageChops.add(vertical, horizontal, scale=2.0)
    return Image.composite(Image.new("RGB", (size, size), BG_TO), Image.new("RGB", (size, size), BG_FROM), mix)
def _glyph_layer(scale: int, *, monochrome: bool = False):
    """بوم شفافِ «کیسه + جرقه» با ابعادِ ``SIZE*scale``؛ ``monochrome``: همه سفید (آیکن تک‌رنگ اندروید ۱۳)."""
    Image, _, ImageDraw = _pillow()
    s = scale
    layer = Image.new("RGBA", (SIZE * s, SIZE * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    white, accent = (WHITE, WHITE) if monochrome else (WHITE, AMBER)
    for ring in RINGS:  # دسته اول کشیده می‌شود تا نیمهٔ پایینی‌اش پشتِ بدنه پنهان بماند
        r = ring["r"]
        d.ellipse([(ring["cx"] - r) * s, (ring["cy"] - r) * s, (ring["cx"] + r) * s, (ring["cy"] + r) * s],
                  outline=white, width=int(ring["width"] * s))
    for b in RECTS:
        d.rounded_rectangle([b["x0"] * s, b["y0"] * s, b["x1"] * s, b["y1"] * s], radius=b["r"] * s, fill=white)
    for cx, cy, radius in SPARKLES:
        d.polygon([(x * s, y * s) for x, y in sparkle_points(cx, cy, radius)], fill=accent)
    return layer
def _placed_glyph(scale: int):
    """گلیف با ``GLYPH_SCALE`` بزرگ شده و دقیقاً وسطِ بوم (هم‌ارزِ تبدیلِ گروهِ SVG)."""
    Image, _, _ = _pillow()
    layer = _glyph_layer(scale)
    full = SIZE * scale
    new_size = int(round(full * GLYPH_SCALE))
    resized = layer.resize((new_size, new_size), Image.LANCZOS)
    cx, cy = glyph_center()
    dest = (int(round(full / 2 - cx * scale * GLYPH_SCALE)), int(round(full / 2 - cy * scale * GLYPH_SCALE)))
    placed = Image.new("RGBA", (full, full), (0, 0, 0, 0))
    placed.paste(resized, dest)  # بدونِ ماسک: ناحیه‌ی شفاف همان‌طور شفاف می‌ماند (alpha درست)
    return placed


def render_master(size: int = SIZE):
    """آیکنِ کامل (مربعِ گرد + گلیف) با اندازه‌ی ``size``."""
    Image, _, ImageDraw = _pillow()
    big = SIZE * SS
    base = _gradient(big).convert("RGBA")
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, big - 1, big - 1], radius=CORNER * SS, fill=255)
    base.putalpha(mask)
    base.alpha_composite(_placed_glyph(SS))
    return base.resize((size, size), Image.LANCZOS)


def render_android_layers(canvas: int = 432):
    """آیکنِ تطبیقیِ اندروید: پس‌زمینه‌ی تخت (گرادیان) + پیش‌زمینه‌ی شفاف (گلیف در ناحیه‌ی امنِ ۶۶٪) + تک‌رنگ."""
    Image, _, _ = _pillow()
    background = _gradient(canvas).convert("RGBA")
    safe = int(canvas * 0.66)
    glyph = _glyph_layer(SS).resize((SIZE, SIZE), Image.LANCZOS)
    bbox = glyph.getbbox() or (0, 0, SIZE, SIZE)
    cropped = glyph.crop(bbox)
    ratio = min(safe / cropped.width, safe / cropped.height)
    cropped = cropped.resize((max(1, int(cropped.width * ratio)), max(1, int(cropped.height * ratio))), Image.LANCZOS)
    foreground = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    foreground.alpha_composite(cropped, ((canvas - cropped.width) // 2, (canvas - cropped.height) // 2))
    mono_glyph = _glyph_layer(SS, monochrome=True).resize((SIZE, SIZE), Image.LANCZOS).crop(bbox)
    mono_glyph = mono_glyph.resize(cropped.size, Image.LANCZOS)
    monochrome = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    monochrome.alpha_composite(mono_glyph, ((canvas - mono_glyph.width) // 2, (canvas - mono_glyph.height) // 2))
    return background, foreground, monochrome


def build(out_dir: Path) -> list:
    """همه‌ی خروجی‌ها را در ``out_dir`` می‌نویسد و مسیرها را برمی‌گرداند."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    created = []
    svg = out_dir / "app-icon.svg"
    svg.write_text(svg_text(), encoding="utf-8")
    created.append(svg)
    master = render_master(SIZE)
    for size in ICON_SIZES:
        path = out_dir / f"app-icon-{size}.png"
        (master if size == SIZE else master.resize((size, size), _pillow()[0].LANCZOS)).save(path, optimize=True)
        created.append(path)
    ico = out_dir / "app.ico"
    master.save(ico, format="ICO", sizes=ICO_SIZES)
    created.append(ico)
    icns = out_dir / "app.icns"
    master.save(icns, format="ICNS")
    created.append(icns)
    background, foreground, monochrome = render_android_layers()
    for name, image in (("background", background), ("foreground", foreground), ("monochrome", monochrome)):
        path = out_dir / f"android-adaptive-{name}.png"
        image.save(path, optimize=True)
        created.append(path)
    return created


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ساخت آیکن برنامه (N9)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    for path in build(args.out):
        print(f"ساخته شد: {path.relative_to(ROOT) if ROOT in path.parents else path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
