"""R8 — صفحه‌ی «تجربه‌ی ربات» با Page جعلی: هر بخش ذخیره می‌کنه، ورودیِ نامعتبر رد می‌شه، چیزی گم نمی‌شه."""

from types import SimpleNamespace

from fake_page import FakePage, collect_text, find, fire

from app.core import checkout_fields as cf
from app.core import shop_texts
from app.core.attention import AttentionInbox
from app.core.conversations import ConversationStore
from app.core.orders import OrderStore
from app.core.products import ProductStore
from app.core.settings import AppSettings
from app.screens import bot_experience


class Env:
    def __init__(self, tmp_path, business_mode="store", manager=None):
        self.settings = AppSettings(business_mode=business_mode)
        self.saves = 0
        self.products = ProductStore(tmp_path / "p.db")
        self.orders = OrderStore(tmp_path / "o.db", product_store=self.products)
        self.page = FakePage()
        self.control = bot_experience.build(self.page, "fa", self.settings, self._save, self.products, self.orders, manager)

    def _save(self):
        self.saves += 1

    def f(self, key):
        found = find(self.control, key)
        assert found is not None, key
        return found

    def click(self, key):
        fire(self.f(key), "on_click")

    def note(self, key):
        n = self.f(key)
        return n.value if n.visible else ""


def test_builds_for_store_and_consultant_with_correct_mode_options(tmp_path):
    store = Env(tmp_path / "a", "store")
    # N3: سه حالتِ اصلی؛ «سفارش با AI» و «جمع‌آوریِ درخواست» پشتِ سوئیچِ «پیشرفته»
    assert {o.key for o in store.f("exp_mode").options} == {"advisor", "shop_buttons", "faq_support"}
    fire(store.f("exp_show_advanced_modes"), "on_change", value=True)
    assert {o.key for o in store.f("exp_mode").options} == {"advisor", "shop_buttons", "shop_ai", "faq_support", "lead_capture"}
    assert store.f("exp_mode").value == "shop_buttons"
    consult = Env(tmp_path / "b", "consultation")
    assert {o.key for o in consult.f("exp_mode").options} == {"advisor", "faq_support"}
    fire(consult.f("exp_show_advanced_modes"), "on_change", value=True)
    assert {o.key for o in consult.f("exp_mode").options} == {"advisor", "faq_support", "lead_capture"}
    assert consult.f("exp_mode").value == "advisor"
    # حالتِ پیشرفته‌ی فعلی همیشه در فهرست می‌مونه (حتی با سوئیچِ خاموش)
    adv = Env(tmp_path / "c", "store")
    adv.settings.shop_mode = "shop_ai"
    again = bot_experience.build(FakePage(), "fa", adv.settings, lambda: None, adv.products, adv.orders, None)
    assert "shop_ai" in {o.key for o in find(again, "exp_mode").options} and find(again, "exp_show_advanced_modes").value is True


def test_mode_save_validates_and_persists(tmp_path):
    e = Env(tmp_path)
    e.f("exp_mode").value, e.f("exp_lang").value = "shop_ai", "en"
    e.f("exp_page_size").value, e.f("exp_max_qty").value = "۸", "5"
    e.f("exp_disclosure").value = False
    e.click("exp_mode_save")
    s = e.settings
    assert (s.shop_mode, s.bot_language, s.catalog_page_size, s.max_qty_per_item, s.ai_disclosure_enabled) == ("shop_ai", "en", 8, 5, False)
    assert e.saves == 1 and "ذخیره" in e.note("exp_mode_note")
    e.f("exp_page_size").value = "99"
    e.click("exp_mode_save")
    assert "2 و 12" in e.note("exp_mode_note") and s.catalog_page_size == 8 and e.saves == 1  # رد شد؛ چیزی عوض نشد
    e.f("exp_page_size").value = "abc"
    e.click("exp_mode_save")
    assert s.catalog_page_size == 8


