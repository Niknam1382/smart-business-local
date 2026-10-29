"""مدیرانِ ربات (N11): نقش‌ها، دعوتِ یک‌بارمصرف، افزودن با شناسه، کنسولِ نقش‌محور، پنلِ دکمه‌ای (با callbackِ جعلی)، ممیزی و confirmed_by."""

import asyncio
import threading
import time

import pytest
from fakes import FakeEngine, FakeSettings
from helpers import wait_until
from fake_servers import FakeBotApiServer
from test_adapters_e2e import make_settings
from test_commerce_e2e import FAST, got, make_commerce_manager, start_both, use_engine

from app.core import admins as am
from app.core import ai_engine
from app.core.admin_panel import AdminPanel
from app.core.admins import AdminStore
from app.core.bot_pipeline import ConversationPipeline, IncomingMessage
from app.core.conversations import ConversationStore
from app.core.orders import METHOD_CARD_TO_CARD, STATUS_CONFIRMED, STATUS_PAID, STATUS_REJECTED, OrderStore
from app.core.owner_console import OwnerConsole, help_text
from app.core.products import ProductStore
from app.core.settings import AppSettings
from app.core.ui import Transport

NOW = 1_800_000_000


# ------------------------------------------------------------- زیرساختِ تست ----

class Recorder(Transport):
    def __init__(self):
        self.sent, self.edits, self.answers = [], [], []

    async def send_ui(self, chat_id, msg):
        self.sent.append((chat_id, msg))
        return str(len(self.sent))

    async def edit_ui(self, chat_id, message_id, msg):
        self.edits.append((chat_id, message_id, msg))
        return True

    async def delete_message(self, chat_id, message_id):
        pass

    async def answer_callback(self, callback_id, text="", alert=False):
        self.answers.append((callback_id, text, alert))

    @property
    def shown(self):
        return [m for _c, m in self.sent] + [m for _c, _i, m in self.edits]

    def texts(self):
        return "\n".join(m.text for m in self.shown)

    def buttons(self):
        return [b.data for m in self.shown for row in m.rows for b in row]

    def labels(self):
        return [b.label for m in self.shown for row in m.rows for b in row]


class Rig:
    def __init__(self, tmp_path):
        self.conv = ConversationStore(tmp_path / "c.db")
        self.products = ProductStore(tmp_path / "p.db")
        self.orders = OrderStore(tmp_path / "o.db", product_store=self.products)
        self.settings = AppSettings()
        self.settings.owner_chats = {"telegram": "900"}
        self.admins = AdminStore(self.conv, lambda: self.settings.owner_chats)
        self.delivered = []

        async def deliver(platform, chat_id, text, log_history):
            self.delivered.append((platform, chat_id, text))
            return True

        self.console = OwnerConsole(lambda: self.settings, self.orders, self.products, deliver, lambda: None, admins=self.admins)
        self.panel = AdminPanel(self.admins, self.console, self.orders, self.products)
        self.t = Recorder()
        self.replies = []

    def admin(self, role, uid="111", platform="telegram"):
        self.admins.add_by_id(platform, uid, role, now=NOW)
        assert self.admins.activate_if_pending(platform, uid, "علی", "ali", now=NOW + 1)
        return uid

    def paid_order(self, chat="10", qty=2, stock=5):
        pid = self.products.add("گوشی", 1_000_000, stock)
        oid = self.orders.create("telegram", chat, [(pid, qty)], customer_name="مریم", customer_phone="09121234567", customer_address="تهران")
        self.orders.mark_paid(oid, METHOD_CARD_TO_CARD, "4321")
        return pid, oid

    async def _send(self, text):
        self.replies.append(text)

    def say(self, chat, text, platform="telegram", **kw):
        self.t = Recorder()
        self.replies.clear()
        message = IncomingMessage(platform=platform, chat_id=str(chat), display_name=kw.pop("display_name", ""), text=text, **kw)
        return asyncio.run(self.panel.handle(message, self._send, self.t, rate_ok=kw.pop("rate_ok", lambda: True) if False else (lambda: True)))

    def tap(self, chat, data, platform="telegram"):
        self.t = Recorder()
        message = IncomingMessage(platform=platform, chat_id=str(chat), display_name="", text="", callback_data=data, callback_id="cb1", message_id="77")
        return asyncio.run(self.panel.handle(message, self._send, self.t))

    def audit_actions(self):
        return [row["action"] for row in self.admins.recent_audit(100)]


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


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


# ---------------------------------------------------------------- نقش و قابلیت ----

