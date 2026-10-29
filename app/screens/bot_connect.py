"""
صفحه‌ی «اتصال ربات‌ها» (فاز ۳): توکن تلگرام/بله، تست اتصال، پروکسی اختیاری
تلگرام، وضعیت زنده‌ی هر ربات، و دکمه‌ی روشن/خاموش/راه‌اندازی مجدد.

اصول:
- هر تغییر (توکن، فعال/غیرفعال، پروکسی) فوراً رمزنگاری و ذخیره می‌شه. اگه
  ربات‌ها همون لحظه روشن باشن، یه هشدار + دکمه‌ی «اعمال تغییرات» نشون داده
  می‌شه؛ خودکار ری‌استارت نمی‌کنیم (وسط تایپ توکن، اتصال قطع نشه).
- کارهای شبکه‌ای (تست، روشن/خاموش) با ``page.run_thread`` انجام می‌شن، نه روی
  ترد رابط.
- وضعیت هر ربات هر ~۱.۵ ثانیه از ``manager.get_status()`` خونده می‌شه
  (LiveRefresher)؛ ترد ربات هیچ‌وقت مستقیم به کنترل‌های Flet دست نمی‌زنه.
- پیام‌های خطا از روی ``error_code`` به متن دوزبانه تبدیل می‌شن.

``build`` دو چیز برمی‌گردونه: کنترل صفحه و تابع پاک‌سازی (توقف به‌روزرسانی
زنده) که main.py هنگام ترک صفحه صدا می‌زنه.
"""

from __future__ import annotations

import asyncio
from typing import Callable

import flet as ft

from app import theme
from app.core import bale_adapter, telegram_adapter
from app.core.adapter_common import (
    ERR_UNEXPECTED,
    STATE_CONNECTED,
    STATE_CONNECTING,
    STATE_ERROR,
    AdapterStatus,
)
from app.core import proxy_subscription
from app.core.bot_manager import BotManagerError
from app.core.proxy_pool import (
    ProxyFormatError,
    mask_credentials,
    normalize_proxy,
    parse_proxy_text,
    probe_bare_candidates,
    proxy_config_from_text,
)
from app.i18n import STRINGS, t
from app.screens.common import StatusChip, card, page_header, section_header
from app.screens.live import LiveRefresher

PLATFORMS = ("telegram", "bale")
_ICONS = {"telegram": ft.Icons.SEND_ROUNDED, "bale": ft.Icons.CHAT_BUBBLE_OUTLINE_ROUNDED}


def error_text(platform: str, status: AdapterStatus, lang: str) -> str:
    """پیام دوزبانه‌ی خطا از روی کد؛ اگه کدی نبود، متن فارسی خام هسته."""
    if status.error_code:
        for key in (f"bots.err.{status.error_code}.{platform}", f"bots.err.{status.error_code}"):
            if key in STRINGS:
                return t(key, lang)
    return status.error or ""


