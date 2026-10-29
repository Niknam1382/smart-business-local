"""R6 — اشتراکِ پروکسی (لینکِ خودِ کاربر) و بازگشت به بهترین پروکسی."""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from app.core import proxy_subscription as sub
from app.core.bot_manager import BotManager
from app.core.proxy_pool import ProxyPool
from app.core.settings import AppSettings
from app.core.telegram_adapter import TelegramAdapter


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------- اعتبارسنجیِ لینک ----


def test_validate_url_accepts_https_warns_on_http_rejects_the_rest():
    assert sub.validate_url(" https://example.com/list.txt ") == ("https://example.com/list.txt", "")
    clean, warn = sub.validate_url("http://example.com/list")
    assert clean == "http://example.com/list" and "http ساده" in warn
    for bad in ("", "   ", "ftp://example.com/x", "javascript:alert(1)", "file:///etc/passwd", "https://", "example.com/x", "https://a b.com", "https://x.com/\x00", "https://" + "a" * 3000):
        with pytest.raises(sub.SubscriptionError):
            sub.validate_url(bad)


def test_fetch_proxies_parses_dedupes_and_rejects_empty_or_garbage():
    async def good(url):
        return "# my list\nsocks5://1.2.3.4:1080\n1.2.3.4:1080\nhttp://u:p@5.6.7.8:8080\nnot a proxy at all\n"

    parsed = run(sub.fetch_proxies("https://example.com/l", good))
    assert parsed.urls == ["socks5://1.2.3.4:1080", "http://u:p@5.6.7.8:8080"] and len(parsed.errors) == 1

    async def junk(url):
        return "<html>blocked</html>\nlogin required"

    with pytest.raises(sub.SubscriptionError, match="هیچ پروکسیِ معتبری"):
        run(sub.fetch_proxies("https://example.com/l", junk))

    async def huge(url):
        return "1.2.3.4:1080\n" * 40_000

    with pytest.raises(sub.SubscriptionError, match="۲۵۶"):
        run(sub.fetch_proxies("https://example.com/l", huge))
    with pytest.raises(sub.SubscriptionError):
        run(sub.fetch_proxies("ftp://example.com/l", good))


def test_combine_puts_manual_first_and_pool_dedupes():
    text = sub.combine("socks5://9.9.9.9:1080", "socks5://1.1.1.1:1080\nsocks5://9.9.9.9:1080")
    from app.core.proxy_pool import parse_proxy_text

    assert parse_proxy_text(text).urls == ["socks5://9.9.9.9:1080", "socks5://1.1.1.1:1080"]
    assert sub.combine("", "") == "" and sub.combine("a", "") == "a"


# ---------------------------------------------------- دریافتِ واقعیِ HTTP (سرورِ محلی) ----


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # ساکت
        pass

    def do_GET(self):
        if self.path == "/ok":
            body = b"socks5://1.2.3.4:1080\nsocks5://5.6.7.8:1080\n"
        elif self.path == "/big":
            body = b"1.2.3.4:1080\n" * 40_000
        elif self.path == "/bin":
            body = b"\xff\xfe\x00bad"
        elif self.path == "/err":
            self.send_response(500); self.end_headers(); return
        elif self.path == "/redir":
            self.send_response(302); self.send_header("Location", "/ok"); self.end_headers(); return
        elif self.path == "/loop":
            self.send_response(302); self.send_header("Location", "/loop"); self.end_headers(); return
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def http_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_real_http_fetch_success_redirect_and_all_failure_modes(http_server):
    assert run(sub.fetch_proxies(http_server + "/ok")).urls == ["socks5://1.2.3.4:1080", "socks5://5.6.7.8:1080"]
    assert len(run(sub.fetch_proxies(http_server + "/redir")).urls) == 2  # ریدایرکتِ http(s) مجازه
    for path, needle in (("/big", "۲۵۶"), ("/err", "HTTP 500"), ("/bin", "UTF-8"), ("/loop", "ممکن نشد"), ("/missing", "HTTP 404")):
        with pytest.raises(sub.SubscriptionError, match=needle):
            run(sub.fetch_proxies(http_server + path))
    with pytest.raises(sub.SubscriptionError, match="ممکن نشد"):
        run(sub.fetch_proxies("http://127.0.0.1:1/never"))  # پورتِ بسته


# ---------------------------------------------------------------- تنظیمات و استخر ----