def test_capability_matrix_is_exactly_what_was_designed():
    """اگه کسی بی‌خبر دسترسی اضافه کنه (escalation) این تست قرمز می‌شه."""
    assert am.CAPABILITIES[am.ROLE_SUPPORT] == {am.CAP_PANEL, am.CAP_SUPPORT_VIEW, am.CAP_SUPPORT_REPLY}
    assert am.CAPABILITIES[am.ROLE_VIEWER] == {am.CAP_PANEL, am.CAP_ORDERS_VIEW, am.CAP_STOCK_VIEW, am.CAP_STATS_VIEW, am.CAP_SUPPORT_VIEW}
    # N19: مدیر = مالک − (مدیریتِ مدیران، قطعِ مالک، مالی). «ارسالِ مجددِ فاکتور» را دارد؛ دیدنِ مالی فقط با اعطای مالک
    assert am.CAPABILITIES[am.ROLE_MANAGER] == am.CAPABILITIES[am.ROLE_OWNER] - {am.CAP_ADMINS_MANAGE, am.CAP_OWNER_UNLINK, am.CAP_FINANCE_VIEW, am.CAP_FINANCE_EDIT}
    assert am.CAP_INVOICE_RESEND in am.CAPABILITIES[am.ROLE_MANAGER] and am.CAP_FINANCE_VIEW in am.CAPABILITIES[am.ROLE_OWNER]
    for role in (am.ROLE_SUPPORT, am.ROLE_VIEWER):
        assert not any(am.can_effective(role, cap, True) for cap in (am.CAP_FINANCE_VIEW, am.CAP_FINANCE_EDIT, am.CAP_INVOICE_RESEND))
    assert not am.can_effective(am.ROLE_MANAGER, am.CAP_FINANCE_VIEW) and am.can_effective(am.ROLE_MANAGER, am.CAP_FINANCE_VIEW, True)
    assert not am.can_effective(am.ROLE_MANAGER, am.CAP_FINANCE_EDIT, True)  # ویرایشِ دفتر هرگز به مدیر داده نمی‌شه
    for role in am.ASSIGNABLE_ROLES:
        assert not am.can(role, am.CAP_ADMINS_MANAGE) and not am.can(role, am.CAP_OWNER_UNLINK)
    assert not am.can("", am.CAP_PANEL) and not am.can("hacker", am.CAP_PANEL)
    assert not am.can(am.ROLE_VIEWER, am.CAP_ORDERS_DECIDE) and not am.can(am.ROLE_SUPPORT, am.CAP_ORDERS_VIEW)


def test_owner_comes_from_settings_and_is_not_a_table_row(rig):
    assert rig.admins.role_of("telegram", "900") == am.ROLE_OWNER and rig.admins.role_of("bale", "900") == ""
    rig.settings.owner_chats = {"bale": "5"}  # مالک عوض شد
    assert rig.admins.role_of("telegram", "900") == "" and rig.admins.role_of("bale", "5") == am.ROLE_OWNER
    assert rig.admins.list() == []


# -------------------------------------------------------------------- دعوت ----

def test_invite_token_is_never_stored_in_plaintext_and_is_single_use(rig):
    token = rig.admins.create_invite("telegram", "manager", now=NOW)
    assert len(token) >= 16
    raw = rig.conv.connection().execute("SELECT * FROM admin_invites").fetchall()
    assert len(raw) == 1 and token not in " ".join(str(v) for v in tuple(raw[0]))
    ok = rig.admins.accept_invite(token, "telegram", "111", "علی", "ali", now=NOW + 5)
    assert ok.status == "ok" and ok.role == "manager" and ok.admin.status == "active" and ok.admin.name == "علی"
    assert rig.admins.role_of("telegram", "111") == "manager"
    assert rig.admins.accept_invite(token, "telegram", "222", now=NOW + 6).status == "used"
    assert rig.admins.role_of("telegram", "222") == ""


@pytest.mark.parametrize("attempt,expected", [("garbage-token", "unknown"), ("", "unknown")])
def test_unknown_tokens_are_rejected(rig, attempt, expected):
    assert rig.admins.accept_invite(attempt, "telegram", "1", now=NOW).status == expected


def test_invite_expires_after_ten_minutes_and_is_bound_to_its_platform(rig):
    token = rig.admins.create_invite("telegram", "viewer", now=NOW)
    assert rig.admins.accept_invite(token, "bale", "1", now=NOW + 5).status == "wrong_platform"
    assert rig.admins.accept_invite(token, "telegram", "1", now=NOW + am.INVITE_TTL_SECONDS + 1).status == "expired"
    assert rig.admins.accept_invite(token, "telegram", "1", now=NOW + am.INVITE_TTL_SECONDS).status == "ok"  # دقیقاً سرِ مهلت هنوز معتبر
    assert rig.admins.role_of("telegram", "1") == "viewer"


def test_the_owner_cannot_be_demoted_by_an_invite(rig):
    token = rig.admins.create_invite("telegram", "viewer", now=NOW)
    assert rig.admins.accept_invite(token, "telegram", "900", now=NOW + 1).status == "owner"
    assert rig.admins.role_of("telegram", "900") == am.ROLE_OWNER and rig.admins.list() == []


def test_invite_for_an_invalid_role_is_refused(rig):
    for bad in ("owner", "root", ""):
        with pytest.raises(ValueError):
            rig.admins.create_invite("telegram", bad)


def test_two_people_racing_for_one_invite_only_one_wins(tmp_path):
    conv = ConversationStore(tmp_path / "race.db")
    token = AdminStore(conv).create_invite("telegram", "manager")
    results, barrier = [], threading.Barrier(2)

    def go(uid):
        store = AdminStore(conv)
        barrier.wait()
        results.append(store.accept_invite(token, "telegram", uid).status)

    threads = [threading.Thread(target=go, args=(str(u),)) for u in (1, 2)]
    [t.start() for t in threads]
    [t.join(10) for t in threads]
    assert sorted(results) == ["ok", "used"]


