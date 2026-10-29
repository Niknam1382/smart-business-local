"""
تست یکپارچه‌ی app/main.py با FakePage: چون آنبوردینگ (فاز ۱) کلید تستی
(``key=``) نداره و از قبل شخصاً تست دستی شده، این‌جا مستقیم state رو از قبل
«آنبوردینگ‌تمام‌شده» می‌سازیم و تمرکز رو می‌ذاریم رو چیزی که فاز ۳ واقعاً
بهش اضافه کرده: مسیریابی به صفحه‌های bots/chats، پاک‌سازی هنگام ترک صفحه
(بدون این، ترد زنده‌ی صفحه‌ی قبلی بی‌نهایت جمع می‌شد)، و روشن‌شدن خودکار ربات‌ها.
"""

from fake_page import FakePage, find, fire

from app.core import bot_manager, settings as settings_module
from app.main import main


def onboarded_state():
    state = settings_module.load_settings()
    state.user_name = "محمد مهدی"
    state.business_mode = "store"
    state.ai_mode = "api"
    state.api_base_url = "https://api.example.com/v1"
    state.set_api_key("sk-test")
    state.api_model_name = "gpt-4o-mini"
    state.onboarding_complete = True
    state.data_acknowledged = True  # N2: کاربر قبلاً «ادامه با داده‌ی قبلی» را انتخاب کرده
    state.ensure_default_prompt()
    settings_module.save_settings(state)
    return state


def reset_bot_manager_singleton():
    bot_manager._manager = None  # noqa: SLF001 — جلوگیری از نشت بین تست‌ها


def click_nav(root, nav_key: str):
    btn = find(root, f"nav_{nav_key}")
    assert btn is not None, f"دکمه‌ی ناوبری {nav_key} پیدا نشد"
    fire(btn, "on_click")


def test_app_boots_past_onboarding_straight_to_home(tmp_path):
    reset_bot_manager_singleton()
    onboarded_state()
    page = FakePage()
    main(page)
    assert page.controls, "page.add() باید یه بار صدا زده بشه"
    assert page.controls[0].content is not None  # خانه (هوش مصنوعی) بلافاصله ساخته شده


def test_nav_buttons_switch_to_bots_and_chats_screens(tmp_path):
    reset_bot_manager_singleton()
    onboarded_state()
    page = FakePage()
    main(page)
    body_container = page.controls[0]

    click_nav(body_container.content, "bots")
    bots_shell = body_container.content
    assert find(bots_shell, "run_button") is not None

    click_nav(bots_shell, "chats")
    chats_shell = body_container.content
    assert find(chats_shell, "detail_area") is not None
    assert find(chats_shell, "run_button") is None, "صفحه‌ی قبلی (bots) نباید توی درخت جدید باقی مونده باشه"


def test_leaving_bots_and_chats_screens_calls_cleanup_without_crashing(tmp_path):
    """رگرسیون: اگه on_leave صدا زده نشه، LiveRefresher صفحه‌ی قبلی برای
    همیشه روی یه ترد پس‌زمینه باقی می‌مونه."""
    reset_bot_manager_singleton()
    onboarded_state()
    page = FakePage()
    main(page)
    body_container = page.controls[0]

    click_nav(body_container.content, "bots")
    click_nav(body_container.content, "settings")  # ترک bots -> cleanup باید بی‌خطا اجرا بشه
    click_nav(body_container.content, "chats")
    click_nav(body_container.content, "ai")  # ترک chats -> cleanup باید بی‌خطا اجرا بشه
    # رسیدن به اینجا یعنی هیچ‌کدوم از cleanup ها استثنا پرت نکردن


