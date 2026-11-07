"""نقطه‌ی ورود برنامه‌ی «کسب‌وکار هوشمند» (نسخه‌ی محلی) — فاز ۲.

مسیر آنبوردینگ: اسم -> نوع کسب‌وکار -> نوع هوش مصنوعی -> پوسته‌ی اصلی
(هوش مصنوعیِ محلی / سیستم پرامپت / تنظیمات). ربات روی تلگرام حرف می‌زند و
بله فقط به‌عنوانِ درگاهِ پرداخت استفاده می‌شه.
"""

from __future__ import annotations

import os
import threading
from typing import Optional

import flet as ft

from app import theme
from app.core import backup, bot_manager, data_probe, update_install, updater, window_close
from app.core import guide as guide_core
from app.core import settings as settings_module
from app.core.orders import OrderStore
from app.core.products import ProductStore
from app.i18n import t
from app.screens import (
    about,
    ai_select,
    ai_setup,
    bot_connect,
    bot_experience,
    broadcast as broadcast_screen,
    discounts as discounts_screen,
    finance as finance_screen,
    guide as guide_screen,
    home as home_screen,
    quickstart_card,
    search as search_screen,
    sidebar as sidebar_mod,
    usage as usage_screen,
    chat_view,
    admins as admins_screen,
    customers as customers_screen,
    data_found,
    mode_select,
    orders,
    payment_settings,
    products,
    prompt_studio,
    settings_screen,
    update_banner,
    welcome,
)

NO_UPDATE_CHECK_ENV = "SMART_BUSINESS_NO_UPDATE_CHECK"  # تست‌ها/اجرای بدونِ شبکه: بررسیِ خودکارِ نسخه‌ی تازه اصلاً شروع نمی‌شه


_UNSET = object()


def _default_quit(page: ft.Page) -> None:
    """بستنِ برنامه برای نصبِ به‌روزرسانی: اول پنجره (بسته‌شدنِ تمیز)، و اگه تا چند ثانیه نبست، خروجِ قطعی؛
    helper منتظرِ پایانِ این پردازش می‌مونه، پس باید حتماً تموم بشه."""
    try:
        page.run_task(page.window.destroy)
    except Exception:  # noqa: BLE001
        pass
    timer = threading.Timer(5.0, lambda: os._exit(0))
    timer.daemon = True
    timer.start()