# ----------------------------------------------------------- افزودن با شناسه ----

def test_add_by_id_is_pending_until_the_person_writes_first(rig):
    admin = rig.admins.add_by_id("telegram", "555", "support", "سارا", now=NOW)
    assert admin.status == am.STATUS_PENDING and rig.admins.role_of("telegram", "555") == ""
    assert rig.admins.activate_if_pending("telegram", "999", now=NOW) is None  # شناسه‌ی دیگر
    active = rig.admins.activate_if_pending("telegram", "555", "Sara T", "sara_t", now=NOW + 60)
    assert active.status == "active" and active.name == "سارا" and active.username == "sara_t"
    assert rig.admins.role_of("telegram", "555") == "support"
    assert rig.admins.activate_if_pending("telegram", "555", now=NOW + 61) is None  # دوباره فعال‌سازی معنی ندارد


def test_pending_admins_expire_after_seven_days(rig):
    rig.admins.add_by_id("telegram", "555", "manager", now=NOW)
    assert rig.admins.activate_if_pending("telegram", "555", now=NOW + am.PENDING_TTL_SECONDS + 1) is None
    assert rig.admins.list(now=NOW + am.PENDING_TTL_SECONDS + 1) == []  # از فهرست هم پاک می‌شه
    assert rig.admins.role_of("telegram", "555") == ""


@pytest.mark.parametrize("bad", ["abc", "12a", "", " ", "-5", "1.5"])
def test_add_by_id_rejects_non_numeric_ids(rig, bad):
    with pytest.raises(ValueError):
        rig.admins.add_by_id("telegram", bad, "manager")


def test_add_by_id_rejects_the_owner_and_bad_roles_and_keeps_active_admins_active(rig):
    with pytest.raises(ValueError):
        rig.admins.add_by_id("telegram", "900", "manager")
    with pytest.raises(ValueError):
        rig.admins.add_by_id("telegram", "5", "owner")
    rig.admin("viewer", "5")
    again = rig.admins.add_by_id("telegram", "5", "manager", now=NOW + 100)
    assert again.status == "active" and again.role == "manager"  # ارتقای نقش، بدونِ برگشت به «در انتظار»


# ------------------------------------------------------------ مدیریت و ممیزی ----

def test_role_change_disable_and_remove_take_effect_immediately_and_are_audited(rig):
    rig.admin("viewer", "5")
    assert rig.admins.set_role("telegram", "5", "manager") and rig.admins.role_of("telegram", "5") == "manager"
    assert rig.admins.set_active("telegram", "5", False) and rig.admins.role_of("telegram", "5") == ""
    assert rig.admins.set_active("telegram", "5", True) and rig.admins.role_of("telegram", "5") == "manager"
    assert rig.admins.remove("telegram", "5") and rig.admins.role_of("telegram", "5") == ""
    assert rig.admins.remove("telegram", "5") is False
    with pytest.raises(ValueError):
        rig.admins.set_role("telegram", "5", "owner")
    assert {"admin_added", "admin_activated", "role_changed", "admin_disabled", "admin_enabled", "admin_removed"} <= set(rig.audit_actions())


def test_disabling_does_not_activate_a_pending_admin(rig):
    rig.admins.add_by_id("telegram", "7", "manager", now=NOW)
    assert rig.admins.set_active("telegram", "7", True) is False
    assert rig.admins.role_of("telegram", "7") == ""


def test_active_with_lists_only_active_admins_having_the_capability(rig):
    rig.admin("manager", "1")
    rig.admin("viewer", "2")
    rig.admin("support", "3")
    rig.admins.add_by_id("telegram", "4", "manager", now=NOW)  # در انتظار
    rig.admin("manager", "5")
    rig.admins.set_active("telegram", "5", False)
    assert {a.user_id for a in rig.admins.active_with(am.CAP_ORDERS_DECIDE)} == {"1"}
    assert {a.user_id for a in rig.admins.active_with(am.CAP_SUPPORT_REPLY)} == {"1", "3"}


def test_audit_log_is_ordered_capped_and_cleaned(rig, monkeypatch):
    rig.admins.audit("a", actor="x\x00y", detail="d" * 1000, now=NOW)
    first = rig.admins.recent_audit(1)[0]
    assert "\x00" not in first["actor"] and len(first["detail"]) <= 300
    monkeypatch.setattr(am, "MAX_AUDIT_ROWS", 5)
    for i in range(20):
        rig.admins.audit(f"act{i}", now=NOW + i)
    rows = rig.admins.recent_audit(100)
    assert len(rows) <= 6 and rows[0]["action"] == "act19"


def test_touch_updates_last_activity(rig):
    rig.admin("manager", "1")
    rig.admins.touch("telegram", "1", now=NOW + 500)
    assert rig.admins.get("telegram", "1").last_active_ts == NOW + 500


