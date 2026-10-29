"""N7 — پیامِ همگانی: محتوا، مخاطب، قوانینِ سرویس، رفتارِ موتور (۴۰۳/۴۲۹/شبکه/توقف/لغو) و حریمِ خصوصی.
ساعت و sleep جعلی‌اند؛ هیچ انتظارِ واقعی‌ای نیست."""

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

from app.core import broadcast as bc
from app.core import conversations, shop_texts
from app.core.bale_client import BaleApiError
from app.core.bot_pipeline import IncomingMessage
from app.core.broadcast import Audience, BroadcastEngine, BroadcastError, BroadcastService, BroadcastStore, Content
from app.core.conversations import ConversationStore
from app.core.customers import CustomerStore
from app.core.orders import OrderStore
from app.core.products import ProductStore

NOW = 1_800_000_000
DAY = 86400


def run(coro):
    return asyncio.run(coro)


def msg(chat, platform="telegram", text="سلام", **kw):
    return IncomingMessage(platform=platform, chat_id=str(chat), display_name=kw.pop("display_name", ""), text=text, **kw)


def settings(**kw):
    base = dict(bot_language="auto", bot_texts={}, broadcast_daily_cap=3, broadcast_footer_enabled=True, broadcast_rate_telegram=20, broadcast_rate_bale=5)
    base.update(kw)
    return SimpleNamespace(**base)


class Clock:
    def __init__(self):
        self.t = 1000.0
        self.sleeps = []

    def mono(self):
        return self.t

    async def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds

    def waited(self):
        """مجموعِ صبرهای «تلاشِ دوباره» (بدونِ فاصله‌گذاریِ نرخ که زیرِ ۱ ثانیه است)."""
        return sum(s for s in self.sleeps if s >= 0.99)


class Rig:
    """مخزن‌ها + موتورِ ارسال با ``send`` جعلی که ترتیبِ تلاش‌ها را ثبت می‌کنه و خطای دلخواه می‌ریزه."""

    def __init__(self, tmp_path, **settings_kw):
        self.conv = ConversationStore(tmp_path / "conversations.db")
        self.orders = OrderStore(tmp_path / "orders.db", product_store=ProductStore(tmp_path / "products.db"))
        self.customers = CustomerStore(self.conv, self.orders)
        self.store = BroadcastStore(self.conv)
        self.settings = settings(**settings_kw)
        self.service = BroadcastService(self.store, self.customers, lambda: self.settings, clock=lambda: NOW)
        self.clock = Clock()
        self.attempts = []  # (platform, chat, text, photo, button) — هر تلاش
        self.delivered = []  # فقط موفق‌ها
        self.script = {}  # (platform, chat) → لیستِ [None | Exception] به‌ترتیبِ تلاش‌ها
        self.notes = []
        self.offline = set()
        self.after_send = None  # hook(platform, chat) بعد از هر تلاش
        self.engine = self.make_engine()

    def make_engine(self, **kw):
        async def send(platform, chat, text, photo, button):
            self.attempts.append((platform, chat, text, photo, button))
            seq = self.script.get((platform, chat))
            err = seq.pop(0) if seq else None
            if self.after_send:
                self.after_send(platform, chat)
            if err is not None:
                raise err
            self.delivered.append((platform, chat, text, photo, button))
            return "1"

        async def notify(text):
            self.notes.append(text)

        return BroadcastEngine(
            self.store, self.customers, lambda: self.settings, send, ready=lambda p: p not in self.offline, notify=notify,
            clock=lambda: NOW, mono=self.clock.mono, sleep=self.clock.sleep, **kw,
        )

    def add(self, chat, platform="telegram", **kw):
        now = kw.pop("now", NOW)
        self.customers.touch(msg(chat, platform, **kw), now=now)

    def start(self, content=None, audience=None):
        return self.service.start(content or Content("سلام به همه"), audience or Audience())

    def drain(self, rounds=80):
        for _ in range(rounds):
            run(self.engine.run_once())
            if not self.store.running_ids():
                return

    def counts(self, bid):
        return self.store.counts(bid)

    def chats(self, which=None):
        rows = self.delivered if which is None else which
        return sorted(c for _p, c, *_ in rows)


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def forbidden(text="Forbidden: bot was blocked by the user"):
    return type("TelegramForbiddenError", (Exception,), {})(text)


def retry_after(seconds):
    exc = type("TelegramRetryAfter", (Exception,), {})(f"Too Many Requests: retry after {seconds}")
    exc.retry_after = seconds
    return exc


def network(text="network down"):
    return type("TelegramNetworkError", (Exception,), {})(text)


# =============================================================================== محتوا ====


def test_empty_or_whitespace_text_is_rejected_and_control_chars_are_stripped():
    s = settings()
    for bad in ("", "   \n\t ", "\x00\x01"):
        with pytest.raises(BroadcastError, match="خالی"):
            bc.validate_content(Content(bad), s)
    assert bc.validate_content(Content("سلام\x00 دنیا\r\nخط دوم  "), s).text == "سلام دنیا\nخط دوم"


