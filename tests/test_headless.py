"""R7 — حالتِ headless: سلامت (heartbeat)، کدهای خروج، توقفِ تمیز، و اجرای واقعی روی آداپتورهای جعلی."""

import json
import threading
import time
from types import SimpleNamespace

import pytest
from fake_servers import FakeBotApiServer
from helpers import wait_until
from test_adapters_e2e import make_manager, make_settings

from app import headless
from app.core.bot_manager import BotManagerError
from app.core.conversations import ConversationStore  # noqa: F401


class FakeManager:
    def __init__(self, platforms=("telegram",), die_after=None, start_error=None):
        self._platforms, self.die_after, self.start_error = list(platforms), die_after, start_error
        self.running, self.started_at, self.stopped = False, None, False

    def enabled_platforms(self):
        return self._platforms

    def start(self):
        if self.start_error:
            raise BotManagerError(self.start_error)
        self.running, self.started_at = True, time.monotonic()

    def is_running(self):
        if self.die_after is not None and time.monotonic() - self.started_at > self.die_after:
            self.running = False
        return self.running

    def get_status(self):
        st = SimpleNamespace(connected=True, error="")
        return SimpleNamespace(running=self.running, platforms={name: st for name in self._platforms})

    def stop(self):
        self.running, self.stopped = False, True


def run(manager, tmp_path, stop=None, interval=0.05):
    out: list = []
    ev = stop or threading.Event()
    code = headless.run(manager, tmp_path, interval, ev, out=out.append)
    return code, out


def test_health_check_states(tmp_path):
    assert headless.check_health(tmp_path)[0] is False  # بدونِ heartbeat
    manager = FakeManager()
    manager.start()
    headless.write_heartbeat(manager, tmp_path, now=1000.0)
    assert headless.check_health(tmp_path, now=1050.0) == (True, "ok")
    ok, msg = headless.check_health(tmp_path, now=1000.0 + 500)
    assert not ok and "قدیمیه" in msg
    manager.stop()
    headless.write_heartbeat(manager, tmp_path, now=2000.0)
    ok, msg = headless.check_health(tmp_path, now=2001.0)
    assert not ok and "در حال اجرا نیست" in msg
    (tmp_path / headless.HEARTBEAT_FILE).write_text("{broken", encoding="utf-8")
    assert not headless.check_health(tmp_path)[0]


def test_heartbeat_survives_a_reader_that_holds_the_file_open(tmp_path, monkeypatch):
    """ویندوز: اگر خواننده‌ای heartbeat.json را باز داشته باشد os.replace با PermissionError می‌شکنه.
    heartbeat نباید باعثِ کرشِ حلقه‌ی headless بشود — بعد از چند تلاشِ کم‌صبر جای‌گزار می‌شه."""
    manager = FakeManager()
    manager.start()
    real_replace = headless.os.replace
    state = {"calls": 0}

    def flaky_replace(src, dst):
        state["calls"] += 1
        if state["calls"] <= 2:
            raise PermissionError(13, "Access is denied", str(dst))
        return real_replace(src, dst)

    monkeypatch.setattr(headless.os, "replace", flaky_replace)
    monkeypatch.setattr(headless.time, "sleep", lambda _s: None)
    headless.write_heartbeat(manager, tmp_path, now=1500.0)
    assert state["calls"] == 3
    assert json.loads((tmp_path / headless.HEARTBEAT_FILE).read_text(encoding="utf-8"))["ts"] == 1500.0
    assert not (tmp_path / "heartbeat.tmp").exists()


def test_heartbeat_falls_back_to_a_whole_file_write_when_replace_never_works(tmp_path, monkeypatch):
    """اگر جابه‌جایی هیچ‌وقت نشود، حداقلِ کاری که باید بکنیم این است که داده‌ی ناسالم یا نیمه‌فایل
    جا نماند: یک نوشتنِ کاملِ مستقیم، و پاک‌کردنِ فایلِ موقت."""

    def blocked_replace(_src, _dst):
        raise PermissionError(13, "Access is denied", _dst)

    manager = FakeManager()
    manager.start()
    monkeypatch.setattr(headless.os, "replace", blocked_replace)
    monkeypatch.setattr(headless.time, "sleep", lambda _s: None)
    headless.write_heartbeat(manager, tmp_path, now=1600.0)
    data = json.loads((tmp_path / headless.HEARTBEAT_FILE).read_text(encoding="utf-8"))
    assert data["ts"] == 1600.0 and data["running"] is True
    assert not (tmp_path / "heartbeat.tmp").exists()
    assert headless.check_health(tmp_path, now=1601.0)[0] is True


