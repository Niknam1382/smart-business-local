"""N10 — عیب‌یابِ «ربات جواب نمی‌ده؟»: هر مشکل ← یک یافته‌ی فارسی با راه‌حل و مقاله‌ی معتبر؛ هیچ توکنی در خروجی نیست.

نسخه‌ی ۱.۰.۰: تلگرام تنها پیام‌رسانِ گفتگو است (بله فقط درگاهِ پرداختِ «بله‌پی» است، پس یافته‌ی
``bale_pay`` از تنظیماتِ توکن‌ها می‌آید نه از شبکه) و هوش مصنوعی فقط محلی است (یافته‌ی ``ai``
از ``ai_engine.engine_readiness``)."""

import asyncio
from types import SimpleNamespace

import pytest

from app.core import ai_engine, guide, model_catalog, troubleshoot as ts
from app.core.adapter_common import AdapterStatus
from app.core.settings import AppSettings

TG = "123456:SECRET-TG-TOKEN"
BALE_PAY_BOT = "bale-pay-SECRET-TOKEN"
BALE_PROVIDER = "WALLET-SECRET-PROVIDER-TOKEN"
FAKE_TIME = 1_800_000_000.0


def status(connected=True, code="", user="shop_bot"):
    from app.core.adapter_common import STATE_CONNECTED, STATE_ERROR

    return AdapterStatus(state=STATE_CONNECTED if connected else STATE_ERROR, username=user if connected else None, error=None if connected else "x", error_code=code or None)


def make_settings(tg=True, proxies="", bale_pay=False):
    s = AppSettings()
    s.telegram_enabled = tg
    if tg:
        s.set_telegram_token(TG)
    if bale_pay:
        s.bale_pay_enabled = True
    if proxies:
        s.set_telegram_proxy(proxies)
    return s


def probes(**over):
    async def tg_check(token, proxies):
        return over.get("tg", status())

    async def webhook(token, proxy):
        if isinstance(over.get("webhook"), Exception):
            raise over["webhook"]
        return over.get("webhook", "")

    async def server_time(url):
        return over.get("time", FAKE_TIME)

    async def proxy_probe(token, proxy):
        return over.get("proxy", {}).get(proxy, status(False, "no_connection"))

    return dict(
        check_telegram=tg_check, webhook_probe=webhook, server_time=server_time, proxy_probe=proxy_probe, now=lambda: FAKE_TIME
    )


def run(settings, running=True, **over):
    return {f.key: f for f in asyncio.run(ts.run(settings, bots_running=running, **probes(**over)))}


def test_healthy_setup_has_no_failures(tmp_path, monkeypatch):
    """همه‌چیز درست + مدلِ محلیِ آماده ⇒ هیچ FAILی نباید باشه و AI هم OK بشه."""
    s = make_settings()
    model = tmp_path / "m.gguf"
    model.write_bytes(b"GGUF")
    s.model_file_path = str(model)
    monkeypatch.setattr(ai_engine, "_llama_available", lambda: True)
    out = run(s)
    assert {f.status for f in out.values()} <= {ts.OK}
    assert out["telegram_token"].detail.startswith("درسته") and "shop_bot" in out["telegram_token"].detail
    assert out["ai"].status == ts.OK


def test_no_bot_configured_and_bots_off():
    assert run(make_settings(tg=False))["no_bot"].status == ts.FAIL
    off = run(make_settings(), running=False)["running"]
    assert off.status == ts.WARN and off.article == "ts-bot-silent"


def test_bale_is_never_reported_as_a_messenger():
    """بله دیگر پیام‌رسان نیست: هیچ‌وقت نباید یافته‌ی ``bale_token``/«رباتِ بله» produced بشه،
    حتی وقتی توکنِ پرداخت هم وارد نشده."""
    s = make_settings(tg=False, bale_pay=True)
    out = run(s)
    assert "bale_token" not in out and "bale_running" not in out
    assert not any("گفتگو" in f.detail and "بله" in f.title for f in out.values())