def test_length_limit_reserves_room_for_the_longest_footer():
    s = settings()
    reserve = 2 + max(len(shop_texts.default("broadcast.footer", lang)) for lang in ("fa", "en"))
    ok = "ا" * (bc.MAX_TEXT - reserve)
    assert bc.validate_content(Content(ok), s).text == ok
    with pytest.raises(BroadcastError, match="بلنده"):
        bc.validate_content(Content(ok + "ا"), s)
    assert len(bc.validate_content(Content("ا" * bc.MAX_TEXT, footer=False), s).text) == bc.MAX_TEXT  # بدونِ پانویس، کلِ سقف


def test_photo_messages_use_the_caption_limit(tmp_path):
    s = settings()
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"x")
    reserve = 2 + max(len(shop_texts.default("broadcast.footer", lang)) for lang in ("fa", "en"))
    assert bc.validate_content(Content("ا" * (bc.MAX_CAPTION - reserve), photo=str(photo)), s)
    with pytest.raises(BroadcastError, match="عکس‌دار"):
        bc.validate_content(Content("ا" * (bc.MAX_CAPTION - reserve + 1), photo=str(photo)), s)


@pytest.mark.parametrize("label, url, ok", [
    ("ببین", "https://example.com/offer", True),
    ("ببین", "http://example.com", True),
    ("ببین", "", False), ("", "https://example.com", False),
    ("x" * 29, "https://example.com", False), ("x" * 28, "https://example.com", True),
    ("ببین", "javascript:alert(1)", False), ("ببین", "tel:+98912", False), ("ببین", "example.com", False),
    ("ببین", "https://example.com/" + "a" * bc.MAX_URL, False),
])
def test_button_needs_both_parts_a_short_label_and_an_http_link(label, url, ok):
    content = Content("متن", button_label=label, button_url=url)
    if ok:
        assert bc.validate_content(content, settings()).button == (label, url)
    else:
        with pytest.raises(BroadcastError):
            bc.validate_content(content, settings())


def test_photo_must_exist_be_small_and_an_allowed_type(tmp_path):
    s = settings()
    big = tmp_path / "big.png"
    big.write_bytes(b"x" * (bc.MAX_PHOTO_BYTES + 1))
    gif = tmp_path / "a.gif"
    gif.write_bytes(b"x")
    for photo, pattern in ((str(tmp_path / "missing.jpg"), "پیدا نشد"), (str(big), "حجم"), (str(gif), "فرمت"), ("bad\x00name.jpg", "")):
        with pytest.raises(BroadcastError, match=pattern or "."):
            bc.validate_content(Content("متن", photo=photo), s)


def test_store_photo_copies_into_the_data_dir_and_validates(tmp_path, monkeypatch):
    monkeypatch.setattr(bc, "get_app_data_dir", lambda: tmp_path / "data")
    src = tmp_path / "promo.JPG"
    src.write_bytes(b"jpegdata")
    copied = bc.store_photo(str(src))
    assert copied.startswith(str(tmp_path / "data" / "broadcast_media")) and copied.endswith(".jpg")
    src.unlink()  # فایلِ اصلی جابه‌جا شد ← نسخه‌ی ما سالم می‌ماند
    assert open(copied, "rb").read() == b"jpegdata"
    bc.delete_photo(copied)
    assert not tmp_path.joinpath(copied).exists()
    bc.delete_photo("")  # بی‌خطر
    for bad in (str(tmp_path / "nope.jpg"), str(tmp_path / "x.gif"), "bad\x00.jpg"):
        with pytest.raises(BroadcastError):
            bc.store_photo(bad)


def test_compose_uses_the_recipients_language_and_the_owners_footer_override():
    s = settings()
    content = Content("متن")
    assert bc.compose(content, s, "fa") == "متن\n\n" + shop_texts.default("broadcast.footer", "fa")
    assert bc.compose(content, s, "en") == "متن\n\n" + shop_texts.default("broadcast.footer", "en")
    assert bc.compose(Content("متن", footer=False), s, "fa") == "متن"
    shop_texts.set_override(s, "broadcast.footer", "fa", "برای لغو /stop")
    assert bc.compose(content, s, "fa") == "متن\n\nبرای لغو /stop"


# =============================================================================== مخاطب ====


def build_crowd(rig):
    c = rig.customers
    rig.add(1, language_code="fa")  # عادی
    rig.add(2, language_code="en")  # عادی انگلیسی
    rig.add(3, platform="bale")  # بله
    rig.add(4)  # بلاک می‌شود
    rig.conv.ensure_conversation("telegram", "4")
    rig.conv.set_blocked("telegram", "4", True)
    rig.add(5)
    c.set_opted_out("telegram", "5")
    rig.add(6)
    c.mark_unreachable("telegram", "6")
    c.touch(msg(7, text="", callback_data="x:y"), now=NOW)  # فقط کلیک (بدونِ پیام)
    return c


def test_recipients_never_include_blocked_opted_out_unreachable_or_never_messaged(rig):
    build_crowd(rig)
    got = bc.select_recipients(rig.customers, Audience(), now=NOW)
    assert sorted((c.platform, c.user_id) for c in got) == [("bale", "3"), ("telegram", "1"), ("telegram", "2")]


