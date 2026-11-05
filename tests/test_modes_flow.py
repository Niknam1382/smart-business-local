"""R2 (نسخه‌ی ۱.۰.۰) — دقیقاً دو حالتِ کاری: ``advisor`` (مشاوره‌ای، بدونِ دکمه) و ``shop_buttons`` (فروشگاه).

 ``faq_support`` و ``lead_capture`` و ``settings.shop_mode``/``shop_mode_overrides`` حذف شده‌اند؛
 این فایل همان را میخکوب می‌کند (روی کدِ قدیمی این تست‌ها یکی‌یکی می‌شکنن):
 * منوی فروشگاه **دقیقاً** چهار دکمه است و راهنما/FAQ/دکمه‌های سفارشی فقط زیرِ «ارتباط با پشتیبانی»اند.
 * در حالتِ مشاوره‌ای هیچ کیبوردی نمی‌رود، متنِ آزاد مصرف نمی‌شود (به AI می‌رود) و هیچ فعلِ
   ``c:*`` فروشی پذیرفته نمی‌شود.
"""

import asyncio
from types import SimpleNamespace

import pytest
from fakes import FakeEngine
from shop_harness import Harness, datas, labels, menu, texts

from app.core import ai_engine, modes
from app.core.attention import AttentionInbox
from app.core.bot_pipeline import ConversationPipeline, IncomingMessage
from app.core.conversations import ConversationStore
from app.core.settings import AppSettings

MENU = ["🛍 محصولات", "🧺 سبد خرید", "📦 سفارش\u200cهای من", "🙋 ارتباط با پشتیبانی"]
SUPPORT = {"id": "support", "label": "تماس با ما", "emoji": "🙋", "action": "text", "config": {"text": "۰۲۱-۱۲۳۴"}}
SHOP_VERBS = ("c:l:-:1", "c:cart", "c:co", "c:ck:ok", "c:o", "c:od:1", "c:a:1:1:-:1", "c:pm:card_to_card", "c:paid:1", "c:op:1", "c:inv:1")


def make(tmp_path, business_mode="consultant", **kw):
    h = Harness(tmp_path, business_mode=business_mode, **kw)
    h.flow.attention = AttentionInbox(ConversationStore(tmp_path / "c.db"))
    return h


# ================================================================ ثبتِ حالت‌ها ====

def test_only_two_modes_exist_and_the_legacy_ones_are_gone():
    assert modes.mode_ids() == ["advisor", "shop_buttons"]
    assert set(modes.MODES) == {"advisor", "shop_buttons"}
    for gone in ("faq_support", "lead_capture", "shop_ai"):
        assert gone not in modes.MODES
    # فیلدهایِ حذف‌شده هرگز برننمی‌گردن (UI/تنظیماتِ قدیمی بی‌صدا دور ریخته می‌شن)
    for gone in ("shop_mode", "shop_mode_overrides"):
        assert not hasattr(AppSettings(), gone), gone
        with pytest.raises(TypeError):  # سازنده هم دیگر آن کلیدها را نمی‌شناسد
            AppSettings(**{gone: "faq_support"})


def test_a_legacy_settings_file_drops_the_deleted_mode_keys():
    """settings.json قدیمی (با shop_mode/overrides) بدونِ خطا بارگذاری می‌شه و آن کلیدها برنمی‌گردن."""
    from app.core.paths import get_app_data_dir
    from app.core.settings import load_settings, save_settings

    path = get_app_data_dir() / "settings.json"
    path.write_text('{"business_mode": "store", "shop_mode": "faq_support", "shop_mode_overrides": {"bale": "advisor"}}', encoding="utf-8")
    s = load_settings()
    assert s.business_mode == "store" and not hasattr(s, "shop_mode")
    save_settings(s)  # ذخیره‌ی دوباره هم کلیدِ حذف‌شده را زنده نمی‌کند
    assert "shop_mode" not in path.read_text(encoding="utf-8")