def test_bale_pay_finding_checks_both_tokens_without_any_network_call():
    """درگاهِ پرداخت بدونِ هر دو توکن کار نمی‌کند؛ عیب‌یاب باید نامِ کم‌شده‌ها را بگوید — و هیچ
    پروبِ شبکه‌ای به بله نزند (آن ربات روی loopِ خودش تست می‌شه)."""
    half = run(make_settings(bale_pay=True))
    assert half["bale_pay"].status == ts.FAIL and half["bale_pay"].article == "pay-bale"
    assert "توکنِ رباتِ پرداختِ بله" in half["bale_pay"].detail and "provider_token" in half["bale_pay"].detail

    s = make_settings(bale_pay=True)
    s.set_bale_pay_bot_token(BALE_PAY_BOT)
    out = run(s)
    assert "توکنِ درگاه" in out["bale_pay"].detail and "توکنِ رباتِ پرداختِ بله" not in out["bale_pay"].detail

    s.set_bale_pay_provider_token(BALE_PROVIDER)
    ok = run(s)["bale_pay"]
    assert ok.status == ts.OK and "هر دو توکن" in ok.detail
    # خاموش ⇒ اصلاً یافته‌ای نیست (کاربرِ بدونِ بله‌پی نباید گله‌ی درگاه ببیند)
    assert "bale_pay" not in run(make_settings())


def test_invalid_token_and_no_connection_point_to_the_right_article():
    bad = run(make_settings(), tg=status(False, "invalid_token"))["telegram_token"]
    assert bad.status == ts.FAIL and bad.article == "ts-token-invalid"
    down = run(make_settings(), tg=status(False, "no_connection"))
    assert down["telegram_token"].article == "ts-no-connection" and down["proxy"].status == ts.WARN and down["proxy"].article == "ts-proxy"  # بدونِ پروکسی ← پیشنهاد


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
    skewed = run(make_settings(), time=FAKE_TIME - 900)["clock"]
    assert skewed.status == ts.FAIL and "۱۵ دقیقه" in skewed.detail and skewed.article == "ts-clock"
    assert run(make_settings(), time=None)["clock"].status == ts.SKIP
    assert run(make_settings(), time=FAKE_TIME + 60)["clock"].status == ts.OK


def test_ai_finding_comes_from_local_readiness_only(tmp_path, monkeypatch):
    """هیچ API/کلیدِ بیرونی‌ای نیست: یافته‌ی «هوش مصنوعی» دقیقاً همان ``engine_readiness`` است."""
    s = make_settings()
    assert run(s)["ai"].status == ts.WARN and run(s)["ai"].article == "ai-choose"  # مدلی انتخاب نشده

    model = tmp_path / "m.gguf"
    model.write_bytes(b"GGUF")
    monkeypatch.setattr(ai_engine, "_llama_available", lambda: True)

    ready = make_settings()
    ready.model_file_path = str(model)
    assert run(ready)["ai"].status == ts.OK and run(ready)["ai"].article == "ai-local"

    no_llama = make_settings()
    no_llama.model_file_path = str(model)
    monkeypatch.setattr(ai_engine, "_llama_available", lambda: False)
    out = run(no_llama)["ai"]
    assert out.status == ts.FAIL and "llama" in out.detail

    monkeypatch.setattr(ai_engine, "_llama_available", lambda: True)
    missing = make_settings()
    missing.model_file_path = str(tmp_path / "nothing.gguf")
    out = run(missing)["ai"]
    # مسیر را خودِ مالک داده و آن فایل وجود ندارد ⇒ «مدل انتخاب نشده» دروغ است؛ باید بگوید مسیر غلط است
    assert out.status == ts.FAIL and "GGUF" in out.detail and out.article == "ai-local"

    bad = make_settings()
    bad.model_id = "tiny-model"
    bad.model_file_path = ""
    monkeypatch.setattr(ai_engine, "downloader_ok", lambda path, entry: False)
    monkeypatch.setattr(model_catalog, "get_entry", lambda mid: SimpleNamespace(filename="m.gguf", size_bytes=99))
    out = run(bad)["ai"]
    assert out.status == ts.WARN and out.article == "ai-local"