def test_filters_platform_purchase_activity_tag_and_language(rig):
    c = rig.customers
    rig.add(1, language_code="fa-IR", now=NOW)
    rig.add(2, language_code="en-US")
    rig.add(3, language_code="ru")
    rig.add(4, language_code="")
    rig.add(5, platform="bale", language_code="fa")
    # خرید: ۱ و ۵ خریدار
    for chat, platform in ((1, "telegram"), (5, "bale")):
        conn = rig.orders.connection()
        conn.execute("INSERT INTO orders (platform, chat_id, status, total_irr, created_at) VALUES (?, ?, 'confirmed', 1000, datetime(?, 'unixepoch'))", (platform, str(chat), NOW))
        conn.commit()
    c.set_tags("telegram", "2", "vip")
    ids = lambda aud, now=NOW: sorted(f"{x.platform[0]}{x.user_id}" for x in bc.select_recipients(c, aud, now=now))  # noqa: E731

    assert ids(Audience(platform="bale")) == ["b5"] and ids(Audience(platform="telegram")) == ["t1", "t2", "t3", "t4"]
    assert ids(Audience(purchase="buyers")) == ["b5", "t1"] and ids(Audience(purchase="no_orders")) == ["t2", "t3", "t4"]
    assert ids(Audience(tag="VIP")) == ["t2"]
    assert ids(Audience(language="fa")) == ["b5", "t1"] and ids(Audience(language="en")) == ["t2"] and ids(Audience(language="other")) == ["t3", "t4"]
    assert ids(Audience(purchase="buyers", language="fa", platform="telegram")) == ["t1"]  # ترکیبِ فیلترها = AND


def test_activity_filters_follow_last_and_first_seen(rig):
    c = rig.customers
    c.touch(msg(1), now=NOW - 40 * DAY)  # قدیمی (۴۰ روز پیش، اولین و آخرین)
    c.touch(msg(2), now=NOW - 20 * DAY)
    c.touch(msg(3), now=NOW - 3 * DAY)
    c.touch(msg(4), now=NOW - 40 * DAY)
    c.touch(msg(4), now=NOW - 1 * DAY)  # قدیمی ولی تازه فعال
    ids = lambda activity: sorted(x.user_id for x in bc.select_recipients(c, Audience(activity=activity), now=NOW))  # noqa: E731
    assert ids("active_7d") == ["3", "4"] and ids("active_30d") == ["2", "3", "4"]
    assert ids("inactive_30d") == ["1"] and ids("new_7d") == ["3"] and ids("all") == ["1", "2", "3", "4"]


def test_invalid_audience_values_are_rejected_and_json_round_trips_tolerantly():
    for bad in (Audience(platform="eitaa"), Audience(purchase="x"), Audience(activity="x"), Audience(language="de")):
        with pytest.raises(BroadcastError):
            bad.normalized()
    aud = Audience("bale", "buyers", "active_7d", "vip", "fa")
    assert Audience.from_json(aud.to_json()) == aud
    for garbage in ("", "not json", "[]", '{"platform":"eitaa"}', "null", '{"purchase": 5}'):
        assert Audience.from_json(garbage) == Audience()


def test_summary_counts_recipients_per_platform(rig):
    build_crowd(rig)
    s = rig.service.summary(Audience())
    assert s.total == 3 and s.per_platform == {"telegram": 2, "bale": 1}
    assert rig.service.summary(Audience(platform="bale")).per_platform == {"bale": 1}
    assert rig.service.summary(Audience(tag="none")).total == 0


# =============================================================================== سرویس ====


def test_start_snapshots_recipients_and_rejects_invalid_requests_without_side_effects(rig):
    build_crowd(rig)
    with pytest.raises(BroadcastError, match="خالی"):
        rig.service.start(Content(" "), Audience())
    with pytest.raises(BroadcastError, match="هیچ مشتریِ مجازی"):
        rig.service.start(Content("x"), Audience(tag="nobody"))
    assert rig.store.recent() == []  # هیچ ردیفی ساخته نشد
    bid = rig.start()
    b = rig.store.get(bid)
    assert b.status == "running" and b.total == 3 and b.counts["pending"] == 3 and b.text == "سلام به همه"
    rig.add(99)  # مشتریِ جدید بعد از شروع ← در این ارسال نیست
    assert rig.store.get(bid).total == 3


def test_only_one_active_broadcast_at_a_time(rig):
    rig.add(1)
    bid = rig.start()
    with pytest.raises(BroadcastError, match="در جریانه"):
        rig.start()
    rig.service.pause(bid)
    with pytest.raises(BroadcastError, match="در جریانه"):  # متوقف هم «فعال» است
        rig.start()
    rig.service.cancel(bid)
    rig.settings.broadcast_daily_cap = 5
    assert rig.start() > bid


def test_daily_cap_counts_every_started_broadcast_in_a_rolling_24h_window(tmp_path):
    rig = Rig(tmp_path)
    rig.add(1)
    now = {"t": NOW}
    rig.service = BroadcastService(rig.store, rig.customers, lambda: rig.settings, clock=lambda: now["t"])
    for _ in range(3):
        rig.service.cancel(rig.service.start(Content("x"), Audience()))  # لغو هم حساب می‌شود (دورزدنِ سقف با لغو ممکن نیست)
        now["t"] += 3600
    with pytest.raises(BroadcastError, match=r"سقف.*\(3\)"):
        rig.service.start(Content("x"), Audience())
    now["t"] = NOW + DAY + 10  # اولین ارسال از پنجره‌ی ۲۴ساعته بیرون رفت
    assert rig.service.start(Content("x"), Audience())


