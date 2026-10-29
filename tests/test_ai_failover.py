"""N16 — زنجیره‌ی چند API/مدل با جابه‌جاییِ خودکار (سرورِ جعلیِ OpenAI)؛ مدارشکن، طبقه‌بندیِ شکست، حافظه، هم‌زمانی، امنیت."""

import threading

import pytest
from fake_openai import FakeOpenAIServer, error_reply, message_reply, native_call, usage_reply

from app.core import ai_cache, ai_providers, ai_usage, crypto, tool_protocol
from app.core.ai_engine import AiEngineError, ChatMessage
from app.core.ai_providers import HEALTH, FailoverEngine, classify, parse_providers, validate_base_url
from app.core.conversations import ConversationStore
from app.core.settings import AppSettings

SPECS = [tool_protocol.ToolSpec("search_products", "جست‌وجو", {"type": "object", "properties": {"query": {"type": "string"}}})]


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture(autouse=True)
def clean():
    HEALTH.reset()
    HEALTH.notifier = None
    ai_cache.CACHE.invalidate_all()
    ai_usage.RECORDER = None
    yield
    HEALTH.reset()
    HEALTH.notifier = None
    ai_usage.RECORDER = None


@pytest.fixture
def servers():
    made = []

    def make(handler):
        srv = FakeOpenAIServer(handler).start()
        made.append(srv)
        return srv

    yield make
    for s in made:
        s.stop()


def provider(srv, pid, models=("m1",), key="sk-secret-key", **kw):
    return {"id": pid, "name": pid.upper(), "kind": "openai_compatible", "base_url": srv.base_url, "api_key_encrypted": crypto.encrypt(key), "timeout": kw.pop("timeout", 0),
            "enabled": True, "models": [{"name": m, "enabled": True, "max_context_tokens": kw.get("ctx", 0), "tools_supported": None, "price_in": kw.get("pin", ""), "price_out": kw.get("pout", "")} for m in models]}


def engine(providers, clock=None, **settings_kw):
    s = AppSettings(ai_mode="api", ai_providers=providers, ai_total_timeout=20, **settings_kw)
    saved = []
    clock = clock or Clock()
    HEALTH.clock = clock
    eng = FailoverEngine(s, persist=lambda: saved.append(1), sleep=lambda x: None)
    eng.saved, eng.clock = saved, clock
    return eng, s


def ok(text="سلام"):
    return lambda payload: usage_reply(text)


def ask(eng, text="سلام", history=None):
    return eng.chat("SYS", history or [], text)


# ---------------------------------------------------------------- پیکربندی


def test_legacy_single_api_settings_become_provider_one():
    s = AppSettings(ai_mode="api", api_base_url="https://api.example.com/v1", api_model_name="gpt-x")
    s.set_api_key("sk-legacy")
    [p] = parse_providers(s)
    assert (p.id, p.base_url, p.api_key, [m.name for m in p.models]) == ("api-1", "https://api.example.com/v1", "sk-legacy", ["gpt-x"])
    s.ai_providers = [{"id": "z", "name": "Z", "base_url": "https://z.example/v1", "models": [{"name": "a"}]}]
    assert [p.id for p in parse_providers(s)] == ["z"]  # تنظیماتِ تازه جایگزینِ قدیمی می‌شود


@pytest.mark.parametrize("url,ok_", [("https://api.openai.com/v1", True), ("http://localhost:11434/v1", True), ("http://192.168.1.5:8080/v1", True), ("http://127.0.0.1:1/v1", True),
                                      ("http://api.example.com/v1", False), ("ftp://x.com", False), ("https://user:pw@x.com/v1", False), ("api.example.com", False), ("", False)])
def test_base_url_rules(url, ok_):
    if ok_:
        assert validate_base_url(url) == url.rstrip("/")
    else:
        with pytest.raises(ValueError):
            validate_base_url(url)


# ---------------------------------------------------------------- مسیرِ شاد و ثبتِ مصرف


