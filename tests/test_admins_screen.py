"""صفحه‌ی «مدیران» (N11): لینکِ دعوت + QR، افزودن با شناسه، نقش‌ها، فعال/غیرفعال/حذف، ممیزی و جایگاه در منوی فروشگاه."""

from types import SimpleNamespace

import pytest
from fake_page import FakePage, collect_text, find, fire
from test_update_banner_install import StubChecker, onboarded

from app.core import admins as am
from app.core import bot_manager, qr
from app.core import settings as settings_module
from app.core.admins import AdminStore
from app.core.conversations import ConversationStore
from app.core.settings import AppSettings
from app.main import main
from app.screens import admins as screen
from app.screens import common


class FakeManager:
    def __init__(self, tmp_path, usernames=None, owner_chats=None):
        self.conv = ConversationStore(tmp_path / "c.db")
        self.owner_chats = dict(owner_chats or {})
        self.admins = AdminStore(self.conv, lambda: self.owner_chats)
        self.usernames = {"telegram": "my_shop_bot", "bale": "my_bale_bot"} if usernames is None else usernames

    def get_status(self):
        return SimpleNamespace(platforms={p: SimpleNamespace(username=u, connected=True) for p, u in self.usernames.items()})


@pytest.fixture
def env(tmp_path):
    return FakeManager(tmp_path)


def make(manager, lang="fa", owner_chats=None):
    state = AppSettings()
    state.owner_chats = dict(owner_chats if owner_chats is not None else manager.owner_chats)
    page = FakePage()
    return screen.build(page, lang, manager, state), page


def invite(root, platform=None, role=None):
    if platform:
        fire(find(root, "admins_platform"), "on_select", platform)
    if role:
        fire(find(root, "admins_role"), "on_select", role)
    fire(find(root, "admins_invite"), "on_click")


def token_from(root):
    return find(root, "admins_invite_cmd").value.split("admin_", 1)[1]


# ------------------------------------------------------------------ پایه ----

def test_empty_screen(env):
    root, _p = make(env)
    text = collect_text(root)
    assert "هنوز مالکی ثبت نشده" in text and "هنوز مدیری اضافه نکردی" in text and "هنوز چیزی ثبت نشده" in text
    assert find(root, "admins_qr") is None and find(root, "admins_notice") is None


def test_owner_is_shown_read_only(tmp_path):
    manager = FakeManager(tmp_path, owner_chats={"telegram": "900", "bale": "7"})
    root, _p = make(manager)
    text = collect_text(find(root, "admins_owner"))
    assert "900" in text and "7" in text and "هنوز مالکی" not in text


# ---------------------------------------------------------------- لینکِ دعوت ----

def test_invite_creates_a_working_link_qr_and_fallback_command(env):
    root, _p = make(env)
    invite(root, role="support")
    link, cmd, qr_img = find(root, "admins_invite_link").value, find(root, "admins_invite_cmd").value, find(root, "admins_qr")
    token = token_from(root)
    assert link == f"https://t.me/my_shop_bot?start=admin_{token}" and cmd == f"/start admin_{token}"
    assert isinstance(qr_img.src, bytes) and qr_img.src.startswith(b"\x89PNG") and "۱۰ دقیقه" in collect_text(root)
    result = env.admins.accept_invite(token, "telegram", "5", "علی")
    assert result.status == "ok" and result.role == "support"  # توکنِ ساخته‌شده واقعاً معتبره و نقشِ انتخابی را دارد


def test_invite_for_bale_uses_the_bale_link(env):
    root, _p = make(env)
    invite(root, platform="bale", role="viewer")
    assert find(root, "admins_invite_link").value == f"https://ble.ir/my_bale_bot?start=admin_{token_from(root)}"
    assert env.admins.accept_invite(token_from(root), "bale", "9").role == "viewer"
    assert env.admins.accept_invite(token_from(root), "telegram", "9").status in ("used", "wrong_platform")


