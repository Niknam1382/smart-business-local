"""QRِ لینکِ دعوتِ مدیر (N11) — با ``segno`` (پایتونِ خالص، بدونِ وابستگیِ بومی)."""

from __future__ import annotations

import io


def png_bytes(text: str, scale: int = 6, border: int = 2) -> bytes:
    """تصویرِ PNGِ QR برای ``text`` (سطحِ تصحیحِ خطای M). برای ``ft.Image(src=bytes)``."""
    import segno

    buffer = io.BytesIO()
    segno.make(text, error="m").save(buffer, kind="png", scale=scale, border=border, dark="#000000", light="#ffffff")
    return buffer.getvalue()