def test_first_target_answers_and_real_usage_is_recorded(servers, tmp_path):
    a = servers(lambda p: usage_reply("جوابِ A", prompt=120, completion=30, cached=100))
    store = ConversationStore(tmp_path / "c.db")
    ai_usage.RECORDER = ai_usage.UsageStore(store)
    eng, _s = engine([provider(a, "a")])
    with ai_usage.bind("telegram", "42", "chat"):
        assert ask(eng) == "جوابِ A"
    row = store.connection().execute("SELECT * FROM ai_calls").fetchone()
    assert (row["provider_id"], row["model"], row["prompt_tokens"], row["completion_tokens"], row["cached_tokens"], row["estimated"], row["chat_id"], row["ok"]) == ("a", "m1", 120, 30, 100, 0, "42", 1)
    assert a.requests[0]["auth"] == "Bearer sk-secret-key" and a.requests[0]["payload"]["model"] == "m1"


def test_missing_usage_field_is_estimated_and_labelled(servers, tmp_path):
    a = servers(lambda p: usage_reply("سلام دنیا", with_usage=False))
    store = ConversationStore(tmp_path / "c.db")
    ai_usage.RECORDER = ai_usage.UsageStore(store)
    eng, _s = engine([provider(a, "a")])
    ask(eng)
    row = store.connection().execute("SELECT * FROM ai_calls").fetchone()
    assert row["estimated"] == 1 and row["prompt_tokens"] > 0 and row["completion_tokens"] > 0


# ---------------------------------------------------------------- جابه‌جایی و مدارشکن


def test_server_error_falls_over_to_next_provider_with_identical_memory(servers):
    a = servers(lambda p: error_reply(500))
    b = servers(ok("از B"))
    eng, _s = engine([provider(a, "a"), provider(b, "b")])
    hist = [ChatMessage("user", "قیمتِ گوشی؟"), ChatMessage("assistant", "۱۰ میلیون")]
    assert ask(eng, "موجوده؟", hist) == "از B"
    seen_a = a.requests[0]["payload"]["messages"]
    seen_b = b.requests[0]["payload"]["messages"]
    assert [m["content"] for m in seen_a] == [m["content"] for m in seen_b] == ["SYS", "قیمتِ گوشی؟", "۱۰ میلیون", "موجوده؟"]  # حافظه بینِ ارائه‌دهنده‌ها یکسان
    assert HEALTH.events[0]["from"] == "a/m1" and HEALTH.events[0]["to"] == "b/m1"


def test_breaker_opens_after_three_failures_then_half_open_probe_returns_to_primary(servers):
    state = {"down": True}
    a = servers(lambda p: error_reply(500) if state["down"] else usage_reply("A برگشت"))
    b = servers(ok("B"))
    eng, _s = engine([provider(a, "a"), provider(b, "b")])
    for _ in range(3):
        assert ask(eng) == "B"
    calls_a = len(a.requests)
    assert ask(eng) == "B" and len(a.requests) == calls_a  # مدار باز: دیگه به A نمی‌زنیم
    state["down"] = False
    eng.clock.t += 31  # مهلتِ اولِ مدار (۳۰ث) تموم شد ⇒ یک درخواستِ آزمایشی
    assert ask(eng) == "A برگشت" and len(a.requests) > calls_a
    assert ask(eng) == "A برگشت"  # مدار بسته؛ از سرِ زنجیره = برگشتِ خودکار به اصلی


def test_half_open_probe_failure_reopens_with_longer_backoff(servers):
    a = servers(lambda p: error_reply(503))
    b = servers(ok("B"))
    eng, _s = engine([provider(a, "a"), provider(b, "b")])
    for _ in range(3):
        ask(eng)
    eng.clock.t += 31
    ask(eng)  # probe شکست می‌خوره
    n = len(a.requests)
    eng.clock.t += 31
    ask(eng)
    assert len(a.requests) == n  # حالا ۱۲۰ث بسته است
    eng.clock.t += 100
    ask(eng)
    assert len(a.requests) > n