@pytest.mark.parametrize("raw, expected", [(0, 1), (-5, 1), (99, 50), ("7", 7), ("abc", 3), (None, 3), (2, 2)])
def test_daily_cap_is_clamped_and_garbage_falls_back_to_the_default(rig, raw, expected):
    rig.settings.broadcast_daily_cap = raw
    assert rig.service.cap() == expected


def test_status_transitions_are_guarded(rig):
    rig.add(1)
    bid = rig.start()
    assert rig.service.pause(bid) and not rig.service.pause(bid)  # دوباره pause نمی‌شود
    assert rig.service.resume(bid) and not rig.service.resume(bid)
    assert rig.service.cancel(bid) and not rig.service.cancel(bid)
    assert not rig.service.resume(bid) and rig.store.get(bid).status == "cancelled"
    assert not rig.store.set_status(bid, "bogus") and not rig.store.set_status(9999, "paused")
    assert rig.store.get(9999) is None and rig.store.status_of(9999) == ""


def test_cancel_skips_every_pending_recipient_with_a_reason(rig):
    for i in range(1, 5):
        rig.add(i)
    bid = rig.start()
    rig.service.cancel(bid)
    b = rig.store.get(bid)
    assert b.counts == {"pending": 0, "sent": 0, "failed": 0, "unreachable": 0, "skipped": 4} and b.finished_ts == NOW


def test_queue_survives_a_restart_and_a_second_connection_sees_the_same_state(tmp_path):
    rig = Rig(tmp_path)
    for i in range(1, 4):
        rig.add(i)
    bid = rig.start(Content("ماندگار", button_label="لینک", button_url="https://example.com"))
    rig.engine = rig.make_engine(batch=1)
    run(rig.engine.run_once())  # فقط یک گیرنده
    assert len(rig.delivered) == 1
    # «ری‌استارتِ برنامه»: همه‌چیز از نو، فقط همان فایلِ دیتابیس
    rig2 = Rig(tmp_path)
    b = rig2.store.get(bid)
    assert b.status == "running" and b.counts["sent"] == 1 and b.counts["pending"] == 2 and b.content.button == ("لینک", "https://example.com")
    rig2.drain()
    assert len(rig2.delivered) == 2 and rig2.store.get(bid).status == "done"
    assert sorted(rig.chats() + rig2.chats()) == ["1", "2", "3"]  # هیچ‌کس دوبار نه


# ================================================================================ موتور ====


def test_happy_path_sends_once_per_recipient_in_their_language_and_finishes_with_one_summary(rig):
    rig.add(1, language_code="fa")
    rig.add(2, language_code="en")
    rig.add(3, platform="bale", language_code="")
    bid = rig.start(Content("پیشنهاد ویژه", button_label="ببین", button_url="https://example.com/o"))
    rig.drain()
    assert rig.chats() == ["1", "2", "3"] and len(rig.attempts) == 3
    texts = {chat: text for _p, chat, text, _ph, _b in rig.delivered}
    assert texts["1"].endswith(shop_texts.default("broadcast.footer", "fa")) and texts["2"].endswith(shop_texts.default("broadcast.footer", "en"))
    assert all(b == ("ببین", "https://example.com/o") for *_x, b in rig.delivered)
    b = rig.store.get(bid)
    assert b.status == "done" and b.counts["sent"] == 3 and b.finished_ts == NOW
    assert len(rig.notes) == 1 and "تموم شد" in rig.notes[0] and "3 رسید" in rig.notes[0]
    assert run(rig.engine.run_once()) == 0 and len(rig.attempts) == 3 and len(rig.notes) == 1  # دوباره هیچ


def test_nothing_is_sent_to_people_who_blocked_opted_out_or_vanished_after_the_snapshot(rig):
    for i in range(1, 6):
        rig.add(i)
    bid = rig.start()
    rig.conv.ensure_conversation("telegram", "1")
    rig.conv.set_blocked("telegram", "1", True)  # مالک بلاک کرد
    rig.customers.set_opted_out("telegram", "2")  # /stop زد
    rig.customers.delete("telegram", "3")  # /forget
    rig.customers.mark_unreachable("telegram", "4")
    rig.drain()
    assert rig.chats() == ["5"]
    errors = {chat: err for chat, err in rig.conv.connection().execute("SELECT user_id, error FROM broadcast_log WHERE broadcast_id = ?", (bid,))}
    assert errors == {"1": "blocked", "2": "opted_out", "3": "forgotten", "4": "unreachable", "5": ""}
    assert rig.store.get(bid).counts["skipped"] == 4


def test_a_stop_sent_in_the_middle_of_a_broadcast_takes_effect_for_the_rest(rig):
    for i in range(1, 7):
        rig.add(i)
    rig.start()
    rig.engine = rig.make_engine(batch=2)
    run(rig.engine.run_once())
    assert rig.chats() == ["1", "2"] or len(rig.delivered) == 2
    already = {c for _p, c, *_ in rig.delivered}
    victim = next(str(i) for i in range(1, 7) if str(i) not in already)
    rig.customers.set_opted_out("telegram", victim)
    rig.drain()
    assert victim not in {c for _p, c, *_ in rig.delivered} and len(rig.delivered) == 5


