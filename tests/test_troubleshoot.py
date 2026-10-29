"""N10 — عیب‌یابِ «ربات جواب نمی‌ده؟»: هر مشکل ← یک یافته‌ی فارسی با راه‌حل و مقاله‌ی معتبر؛ هیچ توکنی در خروجی نیست."""

import asyncio

import pytest

from app.core import guide, troubleshoot as ts
from app.core.adapter_common import AdapterStatus
from app.core.settings import AppSettings

TG, BALE = "123456:SECRET-TG-TOKEN", "bale-SECRET-TOKEN"


def status(connected=True, code="", user="shop_bot"):
    from app.core.adapter_common import STATE_CONNECTED, STATE_ERROR

    return AdapterStatus(state=STATE_CONNECTED if connected else STATE_ERROR, username=user if connected else None, error=None if connected else "x", error_code=code or None)


def make_settings(tg=True, bale=False, proxies=""):
    s = AppSettings()
    s.telegram_enabled, s.bale_enabled = tg, bale
    if tg:
        s.set_telegram_token(TG)
    if bale:
        s.set_bale_token(BALE)
    if proxies:
        s.set_telegram_proxy(proxies)
    s.ai_mode, s.api_base_url, s.api_model_name = "api", "https://api.example.com/v1", "m"
    s.set_api_key("sk-test")
    return s


def probes(**over):
    async def tg_check(token, proxies):
        return over.get("tg", status())

    async def bale_check(token):
        return over.get("bale", status())

    async def webhook(token, proxy):
        if isinstance(over.get("webhook"), Exception):
            raise over["webhook"]
        return over.get("webhook", "")

    async def server_time(url):
        return over.get("time", 1_800_000_000.0)

    async def proxy_probe(token, proxy):
        return over.get("proxy", {}).get(proxy, status(False, "no_connection"))

    return dict(check_telegram=tg_check, check_bale=bale_check, webhook_probe=webhook, server_time=server_time, proxy_probe=proxy_probe, now=lambda: 1_800_000_000.0)


def run(settings, running=True, **over):
    return {f.key: f for f in asyncio.run(ts.run(settings, bots_running=running, **probes(**over)))}


def test_healthy_setup_has_no_failures():
    out = run(make_settings())
    assert {f.status for f in out.values()} <= {ts.OK}
    assert out["telegram_token"].detail.startswith("درسته") and "shop_bot" in out["telegram_token"].detail


def test_no_bot_configured_and_bots_off():
    assert run(make_settings(tg=False))["no_bot"].status == ts.FAIL
    off = run(make_settings(), running=False)["running"]
    assert off.status == ts.WARN and off.article == "ts-bot-silent"


def test_invalid_token_and_no_connection_point_to_the_right_article():
    bad = run(make_settings(), tg=status(False, "invalid_token"))["telegram_token"]
    assert bad.status == ts.FAIL and bad.article == "ts-token-invalid"
    down = run(make_settings(), tg=status(False, "no_connection"))
    assert down["telegram_token"].article == "ts-no-connection" and down["proxy"].status == ts.WARN and down["proxy"].article == "ts-proxy"  # بدونِ پروکسی ← پیشنهاد
    bale = run(make_settings(tg=False, bale=True), bale=status(False, "invalid_token"))["bale_token"]
    assert bale.status == ts.FAIL and "بله" in bale.title


def test_proxy_diagnosis_counts_working_proxies():
    s = make_settings(proxies="socks5://a:1080\nsocks5://b:1080\nsocks5://c:1080")
    out = run(s, tg=status(False, "no_connection"), proxy={"socks5://b:1080": status()})
    assert out["proxy"].status == ts.OK and out["proxy"].detail.startswith("1 از 3")
    none = run(s, tg=status(False, "no_connection"))
    assert none["proxy"].status == ts.FAIL
    assert run(make_settings(), tg=status(False, "bad_proxy"))["telegram_token"].article == "ts-proxy"


def test_webhook_conflict_and_probe_errors():
    assert run(make_settings(), webhook="https://example.com/hook")["webhook"].article == "ts-webhook"
    assert run(make_settings(), webhook="")["webhook"].status == ts.OK
    assert "webhook" not in run(make_settings(), webhook=RuntimeError("boom"))  # پروبِ خراب = بدونِ ادعا


def test_clock_skew_detected_and_unknown_is_skip():
    skewed = run(make_settings(), time=1_800_000_000.0 - 900)["clock"]
    assert skewed.status == ts.FAIL and "۱۵ دقیقه" in skewed.detail and skewed.article == "ts-clock"
    assert run(make_settings(), time=None)["clock"].status == ts.SKIP
    assert run(make_settings(), time=1_800_000_000.0 + 60)["clock"].status == ts.OK


def test_ai_and_disk_findings(tmp_path):
    s = make_settings()
    s.ai_mode, s.api_base_url = "", ""
    s.set_api_key("")
    assert run(s)["ai"].status == ts.WARN and run(s)["ai"].article == "ai-choose"
    assert run(make_settings())["ai"].article == "ts-ai-key"
    out = asyncio.run(ts.run(make_settings(), data_dir=tmp_path, **probes()))
    assert any(f.key == "disk" for f in out)


def test_every_finding_links_to_a_real_article_and_never_leaks_secrets():
    scenarios = [run(make_settings(tg=False)), run(make_settings(), tg=status(False, "invalid_token")), run(make_settings(), tg=status(False, "no_connection")),
                 run(make_settings(), webhook="https://x"), run(make_settings(), time=0.0), run(make_settings(tg=True, bale=True), bale=status(False, "no_connection"))]
    for out in scenarios:
        for f in out.values():
            assert not f.article or guide.by_id(f.article), (f.key, f.article)
            blob = f.title + f.detail + f.article
            assert TG not in blob and BALE not in blob and "SECRET" not in blob and "sk-test" not in blob
            assert f.status in (ts.OK, ts.WARN, ts.FAIL, ts.SKIP) and f.detail


@pytest.mark.parametrize("article", ["ts-token-invalid", "ts-no-connection", "ts-proxy", "ts-bot-silent", "ts-clock", "ts-webhook", "ts-ai-key", "ts-disk", "bot-token", "ai-choose"])
def test_referenced_articles_exist(article):
    assert guide.by_id(article) is not None


def test_telegram_webhook_probe_against_fake_server():
    from fake_servers import FakeBotApiServer

    from app.core import telegram_adapter

    for mode, expect in (("ok", ""), ("webhook_conflict", "https://example.com/hook")):
        srv = FakeBotApiServer(username="x_bot")
        srv.mode = mode
        srv.start()
        try:
            assert asyncio.run(telegram_adapter.webhook_url("123456:ABCDEF", api_base=srv.base_url)) == expect
        finally:
            srv.stop()
    with pytest.raises(RuntimeError) as err:
        asyncio.run(telegram_adapter.webhook_url("", api_base="http://127.0.0.1:1"))
    assert "123456" not in str(err.value)


def test_http_server_time_returns_none_when_unreachable():
    assert asyncio.run(ts.http_server_time("http://127.0.0.1:1", timeout=1.0)) is None