def test_resolve_mode_is_safe_for_every_input():
    assert modes.resolve_mode(AppSettings(business_mode="store")).id == "shop_buttons"
    assert modes.resolve_mode(AppSettings(business_mode="consultant")).id == "advisor"
    assert modes.resolve_mode(AppSettings()).id == "advisor"  # هنوز انتخاب نکرده ← امن‌ترین حالت
    assert modes.resolve_mode(AppSettings(business_mode="nonsense")).id == "advisor"
    assert modes.resolve_mode(None).id == "advisor"
    assert modes.is_store(AppSettings(business_mode="store")) is True
    assert modes.is_store(AppSettings(business_mode="consultant")) is False
    assert modes.is_store(None) is False
    # platform پارامترِ سازگاری است، نه منبعِ تصمیم: هیچ override ای دیگر وجود ندارد
    s = AppSettings(business_mode="store")
    assert modes.resolve_mode(s, "telegram").id == modes.resolve_mode(s, "bale").id == "shop_buttons"
    legacy = SimpleNamespace(business_mode="store", shop_mode="shop_ai", shop_mode_overrides={"bale": "advisor"})
    assert modes.resolve_mode(legacy, "bale").id == "shop_buttons"  # مقادیرِ قدیمی فقط نادیده گرفته می‌شن


def test_mode_registry_capabilities_are_consistent():
    for mode in modes.MODES.values():
        if mode.cart:
            assert mode.buttons and mode.needs_store and mode.ai_qa
    advisor = modes.MODES["advisor"]
    assert not any((advisor.buttons, advisor.cart, advisor.fields, advisor.handoff, advisor.faq, advisor.needs_store))


# =============================================================== فروشگاه: منو ====

def test_store_menu_is_exactly_the_four_requested_buttons(tmp_path):
    h = make(tmp_path, "store", faq_items=[{"q": "ارسال؟", "a": "۲ روزه"}], custom_buttons=[SUPPORT])
    flat = [b for row in menu(h.say("/start")) for b in row]
    assert flat == MENU, "دقیقاً همان چهار دکمه؛ نه راهنما، نه FAQ، نه دکمه‌ی سفارشی"
    assert "📦 سفارش\u200cهای من" in flat  # برچسبِ «سفارش‌هام» دیگر استفاده نمی‌شه
    assert not any("راهنما" in b or "سؤالات متداول" in b for b in flat)
    # شمارنده‌ی سبد فقط داخلِ همان دکمه اضافه می‌شه، نه دکمه‌ی تازه
    pid = h.add_product()
    h.tap(f"c:a:{pid}:2:-:1")
    flat2 = [b for row in menu(h.say("/menu")) for b in row]
    assert flat2 == ["🛍 محصولات", "🧺 سبد خرید (2)", "📦 سفارش\u200cهای من", "🙋 ارتباط با پشتیبانی"]


def test_faq_guide_and_custom_buttons_live_behind_the_support_button(tmp_path):
    h = make(tmp_path, "store", faq_items=[{"q": "ارسال چند روزه؟", "a": "دو روز کاری"}], custom_buttons=[SUPPORT])
    res = h.say("🙋 ارتباط با پشتیبانی")
    assert res.consumed
    btns = {d for d in datas(res)}
    assert {"c:f:1", "c:g:1", "c:b:support", "c:m"} <= btns, "FAQ و راهنما و دکمه‌های سفارشی زیرِ پشتیبانی"
    faq = h.tap("c:f:1")
    assert "c:fa:0" in datas(faq) and "ارسال چند روزه؟" in labels(faq)
    assert "دو روز کاری" in texts(h.tap("c:fa:0"))
    assert "۰۲۱-۱۲۳۴" in texts(h.tap("c:b:support"))
    assert "🛍 محصولات" in texts(h.say("/help"))  # راهنما با فرمان هم باز می‌شه
    assert menu(h.tap("c:m")) and [b for row in menu(h.tap("c:m")) for b in row] == MENU