# ------------------------------------------------------------- کنسولِ متنی ----

def run_console(rig, chat, text, reply_to=""):
    out = []

    async def send(reply):
        out.append(reply)

    handled = asyncio.run(rig.console.handle("telegram", chat, text, send, reply_to=reply_to))
    return handled, (out[-1] if out else "")


def test_manager_can_confirm_and_it_is_recorded_who_did_it(rig):
    rig.admin("manager", "111")
    pid, oid = rig.paid_order()
    handled, reply = run_console(rig, "111", f"/confirm {oid}")
    assert handled and "تایید" in reply
    assert rig.orders.get(oid).status == STATUS_CONFIRMED and rig.orders.confirmed_by(oid) == "manager:telegram:111"
    assert "order_confirmed" in rig.audit_actions()


def test_owner_confirmation_is_attributed_to_the_owner(rig):
    pid, oid = rig.paid_order()
    run_console(rig, "900", f"/confirm {oid}")
    assert rig.orders.confirmed_by(oid) == "owner:telegram:900"


def test_viewer_can_look_but_not_decide_and_plain_words_fall_through(rig):
    rig.admin("viewer", "111")
    pid, oid = rig.paid_order()
    assert run_console(rig, "111", "/orders")[0] is True
    assert run_console(rig, "111", "/stock")[0] is True
    handled, reply = run_console(rig, "111", f"/confirm {oid}")
    assert handled and "⛔" in reply and "ناظر" in reply
    assert rig.orders.get(oid).status == STATUS_PAID and rig.orders.confirmed_by(oid) == ""
    handled, reply = run_console(rig, "111", f"تایید {oid}")  # کلمه‌ی عادی = گفتگوی عادی، بلعیده نمی‌شه
    assert handled is False and reply == ""
    assert rig.orders.get(oid).status == STATUS_PAID


def test_support_has_no_order_or_stock_access(rig):
    rig.admin("support", "111")
    pid, oid = rig.paid_order()
    for text in ("/orders", f"/order {oid}", f"/confirm {oid}", f"/reject {oid}", "/stock"):
        handled, reply = run_console(rig, "111", text)
        assert handled and "⛔" in reply and "پشتیبان" in reply, text
    assert rig.orders.get(oid).status == STATUS_PAID


def test_only_the_owner_can_unlink(rig):
    rig.admin("manager", "111")
    handled, reply = run_console(rig, "111", "/unlink")
    assert handled and "⛔" in reply and rig.settings.owner_chats == {"telegram": "900"}
    handled, reply = run_console(rig, "900", "/unlink")
    assert handled and rig.settings.owner_chats == {}


def test_disabled_removed_and_pending_admins_are_plain_customers(rig):
    pid, oid = rig.paid_order()
    rig.admin("manager", "111")
    rig.admins.set_active("telegram", "111", False)
    assert run_console(rig, "111", f"/confirm {oid}")[0] is False
    rig.admins.add_by_id("telegram", "222", "manager", now=NOW)
    assert run_console(rig, "222", f"/confirm {oid}")[0] is False
    assert run_console(rig, "333", f"/confirm {oid}")[0] is False and rig.orders.get(oid).status == STATUS_PAID


def test_help_shows_only_what_the_role_may_do():
    owner, manager, viewer, support = (help_text(r) for r in (am.ROLE_OWNER, am.ROLE_MANAGER, am.ROLE_VIEWER, am.ROLE_SUPPORT))
    assert "/unlink" in owner and "/unlink" not in manager and "/confirm" in manager
    assert "/confirm" not in viewer and "/orders" in viewer and "/orders" not in support
    assert "/id" in support and "/admin" in support and "پشتیبان" in support


class FakeHandoff:
    def __init__(self):
        self.calls = []

    def owner_list(self):
        return "📋 گفتگوهای باز: (خالی)"

    async def owner_reply(self, platform, chat_id, text):
        self.calls.append(("reply", platform, chat_id, text))
        return "✅ فرستاده شد"

    async def owner_close(self, platform, chat_id):
        self.calls.append(("close", platform, chat_id))
        return "✅ بسته شد"

    def lookup(self, platform, owner_chat, reply_to):
        return ("telegram", "40") if reply_to == "55" else None

    def list_open(self):
        return []


def test_support_commands_are_gated_by_role(rig):
    rig.console._handoff = FakeHandoff()
    rig.admin("viewer", "1")
    rig.admin("support", "2")
    rig.admin("manager", "3")
    handled, reply = run_console(rig, "1", "/reply t40 سلام")
    assert handled and "⛔" in reply and rig.console._handoff.calls == []
    assert "گفتگوهای باز" in run_console(rig, "1", "/handoffs")[1]  # ناظر می‌تونه ببینه
    assert run_console(rig, "1", "جواب", reply_to="55")[0] is False  # Reply توسطِ ناظر: بلعیده نمی‌شه
    assert run_console(rig, "2", "/reply t40 سلام")[1] == "✅ فرستاده شد"
    assert run_console(rig, "3", "جواب", reply_to="55")[1] == "✅ فرستاده شد"
    assert [c[0] for c in rig.console._handoff.calls] == ["reply", "reply"]


