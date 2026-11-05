"""اعتبارِ فایلِ به‌روزرسانی: ``SHA256SUMS.txt`` + امضای Ed25519 (N14).

چون کدِ اجراشونده بدونِ هیچ سروری دانلود می‌شه، نصبِ یک‌کلیکی فقط وقتی مجازه که
۱) امضای ``SHA256SUMS.txt.sig`` با کلیدِ عمومیِ ثابتِ ``branding.UPDATE_PUBLIC_KEY_B64`` درست باشه و
۲) SHA256 فایلِ دانلودشده با خطِ همان فایل در ``SHA256SUMS.txt`` یکی باشه. هر چیزِ دیگه = رد.

قالبِ ``.sig``: متنِ base64 از امضای ۶۴بایتیِ Ed25519 روی *بایت‌های دقیقِ* ``SHA256SUMS.txt`` (فاصله‌ی اضافه مجازه).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
from pathlib import Path
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app import branding

SIGNATURE_BYTES = 64
PUBLIC_KEY_BYTES = 32


class VerifyError(Exception):
    """اعتبارسنجی ناموفق (پیام برای لاگ/دیباگ؛ به کاربر فقط «نامعتبر» نشون بده)."""


def _b64decode(text: str, what: str) -> bytes:
    try:
        return base64.b64decode("".join(text.split()), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise VerifyError(f"{what} base64 معتبر نیست") from exc


def load_public_key(public_key_b64: str) -> Ed25519PublicKey:
    raw = _b64decode(public_key_b64 or "", "کلیدِ عمومی")
    if len(raw) != PUBLIC_KEY_BYTES:
        raise VerifyError("طولِ کلیدِ عمومی درست نیست")
    return Ed25519PublicKey.from_public_bytes(raw)


def configured_public_key() -> str:
    """کلیدِ عمومیِ داخلِ برنامه؛ خالی = نصبِ خودکار هنوز فعال نشده (فقط دانلودِ دستی)."""
    return branding.UPDATE_PUBLIC_KEY_B64


def verify_signature(sums_bytes: bytes, sig_text: str, public_key_b64: Optional[str] = None) -> bool:
    """True فقط وقتی امضا روی بایت‌های دقیقِ ``sums_bytes`` درست باشه. هرگز exception نمی‌ده."""
    key_b64 = branding.UPDATE_PUBLIC_KEY_B64 if public_key_b64 is None else public_key_b64
    if not key_b64:
        return False  # بدونِ کلیدِ عمومی نصبِ خودکار ممکن نیست
    try:
        signature = _b64decode(sig_text, "امضا")
        if len(signature) != SIGNATURE_BYTES:
            return False
        load_public_key(key_b64).verify(signature, sums_bytes)
        return True
    except (VerifyError, InvalidSignature, ValueError):
        return False


def parse_sha256sums(text: str) -> dict:
    """``{نامِ فایل: hexِ کوچک}`` از خروجیِ ``sha256sum`` (``<hex>  <name>`` یا ``<hex> *<name>``). خطِ خراب نادیده."""
    out: dict = {}
    for line in (text or "").splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        digest, name = parts[0].lower(), parts[1].strip()
        if name.startswith("*"):
            name = name[1:]
        if len(digest) == 64 and all(c in "0123456789abcdef" for c in digest) and name and "/" not in name and "\\" not in name:
            out[name] = digest
    return out


def sha256_file(path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def verify_asset(path, asset_name: str, sums_bytes: bytes, sig_text: str, public_key_b64: Optional[str] = None) -> None:
    """فایلِ دانلودشده را کاملاً تأیید می‌کند؛ هر مشکلی ⇒ ``VerifyError`` (فایل نباید نصب بشه)."""
    if not verify_signature(sums_bytes, sig_text, public_key_b64):
        raise VerifyError("امضای SHA256SUMS.txt معتبر نیست")
    expected = parse_sha256sums(sums_bytes.decode("utf-8", errors="replace")).get(Path(asset_name).name)
    if not expected:
        raise VerifyError("فایل در SHA256SUMS.txt نیست")
    actual = sha256_file(path)
    if not hmac.compare_digest(actual, expected):
        raise VerifyError("SHA256 فایل با SHA256SUMS.txt نمی‌خونه")
