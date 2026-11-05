"""
به‌روزرسانی دوره‌ای صفحه‌های «زنده» (وضعیت ربات‌ها، لیست گفتگوها).

قواعد (بر پایه‌ی بررسی سورس Flet 1.0.1، نه حدس):
- کنترل‌های Flet و ``page.update()`` فقط باید داخل کانتکست صفحه صدا زده بشن.
  ``page.run_thread`` همین کانتکست رو (contextvar) برای handler ست می‌کنه؛ یه
  ترد خام این کار رو نمی‌کنه. پس ترد ما هیچ‌وقت خودش به UI دست نمی‌زنه و فقط
  هر ``interval`` ثانیه یه tick کوتاه رو با ``page.run_thread`` می‌فرسته.
- حلقه‌ی ما روی ترد ``daemon`` خودمونه، نه داخل executor خودِ Flet: ترد غیر-daemon
  جلوی خروج پروسه رو می‌گیره و اگه کاربر پنجره رو ببنده و حلقه‌ای بی‌پایان
  داخل executor مونده باشه، برنامه بعد از بسته‌شدن پنجره هم زنده می‌مونه.
- اگه tick قبلی هنوز تموم نشده، tick بعدی رد می‌شه (انباشته نمی‌شن).
- هر خطا (مثلاً بسته‌شدن session) حلقه رو بی‌سروصدا متوقف می‌کنه.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

logger = logging.getLogger(__name__)


class LiveRefresher:
    def __init__(self, page, tick: Callable[[], None], interval: float = 2.0):
        self._page = page
        self._tick = tick
        self._interval = interval
        self._stop = threading.Event()
        self._busy = threading.Lock()
        self._thread = None

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="ui-live-refresh", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._page.run_thread(self._run_tick)
            except Exception:  # noqa: BLE001 — session/صفحه دیگه وجود نداره
                break

    def _run_tick(self) -> None:
        if self._stop.is_set() or not self._busy.acquire(blocking=False):
            return
        try:
            self._tick()
        except Exception:  # noqa: BLE001
            logger.exception("به‌روزرسانی زنده‌ی صفحه ناموفق بود")
        finally:
            self._busy.release()