def test_checkout_fields_add_edit_validate_move_delete_templates(tmp_path):
    e = Env(tmp_path)
    assert len(e.settings.checkout_fields) == 0 and len(e.f("exp_fields_list").controls) == 5  # پیش‌فرض‌ها نمایش داده می‌شن
    e.click("fld_add")
    e.f("fld_id").value, e.f("fld_label").value, e.f("fld_prompt").value = "city", "شهر", "شهر؟"
    e.f("fld_type").value = "choice"
    e.f("fld_choices").value = "تهران\nشیراز"
    e.click("fld_save")
    assert len(e.settings.checkout_fields) == 6 and e.settings.checkout_fields[-1]["choices"] == ["تهران", "شیراز"] and e.saves == 1
    assert [f.id for f in cf.load_fields(e.settings)][-1] == "city"
    # regex نامعتبر / شناسه‌ی تکراری / انتخابیِ بدونِ گزینه رد می‌شه
    e.click("fld_add")
    e.f("fld_id").value, e.f("fld_label").value, e.f("fld_prompt").value, e.f("fld_regex").value = "bad", "ب", "؟", "([a-"
    e.f("fld_type").value = "text"
    e.click("fld_save")
    assert "regex" in e.note("exp_fields_note") and len(e.settings.checkout_fields) == 6
    e.f("fld_regex").value, e.f("fld_id").value = "", "name"
    e.click("fld_save")
    assert "تکراری" in e.note("exp_fields_note")
    e.f("fld_id").value, e.f("fld_type").value, e.f("fld_choices").value = "x", "choice", ""
    e.click("fld_save")
    assert "گزینه" in e.note("exp_fields_note")
    # جابه‌جایی و حذف
    first = e.settings.checkout_fields[0]["id"]
    e.click("fld_down_0")
    assert e.settings.checkout_fields[1]["id"] == first
    e.click("fld_del_5")
    assert len(e.settings.checkout_fields) == 5
    e.f("fld_template").value = "services"
    e.click("fld_apply_tpl")
    assert [f["id"] for f in e.settings.checkout_fields] == ["name", "phone", "request"]
    e.click("fld_defaults")
    assert e.settings.checkout_fields == [] and len(e.f("exp_fields_list").controls) == 5
    e.f("fld_template").value = "services"  # حذفِ آخرین فیلد ممنوع
    e.click("fld_apply_tpl")
    e.click("fld_del_0"); e.click("fld_del_0")
    e.click("fld_del_0")
    assert "حداقل یک فیلد" in e.note("exp_fields_note") and len(e.settings.checkout_fields) == 1


def test_custom_buttons_add_validate_delete(tmp_path):
    e = Env(tmp_path)
    e.click("btn_add")
    e.f("btn_id").value, e.f("btn_label").value, e.f("btn_emoji").value, e.f("btn_action").value = "insta", "اینستاگرام", "📸", "url"
    e.f("btn_value").value = "tel:+98912"
    e.click("btn_save")
    assert "http" in e.note("exp_buttons_note") and e.settings.custom_buttons == []  # tel: در دکمه‌ی URL ممنوع
    e.f("btn_value").value = "https://instagram.com/shop"
    e.click("btn_save")
    assert e.settings.custom_buttons[0]["config"] == {"url": "https://instagram.com/shop"} and e.settings.custom_buttons[0]["platforms"] == ["telegram", "bale"]
    e.click("btn_add")
    e.f("btn_id").value, e.f("btn_label").value, e.f("btn_emoji").value, e.f("btn_action").value = "insta2", "اینستاگرام", "📸", "support"
    e.click("btn_save")
    assert "تکراری" in e.note("exp_buttons_note")
    e.f("btn_label").value = "پشتیبانی"
    e.f("btn_tg").value = False
    e.click("btn_save")
    assert e.settings.custom_buttons[1]["platforms"] == ["bale"] and e.settings.custom_buttons[1]["action"] == "support"
    e.click("btn_edit_0")
    assert e.f("btn_value").value == "https://instagram.com/shop" and e.f("btn_action").value == "url"
    e.click("btn_del_0")
    assert [b["id"] for b in e.settings.custom_buttons] == ["insta2"]


def test_faq_add_delete_and_limit(tmp_path):
    e = Env(tmp_path)
    e.click("faq_add")
    assert "الزامی" in e.note("exp_faq_note") or "؟" in e.note("exp_faq_note")
    e.f("faq_q").value, e.f("faq_a").value = "ارسال چقدر طول می‌کشه؟", "۲ تا ۴ روز کاری"
    e.click("faq_add")
    assert e.settings.faq_items == [{"q": "ارسال چقدر طول می‌کشه؟", "a": "۲ تا ۴ روز کاری"}] and e.f("faq_q").value == ""
    e.click("faq_del_0")
    assert e.settings.faq_items == []
    for i in range(30):
        e.f("faq_q").value, e.f("faq_a").value = f"q{i}", "a"
        e.click("faq_add")
    e.f("faq_q").value, e.f("faq_a").value = "extra", "a"
    e.click("faq_add")
    assert len(e.settings.faq_items) == 30 and "۳۰" in e.note("exp_faq_note")


