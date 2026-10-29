"""نقطه‌ی ورود برنامه‌ی «کسب‌وکار هوشمند» (نسخه‌ی محلی) — فاز ۲.

مسیر آنبوردینگ: اسم -> نوع کسب‌وکار -> نوع هوش مصنوعی -> پوسته‌ی اصلی
(هوش مصنوعی / سیستم پرامپت / تنظیمات). اتصال به تلگرام/بله، و بخش
فروشگاه در فازهای بعدی اضافه می‌شن.
"""

from __future__ import annotations

import os
import threading
from typing import Optional

import flet as ft

from app import theme
from app.core import backup, bot_manager, data_probe, update_install, updater
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
    quickstart_card,
    ai_providers as ai_providers_screen,
    usage as usage_screen,
    chat_view,
    admins as admins_screen,
    common,
    customers as customers_screen,
    data_found,
    mode_select,
    orders,
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
    page.window.width = 960
    page.window.height = 720
    page.window.min_width = 720
    page.window.min_height = 560

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
        elif not state.ai_mode:
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
        def on_next(mode: str, base_url: str, api_key: str, model_name: str) -> None:
            state.ai_mode = mode
            if mode == "api":
                state.api_base_url = base_url
                state.set_api_key(api_key)
                state.api_model_name = model_name
            save()
            show_settings() if editing else route()

        def on_back() -> None:
            show_settings() if editing else show_mode_select()

        set_content(
            ai_select.build(
                page,
                state.language,
                state.ai_mode,
                state.api_base_url,
                state.get_api_key(),
                state.api_model_name,
                on_next,
                on_back,
            )
        )

    # ---------------- پوسته‌ی اصلی (پس از آنبوردینگ) ----------------

    def attention_badge() -> str:
        """تعدادِ موردهای «نیاز به توجه» کنارِ برچسبِ منو (۰ ⇒ هیچی)."""
        try:
            count = manager.attention.count_open() + order_store.count_by_status("paid")  # + سفارش‌های منتظرِ تاییدِ مالک
        except Exception:  # noqa: BLE001 — نمایشِ نشانگر هرگز نباید صفحه رو خراب کنه
            return ""
        return f" ({count})" if count else ""

    def shell(active: str, content: ft.Control) -> ft.Control:
        def nav_item(key: str, icon: str, label: str, on_click) -> ft.Control:
            is_active = active == key
            return ft.Container(
                key=f"nav_{key}",
                margin=ft.Margin.symmetric(horizontal=12),
                padding=ft.Padding.symmetric(horizontal=14, vertical=11),
                border_radius=10,
                bgcolor="#FFFFFF24" if is_active else None,
                ink=True,
                on_click=on_click,
                content=ft.Row(
                    spacing=12,
                    controls=[
                        ft.Icon(icon=icon, size=18, color="#FFFFFF" if is_active else "#C7CCDA"),
                        ft.Text(
                            label,
                            size=13.5,
                            weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.W_400,
                            color="#FFFFFF" if is_active else "#C7CCDA",
                        ),
                    ],
                ),
            )

        sidebar = ft.Container(
            width=224,
            gradient=theme.sidebar_gradient(),
            padding=ft.Padding.symmetric(vertical=22),
            content=ft.Column(
                expand=True,
                spacing=2,
                controls=[
                    ft.Container(
                        padding=ft.Padding.symmetric(horizontal=20),
                        content=ft.Row(
                            spacing=10,
                            controls=[
                                common.logo_badge(36),
                                ft.Column(
                                    spacing=0,
                                    tight=True,
                                    controls=[
                                        ft.Text(
                                            t("app.title", state.language),
                                            size=13,
                                            weight=ft.FontWeight.W_700,
                                            color="#FFFFFF",
                                            max_lines=1,
                                            overflow=ft.TextOverflow.ELLIPSIS,
                                        ),
                                        ft.Text(
                                            t("app.local_badge", state.language),
                                            size=10,
                                            color="#93E6B7",
                                            weight=ft.FontWeight.W_500,
                                        ),
                                    ],
                                ),
                            ],
                        ),
                    ),
                    ft.Container(height=14),
                    ft.Container(
                        padding=ft.Padding.symmetric(horizontal=20),
                        content=ft.Text(
                            t("home.welcome_back", state.language, name=state.user_name),
                            size=12,
                            color="#8B92A8",
                            max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                    ),
                    ft.Container(height=16),
                    ft.Container(
                        margin=ft.Margin.symmetric(horizontal=20),
                        height=1,
                        bgcolor="#FFFFFF1F",
                    ),
                    ft.Container(height=10),
                    nav_item(
                        "ai", ft.Icons.SMART_TOY_ROUNDED, t("home.nav.ai", state.language), lambda e: show_ai_setup()
                    ),
                    *(
                        [
                            nav_item(
                                "products",
                                ft.Icons.INVENTORY_2_ROUNDED,
                                t("home.nav.products", state.language),
                                lambda e: show_products(),
                            )
                        ]
                        if state.business_mode == "store"
                        else []
                    ),
                    *(
                        [
                            nav_item(
                                "orders",
                                ft.Icons.RECEIPT_LONG_ROUNDED,
                                t("home.nav.orders", state.language),
                                lambda e: show_orders(),
                            )
                        ]
                        if state.business_mode == "store"
                        else []
                    ),
                    nav_item(
                        "experience",
                        ft.Icons.TUNE_ROUNDED,
                        t("home.nav.experience", state.language) + attention_badge(),
                        lambda e: show_experience(),
                    ),
                    nav_item(
                        "prompt",
                        ft.Icons.EDIT_NOTE_ROUNDED,
                        t("home.nav.prompt", state.language),
                        lambda e: show_prompt_studio(),
                    ),
                    nav_item(
                        "bots", ft.Icons.LINK_ROUNDED, t("home.nav.bots", state.language), lambda e: show_bots()
                    ),
                    nav_item(
                        "chats",
                        ft.Icons.FORUM_OUTLINED,
                        t("home.nav.chats", state.language),
                        lambda e: show_chats(),
                    ),
                    nav_item(
                        "customers",
                        ft.Icons.PEOPLE_ROUNDED,
                        t("home.nav.customers", state.language),
                        lambda e: show_customers(),
                    ),
                    nav_item(
                        "broadcast",
                        ft.Icons.CAMPAIGN_ROUNDED,
                        t("home.nav.broadcast", state.language),
                        lambda e: show_broadcast(),
                    ),
                    *(
                        [
                            nav_item("usage", ft.Icons.INSIGHTS_ROUNDED, t("home.nav.usage", state.language), lambda e: show_usage()),
                            nav_item("providers", ft.Icons.HUB_ROUNDED, t("home.nav.providers", state.language), lambda e: show_providers()),
                        ]
                        if state.ai_mode == "api"
                        else [nav_item("usage", ft.Icons.INSIGHTS_ROUNDED, t("home.nav.usage", state.language), lambda e: show_usage())]
                    ),
                    *(
                        [
                            nav_item(
                                "discounts",
                                ft.Icons.LOCAL_OFFER_ROUNDED,
                                t("home.nav.discounts", state.language),
                                lambda e: show_discounts(),
                            )
                        ]
                        if state.business_mode == "store"
                        else []
                    ),
                    *(
                        [nav_item("finance", ft.Icons.ACCOUNT_BALANCE_WALLET_ROUNDED, t("home.nav.finance", state.language), lambda e: show_finance())]  # N19
                        if state.business_mode == "store"
                        else []
                    ),
                    *(
                        [
                            nav_item(
                                "admins",
                                ft.Icons.ADMIN_PANEL_SETTINGS_ROUNDED,
                                t("home.nav.admins", state.language),
                                lambda e: show_admins(),
                            )
                        ]
                        if state.business_mode == "store"
                        else []
                    ),
                    ft.Container(expand=True),
                    nav_item("guide", ft.Icons.MENU_BOOK_ROUNDED, t("home.nav.guide", state.language), lambda e: show_guide()),  # N10
                    nav_item(
                        "about",
                        ft.Icons.INFO_OUTLINE_ROUNDED,
                        t("home.nav.about", state.language),
                        lambda e: show_about(),
                    ),
                    nav_item(
                        "settings",
                        ft.Icons.SETTINGS_OUTLINED,
                        t("home.nav.settings", state.language),
                        lambda e: show_settings(),
                    ),
                ],
            ),
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
        """N10: چک‌لیستِ «شروعِ سریع» فقط بالای صفحه‌ی خانه و تا وقتی کاربر نبسته."""
        if active != "ai" or state.quickstart_dismissed:
            return ft.Container(height=0)
        count = len(product_store.list(include_inactive=True)) if state.business_mode == "store" else None
        card = quickstart_card.build(page, state.language, state, count, manager.is_running(), go=goto, open_article=lambda a: show_guide(a), on_dismiss=dismiss_quick_start)
        return card or ft.Container(height=0)

    def dismiss_quick_start() -> None:
        state.quickstart_dismissed = True
        save()
        show_ai_setup()

    def goto(target: str) -> None:
        {"bots": show_bots, "ai": show_ai_setup, "products": show_products, "orders": show_orders}.get(target, show_ai_setup)()

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

    def show_broadcast() -> None:
        control, cleanup = broadcast_screen.build(page, state.language, state, save, manager)  # N7
        set_content(shell("broadcast", control), on_leave=cleanup)

    def show_usage() -> None:
        set_content(shell("usage", usage_screen.build(page, state.language, state, manager)))  # N1/N18

    def show_providers() -> None:
        set_content(shell("providers", ai_providers_screen.build(page, state.language, state)))  # N16

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
                prompt_studio.build(
                    page, state.language, state.business_mode, state.system_prompt, on_save
                ),
            )
        )

    def show_settings(notice: str = "") -> None:
        def on_change_mode() -> None:
            show_mode_select(editing=True)

        def on_change_ai() -> None:
            show_ai_select(editing=True)

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
                    on_data_changed=on_data_changed,
                    manager=manager,
                    notice=notice,
                ),
            )
        )

    def show_about() -> None:
        set_content(shell("about", about.build(page, state.language, state, save, checker=update_checker, can_install=can_install_update, on_install=on_install_from_about)))

    def show_home() -> None:
        show_ai_setup()

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