def test_broadcast_nav_opens_the_screen_and_leaving_it_cleans_up(tmp_path):
    """N7: دکمه‌ی «پیامِ همگانی» در سایدبار؛ ترکِ صفحه باید refresher را متوقف کند (مثلِ گفتگوها)."""
    reset_bot_manager_singleton()
    onboarded_state()
    page = FakePage()
    main(page)
    body_container = page.controls[0]
    click_nav(body_container.content, "broadcast")
    assert find(body_container.content, "bc_text") is not None and find(body_container.content, "bc_start") is not None
    click_nav(body_container.content, "customers")
    assert find(body_container.content, "bc_text") is None, "صفحه‌ی قبلی نباید در درخت بماند"
    click_nav(body_container.content, "broadcast")  # دوباره باز می‌شود (ردیفِ جدول و خودِ نوار سالم)
    assert find(body_container.content, "bc_history") is not None


def test_products_nav_shown_for_store_mode_and_hidden_for_consultant(tmp_path):
    reset_bot_manager_singleton()
    state = onboarded_state()
    state.business_mode = "store"
    settings_module.save_settings(state)
    page = FakePage()
    main(page)
    body_container = page.controls[0]
    assert find(body_container.content, "nav_products") is not None
    assert find(body_container.content, "nav_orders") is not None
    click_nav(body_container.content, "products")
    assert find(body_container.content, "product_name") is not None  # صفحه‌ی محصولات واقعاً باز شد
    click_nav(body_container.content, "orders")
    assert find(body_container.content, "status_filter") is not None  # صفحه‌ی سفارش‌ها واقعاً باز شد

    reset_bot_manager_singleton()
    state2 = onboarded_state()
    state2.business_mode = "consultant"
    settings_module.save_settings(state2)
    page2 = FakePage()
    main(page2)
    assert find(page2.controls[0].content, "nav_products") is None
    assert find(page2.controls[0].content, "nav_orders") is None


def test_autostart_starts_bots_when_enabled_and_token_present(tmp_path, monkeypatch):
    reset_bot_manager_singleton()
    state = onboarded_state()
    state.set_telegram_token("123456:FAKE")
    state.bot_autostart = True
    settings_module.save_settings(state)

    started = []
    monkeypatch.setattr(bot_manager.BotManager, "start", lambda self: started.append(1))
    page = FakePage()
    main(page)
    assert started == [1]
    assert page.run_thread_calls >= 1


def test_autostart_does_nothing_without_any_token(tmp_path, monkeypatch):
    reset_bot_manager_singleton()
    state = onboarded_state()
    state.bot_autostart = True  # ولی هیچ توکنی نداره
    settings_module.save_settings(state)

    started = []
    monkeypatch.setattr(bot_manager.BotManager, "start", lambda self: started.append(1))
    page = FakePage()
    main(page)
    assert started == []


def test_autostart_respects_disabled_setting(tmp_path, monkeypatch):
    reset_bot_manager_singleton()
    state = onboarded_state()
    state.set_telegram_token("123456:FAKE")
    state.bot_autostart = False
    settings_module.save_settings(state)

    started = []
    monkeypatch.setattr(bot_manager.BotManager, "start", lambda self: started.append(1))
    page = FakePage()
    main(page)
    assert started == []


def test_orders_screen_in_real_app_has_payment_card_and_persists_through_main_state(tmp_path):
    """صفحه‌ی «سفارش‌ها» توی خودِ برنامه (main.py) باید کارت پرداخت داشته باشه و
    ذخیره‌ش به همون state/فایل تنظیماتِ برنامه بره — نه یه کپیِ جدا."""
    reset_bot_manager_singleton()
    state = onboarded_state()
    state.business_mode = "store"
    settings_module.save_settings(state)
    page = FakePage()
    main(page)
    body_container = page.controls[0]
    click_nav(body_container.content, "orders")

    number = find(body_container.content, "card_number")
    assert number is not None, "کارت تنظیمات پرداخت توی صفحه‌ی سفارش‌ها نیست"
    number.value = "6219861012345678"
    fire(number, "on_blur")

    assert settings_module.load_settings().card_to_card_number == "6219-8610-1234-5678"
    reset_bot_manager_singleton()
