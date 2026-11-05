"""استخر پروکسی تلگرام: پارس، چرخش، استراحتِ پروکسیِ خراب و رتبه‌بندی."""

import asyncio

import pytest

from app.core import proxy_pool as pp
from app.core.proxy_pool import ProxyFormatError, ProxyPool, normalize_proxy, parse_proxy_text


def run(coro):
    return asyncio.run(coro)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


# ---------------------------------------------------------------- پارس ----


@pytest.mark.parametrize(
    "line, expected",
    [
        ("socks5://127.0.0.1:10808", "socks5://127.0.0.1:10808"),
        ("SOCKS5://127.0.0.1:10808/", "socks5://127.0.0.1:10808"),
        ("socks5h://example.com:1080", "socks5://example.com:1080"),
        ("socks4://10.0.0.1:1080", "socks4://10.0.0.1:1080"),
        ("http://user:p%40ss@proxy.example.org:8080", "http://user:p%40ss@proxy.example.org:8080"),
        ("1.2.3.4:1080", "socks5://1.2.3.4:1080"),
        ("user:pass@1.2.3.4:1080", "socks5://user:pass@1.2.3.4:1080"),
        ("1.2.3.4:1080:user:pass", "socks5://user:pass@1.2.3.4:1080"),
        ("۱۲۷.۰.۰.۱:۱۰۸۰۸", "socks5://127.0.0.1:10808"),
        ("  socks5://[::1]:1080  ", "socks5://[::1]:1080"),
    ],
)
def test_normalize_accepts_common_formats(line, expected):
    assert normalize_proxy(line) == expected


@pytest.mark.parametrize(
    "line, fragment",
    [
        ("", "خالی"),
        ("tg://proxy?server=1.2.3.4&port=443&secret=abc", "MTProto"),
        ("https://t.me/proxy?server=1.2.3.4&port=443&secret=abc", "MTProto"),
        ("https://1.2.3.4:443", "https://"),
        ("ftp://1.2.3.4:21", "پشتیبانی نمی‌شه"),
        ("socks5://1.2.3.4", "پورت"),
        ("1.2.3.4:99999", "پورت"),
        ("1.2.3.4:abc", "پورت"),
        ("bad host!:1080", "معتبر نیست"),
        ("just-words", "نفهمیدم"),
    ],
)
def test_normalize_rejects_with_a_persian_reason(line, fragment):
    with pytest.raises(ProxyFormatError) as info:
        normalize_proxy(line)
    assert fragment in str(info.value)


def test_parse_text_collects_valid_dedupes_and_reports_errors():
    text = """
    # پروکسی‌های من
    socks5://127.0.0.1:10808
    1.2.3.4:1080   # سرور اول
    socks5://127.0.0.1:10808
    tg://proxy?server=9.9.9.9&port=443&secret=x

    http://u:pa#ss@h.example.com:8080
    """
    parsed = parse_proxy_text(text)
    assert parsed.urls == [
        "socks5://127.0.0.1:10808",
        "socks5://1.2.3.4:1080",
        "http://u:pa#ss@h.example.com:8080",
    ]
    assert len(parsed.errors) == 1 and "MTProto" in parsed.errors[0][2] and parsed.errors[0][0] == 6


def test_parse_empty_and_none():
    assert parse_proxy_text("").urls == [] and parse_proxy_text(None).urls == []


def test_mask_credentials():
    assert pp.mask_credentials("socks5://user:pass@1.2.3.4:1080") == "socks5://***@1.2.3.4:1080"
    assert pp.mask_credentials("socks5://1.2.3.4:1080") == "socks5://1.2.3.4:1080"


# ---------------------------------------------------------------- استخر ----


def test_empty_pool_means_direct_connection():
    pool = ProxyPool([])
    assert len(pool) == 0 and pool.pick() == "" and pool.current() == "" and pool.report_failure("x") == ""


def test_pick_is_stable_until_a_failure():
    pool = ProxyPool(["a", "b", "c"])
    assert pool.pick() == "a" and pool.pick() == "a"


def test_failure_rotates_to_next_and_puts_failed_one_to_rest():
    clock = Clock()
    pool = ProxyPool(["a", "b", "c"], cooldown=60, clock=clock)
    assert pool.report_failure("a") == "b"
    assert pool.is_cooling("a") and not pool.is_cooling("b")
    assert pool.report_failure("b") == "c"
    assert pool.report_failure("c") == "a", "همه استراحت می‌کنن؛ اولی که شروع کرد زودتر آماده می‌شه"


def test_cooldown_expires_and_proxy_is_usable_again():
    clock = Clock()
    pool = ProxyPool(["a", "b"], cooldown=60, clock=clock)
    pool.report_failure("a")  # → b
    pool.report_failure("b")  # a و b هر دو استراحت؛ a زودتر آماده می‌شه
    assert pool.pick() == "a"
    clock.now += 61
    assert not pool.is_cooling("a")