def test_429_short_retry_after_retries_same_target_but_long_one_skips(servers):
    calls = {"n": 0}

    def flaky(p):
        calls["n"] += 1
        return error_reply(429, headers={"Retry-After": "1"}) if calls["n"] == 1 else usage_reply("بعد از صبر")

    a = servers(flaky)
    eng, _s = engine([provider(a, "a")])
    assert ask(eng) == "بعد از صبر" and calls["n"] == 2
    b = servers(lambda p: error_reply(429, headers={"Retry-After": "30"}))
    c = servers(ok("C"))
    eng2, _s = engine([provider(b, "b"), provider(c, "c")])
    assert ask(eng2) == "C" and len(b.requests) == 1


def test_invalid_key_blocks_the_whole_provider_and_alerts_once(servers):
    alerts = []
    HEALTH.notifier = alerts.append
    a = servers(lambda p: error_reply(401, "bad key"))
    b = servers(ok("B"))
    eng, _s = engine([provider(a, "a", models=("m1", "m2")), provider(b, "b")])
    assert ask(eng) == "B" and len(a.requests) == 1  # m2 ی A هم امتحان نشد
    assert ask(eng) == "B" and len(a.requests) == 1
    assert len([x for x in alerts if "کلیدِ API نامعتبره" in x]) == 1


def test_exhausted_quota_blocks_provider_for_an_hour(servers):
    a = servers(lambda p: error_reply(429, "You exceeded your current quota", code="insufficient_quota"))
    b = servers(ok("B"))
    eng, _s = engine([provider(a, "a"), provider(b, "b")])
    assert classify(ai_providers.AiHttpError("x", 429, "insufficient_quota")) == "quota"
    ask(eng)
    ask(eng)
    assert len(a.requests) == 1
    eng.clock.t += 3601
    ask(eng)
    assert len(a.requests) == 2


def test_removed_model_is_disabled_persistently_but_next_model_of_same_api_continues(servers):
    def handler(p):
        return error_reply(404, "The model `old` does not exist", code="model_not_found") if p["model"] == "old" else usage_reply("از new")

    a = servers(handler)
    b = servers(ok("B"))
    eng, s = engine([provider(a, "a", models=("old", "new")), provider(b, "b")])
    assert ask(eng) == "از new" and eng.saved
    assert s.ai_providers[0]["models"][0]["enabled"] is False and s.ai_providers[0]["models"][1]["enabled"] is True
    assert len(b.requests) == 0  # فقط همان مدل کنار رفت، API نه


def test_context_overflow_trims_history_and_retries_same_target(servers):
    seen = []

    def handler(p):
        seen.append(len(p["messages"]))
        return error_reply(400, "This model's maximum context length is 8192 tokens", code="context_length_exceeded") if len(seen) == 1 else usage_reply("بعد از کوتاه‌سازی")

    a = servers(handler)
    eng, _s = engine([provider(a, "a", ctx=4000)])
    hist = [ChatMessage("user" if i % 2 == 0 else "assistant", "پیام " * 200 + str(i)) for i in range(10)]
    assert ask(eng, "آخرین", hist) == "بعد از کوتاه‌سازی"
    assert len(seen) == 2 and seen[1] < seen[0] and len(a.requests) == 2
    assert a.requests[1]["payload"]["messages"][-1]["content"] == "آخرین"  # آخرین پیام همیشه می‌مونه


def test_tools_unsupported_switches_that_model_to_text_protocol(servers):
    def handler(p):
        if "tools" in p:
            return error_reply(400, "tools are not supported by this function-less model")
        return usage_reply('<tool_call>{"name": "search_products", "arguments": {"query": "گوشی"}}</tool_call>')

    a = servers(handler)
    eng, s = engine([provider(a, "a")])
    turn = eng.chat_tools("SYS", [], "گوشی دارید؟", SPECS, [])
    assert [c.name for c in turn.tool_calls] == ["search_products"]
    assert s.ai_providers[0]["models"][0]["tools_supported"] is False and eng.saved
    eng.chat_tools("SYS", [], "دوباره", SPECS, [])
    assert all("tools" not in r["payload"] for r in a.requests[2:])  # دیگه بومی امتحان نمی‌شود


