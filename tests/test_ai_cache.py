"""N18 — کشِ پاسخِ یکسان: آزمونِ جهشی (هر تغییرِ ورودی ⇒ حتماً miss با پرامپتِ تازه)، و هرگز-کش‌نکن‌ها. پیش‌فرض خاموش."""

import threading

import pytest
from fake_openai import FakeOpenAIServer, error_reply, usage_reply

from app.core import ai_cache, ai_usage, crypto, shop_texts
from app.core.ai_engine import AiEngineError, ChatMessage
from app.core.ai_providers import HEALTH, FailoverEngine
from app.core.orders import OrderStore
from app.core.products import ProductStore
from app.core.settings import AppSettings


@pytest.fixture(autouse=True)
def clean():
    HEALTH.reset()
    ai_cache.CACHE.invalidate_all()
    ai_cache.CACHE.hits = ai_cache.CACHE.misses = ai_cache.CACHE.tokens_saved = 0
    ai_usage.RECORDER = None
    yield
    ai_cache.CACHE.invalidate_all()


@pytest.fixture
def server():
    made = []

    def make(handler):
        s = FakeOpenAIServer(handler).start()
        made.append(s)
        return s

    yield make
    for s in made:
        s.stop()


def prov(srv, pid="a", model="m1"):
    return {"id": pid, "name": pid, "kind": "openai_compatible", "base_url": srv.base_url, "api_key_encrypted": crypto.encrypt("sk-x"), "timeout": 0, "enabled": True,
            "models": [{"name": model, "enabled": True, "max_context_tokens": 0, "tools_supported": None, "price_in": "", "price_out": ""}]}


def eng(providers, cache=True, **kw):
    s = AppSettings(ai_mode="api", ai_providers=providers, token_opt_response_cache=cache, **kw)
    return FailoverEngine(s, sleep=lambda x: None), s


def counting(server, text="جواب"):
    box = {"n": 0}

    def h(p):
        box["n"] += 1
        return usage_reply(f"{text} {box['n']}")

    return server(h), box


def test_cache_is_off_by_default(server):
    srv, box = counting(server)
    e, s = eng([prov(srv)], cache=False)
    assert AppSettings().token_opt_response_cache is False
    e.chat("SYS", [], "ساعتِ کاری؟"); e.chat("SYS", [], "ساعتِ کاری؟")
    assert box["n"] == 2 and len(ai_cache.CACHE) == 0


def test_identical_first_turn_question_hits_and_counts_savings(server):
    srv, box = counting(server)
    e, _s = eng([prov(srv)])
    first = e.chat("SYS", [], "ساعتِ کاری؟")
    second = e.chat("SYS", [], "ساعتِ کاری؟")
    assert first == second and box["n"] == 1
    st = ai_cache.CACHE.stats()
    assert st["hits"] == 1 and st["misses"] >= 1 and st["tokens_saved"] > 0


@pytest.mark.parametrize("mutation", ["system_prompt", "question", "model", "temperature_via_tools_off", "language_in_prompt"])
def test_any_input_change_is_a_miss_with_the_new_value_in_the_request(server, mutation):
    srv, box = counting(server)
    e, s = eng([prov(srv)])
    e.chat("قیمتِ گوشی ۱۰ میلیون", [], "گوشی چنده؟")
    base = box["n"]
    if mutation == "system_prompt":
        e.chat("قیمتِ گوشی ۱۲ میلیون", [], "گوشی چنده؟")  # قیمت عوض شد
        assert srv.requests[-1]["payload"]["messages"][0]["content"] == "قیمتِ گوشی ۱۲ میلیون"
    elif mutation == "question":
        e.chat("قیمتِ گوشی ۱۰ میلیون", [], "گوشی چند است؟")
    elif mutation == "model":
        s.ai_providers[0]["models"][0]["name"] = "m2"
        e2 = FailoverEngine(s, sleep=lambda x: None)
        e2.chat("قیمتِ گوشی ۱۰ میلیون", [], "گوشی چنده؟")
        assert srv.requests[-1]["payload"]["model"] == "m2"
    elif mutation == "temperature_via_tools_off":
        e.chat("قیمتِ گوشی ۱۰ میلیون\nEN", [], "گوشی چنده؟")
    else:
        e.chat("[fa] قیمتِ گوشی ۱۰ میلیون", [], "گوشی چنده؟")
    assert box["n"] == base + 1  # حتماً miss


def test_fallback_target_has_a_different_key(server):
    bad = server(lambda p: error_reply(500))
    good, box = counting(server)
    e, _s = eng([prov(bad, "a"), prov(good, "b")])
    e.chat("SYS", [], "سلام")
    assert box["n"] == 1 and len(ai_cache.CACHE) == 1
    # همان پرسش روی هدفِ دیگر کلیدِ دیگری دارد؛ مدارِ A هنوز بسته است پس باز هم به B می‌رسد و از کشِ B می‌خواند
    e.chat("SYS", [], "سلام")
    assert box["n"] == 1
    k_a = ai_cache.payload_key({"t": "a/m1", "p": {"x": 1}})
    k_b = ai_cache.payload_key({"t": "b/m1", "p": {"x": 1}})
    assert k_a != k_b


