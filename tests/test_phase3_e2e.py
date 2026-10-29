"""فاز ۳ (۱.۱.۰-alpha.3) سرتاسری — با مدیرِ ربات و آداپتورهای واقعی روی سرورهای جعلیِ تلگرام/بله:
N13 عضویتِ اجباریِ کانال · N7 پیامِ همگانی و /stop · N6 پیامِ شخصیِ مالک."""

import pytest
from fake_servers import FakeBotApiServer
from fakes import say
from helpers import wait_until
from test_adapters_e2e import make_settings
from test_commerce_e2e import got, make_commerce_manager, start_both, use_engine

from app.core import broadcast as bc
from app.core.bot_manager import BotManagerError
from app.core.bot_pipeline import IncomingMessage

TG_CHANNEL = {"platform": "telegram", "channel": "@shop_channel", "title": "کانال فروشگاه"}
BALE_CHANNEL = {"platform": "bale", "channel": "@bale_channel", "title": "کانال بله"}
WELCOME = "به فروشگاه خوش اومدی"
GATE = "اول توی کانالِ زیر عضو شو"
OWNER = "900"


@pytest.fixture
def tg():
    srv = FakeBotApiServer(username="tg_shop_bot").start()
    yield srv
    srv.stop()


@pytest.fixture
def bale():
    srv = FakeBotApiServer(username="bale_shop_bot").start()
    yield srv
    srv.stop()


class Env:
    def __init__(self, manager, settings, tg, bale, engine):
        self.manager, self.settings, self.tg, self.bale, self.engine = manager, settings, tg, bale, engine
        self.customers = manager.customers

    def channels(self, *items, scope="both", enabled=True):
        self.settings.required_channels = list(items)
        self.settings.required_channels_scope = scope
        self.settings.required_channels_enabled = enabled

    def start(self):
        start_both(self.manager)

    def wait(self, server, chat, needle, timeout=10):
        assert wait_until(lambda: got(server, chat, needle), timeout=timeout), f"{needle!r} نیومد؛ پیام‌ها: {server.sent_to(chat)}"

    def joined(self, server, chat):
        return server.push_callback_query(chat, "c:joined", message_id=1)

    def mark(self, platform, chat, text="سلام", **kw):
        """مشتری بدونِ ربات روشن در جدول ثبت می‌شود (برای سناریوهایی که ربات بعداً روشن می‌شود)."""
        self.customers.touch(IncomingMessage(platform=platform, chat_id=str(chat), display_name="", text=text, **kw))

    def done(self, bid, timeout=20):
        assert wait_until(lambda: self.manager.broadcasts.store.status_of(bid) == "done", timeout=timeout), self.manager.broadcasts.store.get(bid)


@pytest.fixture
def env(tmp_path, tg, bale, monkeypatch):
    settings = make_settings()
    settings.owner_chats = {"telegram": OWNER}
    engine = use_engine(monkeypatch, default=say("پاسخِ AI"))
    manager, _products, _orders = make_commerce_manager(tmp_path, settings, tg, bale)
    settings.shop_mode = "shop_buttons"
    e = Env(manager, settings, tg, bale, engine)
    yield e
    manager.stop()


# ============================================================ N13: عضویتِ اجباریِ کانال ====


def test_non_member_sees_the_join_prompt_then_joins_and_enters_the_shop(env):
    env.channels(TG_CHANNEL)
    env.start()
    env.tg.member_status["@shop_channel"] = "left"
    env.tg.push_message("111", "/start")
    env.wait(env.tg, "111", GATE)
    assert WELCOME not in " ".join(env.tg.sent_to("111"))  # منو هنوز نیامده
    assert env.tg.buttons_to("111") == [("📢 کانال فروشگاه", "https://t.me/shop_channel"), ("✅ عضو شدم", None)]
    assert env.tg.chat_member_calls == [{"chat_id": "@shop_channel", "user_id": "111"}]

    env.tg.member_status["@shop_channel"] = "member"
    env.joined(env.tg, "111")
    env.wait(env.tg, "111", WELCOME)
    assert env.tg.callback_answers[-1]["text"] == "✅ عضویتت تأیید شد؛ خوش اومدی!" and env.tg.callback_answers[-1]["show_alert"] == "false"
    assert {"chat_id": "111", "message_id": "1"} in env.tg.deleted  # پیامِ «اول عضو شو» جمع شد