def test_order_alerts_also_reach_managers_but_not_viewers_or_support(rig):
    rig.admin("manager", "1")
    rig.admin("viewer", "2")
    rig.admin("support", "3")
    pid, oid = rig.paid_order()
    asyncio.run(rig.console.alert_order(rig.orders.get(oid)))
    targets = {chat for _p, chat, _t in rig.delivered}
    assert targets == {"900", "1"}
    rig.delivered.clear()
    asyncio.run(rig.console.notify("هشدارِ فنی"))
    assert {chat for _p, chat, _t in rig.delivered} == {"900"}  # هشدارهای غیرِ سفارش فقط برای مالک


# ----------------------------------------------------------------- پنلِ دکمه‌ای ----

def test_slash_admin_opens_a_menu_with_only_the_buttons_of_the_role(rig):
    rig.admin("viewer", "1")
    rig.admin("support", "2")
    rig.admin("manager", "3")
    assert rig.say("1", "/admin") is True
    assert set(rig.t.buttons()) == {"adm:ord", "adm:stk", "adm:prd", "adm:sts", "adm:sup"} and "ناظر" in rig.t.texts()
    rig.say("2", "/admin")
    assert rig.t.buttons() == ["adm:sup"] and "پشتیبان" in rig.t.texts()
    rig.say("3", "/admin")
    assert "adm:ord" in rig.t.buttons() and "مدیر" in rig.t.texts()
    rig.say("900", "/admin")
    assert len(rig.t.buttons()) == 5


def test_strangers_get_nothing_from_admin_commands(rig):
    assert rig.say("40", "/admin") is False and rig.t.sent == [] and rig.t.edits == []
    assert rig.say("40", "/panel") is False


def test_id_command_answers_anyone_with_their_own_number_and_respects_the_rate_limit(rig):
    assert rig.say("40", "/id") is True and "40" in rig.replies[0] and "مدیر" in rig.replies[0]
    assert rig.say("41", "/id@MyShopBot") is True and "41" in rig.replies[0]
    out = []

    async def send(text):
        out.append(text)

    message = IncomingMessage(platform="telegram", chat_id="42", display_name="", text="/id")
    assert asyncio.run(rig.panel.handle(message, send, Recorder(), rate_ok=lambda: False)) is True and out == []


def test_invite_via_start_payload_makes_an_admin_and_shows_the_welcome_menu(rig):
    token = rig.admins.create_invite("telegram", "manager")
    assert rig.say("777", f"/start admin_{token}", first_name="رضا", username="reza") is True
    assert rig.admins.role_of("telegram", "777") == "manager" and rig.admins.get("telegram", "777").name == "رضا"
    assert "به‌عنوان «مدیر»" in rig.t.texts() and "adm:ord" in rig.t.buttons()
    # لینکِ مصرف‌شده: پیامِ روشن (نه بی‌صدا)، نقشی داده نمی‌شه
    assert rig.say("778", f"/start admin_{token}") is True and "قبلاً استفاده شده" in rig.replies[0]
    assert rig.admins.role_of("telegram", "778") == ""


def test_unknown_start_payload_looks_like_a_normal_start(rig):
    assert rig.say("40", "/start admin_totallyfaketoken123") is False and rig.replies == [] and rig.t.sent == []
    assert rig.say("40", "/start") is False and rig.say("40", "/start promo_x") is False


def test_expired_and_foreign_platform_invites_get_clear_messages(rig):
    token = rig.admins.create_invite("telegram", "viewer", now=time.time() - am.INVITE_TTL_SECONDS - 5)
    assert rig.say("5", f"/start admin_{token}") is True and "منقضی" in rig.replies[0]
    other = rig.admins.create_invite("bale", "viewer")
    assert rig.say("5", f"/start admin_{other}") is True and "پیام‌رسانِ دیگه" in rig.replies[0]
    assert rig.admins.role_of("telegram", "5") == ""


def test_the_first_message_of_a_pending_id_activates_access(rig):
    rig.admins.add_by_id("telegram", "555", "manager", now=time.time())
    assert rig.say("555", "سلام") is False  # پیامِ عادی به مسیرِ مشتری ادامه می‌ده
    assert rig.admins.role_of("telegram", "555") == "manager" and "فعال شد" in rig.t.texts()
    rig.admins.add_by_id("telegram", "556", "viewer", now=time.time())
    assert rig.say("556", "/start") is True and rig.admins.role_of("telegram", "556") == "viewer"  # فرمان = مصرف می‌شه


# --- دکمه‌ها: امنیت

def test_forged_callbacks_from_non_admins_do_nothing_silently(rig):
    pid, oid = rig.paid_order()
    for data in (f"adm:ok:{oid}", f"adm:nox:{oid}", f"adm:sa:{pid}:100", f"adm:tg:{pid}", "adm:ord", "adm:home", "adm:sts"):
        assert rig.tap("40", data) is True  # مصرف می‌شه ولی هیچ خروجی ندارد
        assert rig.t.sent == [] and rig.t.edits == [] and [a for a in rig.t.answers if a[1]] == [], data
    assert rig.orders.get(oid).status == STATUS_PAID and rig.products.get(pid).active and rig.products.get(pid).stock_quantity == 5
    assert rig.audit_actions() == []


