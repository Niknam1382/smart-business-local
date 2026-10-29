#!/usr/bin/env python3
"""امضای یک Release (≈ ۳۰ ثانیه): ``SHA256SUMS.txt`` رو از Release می‌گیره، با کلیدِ آفلاینِ تو امضا می‌کنه و
فایلِ ``SHA256SUMS.txt.sig`` رو برای آپلود آماده می‌کنه.

    python scripts/sign_release.py v1.1.0
    python scripts/sign_release.py v1.1.0 --key D:\\keys\\update_signing_key.pem --passphrase

بعدش: GitHub → Releases → همان نسخه → Edit → فایلِ ``SHA256SUMS.txt.sig`` رو پیوست کن → Update release.
اگه فراموش کنی امضا کنی چیزی خراب نمی‌شه؛ فقط «نصبِ یک‌کلیکی» برای اون نسخه غیرفعال می‌مونه و کاربر دستی دانلود می‌کنه.
قبل از امضا چک می‌کنه کلیدِ تو با ``UPDATE_PUBLIC_KEY_B64`` در ``app/branding.py`` یکی باشه (وگرنه برنامه امضا رو رد می‌کنه).
"""

from __future__ import annotations

import argparse
import base64
import getpass
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import branding  # noqa: E402
from app.core.update_verify import parse_sha256sums, verify_signature  # noqa: E402

SUMS_NAME = "SHA256SUMS.txt"
SIG_NAME = "SHA256SUMS.txt.sig"
DEFAULT_KEY_PATH = Path.home() / "SmartBusinessLocal-signing" / "update_signing_key.pem"


class SignError(Exception):
    pass


def load_private_key(path: Path, passphrase: str = ""):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    try:
        key = serialization.load_pem_private_key(Path(path).read_bytes(), password=passphrase.encode("utf-8") if passphrase else None)
    except FileNotFoundError as exc:
        raise SignError(f"کلیدِ خصوصی پیدا نشد: {path}") from exc
    except (ValueError, TypeError) as exc:
        raise SignError("کلید خوانده نشد (رمز اشتباه است یا فایل خراب).") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise SignError("این کلید Ed25519 نیست.")
    return key


def public_b64(key) -> str:
    from cryptography.hazmat.primitives import serialization

    return base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode("ascii")


def sign_sums(key, sums_bytes: bytes) -> str:
    """امضای base64 روی بایت‌های دقیقِ ``SHA256SUMS.txt``؛ قبل از برگشت با همان کلید خودآزمایی می‌شه."""
    sig_b64 = base64.b64encode(key.sign(sums_bytes)).decode("ascii")
    if not verify_signature(sums_bytes, sig_b64, public_b64(key)):  # pragma: no cover — نباید رخ بده
        raise SignError("خودآزماییِ امضا ناموفق بود.")
    return sig_b64


def download_sums(repo: str, tag: str, timeout: float = 30.0) -> bytes:
    url = f"https://github.com/{repo}/releases/download/{tag}/{SUMS_NAME}"
    request = urllib.request.Request(url, headers={"User-Agent": "SmartBusinessLocal-sign-release"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — https و github.com
            return response.read(5_000_000)
    except (urllib.error.URLError, OSError) as exc:
        raise SignError(f"دانلودِ {SUMS_NAME} ناموفق بود ({url}): {exc}. مطمئن شو Release منتشر شده؛ یا با --sums-file فایل رو دستی بده.") from exc


def check_key_matches_branding(key) -> Optional[str]:
    """None = مشکلی نیست؛ وگرنه پیامِ هشدار/خطا."""
    configured = branding.UPDATE_PUBLIC_KEY_B64
    if not configured:
        return "هشدار: UPDATE_PUBLIC_KEY_B64 در app/branding.py هنوز خالیه؛ برنامه‌های منتشرشده امضا رو نمی‌تونن بررسی کنن."
    if configured != public_b64(key):
        raise SignError("کلیدِ تو با UPDATE_PUBLIC_KEY_B64 در app/branding.py یکی نیست؛ با این امضا برنامه به‌روزرسانی رو رد می‌کنه. کلیدِ درست رو بده.")
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="امضای SHA256SUMS.txt یک Release")
    parser.add_argument("tag", help="مثلاً v1.1.0")
    parser.add_argument("--key", type=Path, default=DEFAULT_KEY_PATH, help="کلیدِ خصوصیِ آفلاین (PEM)")
    parser.add_argument("--passphrase", action="store_true", help="کلید با رمز رمزنگاری شده؛ رمز پرسیده می‌شه")
    parser.add_argument("--repo", default=branding.GITHUB_REPO)
    parser.add_argument("--out-dir", type=Path, default=Path.cwd())
    parser.add_argument("--sums-file", type=Path, help="به‌جای دانلود از GitHub، این فایلِ SHA256SUMS.txt رو امضا کن")
    args = parser.parse_args(argv)
    try:
        key = load_private_key(args.key, getpass.getpass("رمزِ کلید: ") if args.passphrase else "")
        warning = check_key_matches_branding(key)
        sums = args.sums_file.read_bytes() if args.sums_file else download_sums(args.repo, args.tag)
        if not parse_sha256sums(sums.decode("utf-8", errors="replace")):
            raise SignError("SHA256SUMS.txt خالی یا نامعتبره.")
        sig = sign_sums(key, sums)
    except SignError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    out = args.out_dir / SIG_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(sig + "\n", encoding="ascii")
    if warning:
        print(warning)
    print(f"✅ امضا ساخته شد: {out}")
    print("بعدش: GitHub → Releases → همین نسخه → Edit → این فایل رو پیوست کن → Update release.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
