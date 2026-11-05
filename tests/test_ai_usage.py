"""N1 — ثبتِ مصرفِ مدلِ محلی: شمارِ تماس‌ها، توکن‌ها، میانگین‌ها، روزِ خالی، جمع‌بندیِ ماهانه و برآوردِ توکن.

در نسخه‌ی ۱.۰.۰ خبری از دلار/بودجه نیست (هزینه‌ی مدلِ محلی همان برقِ خودِ فروشنده است)، پس
«مصرف» با توکن، زمانِ پاسخ و سهمِ تخمینی سنجیده می‌شه — نه با قیمتِ هر میلیون توکن.
"""

import pytest

from app.core import ai_usage as u
from app.core import token_budget as tb
from app.core.conversations import ConversationStore

DAY = 86400
T0 = 1_800_000_000  # یک روزِ ثابت


@pytest.fixture
def usage(tmp_path):
    clock = {"t": float(T0)}
    store = ConversationStore(tmp_path / "c.db")
    return u.UsageStore(store, clock=lambda: clock["t"]), clock, store


def rec(usage_store, **kw):
    base = dict(provider_id="a", model="m1", prompt_tokens=1000, completion_tokens=500, platform="telegram", chat_id="1", sys_tokens=300, hist_tokens=500, msg_tokens=50)
    base.update(kw)
    usage_store.record(**base)


def test_totals_by_model_and_averages(usage):
    s, clock, _ = usage
    rec(s); rec(s, prompt_tokens=3000, completion_tokens=1500, chat_id="2"); rec(s, ok=False)
    t = s.totals(0)
    assert (t.calls, t.ok_calls, t.prompt, t.completion) == (3, 2, 5000, 2500)
    bd = s.input_breakdown(0)
    assert bd["calls"] == 2 and bd["system"] == 300 and bd["history"] == 500


def test_period_filters_and_daily_series_fill_zero_days(usage):
    s, clock, _ = usage
    rec(s)
    clock["t"] += 3 * DAY
    rec(s, prompt_tokens=10, completion_tokens=5)
    daily = s.daily(5)
    assert len(daily) == 5 and sum(c for _d, c, _t in daily) == 2 and daily[-1][2] == 15
    assert s.totals(int(clock["t"]) - DAY).prompt == 10
    assert [c for c in s.top_chats(0, 5)][0][0] == "telegram"


def test_prune_rolls_old_rows_into_daily_summary_without_losing_totals(usage):
    s, clock, store = usage
    rec(s); rec(s)
    before = s.totals(0)
    clock["t"] += 100 * DAY
    rec(s, prompt_tokens=7, completion_tokens=3)
    assert s.prune() == 2
    assert store.connection().execute("SELECT COUNT(*) FROM ai_calls").fetchone()[0] == 1
    after = s.totals(0)
    assert after.prompt == before.prompt + 7 and after.calls == before.calls + 1
    assert s.prune() == 0  # idempotent
    assert sum(t for _d, _c, t in s.daily(120)) == before.tokens + 10


def test_local_metrics_are_what_the_usage_screen_shows(usage):
    """مصرفِ محلی = توکن + زمانِ پاسخ + سهمِ تخمینی؛ هیچ عددِ دلاری باقی نمانده است."""
    s, _clock, _store = usage
    assert u.LOCAL_PROVIDER == "local"
    rec(s, latency_ms=1200)
    rec(s, latency_ms=300)
    rec(s, ok=False, latency_ms=9000)  # خطا میانگینِ زمانِ پاسخ را آلوده نمی‌کند
    rec(s, chat_id="2", estimated=True, prompt_tokens=10, completion_tokens=5)
    assert s.avg_latency_ms(0) == 750
    est, answered = s.estimated_share(0)
    assert (est, answered) == (1, 3)  # یکی از سه پاسخِ موفق، توکنش تخمینی بود
    assert s.activity(0) == {"chats": 2, "calls": 3, "estimated": 1}
    assert s.totals(0).calls == 4 and "m1" in s.by_model(0)  # تماسِ ناموفق هم ثبت می‌شه
    for name in ("call_cost", "cost_of", "model_prices", "forecast_month", "what_if", "fmt_money", "Budget", "dec"):
        assert not hasattr(u, name), f"{name} دورانِ API بود و باید حذف می‌شد"


def test_recorder_binds_chat_and_survives_store_failure(usage, monkeypatch):
    s, _c, store = usage
    u.RECORDER = s
    try:
        with u.bind("telegram", "99", "agent"):
            u.record_call(provider_id="a", model="m", prompt_tokens=1)
        row = store.connection().execute("SELECT platform, chat_id, source FROM ai_calls").fetchone()
        assert (row["platform"], row["chat_id"], row["source"]) == ("telegram", "99", "agent")
        monkeypatch.setattr(s, "record", lambda **k: (_ for _ in ()).throw(RuntimeError("db")))
        u.record_call(provider_id="a")  # بی‌صدا
    finally:
        u.RECORDER = None


def test_token_estimates_and_window():
    assert tb.estimate_tokens("") == 0 and tb.estimate_tokens("abcd") == 1 and tb.estimate_tokens("سلام") >= 1
    assert tb.pick_max_tokens("سلام") < tb.pick_max_tokens("x" * 300) and tb.pick_max_tokens("hi", tools=True) > tb.pick_max_tokens("hi")
    from app.core.ai_engine import ChatMessage
    hist = [ChatMessage("user", "x" * 400) for _ in range(30)]
    kept = tb.fit_history("S", hist, "q", 1000, reply_tokens=200)
    assert 0 < len(kept) < 30 and kept == hist[-len(kept):]
    assert tb.fit_history("S", hist, "q", 50, reply_tokens=200) == []  # جا نبود ⇒ فقط سیستم+پیام
