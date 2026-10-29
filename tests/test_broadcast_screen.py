"""N7 — صفحه‌ی «پیامِ همگانی» (UI با Page جعلی؛ ارسالِ واقعی در test_phase3_e2e.py و موتور در test_broadcast.py پوشانده شده)."""

import asyncio
from pathlib import Path

import pytest
from fake_page import FakePage, collect_text, find, fire

from app import theme
from app.core import broadcast as bc
from app.core.bot_manager import BotManager, BotManagerError
from app.core.bot_pipeline import IncomingMessage
from app.core.conversations import ConversationStore
from app.core.settings import AppSettings
from app.screens import broadcast as screen


class StubRefresher:
    last = None

    def __init__(self, page, tick, interval=2.0):
        self.tick, self.stopped = tick, False
        StubRefresher.last = self

    def start(self):
        pass

    def stop(self):
        self.stopped = True


class Rig:
    def __init__(self, tmp_path, monkeypatch, running=False, lang="fa", customers=3):
        monkeypatch.setattr(screen, "LiveRefresher", StubRefresher)
        monkeypatch.setattr(bc, "get_app_data_dir", lambda: tmp_path / "data")
        self.tmp_path = tmp_path
        self.settings = AppSettings()
        self.store = ConversationStore(db_path=tmp_path / "c.db")
        self.manager = BotManager(self.settings, store=self.store, adapter_factories={}, log_dir=tmp_path)
        if running:
            self.manager._thread = type("T", (), {"is_alive": lambda self: True})()  # noqa: SLF001 — فقط شبیه‌سازیِ «روشن»
        self.saves = 0
        self.test_calls, self.test_result = [], [("telegram", True, "")]
        monkeypatch.setattr(self.manager, "broadcast_test_sync", self.fake_test)
        for i in range(1, customers + 1):
            self.customer("telegram" if i != 3 else "bale", str(i))
        self.page = FakePage()
        self.control, self.cleanup = screen.build(self.page, lang, self.settings, self.save, self.manager)

    def fake_test(self, content, timeout=30.0):
        self.test_calls.append(content)
        if isinstance(self.test_result, Exception):
            raise self.test_result
        return self.test_result

    def save(self):
        self.saves += 1

    def customer(self, platform, chat, **kw):
        self.manager.customers.touch(IncomingMessage(platform=platform, chat_id=chat, display_name="", text="سلام", **kw))

    def f(self, key):
        return find(self.control, key)

    def type(self, **fields):
        for key, value in fields.items():
            self.f(f"bc_{key}").value = value
            handler = self.f(f"bc_{key}").on_change
            if handler:
                handler(None)

    def pick(self, key, value):
        fire(self.f(f"bc_{key}"), "on_select", value)

    def click(self, key):
        fire(self.f(key), "on_click")

    def notice(self):
        n = self.f("bc_notice")
        return (n.value, n.color) if n.visible else ("", None)

    def tick(self):
        StubRefresher.last.tick()

    def history_text(self):
        return collect_text(self.f("bc_history"))


@pytest.fixture
def rig(tmp_path, monkeypatch):
    r = Rig(tmp_path, monkeypatch)
    yield r
    r.cleanup()


def test_initial_state_shows_recipients_empty_history_and_the_bots_off_banner(rig):
    assert "گیرندگان: 3 نفر" in rig.f("bc_who").value and "تلگرام 2" in rig.f("bc_who").value and "بله 1" in rig.f("bc_who").value
    assert "هنوز پیامِ همگانی نفرستاده‌ای" in rig.history_text()
    assert rig.f("bc_bots_off").visible is True and rig.f("bc_confirm_row").visible is False
    assert rig.f("bc_footer").value is True  # پیش‌فرضِ تنظیمات


def test_the_banner_is_hidden_when_the_bots_run(tmp_path, monkeypatch):
    r = Rig(tmp_path, monkeypatch, running=True)
    assert r.f("bc_bots_off").visible is False
    r.cleanup()


def test_no_eligible_customers_is_called_out_in_red(tmp_path, monkeypatch):
    r = Rig(tmp_path, monkeypatch, customers=0)
    assert r.f("bc_who").value == "با این فیلترها هیچ مشتریِ مجازی نیست." and r.f("bc_who").color == theme.DANGER
    r.cleanup()