def test_exit_codes_no_platform_start_error_and_unexpected_death(tmp_path):
    code, out = run(FakeManager(platforms=()), tmp_path)
    assert code == headless.EXIT_NO_PLATFORM and "هیچ رباتی فعال نیست" in out[0]
    code, out = run(FakeManager(start_error="توکن نامعتبر"), tmp_path)
    assert code == headless.EXIT_NO_PLATFORM and "توکن نامعتبر" in out[0]
    dying = FakeManager(die_after=0.2)
    code, out = run(dying, tmp_path)
    assert code == headless.EXIT_DIED and any("ناگهانی" in line for line in out) and dying.stopped
    assert not (tmp_path / headless.HEARTBEAT_FILE).exists()  # بعد از خروج heartbeat پاک می‌شه → healthcheck ناسالم


def test_graceful_stop_writes_heartbeat_then_removes_it(tmp_path):
    manager = FakeManager()
    stop = threading.Event()
    result: list = []
    thread = threading.Thread(target=lambda: result.append(run(manager, tmp_path, stop)))
    thread.start()
    assert wait_until(lambda: (tmp_path / headless.HEARTBEAT_FILE).exists(), timeout=5)
    assert headless.check_health(tmp_path) == (True, "ok")
    stop.set()
    thread.join(timeout=5)
    code, out = result[0]
    assert code == headless.EXIT_OK and manager.stopped and any("وصل" in line for line in out)
    assert not (tmp_path / headless.HEARTBEAT_FILE).exists()


def test_main_loads_settings_from_data_dir_and_reports_no_platform(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("SMART_BUSINESS_DATA_DIR", raising=False)
    data = tmp_path / "d"
    code = headless.main(["--data-dir", str(data), "--status-interval", "0.1"], stop_event=threading.Event())
    assert code == headless.EXIT_NO_PLATFORM  # تنظیماتِ خالی: هیچ ربات/توکنی نیست
    assert "هیچ رباتی فعال نیست" in capsys.readouterr().out
    assert data.is_dir()
    code = headless.main(["--healthcheck", "--data-dir", str(data)])
    assert code == headless.EXIT_DIED and "heartbeat" in capsys.readouterr().out


def test_incompatible_database_exits_with_code_3(tmp_path, monkeypatch, capsys):
    import sqlite3

    data = tmp_path / "d2"
    data.mkdir()
    conn = sqlite3.connect(data / "products.db")
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    code = headless.main(["--data-dir", str(data)], stop_event=threading.Event())
    assert code == headless.EXIT_INCOMPATIBLE and "به‌روز" in capsys.readouterr().out


@pytest.fixture
def tg():
    srv = FakeBotApiServer(username="tg_head_bot").start()
    yield srv
    srv.stop()


def test_headless_serves_real_telegram_traffic_then_stops_cleanly(tmp_path, tg, monkeypatch):
    from fakes import ScriptedToolEngine, say

    settings = make_settings()
    manager, _store = make_manager(tmp_path, settings, tg)
    monkeypatch.setattr("app.core.ai_engine.build_engine_from_settings", lambda s: ScriptedToolEngine({}, default=say("جواب headless")))
    stop = threading.Event()
    data = tmp_path / "hd"
    result: list = []

    def target():
        result.append(headless.run(manager, data, 0.1, stop, out=lambda line: None))

    data.mkdir()
    thread = threading.Thread(target=target)
    thread.start()
    try:
        assert wait_until(lambda: (data / headless.HEARTBEAT_FILE).exists(), timeout=20)
        assert wait_until(lambda: manager.get_status().platforms["telegram"].connected, timeout=20)
        assert set(manager.get_status().platforms) == {"telegram"}  # بله پیام‌رسان نیست؛ فقط تلگرام
        tg.push_message(10, "سلام تلگرام")
        assert wait_until(lambda: any("جواب headless" in m or "پاسخ" in m for m in tg.sent_to(10)), timeout=15)
        hb = json.loads((data / headless.HEARTBEAT_FILE).read_text(encoding="utf-8"))
        assert hb["running"] and hb["platforms"]["telegram"]["connected"]
    finally:
        stop.set()
        thread.join(timeout=20)
    assert result == [headless.EXIT_OK] and not manager.is_running()