def test_pressing_joined_before_joining_only_shows_an_alert(env):
    env.channels(TG_CHANNEL)
    env.start()
    env.tg.member_status["@shop_channel"] = "kicked"
    env.tg.push_message("111", "/start")
    env.wait(env.tg, "111", GATE)
    env.joined(env.tg, "111")
    assert wait_until(lambda: any("هنوز عضو نشدی" in a["text"] for a in env.tg.callback_answers))
    assert next(a for a in env.tg.callback_answers if "هنوز عضو نشدی" in a["text"])["show_alert"] == "true"
    assert WELCOME not in " ".join(env.tg.sent_to("111")) and len(env.tg.sent_to("111")) == 1
    assert env.engine.calls == []


def test_members_are_cached_but_start_and_the_join_button_always_recheck(env):
    env.channels(TG_CHANNEL)
    env.start()
    env.tg.push_message("111", "/start")
    env.wait(env.tg, "111", WELCOME)
    assert len(env.tg.chat_member_calls) == 1
    for text in ("سلام", "چه خبر", "قیمت‌ها؟"):
        env.tg.push_message("111", text)
    env.wait(env.tg, "111", "پاسخِ AI")
    assert wait_until(lambda: len(env.engine.calls) >= 1)
    assert len(env.tg.chat_member_calls) == 1  # کشِ ۱۰ دقیقه‌ای
    env.tg.push_message("111", "/start")
    assert wait_until(lambda: len(env.tg.chat_member_calls) == 2)  # /start بدونِ کش


def test_owner_and_active_admins_skip_the_gate(env):
    env.channels(TG_CHANNEL)
    env.start()
    env.tg.member_status["@shop_channel"] = "left"
    env.manager.admins.add_by_id("telegram", "701", "support", "سارا")
    env.tg.push_message(OWNER, "/start")
    env.wait(env.tg, OWNER, WELCOME)
    env.tg.push_message("701", "/start")
    env.wait(env.tg, "701", "دسترسیِ مدیریتِ تو فعال شد")  # اولین پیامِ مدیرِ «در انتظار» را پنل می‌گیرد و فعالش می‌کند
    env.tg.push_message("701", "/start")
    env.wait(env.tg, "701", WELCOME)  # از این به بعد مدیرِ فعال است ← معاف از دروازه
    assert GATE not in " ".join(env.tg.sent_to(OWNER) + env.tg.sent_to("701"))
    assert all(c["user_id"] not in (OWNER, "701") for c in env.tg.chat_member_calls)
    env.tg.push_message("555", "/start")  # مشتریِ عادی همچنان متوقف می‌شود
    env.wait(env.tg, "555", GATE)


def test_a_broken_channel_check_fails_open_and_tells_the_owner_exactly_once(env):
    env.channels(TG_CHANNEL)
    env.start()
    env.tg.chat_member_mode = "not_admin"  # ربات ادمینِ کانال نیست
    for chat in ("111", "112", "113"):
        env.tg.push_message(chat, "/start")
    for chat in ("111", "112", "113"):
        env.wait(env.tg, chat, WELCOME)  # قفل نشدند
    assert GATE not in " ".join(env.tg.sent_to("111"))
    alerts = lambda: [m for m in env.tg.sent_to(OWNER) if "بررسیِ عضویتِ کانالِ «کانال فروشگاه»" in m]  # noqa: E731
    assert wait_until(lambda: len(alerts()) == 1) and "ادمینِ کانال" in alerts()[0]
    assert [i.type for i in env.manager.attention.list_open()] == ["channel_check"]
    env.tg.push_message("114", "/start")
    env.wait(env.tg, "114", WELCOME)
    assert len(alerts()) == 1  # هشدارِ تکراری نه
    # درست شد ← ردیفِ «نیاز به توجه» خودش بسته می‌شود
    env.tg.chat_member_mode = "ok"
    env.tg.push_message("115", "/start")
    env.wait(env.tg, "115", WELCOME)
    assert wait_until(lambda: env.manager.attention.list_open() == [])