def test_store_text_commands_still_work(tmp_path):
    h = make(tmp_path, "store")
    pid = h.add_product()
    for command, needle in (("/start", "🛍 محصولات"), ("/menu", "🛍 محصولات"), ("/products", "محصولات"), ("/cart", "سبد"), ("/orders", "سفارش")):
        res = h.say(command)
        assert res.consumed, command
        assert needle in texts(res) or needle in str(menu(res)), (command, texts(res))
    assert h.say("/checkout").consumed  # سبدِ خالی ← پیامِ سبد، نه خطا
    assert h.say("/faq").consumed and h.say("/support").consumed
    h.tap(f"c:a:{pid}:1:-:1")
    assert "c:co" in datas(h.say("/cart"))
    assert h.say("/checkout").consumed and h.flow.sessions.get("telegram", "1") is not None
    h.tap("c:ck:x")


# ============================================================ مشاوره‌ای: هیچ دکمه ====

def test_advisor_mode_has_no_keyboard_and_rejects_every_shop_callback(tmp_path):
    h = make(tmp_path, "consultant", faq_items=[{"q": "سؤال", "a": "پاسخ"}], custom_buttons=[SUPPORT])
    res = h.say("/start")
    assert [row for row in menu(res)] == [], "در حالتِ مشاوره هیچ کیبوردی نمی‌رود"
    assert h.say("سلام").consumed is False  # متنِ آزاد ← AI
    assert h.say("🛍 محصولات").consumed is False  # برچسبِ منویِ فروشگاه هم فقط متنِ آزاد است
    for data in SHOP_VERBS:
        tapped = h.tap(data)
        assert tapped.answer, f"{data} باید رد شود"
        assert not any(d.startswith(("c:p:", "c:a:", "c:s:", "c:pm:")) for d in datas(tapped)), data
        assert h.flow.sessions.get("telegram", "1") is None
    assert h.orders.list() == [] and h.flow.carts.count("telegram", "1") == 0


def test_advisor_mode_never_touches_the_cart_or_orders(tmp_path):
    """حتی اگر کسی callback فروشگاهی را «بفرستد» (کلیکِ قدیمی روی پیامِ ۱.۰)، چیزی ساخته نمی‌شه."""
    h = make(tmp_path, "consultant")
    pid = h.add_product()
    for data in (f"c:a:{pid}:1:-:1", "c:cart", "c:co", "c:ck:ok", "c:pm:card_to_card"):
        assert h.tap(data).answer
    assert h.flow.carts.get("telegram", "1") == []
    assert h.orders.list() == []
    assert h.owner_alerts == []


def test_the_pipeline_never_hands_the_advisor_a_shop_surface(tmp_path, monkeypatch):
    """در حالتِ مشاوره‌ای پایپ‌لاین اصلاً ShopFlow را صدا نمی‌زند ⇒ هیچ کیبورد/دکمه‌ای ممکن نیست."""
    h = make(tmp_path, "consultant")
    h.settings.system_prompt = "مشاورِ کتاب."
    seen = []
    original = h.flow.handle

    async def spy(ev):
        seen.append(ev)
        return await original(ev)

    monkeypatch.setattr(h.flow, "handle", spy)
    monkeypatch.setattr(ai_engine, "build_engine_from_settings", lambda s: FakeEngine())
    pipeline = ConversationPipeline(
        h.settings, store=ConversationStore(tmp_path / "p.db"), shop_flow=h.flow,
        debounce_wait=0.05, debounce_max_wait=0.2,
    )
    sent = []

    async def go():
        async def send(text, **_kw):
            sent.append(text)

        await pipeline.handle_incoming(IncomingMessage("telegram", "1", "علی", "/start"), send)
        await pipeline.handle_incoming(
            IncomingMessage("telegram", "1", "علی", "", callback_data="c:l:-:1", callback_id="cb1"), send
        )
        await pipeline.handle_incoming(IncomingMessage("telegram", "1", "علی", "🛍 محصولات"), send)
        await asyncio.sleep(0.6)  # سیگنالِ مثبتِ پایانِ کارِ debounce: جوابِ AI آمده
        await pipeline.shutdown()

    asyncio.run(go())
    assert seen == [], "هیچ رویدادی به ShopFlow نرفت (نه منو، نه کلیکِ قدیمی)"
    assert h.orders.list() == [] and h.flow.carts.get("telegram", "1") == []
    assert any("هوش مصنوعی" in s for s in sent), sent  # فقط خطِ شفافیت + جوابِ مدل
    assert any(s.startswith("پاسخ:") for s in sent), sent
