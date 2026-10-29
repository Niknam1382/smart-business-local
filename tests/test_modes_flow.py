"""R2 — حالت‌های «پاسخ‌گویی + پشتیبانی» و «جمع‌آوریِ سرنخ» (بدونِ سبد/فروش)، و ثبتِ حالت‌ها."""


from shop_harness import Harness, datas, texts

from app.core import modes
from app.core.attention import AttentionInbox
from app.core.conversations import ConversationStore
from app.core.settings import AppSettings

SUPPORT = {"id": "support", "label": "پشتیبانی", "emoji": "🙋", "action": "support", "config": {}}


def make(tmp_path, mode, **kw):
    h = Harness(tmp_path, business_mode="consultation", shop_mode=mode, **kw)
    h.flow.attention = AttentionInbox(ConversationStore(tmp_path / "c.db"))
    return h


def test_resolve_mode_is_safe_for_every_input():
    assert modes.resolve_mode(AppSettings(business_mode="store")).id == "shop_buttons"
    assert modes.resolve_mode(AppSettings(business_mode="consultation")).id == "advisor"
    assert modes.resolve_mode(AppSettings(business_mode="consultation", shop_mode="shop_buttons")).id == "advisor"  # فروشگاه برای مشاور ممنوع
    assert modes.resolve_mode(AppSettings(business_mode="consultation", shop_mode="lead_capture")).id == "lead_capture"
    assert modes.resolve_mode(AppSettings(business_mode="store", shop_mode="nonsense")).id == "shop_buttons"
    s = AppSettings(business_mode="store", shop_mode="shop_buttons", shop_mode_overrides={"bale": "advisor", "telegram": 5})
    assert modes.resolve_mode(s, "bale").id == "advisor" and modes.resolve_mode(s, "telegram").id == "shop_buttons"
    s.shop_mode_overrides = "garbage"
    assert modes.resolve_mode(s, "bale").id == "shop_buttons"
    assert modes.resolve_mode(None).id == "advisor"


def test_faq_support_menu_has_no_shop_rows_and_shop_callbacks_are_rejected(tmp_path):
    h = make(tmp_path, "faq_support", faq_items=[{"q": "ارسال؟", "a": "۲ روزه"}], custom_buttons=[SUPPORT])
    menu = h.say("/start").messages[0].menu
    flat = [b for row in menu for b in row]
    assert flat == ["❓ سؤالات متداول", "🙋 پشتیبانی"]
    for data in ("c:l:-:1", "c:cart", "c:co", "c:o", "c:a:1:1:-:1", "c:pm:card_to_card"):
        res = h.tap(data)
        assert res.answer and res.messages and not any(d.startswith(("c:p:", "c:a:")) for d in datas(res))
    assert h.say("🛍 محصولات").consumed is False  # منو چنین چیزی نداره → متنِ آزاد (AI)
    assert "ارسال؟" in texts(h.say("❓ سؤالات متداول")) or any("c:fa:0" in d for d in datas(h.say("❓ سؤالات متداول")))
    assert "۲ روزه" in texts(h.tap("c:fa:0"))


def test_lead_capture_wizard_notifies_owner_and_stores_inbox_entry(tmp_path):
    h = make(tmp_path, "lead_capture", custom_buttons=[SUPPORT])
    menu = h.say("/start").messages[0].menu
    assert menu[0] == ["📝 ثبت درخواست", "🙋 پشتیبانی"]
    res = h.say("📝 ثبت درخواست")
    assert "نام" in texts(res) and "c:ck:x" in datas(res)
    assert h.flow.sessions.get("telegram", "1").data["fields"] == ["name", "phone", "notes"]  # آدرس/کدپستیِ فیزیکی نیست
    assert "⚠️" in texts(h.say("0"))
    h.say("مریم احمدی")
    assert "موبایل" in texts(h.say("12345"))  # شماره‌ی نامعتبر → دوباره می‌پرسه
    res = h.say("۰۹۱۲۱۲۳۴۵۶۷")
    assert "توضیحات" in texts(res)
    res = h.say("درباره‌ی مشاوره‌ی حقوقی می‌خوام")
    assert "ثبت شد" in texts(res) and res.messages[0].menu and h.flow.sessions.get("telegram", "1") is None
    assert len(h.owner_alerts) == 1 and "مریم احمدی" in h.owner_alerts[0] and "09121234567" in h.owner_alerts[0] and "مشاوره‌ی حقوقی" in h.owner_alerts[0]
    [item] = h.flow.attention.list_open()
    assert item.type == "lead" and "09121234567" in item.detail and item.ref == "telegram:1"
    assert h.say("سلام").consumed is False  # بعد از پایان، متنِ آزاد به AI می‌ره


def test_lead_wizard_cancel_back_and_stale_checkout_buttons(tmp_path):
    h = make(tmp_path, "lead_capture")
    h.say("📝 ثبت درخواست")
    h.say("مریم")
    res = h.tap("c:ck:b")
    assert "نام" in texts(res)
    assert "c:ck:ok" not in datas(res)
    h.say("مریم"); h.say("09121234567")
    res = h.tap("c:ck:s")  # رد کردنِ «توضیحات» (اختیاری) → پایان
    assert "ثبت شد" in texts(res) and len(h.owner_alerts) == 1
    h.say("📝 ثبت درخواست")
    res = h.tap("c:ck:x")
    assert "لغو" in texts(res) and h.flow.sessions.get("telegram", "1") is None
    assert len(h.owner_alerts) == 1  # لغو = اعلانِ مالک نمی‌ره


def test_advisor_mode_has_no_flow_surface_in_the_pipeline_but_flow_menu_is_empty(tmp_path):
    h = make(tmp_path, "advisor")
    # پایپ‌لاین در حالتِ مشاور اصلاً ShopFlow رو صدا نمی‌زنه؛ اگه مستقیم صدا زده بشه هم چیزی نشون نمی‌ده
    res = h.say("/start")
    assert res.messages[0].menu == []
    assert h.tap("c:l:-:1").answer


def test_mode_registry_capabilities_are_consistent():
    for mode in modes.MODES.values():
        if mode.cart:
            assert mode.buttons and mode.needs_store
        if mode.store_agent:
            assert not mode.buttons  # AIِ سفارش‌گیر و دکمه‌ها هم‌زمان نیستن
    assert modes.mode_ids() == ["advisor", "shop_buttons", "shop_ai", "faq_support", "lead_capture"]