def test_blocked_by_the_user_marks_unreachable_and_the_broadcast_continues(rig):
    for i in (1, 2, 3):
        rig.add(i)
    bid = rig.start()
    rig.script[("telegram", "2")] = [forbidden()]
    rig.drain()
    b = rig.store.get(bid)
    assert b.counts["sent"] == 2 and b.counts["unreachable"] == 1 and b.status == "done"
    assert rig.customers.get("telegram", "2").unreachable and not rig.customers.get("telegram", "1").unreachable
    assert len([a for a in rig.attempts if a[1] == "2"]) == 1  # یک بار هم دوباره امتحان نشد
    assert rig.store.errors(bid) == [("TelegramForbiddenError: Forbidden: bot was blocked by the user", 1)]


def test_bale_403_and_chat_not_found_are_unreachable_too(rig):
    for i in (1, 2):
        rig.add(i, platform="bale")
    bid = rig.start()
    rig.script[("bale", "1")] = [BaleApiError("بله خطا برگردوند: Forbidden", error_code=403)]
    rig.script[("bale", "2")] = [BaleApiError("بله خطا برگردوند: Bad Request: chat not found", error_code=400)]
    rig.drain()
    assert rig.store.get(bid).counts["unreachable"] == 2


def test_rate_limit_waits_the_requested_time_and_retries_the_same_recipient_without_burning_attempts(rig):
    for i in (1, 2, 3):
        rig.add(i)
    bid = rig.start()
    rig.script[("telegram", "1")] = [retry_after(3)]
    rig.drain()
    assert rig.chats() == ["1", "2", "3"] and rig.store.get(bid).counts["sent"] == 3
    assert [a[1] for a in rig.attempts].count("1") == 2  # یک ۴۲۹ + یک موفق
    assert rig.clock.waited() == 3.0
    assert rig.conv.connection().execute("SELECT MAX(attempts) FROM broadcast_log").fetchone()[0] == 0  # تلاشِ ۴۲۹ حساب نمی‌شود


def test_bale_429_uses_its_retry_after_and_defaults_to_five_seconds(rig):
    rig.add(1, platform="bale")
    rig.add(2, platform="bale")
    rig.start()
    rig.script[("bale", "1")] = [BaleApiError("x", error_code=429, retry_after=2.0)]
    rig.script[("bale", "2")] = [BaleApiError("x", error_code=429)]
    rig.drain()
    assert len(rig.delivered) == 2 and rig.clock.waited() == 2.0 + 5.0


def test_repeated_rate_limits_halve_that_platforms_rate_but_not_the_other(rig):
    for i in range(1, 4):
        rig.add(i)
    rig.add(10, platform="bale")
    rig.start()
    rig.script[("telegram", "1")] = [retry_after(1), retry_after(1), retry_after(1)]
    rig.drain()
    assert rig.engine._pacers["telegram"].rate == 10.0  # noqa: SLF001 — ۲۰ ← ۱۰ بعد از ۳ بار
    assert rig.engine._pacers["bale"].rate == 5.0  # noqa: SLF001


def test_the_rate_is_clamped_per_platform_and_garbage_uses_defaults(rig):
    for platform, raw, expected in (("telegram", 100, 25.0), ("telegram", 0, 1.0), ("telegram", "abc", 20.0), ("bale", 50, 10.0), ("bale", 3, 3.0), ("bale", None, 5.0)):
        setattr(rig.settings, f"broadcast_rate_{platform}", raw)
        assert rig.make_engine()._rate(platform) == expected, (platform, raw)  # noqa: SLF001


def test_pacing_keeps_the_configured_gap_between_sends(rig):
    rig.settings.broadcast_rate_telegram = 5
    for i in range(1, 7):
        rig.add(i)
    rig.start()
    times = []
    rig.after_send = lambda *_a: times.append(rig.clock.t)
    rig.drain()
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert len(times) == 6 and all(abs(g - 0.2) < 1e-9 for g in gaps)


def test_pacer_unit_behaviour():
    clock = Clock()
    pacer = bc.Pacer(10, clock=clock.mono, sleep=clock.sleep)
    for _ in range(3):
        run(pacer.wait())
    assert clock.sleeps == [pytest.approx(0.1), pytest.approx(0.1)]  # اولی بدونِ صبر
    pacer.slow_down()
    pacer.slow_down()
    assert pacer.rate == 2.5
    for _ in range(10):
        pacer.slow_down()
    assert pacer.rate == 1.0 and bc.Pacer(0).rate == 0.5


def test_transient_errors_retry_with_backoff_then_succeed(rig):
    rig.add(1)
    rig.add(2)
    bid = rig.start()
    rig.script[("telegram", "1")] = [network(), network()]
    rig.drain()
    assert rig.chats() == ["1", "2"] and rig.store.get(bid).counts["sent"] == 2
    assert [a[1] for a in rig.attempts].count("1") == 3 and rig.clock.waited() == 2.0 + 4.0


def test_a_recipient_that_keeps_failing_on_the_network_is_marked_failed_after_three_attempts(rig):
    rig.add(1)
    rig.add(2)
    bid = rig.start()
    rig.script[("telegram", "1")] = [network("a"), network("b"), network("c"), network("d")]
    rig.drain()
    b = rig.store.get(bid)
    assert b.counts["failed"] == 1 and b.counts["sent"] == 1 and [a[1] for a in rig.attempts].count("1") == 3
    assert rig.store.errors(bid)[0][0].startswith("TelegramNetworkError: c")