def test_audience_filters_update_the_live_count(rig):
    rig.manager.store.ensure_conversation("telegram", "1")  # در برنامه‌ی واقعی هر مشتری گفتگو دارد؛ بلاک روی همان ردیف است
    rig.manager.store.set_blocked("telegram", "1", True)
    rig.type(tag="")  # بازآوریِ شمارش
    assert "گیرندگان: 2 نفر" in rig.f("bc_who").value
    rig.pick("platform", "bale")
    assert rig.f("bc_who").value.startswith("گیرندگان: 1 نفر") and "(" not in rig.f("bc_who").value  # تک‌پلتفرم: بدونِ تفکیک
    rig.pick("platform", "all")
    rig.manager.customers.set_tags("telegram", "2", "vip")
    rig.type(tag="vip")
    assert rig.f("bc_who").value.startswith("گیرندگان: 1 نفر")
    rig.type(tag="nobody")
    assert rig.f("bc_who").color == theme.DANGER
    rig.type(tag="")
    rig.pick("purchase", "buyers")
    assert rig.f("bc_who").color == theme.DANGER  # هیچ خریداری نیست
    rig.pick("purchase", "all")
    rig.pick("language", "en")
    assert rig.f("bc_who").color == theme.DANGER and "هیچ مشتری" in rig.f("bc_who").value


def test_preview_follows_the_text_the_footer_switch_and_the_button(rig):
    assert "بنویس تا اینجا ببینی" in collect_text(rig.f("bc_preview"))
    rig.type(text="تخفیفِ ویژه")
    shown = collect_text(rig.f("bc_preview"))
    assert "تخفیفِ ویژه" in shown and "/stop" in shown
    rig.f("bc_footer").value = False
    rig.f("bc_footer").on_change(None)
    assert "/stop" not in collect_text(rig.f("bc_preview"))
    rig.type(button_label="ببین")
    assert "ببین" in collect_text(rig.f("bc_preview"))


@pytest.mark.parametrize("fields, pattern", [
    ({"text": ""}, "خالی"),
    ({"text": "   "}, "خالی"),
    ({"text": "متن", "button_label": "فقط عنوان"}, "عنوان و هم لینک"),
    ({"text": "متن", "button_label": "x", "button_url": "javascript:alert(1)"}, "http"),
    ({"text": "ا" * 3600}, "بلنده"),
])
def test_start_validates_before_asking_for_confirmation(rig, fields, pattern):
    rig.type(**fields)
    rig.click("bc_start")
    value, color = rig.notice()
    assert pattern in value and color == theme.DANGER and rig.f("bc_confirm_row").visible is False
    assert rig.manager.broadcasts.history() == []


def test_start_with_nobody_to_send_to_is_refused(tmp_path, monkeypatch):
    r = Rig(tmp_path, monkeypatch, customers=0)
    r.type(text="متن")
    r.click("bc_start")
    assert "هیچ مشتریِ مجازی" in r.notice()[0] and r.f("bc_confirm_row").visible is False
    r.cleanup()


def test_two_step_start_creates_one_running_broadcast_and_clears_the_form(rig):
    rig.type(text="تخفیفِ آخرِ هفته", button_label="ببین", button_url="https://example.com/o")
    rig.click("bc_start")
    assert rig.f("bc_confirm_row").visible and "3 نفر" in rig.f("bc_confirm_text").value
    assert rig.manager.broadcasts.history() == []  # هنوز نه
    rig.click("bc_confirm")
    [b] = rig.manager.broadcasts.history()
    assert b.status == "running" and b.total == 3 and b.text == "تخفیفِ آخرِ هفته" and b.content.button == ("ببین", "https://example.com/o") and b.footer is True
    assert rig.f("bc_confirm_row").visible is False and rig.f("bc_text").value == "" and rig.f("bc_button_label").value == rig.f("bc_button_url").value == ""
    value, color = rig.notice()
    assert f"#{b.id}" in value and "ربات‌ها خاموشن" in value and color == theme.SUCCESS
    assert "در حال ارسال" in rig.history_text() and "تخفیفِ آخرِ هفته" in rig.history_text()


def test_declining_the_confirmation_sends_nothing(rig):
    rig.type(text="متن")
    rig.click("bc_start")
    rig.click("bc_confirm_no")
    assert rig.f("bc_confirm_row").visible is False and rig.manager.broadcasts.history() == []


def test_editing_after_the_confirmation_prompt_withdraws_it(rig):
    rig.type(text="متن اول")
    rig.click("bc_start")
    assert rig.f("bc_confirm_row").visible
    rig.type(text="متنِ تغییرکرده")  # شمارش/محتوا عوض شد ← تأییدِ قبلی دیگر معتبر نیست
    assert rig.f("bc_confirm_row").visible is False


def test_the_service_rules_are_surfaced_as_readable_errors(rig):
    rig.type(text="اول")
    rig.click("bc_start")
    rig.click("bc_confirm")
    rig.type(text="دوم")
    rig.click("bc_start")
    rig.click("bc_confirm")
    value, color = rig.notice()
    assert "در جریانه" in value and color == theme.DANGER and len(rig.manager.broadcasts.history()) == 1
    assert rig.f("bc_confirm_row").visible is False
    bid = rig.manager.broadcasts.history()[0].id
    rig.manager.broadcasts.cancel(bid)
    rig.settings.broadcast_daily_cap = 1
    rig.type(text="سوم")
    rig.click("bc_start")
    rig.click("bc_confirm")
    assert "سقفِ ارسالِ همگانی" in rig.notice()[0]