def test_content_filter_gives_safe_reply_without_failover(servers):
    a = servers(lambda p: error_reply(400, "blocked", code="content_filter"))
    b = servers(ok("B"))
    eng, _s = engine([provider(a, "a"), provider(b, "b")])
    assert "نمی‌تونم" in ask(eng) and len(b.requests) == 0


def test_broken_json_and_empty_answer_count_as_failures(servers):
    a = servers(lambda p: (200, "this is not json"))
    b = servers(lambda p: (200, {"choices": [{"message": {"content": ""}}]}))
    c = servers(ok("C"))
    eng, _s = engine([provider(a, "a"), provider(b, "b"), provider(c, "c")], ai_max_targets=3)
    assert ask(eng) == "C"


def test_slow_server_times_out_then_falls_over(servers):
    a = servers(lambda p: (200, {"choices": [{"message": {"content": "دیر"}}]}, {"sleep": 2.5}))
    b = servers(ok("B"))
    eng, _s = engine([provider(a, "a", timeout=1), provider(b, "b")])
    assert ask(eng) == "B"


def test_all_targets_failing_raises_alerts_once_and_announces_recovery(servers):
    alerts = []
    HEALTH.notifier = alerts.append
    state = {"down": True}
    a = servers(lambda p: error_reply(500) if state["down"] else usage_reply("برگشت"))
    eng, _s = engine([provider(a, "a")])
    for _ in range(2):
        with pytest.raises(AiEngineError):
            ask(eng)
    assert len([x for x in alerts if "هیچ‌کدام از APIهای هوش مصنوعی" in x]) == 1
    state["down"] = False
    eng.clock.t += 2000
    assert ask(eng) == "برگشت"
    assert any("دوباره" in x for x in alerts)


def test_max_targets_caps_the_attempts(servers):
    down = [servers(lambda p: error_reply(500)) for _ in range(3)]
    c = servers(ok("C"))
    eng, _s = engine([provider(down[0], "a"), provider(down[1], "b"), provider(down[2], "c"), provider(c, "d")], ai_max_targets=3)
    with pytest.raises(AiEngineError):
        ask(eng)
    assert len(c.requests) == 0


def test_provider_concurrency_is_capped(servers):
    state = {"now": 0, "max": 0}
    lock = threading.Lock()

    def handler(p):
        import time
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        time.sleep(0.15)
        with lock:
            state["now"] -= 1
        return usage_reply("ok")

    a = servers(handler)
    eng, _s = engine([provider(a, "a")], ai_provider_concurrency=2)
    threads = [threading.Thread(target=lambda: ask(eng)) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert 1 <= state["max"] <= 2


def test_api_key_never_appears_in_errors_or_logs(servers, caplog):
    a = servers(lambda p: error_reply(500, "echo sk-secret-key leaked?"))
    eng, _s = engine([provider(a, "a")])
    with caplog.at_level("DEBUG"):
        with pytest.raises(AiEngineError) as exc:
            ask(eng)
    assert "sk-secret-key" not in str(exc.value) and "sk-secret-key" not in caplog.text


# ---------------------------------------------------------------- ابزار، خروجی، پنجره


def test_tool_loop_continues_on_another_provider_after_switch(servers):
    a_calls = {"n": 0}

    def a_handler(p):
        a_calls["n"] += 1
        if a_calls["n"] == 1:
            return message_reply(None, [native_call("search_products", {"query": "گوشی"})])
        return error_reply(500)

    a = servers(a_handler)
    b = servers(ok("نتیجه‌ی نهایی"))
    eng, _s = engine([provider(a, "a"), provider(b, "b")])
    turn = eng.chat_tools("SYS", [], "گوشی", SPECS, [])
    assert turn.tool_calls and turn.tool_calls[0].name == "search_products"
    tool_msgs = [{"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", "name": "search_products", "arguments": {"query": "گوشی"}}]},
                 {"role": "tool", "tool_call_id": "call_1", "name": "search_products", "content": '{"products": []}'}]
    turn2 = eng.chat_tools("SYS", [], "گوشی", SPECS, tool_msgs)
    assert turn2.text == "نتیجه‌ی نهایی"
    assert any(m.get("role") == "tool" for m in b.requests[0]["payload"]["messages"])  # مدلِ بعدی تبادلِ ابزار را دید