def test_texts_override_validation_and_reset(tmp_path):
    e = Env(tmp_path)
    e.f("txt_key").value = "pay.left"
    fire(e.f("txt_key"), "on_select")
    assert "{minutes}" not in e.f("txt_default").value and "{تعدادِ دقیقه}" in e.f("txt_default").value  # N3: متغیرِ فارسی، نه placeholderِ خام
    assert e.f("txt_var_minutes").content == "{تعدادِ دقیقه}"
    e.f("txt_override").value = "⏰ {تعدادِ دقیقه} دقیقه فرصت داری"
    e.click("txt_save")
    assert shop_texts.render(e.settings, "pay.left", minutes=5) == "⏰ 5 دقیقه فرصت داری" and e.saves == 1
    assert e.settings.bot_texts["fa"]["pay.left"] == "⏰ {minutes} دقیقه فرصت داری"  # ذخیره‌شده همان قالبِ قدیمی (بدونِ مهاجرت)
    e.f("txt_override").value = "{تعدادِ دقیقه} {چیزِ ناشناخته}"
    e.click("txt_save")
    assert "قابل‌استفاده نیست" in e.note("txt_note") and shop_texts.render(e.settings, "pay.left", minutes=5) == "⏰ 5 دقیقه فرصت داری"  # قبلی سالم ماند
    e.f("txt_lang").value = "en"
    fire(e.f("txt_lang"), "on_select")
    assert e.f("txt_override").value == "" and "reserved" in e.f("txt_default").value
    e.f("txt_lang").value = "fa"
    fire(e.f("txt_lang"), "on_select")
    assert "فرصت" in e.f("txt_override").value and "{تعدادِ دقیقه}" in e.f("txt_override").value
    e.click("txt_reset")
    assert "pay.left" not in (e.settings.bot_texts.get("fa") or {})


def test_working_hours_and_support_timeout(tmp_path):
    e = Env(tmp_path)
    e.f("wh_enabled").value = True
    e.f("wh_sat").value = "09:00-13:00, 16:00-20:00"
    e.f("wh_mon").value = "9-17"
    e.click("wh_save")
    assert "بازه" in e.note("wh_note") and e.settings.working_hours == {}
    e.f("wh_mon").value = "08:30-17:00"
    e.f("wh_timeout").value = "12"
    e.f("wh_message").value = "فردا برمی‌گردیم"
    e.click("wh_save")
    wh = e.settings.working_hours
    assert wh["enabled"] and wh["days"]["sat"] == ["09:00-13:00", "16:00-20:00"] and wh["days"]["mon"] == ["08:30-17:00"] and "sun" not in wh["days"]
    assert e.settings.handoff_timeout_hours == 12 and wh["message"] == "فردا برمی‌گردیم"
    e.f("wh_timeout").value = "0"
    e.click("wh_save")
    assert e.settings.handoff_timeout_hours == 12  # نامعتبر رد شد


def test_limits_save_kill_switch_and_usage_line(tmp_path):
    conv = ConversationStore(tmp_path / "c.db")
    from app.core.usage_limits import UsageLimiter

    settings_holder = AppSettings(business_mode="store", max_ai_messages_per_day_total=50)
    limiter = UsageLimiter(conv, lambda: settings_holder)
    limiter.record_ai("telegram", "1", 300)
    manager = SimpleNamespace(limits=limiter, attention=AttentionInbox(conv))
    e = Env(tmp_path, manager=manager)
    assert "1 پاسخِ AI" in e.f("lim_usage").value
    e.f("lim_per_chat").value, e.f("lim_total").value, e.f("lim_retention").value = "۳۰", "500", "90"
    e.click("lim_save")
    s = e.settings
    assert (s.max_ai_messages_per_chat_per_day, s.max_ai_messages_per_day_total, s.retention_days) == (30, 500, 90)
    e.f("lim_total").value = "-4"
    e.click("lim_save")
    assert s.max_ai_messages_per_day_total == 500
    saves = e.saves
    e.f("lim_kill").value = True
    fire(e.f("lim_kill"), "on_change")
    assert s.ai_kill_switch is True and e.saves == saves + 1  # فوری، بدونِ دکمه‌ی ذخیره