def test_callbacks_from_disabled_or_removed_admins_are_ignored(rig):
    pid, oid = rig.paid_order()
    rig.admin("manager", "111")
    rig.admins.set_active("telegram", "111", False)
    rig.tap("111", f"adm:ok:{oid}")
    rig.admins.remove("telegram", "111")
    rig.tap("111", f"adm:ok:{oid}")
    assert rig.orders.get(oid).status == STATUS_PAID


def test_a_role_without_the_capability_gets_an_alert_and_changes_nothing(rig):
    pid, oid = rig.paid_order()
    rig.admin("viewer", "1")
    rig.admin("support", "2")
    rig.tap("1", f"adm:ok:{oid}")
    assert rig.orders.get(oid).status == STATUS_PAID and any(alert and "⛔" in text for _id, text, alert in rig.t.answers)
    rig.tap("1", f"adm:sa:{pid}:5")
    rig.tap("1", f"adm:tg:{pid}")
    assert rig.products.get(pid).stock_quantity == 5 and rig.products.get(pid).active
    rig.tap("2", "adm:ord")
    assert any(alert for _id, _t, alert in rig.t.answers) and rig.t.edits == []
    rig.tap("2", f"adm:nox:{oid}")
    assert rig.orders.get(oid).status == STATUS_PAID


def test_malformed_or_unknown_callbacks_are_harmless(rig):
    rig.admin("manager", "111")
    pid, oid = rig.paid_order()
    for data in ("adm:", "adm:zzz", "adm:od:abc", "adm:od:999", "adm:od", "adm:ok:", "adm:sa:abc:1", f"adm:sa:{pid}:0", f"adm:sa:{pid}:9999", f"adm:sa:{pid}", "adm:ok:1:2:3:4", "adm:ok:-1", "adm:sp:999"):
        assert rig.tap("111", data) is True, data
    assert rig.orders.get(oid).status == STATUS_PAID and rig.products.get(pid).stock_quantity == 5
    assert rig.tap("111", "other:thing") is False and rig.tap("111", "adm") is False  # callbackهای غیرِ پنل به مسیرهای دیگر می‌رسه


# --- دکمه‌ها: کار

def test_orders_list_shows_buttons_by_capability(rig):
    pid, oid = rig.paid_order()
    rig.admin("manager", "1")
    rig.admin("viewer", "2")
    rig.tap("1", "adm:ord")
    assert {f"adm:ok:{oid}", f"adm:no:{oid}", f"adm:od:{oid}"} <= set(rig.t.buttons()) and f"#{oid}" in rig.t.texts()
    rig.tap("2", "adm:ord")
    assert f"adm:ok:{oid}" not in rig.t.buttons() and f"adm:od:{oid}" in rig.t.buttons()
    assert rig.tap("900", "adm:ord") is True and "منتظر تایید" in rig.t.texts()


def test_empty_orders_list_says_so(rig):
    rig.admin("manager", "1")
    rig.tap("1", "adm:ord")
    assert "سفارشِ منتظر تایید نداری" in rig.t.texts()


def test_confirm_button_confirms_edits_the_message_and_records_the_confirmer(rig):
    pid, oid = rig.paid_order()
    rig.admin("manager", "111")
    rig.tap("111", f"adm:ok:{oid}")
    assert rig.orders.get(oid).status == STATUS_CONFIRMED and rig.products.get(pid).stock_quantity == 3
    assert rig.orders.confirmed_by(oid) == "manager:telegram:111"
    assert rig.t.edits and rig.t.edits[0][1] == "77" and "تایید" in rig.t.texts()  # پیامِ مبدأ ویرایش شد
    assert any(p == "telegram" and c == "10" for p, c, _t in rig.delivered), "مشتری خبردار شد"
    assert "order_confirmed" in rig.audit_actions()
    rig.tap("111", f"adm:ok:{oid}")  # دکمه‌ی دوباره: خطای فارسی، بدونِ تغییر
    assert "❌" in rig.t.texts() and rig.products.get(pid).stock_quantity == 3


def test_reject_needs_a_confirmation_step(rig):
    pid, oid = rig.paid_order()
    rig.admin("manager", "111")
    rig.tap("111", f"adm:no:{oid}")
    assert rig.orders.get(oid).status == STATUS_PAID and f"adm:nox:{oid}" in rig.t.buttons() and "رد بشه" in rig.t.texts()
    rig.tap("111", f"adm:nox:{oid}")
    assert rig.orders.get(oid).status == STATUS_REJECTED and "order_rejected" in rig.audit_actions()


def test_order_card_shows_details_and_the_confirmer(rig):
    pid, oid = rig.paid_order()
    rig.admin("viewer", "2")
    rig.tap("2", f"adm:od:{oid}")
    assert "مریم" in rig.t.texts() and f"adm:ok:{oid}" not in rig.t.buttons()
    rig.admin("manager", "1")
    rig.tap("1", f"adm:od:{oid}")
    assert f"adm:ok:{oid}" in rig.t.buttons()
    rig.tap("1", f"adm:ok:{oid}")
    rig.tap("2", f"adm:od:{oid}")
    assert "manager:telegram:1" in rig.t.texts()


