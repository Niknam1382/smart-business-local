"""ابزارهای مشترک تست‌ها."""

import time


def wait_until(predicate, timeout: float = 8.0, interval: float = 0.02) -> bool:
    """تا وقتی predicate درست بشه (یا timeout) صبر می‌کنه؛ برای تست‌های چندتردی."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())
