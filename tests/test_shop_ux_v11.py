"""۱.۱ — N4/N5: آیکن‌های بله، منوی چهاردکمه‌ای، زیرمنوی «راهنما»، سبدِ تک‌ردیفی و سقفِ دکمه‌ها."""

import pytest

from app.core import ui_glyphs
from app.core.cart import MAX_CART_LINES
from tests.shop_harness import Harness, datas, labels, texts


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


def seed(h, n=2, **kw):
    return [h.products.add(f"کالا {i + 1}", 1000 * (i + 1), 50, **kw) for i in range(n)]


def buttons(res):
    return [b for m in res.messages for row in m.rows for b in row]


def custom(i, action="text", **config):
    base = {"text": f"پاسخ {i}"} if action == "text" else config
    return {"id": f"b{i}", "label": f"دکمه {i}", "action": action, "config": base}


# ============================================================ منوی ثابت (N5) ====

def test_persistent_menu_is_exactly_four_buttons_even_with_faq_and_custom_buttons(h):
    h.settings.faq_items = [{"q": "ارسال چند روزه است؟", "a": "۳ روز"}]
    h.settings.custom_buttons = [custom(1), custom(2), custom(3)]
    menu = h.say("/start").messages[0].menu
    assert menu == [["🛍 محصولات", "🧺 سبد خرید"], ["📦 سفارش‌هام", "ℹ️ راهنما"]]
    assert sum(len(r) for r in menu) == 4


def test_legacy_keyboard_labels_from_v1_0_0_still_work(h):
    [pid] = seed(h, 1)
    h.tap(f"c:a:{pid}:1:-:1")
    old_checkout = h.say("✅ نهایی کردن سفارش")  # کیبوردِ قدیمیِ مشتری
    assert old_checkout.consumed and h.flow.sessions.get("telegram", "1") is not None
    h.tap("c:ck:x")
    assert h.say("📦 پیگیری سفارش").consumed  # برچسبِ قدیمیِ «پیگیری سفارش»
    assert h.say("/checkout").consumed and h.say("/orders").consumed  # فرمان‌ها سر جاشونن


def test_checkout_button_lives_inside_the_cart_message_only(h):
    [pid] = seed(h, 1)
    h.tap(f"c:a:{pid}:1:-:1")
    assert "c:co" in datas(h.tap("c:cart"))
    assert not any("نهایی" in item for row in h.say("/menu").messages[0].menu for item in row)


# =========================================================== زیرمنوی راهنما ====

def test_guide_shows_faq_and_first_two_custom_buttons_then_more(h):
    h.settings.faq_items = [{"q": "ارسال چند روزه است؟", "a": "۳ روز"}]
    h.settings.custom_buttons = [
        custom(1, "url", url="https://example.com/rules", caption="قوانین"),
        custom(2),
        custom(3),
        custom(4),
    ]
    res = h.say("ℹ️ راهنما")
    btns = buttons(res)
    assert [b.label for b in btns] == ["❓ سؤالات متداول", "دکمه 1", "دکمه 2", "بیشتر ◀"]
    assert btns[0].data == "c:f:1" and btns[1].url == "https://example.com/rules" and btns[1].data == ""  # لینک = یک لمس
    assert btns[2].data == "c:b:b2" and btns[3].data == "c:g:2"
    page2 = h.tap("c:g:2")
    assert [b.label for b in buttons(page2)] == ["دکمه 3", "دکمه 4", "↩️ بازگشت"]
    assert page2.messages[0].edit is True
    assert h.tap("c:g:1").messages[0].rows[-1][0].data == "c:g:2"
    assert h.tap("c:b:b3").consumed  # دکمه‌ی سفارشی از زیرمنو کار می‌کند