def test_attention_inbox_list_and_mark_done(tmp_path):
    conv = ConversationStore(tmp_path / "c.db")
    inbox = AttentionInbox(conv)
    first = inbox.add("delivery_failed", "12", "ربات خاموش")
    inbox.add("support_no_owner", "t55", "")
    e = Env(tmp_path, manager=SimpleNamespace(attention=inbox, limits=None))
    assert len(e.f("exp_inbox_list").controls) == 2
    e.click(f"inbox_done_{first}")
    assert inbox.count_open() == 1 and len(e.f("exp_inbox_list").controls) == 1
    e.click("inbox_all")
    assert inbox.count_open() == 0 and "✅" in e.f("exp_inbox_list").controls[0].value
    assert "✅" in Env(tmp_path / "x").f("exp_inbox_list").controls[0].value  # بدونِ manager هم نمی‌ترکه


def test_preview_runs_real_flow_and_reset_cancels_open_orders(tmp_path):
    e = Env(tmp_path)
    e.settings.card_to_card_number = "6037991234567890"
    pid = e.products.add("هدفون", 1000, 5)
    e.click("preview_start")
    menu_labels = [c.key for c in e.f("preview_menu").controls]
    assert "menu:🛍 محصولات" in menu_labels
    fire(e.f("menu:🛍 محصولات"), "on_click")
    assert find(e.control, f"cb:c:p:{pid}:-:1") is not None  # دکمه‌ی محصول داخلِ حبابِ چت
    fire(find(e.control, f"cb:c:p:{pid}:-:1"), "on_click")
    fire(find(e.control, f"cb:c:a:{pid}:1:-:1"), "on_click")
    fire(e.f("menu:🧺 سبد خرید"), "on_click")  # ۱.۱ (N5): «نهایی کردن» داخلِ پیامِ سبد است، نه منوی ثابت
    fire(find(e.control, "cb:c:co"), "on_click")
    for text in ("مریم", "09121234567", "شیراز، خیابان زند، پلاک ۵"):
        e.f("preview_input").value = text
        e.click("preview_send")
    for data in ("c:ck:s", "c:ck:s", "c:ck:ok", "c:pm:card_to_card"):
        fire(find(e.control, f"cb:{data}"), "on_click")
    order = e.orders.list_for_chat("preview", "preview-1")[0]
    assert order.status == "pending_payment" and order.customer_name == "مریم"
    e.click("preview_reset")
    assert e.orders.get(order.id).status == "cancelled" and e.f("preview_chat").controls == []
    e.f("preview_input").value = "یه سؤال آزاد"
    e.click("preview_send")
    from fake_page import collect_text

    assert "AI" in collect_text(e.f("preview_chat"))  # متنِ آزاد → یادداشتِ «در پیش‌نمایش پاسخِ AI ساخته نمی‌شه»


def test_inbox_shows_paid_orders_waiting_for_the_owner(tmp_path):
    from app.core.orders import METHOD_CARD_TO_CARD

    e = Env(tmp_path, manager=SimpleNamespace(attention=AttentionInbox(ConversationStore(tmp_path / "c.db")), limits=None))
    pid = e.products.add("کالا", 1000, 5)
    for chat in ("1", "2"):
        oid = e.orders.create("telegram", chat, [(pid, 1)])
        e.orders.mark_paid(oid, METHOD_CARD_TO_CARD, "r")
    assert e.orders.count_by_status("paid") == 2
    e2 = Env(tmp_path / "again", manager=None)
    assert "✅" in e2.f("exp_inbox_list").controls[0].value  # بدونِ سفارشِ منتظر: «چیزی نیاز به توجه نداره»
    fresh = bot_experience.build(e.page, "fa", e.settings, e._save, e.products, e.orders, SimpleNamespace(attention=AttentionInbox(ConversationStore(tmp_path / "c.db")), limits=None))
    line = find(fresh, "inbox_orders_waiting")
    assert line is not None and "2 سفارش" in line.value


# ----------------------------------------------------- N3: ویرایشگرِ ساده‌ی پیام‌ها ----