def test_invite_without_a_running_bot_explains_and_creates_nothing(tmp_path):
    manager = FakeManager(tmp_path, usernames={})
    root, _p = make(manager)
    invite(root)
    assert "اول ربات این پیام‌رسان رو وصل" in collect_text(find(root, "admins_notice")) and find(root, "admins_qr") is None
    assert manager.conv.connection().execute("SELECT COUNT(*) FROM admin_invites").fetchone()[0] == 0


def test_changing_platform_or_role_hides_the_old_invite(env):
    root, _p = make(env)
    invite(root)
    assert find(root, "admins_qr") is not None
    fire(find(root, "admins_role"), "on_select", "viewer")
    assert find(root, "admins_qr") is None  # نقشِ کدِ قبلی با انتخابِ جدید نمی‌خونه
    invite(root)
    fire(find(root, "admins_platform"), "on_select", "bale")
    assert find(root, "admins_qr") is None


def test_copy_buttons_copy_the_link_and_the_command(env, monkeypatch):
    copied = []
    monkeypatch.setattr(common, "copy_text", lambda page, text: copied.append(text) or True)
    root, _p = make(env)
    invite(root)
    fire(find(root, "admins_copy_link"), "on_click")
    fire(find(root, "admins_copy_cmd"), "on_click")
    assert copied == [find(root, "admins_invite_link").value, find(root, "admins_invite_cmd").value]
    assert "کپی شد" in collect_text(find(root, "admins_notice"))


# --------------------------------------------------------- افزودن با شناسه ----

def test_add_by_id_shows_a_pending_row_and_clears_the_fields(env):
    root, _p = make(env)
    find(root, "admins_id").value = " 5551234 "
    find(root, "admins_id_name").value = "سارا"
    fire(find(root, "admins_add_id"), "on_click")
    assert "در انتظار" in collect_text(find(root, "admins_notice"))
    assert "در انتظارِ اولین پیام" in collect_text(find(root, "admin_status_telegram_5551234")) and "سارا" in collect_text(find(root, "admin_row_telegram_5551234"))
    assert find(root, "admins_id").value == "" and find(root, "admin_toggle_telegram_5551234") is None  # در انتظار: دکمه‌ی فعال/غیرفعال ندارد
    assert env.admins.get("telegram", "5551234").status == "pending"


@pytest.mark.parametrize("bad", ["abc", "", "12.5", "-3"])
def test_add_by_id_rejects_garbage(env, bad):
    root, _p = make(env)
    find(root, "admins_id").value = bad
    fire(find(root, "admins_add_id"), "on_click")
    assert "فقط عدد" in collect_text(find(root, "admins_notice")) and env.admins.list() == []


def test_add_by_id_refuses_the_owner(tmp_path):
    manager = FakeManager(tmp_path, owner_chats={"telegram": "900"})
    root, _p = make(manager)
    find(root, "admins_id").value = "900"
    fire(find(root, "admins_add_id"), "on_click")
    assert "فقط عدد" in collect_text(find(root, "admins_notice")) and manager.admins.list() == []


# ----------------------------------------------------------------- مدیریت ----

def seeded(env):
    env.admins.add_by_id("telegram", "111", "viewer", "علی", now=1)
    env.admins.activate_if_pending("telegram", "111", "", "ali", now=2)
    env.admins.add_by_id("bale", "222", "support", "مینا", now=1)
    env.admins.activate_if_pending("bale", "222", now=2)


def test_list_shows_status_role_and_last_activity(env):
    seeded(env)
    root, _p = make(env)
    assert "علی" in collect_text(find(root, "admin_row_telegram_111")) and "@ali" in collect_text(find(root, "admin_row_telegram_111"))
    assert "فعال" in collect_text(find(root, "admin_status_telegram_111")) and find(root, "admin_role_bale_222").value == "support"


