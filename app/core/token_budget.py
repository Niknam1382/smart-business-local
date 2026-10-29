"""شمارشِ توکن و پنجره‌ی تاریخچه (N18) — بدونِ وابستگیِ بیرونی؛ تخمین‌ها همیشه «تخمینی» برچسب می‌خورن.

قاعده‌ی تخمین: متنِ لاتین ≈ ۴ نویسه/توکن، فارسی/عربی/سایر ≈ ۲٫۵ نویسه/توکن (توکنایزرها روی فارسی ریزتر می‌شکنند).
پنجره‌ی تاریخچه: پرامپتِ سیستم، پیامِ تازه و آخرین پیام‌ها **همیشه** می‌مانند؛ قدیمی‌ترها اول حذف می‌شوند.
"""

from __future__ import annotations

import math

DEFAULT_CONTEXT_TOKENS = 16_000
MIN_REPLY_TOKENS = 256
PER_MESSAGE_OVERHEAD = 6


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    latin = sum(1 for ch in text if ord(ch) < 0x250)
    other = len(text) - latin
    return max(1, math.ceil(latin / 4 + other / 2.5))


def messages_tokens(messages: list) -> int:
    """جمعِ تخمینیِ لیستِ پیام‌های OpenAI-ایی (dict با content) یا ChatMessage."""
    total = 0
    for m in messages:
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
        total += estimate_tokens(content or "") + PER_MESSAGE_OVERHEAD
    return total


def fit_history(system_prompt: str, history: list, user_message: str, context_tokens: int, reply_tokens: int = 700, extra_tokens: int = 0) -> list:
    """قدیمی‌ترین پیام‌ها را کنار می‌گذارد تا سیستم + تاریخچه + پیام + سقفِ پاسخ در ``context_tokens`` جا شود. ترتیب حفظ می‌شود."""
    budget = int(context_tokens or DEFAULT_CONTEXT_TOKENS) - reply_tokens - extra_tokens
    budget -= estimate_tokens(system_prompt) + estimate_tokens(user_message) + 2 * PER_MESSAGE_OVERHEAD
    kept: list = []
    used = 0
    for msg in reversed(history):
        cost = estimate_tokens(msg.content) + PER_MESSAGE_OVERHEAD
        if used + cost > budget:
            break
        kept.append(msg)
        used += cost
    kept.reverse()
    return kept


def pick_max_tokens(user_message: str, tools: bool = False) -> int:
    """سقفِ خروجی به‌تناسبِ پرسش؛ پرسشِ کوتاه ⇒ پاسخِ کوتاه‌تر. ``finish_reason=length`` یک‌بار با دو برابر امتحان می‌شود (موتور)."""
    n = len((user_message or "").strip())
    base = 350 if n <= 60 else 600 if n <= 240 else 900
    return base + (150 if tools else 0)