def test_history_shows_progress_pause_resume_and_a_two_click_cancel(rig):
    rig.type(text="پیام")
    rig.click("bc_start")
    rig.click("bc_confirm")
    bid = rig.manager.broadcasts.history()[0].id
    store = rig.manager.broadcasts.store
    store.mark(bid, "telegram", "1", "sent")
    store.mark(bid, "telegram", "2", "unreachable", "TelegramForbiddenError: Forbidden: bot was blocked by the user")
    rig.tick()
    text = rig.history_text()
    assert "رسید 1" in text and "دسترس‌ناپذیر 1" in text and "مانده 1" in text and "دلیلِ خطاها" in text and "bot was blocked" in text
    assert find(rig.f("bc_history"), f"bc_item_{bid}") is not None
    bar = [c for c in find(rig.f("bc_history"), f"bc_item_{bid}").controls if type(c).__name__ == "ProgressBar"][0]
    assert abs(bar.value - 2 / 3) < 1e-9

    rig.click(f"bc_pause_{bid}")
    assert store.status_of(bid) == "paused" and "متوقف" in rig.history_text()
    assert rig.f(f"bc_pause_{bid}") is None and rig.f(f"bc_resume_{bid}") is not None
    rig.click(f"bc_resume_{bid}")
    assert store.status_of(bid) == "running"
    rig.click(f"bc_cancel_{bid}")
    assert store.status_of(bid) == "running" and rig.f(f"bc_cancel_{bid}").content == "مطمئنی؟ دوباره بزن"  # کلیکِ اول فقط مسلح می‌کند
    rig.click(f"bc_cancel_{bid}")
    assert store.status_of(bid) == "cancelled" and "لغو شد" in rig.history_text()
    assert rig.f(f"bc_cancel_{bid}") is None and rig.f(f"bc_pause_{bid}") is None  # دکمه‌ای برای ارسالِ تمام‌شده نیست


def test_the_history_only_rerenders_when_something_changed(rig):
    rig.type(text="پیام")
    rig.click("bc_start")
    rig.click("bc_confirm")
    first = rig.f("bc_history").controls
    rig.tick()
    assert rig.f("bc_history").controls is first  # بدونِ تغییر ← بازسازی نمی‌شود (دکمه‌ها وسطِ کلیک نمی‌پرند)


def test_finished_broadcasts_show_done_and_failure_reasons(rig):
    rig.type(text="پیام")
    rig.click("bc_start")
    rig.click("bc_confirm")
    b = rig.manager.broadcasts.history()[0]
    store = rig.manager.broadcasts.store
    for user, status in (("1", "sent"), ("2", "failed"), ("3", "sent")):
        store.mark(b.id, "bale" if user == "3" else "telegram", user, status, "ValueError: Bad Request: wrong file" if status == "failed" else "")
    store.set_status(b.id, "done")
    rig.tick()
    text = rig.history_text()
    assert "تمام شد" in text and "ناموفق 1" in text and "1× ValueError: Bad Request: wrong file" in text


def test_test_send_reports_success_failures_and_manager_errors(rig):
    rig.type(text="آزمایش")
    rig.click("bc_test")
    assert rig.test_calls and rig.test_calls[0].text == "آزمایش"
    assert rig.notice() == ("✅ پیامِ آزمایشی برایت فرستاده شد (تلگرام).", theme.SUCCESS)
    rig.test_result = [("telegram", True, ""), ("bale", False, "ربات این پلتفرم روشن نیست")]
    rig.click("bc_test")
    value, color = rig.notice()
    assert "بله: ربات این پلتفرم روشن نیست" in value and color == theme.DANGER
    for exc, pattern in ((bc.BroadcastError("اول خودت را به‌عنوان مالک وصل کن"), "مالک"), (BotManagerError("ربات‌ها خاموشن"), "خاموشن"), (RuntimeError("boom"), "فرستاده نشد")):
        rig.test_result = exc
        rig.click("bc_test")
        assert pattern in rig.notice()[0] and rig.notice()[1] == theme.DANGER
    n = len(rig.test_calls)
    rig.type(text="")
    rig.click("bc_test")
    assert "خالی" in rig.notice()[0] and len(rig.test_calls) == n  # متنِ نامعتبر هرگز به مدیر نمی‌رسد
    assert rig.manager.broadcasts.history() == []


def stub_picker(monkeypatch, path):
    class Result:
        pass

    Result.path = str(path)

    class Picker:
        async def pick_files(self, **kw):
            return [Result()]

    monkeypatch.setattr(screen.common, "get_or_create_file_picker", lambda page: Picker())