def test_scope_ai_gates_ai_chat_but_not_the_button_menu(env):
    env.channels(TG_CHANNEL, scope="ai")
    env.start()
    env.tg.member_status["@shop_channel"] = "left"
    env.tg.push_message("111", "/start")
    env.wait(env.tg, "111", WELCOME)  # منو آزاد
    env.tg.push_message("111", "یه سؤالِ آزاد دارم")
    env.wait(env.tg, "111", GATE)  # گفتگو با AI بسته
    assert env.engine.calls == []


def test_scope_shop_gates_the_menu_but_leaves_ai_only_chat_open(env):
    env.channels(TG_CHANNEL, scope="shop")
    env.settings.shop_mode = "shop_ai"  # بدونِ دکمه: همه‌چیز گفتگو با AI
    env.start()
    env.tg.member_status["@shop_channel"] = "left"
    env.tg.push_message("111", "سلام")
    env.wait(env.tg, "111", "پاسخِ AI")  # AI جواب داد؛ دروازه‌ای نبود
    assert env.tg.chat_member_calls == []
    env.settings.shop_mode = "shop_buttons"
    env.tg.push_message("112", "/start")
    env.wait(env.tg, "112", GATE)  # حالا منو دکمه‌ای است و دامنه‌ی «shop» اعمال می‌شود


def test_scope_ai_gates_the_ai_only_mode(env):
    env.channels(TG_CHANNEL, scope="ai")
    env.settings.shop_mode = "shop_ai"
    env.start()
    env.tg.member_status["@shop_channel"] = "left"
    env.tg.push_message("111", "سلام")
    env.wait(env.tg, "111", GATE)
    assert env.engine.calls == []


def test_bale_users_are_checked_on_bale_against_bale_channels_only(env):
    tg_channel = {"platform": "telegram", "channel": "@tg_channel"}
    env.channels(tg_channel, BALE_CHANNEL)
    env.start()
    env.bale.member_status["@bale_channel"] = "left"
    env.bale.push_message("221", "/start")
    env.wait(env.bale, "221", GATE)
    assert env.bale.buttons_to("221")[0] == ("📢 کانال بله", "https://ble.ir/bale_channel")
    assert env.bale.chat_member_calls == [{"chat_id": "@bale_channel", "user_id": "221"}]
    env.tg.push_message("111", "/start")  # تلگرام: کانالِ خودش، و عضو است
    env.wait(env.tg, "111", WELCOME)
    assert env.tg.chat_member_calls == [{"chat_id": "@tg_channel", "user_id": "111"}]
    env.bale.member_status["@bale_channel"] = "member"
    env.joined(env.bale, "221")
    env.wait(env.bale, "221", WELCOME)


def test_a_stalled_membership_check_times_out_and_lets_the_customer_in(env):
    env.channels(TG_CHANNEL)
    env.manager._membership_timeout = 0.3  # noqa: SLF001
    env.start()
    env.tg.chat_member_delay = 6  # سرورِ گیرکرده؛ بدونِ مهلت مشتری ۶ ثانیه معطل می‌ماند
    env.tg.member_status["@shop_channel"] = "left"
    env.tg.push_message("111", "/start")
    env.wait(env.tg, "111", WELCOME, timeout=3)  # fail-open بعد از مهلت
    assert wait_until(lambda: any("TimeoutError" in m for m in env.tg.sent_to(OWNER)))  # مالک می‌فهمد چرا


def test_every_required_channel_must_be_joined(env):
    env.channels(TG_CHANNEL, {"platform": "telegram", "channel": "@second_chan", "title": "دوم"})
    env.start()
    env.tg.member_status["@second_chan"] = "left"
    env.tg.push_message("111", "/start")
    env.wait(env.tg, "111", GATE)
    assert env.tg.buttons_to("111") == [("📢 دوم", "https://t.me/second_chan"), ("✅ عضو شدم", None)]  # فقط کانالِ مانده


def test_turning_the_gate_off_lets_everyone_in_at_once(env):
    env.channels(TG_CHANNEL)
    env.start()
    env.tg.member_status["@shop_channel"] = "left"
    env.tg.push_message("111", "/start")
    env.wait(env.tg, "111", GATE)
    env.settings.required_channels_enabled = False
    env.tg.push_message("111", "/start")
    env.wait(env.tg, "111", WELCOME)
    env.joined(env.tg, "111")  # دکمه‌ی قدیمی با دروازه‌ی خاموش: فقط ادامه، بی‌خطا
    assert wait_until(lambda: len(env.tg.callback_answers) >= 1)