def test_role_change_disable_enable_and_two_step_remove(env):
    seeded(env)
    root, _p = make(env)
    fire(find(root, "admin_role_telegram_111"), "on_select", "manager")
    assert env.admins.role_of("telegram", "111") == "manager"
    fire(find(root, "admin_role_telegram_111"), "on_select", "owner")  # نقشِ غیرمجاز نادیده گرفته می‌شه
    assert env.admins.role_of("telegram", "111") == "manager"
    fire(find(root, "admin_toggle_telegram_111"), "on_click")
    assert env.admins.role_of("telegram", "111") == "" and "غیرفعال" in collect_text(find(root, "admin_status_telegram_111"))
    assert "فعال کن" in collect_text(find(root, "admin_toggle_telegram_111"))
    fire(find(root, "admin_toggle_telegram_111"), "on_click")
    assert env.admins.role_of("telegram", "111") == "manager"
    fire(find(root, "admin_remove_telegram_111"), "on_click")
    assert env.admins.get("telegram", "111") is not None and "مطمئنی" in collect_text(find(root, "admin_remove_telegram_111"))
    fire(find(root, "admin_remove_telegram_111"), "on_click")
    assert env.admins.get("telegram", "111") is None and find(root, "admin_row_telegram_111") is None
    assert env.admins.get("bale", "222") is not None


def test_arming_one_removal_does_not_arm_another(env):
    seeded(env)
    root, _p = make(env)
    fire(find(root, "admin_remove_telegram_111"), "on_click")
    fire(find(root, "admin_remove_bale_222"), "on_click")  # اولین کلیکِ دومی فقط مسلح می‌کنه
    assert env.admins.get("telegram", "111") is not None and env.admins.get("bale", "222") is not None


def test_audit_log_lists_actions_in_the_ui_language(env):
    seeded(env)
    env.admins.audit("order_confirmed", actor="manager:telegram:111", detail="#7")
    root, _p = make(env)
    text = collect_text(root)
    assert "سفارش تأیید شد" in text and "manager:telegram:111" in text and "#7" in text and "مدیر اضافه شد" in text
    en_root, _p2 = make(env, lang="en")
    assert "Order confirmed" in collect_text(en_root) and "Add an admin" in collect_text(en_root)


def test_unknown_audit_actions_fall_back_to_the_raw_code(env):
    env.admins.audit("something_new", actor="x")
    root, _p = make(env)
    assert "something_new" in collect_text(root)


# --------------------------------------------------------- ابزارها و منو ----

def test_qr_png_is_valid_and_depends_on_the_payload():
    a, b = qr.png_bytes("https://t.me/a?start=admin_1"), qr.png_bytes("https://t.me/a?start=admin_2")
    assert a.startswith(b"\x89PNG\r\n\x1a\n") and len(a) > 100 and a != b and a == qr.png_bytes("https://t.me/a?start=admin_1")


def test_invite_link_helpers():
    assert am.invite_link("telegram", "@Shop_Bot", "tok") == "https://t.me/Shop_Bot?start=admin_tok"
    assert am.invite_link("bale", "shop", "tok") == "https://ble.ir/shop?start=admin_tok"
    assert am.invite_link("signal", "shop", "tok") == "" and am.invite_link("telegram", "", "tok") == "" and am.invite_link("telegram", "  ", "t") == ""
    assert am.start_command("tok") == "/start admin_tok"


def boot(business_mode="store"):
    bot_manager._manager = None  # noqa: SLF001
    onboarded()
    state = settings_module.load_settings()
    state.business_mode = business_mode
    settings_module.save_settings(state)
    page = FakePage()
    main(page, checker=StubChecker(None), start_update_thread=False, quit_app=lambda: None)
    return page


def test_admins_page_is_in_the_store_sidebar_and_opens():
    page = boot("store")
    nav = find(page.controls[0].content, "nav_admins")
    assert nav is not None
    fire(nav, "on_click")
    view = page.controls[0].content
    assert find(view, "admins_invite") is not None and "مدیرانِ ربات" in collect_text(view)


def test_admins_page_is_hidden_for_consultants():
    page = boot("consultant")
    assert find(page.controls[0].content, "nav_admins") is None and find(page.controls[0].content, "nav_customers") is not None
