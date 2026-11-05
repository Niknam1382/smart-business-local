"""N6 — کادرِ «پیامِ شخصی به مشتری» در صفحه‌ی گفتگوها (UI با Page جعلی؛ ارسالِ واقعی در test_phase3_e2e.py پوشانده شده)."""

import pytest
from fake_page import FakePage, collect_text, find, fire
from test_chat_view_screen import make_env

from app import theme
from app.core.bot_manager import BotManagerError
from app.core.bot_pipeline import IncomingMessage
from app.screens import chat_view
from app.screens.chat_view import tp


class StubRefresher:
    """جایگزینِ LiveRefresher تا tickِ زنده را دستی و بدونِ ترد صدا بزنیم."""

    last = None

    def __init__(self, page, tick, interval=2.0):
        self.tick = tick
        StubRefresher.last = self

    def start(self):
        pass

    def stop(self):
        pass


class Rig:
    def __init__(self, tmp_path, monkeypatch, running=True, with_chat=True):
        monkeypatch.setattr(chat_view, "LiveRefresher", StubRefresher)
        self.manager, self.store = make_env(tmp_path, running=running)
        self.calls, self.fail = [], None
        if with_chat:
            self.add_chat("telegram", "1", "علی")

        def send(platform, chat_id, text, timeout=20.0):
            if self.fail is not None:
                raise self.fail
            self.calls.append((platform, chat_id, text))
            self.store.add_message(platform, chat_id, "owner", text)

        monkeypatch.setattr(self.manager, "send_to_customer_sync", send)
        self.page = FakePage()
        self.control, self.cleanup = chat_view.build(self.page, "fa", self.manager, on_open_bots=lambda: None)

    def add_chat(self, platform, chat_id, name):
        self.store.ensure_conversation(platform, chat_id, name)
        self.store.add_message(platform, chat_id, "user", f"سلام از {name}")
        self.manager.customers.touch(IncomingMessage(platform=platform, chat_id=chat_id, display_name=name, text="سلام"))

    def f(self, key):
        return find(self.control, key)

    def tick(self):
        StubRefresher.last.tick()

    def type(self, text):
        self.f("personal_input").value = text

    def send(self):
        fire(self.f("personal_send"), "on_click")


def sub(tmp_path, name):
    folder = tmp_path / name
    folder.mkdir()
    return folder


@pytest.fixture
def rig(tmp_path, monkeypatch):
    r = Rig(tmp_path, monkeypatch)
    yield r
    r.cleanup()


def test_composer_is_hidden_without_conversations_and_visible_with_one(tmp_path, monkeypatch):
    empty = Rig(sub(tmp_path, "e"), monkeypatch, with_chat=False)
    assert empty.f("personal_box").visible is False
    empty.cleanup()
    full = Rig(sub(tmp_path, "f"), monkeypatch, with_chat=True)
    assert full.f("personal_box").visible is True and "💬 فروشگاه" in collect_text(full.f("personal_note"))
    full.cleanup()


def test_owner_messages_get_their_own_bubble_labelled_you(rig):
    rig.store.add_message("telegram", "1", "owner", "سفارشت فردا می‌رسه")
    rig.store.add_message("telegram", "1", "assistant", "پاسخِ ربات")
    fire(rig.f("conv_telegram_1"), "on_click")
    text = collect_text(rig.f("detail_area"))
    assert "شما" in text and "سفارشت فردا می‌رسه" in text and "ربات" in text and "مشتری" in text


def test_templates_fill_the_editable_input_and_can_be_picked_again(rig):
    fire(rig.f("personal_template"), "on_select", "2")
    assert rig.f("personal_input").value == tp("tpl.2", "fa") and rig.f("personal_template").value is None
    rig.type("ویرایش‌شده: " + rig.f("personal_input").value)
    fire(rig.f("personal_template"), "on_select", "2")  # همان قالب دوباره
    assert rig.f("personal_input").value == tp("tpl.2", "fa")
    fire(rig.f("personal_template"), "on_select", "5")
    assert rig.f("personal_input").value == tp("tpl.5", "fa")
    assert len(rig.f("personal_template").options) == 5


def test_sending_calls_the_manager_clears_the_input_and_shows_the_message_in_the_history(rig):
    rig.type("  سفارشت فردا ارسال می‌شه  ")
    rig.send()
    assert rig.calls == [("telegram", "1", "سفارشت فردا ارسال می‌شه")]
    assert rig.f("personal_input").value == "" and rig.f("personal_result").visible
    assert rig.f("personal_result").value == tp("sent", "fa") and rig.f("personal_result").color == theme.SUCCESS
    assert rig.f("personal_send").disabled is False  # دوباره فعال
    assert "سفارشت فردا ارسال می‌شه" in collect_text(rig.f("detail_area")) and "شما" in collect_text(rig.f("detail_area"))