def main(
    page: ft.Page,
    *,
    checker: updater.UpdateChecker | None = None,
    start_update_thread: bool | None = None,
    installer: update_install.UpdateInstaller | None = None,
    quit_app=None,
    update_result=_UNSET,
) -> None:
    try:
        page.window.icon = "icons/app.ico"  # Flet 1.0: نسبت به assets_dir (فقط ویندوز اثر دارد؛ در بقیه نادیده)
    except Exception:  # noqa: BLE001 — آیکنِ پنجره هرگز نباید شروعِ برنامه را بشکند
        pass
    page.title = "کسب‌وکار هوشمند — Smart Business"
    page.padding = 0
    page.fonts = theme.FONT_PATHS
    page.theme = theme.build_theme()
    page.dark_theme = theme.build_dark_theme()
    page.theme_mode = ft.ThemeMode.LIGHT
    # قلم ۱۳: رنگِ بومِ پنجره با سطحِ برنامه یکی است — در پنجره‌ی تمام‌صفحه حاشیه‌ی سفیدِ خام نمی‌بینی.
    page.backgroundColor = theme.SURFACE_LIGHT
    page.window.width = 960
    page.window.height = 720
    page.window.min_width = 720
    page.window.min_height = 560
    # قلم ۱۶: برنامه تمام‌صفحه باز می‌شه و ✕ دیگر بی‌سؤال نمی‌بندد (پس‌زمینه یا خروج، انتخابِ کاربر).
    page.window.maximized = True

    state = settings_module.load_settings()
    page.rtl = state.language == "fa"
    # یه نمونه‌ی مشترک برای کل پروسه (نه هر session) — توی حالت --web با چند
    # تب باز، همه باید همین یه poller رو ببینن/کنترل کنن، وگرنه دو تا poller
    # هم‌زمان برای یه توکن یعنی خطای Conflict از تلگرام.
    product_store = ProductStore()
    order_store = OrderStore(product_store=product_store)
    manager = bot_manager.get_manager(state, product_store=product_store, order_store=order_store)

    body = ft.Container(expand=True)
    page.add(body)

    _current_cleanup: dict = {"fn": None}

    def set_content(control: ft.Control, on_leave=None) -> None:
        """``on_leave`` (اختیاری): قبل از رفتن به صفحه‌ی بعدی صدا زده می‌شه —
        صفحه‌های زنده (bots/chats) برای متوقف‌کردن به‌روزرسانی دوره‌ای‌شون ازش
        استفاده می‌کنن؛ بدونش، تردهای پس‌زمینه‌ی صفحه‌ی قبلی بی‌نهایت جمع می‌شدن."""
        if _current_cleanup["fn"] is not None:
            try:
                _current_cleanup["fn"]()
            except Exception:  # noqa: BLE001
                pass
        _current_cleanup["fn"] = on_leave
        body.content = control
        page.rtl = state.language == "fa"
        page.update()

    def save() -> None:
        settings_module.save_settings(state)

    window_close.bind(page, state, save)  # قلم ۱۶: ✕ = انتخابِ خودِ کاربر

    # ---------------- بررسیِ نسخه‌ی تازه (N14a) ----------------
    update_checker = checker or updater.UpdateChecker(lambda: state, save)
    update_installer = installer or update_install.UpdateInstaller()
    banner_holder: dict = {"control": None}
    banner_flags: dict = {"confirm": False}  # «نصب» از صفحه‌ی «درباره»: بنر مستقیم در مرحله‌ی تأیید باز بشه
    update_ctx: dict = {"stopped_bots": False}
    notice_holder: dict = {"control": None, "result": update_install.consume_update_result() if update_result is _UNSET else update_result}

    def stop_bots_for_update() -> None:
        """درست قبل از تحویل به helper: ربات‌ها تمیز خاموش بشن (پیام‌های در راه ثبت بشن)."""
        if manager.is_running():
            update_ctx["stopped_bots"] = True
            manager.stop(timeout=10)

    def resume_bots_after_failed_update() -> None:
        """نصب بعد از توقفِ ربات‌ها شکست خورد؛ برنامه باز می‌مونه ⇒ رباتی که ما خاموش کردیم دوباره روشن بشه."""
        if update_ctx.pop("stopped_bots", False):
            try:
                manager.start()
            except bot_manager.BotManagerError:
                pass

    def quit_for_update() -> None:
        (quit_app or (lambda: _default_quit(page)))()

    def render_banner() -> ft.Control | None:
        info = update_checker.pending()
        if info is None:
            return None
        start_confirm = bool(banner_flags.pop("confirm", False))
        return update_banner.build(
            page,
            state.language,
            info,
            on_banner_later,
            installer=update_installer,
            on_restart=quit_for_update,
            before_handoff=stop_bots_for_update,
            on_resume=resume_bots_after_failed_update,
            start_in_confirm=start_confirm,
        )

    def render_notice() -> ft.Control | None:
        result = notice_holder["result"]
        return update_banner.build_notice(page, state.language, result, dismiss_notice) if result else None

    def dismiss_notice() -> None:
        notice_holder["result"] = None
        holder = notice_holder["control"]
        if holder is not None:
            holder.content = None
            holder.visible = False
            try:
                page.update()
            except Exception:  # noqa: BLE001
                pass

    def can_install_update(info: updater.UpdateInfo) -> bool:
        return update_installer.availability(info).mode != update_install.MODE_MANUAL

    def on_install_from_about(info: updater.UpdateInfo) -> None:
        """«نصبِ به‌روزرسانی» در صفحه‌ی «درباره»: اگه قبلاً «بعداً» زده بود برمی‌گردونیمش و بنر در مرحله‌ی تأیید باز می‌شه."""
        update_checker.dismiss("")
        banner_flags["confirm"] = True
        refresh_banner()

    def on_banner_later(version: str) -> None:
        update_checker.dismiss(version)
        refresh_banner()

    def refresh_banner() -> None:
        holder = banner_holder["control"]
        if holder is None:
            return
        banner = render_banner()
        holder.content = banner
        holder.visible = banner is not None
        try:
            page.update()
        except Exception:  # noqa: BLE001 — به‌روزرسانیِ بنر هرگز نباید برنامه را بشکند
            pass

    def on_update_result(result: updater.CheckResult) -> None:
        refresh_banner()

    # ---------------- مسیریابی آنبوردینگ ----------------

    def route() -> None:
        if not state.data_acknowledged:
            # N2: پوشه‌ی داده از قبل استفاده شده؟ پیش از هر چیز یک‌بار از کاربر بپرس (ادامه / شروعِ تازه)
            footprint = data_probe.probe()
            if footprint.has_data:
                show_data_found(footprint)
                return
            state.data_acknowledged = True  # نصبِ تازه: دیگه هرگز نپرس
            save()
        if not state.user_name:
            show_welcome()
        elif not state.business_mode:
            show_mode_select()
        elif not state.ai_declined and not state.model_id and not state.model_file_path:
            show_ai_select()
        else:
            if not state.onboarding_complete:
                state.onboarding_complete = True
                state.ensure_default_prompt()
                save()
            show_home()

    def show_data_found(footprint: data_probe.DataFootprint) -> None:
        def on_continue() -> None:
            state.data_acknowledged = True
            save()
            route()
            maybe_autostart_bots()  # حالا که کاربر ادامه با داده‌ی قبلی را انتخاب کرده

        def on_fresh_start(set_status) -> None:
            if manager.is_running():
                manager.stop(timeout=10)
            backup.factory_reset(make_backup=True, keep_models=True)  # اول پشتیبانِ کامل، بعد پاک‌کردن
            settings_module.reload_into(state)
            state.data_acknowledged = True
            save()
            route()

        set_content(data_found.build(page, state.language, footprint, on_continue, on_fresh_start))

    def show_welcome() -> None:
        def on_next(name: str) -> None:
            state.user_name = name
            save()
            route()

        set_content(welcome.build(page, state.language, state.user_name, on_next))

    def show_mode_select(editing: bool = False) -> None:
        def on_next(mode: str) -> None:
            state.business_mode = mode
            save()
            show_settings() if editing else route()

        def on_back() -> None:
            show_settings() if editing else show_welcome()

        set_content(
            mode_select.build(page, state.language, state.business_mode, on_next, on_back)
        )

    def show_ai_select(editing: bool = False) -> None:
        """آنبوردینگِ هوش مصنوعی: انتخابِ مدلِ محلی و دانلودِ آن. هیچ API بیرونی‌ای نیست."""

        def on_done() -> None:
            save()
            show_settings() if editing else route()

        def on_back() -> None:
            show_settings() if editing else show_mode_select()

        def on_skip() -> None:
            # بدونِ این پرچم، route دوباره همین صفحه را می‌سازد و «بعداً» معنایش بی‌خطر می‌ماند
            state.ai_declined = True
            on_done()

        set_content(ai_select.build(page, state.language, state, save, on_done, on_back, on_skip=on_skip))

    # ---------------- پوسته‌ی اصلی (پس از آنبوردینگ) ----------------

    def attention_badge() -> str:
        """تعدادِ موردهای «نیاز به توجه» کنارِ برچسبِ منو (۰ ⇒ هیچی)."""
        try:
            count = manager.attention.count_open() + order_store.count_by_status("paid")  # + سفارش‌های منتظرِ تاییدِ مالک
        except Exception:  # noqa: BLE001 — نمایشِ نشانگر هرگز نباید صفحه رو خراب کنه
            return ""
        return f" ({count})" if count else ""

    def shell(active: str, content: ft.Control) -> ft.Control:
        store = state.business_mode == "store"
        lang = state.language
        entry = lambda key, icon, label, cb: sidebar_mod.NavEntry(key, icon, label, lambda e: cb())  # noqa: E731
        shop_group = (
            [
                entry("products", ft.Icons.INVENTORY_2_ROUNDED, t("home.nav.products", lang), show_products),
                entry("orders", ft.Icons.RECEIPT_LONG_ROUNDED, t("home.nav.orders", lang), show_orders),
                entry("finance", ft.Icons.ACCOUNT_BALANCE_WALLET_ROUNDED, t("home.nav.finance", lang), show_finance),  # N19
                entry("discounts", ft.Icons.LOCAL_OFFER_ROUNDED, t("home.nav.discounts", lang), show_discounts),
            ]
            if store
            else []
        )
        bot_group = [
            entry("experience", ft.Icons.TUNE_ROUNDED, t("home.nav.experience", lang) + attention_badge(), show_experience),
            entry("prompt", ft.Icons.EDIT_NOTE_ROUNDED, t("home.nav.prompt", lang), show_prompt_studio),
            entry("bots", ft.Icons.LINK_ROUNDED, t("home.nav.bots", lang), show_bots),
            entry("payment", ft.Icons.PAYMENTS_OUTLINED, t("home.nav.payment", lang), show_payment_settings),
            entry("chats", ft.Icons.FORUM_OUTLINED, t("home.nav.chats", lang), show_chats),
            entry("customers", ft.Icons.PEOPLE_ROUNDED, t("home.nav.customers", lang), show_customers),
            entry("search", ft.Icons.SEARCH_ROUNDED, t("home.nav.search", lang), show_search),
            entry("broadcast", ft.Icons.CAMPAIGN_ROUNDED, t("home.nav.broadcast", lang), show_broadcast),
            *([entry("admins", ft.Icons.ADMIN_PANEL_SETTINGS_ROUNDED, t("home.nav.admins", lang), show_admins)] if store else []),
        ]
        ai_group = [
            entry("usage", ft.Icons.INSIGHTS_ROUNDED, t("home.nav.usage", lang), show_usage),
        ]
        sidebar = sidebar_mod.build(
            t("app.title", lang),
            t("app.local_badge", lang),
            t("home.welcome_back", lang, name=state.user_name),
            active,
            top=[
                entry("home", ft.Icons.SPACE_DASHBOARD_ROUNDED, t("home.nav.home", lang), show_home),
                entry("ai", ft.Icons.SMART_TOY_ROUNDED, t("home.nav.ai", lang), show_ai_setup),
            ],
            groups=[(t("nav.group.shop", lang), shop_group), (t("nav.group.bot", lang), bot_group), (t("nav.group.ai", lang), ai_group)],
            bottom=[
                entry("guide", ft.Icons.MENU_BOOK_ROUNDED, t("home.nav.guide", lang), show_guide),  # N10
                entry("support", ft.Icons.FAVORITE_ROUNDED, t("home.nav.support", lang), show_support),  # حمایتِ اختیاری (دارمت) — از منو پیدا باشه
                entry("about", ft.Icons.INFO_OUTLINE_ROUNDED, t("home.nav.about", lang), show_about),
                entry("settings", ft.Icons.SETTINGS_OUTLINED, t("home.nav.settings", lang), show_settings),
            ],
        )

        banner = render_banner()
        holder = ft.Container(key="update_banner_holder", content=banner, visible=banner is not None)
        banner_holder["control"] = holder
        notice = render_notice()
        notice_box = ft.Container(key="update_notice_holder", content=notice, visible=notice is not None)
        notice_holder["control"] = notice_box
        return ft.Row(
            expand=True,
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[
                sidebar,
                ft.Container(
                    expand=True,
                    bgcolor=theme.surface_bgcolor(page),
                    content=ft.Column(expand=True, spacing=0, controls=[notice_box, holder, help_bar(active), quick_start(active), ft.Container(expand=True, content=content)]),
                ),
            ],
        )

    def help_bar(active: str) -> ft.Control:
        """N10: «؟» کنارِ هر صفحه — مقاله‌ی مرتبط با همین صفحه را باز می‌کنه (بدونِ مقاله‌ی اختصاصی ← صفحه‌ی راهنما)."""
        if active == "guide":
            return ft.Container(height=0)
        return ft.Container(
            key="help_bar", padding=ft.Padding.symmetric(horizontal=24, vertical=0), alignment=ft.Alignment.CENTER_RIGHT if state.language == "en" else ft.Alignment.CENTER_LEFT,
            content=ft.IconButton(key="help_button", icon=ft.Icons.HELP_OUTLINE_ROUNDED, icon_size=20, tooltip=t("help.tooltip", state.language),
                                  on_click=lambda e: show_guide(guide_core.HELP_FOR.get(active))),
        )

    def quick_start(active: str) -> ft.Control:
        """چک‌لیستِ «شروعِ سریع» فقط بالای صفحه‌ی خانه و تا وقتی کاربر نبسته."""
        if active != "home" or state.quickstart_dismissed:
            return ft.Container(height=0)
        count = len(product_store.list(include_inactive=True)) if state.business_mode == "store" else None
        card = quickstart_card.build(page, state.language, state, count, manager.is_running(), go=goto, open_article=lambda a: show_guide(a), on_dismiss=dismiss_quick_start)
        return card or ft.Container(height=0)

    def dismiss_quick_start() -> None:
        state.quickstart_dismissed = True
        save()
        show_home()

    def goto(target: str) -> None:
        {"home": show_home, "bots": show_bots, "ai": show_ai_setup, "products": show_products, "orders": show_orders,
         "finance": show_finance, "customers": show_customers, "chats": show_chats, "prompt": show_prompt_studio,
         "experience": show_experience, "payment": show_payment_settings}.get(target, show_home)()

    def show_guide(article_id: Optional[str] = None) -> None:
        set_content(shell("guide", guide_screen.build(page, state.language, state, manager, open_article=article_id)))

    def show_ai_setup() -> None:
        set_content(shell("ai", ai_setup.build(page, state.language, state, save)))

    def show_products() -> None:
        set_content(shell("products", products.build(page, state.language, product_store, state, save)))

    def show_experience() -> None:
        set_content(shell("experience", bot_experience.build(page, state.language, state, save, product_store, order_store, manager)))

    def show_orders() -> None:
        set_content(shell("orders", orders.build(page, state.language, order_store, manager, state, save)))

    def show_payment_settings() -> None:
        set_content(shell("payment", payment_settings.build(page, state.language, state, save, manager)))

    def show_bots() -> None:
        control, cleanup = bot_connect.build(page, state.language, state, save, manager)
        set_content(shell("bots", control), on_leave=cleanup)

    def show_admins() -> None:
        set_content(shell("admins", admins_screen.build(page, state.language, manager, state)))

    def show_customers() -> None:
        set_content(shell("customers", customers_screen.build(page, state.language, manager, order_store)))

    def show_chats() -> None:
        control, cleanup = chat_view.build(page, state.language, manager, on_open_bots=show_bots)
        set_content(shell("chats", control), on_leave=cleanup)

    def show_search() -> None:
        """جست‌وجوی سراسری (A2): دکمه‌ی هر نتیجه همان صفحه را باز می‌کند."""
        targets = {"orders": show_orders, "products": show_products, "customers": show_customers}
        control = search_screen.build(page, state.language, orders=order_store, products=product_store,
                                      customers=manager.customers,
                                      on_open=lambda key: targets[key]() if key in targets else show_home())
        set_content(shell("search", control))

    def show_broadcast() -> None:
        control, cleanup = broadcast_screen.build(page, state.language, state, save, manager)  # N7
        set_content(shell("broadcast", control), on_leave=cleanup)

    def show_usage() -> None:
        set_content(shell("usage", usage_screen.build(page, state.language, state, manager)))  # N1/N18

    def show_discounts() -> None:
        set_content(shell("discounts", discounts_screen.build(page, state.language, manager, product_store)))  # N8

    def show_finance() -> None:
        set_content(shell("finance", finance_screen.build(page, state.language, manager, state, product_store)))  # N19

    def show_prompt_studio() -> None:
        def on_save(text: str) -> None:
            state.system_prompt = text
            save()

        set_content(
            shell(
                "prompt",
                prompt_studio.build(page, state.language, state, on_save, product_store, order_store),
            )
        )

    def show_settings(notice: str = "") -> None:
        def on_change_mode() -> None:
            show_mode_select(editing=True)

        def on_change_ai() -> None:
            show_ai_select(editing=True)

        def on_change_close(action: str) -> None:
            window_close.apply_close(state, action)
            save()
            show_settings()

        def on_change_language(new_lang: str) -> None:
            state.language = new_lang
            save()
            show_settings()

        def on_data_changed(kind: str, message: str = "") -> None:
            """بعد از بازگردانی/بازنشانیِ موفق: ``state`` همین الان از دیسک نو شده (درجا)؛
            زبان/راست‌به‌چپ رو دوباره اعمال می‌کنیم. ریست → برگشت به معرفی؛ بازگردانی → همین
            صفحه با پیامِ نتیجه."""
            page.rtl = state.language == "fa"
            if kind == "reset":
                route()
            else:
                show_settings(notice=message)

        set_content(
            shell(
                "settings",
                settings_screen.build(
                    page,
                    state.language,
                    state,
                    on_change_mode,
                    on_change_ai,
                    on_change_language,
                    on_change_close,
                    on_data_changed=on_data_changed,
                    manager=manager,
                    notice=notice,
                ),
            )
        )

    def show_about(support_first: bool = False) -> None:
        set_content(shell("support" if support_first else "about", about.build(page, state.language, state, save, checker=update_checker, can_install=can_install_update, on_install=on_install_from_about, support_first=support_first)))

    def show_support() -> None:
        show_about(support_first=True)

    def show_home() -> None:
        set_content(shell("home", home_screen.build(page, state.language, state, manager, order_store, product_store, goto)))

    def maybe_autostart_bots() -> None:
        """اگه کاربر آنبوردینگ رو تموم کرده، «روشن‌شدن خودکار» فعاله، و
        حداقل یه ربات توکن‌دار/فعال داره، بدون نیاز به کلیک، ربات‌ها رو روشن
        می‌کنه — تا با هر بار باز کردن برنامه، پاسخ‌گویی خودش شروع بشه."""
        if not (state.onboarding_complete and state.bot_autostart and manager.enabled_platforms()):
            return
        if not state.data_acknowledged:
            return  # N2: تا کاربر «ادامه / شروعِ تازه» را انتخاب نکرده ربات‌ها با داده‌ی قبلی روشن نمی‌شن

        def worker() -> None:
            try:
                manager.start()
            except bot_manager.BotManagerError:
                pass  # وضعیت واقعی توی صفحه‌ی «ربات‌ها» دیده می‌شه؛ نیازی به مزاحمت اینجا نیست

        page.run_thread(worker)

    def maybe_start_update_checks() -> None:
        """هنگامِ شروع و هر ۲۴ ساعتِ اجرا؛ ترد daemon است و با بستنِ برنامه تموم می‌شه. بی‌صدا در شکست."""
        enabled = start_update_thread if start_update_thread is not None else not os.environ.get(NO_UPDATE_CHECK_ENV)
        if enabled:  # پوشه‌های موقتِ نصب‌های نیمه‌کاره‌ی قبلی (مستقل از خاموش/روشنِ بررسیِ خودکار)
            threading.Thread(target=update_install.cleanup_stale_staging, name="smart-business-update-cleanup", daemon=True).start()
        if not (enabled and state.update_check_enabled):
            return
        stop = threading.Event()
        threading.Thread(
            target=updater.run_periodic, args=(update_checker, on_update_result, stop), name="smart-business-update-check", daemon=True
        ).start()

    route()
    maybe_autostart_bots()
    maybe_start_update_checks()