def test_settings_roundtrip_encrypted_and_combined_text():
    s = AppSettings()
    s.set_telegram_proxy("socks5://9.9.9.9:1080")
    s.set_telegram_proxy_sub_url("https://example.com/secret-token-list")
    s.set_telegram_proxy_sub_cache("socks5://u:pw@1.1.1.1:1080")
    # (متنِ رمزنگاری‌شده base64 تصادفیه؛ فقط رشته‌های بلندِ بی‌قیدوبند معنی دارن، نه «pw» که شانسی هم ممکنه ببینیش)
    assert "secret-token-list" not in s.telegram_proxy_sub_url_encrypted and "u:pw@1.1.1.1" not in s.telegram_proxy_sub_cache_encrypted
    assert s.get_telegram_proxy_sub_url() == "https://example.com/secret-token-list"
    assert s.combined_telegram_proxy_text() == "socks5://9.9.9.9:1080\nsocks5://u:pw@1.1.1.1:1080"
    s.set_telegram_proxy_sub_cache("")
    assert s.combined_telegram_proxy_text() == "socks5://9.9.9.9:1080"


def test_pool_replace_keeps_state_and_current():
    pool = ProxyPool(["socks5://a:1", "socks5://b:1", "socks5://c:1"], cooldown=60)
    pool.report_success("socks5://b:1", 120.0)
    assert pool.current() == "socks5://b:1"
    assert pool.replace(["socks5://a:1", "socks5://b:1", "socks5://c:1"]) is False
    assert pool.replace(["socks5://z:1", "socks5://b:1", "socks5://a:1", "socks5://b:1"]) is True
    assert pool.urls == ["socks5://z:1", "socks5://b:1", "socks5://a:1"] and pool.current() == "socks5://b:1"
    assert pool.entry("socks5://b:1").latency_ms == 120.0  # حفظ شد
    assert pool.replace(["socks5://q:1", "socks5://r:1"]) is True and pool.current() == "socks5://q:1"  # فعلی حذف شد ⇒ اولی


# ------------------------------------------------------ BotManager: چرخه‌ی به‌روزرسانی ----


class FakeAdapter:
    def __init__(self, outcome):
        self.outcome, self.calls = outcome, []

    def update_proxy_pool(self, text):
        self.calls.append(text)
        return self.outcome

    current_proxy = "socks5://***@1.1.1.1:1080"
    proxy_events = [(1.0, "a", "b", "failover")]


def make_manager(fetcher, **settings_kw):
    settings = AppSettings(**settings_kw)
    settings.set_telegram_proxy_sub_url("https://example.com/list")
    return BotManager(settings, proxy_sub_fetcher=fetcher), settings


def test_manager_refresh_success_failure_keeps_cache_and_schedule(monkeypatch):
    state = {"mode": "ok"}

    async def fetcher(url):
        if state["mode"] == "fail":
            raise sub.SubscriptionError("سرور خراب")
        return "socks5://1.1.1.1:1080\nsocks5://2.2.2.2:1080\n"

    manager, settings = make_manager(fetcher)
    adapter = FakeAdapter("hot")
    manager._adapters["telegram"] = adapter  # noqa: SLF001
    assert "2 پروکسی" in run(manager._refresh_proxy_subscription())  # noqa: SLF001 — بارِ اول: به‌روزرسانی سررسیده
    assert settings.get_telegram_proxy_sub_cache() == "socks5://1.1.1.1:1080\nsocks5://2.2.2.2:1080" and settings.telegram_proxy_sub_updated_ts > 0
    assert len(adapter.calls) == 1 and manager.telegram_proxy_info()["restart_pending"] is False
    assert run(manager._refresh_proxy_subscription()) == ""  # noqa: SLF001 — هنوز سررسید نشده (۶ ساعت)
    state["mode"] = "fail"
    out = run(manager._refresh_proxy_subscription(force=True))  # noqa: SLF001
    assert "سرور خراب" in out and settings.telegram_proxy_sub_error
    assert settings.get_telegram_proxy_sub_cache().count("socks5") == 2  # شکست، کش رو پاک نکرد
    settings.telegram_proxy_sub_updated_ts = 0  # سررسید می‌شه ولی backoffِ ۱۵دقیقه‌ای مانع می‌شه
    assert run(manager._refresh_proxy_subscription()) == ""  # noqa: SLF001


def test_manager_manual_mode_restart_flag_and_info(monkeypatch):
    async def fetcher(url):
        return "socks5://1.1.1.1:1080\n"

    manager, settings = make_manager(fetcher, telegram_proxy_sub_hours=0)
    assert run(manager._refresh_proxy_subscription()) == ""  # noqa: SLF001 — ۰ = فقط دستی
    manager._adapters["telegram"] = FakeAdapter("restart")  # noqa: SLF001
    assert "1 پروکسی" in manager.refresh_proxy_subscription_sync()  # دکمه‌ی «به‌روزرسانیِ همین الان» (ربات خاموش هم کار می‌کنه)
    info = manager.telegram_proxy_info()
    assert info["restart_pending"] is True and info["current"].startswith("socks5://***@") and len(info["events"]) == 1
    empty = BotManager(AppSettings())
    assert empty.refresh_proxy_subscription_sync() == "—" or empty.refresh_proxy_subscription_sync() == ""


