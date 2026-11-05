"""ابزارهای مشترک تست‌ها."""

import time


def wait_until(predicate, timeout: float = 20.0, interval: float = 0.02) -> bool:
    """تا وقتی predicate درست بشه (یا timeout) صبر می‌کنه؛ برای تست‌های چندتردی.

    سقفِ ۲۰ ثانیه (نه ۸) عمداً وسیعه: روی رانرهایِ اشتراکیِ GitHub Actions که CPU را با سه jobِ
    دیگر تقسیم می‌کنند، یک صبرِ ۸ ثانیه‌ای گاهی «تستِ شکسته» می‌دهد در حالی که رفتارِ برنامه درست
    است (اولین شکستِ عمومیِ CI دقیقاً همین شکل بود: یک تست در ۸۳٪، بقیه سبز). چیزی که asserted
    می‌شود عوض نمی‌شه — فقط مهلتِ رسیدن به همان حالت.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())