def test_a_network_outage_pauses_the_whole_broadcast_instead_of_failing_everyone(rig):
    for i in range(1, 9):
        rig.add(i)
    bid = rig.start()
    for i in range(1, 9):
        rig.script[("telegram", str(i))] = [network()] * 10
    rig.drain()
    b = rig.store.get(bid)
    assert b.status == "paused" and b.counts["sent"] == 0 and b.counts["failed"] <= 1 and b.counts["pending"] >= 7
    assert len(rig.notes) == 1 and "اتصال" in rig.notes[0] and f"#{bid}" in rig.notes[0]
    before = len(rig.attempts)
    assert run(rig.engine.run_once()) == 0 and len(rig.attempts) == before  # متوقف = هیچ ارسالی
    rig.script.clear()
    assert rig.service.resume(bid)
    rig.drain()
    assert rig.store.get(bid).status == "done" and rig.store.get(bid).counts["sent"] >= 7


def test_unexpected_status_and_garbage_errors_are_permanent_failures_and_a_streak_pauses(rig):
    for i in range(1, 9):
        rig.add(i)
    bid = rig.start(Content("متن", button_label="ببین", button_url="https://example.com"))
    for i in range(1, 9):
        rig.script[("telegram", str(i))] = [ValueError("Bad Request: BUTTON_URL_INVALID")]
    rig.drain()
    b = rig.store.get(bid)
    assert b.status == "paused" and b.counts["failed"] == bc.FAILED_PAUSE_AFTER and b.counts["pending"] == 3
    assert len(rig.notes) == 1 and "BUTTON_URL_INVALID" in rig.notes[0] and "لغو" in rig.notes[0]


def test_a_few_permanent_failures_do_not_pause_and_a_success_resets_the_streak(rig):
    for i in range(1, 12):
        rig.add(i)
    bid = rig.start()
    for i in (1, 2, 3, 4, 6, 7, 8, 9):  # ۴ تا، موفق، ۴ تا
        rig.script[("telegram", str(i))] = [ValueError("Bad Request: wrong file")]
    rig.drain()
    b = rig.store.get(bid)
    assert b.status == "done" and b.counts["failed"] == 8 and b.counts["sent"] == 3


def test_pause_in_the_middle_of_a_batch_stops_before_the_next_send_and_resume_completes(rig):
    for i in range(1, 7):
        rig.add(i)
    bid = rig.start()
    rig.after_send = lambda p, c: rig.service.pause(bid) if len(rig.attempts) == 2 else None
    run(rig.engine.run_once())
    assert len(rig.attempts) == 2 and rig.store.get(bid).status == "paused"
    run(rig.engine.run_once())
    assert len(rig.attempts) == 2  # در حالتِ pause هیچ
    rig.after_send = None
    rig.service.resume(bid)
    rig.drain()
    assert rig.chats() == ["1", "2", "3", "4", "5", "6"]


def test_cancel_in_the_middle_stops_everything_and_skips_the_rest(rig):
    for i in range(1, 7):
        rig.add(i)
    bid = rig.start()
    rig.after_send = lambda p, c: rig.service.cancel(bid) if len(rig.attempts) == 3 else None
    rig.drain()
    b = rig.store.get(bid)
    assert len(rig.attempts) == 3 and b.status == "cancelled" and b.counts["sent"] == 3 and b.counts["skipped"] == 3 and rig.notes == []


def test_an_offline_platform_never_starves_the_other_and_the_broadcast_waits_for_it(rig):
    for i in range(1, 6):
        rig.add(i, platform="bale")  # اول در صف (ترتیبِ درج)
    for i in range(10, 13):
        rig.add(i, platform="telegram")
    rig.engine = rig.make_engine(batch=2)  # دسته‌ی کوچک‌تر از تعدادِ ردیف‌های بله
    bid = rig.start()
    rig.offline = {"bale"}
    for _ in range(10):
        run(rig.engine.run_once())
    b = rig.store.get(bid)
    assert sorted(c for _p, c, *_ in rig.delivered) == ["10", "11", "12"] and b.counts["pending"] == 5
    assert b.status == "running" and rig.notes == []  # تمام نشده؛ منتظرِ بله
    rig.offline = set()
    rig.drain()
    assert rig.store.get(bid).status == "done" and len(rig.delivered) == 8


def test_a_missing_photo_pauses_instead_of_failing_every_recipient(rig, tmp_path):
    rig.add(1)
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"x")
    bid = rig.start(Content("متن", photo=str(photo)))
    photo.unlink()
    rig.drain()
    assert rig.store.get(bid).status == "paused" and rig.attempts == [] and "عکس" in rig.notes[0]


def test_photo_and_button_reach_the_sender(rig, tmp_path):
    rig.add(1)
    photo = tmp_path / "p.png"
    photo.write_bytes(b"x")
    rig.start(Content("متن", photo=str(photo), button_label="خرید", button_url="https://example.com/b"))
    rig.drain()
    assert rig.delivered[0][3] == str(photo) and rig.delivered[0][4] == ("خرید", "https://example.com/b")


def test_a_failing_owner_notification_never_breaks_the_engine(rig):
    rig.add(1)

    async def broken(_text):
        raise RuntimeError("telegram down")

    rig.engine._notify = broken  # noqa: SLF001
    bid = rig.start()
    rig.drain()
    assert rig.store.get(bid).status == "done" and len(rig.delivered) == 1


