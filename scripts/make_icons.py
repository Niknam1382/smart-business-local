#!/usr/bin/env python3
"""ساختِ آیکنِ برنامه (N9) — یک منبعِ هندسی ⇒ SVG + PNG (۱۶…۱۰۲۴) + ICO + ICNS + لایه‌های آیکنِ تطبیقیِ اندروید.

    python scripts/make_icons.py            # خروجی: assets/icons/
    python scripts/make_icons.py --out /tmp/icons

طرح: مربعِ گردِ گرادیانِ آبی→سبز، کیفِ خریدِ سفید و حبابِ گفتگوی کهربایی با سه نقطه (دستیارِ هوشمندِ فروشگاه).
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
BLUE = (36, 59, 122)  # #243B7A
GREEN = (43, 167, 127)  # #2BA77F
WHITE = (255, 255, 255)
AMBER = (245, 184, 61)  # #F5B83D
NAVY = (27, 43, 85)  # #1B2B55
CORNER = 230  # شعاعِ گوشه‌ی مربعِ گرد

# هندسه (روی بومِ ۱۰۲۴) — همین اعداد هم برای SVG و هم برای Pillow استفاده می‌شن
BAG = dict(x0=250, y0=390, x1=650, y1=790, r=60)
HANDLE = dict(cx=450, cy=400, radius=118, width=40)
BUBBLE = dict(x0=520, y0=530, x1=810, y1=745, r=72)
TAIL = [(590, 735), (575, 830), (680, 740)]
OUTLINE = 22  # حاشیه‌ی تیره دورِ حباب (برش از کیف)
DOTS = dict(cy=638, xs=(594, 665, 736), r=25)
GLYPH_SCALE = 1.22  # گلیف کمی بزرگ‌تر از بوم‌ِ خام تا در ۳۲/۱۶ پیکسل هم خوانا بمونه
ICON_SIZES = (1024, 512, 256, 128, 64, 48, 32, 16)
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def hex_color(rgb) -> str:
    return "#%02X%02X%02X" % rgb


def glyph_bounds():
    """کادرِ پیرامونِ گلیف (کیف + دسته + حباب + دُم) در واحدِ بومِ ۱۰۲۴."""
    h, b, u, o = HANDLE, BAG, BUBBLE, OUTLINE
    left = min(b["x0"], u["x0"] - o)
    right = max(b["x1"], u["x1"] + o)
    top = h["cy"] - h["radius"] - h["width"] // 2
    bottom = max(b["y1"], u["y1"] + o, max(y for _, y in TAIL) + int(o * 1.6))
    return left, top, right, bottom


def glyph_center():
    left, top, right, bottom = glyph_bounds()
    return (left + right) / 2, (top + bottom) / 2


# ------------------------------------------------------------------- SVG ----

def svg_text() -> str:
    b, h, u, t, d = BAG, HANDLE, BUBBLE, TAIL, DOTS
    gx, gy = glyph_center()
    tail_pts = " ".join(f"{x},{y}" for x, y in t)
    o = OUTLINE
    dots = "".join(f'<circle cx="{x}" cy="{d["cy"]}" r="{d["r"]}" fill="{hex_color(NAVY)}"/>' for x in d["xs"])
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}" width="{SIZE}" height="{SIZE}">
  <title>Smart Business Local</title>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{hex_color(BLUE)}"/>
      <stop offset="1" stop-color="{hex_color(GREEN)}"/>
    </linearGradient>
  </defs>
  <rect width="{SIZE}" height="{SIZE}" rx="{CORNER}" fill="url(#bg)"/>
  <g transform="translate({SIZE // 2} {SIZE // 2}) scale({GLYPH_SCALE}) translate({-gx:g} {-gy:g})">
  <path d="M{h['cx'] - h['radius']} {h['cy']} A{h['radius']} {h['radius']} 0 0 1 {h['cx'] + h['radius']} {h['cy']}" fill="none" stroke="#FFFFFF" stroke-width="{h['width']}"/>
  <rect x="{b['x0']}" y="{b['y0']}" width="{b['x1'] - b['x0']}" height="{b['y1'] - b['y0']}" rx="{b['r']}" fill="#FFFFFF"/>
  <g fill="{hex_color(NAVY)}" stroke="{hex_color(NAVY)}" stroke-width="{2 * o}" stroke-linejoin="round">
    <rect x="{u['x0']}" y="{u['y0']}" width="{u['x1'] - u['x0']}" height="{u['y1'] - u['y0']}" rx="{u['r']}"/>
    <polygon points="{tail_pts}"/>
  </g>
  <g fill="{hex_color(AMBER)}">
    <rect x="{u['x0']}" y="{u['y0']}" width="{u['x1'] - u['x0']}" height="{u['y1'] - u['y0']}" rx="{u['r']}"/>
    <polygon points="{tail_pts}"/>
  </g>
  {dots}
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
    vertical = Image.linear_gradient("L").resize((size, size), Image.BILINEAR)  # بالا سیاه → پایین سفید
    horizontal = vertical.transpose(Image.Transpose.TRANSPOSE)  # چپ سیاه → راست سفید
    mix = ImageChops.add(vertical, horizontal, scale=2.0)  # قطری
    return Image.composite(Image.new("RGB", (size, size), GREEN), Image.new("RGB", (size, size), BLUE), mix)


def _glyph_layer(scale: int, *, monochrome: bool = False):
    """بومِ شفافِ «کیف + حباب» با ابعادِ ``SIZE*scale``؛ ``monochrome``: همه سفید (آیکنِ تک‌رنگِ اندروید ۱۳)."""
    Image, _, ImageDraw = _pillow()
    s = scale
    layer = Image.new("RGBA", (SIZE * s, SIZE * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    white, amber, navy = (WHITE, WHITE, WHITE) if monochrome else (WHITE, AMBER, NAVY)

    h = HANDLE
    box = [(h["cx"] - h["radius"]) * s, (h["cy"] - h["radius"]) * s, (h["cx"] + h["radius"]) * s, (h["cy"] + h["radius"]) * s]
    d.arc(box, 180, 360, fill=white, width=h["width"] * s)
    b = BAG
    d.rounded_rectangle([b["x0"] * s, b["y0"] * s, b["x1"] * s, b["y1"] * s], radius=b["r"] * s, fill=white)

    u, o = BUBBLE, OUTLINE
    if not monochrome:  # حاشیه‌ی تیره = «برش» از کیف
        d.rounded_rectangle([(u["x0"] - o) * s, (u["y0"] - o) * s, (u["x1"] + o) * s, (u["y1"] + o) * s], radius=(u["r"] + o) * s, fill=navy)
        d.polygon(_grow_triangle(TAIL, o, s), fill=navy)
    else:  # تک‌رنگ: حباب با فاصله‌ی شفاف از کیف
        d.rounded_rectangle([(u["x0"] - o) * s, (u["y0"] - o) * s, (u["x1"] + o) * s, (u["y1"] + o) * s], radius=(u["r"] + o) * s, fill=(0, 0, 0, 0))
    d.rounded_rectangle([u["x0"] * s, u["y0"] * s, u["x1"] * s, u["y1"] * s], radius=u["r"] * s, fill=amber)
    d.polygon([(x * s, y * s) for x, y in TAIL], fill=amber)
    dots = DOTS
    dot_color = (0, 0, 0, 0) if monochrome else navy
    for x in dots["xs"]:
        d.ellipse([(x - dots["r"]) * s, (dots["cy"] - dots["r"]) * s, (x + dots["r"]) * s, (dots["cy"] + dots["r"]) * s], fill=dot_color)
    return layer


def _grow_triangle(points, amount: int, s: int):
    """مثلثِ دُم را کمی بزرگ می‌کند (از مرکزش) تا حاشیه‌ی تیره دورِ دُم هم بیاید."""
    cx = sum(x for x, _ in points) / 3
    cy = sum(y for _, y in points) / 3
    out = []
    for x, y in points:
        dx, dy = x - cx, y - cy
        norm = (dx * dx + dy * dy) ** 0.5 or 1.0
        out.append(((x + dx / norm * amount * 1.6) * s, (y + dy / norm * amount * 1.6) * s))
    return out


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
