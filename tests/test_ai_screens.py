"""N16/N1/N18 — صفحه‌های «ارائه‌دهنده‌های AI» و «مصرف و هزینه» (FakePage) + دکمه‌ی تست."""

import pytest
from fake_openai import FakeOpenAIServer, error_reply, usage_reply
from fake_page import FakePage, collect_text, find, fire

from app.core import ai_cache, ai_providers as ap, ai_usage as u, crypto
from app.core.bot_manager import BotManager
from app.core.conversations import ConversationStore
from app.core.settings import AppSettings, load_settings
from app.screens import ai_providers as prov_screen
from app.screens import usage as usage_screen


@pytest.fixture(autouse=True)
def clean():
    ap.HEALTH.reset()
    ai_cache.CACHE.invalidate_all()
    yield
    u.RECORDER = None


@pytest.fixture
def server():
    made = []

    def make(h):
        s = FakeOpenAIServer(h).start()
        made.append(s)
        return s

    yield make
    for s in made:
        s.stop()


def provs(settings, lang="fa"):
    page = FakePage()
    return page, prov_screen.build(page, lang, settings)


def test_add_provider_validates_url_models_and_key_then_encrypts_the_key():
    s = AppSettings(ai_mode="api")
    page, ctl = provs(s)
    f = lambda k: find(ctl, k)  # noqa: E731
    f("ap_url").value, f("ap_models").value, f("ap_key").value = "http://api.example.com/v1", "m1", "sk-1"
    fire(f("ap_add"), "on_click")
    assert "https://" in f("ap_notice").value and s.ai_providers == []
    f("ap_url").value, f("ap_models").value = "https://api.example.com/v1", ""
    fire(f("ap_add"), "on_click")
    assert "مدل" in f("ap_notice").value
    f("ap_models").value, f("ap_key").value = "m1، m2", ""
    fire(f("ap_add"), "on_click")
    assert "کلیدِ API" in f("ap_notice").value
    f("ap_key").value, f("ap_name").value = "sk-SECRET", "اصلی"
    fire(f("ap_add"), "on_click")
    [p] = s.ai_providers
    assert p["name"] == "اصلی" and [m["name"] for m in p["models"]] == ["m1", "m2"] and "sk-SECRET" not in str(p) and crypto.decrypt(p["api_key_encrypted"]) == "sk-SECRET"
    assert "sk-SECRET" not in collect_text(ctl)
    assert load_settings().ai_providers[0]["id"] == p["id"]  # روی دیسک ذخیره شد


def test_preset_fills_url_and_chain_order_moves_with_buttons():
    s = AppSettings(ai_mode="api", ai_providers=[
        {"id": "a", "name": "A", "base_url": "https://a.example/v1", "api_key_encrypted": "", "enabled": True, "models": [{"name": "x"}, {"name": "y"}]},
        {"id": "b", "name": "B", "base_url": "https://b.example/v1", "api_key_encrypted": "", "enabled": True, "models": [{"name": "z"}]}])
    page, ctl = provs(s)
    fire(find(ctl, "ap_preset"), "on_select", "groq")
    assert find(ctl, "ap_url").value.startswith("https://api.groq.com")
    fire(find(ctl, "ap_down_a"), "on_click")
    assert [p["id"] for p in s.ai_providers] == ["b", "a"]
    fire(find(ctl, "ap_mdown_a_0"), "on_click")
    assert [m["name"] for m in s.ai_providers[1]["models"]] == ["y", "x"]
    fire(find(ctl, "ap_on_b"), "on_change", False)
    assert s.ai_providers[0]["enabled"] is False
    assert [p.id for p in ap.parse_providers(s)] == ["b", "a"] and [t.key for t in ap.build_chain(ap.parse_providers(s))] == ["a/y", "a/x"]  # غیرفعال از زنجیره بیرون