def test_the_access_test_reports_whether_the_bot_is_an_admin_of_the_channel(env):
    env.start()
    env.tg.member_status["@shop_channel"] = "administrator"
    ok, detail = env.manager.test_channel_sync("telegram", "@shop_channel")
    assert (ok, detail) == (True, "administrator") and env.tg.chat_member_calls[-1]["user_id"] == "123456789"  # شناسه‌ی عددیِ خودِ ربات
    env.tg.chat_member_mode = "no_chat"
    ok, detail = env.manager.test_channel_sync("telegram", "@shop_channel")
    assert ok is False and "chat not found" in detail
    env.manager.stop()
    with pytest.raises(BotManagerError, match="خاموشن"):
        env.manager.test_channel_sync("telegram", "@shop_channel")


# ====================================================================== N7: پیامِ همگانی ====


def test_stop_and_start_toggle_the_broadcast_opt_out_and_never_reach_the_ai(env):
    env.start()
    env.tg.push_message("111", "/start")
    env.wait(env.tg, "111", WELCOME)
    env.tg.push_message("111", "/stop")
    env.wait(env.tg, "111", "دیگه پیامِ همگانی برات نمی‌فرستیم")
    assert env.customers.get("telegram", "111").opted_out
    assert env.manager.broadcasts.summary(bc.Audience()).total == 0
    env.tg.push_message("111", "/start")
    env.wait(env.tg, "111", "دوباره پیام‌های همگانی برات فعال شد")
    assert not env.customers.get("telegram", "111").opted_out and env.manager.broadcasts.summary(bc.Audience()).total == 1
    env.tg.push_message("111", "/start")  # بارِ دوم: دیگر خطِ «فعال شد» نه
    env.wait(env.tg, "111", WELCOME)
    assert sum("فعال شد" in m for m in env.tg.sent_to("111")) == 1 and env.engine.calls == []


def test_a_broadcast_reaches_both_platforms_with_the_footer_and_skips_stopped_and_blocked(env):
    env.start()
    for chat in ("111", "112", "113"):
        env.tg.push_message(chat, "/start")
        env.wait(env.tg, chat, WELCOME)
    for chat in ("221", "222"):
        env.bale.push_message(chat, "/start")
        env.wait(env.bale, chat, WELCOME)
    env.tg.push_message("112", "/stop")
    env.wait(env.tg, "112", "دیگه پیامِ همگانی")
    env.manager.store.set_blocked("telegram", "113", True)
    bid = env.manager.broadcasts.start(bc.Content("تخفیفِ ویژه‌ی آخرِ هفته"), bc.Audience())
    env.done(bid)
    for server, chat in ((env.tg, "111"), (env.bale, "221"), (env.bale, "222")):
        assert got(server, chat, "تخفیفِ ویژه‌ی آخرِ هفته") and got(server, chat, "/stop"), (chat, server.sent_to(chat))
    assert not got(env.tg, "112", "تخفیفِ ویژه") and not got(env.tg, "113", "تخفیفِ ویژه")
    counts = env.manager.broadcasts.store.get(bid).counts
    assert counts["sent"] == 3 and counts["pending"] == 0 and counts["failed"] == 0
    assert wait_until(lambda: any("تموم شد" in m and "3 رسید" in m for m in env.tg.sent_to(OWNER)))  # خلاصه برای مالک
    assert env.manager.attention.list_open() == []


def test_a_broadcast_survives_a_blocked_user_and_a_rate_limit(env):
    env.start()
    for chat in ("111", "112", "113"):
        env.tg.push_message(chat, "/start")
        env.wait(env.tg, chat, WELCOME)
    env.tg.send_failures["112"] = (403, "Forbidden: bot was blocked by the user")
    env.tg.flood_sends, env.tg.flood_retry_after = 1, 1
    env.tg.send_log.clear()
    bid = env.manager.broadcasts.start(bc.Content("پیامِ همگانی"), bc.Audience())
    env.done(bid, timeout=30)
    b = env.manager.broadcasts.store.get(bid)
    assert b.counts["sent"] == 2 and b.counts["unreachable"] == 1 and b.counts["failed"] == 0
    assert env.customers.get("telegram", "112").unreachable and not env.customers.get("telegram", "111").unreachable
    assert "fail:429" in [r for _c, r in env.tg.send_log]  # ۴۲۹ دیده شد و موتور صبر کرد
    assert got(env.tg, "111", "پیامِ همگانی") and got(env.tg, "113", "پیامِ همگانی") and not got(env.tg, "112", "پیامِ همگانی")
    assert sum(1 for c, r in env.tg.send_log if c == "112") == 1  # به بلاک‌کرده فقط یک بار تلاش شد