def test_explicit_model_file_takes_priority_over_stale_model_id(tmp_path, monkeypatch):
    """مسیرِ صریحِ فایلِ GGUF نباید به‌علتِ model_idِ قدیمی/کاذب، به‌صورتِ اشتباه به‌عنوانِ مدلِ نامعتبر گزارش شود."""
    s = make_settings()
    model = tmp_path / "chosen.gguf"
    model.write_bytes(b"GGUF")
    s.model_file_path = str(model)
    s.model_id = "qwen35-4b"
    monkeypatch.setattr(ai_engine, "_llama_available", lambda: True)
    out = run(s)["ai"]
    assert out.status == ts.OK and out.article == "ai-local"


def test_invalid_explicit_model_path_is_reported_as_a_bad_path(tmp_path, monkeypatch):
    """«مسیرِ داده‌شده معتبر نیست» باید دلیلش را درست بگوید، نه اینکه وانمود کند مدلی انتخاب نشده."""
    monkeypatch.setattr(ai_engine, "_llama_available", lambda: True)
    s = make_settings()
    folder = tmp_path / "not-a-model"
    folder.mkdir()
    s.model_file_path = str(folder)  # پوشه، نه فایلِ GGUF
    ready, reason = ai_engine.engine_readiness(s)
    assert not ready and reason == "ai.ready.path_invalid"
    out = run(s)["ai"]
    assert out.status == ts.FAIL and "پوشه" in out.detail

    wrong_ext = tmp_path / "notes.txt"
    wrong_ext.write_text("x", encoding="utf-8")
    s.model_file_path = str(wrong_ext)
    assert ai_engine.engine_readiness(s)[1] == "ai.ready.path_invalid"

    # و وقتی اصلاً مسیری داده نشده باشد، همان «مدلی انتخاب نشده» می‌ماند
    s.model_file_path = ""
    assert ai_engine.engine_readiness(s)[1] == "ai.ready.no_model_selected"


def test_disk_finding(tmp_path):
    out = asyncio.run(ts.run(make_settings(), data_dir=tmp_path, **probes()))
    assert any(f.key == "disk" for f in out)


def test_every_finding_links_to_a_real_article_and_never_leaks_secrets():
    bale_on = make_settings(bale_pay=True)
    bale_on.set_bale_pay_bot_token(BALE_PAY_BOT)
    bale_on.set_bale_pay_provider_token(BALE_PROVIDER)
    scenarios = [
        run(make_settings(tg=False)),
        run(make_settings(), tg=status(False, "invalid_token")),
        run(make_settings(), tg=status(False, "no_connection")),
        run(make_settings(), webhook="https://x"),
        run(make_settings(), time=0.0),
        run(make_settings(bale_pay=True)),  # توکن‌هایِ ناقصِ درگاه
        run(bale_on),  # درگاهِ کامل
    ]
    for out in scenarios:
        for f in out.values():
            assert not f.article or guide.by_id(f.article), (f.key, f.article)
            blob = f.title + f.detail + f.article
            assert TG not in blob and BALE_PAY_BOT not in blob and BALE_PROVIDER not in blob
            assert "SECRET" not in blob and "sk-" not in blob
            assert f.status in (ts.OK, ts.WARN, ts.FAIL, ts.SKIP) and f.detail


@pytest.mark.parametrize(
    "article",
    ["ts-token-invalid", "ts-no-connection", "ts-proxy", "ts-bot-silent", "ts-clock", "ts-webhook", "ts-disk", "bot-token", "ai-choose", "ai-local", "pay-bale"],
)
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