def build(page: ft.Page, lang: str, settings, save_callback, manager) -> tuple[ft.Control, Callable[[], None]]:
    ui = {
        "busy": None,  # None | "starting" | "stopping"
        "needs_restart": False,
        "run_error": "",
        "testing": {p: False for p in PLATFORMS},
        "test": {p: None for p in PLATFORMS},  # (متن، رنگ)
    }
    last = {"snap": None}

    # ------------------------------------------------------------ توکن/پروکسی
    def get_token(platform: str) -> str:
        return settings.get_telegram_token() if platform == "telegram" else settings.get_bale_token()

    def set_token(platform: str, raw: str) -> None:
        if platform == "telegram":
            settings.set_telegram_token(raw)
        else:
            settings.set_bale_token(raw)

    def mark_dirty() -> None:
        if manager.is_running():
            ui["needs_restart"] = True

    token_fields = {
        p: ft.TextField(
            key=f"{p}_token",
            label=t("bots.token_label", lang),
            hint_text=t("bots.token_hint", lang),
            value=get_token(p),
            password=True,
            can_reveal_password=True,
            prefix_icon=ft.Icons.VPN_KEY_ROUNDED,
            text_align=ft.TextAlign.LEFT,
            border_radius=10,
            expand=True,
        )
        for p in PLATFORMS
    }
    proxy_field = ft.TextField(
        key="telegram_proxy",
        label=t("bots.proxy.label", lang),
        hint_text=t("bots.proxy.hint", lang),
        value=settings.get_telegram_proxy(),
        multiline=True,
        min_lines=2,
        max_lines=8,
        text_align=ft.TextAlign.LEFT,
        border_radius=10,
    )
    proxy_status = ft.Text("", key="proxy_status", size=12, color=theme.text_secondary(page))
    proxy_rank_result = ft.Text("", key="proxy_rank_result", size=12)

    def refresh_proxy_status() -> None:
        """خلاصه‌ی زنده‌ی فیلد: چندتا پروکسیِ معتبر + اولین خطاها (با پیامِ فارسیِ روشن)."""
        text = proxy_field.value or ""
        parsed = parse_proxy_text(text)
        if not parsed.urls and not parsed.errors:
            proxy_status.value = ""
        else:
            count = len(parsed.urls)
            message = t("bots.proxy.summary", lang, count=count, plural="y" if count == 1 else "ies")
            if count >= 2:
                message += t("bots.proxy.summary_auto", lang)
            if parsed.errors:
                number, raw, reason = parsed.errors[0]
                detail = f"«{raw[:28]}» — {reason}"
                message += t("bots.proxy.summary_errors", lang, n=len(parsed.errors), detail=detail)
            proxy_status.value = message
            proxy_status.color = theme.DANGER if (parsed.errors and not parsed.urls) else theme.text_secondary(page)

    refresh_proxy_status()

    # ---- اشتراکِ پروکسی (R6): لینکِ خودِ کاربر؛ هرگز لیستِ عمومیِ رایگان ----
    _SUB = {
        "title": ("اشتراکِ پروکسی (اختیاری)", "Proxy subscription (optional)"),
        "url": ("لینکِ اشتراک (فقط لینکی که خودت داری؛ هر خط یک پروکسی)", "Subscription link (your own; one proxy per line)"),
        "hours": ("به‌روزرسانیِ خودکار هر ... ساعت (۰ = فقط دستی)", "Auto-refresh every ... hours (0 = manual only)"),
        "now": ("به‌روزرسانیِ همین الان", "Refresh now"),
        "never": ("هنوز دریافت نشده", "Not fetched yet"),
        "updated": ("آخرین به‌روزرسانی: {when}", "Last refresh: {when}"),
        "error": ("آخرین خطا: {err}", "Last error: {err}"),
        "current": ("پروکسیِ فعلی: {p}", "Current proxy: {p}"),
        "direct": ("اتصالِ مستقیم/ربات خاموش", "direct / bot not running"),
        "events": ("جابه‌جایی‌های اخیر", "Recent switches"),
        "restart": ("برای اعمالِ لیستِ جدید ربات رو ری‌استارت کن.", "Restart the bot to apply the new list."),
        "bad": ("عددِ ساعت نامعتبره.", "Invalid number of hours."),
    }

    def SB(key: str, **kw) -> str:
        fa, en = _SUB[key]
        text = en if lang == "en" else fa
        return text.format(**kw) if kw else text

    sub_url = ft.TextField(key="proxy_sub_url", label=SB("url"), value=settings.get_telegram_proxy_sub_url(), password=True, can_reveal_password=True,
                           text_align=ft.TextAlign.LEFT, border_radius=10)
    sub_hours = ft.TextField(key="proxy_sub_hours", label=SB("hours"), value=str(settings.telegram_proxy_sub_hours), border_radius=10, width=300)
    sub_status = ft.Text("", key="proxy_sub_status", size=12, color=theme.text_secondary(page))
    proxy_info = ft.Text("", key="proxy_info", size=12, color=theme.text_secondary(page))

    def refresh_sub_status(extra: str = "") -> None:
        lines = []
        if extra:
            lines.append(extra)
        ts = int(settings.telegram_proxy_sub_updated_ts or 0)
        lines.append(SB("updated", when=__import__("time").strftime("%Y-%m-%d %H:%M", __import__("time").localtime(ts))) if ts else SB("never"))
        if settings.telegram_proxy_sub_error:
            lines.append(SB("error", err=settings.telegram_proxy_sub_error))
        info = manager.telegram_proxy_info() if hasattr(manager, "telegram_proxy_info") else {"current": "", "events": [], "restart_pending": False}
        lines.append(SB("current", p=info["current"] or SB("direct")))
        if info["events"]:
            import time as _time

            lines.append(SB("events") + ": " + " | ".join(f"{_time.strftime('%H:%M', _time.localtime(ts_))} {old or '·'} → {new}" for ts_, old, new, _why in info["events"][-5:]))
        if info.get("restart_pending"):
            lines.append("⚠️ " + SB("restart"))
        sub_status.value = "\n".join(lines)
        proxy_info.value = ""

    def save_sub(e=None) -> None:
        url = (sub_url.value or "").strip()
        warning = ""
        if url:
            try:
                url, warning = proxy_subscription.validate_url(url)
            except proxy_subscription.SubscriptionError as exc:
                refresh_sub_status("⚠️ " + str(exc))
                page.update()
                return
        digits = (sub_hours.value or "0").strip()
        if not digits.isdigit() or int(digits) > 168:
            refresh_sub_status("⚠️ " + SB("bad"))
            page.update()
            return
        settings.set_telegram_proxy_sub_url(url)
        settings.telegram_proxy_sub_hours = int(digits)
        save_callback()
        refresh_sub_status(warning)
        page.update()

    def refresh_sub_now(e=None) -> None:
        save_sub()

        def work() -> None:
            refresh_sub_status(manager.refresh_proxy_subscription_sync())
            page.update()

        page.run_thread(work)

    sub_url.on_blur = sub_hours.on_blur = save_sub
    sub_now_button = ft.OutlinedButton(key="proxy_sub_now", content=SB("now"), icon=ft.Icons.REFRESH_ROUNDED, on_click=refresh_sub_now)
    refresh_sub_status()

    def save_token(platform: str) -> None:
        new = (token_fields[platform].value or "").strip()
        if new == get_token(platform):
            return
        set_token(platform, new)
        save_callback()
        mark_dirty()
        ui["test"][platform] = None
        render()

    def save_proxy() -> None:
        new = (proxy_field.value or "").strip()
        refresh_proxy_status()
        if new == settings.get_telegram_proxy():
            return
        settings.set_telegram_proxy(new)
        save_callback()
        mark_dirty()
        ui["test"]["telegram"] = None
        render()

    for p in PLATFORMS:
        token_fields[p].on_blur = lambda e, p=p: save_token(p)
        token_fields[p].on_submit = lambda e, p=p: save_token(p)
    proxy_field.on_blur = lambda e: save_proxy()

    def on_proxy_change(e=None) -> None:
        refresh_proxy_status()
        page.update()

    proxy_field.on_change = on_proxy_change  # چندخطی: Enter خط جدیده، پس ذخیره روی blur/تست/رتبه‌بندی

    def on_rank_proxies(e=None) -> None:
        """هر پروکسی رو (از طریقِ اتصال به تلگرام) می‌آزماید و لیست رو سریع‌ترین‌ها-اول مرتب می‌کنه."""
        lines = [
            ln.strip() for ln in (proxy_field.value or "").splitlines() if ln.strip() and not ln.strip().startswith("#")
        ]
        valid = []
        for ln in lines:
            try:
                normalize_proxy(ln)
                valid.append(ln)
            except ProxyFormatError:
                pass
        if not valid:
            proxy_rank_result.value = t("bots.proxy.rank_empty", lang)
            proxy_rank_result.color = theme.DANGER
            page.update()
            return
        proxy_rank_result.value = t("bots.proxy.ranking", lang)
        proxy_rank_result.color = theme.text_secondary(page)
        rank_button.disabled = True
        page.update()

        def worker() -> None:
            try:
                results = asyncio.run(probe_bare_candidates(valid))
            except Exception:  # noqa: BLE001
                results = {}
            ranked = sorted(results.items(), key=lambda kv: (kv[1] is None, kv[1] if kv[1] is not None else 0.0))
            alive = sum(1 for _, ms in ranked if ms is not None)
            if ranked:
                proxy_field.value = "\n".join(url for url, _ in ranked)
                save_proxy()
            if alive:
                detail = "  ".join(
                    f"{'✓' if ms is not None else '✗'} {mask_credentials(url)}"
                    + (f" {ms:.0f}ms" if ms is not None else "")
                    for url, ms in ranked[:4]
                )
                proxy_rank_result.value = t("bots.proxy.rank_done", lang, ok=alive, total=len(ranked)) + "  " + detail
                proxy_rank_result.color = theme.SUCCESS
            else:
                proxy_rank_result.value = t("bots.proxy.rank_none", lang)
                proxy_rank_result.color = theme.DANGER
            rank_button.disabled = False
            page.update()

        page.run_thread(worker)

    rank_button = ft.OutlinedButton(
        key="proxy_rank",
        content=t("bots.proxy.rank", lang),
        icon=ft.Icons.SPEED_ROUNDED,
        on_click=on_rank_proxies,
    )

    # ---------------------------------------------------------- فعال/غیرفعال
    def on_enabled(platform: str, value: bool) -> None:
        setattr(settings, f"{platform}_enabled", bool(value))
        save_callback()
        mark_dirty()
        render()

    enabled_switches = {
        p: ft.Switch(
            key=f"{p}_enabled",
            label=t("bots.enabled", lang),
            value=bool(getattr(settings, f"{p}_enabled")),
            active_color=theme.SUCCESS,
            on_change=lambda e, p=p: on_enabled(p, e.control.value),
        )
        for p in PLATFORMS
    }

    # -------------------------------------------------------------- تست اتصال
    def on_test(platform: str) -> None:
        token = (token_fields[platform].value or "").strip()
        if not token:
            ui["test"][platform] = (t("bots.token_empty", lang), theme.DANGER)
            render()
            return
        proxy = (proxy_field.value or "").strip()
        ui["testing"][platform] = True
        ui["test"][platform] = (t("bots.testing", lang), theme.text_secondary(page))
        render()

        def worker() -> None:
            try:
                if platform == "telegram":
                    single, pool = proxy_config_from_text(proxy)
                    if pool is not None:
                        result = asyncio.run(telegram_adapter.check_token_via_proxies(token, pool.urls))
                    else:
                        result = asyncio.run(telegram_adapter.check_token(token, single))
                else:
                    result = asyncio.run(bale_adapter.check_token(token))
            except Exception as exc:  # noqa: BLE001
                result = AdapterStatus(state=STATE_ERROR, error=str(exc)[:200], error_code=ERR_UNEXPECTED)
            ui["testing"][platform] = False
            if result.connected:
                # تست موفق یعنی توکن (و پروکسی) درسته → همون‌جا ذخیره می‌شه
                if platform == "telegram":
                    save_proxy()
                save_token(platform)
                ui["test"][platform] = (
                    "✓ " + t("bots.test_ok", lang, username=result.username or "?"),
                    theme.SUCCESS,
                )
            else:
                ui["test"][platform] = ("✗ " + error_text(platform, result, lang), theme.DANGER)
            render()

        page.run_thread(worker)

    test_buttons = {
        p: ft.Button(
            key=f"{p}_test",
            content=t("bots.test", lang),
            icon=ft.Icons.WIFI_TETHERING_ROUNDED,
            bgcolor=theme.PRIMARY,
            color="#FFFFFF",
            on_click=lambda e, p=p: on_test(p),
        )
        for p in PLATFORMS
    }
    test_results = {p: ft.Text("", size=13, expand=True) for p in PLATFORMS}
    chips = {p: StatusChip(t("bots.status.stopped", lang), theme.text_secondary(page)) for p in PLATFORMS}
    platform_errors = {p: ft.Text("", size=12, color=theme.DANGER, visible=False) for p in PLATFORMS}

    # ------------------------------------------------------ روشن/خاموش‌کردن
    def on_run(e=None) -> None:
        if ui["busy"]:
            return
        running = manager.is_running()
        has_targets = bool(manager.enabled_platforms())
        if running and ui["needs_restart"] and has_targets:
            action = "restart"
        elif running:
            action = "stop"
        elif has_targets:
            action = "start"
        else:
            ui["run_error"] = t("bots.run.no_token", lang)
            render()
            return
        ui["busy"] = "stopping" if action == "stop" else "starting"
        ui["run_error"] = ""
        render()

        def worker() -> None:
            try:
                if action == "stop":
                    manager.stop()
                elif action == "restart":
                    manager.restart()
                else:
                    manager.start()
                ui["needs_restart"] = False
            except BotManagerError as exc:
                ui["run_error"] = str(exc)
            except Exception as exc:  # noqa: BLE001
                ui["run_error"] = str(exc)[:200]
            finally:
                ui["busy"] = None
            render()

        page.run_thread(worker)

    run_status_text = ft.Text("", size=14, weight=ft.FontWeight.W_500)
    run_button = ft.Button(
        key="run_button",
        content=t("bots.run.start", lang),
        icon=ft.Icons.PLAY_ARROW_ROUNDED,
        bgcolor=theme.ACCENT,
        color="#FFFFFF",
        on_click=on_run,
    )
    restart_note = ft.Text(
        t("bots.run.needs_restart", lang), size=12, color=theme.ACCENT_DARK, visible=False
    )
    run_error_text = ft.Text("", size=12, color=theme.DANGER, visible=False)

    def on_autostart(value: bool) -> None:
        settings.bot_autostart = bool(value)
        save_callback()

    autostart_switch = ft.Switch(
        key="autostart",
        label=t("bots.autostart", lang),
        value=bool(settings.bot_autostart),
        active_color=theme.SUCCESS,
        on_change=lambda e: on_autostart(e.control.value),
    )

    # -------------------------------------------------------------- رندر زنده
    def snapshot() -> tuple:
        status = manager.get_status()
        return (
            status.running,
            tuple((p, s.state, s.username, s.error_code, s.error) for p, s in sorted(status.platforms.items())),
            ui["busy"],
            ui["needs_restart"],
            ui["run_error"],
            tuple(ui["testing"].values()),
            tuple(ui["test"].values()),
        )

    def render(update: bool = True) -> None:
        status = manager.get_status()
        last["snap"] = snapshot()

        running, busy = status.running, ui["busy"]
        if busy == "starting":
            run_status_text.value = t("bots.run.starting", lang)
        elif busy == "stopping":
            run_status_text.value = t("bots.run.stopping", lang)
        else:
            run_status_text.value = t("bots.run.running" if running else "bots.run.stopped", lang)
        run_status_text.color = theme.SUCCESS if running and not busy else None

        if running and ui["needs_restart"] and manager.enabled_platforms():
            run_button.content, run_button.icon = t("bots.run.restart", lang), ft.Icons.REFRESH_ROUNDED
        elif running:
            run_button.content, run_button.icon = t("bots.run.stop", lang), ft.Icons.STOP_ROUNDED
        else:
            run_button.content, run_button.icon = t("bots.run.start", lang), ft.Icons.PLAY_ARROW_ROUNDED
        run_button.bgcolor = theme.DANGER if (running and not ui["needs_restart"]) else theme.ACCENT
        run_button.disabled = bool(busy)
        restart_note.visible = bool(running and ui["needs_restart"])
        run_error_text.value = ui["run_error"]
        run_error_text.visible = bool(ui["run_error"])

        for p in PLATFORMS:
            st = status.platforms[p]
            if st.state == STATE_CONNECTED:
                text = (
                    t("bots.status.connected", lang, username=st.username)
                    if st.username
                    else t("bots.status.connected_anon", lang)
                )
                chips[p].set(text, theme.SUCCESS)
            elif st.state == STATE_CONNECTING:
                chips[p].set(t("bots.status.connecting", lang), theme.ACCENT)
            elif st.state == STATE_ERROR:
                chips[p].set(t("bots.status.error", lang), theme.DANGER)
            else:
                chips[p].set(t("bots.status.stopped", lang), theme.text_secondary(page))

            shown = error_text(p, st, lang) if st.state in (STATE_CONNECTING, STATE_ERROR) else ""
            platform_errors[p].value = shown
            platform_errors[p].visible = bool(shown)
            platform_errors[p].color = theme.DANGER if st.state == STATE_ERROR else theme.ACCENT_DARK

            result = ui["test"][p]
            test_results[p].value, test_results[p].color = result if result else ("", None)
            test_buttons[p].disabled = ui["testing"][p]

        if update:
            page.update()

    def tick() -> None:
        if snapshot() != last["snap"]:
            render()

    # ------------------------------------------------------------ چیدمان صفحه
    def platform_card(platform: str) -> ft.Control:
        controls: list[ft.Control] = [
            ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[section_header(_ICONS[platform], t(f"bots.{platform}", lang)), chips[platform].control],
            ),
            ft.Row(controls=[token_fields[platform]]),
            ft.Text(t(f"bots.{platform}.howto", lang), size=12, color=theme.text_secondary(page)),
        ]
        if platform == "telegram":
            controls.append(
                ft.ExpansionTile(
                    title=ft.Text(t("bots.proxy.title", lang), size=13, weight=ft.FontWeight.W_500),
                    expanded=bool(settings.get_telegram_proxy() or settings.get_telegram_proxy_sub_url()),
                    controls=[
                        ft.Container(
                            padding=ft.Padding.only(left=8, right=8, bottom=12),
                            content=ft.Column(
                                spacing=8,
                                controls=[
                                    proxy_field,
                                    proxy_status,
                                    ft.Row(spacing=12, controls=[rank_button, ft.Container(content=proxy_rank_result, expand=True)]),
                                    ft.Text(t("bots.proxy.help", lang), size=12, color=theme.text_secondary(page)),
                                    ft.Text(SB("title"), size=13, weight=ft.FontWeight.W_500),
                                    sub_url,
                                    ft.Row(spacing=12, wrap=True, controls=[sub_hours, sub_now_button]),
                                    sub_status,
                                ],
                            ),
                        )
                    ],
                )
            )
        controls += [
            ft.Row(
                spacing=12,
                controls=[enabled_switches[platform], test_buttons[platform], test_results[platform]],
            ),
            platform_errors[platform],
        ]
        return card(page, ft.Column(spacing=12, controls=controls))

    # -------------------------------------------------------------- حافظه
    _HISTORY_OPTIONS = ["5", "10", "20", "40", "80"]
    _EXPIRE_OPTIONS = [
        ("0", "bots.memory.expire_never"),
        ("1", "bots.memory.expire_1h"),
        ("6", "bots.memory.expire_6h"),
        ("24", "bots.memory.expire_24h"),
        ("72", "bots.memory.expire_72h"),
    ]

    def on_history_change(e) -> None:
        settings.memory_history_limit = int(e.control.value)
        save_callback()

    def on_expire_change(e) -> None:
        settings.memory_expire_hours = int(e.control.value)
        save_callback()

    history_dropdown = ft.Dropdown(
        key="memory_history_limit",
        label=t("bots.memory.history_label", lang),
        value=str(settings.memory_history_limit),
        options=[
            ft.DropdownOption(key=v, text=f"{v} {t('bots.memory.messages_suffix', lang)}") for v in _HISTORY_OPTIONS
        ],
        on_select=on_history_change,
        border_radius=10,
        width=230,
    )
    expire_dropdown = ft.Dropdown(
        key="memory_expire_hours",
        label=t("bots.memory.expire_label", lang),
        value=str(settings.memory_expire_hours),
        options=[ft.DropdownOption(key=v, text=t(label_key, lang)) for v, label_key in _EXPIRE_OPTIONS],
        on_select=on_expire_change,
        border_radius=10,
        width=230,
    )
    memory_card = card(
        page,
        ft.Column(
            spacing=12,
            controls=[
                section_header(ft.Icons.MEMORY_ROUNDED, t("bots.memory.title", lang)),
                ft.Text(t("bots.memory.subtitle", lang), size=12, color=theme.text_secondary(page)),
                ft.Row(spacing=16, wrap=True, controls=[history_dropdown, expire_dropdown]),
            ],
        ),
    )

    run_card = card(
        page,
        ft.Column(
            spacing=10,
            controls=[
                section_header(ft.Icons.POWER_SETTINGS_NEW_ROUNDED, t("bots.run.title", lang)),
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[run_status_text, run_button],
                ),
                restart_note,
                run_error_text,
                ft.Text(t("bots.run.note", lang), size=12, color=theme.text_secondary(page)),
                ft.Text(t("bots.run.credit_note", lang), key="bots_credit_note", size=12, color=theme.text_secondary(page)),
                autostart_switch,
            ],
        ),
    )

    render(update=False)
    refresher = LiveRefresher(page, tick, interval=1.5)
    refresher.start()

    control = ft.Container(
        expand=True,
        padding=ft.Padding.symmetric(horizontal=32, vertical=24),
        content=ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=18,
            controls=[
                page_header(page, ft.Icons.LINK_ROUNDED, t("bots.title", lang), t("bots.subtitle", lang)),
                run_card,
                platform_card("telegram"),
                platform_card("bale"),
                memory_card,
            ],
        ),
    )
    return control, refresher.stop
