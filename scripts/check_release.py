#!/usr/bin/env python3
"""بررسیِ یک Release منتشرشده: همه‌ی فایل‌هایِ لازم هست؟ (۱٫۲٫۲)

    python scripts/check_release.py v1.2.2

نتیجه را به زبانِ ساده می‌گوید: کدام فایل هست، کدام کم است و برایِ هر کمبود چه باید کرد. بدونِ توکن کار می‌کند
(Release عمومی است). کدِ خروج: ۰ = همه چیز هست، ۱ = چیزی کم است، ۲ = دسترسی به GitHub ممکن نشد.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import branding  # noqa: E402

APP_PREFIX = "SmartBusinessLocal"
SUMS_NAME = "SHA256SUMS.txt"
SIG_NAME = "SHA256SUMS.txt.sig"

# هر فایل → «اگر نبود چه کنم؟»
_HINT = {
    "setup": "بیلدِ ویندوز تمام نشده یا شکست خورده؛ Actions ← Release builds را ببین و در صورتِ نیاز تگ را دوباره بزن.",
    "exe": "بیلدِ ویندوز تمام نشده یا شکست خورده؛ Actions ← Release builds را ببین.",
    "linux": "بیلدِ لینوکس تمام نشده یا شکست خورده؛ Actions ← Release builds را ببین.",
    "sums": "فایلِ SHA256SUMS.txt ساخته نشده؛ مرحله‌یِ «Checksums» در Release builds را ببین.",
    "sig": "امضا نشده: روی کامپیوترِ خودت `python scripts/sign_release.py <تگ>` را بزن و فایلِ SHA256SUMS.txt.sig را به Release پیوست کن. "
           "بدونِ آن «نصبِ یک‌کلیکی» برایِ این نسخه کار نمی‌کند و برنامه کاربر را به صفحه‌یِ GitHub می‌برد.",
}


def expected_assets(version: str) -> list:
    """``[(نامِ فایل، کلیدِ راهنما), ...]`` برایِ نسخه‌ی بدونِ «v»."""
    v = version.lstrip("vV")
    return [
        (f"{APP_PREFIX}-{v}-windows-setup.exe", "setup"),
        (f"{APP_PREFIX}-{v}-windows.exe", "exe"),
        (f"{APP_PREFIX}-{v}-linux.tar.gz", "linux"),
        (SUMS_NAME, "sums"),
        (SIG_NAME, "sig"),
    ]


def evaluate(version: str, asset_names) -> tuple:
    """``(present, missing)`` — هرکدام فهرستِ ``(نام، راهنما)``."""
    have = {str(n) for n in asset_names}
    present, missing = [], []
    for name, key in expected_assets(version):
        (present if name in have else missing).append((name, _HINT[key]))
    return present, missing


def fetch_asset_names(repo: str, tag: str, opener=urllib.request.urlopen) -> list:
    url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "smart-business-release-check"})
    with opener(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
    return [str(a.get("name", "")) for a in data.get("assets", []) if isinstance(a, dict)]


def render(tag: str, present: list, missing: list) -> str:
    lines = [f"بررسیِ Release {tag}", ""]
    lines += [f"  ✅ {name}" for name, _hint in present]
    lines += [f"  ❌ {name}\n     ← {hint}" for name, hint in missing]
    lines.append("")
    lines.append("همه‌ی فایل‌ها هست؛ Release کامل است." if not missing else f"{len(missing)} فایل کم است.")
    return "\n".join(lines)


def main(argv=None, opener=urllib.request.urlopen) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    parser = argparse.ArgumentParser(description="بررسیِ کامل‌بودنِ یک Release")
    parser.add_argument("tag", help="مثلاً v1.2.2")
    parser.add_argument("--repo", default=branding.GITHUB_REPO)
    args = parser.parse_args(argv)
    try:
        names = fetch_asset_names(args.repo, args.tag, opener=opener)
    except urllib.error.HTTPError as exc:
        print("این تگ Release ندارد (یا هنوز ساخته نشده)." if exc.code == 404 else f"GitHub خطا داد ({exc.code}).")
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"به GitHub وصل نشدم: {type(exc).__name__}")
        return 2
    present, missing = evaluate(args.tag, names)
    print(render(args.tag, present, missing))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