def test_a_broadcast_queued_while_the_bots_are_off_is_delivered_after_they_start(env):
    env.mark("telegram", "111")
    env.mark("bale", "221")
    bid = env.manager.broadcasts.start(bc.Content("ماندگار"), bc.Audience())
    assert env.manager.broadcasts.store.get(bid).status == "running" and not env.tg.sent_to("111")
    env.start()
    env.done(bid)
    assert got(env.tg, "111", "ماندگار") and got(env.bale, "221", "ماندگار")


def test_the_test_broadcast_goes_only_to_the_owner_and_never_creates_a_queue(env):
    env.start()
    env.mark("telegram", "111")
    results = env.manager.broadcast_test_sync(bc.Content("پیامِ آزمایشی", button_label="ببین", button_url="https://example.com/o"))
    assert results == [("telegram", True, "")]
    env.wait(env.tg, OWNER, "پیامِ آزمایشی")
    assert "/stop" in env.tg.sent_to(OWNER)[-1]
    assert env.tg.last_message(OWNER)["reply_markup"]["inline_keyboard"][0][0]["url"] == "https://example.com/o"
    assert not env.tg.sent_to("111") and env.manager.broadcasts.history() == []
    env.settings.owner_chats = {}
    with pytest.raises(bc.BroadcastError, match="مالک"):
        env.manager.broadcast_test_sync(bc.Content("x"))


def test_photo_and_button_broadcast_on_both_platforms(env, tmp_path):
    photo = tmp_path / "promo.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xe0 fake")
    env.start()
    env.tg.push_message("111", "/start")
    env.bale.push_message("221", "/start")
    env.wait(env.tg, "111", WELCOME)
    env.wait(env.bale, "221", WELCOME)
    bid = env.manager.broadcasts.start(bc.Content("با عکس", photo=str(photo), button_label="ببین", button_url="https://example.com/offer"), bc.Audience())
    env.done(bid)
    for server, chat in ((env.tg, "111"), (env.bale, "221")):
        entry = [m for m in server.sent if m["chat_id"] == chat and m["kind"] == "sendPhoto"]
        assert len(entry) == 1 and entry[0]["text"].startswith("با عکس") and "/stop" in entry[0]["text"], (chat, server.sent)
        assert entry[0]["reply_markup"]["inline_keyboard"][0][0]["url"] == "https://example.com/offer"


def test_a_missing_photo_pauses_the_broadcast_and_the_owner_is_told(env, tmp_path):
    photo = tmp_path / "p.png"
    photo.write_bytes(b"x")
    env.mark("telegram", "111")
    bid = env.manager.broadcasts.start(bc.Content("متن", photo=str(photo)), bc.Audience())
    photo.unlink()
    env.start()
    assert wait_until(lambda: env.manager.broadcasts.store.status_of(bid) == "paused")
    assert wait_until(lambda: any("فایلِ عکسِ پیام پیدا نشد" in m for m in env.tg.sent_to(OWNER)))
    assert [i.type for i in env.manager.attention.list_open()] == ["broadcast"] and not env.tg.sent_to("111")
    env.manager.broadcasts.cancel(bid)  # لغو = هشدار هم بسته می‌شود
    assert env.manager.attention.list_open() == []


# ================================================================= N6: پیامِ شخصیِ مالک ====


