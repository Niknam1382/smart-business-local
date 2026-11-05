#!/usr/bin/env python3
"""ساختِ کلیدِ امضای به‌روزرسانی (Ed25519) — **فقط یک‌بار**، روی سیستمِ خودت.

    python scripts/make_signing_key.py

چه می‌کنه:
* یک جفت‌کلیدِ Ed25519 می‌سازه؛ کلیدِ **خصوصی** رو (PEM) *بیرون از مخزن* ذخیره می‌کنه (پیش‌فرض:
  ``~/SmartBusinessLocal-signing/update_signing_key.pem``) و کلیدِ **عمومی** رو چاپ می‌کنه.
* کلیدِ عمومی رو باید در ``app/branding.py`` جلوی ``UPDATE_PUBLIC_KEY_B64`` بذاری و همان نسخه رو منتشر کنی.

⚠️ هشدار — جدی بگیر:
* کلیدِ خصوصی هرگز در گیت/زیپ/چت/ایمیل نره. هر کسی اون رو داشته باشه می‌تونه به‌روزرسانیِ جعلی برای کاربرات بسازه.
* **حتماً چند نسخه‌ی پشتیبانِ آفلاین بگیر** (فلشِ جدا، مدیرِ رمز). اگه کلید گم بشه، امضای نسخه‌ی بعدی ممکن نیست و
  کاربران با نسخه‌ی فعلی دیگه نصبِ یک‌کلیکی نمی‌گیرن (باید دستی از GitHub دانلود کنن).
* اگه کلید لو رفت: کلیدِ تازه بساز، ``UPDATE_PUBLIC_KEY_B64`` رو عوض کن و نسخه‌ی تازه رو *دستی* منتشر کن.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KEY_PATH = Path.home() / "SmartBusinessLocal-signing" / "update_signing_key.pem"


def _inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(ROOT.resolve())
        return True
    except ValueError:
        return False


def public_key_b64(private_key) -> str:
    from cryptography.hazmat.primitives import serialization

    raw = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def generate_key(out_path: Path, passphrase: str = "", force: bool = False) -> str:
    """کلیدِ خصوصی رو در ``out_path`` می‌نویسه و کلیدِ عمومیِ base64 رو برمی‌گردونه.
    داخلِ مخزن ممنوع است؛ نوشتن روی کلیدِ موجود بدونِ ``force`` ممنوع."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    out_path = Path(out_path).expanduser()
    if _inside_repo(out_path):
        raise SystemExit("خطا: کلیدِ خصوصی نباید داخلِ پوشه‌ی پروژه ذخیره بشه؛ یه مسیرِ بیرون از مخزن بده (--out).")
    if out_path.exists() and not force:
        raise SystemExit(f"خطا: «{out_path}» از قبل هست. اگه کلیدِ قبلی رو دارید پشتیبان‌گیری کنید؛ بازنویسی فقط با --force (کلیدِ قبلی برای همیشه گم می‌شه).")
    key = Ed25519PrivateKey.generate()
    encryption = serialization.BestAvailableEncryption(passphrase.encode("utf-8")) if passphrase else serialization.NoEncryption()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, encryption)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(pem)
    try:
        os.chmod(out_path, 0o600)
    except OSError:
        pass  # ویندوز
    return public_key_b64(key)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ساخت کلید امضای به‌روزرسانی (Ed25519) — فقط یک‌بار")
    parser.add_argument("--out", type=Path, default=DEFAULT_KEY_PATH, help="مسیرِ کلیدِ خصوصی (بیرون از مخزن)")
    parser.add_argument("--passphrase", action="store_true", help="کلیدِ خصوصی با رمز رمزنگاری بشه (پیشنهاد می‌شه)")
    parser.add_argument("--force", action="store_true", help="بازنویسیِ کلیدِ موجود (خطرناک)")
    args = parser.parse_args(argv)
    passphrase = ""
    if args.passphrase:
        passphrase = getpass.getpass("رمزِ کلیدِ خصوصی: ")
        if passphrase != getpass.getpass("تکرارِ رمز: "):
            print("رمزها یکی نبودن.", file=sys.stderr)
            return 1
    public = generate_key(args.out, passphrase, args.force)
    print(f"\n✅ کلیدِ خصوصی ذخیره شد: {args.out}")
    print("\nکلیدِ عمومی (این رو در app/branding.py جلوی UPDATE_PUBLIC_KEY_B64 بذار):\n")
    print(f'    UPDATE_PUBLIC_KEY_B64 = "{public}"\n')
    print("⚠️  از فایلِ کلیدِ خصوصی همین حالا چند پشتیبانِ آفلاین بگیر (فلشِ جدا / مدیرِ رمز).")
    print("    گم‌شدنِ کلید = امضای نسخه‌ی بعدی ممکن نیست؛ لو رفتنِ کلید = هرکسی می‌تونه به‌روزرسانیِ جعلی بسازه.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