def test_finish_reason_length_retries_once_with_a_bigger_cap(servers):
    caps = []

    def handler(p):
        caps.append(p.get("max_tokens"))
        return usage_reply("ناقص", finish="length") if len(caps) == 1 else usage_reply("کامل")

    a = servers(handler)
    eng, _s = engine([provider(a, "a")])
    assert ask(eng, "سلام") == "کامل" and caps[1] == caps[0] * 2


def test_history_window_by_tokens_keeps_system_and_last_messages_and_measures_savings(servers, tmp_path):
    a = servers(ok("ok"))
    store = ConversationStore(tmp_path / "c.db")
    ai_usage.RECORDER = ai_usage.UsageStore(store)
    eng, _s = engine([provider(a, "a", ctx=1200)])
    hist = [ChatMessage("user" if i % 2 == 0 else "assistant", f"پیام شماره {i} " + "متن " * 80) for i in range(14)]
    ask(eng, "آخرین پرسش", hist)
    sent = a.requests[0]["payload"]["messages"]
    assert sent[0]["content"] == "SYS" and sent[-1]["content"] == "آخرین پرسش" and len(sent) < len(hist) + 2
    assert sent[-2]["content"] == hist[-1].content  # جدیدترین پیامِ تاریخچه می‌ماند
    row = store.connection().execute("SELECT saved_tokens, hist_tokens FROM ai_calls").fetchone()
    assert row["saved_tokens"] > 0 and row["hist_tokens"] > 0


def test_max_tokens_optimization_can_be_turned_off(servers):
    a = servers(ok("ok"))
    eng, _s = engine([provider(a, "a")], token_opt_max_tokens=False)
    ask(eng)
    assert "max_tokens" not in a.requests[0]["payload"]


# ---------------------------------------------------------------- بودجه (N1 × N16)


def budget_rig(servers, tmp_path, action, limit="0.001"):
    a = servers(lambda p: usage_reply("ok", prompt=1_000_000, completion=0))
    store = ConversationStore(tmp_path / "c.db")
    usage = ai_usage.UsageStore(store)
    ai_usage.RECORDER = usage
    eng, s = engine([provider(a, "a", pin="1", pout="2")], ai_budget_monthly_usd=limit, ai_budget_action=action)
    eng.budget = ai_usage.Budget(usage, lambda: s)
    return a, eng, usage


def test_budget_stop_blocks_ai_after_the_limit_is_reached(servers, tmp_path):
    a, eng, _u = budget_rig(servers, tmp_path, "stop")
    assert ask(eng) == "ok"  # اولین تماس: هنوز مصرفی نیست
    with pytest.raises(AiEngineError):
        ask(eng)
    assert len(a.requests) == 1


def test_budget_warn_alerts_but_keeps_answering_and_local_without_model_stops(servers, tmp_path):
    alerts = []
    HEALTH.notifier = alerts.append
    a, eng, _u = budget_rig(servers, tmp_path, "warn")
    ask(eng); ask(eng); ask(eng)
    assert len(a.requests) == 3 and len([x for x in alerts if "بودجه" in x]) >= 1
    a2, eng2, _u = budget_rig(servers, tmp_path / "x", "local") if (tmp_path / "x").mkdir() is None else (None, None, None)
    ask(eng2)
    with pytest.raises(AiEngineError):
        ask(eng2)
