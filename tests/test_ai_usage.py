"""N1 — ثبتِ مصرف، میانگین‌ها، ریاضیِ هزینه (Decimal)، پیش‌بینی، «چه می‌شود اگر»، بودجه و واحدها."""

from decimal import Decimal

import pytest

from app.core import ai_usage as u
from app.core import token_budget as tb
from app.core.conversations import ConversationStore
from app.core.settings import AppSettings

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


def test_cost_math_is_exact_decimal_and_unpriced_models_are_reported_not_guessed():
    assert u.call_cost(1_000_000, 500_000, Decimal("0.15"), Decimal("0.6")) == Decimal("0.45")
    assert u.call_cost(3, 7, Decimal("0.1"), Decimal("0.2")) == Decimal("0.0000017")  # بدونِ خطای float
    by_model = {("a", "m1"): u.Totals(1, 1, 2_000_000, 1_000_000), ("b", "free"): u.Totals(1, 1, 500, 500), ("cache", "m1"): u.Totals(1, 1, 99, 99)}
    cost, unpriced = u.cost_of(by_model, {("a", "m1"): (Decimal("1"), Decimal("2"))})
    assert cost == Decimal("4") and unpriced == 1000  # کش جزوِ هزینه نیست؛ مدلِ بی‌قیمت جدا


def test_dec_parsing_is_safe():
    assert u.dec("۱٫۵") == Decimal("1.5") and u.dec("1,000") == Decimal("1000")
    for bad in ("abc", "-3", "NaN", "inf", "", None):
        assert u.dec(bad) == Decimal(0)


def test_prices_come_only_from_user_input_and_unit_conversion():
    s = AppSettings(ai_mode="api", ai_providers=[{"id": "a", "name": "A", "base_url": "https://x.example/v1", "models": [{"name": "m1", "price_in": "0.15", "price_out": ""}, {"name": "m2"}]}])
    assert u.model_prices(s) == {("a", "m1"): (Decimal("0.15"), Decimal(0))}  # قیمتِ پیش‌فرضِ ساختگی نیست
    assert u.fmt_money(Decimal("1.5"), s) == "$1.5000"  # نرخ ننوشته ⇒ دلار
    s.cost_display_unit, s.usd_to_irr_rate = "toman", "60,000"
    assert u.fmt_money(Decimal("1.5"), s) == "90,000 تومان"
    s.cost_display_unit = "irr"
    assert u.fmt_money(Decimal("1.5"), s) == "900,000 ریال"


def test_forecast_and_what_if():
    mid_month = 1_800_000_000  # ۲۰۲۷-۰۱-۱۵ ~
    assert u.forecast_month(Decimal("10"), mid_month) > Decimal("10")
    cost = u.what_if(100, 3, (2000, 500), (Decimal("1"), Decimal("2")))
    assert cost == u.call_cost(2000 * 9000, 500 * 9000, Decimal("1"), Decimal("2")) == Decimal("27")


def test_budget_status_thresholds(usage):
    s, clock, _ = usage
    settings = AppSettings(ai_mode="api", ai_providers=[{"id": "a", "name": "A", "base_url": "https://x.example/v1", "models": [{"name": "m1", "price_in": "1", "price_out": "0"}]}], ai_budget_monthly_usd="10")
    b = u.Budget(s, lambda: settings, clock=lambda: clock["t"])
    assert b.status() == "ok"
    rec(s, prompt_tokens=8_000_000, completion_tokens=0)
    assert b.status() == "warn"
    rec(s, prompt_tokens=2_000_000, completion_tokens=0)
    assert b.status() == "exceeded"
    settings.ai_budget_monthly_usd = ""
    assert b.status() == "ok"  # بدونِ بودجه


def test_recorder_binds_chat_and_survives_store_failure(usage, monkeypatch):
    s, _c, store = usage
    u.RECORDER = s
    try:
        with u.bind("bale", "99", "agent"):
            u.record_call(provider_id="a", model="m", prompt_tokens=1)
        row = store.connection().execute("SELECT platform, chat_id, source FROM ai_calls").fetchone()
        assert (row["platform"], row["chat_id"], row["source"]) == ("bale", "99", "agent")
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