def test_texts_editor_shows_titles_not_keys_and_only_basic_messages_by_default(tmp_path):
    e = Env(tmp_path)
    options = [o.text for o in e.f("txt_key").options]
    assert 10 <= len(options) <= 14 and all("." not in o.split("—")[-1] for o in options)
    assert any("پیامِ خوش‌آمدگویی" in o for o in options) and not any("pay.card" in o for o in options)
    assert e.f("txt_title").value and "کِی نشون داده می‌شه" in e.f("txt_when").value
    fire(e.f("txt_advanced"), "on_change", value=True)
    assert len(e.f("txt_key").options) > 100  # همه‌ی پیام‌ها پشتِ «پیشرفته»
    fire(e.f("txt_advanced"), "on_change", value=False)
    assert len(e.f("txt_key").options) <= 14


def test_texts_editor_variable_buttons_insert_and_preview_updates_live(tmp_path):
    e = Env(tmp_path)
    e.f("txt_key").value = "order.head"
    fire(e.f("txt_key"), "on_select")
    e.f("txt_override").value = "سفارش شماره‌ی "
    fire(e.f("txt_var_order_id"), "on_click")
    assert e.f("txt_override").value == "سفارش شماره‌ی {شماره‌ی سفارش}"
    assert e.f("txt_preview").value == "سفارش شماره‌ی 12"  # با مقدارِ نمونه
    e.f("txt_override").value = "سفارش {نامعتبر}"
    fire(e.f("txt_override"), "on_change", value="سفارش {نامعتبر}")
    assert "قابل‌استفاده نیست" in e.f("txt_preview").value
    e.click("txt_save")
    assert "order.head" not in (e.settings.bot_texts.get("fa") or {})  # متنِ نامعتبر ذخیره نمی‌شه


def test_texts_editor_button_label_limit_and_no_variable_message(tmp_path):
    e = Env(tmp_path)
    e.f("txt_key").value = "cart.checkout"
    fire(e.f("txt_key"), "on_select")
    e.f("txt_override").value = "✅ " + "ا" * 60
    e.click("txt_save")
    assert "کوتاه" in e.note("txt_note")
    e.f("txt_key").value = "menu.welcome"
    fire(e.f("txt_key"), "on_select")
    assert e.f("txt_vars").controls and e.f("txt_vars").controls[0].content == "{نامِ مشتری}"  # «name» در خوش‌آمد = مشتری، نه محصول
    e.f("txt_key").value = "cart.cleared"
    fire(e.f("txt_key"), "on_select")
    assert e.f("txt_vars").controls == [] and "متغیری نداره" in e.f("txt_hint").value


# ------------------------------------------------- N3: تب‌ها، راه‌اندازیِ سریع و بخشِ فروشگاه ----

TABS = ("quick", "shop", "messages", "advanced")


def visible_panels(e):
    return [t for t in TABS if e.f(f"exp_panel_{t}").visible]


def test_four_tabs_switch_panels_and_every_control_stays_reachable(tmp_path):
    e = Env(tmp_path)
    assert [e.f(f"exp_tab_{t}").content for t in TABS] == ["شروع سریع", "فروشگاه", "پیام‌ها", "پیشرفته"]
    assert visible_panels(e) == ["quick"]
    for tab in TABS:
        e.click(f"exp_tab_{tab}")
        assert visible_panels(e) == [tab]
    # هر بخش در تبِ درستِ خودش است
    where = {"quick": ["sec_quick", "sec_mode", "sec_profile", "sec_preview"], "shop": ["sec_catalog", "sec_fields", "sec_buttons"],
             "messages": ["sec_texts", "sec_faq"], "advanced": ["sec_hours", "sec_limits", "sec_inbox", "sec_adv_modes"]}
    for tab, keys in where.items():
        for key in keys:
            assert find(e.f(f"exp_panel_{tab}"), key) is not None, (tab, key)


def test_basic_sections_stay_small_progressive_disclosure(tmp_path):
    e = Env(tmp_path)

    def controls(root):
        out = []
        for key in ("exp_mode", "exp_lang", "exp_disclosure", "exp_mode_save", "qs_type", "qs_apply", "exp_page_size", "exp_max_qty", "exp_catalog_save"):
            if find(root, key) is not None:
                out.append(key)
        return out

    assert len(controls(find(e.control, "sec_mode"))) <= 7 and len(controls(find(e.control, "sec_quick"))) <= 7
    assert controls(find(e.control, "sec_mode")) == ["exp_mode", "exp_lang", "exp_disclosure", "exp_mode_save"]  # اندازه‌ی صفحه/تعداد در تبِ فروشگاه
    assert find(find(e.control, "sec_mode"), "exp_page_size") is None