def test_two_step_delete_and_model_edit_prices():
    s = AppSettings(ai_mode="api", ai_providers=[{"id": "a", "name": "A", "base_url": "https://a.example/v1", "api_key_encrypted": "", "enabled": True, "models": [{"name": "x"}]}])
    page, ctl = provs(s)
    find(ctl, "ap_pin_a_0").value = "0.15"
    fire(find(ctl, "ap_pin_a_0"), "on_blur")
    fire(find(ctl, "ap_ctx_a_0"), "on_blur")
    assert s.ai_providers[0]["models"][0]["price_in"] == "0.15"
    fire(find(ctl, "ap_mdel_a_0"), "on_click")
    assert len(s.ai_providers[0]["models"]) == 1
    fire(find(ctl, "ap_mdel_a_0"), "on_click")
    assert s.ai_providers[0]["models"] == []
    fire(find(ctl, "ap_del_a"), "on_click"); fire(find(ctl, "ap_del_a"), "on_click")
    assert s.ai_providers == [] and "هنوز ارائه‌دهنده‌ای" in collect_text(ctl)


def test_legacy_api_is_offered_for_conversion():
    s = AppSettings(ai_mode="api", api_base_url="https://api.example.com/v1", api_model_name="gpt-x")
    s.set_api_key("sk-legacy")
    page, ctl = provs(s)
    fire(find(ctl, "ap_migrate"), "on_click")
    [p] = s.ai_providers
    assert p["models"][0]["name"] == "gpt-x" and crypto.decrypt(p["api_key_encrypted"]) == "sk-legacy"


def test_chain_settings_are_validated_and_saved():
    s = AppSettings(ai_mode="api")
    page, ctl = provs(s)
    find(ctl, "ap_attempt").value = "abc"
    fire(find(ctl, "ap_save_chain"), "on_click")
    assert "درست نیست" in find(ctl, "ap_notice").value
    find(ctl, "ap_attempt").value, find(ctl, "ap_total").value, find(ctl, "ap_targets").value, find(ctl, "ap_conc").value = "10", "30", "2", "3"
    find(ctl, "ap_local").value = True
    fire(find(ctl, "ap_save_chain"), "on_click")
    assert (s.ai_attempt_timeout, s.ai_total_timeout, s.ai_max_targets, s.ai_provider_concurrency, s.ai_local_fallback) == (10, 30, 2, 3, True)


def test_status_badges_and_failover_history_render(server):
    s = AppSettings(ai_mode="api", ai_providers=[{"id": "a", "name": "A", "base_url": "https://a.example/v1", "api_key_encrypted": "", "enabled": True, "models": [{"name": "x"}]}])
    t = ap.build_chain(ap.parse_providers(s))[0]
    for _ in range(3):
        ap.HEALTH.failure(t, "transient")
    ap.HEALTH.note_failover(t, "transient", None)
    page, ctl = provs(s)
    text = collect_text(ctl)
    assert "قطع" in text and "A/x" not in text.replace("a/x", "") or "a/x" in text
    assert "a/x" in text and "جوابِ سرور کند" in text


def test_test_button_reports_latency_tokens_and_tool_support(server, monkeypatch):
    def handler(p):
        if "tools" in p:
            return usage_reply("ok")
        return usage_reply("OK", prompt=9, completion=1)

    srv = server(handler)
    s = AppSettings(ai_mode="api", ai_providers=[{"id": "a", "name": "A", "base_url": srv.base_url, "api_key_encrypted": crypto.encrypt("sk-t"), "enabled": True, "models": [{"name": "x"}]}])
    page, ctl = provs(s)
    fire(find(ctl, "ap_test_a_0"), "on_click")
    out = find(ctl, "ap_testout_a_0").value
    assert "✅" in out and "10 توکن" in out and "پشتیبانی می‌شه" in out and s.ai_providers[0]["models"][0]["tools_supported"] is True
    bad = server(lambda p: error_reply(401))
    s2 = AppSettings(ai_mode="api", ai_providers=[{"id": "b", "name": "B", "base_url": bad.base_url, "api_key_encrypted": crypto.encrypt("sk-t"), "enabled": True, "models": [{"name": "x"}]}])
    page, ctl = provs(s2)
    fire(find(ctl, "ap_test_b_0"), "on_click")
    assert "❌" in find(ctl, "ap_testout_b_0").value and "sk-t" not in find(ctl, "ap_testout_b_0").value


# ---------------------------------------------------------------- صفحه‌ی مصرف