def test_empty_text_never_reaches_the_manager(rig):
    for blank in ("", "   \n  "):
        rig.type(blank)
        rig.send()
        assert rig.f("personal_result").value == tp("empty", "fa") and rig.f("personal_result").color == theme.DANGER
    assert rig.calls == []


def test_manager_errors_are_shown_verbatim_and_the_draft_is_kept(rig):
    rig.fail = BotManagerError("این مشتری ربات رو بلاک کرده یا حسابش بسته شده؛ دیگه نمی‌شه بهش پیام داد.")
    rig.type("سلام دوباره")
    rig.send()
    assert rig.f("personal_result").value == str(rig.fail) and rig.f("personal_result").color == theme.DANGER
    assert rig.f("personal_input").value == "سلام دوباره" and rig.f("personal_send").disabled is False


def test_an_unexpected_crash_shows_a_generic_error_and_never_breaks_the_screen(rig):
    rig.fail = RuntimeError("boom")
    rig.type("سلام")
    rig.send()
    assert rig.f("personal_result").value == tp("failed", "fa") and rig.f("personal_input").value == "سلام"
    rig.fail = None
    rig.send()  # بعدش هنوز کار می‌کند
    assert rig.calls == [("telegram", "1", "سلام")]


def test_the_composer_is_disabled_with_a_reason_when_blocked_stopped_or_the_bots_are_off(tmp_path, monkeypatch):
    r = Rig(sub(tmp_path, "on"), monkeypatch, running=True)

    def controls():
        return [r.f("personal_input").disabled, r.f("personal_send").disabled, r.f("personal_template").disabled]

    assert controls() == [False, False, False]
    r.store.set_blocked("telegram", "1", True)
    r.tick()
    assert controls() == [True, True, True] and r.f("personal_note").value == tp("blocked", "fa")
    r.store.set_blocked("telegram", "1", False)
    r.manager.customers.set_opted_out("telegram", "1")
    r.tick()
    assert controls() == [True, True, True] and r.f("personal_note").value == tp("stopped", "fa")
    r.manager.customers.set_opted_out("telegram", "1", False)
    r.tick()
    assert controls() == [False, False, False] and r.f("personal_note").value == tp("note", "fa")
    r.cleanup()
    off = Rig(sub(tmp_path, "off"), monkeypatch, running=False)
    assert [off.f("personal_input").disabled, off.f("personal_send").disabled] == [True, True] and off.f("personal_note").value == tp("off", "fa")
    off.cleanup()


def test_the_draft_survives_new_incoming_messages_but_not_a_conversation_switch(rig):
    rig.add_chat("bale", "2", "سارا")
    fire(rig.f("conv_telegram_1"), "on_click")
    rig.type("نیمه‌نوشته…")
    rig.store.add_message("telegram", "1", "user", "پیامِ تازه از مشتری")
    rig.tick()  # بازسازیِ ناحیه‌ی جزئیات
    assert "پیامِ تازه از مشتری" in collect_text(rig.f("detail_area"))
    assert rig.f("personal_input").value == "نیمه‌نوشته…"  # دلیلِ اینکه کادر بیرونِ detail_area است
    rig.send()
    rig.type("نیمه‌نوشته‌ی دیگر")
    fire(rig.f("conv_bale_2"), "on_click")
    assert rig.f("personal_input").value == "" and rig.f("personal_result").visible is False
    rig.type("برای سارا")
    rig.send()
    assert rig.calls[-1] == ("bale", "2", "برای سارا")


def test_a_late_result_never_clears_a_draft_typed_for_another_customer(rig):
    rig.add_chat("bale", "2", "سارا")
    fire(rig.f("conv_telegram_1"), "on_click")
    rig.type("برای علی")
    original = rig.manager.send_to_customer_sync

    def slow(platform, chat_id, text, timeout=20.0):
        original(platform, chat_id, text)
        fire(rig.f("conv_bale_2"), "on_click")  # وسطِ ارسال مالک به مشتریِ دیگر رفت
        rig.type("پیش‌نویسِ سارا")

    rig.manager.send_to_customer_sync = slow
    rig.send()
    assert rig.f("personal_input").value == "پیش‌نویسِ سارا" and rig.f("personal_result").visible is False


def test_english_ui_uses_english_labels_and_templates(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_view, "LiveRefresher", StubRefresher)
    manager, store = make_env(tmp_path, running=True)
    store.ensure_conversation("telegram", "1", "Ali")
    store.add_message("telegram", "1", "owner", "On its way")
    control, cleanup = chat_view.build(FakePage(), "en", manager, on_open_bots=lambda: None)
    assert find(control, "personal_send").content == "Send" and find(control, "personal_input").hint_text.startswith("Write")
    assert "You" in collect_text(find(control, "detail_area"))
    fire(find(control, "personal_template"), "on_select", "1")
    assert find(control, "personal_input").value == tp("tpl.1", "en")
    cleanup()