def test_all_cooling_picks_the_one_that_recovers_first():
    clock = Clock()
    pool = ProxyPool(["a", "b", "c"], cooldown=60, clock=clock)
    pool.report_failure("a")
    clock.now += 10
    pool.report_failure("b")
    clock.now += 10
    pool.report_failure("c")
    assert pool.pick() == "a", "a زودتر از همه شروع به استراحت کرد، پس زودتر از همه آماده می‌شه"


def test_repeated_failures_extend_the_cooldown_up_to_a_cap():
    clock = Clock()
    pool = ProxyPool(["a", "b"], cooldown=60, max_cooldown=100, clock=clock)
    pool.report_failure("a")
    first = pool.entry("a").cooldown_until - clock.now
    pool.report_failure("a")
    second = pool.entry("a").cooldown_until - clock.now
    pool.report_failure("a")
    third = pool.entry("a").cooldown_until - clock.now
    assert first == 60 and second == 100 and third == 100


def test_success_resets_failure_state_and_makes_proxy_current():
    clock = Clock()
    pool = ProxyPool(["a", "b"], cooldown=60, clock=clock)
    pool.report_failure("a")
    pool.report_success("a", latency_ms=120.0)
    assert not pool.is_cooling("a") and pool.entry("a").fails == 0 and pool.entry("a").latency_ms == 120.0
    assert pool.current() == "a"


def test_single_proxy_keeps_returning_itself():
    pool = ProxyPool(["only"], cooldown=60, clock=Clock())
    assert pool.report_failure("only") == "only"


def test_duplicate_urls_are_collapsed():
    assert ProxyPool(["a", "a", "b", ""]).urls == ["a", "b"]


def test_apply_probe_results_sorts_fastest_first_and_rests_the_dead():
    clock = Clock()
    pool = ProxyPool(["slow", "dead", "fast", "mid"], cooldown=60, clock=clock)
    pool.apply_probe_results({"slow": 900.0, "dead": None, "fast": 80.0, "mid": 300.0})
    assert pool.urls == ["fast", "mid", "slow", "dead"]
    assert pool.pick() == "fast" and pool.is_cooling("dead")


def test_apply_probe_results_ignores_unknown_urls():
    pool = ProxyPool(["a"], clock=Clock())
    pool.apply_probe_results({"zzz": 10.0})
    assert pool.urls == ["a"]


# --------------------------------------------------------------- تست واقعی ----


def test_probe_all_returns_latencies_and_respects_concurrency():
    active = {"now": 0, "max": 0}

    async def prober(url):
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        await asyncio.sleep(0.02)
        active["now"] -= 1
        return None if "bad" in url else 42.0

    urls = [f"socks5://h{i}:1" for i in range(7)] + ["socks5://bad:1"]
    result = run(pp.probe_all(urls, prober, concurrency=3))
    assert set(result) == set(urls) and result["socks5://bad:1"] is None and result["socks5://h0:1"] == 42.0
    assert active["max"] <= 3


def test_bare_lines_fall_back_to_http_when_socks_does_not_answer():
    calls = []

    async def prober(url):
        calls.append(url)
        return 50.0 if url.startswith("http://") else None

    result = run(pp.probe_bare_candidates(["1.2.3.4:8080", "socks5://5.6.7.8:1080", "garbage!"], prober))
    assert result == {"http://1.2.3.4:8080": 50.0, "socks5://5.6.7.8:1080": None}
    assert "http://5.6.7.8:1080" not in calls, "scheme صریح دست‌نخورده می‌مونه"


def test_real_probe_of_a_closed_port_returns_none_quickly():
    result = run(pp.probe_proxy("socks5://127.0.0.1:9", timeout=2.0))
    assert result is None


# ------------------------------------------------- یکپارچگی با آداپتور و مدیر ----


def test_proxy_config_from_text_variants():
    from app.core.proxy_pool import proxy_config_from_text, proxy_secrets

    assert proxy_config_from_text("") == ("", None)
    assert proxy_config_from_text("  \n# فقط کامنت\n") == ("", None)
    assert proxy_config_from_text("1.2.3.4:1080") == ("socks5://1.2.3.4:1080", None)
    proxy, pool = proxy_config_from_text("1.2.3.4:1080\nhttp://5.6.7.8:8080")
    assert proxy == "" and pool.urls == ["socks5://1.2.3.4:1080", "http://5.6.7.8:8080"]
    # فقط خطِ نامعتبر: خامش به آداپتور می‌رسه تا «پروکسی نامعتبره» نشون بده
    assert proxy_config_from_text("tg://proxy?server=1&port=2&secret=3") == ("tg://proxy?server=1&port=2&secret=3", None)
    secrets_list = proxy_secrets("user:pw@1.2.3.4:1080\n# note")
    assert "user:pw@1.2.3.4:1080" in secrets_list and "socks5://user:pw@1.2.3.4:1080" in secrets_list


