"""صفحه‌ی «سفارش‌ها» (فاز ۴، فقط حالت فروشگاه) — دیدن سفارش‌ها و تایید/رد
سفارش‌های پرداخت‌شده. ساخته‌شدنِ خودِ سفارش‌ها (مکالمه‌ی خرید داخل ربات) و
اتصال به درگاه بله‌پی/کارت‌به‌کارت بخش بعدیِ فاز ۴ـه؛ این صفحه فقط بخش
«مدیریت» رو از سمت صاحب فروشگاه پوشش می‌ده."""

from __future__ import annotations

import flet as ft

from app import theme
from app.core.bot_manager import BotManagerError
from app.core.owner_console import extra_info_lines
from app.core.orders import (
    STATUS_CANCELLED,
    STATUS_CONFIRMED,
    STATUS_EXPIRED,
    STATUS_PAID,
    STATUS_PENDING_PAYMENT,
    STATUS_REJECTED,
    Order,
    OrderError,
    OrderStore,
    build_order_confirmed_text,
    build_order_rejected_text,
)
from app.i18n import t
from app.screens import owner_settings, payment_settings
from app.screens.common import card, page_header

_ALL_STATUSES = [STATUS_PENDING_PAYMENT, STATUS_PAID, STATUS_CONFIRMED, STATUS_REJECTED, STATUS_CANCELLED, STATUS_EXPIRED]
_PLATFORM_ICON = {"telegram": ft.Icons.SEND_ROUNDED, "bale": ft.Icons.CHAT_BUBBLE_OUTLINE_ROUNDED}


def _status_color(status: str) -> str:
    return {
        STATUS_PENDING_PAYMENT: theme.ACCENT_DARK,
        STATUS_PAID: theme.ACCENT,
        STATUS_CONFIRMED: theme.SUCCESS,
        STATUS_REJECTED: theme.DANGER,
        STATUS_CANCELLED: theme.DANGER,
        STATUS_EXPIRED: theme.TEXT_SECONDARY_LIGHT,
    }.get(status, theme.ACCENT)


def _format_price(amount: int, lang: str) -> str:
    return f"{amount:,} {t('products.price_suffix', lang)}"


def _delivery_label(delivered: bool, lang: str) -> str:
    if lang == "en":
        return "📬 Digital delivery: sent" if delivered else "📬 Digital delivery: pending (will retry automatically)"
    return "📬 تحویلِ دیجیتال: ارسال شد" if delivered else "📬 تحویلِ دیجیتال: هنوز نرسیده (خودکار دوباره تلاش می‌شه)"


def _redeliver_label(lang: str) -> str:
    return "Send delivery again" if lang == "en" else "ارسالِ دوباره‌ی تحویل"


