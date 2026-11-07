"""قلم‌های ۱۴/۱۷/۱۸ مستر‌پرامپت در UI: بخشِ «سرعت و هزینه» ذخیره می‌کند، ورودیِ خراب را رد
می‌کند و رباتِ روشن را با تنظیماتِ تازه دوباره بالا می‌آورد."""

import pytest
from test_bot_experience_screen import Env

from app.core import ai_engine, bot_pipeline
from app.core.settings import AppSettings


class Manager:
    def __init__(self, running=True, boom=False):
        self.running = running
        self.boom = boom
        self.restarts = 0

    def started_platforms(self):
        return ["telegram"] if self.running else []

    def restart(self, timeout: float = 15.0) -> None:
        self.restarts += 1
        if self.boom:
            raise RuntimeError("ربات بالا نیامد")


@pytest.fixture
def cpu_only(monkeypatch):
    monkeypatch.setattr(ai_engine, "gpu_offload_available", lambda force=False: False)


def test_perf_section_says_what_the_build_really_does(tmp_path, cpu_only):
    """۱۴: عددِ GPU حدس نیست — از خودِ موتور پرسیده می‌شه و همان‌جا نوشته می‌شه."""
    e = Env(tmp_path, manager=Manager())
    line = e.f("perf_gpu").value
    assert "CPU" in line
    monkeypatch_other = ai_engine.gpu_offload_available
    assert monkeypatch_other() is False


def test_perf_values_are_validated_and_saved(tmp_path):
    e = Env(tmp_path, manager=Manager(running=False))
    e.f("perf_cache").value = False
    e.f("perf_cache_minutes").value = "۴۵"
    e.f("perf_debounce_wait").value = "۲٫۵"
    e.f("perf_debounce_max").value = "۸"
    e.click("perf_save")
    assert e.settings.ai_response_cache is False
    assert e.settings.ai_response_cache_minutes == 45
    assert e.settings.debounce_wait_seconds == 2.5 and e.settings.debounce_max_wait_seconds == 8.0
    assert e.saves == 1
    assert e.note("perf_note")  # پیامِ ذخیره نشان داده می‌شه


def test_perf_rejects_a_cap_shorter_than_the_wait(tmp_path):
    e = Env(tmp_path, manager=Manager(running=False))
    wait_before, cap_before = e.settings.debounce_wait_seconds, e.settings.debounce_max_wait_seconds
    e.f("perf_debounce_wait").value = "۹"
    e.f("perf_debounce_max").value = "۴"
    e.click("perf_save")
    assert (e.settings.debounce_wait_seconds, e.settings.debounce_max_wait_seconds) == (wait_before, cap_before)
    assert "بیشتر" in e.note("perf_note")


def test_perf_rejects_a_non_number(tmp_path):
    e = Env(tmp_path, manager=Manager(running=False))
    e.f("perf_debounce_wait").value = ".zzz"
    e.click("perf_save")
    assert "عدد" in e.note("perf_note")


def test_perf_restarts_a_running_bot_and_reports_it(tmp_path):
    manager = Manager()
    e = Env(tmp_path, manager=manager)
    e.f("perf_debounce_wait").value = "۱"
    e.f("perf_debounce_max").value = "۶"
    e.click("perf_save")
    assert manager.restarts == 1
    assert "تنظیماتِ تازه" in e.note("perf_note")


def test_perf_reports_a_failed_restart_without_losing_the_save(tmp_path):
    manager = Manager(boom=True)
    e = Env(tmp_path, manager=manager)
    e.settings.debounce_wait_seconds = 5.0
    e.f("perf_debounce_wait").value = "۲"
    e.f("perf_debounce_max").value = "۹"
    e.click("perf_save")
    assert e.settings.debounce_wait_seconds == 2.0  # ذخیره شد
    assert manager.restarts == 1
    assert "بالا نیامد" in e.note("perf_note")


def test_the_four_settings_reach_the_runtime(tmp_path):
    """۱۷/۱۸: این کلیدها دیگر تزئینی نیستند — موتورِ پاسخ‌گویی واقعاً از آنها می‌خواند."""
    s = AppSettings(token_opt_max_tokens=False, token_opt_history_window=False,
                    ai_response_cache=False, ai_response_cache_minutes=30,
                    debounce_wait_seconds=1.5, debounce_max_wait_seconds=6)
    assert bot_pipeline._cache_seconds(s) == 0.0  # سوییچِ خاموش، سقفِ ۳۰ دقیقه را بی‌اثر می‌کند
    s.ai_response_cache = True
    assert bot_pipeline._cache_seconds(s) == 1800.0
    assert bot_pipeline._debounce_value(s, "debounce_wait_seconds", None, 3.0) == 1.5
    assert bot_pipeline._debounce_value(s, "debounce_wait_seconds", 0.2, 3.0) == 0.2
    assert s.debounce_wait_seconds == 1.5  # چیزی که مالک نوشت دست‌نخورده مانده