def test_low_stock_products_and_quick_stock_edit(rig):
    pid = rig.products.add("هدفون", 500_000, 2)
    full = rig.products.add("کیف", 100_000, 50)
    rig.admin("manager", "1")
    rig.tap("1", "adm:stk")
    assert f"adm:sp:{pid}" in rig.t.buttons() and f"adm:sp:{full}" not in rig.t.buttons()
    rig.tap("1", f"adm:sp:{pid}")
    assert {f"adm:sa:{pid}:5", f"adm:sa:{pid}:-1", f"adm:tg:{pid}"} <= set(rig.t.buttons())
    rig.tap("1", f"adm:sa:{pid}:5")
    assert rig.products.get(pid).stock_quantity == 7 and "7" in rig.t.texts()
    rig.tap("1", f"adm:sa:{pid}:-5")
    assert rig.products.get(pid).stock_quantity == 2
    rig.tap("1", f"adm:sa:{pid}:-5")  # نمی‌شه منفی شد
    assert rig.products.get(pid).stock_quantity == 2 and any(alert for _i, _t, alert in rig.t.answers)
    assert rig.audit_actions().count("stock_changed") == 2


def test_toggle_product_and_viewer_sees_but_cannot_edit(rig):
    pid = rig.products.add("هدفون", 500_000, 5)
    rig.admin("manager", "1")
    rig.admin("viewer", "2")
    rig.tap("1", f"adm:tg:{pid}")
    assert rig.products.get(pid).active is False and "غیرفعال" in rig.t.texts()
    rig.tap("1", f"adm:tg:{pid}")
    assert rig.products.get(pid).active is True
    rig.tap("2", f"adm:sp:{pid}")
    assert "هدفون" in rig.t.texts() and not any(b.startswith(("adm:sa", "adm:tg")) for b in rig.t.buttons())


def test_discount_toggle_is_for_owner_and_manager_only_and_is_audited(rig):
    from app.core.discounts import DiscountCode, DiscountStore

    rig.panel._discounts = DiscountStore(rig.orders)
    cid = rig.panel._discounts.create(DiscountCode(0, "SUMMER", "percent", 10))
    rig.admin("manager", "1")
    rig.admin("viewer", "2")
    rig.admin("support", "3")
    rig.say("1", "/panel")
    assert "adm:dsc" in rig.t.buttons()
    rig.tap("1", "adm:dsc")
    assert "SUMMER" in rig.t.texts() and f"adm:dtg:{cid}" in rig.t.buttons()
    rig.tap("1", f"adm:dtg:{cid}")
    assert rig.panel._discounts.get(cid).active is False and "discount_toggled" in rig.audit_actions()
    rig.tap("1", f"adm:dtg:{cid}")
    assert rig.panel._discounts.get(cid).active is True
    for uid in ("2", "3", "40"):  # بیننده/پشتیبان/غیرمدیر
        rig.tap(uid, f"adm:dtg:{cid}")
        assert rig.panel._discounts.get(cid).active is True
    assert not am.can("viewer", am.CAP_DISCOUNTS_TOGGLE) and not am.can("support", am.CAP_DISCOUNTS_TOGGLE)
    rig.tap("1", "adm:dtg:99999")  # کدِ ناموجود بی‌اثر و بدونِ خطا
    rig.tap("1", f"adm:dtg:{cid}:extra")  # آرگومانِ اضافه رد می‌شه
    assert rig.panel._discounts.get(cid).active is True


def test_unlimited_products_have_no_stock_buttons(rig):
    pid = rig.products.add("کتابِ دیجیتال", 90_000, 0, unlimited_stock=True) if "unlimited_stock" in ProductStore.add.__code__.co_varnames else None
    if pid is None:
        pytest.skip("add() پارامترِ unlimited_stock ندارد")
    rig.admin("manager", "1")
    rig.tap("1", f"adm:sp:{pid}")
    assert "نامحدود" in rig.t.texts() and not any(b.startswith("adm:sa") for b in rig.t.buttons())


def test_products_list_and_stats(rig):
    pid, oid = rig.paid_order()
    rig.products.add("دومی", 1000, 3)
    rig.admin("manager", "1")
    rig.tap("1", "adm:prd")
    assert len([b for b in rig.t.buttons() if b.startswith("adm:sp:")]) == 2
    rig.tap("1", "adm:sts")
    text = rig.t.texts()
    assert "آمارِ امروز" in text and "سفارشِ جدید: 1" in text and "منتظرِ تایید: 1" in text
    rig.tap("1", f"adm:ok:{oid}")
    rig.tap("1", "adm:sts")
    assert "تاییدشده: 1" in rig.t.texts() and "منتظرِ تایید: 0" in rig.t.texts()