def build(
    page: ft.Page, lang: str, order_store: OrderStore, manager=None, settings=None, save_callback=None
) -> ft.Control:
    """``manager`` (BotManager) اختیاریه: بدونش تایید سفارش فقط توی دیتابیس ثبت
    می‌شه و پیامی برای مشتری نمی‌ره. ``settings``/``save_callback`` هم اختیاری‌ان:
    اگه داده بشن، کارت «تنظیمات پرداخت» بالای صفحه نشون داده می‌شه."""
    ui = {"filter": "", "error": "", "notice": ""}
    list_column = ft.Column(spacing=12)
    error_text = ft.Text("", size=12, color=theme.DANGER, visible=False)
    notice_text = ft.Text("", size=12, color=theme.SUCCESS, visible=False)

    def notify_customer(order: Order, kind: str = "confirm") -> None:
        """بعد از تایید/ردِ موفق، پیام رو به پلتفرم/چتِ واقعیِ سفارش می‌فرسته. تغییرِ وضعیت توی
        دیتابیس *قبلاً* انجام شده؛ شکستِ ارسال (ربات خاموش، قطعی شبکه) نباید برش‌گردونه — فقط
        به صاحب فروشگاه هشدار می‌دیم تا خودش خبر بده. (ردِ یه سفارشِ پرداخت‌شده هم باید به
        مشتری گفته بشه: پول داده و بی‌خبر موندن بدترین حالته.)"""
        if manager is None:
            return
        text = build_order_confirmed_text(order) if kind == "confirm" else build_order_rejected_text(order)
        try:
            manager.send_message_sync(order.platform, order.chat_id, text)
            ui["notice"] = t("orders.notify_sent" if kind == "confirm" else "orders.notify_reject_sent", lang, id=order.id)
            if kind == "confirm":
                manager.deliver_digital_sync(order.id)  # محصولِ دیجیتال (اگه داشت)؛ شکست = اعلان به مالک + تلاشِ مجدد
        except BotManagerError as exc:
            key = "orders.notify_failed" if kind == "confirm" else "orders.notify_reject_failed"
            ui["error"] = t(key, lang, id=order.id, reason=str(exc))

    def handle_confirm(order_id: int) -> None:
        ui["notice"] = ""
        try:
            order_store.confirm(order_id)
            order_store.set_confirmed_by(order_id, "app")  # N11: چه کسی تأیید کرد
            order = order_store.get(order_id)
            ui["error"] = ""
        except OrderError as exc:
            ui["error"] = t("orders.confirm_error_prefix", lang) + str(exc)
            render_list()
            page.update()
            return
        render_list()
        page.update()
        # ارسال شبکه‌ای روی ترد جدا، تا UI فریز نشه (و یه ارسال کند/قطع، دکمه‌ها رو قفل نکنه)
        page.run_thread(lambda: (notify_customer(order), render_list(), page.update()))

    def handle_redeliver(order_id: int) -> None:
        """تلاشِ دستیِ دوباره برای تحویلِ دیجیتال (idempotent: کلیدِ تازه‌ای مصرف نمی‌شه)."""
        ui["notice"] = ""
        render_list()
        page.update()

        def work() -> None:
            result = manager.deliver_digital_sync(order_id) if manager is not None else "failed:ربات خاموشه"
            ui["notice"] = _delivery_label(True, lang) if result in ("delivered", "nothing") else f"⚠️ {result.removeprefix('failed:')}"
            render_list()
            page.update()

        page.run_thread(work)

    def handle_reject(order_id: int) -> None:
        ui["notice"] = ""
        try:
            order_store.reject(order_id)
            order = order_store.get(order_id)
            ui["error"] = ""
        except OrderError as exc:
            ui["error"] = str(exc)
            render_list()
            page.update()
            return
        render_list()
        page.update()
        page.run_thread(lambda: (notify_customer(order, "reject"), render_list(), page.update()))

    def order_card(order: Order) -> ft.Control:
        items_text = "، ".join(f"{i.product_name} ×{i.quantity}" for i in order.items)
        method_key = f"orders.payment_method.{order.payment_method}" if order.payment_method else "orders.payment_method.none"

        header = ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                ft.Row(
                    spacing=8,
                    controls=[
                        ft.Icon(_PLATFORM_ICON.get(order.platform, ft.Icons.CHAT_ROUNDED), size=16, color=theme.text_secondary(page)),
                        ft.Text(f"#{order.id}", size=13, weight=ft.FontWeight.W_600),
                        ft.Text(order.chat_id, size=12, color=theme.text_secondary(page)),
                    ],
                ),
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                    border_radius=20,
                    bgcolor=f"{_status_color(order.status)}22",
                    content=ft.Text(t(f"orders.status.{order.status}", lang), size=11.5, color=_status_color(order.status), weight=ft.FontWeight.W_500),
                ),
            ],
        )

        body = ft.Column(
            spacing=6,
            controls=[
                ft.Text(items_text, size=13),
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Text(f"{t('orders.total_label', lang)}: {_format_price(order.total_irr, lang)}", size=13, weight=ft.FontWeight.W_600),
                        ft.Text(t(method_key, lang), size=12, color=theme.text_secondary(page)),
                    ],
                ),
            ],
        )
        controls = [header, body]
        if order.status == STATUS_PENDING_PAYMENT and order.expires_ts:
            minutes = (order.seconds_left() + 59) // 60
            controls.append(
                ft.Text(
                    t("orders.reserved_left", lang, minutes=minutes) if minutes else t("orders.reserved_over", lang),
                    key=f"reserve_{order.id}", size=11.5, color=theme.ACCENT_DARK,
                )
            )
        if order.paid_late:
            controls.append(ft.Text(t("orders.paid_late", lang), key=f"late_{order.id}", size=11.5, color=theme.DANGER, weight=ft.FontWeight.W_500))
        details = [x for x in (order.customer_name, order.customer_phone, order.customer_address) if x]
        if details:
            controls.append(ft.Text(" · ".join(details), key=f"customer_{order.id}", size=11.5, color=theme.text_secondary(page)))
        extra = extra_info_lines(order)
        if extra:
            controls.append(ft.Text(" · ".join(extra), key=f"extra_{order.id}", size=11.5, color=theme.text_secondary(page)))
        if order.status == STATUS_CONFIRMED and order.delivered_ts != -1:
            delivered = order.delivered_ts > 0
            controls.append(ft.Text(_delivery_label(delivered, lang), key=f"delivery_{order.id}", size=11.5, color=theme.SUCCESS if delivered else theme.DANGER))
            if not delivered and manager is not None:
                controls.append(ft.OutlinedButton(key=f"redeliver_{order.id}", content=_redeliver_label(lang), icon=ft.Icons.SEND_ROUNDED,
                                                  on_click=lambda e, oid=order.id: handle_redeliver(oid)))
        if order.payment_reference:
            controls.append(
                ft.Text(f"{t('orders.reference_label', lang)}: {order.payment_reference}", size=11, color=theme.text_secondary(page))
            )
        if order.status == STATUS_PAID:
            controls.append(
                ft.Row(
                    spacing=10,
                    controls=[
                        ft.Button(
                            key=f"confirm_{order.id}",
                            content=t("orders.confirm", lang),
                            icon=ft.Icons.CHECK_ROUNDED,
                            bgcolor=theme.SUCCESS,
                            color="#FFFFFF",
                            on_click=lambda e, oid=order.id: handle_confirm(oid),
                        ),
                        ft.OutlinedButton(
                            key=f"reject_{order.id}",
                            content=t("orders.reject", lang),
                            icon=ft.Icons.CLOSE_ROUNDED,
                            on_click=lambda e, oid=order.id: handle_reject(oid),
                        ),
                    ],
                )
            )
            controls.append(ft.Text(t("orders.confirm_note", lang), size=11, color=theme.text_secondary(page)))

        return ft.Container(key=f"order_{order.id}", content=card(page, ft.Column(spacing=10, controls=controls), padding=16))

    def render_list() -> None:
        orders = order_store.list(status=ui["filter"] or None)
        error_text.value = ui["error"]
        error_text.visible = bool(ui["error"])
        notice_text.value = ui["notice"]
        notice_text.visible = bool(ui["notice"])
        if not orders:
            list_column.controls = [
                ft.Container(
                    padding=30,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=8,
                        controls=[
                            ft.Icon(ft.Icons.RECEIPT_LONG_OUTLINED, size=34, color=theme.text_secondary(page)),
                            ft.Text(t("orders.empty", lang), size=13, color=theme.text_secondary(page), text_align=ft.TextAlign.CENTER),
                        ],
                    ),
                )
            ]
        else:
            list_column.controls = [order_card(o) for o in orders]

    def handle_filter_change(e) -> None:
        ui["filter"] = e.control.value
        render_list()
        page.update()

    filter_dropdown = ft.Dropdown(
        key="status_filter",
        label=t("orders.filter.all", lang),
        value="",
        width=230,
        border_radius=10,
        options=[ft.DropdownOption(key="", text=t("orders.filter.all", lang))]
        + [ft.DropdownOption(key=s, text=t(f"orders.status.{s}", lang)) for s in _ALL_STATUSES],
        on_select=handle_filter_change,
    )

    render_list()

    return ft.Container(
        expand=True,
        padding=ft.Padding.symmetric(horizontal=32, vertical=24),
        content=ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=18,
            controls=[
                page_header(page, ft.Icons.RECEIPT_LONG_ROUNDED, t("orders.title", lang), t("orders.subtitle", lang)),
                *(
                    [
                        owner_settings.build(page, lang, settings, manager),
                        payment_settings.build(page, lang, settings, save_callback or (lambda: None), manager),
                    ]
                    if settings is not None
                    else []
                ),
                filter_dropdown,
                error_text,
                notice_text,
                list_column,
            ],
        ),
    )