def pick(rig):
    asyncio.run(rig.f("bc_photo_pick").on_click(None))


def media(rig):
    return rig.tmp_path / "data" / "broadcast_media"


def test_photo_pick_preview_clear_and_cleanup(rig, monkeypatch):
    photo = rig.tmp_path / "promo.jpg"
    photo.write_bytes(b"\xff\xd8\xff data")
    stub_picker(monkeypatch, photo)
    pick(rig)
    stored = rig.f("bc_photo_label").value
    assert stored.endswith(".jpg") and "promo" not in stored and rig.f("bc_photo_clear") is not None  # کپیِ داخلی با نامِ یکتا
    assert (media(rig) / stored).is_file() and stored in collect_text(rig.f("bc_preview"))
    rig.click("bc_photo_clear")
    assert rig.f("bc_photo_label").value == "بدونِ عکس" and list(media(rig).iterdir()) == []
    pick(rig)
    assert len(list(media(rig).iterdir())) == 1
    rig.cleanup()  # ارسال‌نشده ← کپی پاک می‌شود و refresher متوقف
    assert list(media(rig).iterdir()) == [] and StubRefresher.last.stopped


def test_replacing_a_photo_deletes_the_previous_unsent_copy(rig, monkeypatch):
    photo = rig.tmp_path / "p.png"
    photo.write_bytes(b"x")
    stub_picker(monkeypatch, photo)
    pick(rig)
    pick(rig)
    assert len(list(media(rig).iterdir())) == 1


def test_a_photo_that_was_sent_belongs_to_the_broadcast_and_survives_cleanup(rig, monkeypatch):
    photo = rig.tmp_path / "p.png"
    photo.write_bytes(b"x")
    stub_picker(monkeypatch, photo)
    pick(rig)
    rig.type(text="با عکس")
    rig.click("bc_start")
    rig.click("bc_confirm")
    [b] = rig.manager.broadcasts.history()
    assert b.photo and Path(b.photo).is_file() and rig.f("bc_photo_label").value == "بدونِ عکس"  # فرم خالی شد
    rig.cleanup()
    assert Path(b.photo).is_file()  # موتور هنوز لازمش دارد


def test_invalid_photos_are_rejected_with_a_message(rig, monkeypatch):
    gif = rig.tmp_path / "a.gif"
    gif.write_bytes(b"x")
    stub_picker(monkeypatch, gif)
    pick(rig)
    assert "فرمتِ عکس" in rig.notice()[0] and rig.f("bc_photo_label").value == "بدونِ عکس"


def test_settings_validate_persist_and_accept_persian_digits(rig):
    rig.type(cap="۵", rate_tg="25", rate_bale="۱۰")
    rig.f("bc_footer_default").value = False
    rig.click("bc_settings_save")
    assert (rig.settings.broadcast_daily_cap, rig.settings.broadcast_rate_telegram, rig.settings.broadcast_rate_bale) == (5, 25, 10)
    assert rig.settings.broadcast_footer_enabled is False and rig.saves == 1 and rig.f("bc_settings_note").value == "ذخیره شد."
    for field, bad in (("cap", "0"), ("cap", "51"), ("cap", "abc"), ("rate_tg", "26"), ("rate_tg", "0"), ("rate_bale", "11"), ("rate_bale", "")):
        before, saves = rig.settings.broadcast_daily_cap, rig.saves
        rig.type(**{field: bad})
        rig.click("bc_settings_save")
        assert "باید عددی بینِ" in rig.f("bc_settings_note").value and rig.f("bc_settings_note").color == theme.DANGER
        assert rig.settings.broadcast_daily_cap == before and rig.saves == saves  # چیزی ذخیره نشد
        rig.type(cap="5", rate_tg="25", rate_bale="10")


def test_the_settings_flow_into_the_service(rig):
    rig.type(cap="1")
    rig.click("bc_settings_save")
    assert rig.manager.broadcasts.cap() == 1
    rig.type(text="اول")
    rig.click("bc_start")
    rig.click("bc_confirm")
    rig.manager.broadcasts.cancel(rig.manager.broadcasts.history()[0].id)
    rig.type(text="دوم")
    rig.click("bc_start")
    rig.click("bc_confirm")
    assert "سقفِ ارسالِ همگانی" in rig.notice()[0] and "(1)" in rig.notice()[0]


def test_english_ui(tmp_path, monkeypatch):
    r = Rig(tmp_path, monkeypatch, lang="en")
    assert "Recipients: 3" in r.f("bc_who").value and "Broadcast" in collect_text(r.control) and r.f("bc_start").content == "Start sending…"
    r.type(text="Hello")
    r.click("bc_start")
    assert "3 people" in r.f("bc_confirm_text").value
    r.click("bc_confirm")
    assert "Sending" in r.history_text() and "started" in r.notice()[0]
    r.cleanup()