def test_customers_with_different_history_never_share_answers(server):
    srv, box = counting(server)
    e, _s = eng([prov(srv)])
    e.chat("SYS", [ChatMessage("user", "من علیم")], "اسمم چیه؟")
    e.chat("SYS", [ChatMessage("user", "من مریمم")], "اسمم چیه؟")
    e.chat("SYS", [ChatMessage("user", "من علیم")], "اسمم چیه؟")
    assert box["n"] == 3 and len(ai_cache.CACHE) == 0  # نوبتِ دارای تاریخچه اصلاً کش نمی‌شود


@pytest.mark.parametrize("msg", ["شماره‌ام ۰۹۱۲۳۴۵۶۷۸۹ است", "ایمیلم a@b.com", "این لینک https://x.com/pay", "کدِ سفارش 123456"])
def test_personal_data_is_never_cached(server, msg):
    srv, box = counting(server)
    e, _s = eng([prov(srv)])
    e.chat("SYS", [], msg.replace("۰۹۱۲۳۴۵۶۷۸۹", "09123456789")); e.chat("SYS", [], msg.replace("۰۹۱۲۳۴۵۶۷۸۹", "09123456789"))
    assert box["n"] == 2


def test_errors_incomplete_and_empty_answers_are_not_cached(server):
    state = {"n": 0}

    def h(p):
        state["n"] += 1
        if state["n"] <= 2:  # تلاشِ اول + تلاشِ مجددِ کوتاه
            return error_reply(500)
        if state["n"] == 3:
            return usage_reply("ناقص", finish="length")
        return usage_reply("کامل")

    srv = server(h)
    e, _s = eng([prov(srv)])
    with pytest.raises(AiEngineError):
        e.chat("SYS", [], "q")
    ai_cache.CACHE.invalidate_all()
    HEALTH.reset()
    assert e.chat("SYS", [], "q") == "کامل"  # length ⇒ یک‌بار با سقفِ بزرگ‌تر؛ نسخه‌ی ناقص کش نشد
    assert state["n"] == 4 and len(ai_cache.CACHE) == 1


def test_tool_turns_are_never_cached(server):
    from app.core import tool_protocol as tp

    srv, box = counting(server)
    e, _s = eng([prov(srv)])
    specs = [tp.ToolSpec("search_products", "x", {"type": "object", "properties": {}})]
    e.chat_tools("SYS", [], "سلام", specs, []); e.chat_tools("SYS", [], "سلام", specs, [])
    assert box["n"] == 2 and len(ai_cache.CACHE) == 0


def test_ttl_lru_size_and_clear():
    t = {"now": 0.0}
    c = ai_cache.ResponseCache(clock=lambda: t["now"])
    assert c.put("k", "v", ttl_seconds=60) and c.get("k") == "v"
    t["now"] = 61
    assert c.get("k") is None  # TTL
    assert c.put("big", "x", ttl_seconds=10 ** 9) and c._items["big"][0] - t["now"] <= ai_cache.MAX_TTL_SECONDS  # سقفِ ۲۴ ساعت
    for i in range(ai_cache.MAX_ITEMS + 50):
        c.put(f"k{i}", "v", 60)
    assert len(c) <= ai_cache.MAX_ITEMS and c.get("k0") is None and c.get(f"k{ai_cache.MAX_ITEMS + 49}") == "v"  # LRU
    assert not c.put("empty", "", 60) and not c.put("huge", "x" * 9000, 60)
    c.invalidate_all()
    assert len(c) == 0


def test_hooks_clear_the_cache_on_product_order_and_texts_changes(tmp_path):
    ai_cache.install_hooks()
    ai_cache.install_hooks()  # idempotent
    products = ProductStore(tmp_path / "p.db")
    orders = OrderStore(tmp_path / "o.db", product_store=products)
    for action in (lambda: products.add("کالا", 100_000, 5), lambda: shop_texts.configure(None)):
        ai_cache.CACHE.put("x", "y", 60)
        action()
        assert len(ai_cache.CACHE) == 0
    pid = products.add("کالا۲", 100_000, 5)
    ai_cache.CACHE.put("x", "y", 60)
    products.adjust_stock(pid, 1)
    assert len(ai_cache.CACHE) == 0
    ai_cache.CACHE.put("x", "y", 60)
    oid = orders.create("telegram", "1", [(pid, 1)])
    assert len(ai_cache.CACHE) == 0
    ai_cache.CACHE.put("x", "y", 60)
    orders.cancel(oid)
    assert len(ai_cache.CACHE) == 0


def test_concurrent_identical_requests_never_corrupt_the_cache(server):
    srv, box = counting(server)
    e, _s = eng([prov(srv)])
    results = []
    threads = [threading.Thread(target=lambda: results.append(e.chat("SYS", [], "ساعتِ کاری؟"))) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(results) == 12 and all(r.startswith("جواب") for r in results) and len(ai_cache.CACHE) == 1
    assert box["n"] >= 1


def test_stats_and_log_do_not_contain_message_text(server, caplog):
    srv, _box = counting(server)
    e, _s = eng([prov(srv)])
    with caplog.at_level("DEBUG"):
        e.chat("SYS", [], "پیامِ خیلی محرمانه"); e.chat("SYS", [], "پیامِ خیلی محرمانه")
    assert "محرمانه" not in caplog.text and "محرمانه" not in str(ai_cache.CACHE.stats())
