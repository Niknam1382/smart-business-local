"""بنچمارکِ توکن (N18) — بدونِ شبکه و بدونِ سرویسِ بیرونی؛ فقط تخمینِ داخلیِ ``token_budget``.

برای چند مکالمه‌ی نمونه، ورودیِ هر پاسخ را «بدونِ بهینه‌سازی» (کلِ تاریخچه) و «با پنجره‌ی هوشمند» مقایسه می‌کند و درصدِ کاهش را
چاپ می‌کند (برای README). اعداد **تخمینی**‌اند؛ مصرفِ واقعی در صفحه‌ی «مصرف و هزینه» از ``usage`` ِ خودِ API می‌آید.

اجرا:  python scripts/bench_tokens.py [--context 1500]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import token_budget as tb  # noqa: E402
from app.core.ai_engine import ChatMessage  # noqa: E402

SYSTEM = "تو دستیارِ یک فروشگاه آنلاین هستی. فقط با اطلاعاتِ کاتالوگ جواب بده و اگه نمی‌دونی بگو. " * 12
QUESTIONS = ["ساعت کاری شما چیست؟", "گوشی مدل X موجوده؟", "ارسال به شیراز چند روزه؟", "می‌شه تخفیف بگیرم؟", "روش پرداخت چیه؟"]
ANSWER = "ممنون از پیامتون! " + "توضیحِ کامل درباره‌ی محصول و شرایط. " * 8


def scenario(turns: int) -> list:
    hist = []
    for i in range(turns):
        hist += [ChatMessage("user", QUESTIONS[i % len(QUESTIONS)] + f" ({i})"), ChatMessage("assistant", ANSWER)]
    return hist


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--context", type=int, default=1500, help="پنجره‌ی context مدل (توکن)؛ مدل‌های محلیِ کوچک ≈ ۱۵۰۰–۴۰۰۰. اگه تاریخچه جا بشه صرفه‌جویی صفر است (صادقانه)")
    args = ap.parse_args()
    print(f"{'گفتگو (نوبت)':<16}{'بدونِ بهینه':>14}{'با پنجره':>12}{'کاهش':>8}")
    total_before = total_after = 0
    for turns in (2, 6, 12, 20):
        hist = scenario(turns)
        question = QUESTIONS[0]
        before = tb.estimate_tokens(SYSTEM) + tb.messages_tokens(hist) + tb.estimate_tokens(question)
        kept = tb.fit_history(SYSTEM, hist, question, args.context, reply_tokens=tb.pick_max_tokens(question))
        after = tb.estimate_tokens(SYSTEM) + tb.messages_tokens(kept) + tb.estimate_tokens(question)
        total_before, total_after = total_before + before, total_after + after
        print(f"{turns:<16}{before:>14,}{after:>12,}{(1 - after / before) * 100:>7.0f}%")
    print(f"\nمجموع: {total_before:,} ← {total_after:,} توکن ({(1 - total_after / total_before) * 100:.0f}٪ کمتر، تخمینی)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