def test_support_view_without_a_handoff_service_is_graceful(rig):
    rig.admin("support", "2")
    rig.tap("2", "adm:sup")
    assert "پشتیبانی فعال نیست" in rig.t.texts()
    rig.panel._handoff = FakeHandoff()
    rig.tap("2", "adm:sup")
    assert "گفتگوهای باز" in rig.t.texts() and "/reply" in rig.t.texts()
    rig.admin("viewer", "3")
    rig.tap("3", "adm:sup")
    assert "/reply" not in rig.t.texts()  # ناظر فقط می‌بینه


def test_home_button_returns_to_the_menu_by_editing(rig):
    rig.admin("manager", "1")
    rig.tap("1", "adm:home")
    assert rig.t.edits and "پنلِ مدیریت" in rig.t.texts()


# ----------------------------------------------------------------- پایپ‌لاین ----

@pytest.fixture
def pipe(tmp_path, monkeypatch):
    rig = Rig(tmp_path)
    engine = FakeEngine()
    monkeypatch.setattr(ai_engine, "build_engine_from_settings", lambda _s: engine)
    pipeline = ConversationPipeline(FakeSettings(tmp_path), store=rig.conv, admin_panel=rig.panel, owner_console=rig.console, **FAST)
    return rig, pipeline, engine


def feed(pipeline, **kw):
    out, rec = [], Recorder()

    async def send(text):
        out.append(text)

    async def go():
        await pipeline.handle_incoming(IncomingMessage(platform="telegram", display_name="", **kw), send, rec)
        await asyncio.sleep(0.3)

    asyncio.run(go())
    return out, rec


def test_pipeline_routes_panel_traffic_away_from_the_customer_and_ai_paths(pipe):
    rig, pipeline, engine = pipe
    out, _rec = feed(pipeline, chat_id="40", text="/id")
    assert "40" in out[0] and engine.calls == [] and rig.conv.get_messages("telegram", "40") == []
    pid, oid = rig.paid_order()
    out, rec = feed(pipeline, chat_id="40", text="", callback_data=f"adm:ok:{oid}", callback_id="c", message_id="9")
    assert out == [] and rec.sent == [] and rec.edits == [] and engine.calls == [] and rig.orders.get(oid).status == STATUS_PAID
    rig.admin("manager", "111")
    _out, rec = feed(pipeline, chat_id="111", text="/admin")
    assert "adm:ord" in rec.buttons() and engine.calls == []
    out, _rec = feed(pipeline, chat_id="111", text="سلام، یه سوال دارم")  # مدیر هم می‌تونه مثلِ مشتری باشه
    assert engine.calls and out


def test_pipeline_survives_a_crashing_panel(tmp_path, monkeypatch):
    rig = Rig(tmp_path)
    monkeypatch.setattr(ai_engine, "build_engine_from_settings", lambda _s: FakeEngine())

    class Boom:
        async def handle(self, *a, **k):
            raise RuntimeError("panel bug")

    pipeline = ConversationPipeline(FakeSettings(tmp_path), store=rig.conv, admin_panel=Boom(), **FAST)
    out, _rec = feed(pipeline, chat_id="40", text="سلام")
    assert out  # مشتری هنوز جواب می‌گیره


# -------------------------------------------------------------- سرتاسری (ربات واقعی) ----

def test_invite_a_manager_end_to_end_and_confirm_from_a_button(tmp_path, tg, bale, monkeypatch):
    settings = make_settings()
    settings.card_to_card_number = "6219-8610-1234-5678"
    manager, products, orders = make_commerce_manager(tmp_path, settings, tg, bale)
    use_engine(monkeypatch, {"سلام": [lambda r: None]})
    start_both(manager)
    try:
        code = manager.owner_console.new_link_code()
        tg.push_message(900, f"/owner {code}")
        assert wait_until(lambda: got(tg, 900, "ثبت شد"), timeout=30)
        token = manager.admins.create_invite("telegram", "manager")
        tg.push_message(888, f"/start admin_{token}", first_name="رضا")
        assert wait_until(lambda: got(tg, 888, "به‌عنوان «مدیر»"), timeout=30)
        assert manager.admins.role_of("telegram", "888") == "manager" and not manager.store.get_messages("telegram", "888")
        pid = products.add("گوشی", 1_000_000, 5)
        oid = orders.create("telegram", "40", [(pid, 1)], customer_name="مریم", customer_phone="09121234567", customer_address="تهران")
        orders.mark_paid(oid, METHOD_CARD_TO_CARD, "4321")
        tg.push_callback_query(888, f"adm:ok:{oid}")
        assert wait_until(lambda: orders.get(oid).status == STATUS_CONFIRMED, timeout=30)
        assert orders.confirmed_by(oid) == "manager:telegram:888"
        # یک مشتریِ معمولی همان دکمه را جعل می‌کنه
        oid2 = orders.create("telegram", "41", [(pid, 1)], customer_name="ب", customer_phone="09120000000", customer_address="ت")
        orders.mark_paid(oid2, METHOD_CARD_TO_CARD, "1111")
        bale.push_callback_query(41, f"adm:ok:{oid2}")
        time.sleep(0.8)
        assert orders.get(oid2).status == STATUS_PAID
    finally:
        manager.stop(timeout=10)