def test_guide_second_page_paginates_long_custom_lists(h):
    h.settings.custom_buttons = [custom(i) for i in range(1, 9)]  # ۸ دکمه (سقفِ مجاز)
    p1 = h.tap("c:g:1")
    assert len([b for b in buttons(p1) if b.data.startswith("c:b:")]) == 2
    p2 = h.tap("c:g:2")
    assert len([b for b in buttons(p2) if b.data.startswith("c:b:")]) == 6
    assert h.tap("c:g:99").messages  # صفحه‌ی بیرون از محدوده کلمپ می‌شود، نه خطا


def test_guide_callbacks_never_raise_on_garbage(h):
    for data in ("c:g", "c:g:x", "c:g:-5", "c:g:99999999999", "c:g:1:2:3"):
        res = h.tap(data)
        assert res.messages  # راهنما یا منوی دوستانه


def test_guide_without_faq_or_buttons_still_explains_the_next_step(h):
    res = h.say("ℹ️ راهنما")
    assert "محصولات" in texts(res) and buttons(res) == []


def test_help_command_opens_guide_in_shop_mode_and_welcome_in_other_modes(h):
    assert "ℹ️ راهنما" in texts(h.say("/help"))
    h.settings.shop_mode = "faq_support"
    assert "خوش اومدی" in texts(h.say("/help"))


def test_other_modes_keep_faq_and_custom_buttons_in_the_keyboard(tmp_path):
    h2 = Harness(tmp_path, shop_mode="faq_support")
    h2.settings.faq_items = [{"q": "سؤال", "a": "پاسخ"}]
    h2.settings.custom_buttons = [custom(1)]
    menu = h2.say("/start").messages[0].menu
    assert ["❓ سؤالات متداول", "دکمه 1"] in menu and not any("ℹ️ راهنما" in r for r in menu)


# ================================================================= سبد (N5/N4) ====

def cart_with(h, qty, platform="telegram", chat="1"):
    existing = h.products.list()
    pid = existing[0].id if existing else seed(h, 1)[0]
    h.tap(f"c:a:{pid}:{qty}:-:1", chat=chat, platform=platform)
    return pid, h.tap("c:cart", chat=chat, platform=platform)


def test_cart_item_row_is_minus_name_plus_and_minus_becomes_remove_at_one(h):
    pid, res = cart_with(h, 2)
    row = res.messages[0].rows[0]
    assert [b.label for b in row] == ["➖", "2× کالا 1", "➕"]
    assert [b.data for b in row] == [f"c:s:{pid}:1", "c:n", f"c:s:{pid}:3"]
    pid1, res1 = cart_with(h, 1, chat="2")
    row1 = res1.messages[0].rows[0]
    assert row1[0].label == "🗑" and row1[0].data == f"c:s:{pid1}:0"  # تعدادِ ۱ ⇒ «−» حذف می‌کند


def test_cart_bottom_row_is_clear_and_place_order_with_no_extra_buttons(h):
    _pid, res = cart_with(h, 2)
    last = res.messages[0].rows[-1]
    assert [b.label for b in last] == ["🧹 خالی\u200cکردنِ سبد", "✅ ثبتِ سفارش"]
    assert [b.data for b in last] == ["c:cl", "c:co"]
    assert len(res.messages[0].rows) == 2  # یک قلم + ردیفِ پایانی


def test_product_list_bottom_has_only_cart_and_categories(h):
    seed(h, 2, category="لوازم")
    res = h.tap("c:l:-:1")
    assert [b.data for b in res.messages[0].rows[-1]] == ["c:cart", "c:k"]


def test_cart_stepper_buttons_actually_change_quantity_and_remove(h):
    pid, _ = cart_with(h, 2)
    h.tap(f"c:s:{pid}:3")
    assert h.flow.carts.quantity("telegram", "1", pid) == 3
    h.tap(f"c:s:{pid}:0")
    assert h.flow.carts.get("telegram", "1") == []


# =================================================== بله: هیچ برچسبِ فقط‌ایموجی ====