def test_an_owner_message_reaches_the_customer_and_the_ai_later_sees_it_as_a_shop_message(env):
    env.start()
    env.tg.push_message("111", "/start")
    env.wait(env.tg, "111", WELCOME)
    env.manager.send_to_customer_sync("telegram", "111", "  سفارشت فردا ارسال می‌شه \x00 ")
    assert env.tg.sent_to("111")[-1] == "💬 فروشگاه: سفارشت فردا ارسال می‌شه"
    stored = env.manager.store.get_messages("telegram", "111")
    assert (stored[-1].role, stored[-1].content) == ("owner", "سفارشت فردا ارسال می‌شه")
    env.tg.push_message("111", "پس کی می‌رسه؟")
    assert wait_until(lambda: env.engine.calls)
    history = env.engine.calls[-1]["history"]
    assert any(h.role == "assistant" and h.content == "[فروشگاه] سفارشت فردا ارسال می‌شه" for h in history)
    assert not any(h.role == "owner" for h in history)  # نقشِ ناشناس هرگز به موتورِ AI نمی‌رسد


@pytest.mark.parametrize("prepare, pattern", [
    (lambda e: e.manager.store.set_blocked("telegram", "111", True), "بلاک شده"),
    (lambda e: e.customers.set_opted_out("telegram", "111"), "/stop"),
])
def test_personal_messages_are_refused_for_blocked_and_stopped_customers(env, prepare, pattern):
    env.start()
    env.tg.push_message("111", "/start")
    env.wait(env.tg, "111", WELCOME)
    before = list(env.tg.sent_to("111"))
    prepare(env)
    with pytest.raises(BotManagerError, match=pattern):
        env.manager.send_to_customer_sync("telegram", "111", "سلام شخصی")
    assert env.tg.sent_to("111") == before and "owner" not in [m.role for m in env.manager.store.get_messages("telegram", "111")]


def test_personal_message_validation_and_offline_bots(env):
    env.mark("telegram", "111")
    with pytest.raises(BotManagerError, match="خاموشن"):  # ربات‌ها هنوز روشن نشده‌اند
        env.manager.send_to_customer_sync("telegram", "111", "سلام")
    env.start()
    for bad, pattern in (("", "خالیه"), ("  \n\t\x00 ", "خالیه"), ("ا" * 3001, "بلنده")):
        with pytest.raises(BotManagerError, match=pattern):
            env.manager.send_to_customer_sync("telegram", "111", bad)
    env.manager.send_to_customer_sync("telegram", "111", "ا" * 3000)  # دقیقاً سقف
    assert wait_until(lambda: any(len(m) > 3000 for m in env.tg.sent_to("111")))


def test_a_customer_who_blocked_the_bot_is_flagged_unreachable_by_a_personal_message(env):
    env.start()
    env.tg.push_message("111", "/start")
    env.wait(env.tg, "111", WELCOME)
    env.tg.send_failures["111"] = (403, "Forbidden: bot was blocked by the user")
    with pytest.raises(BotManagerError, match="بلاک کرده"):
        env.manager.send_to_customer_sync("telegram", "111", "سلام شخصی")
    assert env.customers.get("telegram", "111").unreachable
    assert "owner" not in [m.role for m in env.manager.store.get_messages("telegram", "111")]  # نرسیده ← ثبت نمی‌شود
    del env.tg.send_failures["111"]
    with pytest.raises(BotManagerError, match="اتصال"):  # خطای غیرِ-۴۰۳ ← «اتصال را چک کن»
        env.tg.send_failures["111"] = (500, "Internal Server Error")
        env.manager.send_to_customer_sync("telegram", "111", "دوباره")


def test_a_personal_message_counts_as_the_answer_in_an_open_support_chat(env):
    env.start()
    env.tg.push_message("111", "/start")
    env.wait(env.tg, "111", WELCOME)
    handoff = env.manager._handoff  # noqa: SLF001
    assert handoff.open("telegram", "111", "علی")
    conn = env.manager.store.connection()
    conn.execute("UPDATE handoff_sessions SET last_activity_ts = 5 WHERE platform = 'telegram' AND chat_id = '111'")
    conn.commit()
    env.manager.send_to_customer_sync("telegram", "111", "الان جواب می‌دم")
    row = env.manager.store.connection().execute("SELECT last_activity_ts, status FROM handoff_sessions WHERE chat_id = '111'").fetchone()
    assert row["status"] == "open" and row["last_activity_ts"] > 5  # گفتگو زنده ماند و بسته‌شدنِ خودکار عقب رفت