def test_catalog_section_saves_and_validates_in_its_own_note(tmp_path):
    e = Env(tmp_path)
    e.f("exp_page_size").value, e.f("exp_max_qty").value = "8", "5"
    e.click("exp_catalog_save")
    assert (e.settings.catalog_page_size, e.settings.max_qty_per_item) == (8, 5) and "ذخیره" in e.note("exp_catalog_note")
    e.f("exp_page_size").value = "99"
    e.click("exp_catalog_save")
    assert "2 و 12" in e.note("exp_catalog_note") and e.settings.catalog_page_size == 8


def test_quick_setup_card_lists_presets_and_applies_without_touching_other_settings(tmp_path):
    e = Env(tmp_path)
    assert [o.key for o in e.f("qs_type").options] == ["physical", "digital", "services", "consult", "support"]
    e.settings.card_to_card_number = "6037991234567890"
    e.settings.faq_items = [{"q": "الف", "a": "ب"}]
    e.f("qs_type").value = "digital"
    fire(e.f("qs_type"), "on_select")
    assert "ایمیل" in e.f("qs_desc").value
    e.click("qs_apply")
    assert [f["id"] for f in e.settings.checkout_fields] == ["name", "email", "phone"] and e.saves == 1
    assert "✅ انجام شد" in e.note("qs_note") and "فرمِ سفارش" in e.note("qs_note")
    assert "ایمیل" in collect_text(e.f("exp_fields_list"))  # فهرستِ فیلدها هم با تنظیماتِ تازه هماهنگ شد
    assert e.settings.card_to_card_number == "6037991234567890" and e.settings.faq_items == [{"q": "الف", "a": "ب"}]
    e.click("qs_apply")  # دوباره: بی‌اثر
    assert "همین الان هم همین‌طور" in e.note("qs_note")


def test_quick_setup_support_preset_updates_the_mode_dropdown(tmp_path):
    e = Env(tmp_path)
    e.f("qs_type").value = "support"
    e.click("qs_apply")
    assert e.settings.shop_mode == "faq_support" and e.f("exp_mode").value == "faq_support"


def test_consultants_only_get_consult_and_support_presets_and_a_shop_hint(tmp_path):
    e = Env(tmp_path, "consultation")
    assert [o.key for o in e.f("qs_type").options] == ["consult", "support"]
    assert e.f("exp_shop_hint").visible is True
    assert Env(tmp_path / "s", "store").f("exp_shop_hint").visible is False


def test_field_and_button_forms_hide_technical_inputs_and_generate_ids(tmp_path):
    e = Env(tmp_path)
    # انواع به زبانِ ساده؛ مقدارِ ذخیره‌شده همان شناسه‌ی قدیمی
    assert {o.key: o.text for o in e.f("fld_type").options}["phone"] == "شماره‌ی موبایل"
    assert {o.key: o.text for o in e.f("fld_applies").options}["digital"] == "فقط محصولِ دیجیتال"
    assert "regex" not in e.f("fld_regex").label.lower() and "regex" not in e.f("fld_id").label.lower()
    assert find(e.f("fld_advanced"), "fld_id") is not None and find(e.f("fld_advanced"), "fld_regex") is not None  # زیرِ «حرفه‌ای»
    assert find(e.f("exp_field_form").content.controls[0], "fld_id") is None  # در ردیفِ اصلی نیست
    # بدونِ نوشتنِ شناسه، فیلدِ تازه ساخته می‌شه
    e.click("fld_add")
    e.f("fld_label").value, e.f("fld_prompt").value = "شهر", "شهرت کدومه؟"
    e.click("fld_save")
    assert [f["id"] for f in e.settings.checkout_fields][-1] == "f1" and e.settings.checkout_fields[-1]["label"] == "شهر"
    assert "متن" in collect_text(e.f("exp_fields_list")) and "text" not in collect_text(e.f("exp_fields_list")).split("شهر")[1][:30]
    # دکمه‌ی سفارشی هم شناسه‌ی خودکار می‌گیره
    e.click("btn_add")
    e.f("btn_label").value, e.f("btn_value").value = "قوانین", "ارسال ۳ روزه"
    e.click("btn_save")
    assert e.settings.custom_buttons[-1]["id"] == "b1" and e.settings.custom_buttons[-1]["label"] == "قوانین"