def walk_views(h, platform):
    """همه‌ی نماهایی که دکمه می‌سازن را برای یک پلتفرم می‌گردد و نتیجه‌ها را برمی‌گرداند."""
    pids = seed(h, 8, category="لوازم")
    h.settings.faq_items = [{"q": f"سؤال {i}", "a": f"پاسخ {i}"} for i in range(8)]
    h.settings.custom_buttons = [custom(1, "url", url="https://example.com", caption="x"), custom(2), custom(3)]
    results = []

    def tap(data):
        res = h.tap(data, platform=platform)
        results.append(res)
        return res

    results.append(h.say("/start", platform=platform))
    results.append(h.say("🛍 محصولات", platform=platform))
    for data in ("c:k", "c:l:-:1", "c:l:-:2"):
        tap(data)
    tap(f"c:p:{pids[0]}:-:1")
    tap(f"c:q:{pids[0]}:3:-:1")
    tap(f"c:a:{pids[0]}:2:-:1")
    tap(f"c:p:{pids[0]}:-:1")  # در سبد
    tap(f"c:a:{pids[1]}:1:-:1")
    tap("c:cart")
    h.products.set_active(pids[1], False)  # قلمِ سبد ناپدید شد ⇒ دکمه‌ی «اصلاحِ خودکار» هم ساخته می‌شود
    tap("c:fix")
    tap("c:cl")
    tap("c:g:1")
    tap("c:g:2")
    tap("c:f:1")
    tap("c:fa:0")
    tap("c:b:b2")
    results += h.flow.suggestion_cards(platform, "1", pids[:2])
    return results


def flatten(results):
    out = []
    for r in results:
        msgs = r.messages if hasattr(r, "messages") else [r]
        for m in msgs:
            out += [b for row in m.rows for b in row]
    return out


def test_bale_has_no_emoji_only_labels_and_no_heavy_plus_minus_in_any_view(tmp_path):
    h = Harness(tmp_path)
    btns = flatten(walk_views(h, "bale"))
    assert btns
    bad = [b.label for b in btns if ui_glyphs.is_emoji_only(b.label)]
    assert not bad, f"برچسبِ فقط‌ایموجی برای بله: {bad}"
    joined = " ".join(b.label for b in btns)
    for glyph in ("➖", "➕", "🗑"):
        assert glyph not in joined


def test_telegram_keeps_familiar_glyphs(tmp_path):
    h = Harness(tmp_path)
    joined = " ".join(b.label for b in flatten(walk_views(h, "telegram")))
    assert "➖" in joined and "➕" in joined


def test_bale_cart_uses_text_minus_plus_and_remove_word(tmp_path):
    h = Harness(tmp_path)
    [pid] = seed(h, 1)
    h.tap(f"c:a:{pid}:2:-:1", platform="bale")
    row = h.tap("c:cart", platform="bale").messages[0].rows[0]
    assert [b.label for b in row] == ["−", "2× کالا 1", "+"]
    h.tap(f"c:s:{pid}:1", platform="bale")
    assert h.tap("c:cart", platform="bale").messages[0].rows[0][0].label == "حذف"


def test_all_views_respect_platform_button_caps_even_for_a_full_cart(tmp_path):
    h = Harness(tmp_path)
    pids = seed(h, MAX_CART_LINES)
    for pid in pids:
        h.tap(f"c:a:{pid}:1:-:1")
    res = h.tap("c:cart")
    msg = res.messages[0]
    assert sum(len(r) for r in msg.rows) <= 100  # سقفِ دکمه‌ی تلگرام در یک پیام
    assert all(len(r) <= 8 for r in msg.rows)
    for lbl in labels(res):
        assert len(lbl) <= 48


def test_ui_glyphs_have_labels_for_every_platform_and_language():
    for platform in ("telegram", "bale"):
        for lang in ("fa", "en"):
            g = ui_glyphs.for_platform(platform, lang)
            assert g.minus and g.plus and g.remove and g.details