def test_run_forever_survives_a_crash_in_a_round_and_stops_on_cancel(rig):
    rig.add(1)
    bid = rig.start()
    boom = {"n": 1}
    original = rig.store.running_ids

    def flaky():
        if boom["n"]:
            boom["n"] -= 1
            raise RuntimeError("db hiccup")
        return original()

    rig.store.running_ids = flaky

    async def yielding_sleep(_seconds):  # sleepِ جعلیِ Clock هرگز کنترل را پس نمی‌دهد؛ اینجا لازم است (مثلِ asyncio.sleep واقعی)
        await asyncio.sleep(0)

    rig.engine._sleep = yielding_sleep  # noqa: SLF001

    async def go():
        task = asyncio.create_task(rig.engine.run_forever(idle=0))
        for _ in range(200):
            await asyncio.sleep(0)
            if rig.store.status_of(bid) == "done":
                break
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    run(go())
    assert rig.store.status_of(bid) == "done" and len(rig.delivered) == 1


def test_auto_pause_raises_an_attention_alert_and_resume_cancel_or_finish_resolve_it(tmp_path):
    rig = Rig(tmp_path)
    alerts, resolved = [], []
    rig.engine = rig.make_engine(alert=lambda bid, why: alerts.append((bid, why)), resolved=resolved.append)
    rig.service = BroadcastService(rig.store, rig.customers, lambda: rig.settings, clock=lambda: NOW, on_resolved=resolved.append)
    for i in range(1, 9):
        rig.add(i)
        rig.script[("telegram", str(i))] = [ValueError("Bad Request: BUTTON_URL_INVALID")]
    bid = rig.start()
    rig.drain()
    assert rig.store.get(bid).status == "paused" and len(alerts) == 1 and alerts[0][0] == bid and "BUTTON_URL_INVALID" in alerts[0][1] and resolved == []
    assert rig.service.resume(bid) and resolved == [bid]  # ادامه ← هشدار بسته می‌شود
    rig.script.clear()
    rig.drain()
    assert rig.store.get(bid).status == "done" and resolved == [bid, bid]  # تمام‌شدن هم رفع می‌کند
    bid2 = rig.service.start(Content("دوم"), Audience()) if rig.service.cap() > 1 else None
    assert bid2 and rig.service.cancel(bid2) and resolved[-1] == bid2


def test_a_missing_photo_and_an_outage_also_alert_and_a_crashing_alert_callback_changes_nothing(tmp_path):
    rig = Rig(tmp_path)
    alerts = []

    def alert(bid, why):
        alerts.append(why)
        raise RuntimeError("inbox is down")  # خرابیِ هشدار نباید توقف را خراب کند

    rig.engine = rig.make_engine(alert=alert, resolved=lambda bid: 1 / 0)
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"x")
    rig.add(1)
    bid = rig.start(Content("متن", photo=str(photo)))
    photo.unlink()
    rig.drain()
    assert rig.store.get(bid).status == "paused" and alerts == ["فایلِ عکسِ پیام پیدا نشد"]
    rig.service.cancel(bid)
    for i in range(1, 9):
        rig.add(i)
        rig.script[("telegram", str(i))] = [network()] * 10
    rig.settings.broadcast_daily_cap = 9
    bid = rig.start()
    rig.drain()
    assert rig.store.get(bid).status == "paused" and alerts[-1] == "خطاهای پیاپیِ اتصال"


def test_rates_are_rebuilt_from_the_current_settings_between_broadcasts(tmp_path):
    rig = Rig(tmp_path)
    for i in range(1, 4):
        rig.add(i)
    rig.script[("telegram", "1")] = [retry_after(1)] * 3
    rig.start()
    rig.drain()
    assert rig.engine._pacers["telegram"].rate == 10.0  # noqa: SLF001 — کندیِ ۴۲۹ در همین ارسال
    run(rig.engine.run_once())  # بینِ دو ارسال: هیچ فعالی نیست ← نرخ‌ها پاک
    assert rig.engine._pacers == {} and rig.engine._rl_streak == {}  # noqa: SLF001
    rig.settings.broadcast_rate_telegram = 7
    rig.settings.broadcast_daily_cap = 5
    rig.start()
    rig.drain()
    assert rig.engine._pacers["telegram"].rate == 7.0  # noqa: SLF001 — تنظیمِ تازه بدونِ ری‌استارت اعمال شد


# ------------------------------------------------------------------- دسته‌بندیِ خطاها ====


class ClientOSError(OSError):
    pass


def named(name, *bases, **attrs):
    cls = type(name, bases or (Exception,), {})
    exc = cls("boom")
    for k, v in attrs.items():
        setattr(exc, k, v)
    return exc