def test_check_token_via_proxies_tries_in_order(monkeypatch):
    from app.core import telegram_adapter as ta
    from app.core.adapter_common import (
        ERR_INVALID_TOKEN,
        ERR_NO_CONNECTION,
        STATE_CONNECTED,
        STATE_ERROR,
        AdapterStatus,
    )

    tried = []

    async def fake_check(token, proxy="", api_base=""):
        tried.append(proxy)
        if proxy == "good":
            return AdapterStatus(state=STATE_CONNECTED, username="bot")
        return AdapterStatus(state=STATE_ERROR, error="x", error_code=ERR_NO_CONNECTION)

    monkeypatch.setattr(ta, "check_token", fake_check)
    result = run(ta.check_token_via_proxies("t", ["bad1", "bad2", "good", "never"]))
    assert result.connected and tried == ["bad1", "bad2", "good"]

    tried.clear()
    assert run(ta.check_token_via_proxies("t", ["bad1", "bad2"])).error_code == ERR_NO_CONNECTION and tried == ["bad1", "bad2"]
    tried.clear()
    assert run(ta.check_token_via_proxies("t", [])).error_code == ERR_NO_CONNECTION and tried == [""], "لیست خالی = مستقیم"

    async def invalid(token, proxy="", api_base=""):
        tried.append(proxy)
        return AdapterStatus(state=STATE_ERROR, error="bad token", error_code=ERR_INVALID_TOKEN)

    monkeypatch.setattr(ta, "check_token", invalid)
    tried.clear()
    assert run(ta.check_token_via_proxies("t", ["p1", "p2"])).error_code == ERR_INVALID_TOKEN and tried == ["p1"]


class _FakeBot:
    """جای aiogram.Bot: به ازای هر پروکسی رفتارِ جدا (وصل/قطع) و ثبتِ فراخوانی‌ها."""

    def __init__(self, proxy, behaviours, log):
        self.proxy = proxy
        self._behaviours = behaviours
        self._log = log
        self.session = _FakeSession()

    async def get_me(self, request_timeout=15):
        from aiogram.exceptions import TelegramNetworkError

        self._log.append(("get_me", self.proxy))
        if self._behaviours.get(self.proxy) == "down":
            raise TelegramNetworkError(method=None, message="proxy down")
        from types import SimpleNamespace

        return SimpleNamespace(username="shop_bot")

    async def get_updates(self, **kwargs):
        from aiogram.exceptions import TelegramNetworkError

        self._log.append(("get_updates", self.proxy))
        if self._behaviours.get(self.proxy) == "down":
            raise TelegramNetworkError(method=None, message="proxy down")
        await asyncio.sleep(0.01)
        return []


class _FakeSession:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


def _adapter(urls, behaviours, log, failover_after=2):
    from app.core.telegram_adapter import TelegramAdapter

    made = []

    def factory(token, proxy, api_base):
        bot = _FakeBot(proxy, behaviours, log)
        made.append(bot)
        return bot

    adapter = TelegramAdapter(
        "123456:ABCDEF",
        pipeline=None,
        proxy_pool=ProxyPool(urls, cooldown=60),
        retry_delays=(0.01, 0.02),
        poll_timeout=1,
        failover_after=failover_after,
        bot_factory=factory,
    )
    return adapter, made


async def _run_for(adapter, seconds):
    task = asyncio.create_task(adapter.run())
    await asyncio.sleep(seconds)
    await adapter.stop()
    await asyncio.wait_for(task, timeout=5)


def test_adapter_switches_to_next_proxy_after_consecutive_failures():
    log = []
    adapter, made = _adapter(["p1", "p2", "p3"], {"p1": "down", "p2": "down"}, log, failover_after=2)
    run(_run_for(adapter, 0.6))
    assert [b.proxy for b in made][:3] == ["p1", "p2", "p3"], "هر پروکسیِ خراب بعد از ۲ شکست کنار می‌ره"
    assert adapter.proxy == "p3" and adapter.status.state in ("connected", "stopped")
    assert made[0].session.closed and made[1].session.closed, "جلسه‌ی قدیمی بسته می‌شه"
    assert any(call == ("get_updates", "p3") for call in log), "polling با پروکسیِ سالم ادامه پیدا کرد"


def test_adapter_does_not_switch_on_a_single_transient_failure():
    log = []
    adapter, made = _adapter(["p1", "p2"], {}, log, failover_after=3)
    adapter._pool.entry("p1")  # noqa: SLF001
    # یه شکستِ تکی (کمتر از آستانه) پروکسی رو عوض نمی‌کنه
    run(adapter._note_network_failure())  # noqa: SLF001
    assert adapter.proxy == "p1" and made == []


def test_adapter_with_single_proxy_never_switches():
    log = []
    adapter, made = _adapter(["only"], {"only": "down"}, log, failover_after=1)
    run(_run_for(adapter, 0.2))
    assert {b.proxy for b in made} == {"only"} and len(made) == 1


def test_adapter_logs_never_show_proxy_credentials(caplog):
    import logging

    log = []
    adapter, _ = _adapter(["socks5://user:secret@1.1.1.1:1080", "socks5://2.2.2.2:1080"], {"socks5://user:secret@1.1.1.1:1080": "down"}, log, failover_after=1)
    with caplog.at_level(logging.WARNING, logger="app.core.telegram_adapter"):
        run(_run_for(adapter, 0.4))
    assert "secret" not in caplog.text and "user:secret" not in caplog.text
    assert "پروکسی تلگرام عوض شد" in caplog.text
