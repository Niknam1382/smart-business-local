"""صفحه‌ی «خانه»: یک نگاهِ روزانه به وضعیتِ کسب‌وکار.

پیش از این، خانه همان صفحه‌ی «هوش مصنوعی» بود؛ مالک برای دیدنِ «چند فروش داشتم، چه چیزی
منتظرِ بررسی‌ست، ربات روشن است یا نه» باید بین چند صفحه جابه‌جا می‌شد. اینجا همان چهار چیز
روی هم نشسته است، با دکمه‌ی پرش به جایش. صفحه فقط می‌خواند؛ هیچ تصمیمی اینجا گرفته نمی‌شود.
"""

from __future__ import annotations

import time

import flet as ft

from app import theme
from app.core import jalali
from app.i18n import t
from app.screens import common

DAY_SECONDS = 86400
MAX_ATTENTION_ROWS = 6
CHART_DAYS = 14


def build(page: ft.Page, lang: str, state, manager, order_store, product_store, on_goto) -> ft.Control:
    """``on_goto(target)`` به صفحه‌ی درست می‌بَرَد (خانه هیچ کاری را انجام نمی‌دهد)."""
    from app.core import ai_engine

    store_mode = state.business_mode == "store"
    now = int(time.time())
    ready, reason_key = ai_engine.engine_readiness(state)
    status = manager.get_status()
    tg = status.platforms.get("telegram")
    bot_on = bool(status.running and tg is not None and tg.connected)

    attention_items = []
    try:
        attention_items = manager.attention.list_open(limit=MAX_ATTENTION_ROWS)
    except Exception:  # noqa: BLE001 — صفحه‌ی خانه هرگز نباید به‌خاطر یک شمارش بخوابد
        pass

    waiting: list = []
    low_stock = 0
    report = None
    customers = 0
    if store_mode:
        try:
            waiting = order_store.receipts_needing_attention(limit=MAX_ATTENTION_ROWS)
        except Exception:  # noqa: BLE001
            waiting = []
        try:
            threshold = int(getattr(state, "low_stock_threshold", 0) or 0)
            if threshold > 0:
                low_stock = sum(
                    1
                    for p in product_store.list()
                    if not p.unlimited_stock and p.active and p.stock_quantity <= threshold
                )
        except Exception:  # noqa: BLE001
            low_stock = 0
        try:
            ledger = manager.finance
            if ledger is not None:
                report = ledger.report(now - 7 * DAY_SECONDS, now + DAY_SECONDS)
        except Exception:  # noqa: BLE001
            report = None
        try:
            customers = manager.customers.count()
        except Exception:  # noqa: BLE001
            customers = 0

    def money_of(value: int) -> str:
        return jalali.fa_digits(f"{int(value or 0):,}")

    # ------------------------------------------------------------ نوار وضعیت
    def pill(key: str, icon: str, label: str, ok: bool, target: str) -> ft.Control:
        color = theme.SUCCESS if ok else theme.DANGER
        return ft.Container(
            key=key,
            border_radius=theme.RADIUS_PILL,
            bgcolor=f"{color}14",
            padding=ft.Padding.symmetric(horizontal=12, vertical=8),
            on_click=lambda e: on_goto(target),
            ink=True,
            content=ft.Row(
                tight=True,
                spacing=7,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(icon, size=15, color=color),
                    ft.Text(label, size=12.5, color=color, weight=ft.FontWeight.W_600),
                ],
            ),
        )

    model_label = t("home.model_ready", lang) if ready else t("home.model_not_ready", lang)
    status_row = ft.Row(
        spacing=10,
        wrap=True,
        controls=[
            pill(
                "home_pill_bot",
                ft.Icons.SMART_TOY_OUTLINED,
                t("home.bot_on", lang) if bot_on else t("home.bot_off", lang),
                bot_on,
                "bots",
            ),
            pill("home_pill_ai", ft.Icons.TUNE_ROUNDED, model_label, ready, "ai"),
            pill(
                "home_pill_attention",
                ft.Icons.NOTIFICATIONS_ACTIVE_ROUNDED,
                t("home.attention_count", lang, n=len(attention_items)) if attention_items else t("home.attention_clear", lang),
                not attention_items,
                "experience",
            ),
        ],
    )

    # ---------------------------------------------------------------- کارت‌های KPI
    def kpi(key: str, icon: str, label: str, value: str, hint: str, target: str) -> ft.Control:
        return ft.Container(
            key=key,
            width=210,
            border_radius=theme.RADIUS_CARD,
            bgcolor=theme.card_bgcolor(page),
            border=ft.Border.all(1, theme.border_color(page)),
            padding=16,
            on_click=lambda e: on_goto(target),
            ink=True,
            content=ft.Column(
                tight=True,
                spacing=6,
                controls=[
                    ft.Row(
                        tight=True,
                        spacing=7,
                        controls=[
                            ft.Container(
                                width=26,
                                height=26,
                                border_radius=8,
                                bgcolor=f"{theme.PRIMARY}12",
                                alignment=ft.Alignment.CENTER,
                                content=ft.Icon(icon, size=15, color=theme.PRIMARY),
                            ),
                            ft.Text(label, size=11.5, color=theme.text_secondary(page)),
                        ],
                    ),
                    ft.Text(value, size=theme.FONT_DISPLAY, weight=ft.FontWeight.W_700, color=theme.text_primary(page)),
                    ft.Text(hint, size=11, color=theme.text_secondary(page)),
                ],
            ),
        )

    kpis = []
    if store_mode and report is not None:
        kpis.append(
            kpi(
                "home_kpi_sales",
                ft.Icons.MONEY_ROUNDED,
                t("home.sales_7d", lang),
                money_of(report.sales_net),
                t("home.rial_and_orders", lang, orders=jalali.fa_digits(report.orders_count)),
                "finance",
            )
        )
        kpis.append(
            kpi(
                "home_kpi_waiting",
                ft.Icons.PENDING_ROUNDED,
                t("home.waiting_check", lang),
                jalali.fa_digits(len(waiting)),
                t("home.waiting_hint", lang),
                "orders",
            )
        )
        kpis.append(
            kpi(
                "home_kpi_low",
                ft.Icons.INVENTORY_2_OUTLINED,
                t("home.low_stock", lang),
                jalali.fa_digits(low_stock),
                t("home.low_stock_hint", lang),
                "products",
            )
        )
        kpis.append(kpi("home_kpi_customers", ft.Icons.PEOPLE_OUTLINE_ROUNDED, t("home.customers", lang),
                        jalali.fa_digits(customers), t("home.customers_hint", lang), "customers"))

    if not store_mode:
        kpis.append(
            kpi(
                "home_kpi_chats",
                ft.Icons.FORUM_OUTLINED,
                t("home.recent_chats", lang),
                jalali.fa_digits(len(manager.store.list_conversations())),
                t("home.recent_chats_hint", lang),
                "chats",
            )
        )
        kpis.append(
            kpi(
                "home_kpi_ai",
                ft.Icons.EDIT_NOTE_ROUNDED,
                t("home.prompt_ready", lang),
                t("home.prompt_yes", lang) if (getattr(state, "system_prompt", "") or "").strip() else t("home.prompt_no", lang),
                t("home.prompt_hint", lang),
                "prompt",
            )
        )

    # ------------------------------------------------------- فهرست «برو چک کن»
    rows = []
    for item in attention_items:
        rows.append(
            ft.Row(
                key=f"home_at_{item.id}",
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, size=15, color=theme.WARNING),
                    ft.Text(item.detail or item.type, size=12.5, expand=True,
                            color=theme.text_primary(page), max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.TextButton(t("home.open", lang), on_click=lambda e: on_goto("experience")),
                ],
            )
        )
    for receipt in waiting:
        if any(str(receipt.get("order_id")) in (r.detail or "") for r in attention_items):
            continue
        flag = ""
        if receipt.get("match_state") == "amount_mismatch":
            flag = f" · {t('home.amount_mismatch', lang)}"
        elif receipt.get("kind") == "image":
            flag = f" · {t('home.receipt_photo', lang)}"
        rows.append(
            ft.Row(
                key=f"home_wait_{receipt.get('order_id')}",
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(ft.Icons.RECEIPT_LONG_ROUNDED, size=15, color=theme.PRIMARY),
                    ft.Text(
                        t("home.waiting_row", lang, order_id=jalali.fa_digits(receipt.get("order_id") or 0),
                          amount=jalali.fa_digits(f"{int(receipt.get('total_irr') or 0):,}")) + flag,
                        size=12.5, expand=True, color=theme.text_primary(page),
                        max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    ft.TextButton(t("home.check", lang), on_click=lambda e: on_goto("orders")),
                ],
            )
        )

    check_card = common.card(
        page,
        ft.Column(
            spacing=10,
            controls=[
                ft.Row(
                    spacing=8,
                    controls=[
                        ft.Icon(ft.Icons.CHECKLIST_ROUNDED, size=17, color=theme.PRIMARY),
                        ft.Text(t("home.needs_check", lang), size=14, weight=ft.FontWeight.W_600),
                    ],
                ),
                *(rows or [ft.Text(t("home.all_clear", lang), size=12.5, color=theme.text_secondary(page))]),
            ],
        ),
    )

    # ------------------------------------------------------------ نمودارِ هفتگی
    chart = ft.Container(height=0)
    if store_mode and report is not None and getattr(report, "by_day", None):
        days = list(report.by_day)[-CHART_DAYS:]
        peak = max([abs(int(v or 0)) for _label, v in days] + [1])
        bars = []
        for label, value in days:
            height = max(4, int(74 * abs(int(value or 0)) / peak))
            bars.append(
                ft.Container(
                    width=16,
                    height=height,
                    border_radius=4,
                    bgcolor=theme.ACCENT if int(value or 0) > 0 else "#D8D5CC",
                    tooltip=f"{jalali.fa_digits(label)} · {money_of(int(value or 0))}",
                )
            )
        chart = common.card(
            page,
            ft.Column(
                spacing=10,
                controls=[
                    ft.Text(t("home.week_chart", lang), size=14, weight=ft.FontWeight.W_600),
                    ft.Row(spacing=6, alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=bars,
                           vertical_alignment=ft.CrossAxisAlignment.END),
                    ft.Text(t("home.week_hint", lang), size=11, color=theme.text_secondary(page)),
                ],
            ),
        )

    controls = [status_row]
    if kpis:
        controls.append(ft.Row(spacing=12, wrap=True, controls=kpis))
    controls.append(check_card)
    if not isinstance(chart, ft.Container) or chart.height != 0:
        controls.append(chart)

    return common.screen_frame(
        page,
        common.page_header(page, ft.Icons.SPACE_DASHBOARD_ROUNDED, t("home.title", lang),
                           t("home.subtitle", lang, name=state.user_name or "")),
        controls,
        key="home_frame",
    )