@pytest.fixture
def usage_rig(tmp_path):
    s = AppSettings(ai_mode="api", ai_providers=[{"id": "a", "name": "A", "base_url": "https://a.example/v1", "api_key_encrypted": "", "enabled": True,
                                                  "models": [{"name": "m1", "price_in": "1", "price_out": "2"}, {"name": "free"}]}])
    manager = BotManager(s, store=ConversationStore(db_path=tmp_path / "c.db"), adapter_factories={}, log_dir=tmp_path)
    return s, manager


def test_usage_page_shows_totals_cost_unpriced_warning_and_tips(usage_rig):
    s, manager = usage_rig
    for _ in range(4):
        manager.usage.record(provider_id="a", model="m1", prompt_tokens=1_000_000, completion_tokens=500_000, platform="telegram", chat_id="1", sys_tokens=100, hist_tokens=900, msg_tokens=20)
    manager.usage.record(provider_id="a", model="free", prompt_tokens=700, completion_tokens=300, platform="telegram", chat_id="2")
    page = FakePage()
    ctl = usage_screen.build(page, "fa", s, manager)
    text = collect_text(ctl)
    assert "$8.0000" in text  # ۴ × (۱×۱ + ۰٫۵×۲)
    assert "1,000 توکن" in find(ctl, "us_unpriced").value and "تاریخچه" in text and "💡" in text
    assert "telegram:1" in text
    s.cost_display_unit, s.usd_to_irr_rate = "toman", "60000"
    assert "480,000 تومان" in collect_text(usage_screen.build(FakePage(), "fa", s, manager))


def test_usage_page_empty_state_and_what_if(usage_rig):
    s, manager = usage_rig
    page = FakePage()
    ctl = usage_screen.build(page, "fa", s, manager)
    assert find(ctl, "us_avg").value == "هنوز مصرفی ثبت نشده."
    fire(find(ctl, "us_wi_calc"), "on_click")
    assert "$" in find(ctl, "us_wi_result").value  # میانگینِ پیش‌فرض؛ مدلِ قیمت‌دار انتخاب شده
    find(ctl, "us_wi_customers").value = "x"
    fire(find(ctl, "us_wi_calc"), "on_click")
    assert "درست" in find(ctl, "us_wi_result").value


def test_usage_settings_save_validate_and_clear_cache(usage_rig):
    s, manager = usage_rig
    ctl = usage_screen.build(FakePage(), "fa", s, manager)
    find(ctl, "us_rate").value = "abc"
    fire(find(ctl, "us_save"), "on_click")
    assert "درست نیست" in find(ctl, "us_notice").value and s.usd_to_irr_rate == ""
    find(ctl, "us_rate").value, find(ctl, "us_unit").value, find(ctl, "us_budget").value, find(ctl, "us_action").value = "60000", "toman", "5", "stop"
    find(ctl, "us_opt_cache").value, find(ctl, "us_ttl").value, find(ctl, "us_opt_history").value = True, "30", False
    ai_cache.CACHE.put("k", "v", 60)
    fire(find(ctl, "us_save"), "on_click")
    assert (s.usd_to_irr_rate, s.cost_display_unit, s.ai_budget_monthly_usd, s.ai_budget_action, s.token_opt_response_cache, s.token_opt_cache_ttl_minutes, s.token_opt_history_window) == ("60000", "toman", "5", "stop", True, 30, False)
    assert len(ai_cache.CACHE) == 0  # ذخیره‌ی تنظیمات کش را پاک می‌کند
    find(ctl, "us_ttl").value = "99999"
    fire(find(ctl, "us_save"), "on_click")
    assert "درست نیست" in find(ctl, "us_notice").value
    ai_cache.CACHE.put("k", "v", 60)
    fire(find(ctl, "us_clear_cache"), "on_click")
    assert len(ai_cache.CACHE) == 0 and "پاک شد" in find(ctl, "us_notice").value


def test_english_pages_build(usage_rig):
    s, manager = usage_rig
    assert "Usage & cost" in collect_text(usage_screen.build(FakePage(), "en", s, manager))
    assert "AI providers" in collect_text(prov_screen.build(FakePage(), "en", s))