# --------------------------------------------- آداپتور: بازگشت به بهترین پروکسی ----


class _Session:
    async def close(self):
        pass


class _Bot:
    def __init__(self, proxy):
        self.proxy, self.session = proxy, _Session()


def make_adapter(urls, current, latencies, probe_results, interval=600.0):
    clock = SimpleNamespace(now=1000.0)
    probes = []

    async def prober(url):
        probes.append(url)
        return probe_results.get(url)

    pool = ProxyPool(urls)
    for url, latency in latencies.items():
        pool.report_success(url, latency)
    pool.report_success(current, latencies.get(current))  # فعلی = current
    adapter = TelegramAdapter("123456:ABCDEF", pipeline=None, proxy_pool=pool, bot_factory=lambda t, p, a: _Bot(p),
                              best_check_interval=interval, prober=prober, clock=lambda: clock.now)
    adapter._bot = _Bot(current)  # noqa: SLF001
    return adapter, pool, clock, probes


def test_returns_to_first_proxy_only_when_healthy_and_30_percent_faster():
    urls = ["socks5://a:1", "socks5://b:1"]
    adapter, pool, clock, probes = make_adapter(urls, "socks5://b:1", {"socks5://b:1": 200.0}, {"socks5://a:1": 100.0})
    assert adapter.proxy == "socks5://b:1"
    run(adapter._maybe_return_to_best())  # noqa: SLF001 — هنوز به بازه نرسیده
    assert probes == [] and adapter.proxy == "socks5://b:1"
    clock.now += 601
    run(adapter._maybe_return_to_best())  # noqa: SLF001
    assert probes == ["socks5://a:1"] and adapter.proxy == "socks5://a:1" and adapter._bot.proxy == "socks5://a:1"  # noqa: SLF001
    assert adapter.proxy_events[-1][1:] == ("socks5://b:1", "socks5://a:1", "back_to_best")
    assert pool.current() == "socks5://a:1"
    clock.now += 601
    run(adapter._maybe_return_to_best())  # noqa: SLF001
    assert probes == ["socks5://a:1"]  # روی اولی هستیم؛ probe لازم نیست


@pytest.mark.parametrize("probe,expect_switch", [(None, False), (150.0, False), (141.0, False), (139.0, True)])
def test_hysteresis_and_unhealthy_first_proxy_never_flip_flop(probe, expect_switch):
    adapter, pool, clock, probes = make_adapter(["socks5://a:1", "socks5://b:1"], "socks5://b:1", {"socks5://b:1": 200.0}, {"socks5://a:1": probe})
    clock.now += 601
    run(adapter._maybe_return_to_best())  # noqa: SLF001
    assert (adapter.proxy == "socks5://a:1") is expect_switch
    assert len(adapter.proxy_events) == (1 if expect_switch else 0)


def test_unknown_current_latency_switches_back_when_first_is_healthy_and_disabled_interval_never_probes():
    adapter, pool, clock, probes = make_adapter(["socks5://a:1", "socks5://b:1"], "socks5://b:1", {}, {"socks5://a:1": 50.0})
    clock.now += 601
    run(adapter._maybe_return_to_best())  # noqa: SLF001
    assert adapter.proxy == "socks5://a:1"
    adapter2, _pool2, clock2, probes2 = make_adapter(["socks5://a:1", "socks5://b:1"], "socks5://b:1", {"socks5://b:1": 900.0}, {"socks5://a:1": 10.0}, interval=0)
    clock2.now += 10_000
    run(adapter2._maybe_return_to_best())  # noqa: SLF001
    assert probes2 == [] and adapter2.proxy == "socks5://b:1"


def test_adapter_update_proxy_pool_hot_same_restart():
    adapter, pool, *_ = make_adapter(["socks5://a:1", "socks5://b:1"], "socks5://a:1", {}, {})
    assert adapter.update_proxy_pool("socks5://a:1\nsocks5://b:1") == "same"
    assert adapter.update_proxy_pool("socks5://a:1\nsocks5://b:1\nsocks5://c:1") == "hot" and len(pool) == 3
    assert adapter.update_proxy_pool("socks5://a:1") == "restart"  # از استخر به تک‌پروکسی = ساختار عوض شده
    plain = TelegramAdapter("123456:ABCDEF", pipeline=None, proxy="socks5://a:1", bot_factory=lambda t, p, a: _Bot(p))
    assert plain.update_proxy_pool("socks5://a:1") == "same"
    assert plain.update_proxy_pool("socks5://a:1\nsocks5://b:1") == "restart"