@pytest.mark.parametrize("exc, expected", [
    (retry_after(7), ("rate_limit", 7.0)),
    (BaleApiError("x", error_code=429, retry_after=1.5), ("rate_limit", 1.5)),
    (BaleApiError("x", error_code=429), ("rate_limit", 5.0)),
    (forbidden(), ("unreachable", 0.0)),
    (BaleApiError("بله خطا برگردوند: Forbidden", error_code=403), ("unreachable", 0.0)),
    (BaleApiError("بله خطا برگردوند: Bad Request: chat not found", error_code=400), ("unreachable", 0.0)),
    (RuntimeError("Forbidden: user is deactivated"), ("unreachable", 0.0)),
    (network(), ("transient", 0.0)),
    (named("TelegramServerError"), ("transient", 0.0)),
    (asyncio.TimeoutError(), ("transient", 0.0)),
    (ConnectionResetError("reset"), ("transient", 0.0)),
    (ClientOSError("boom"), ("transient", 0.0)),
    (named("ClientConnectionError", type("ClientError", (Exception,), {})), ("transient", 0.0)),
    (BaleApiError("x", error_code=502), ("transient", 0.0)),
    (BaleApiError("اتصال به سرور بله ناموفق بود"), ("transient", 0.0)),
    (BaleApiError("بله خطا برگردوند: Bad Request: message is too long", error_code=400), ("failed", 0.0)),
    (named("TelegramBadRequest"), ("failed", 0.0)),
    (ValueError("whatever"), ("failed", 0.0)),
    (retry_after(-3), ("rate_limit", 5.0)),  # مقدارِ منفیِ خراب نادیده گرفته می‌شود
])
def test_classify_error(exc, expected):
    assert bc.classify_error(exc) == expected


# ====================================================================== حریمِ خصوصی ====


def test_forget_keeps_only_the_opt_out_marker_and_wipes_everything_else(rig):
    c = rig.customers
    rig.add(1, first_name="سارا", username="sara", phone="0912", language_code="fa")
    rig.add(2, first_name="علی")
    c.set_opted_out("telegram", "1")
    c.set_tags("telegram", "1", "vip")
    c.set_notes("telegram", "1", "یادداشت خصوصی")
    bid = rig.start(audience=Audience())  # ۲ فقط (۱ لغو کرده)
    rig.conv.forget_chat("telegram", "1")
    rig.conv.forget_chat("telegram", "2")
    tomb = c.get("telegram", "1")
    assert tomb is not None and tomb.opted_out and (tomb.first_name, tomb.last_name, tomb.username, tomb.phone, tomb.notes, tomb.language_code) == ("",) * 6
    assert tomb.tags == [] and tomb.msg_count == 0 and tomb.first_seen_ts == 0 and tomb.last_seen_ts == 0
    assert c.get("telegram", "2") is None  # لغو نکرده بود ← کاملاً پاک
    assert rig.conv.connection().execute("SELECT COUNT(*) FROM broadcast_log WHERE broadcast_id = ?", (bid,)).fetchone()[0] == 0
    # /forget ترکِ اشتراک را دور نمی‌زند: مشتری دوباره پیام داد، همچنان لغوکرده است
    rig.add(1)
    assert c.get("telegram", "1").opted_out and bc.select_recipients(c, Audience(), now=NOW) == []


def test_retention_keeps_opt_out_markers_and_prunes_old_broadcast_logs(tmp_path):
    rig = Rig(tmp_path)
    old = NOW - 400 * DAY
    rig.customers.touch(msg(1), now=old)
    rig.customers.touch(msg(2), now=old)
    rig.customers.set_opted_out("telegram", "1")
    conn = rig.conv.connection()
    conn.execute("INSERT INTO broadcasts (created_ts, started_ts, status, text) VALUES (1, 1, 'done', 'x')")
    conn.executemany("INSERT INTO broadcast_log (broadcast_id, platform, user_id, status, ts) VALUES (1, 'telegram', ?, ?, ?)",
                     [("a", "sent", 100), ("b", "pending", 0), ("c", "sent", 2_000_000_000)])
    conn.commit()
    rig.conv.purge_older_than(30)
    left = {r[0] for r in conn.execute("SELECT user_id FROM broadcast_log")}
    assert left == {"b", "c"}  # قدیمیِ ارسال‌شده پاک؛ در-انتظار و آینده دست‌نخورده
    assert rig.customers.get("telegram", "1") is not None and rig.customers.get("telegram", "1").opted_out
    assert rig.customers.get("telegram", "2") is None


def test_history_maps_the_owner_role_to_a_shop_message_for_the_ai(rig):
    rig.conv.ensure_conversation("telegram", "1")
    rig.conv.add_message("telegram", "1", "user", "سفارشم کی می‌رسه؟")
    rig.conv.add_message("telegram", "1", "owner", "فردا ارسال می‌شه")
    rig.conv.add_message("telegram", "1", "assistant", "باشه")
    hist = rig.conv.get_history("telegram", "1")
    assert [h.role for h in hist] == ["user", "assistant", "assistant"]
    assert hist[1].content == conversations.OWNER_NOTE + "فردا ارسال می‌شه"
    assert [m.role for m in rig.conv.get_messages("telegram", "1")] == ["user", "owner", "assistant"]  # UI نقشِ واقعی را می‌بیند


def test_migration_5_creates_the_tables_idempotently(tmp_path):
    path = tmp_path / "c.db"
    store = ConversationStore(path)
    store.connection()  # ConversationStore تنبل است؛ مهاجرت‌ها موقعِ اولین اتصال اجرا می‌شن
    conn = sqlite3.connect(path)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"broadcasts", "broadcast_log"} <= names
    assert len(conversations.MIGRATIONS) >= 5  # (۶ = ai_calls، فازِ ۵)
    ConversationStore(path)  # باز کردنِ دوباره خطا نمی‌دهد
    assert store.connection().execute("SELECT COUNT(*) FROM broadcasts").fetchone()[0] == 0
