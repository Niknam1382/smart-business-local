"""صفحه‌ی «سفارش‌ها» (فقط حالت فروشگاه) — دیدن سفارش‌ها، رسیدهایِ کارت‌به‌کارت و
تایید/رد سفارش‌های پرداخت‌شده.

بخش «منتظرِ بررسیِ شما» بالای لیست، سفارش‌های «پرداخت‌شده» را از تازه به قدیم
نشان می‌دهد: همان‌هایی که مشتری پرداخت را اعلام کرده (کارت‌به‌کارت) یا درگاه
پرداختشان را تأیید کرده و هنوز تأییدِ نهاییِ تو لازم است.
**تأییدِ کارت‌به‌کارت همیشه دستی است** — این صفحه هیچ‌وقت چیزی را خودکار تأیید
نمی‌کند؛ فقط رسید (متن یا عکس)، کدِ رهگیری و نظرِ برنامه دربارهٔ مبلغ را نشان می‌دهد.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import flet as ft

from app import theme
from app.core import jalali
from app.core.bot_manager import BotManagerError
from app.core.owner_console import extra_info_lines
from app.core.orders import (
    FULFILL_DELIVERED,
    FULFILL_PREPARING,
    FULFILL_SHIPPED,
    METHOD_BALE_PAY,
    METHOD_CARD_TO_CARD,
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
    build_order_shipped_text,
)
from app.i18n import t
from app.screens import owner_settings, payment_settings
from app.screens.common import card, page_header

_ALL_STATUSES = [STATUS_PENDING_PAYMENT, STATUS_PAID, STATUS_CONFIRMED, STATUS_REJECTED, STATUS_CANCELLED, STATUS_EXPIRED]
_PLATFORM_ICON = {"telegram": ft.Icons.SEND_ROUNDED, "bale": ft.Icons.CHAT_BUBBLE_OUTLINE_ROUNDED}

# متن‌های مخصوصِ همین صفحه (دوزبانه) — کلیدهایِ تازه به app/i18n اضافه نمی‌شن
_S = {
    "fulfill.head": ("وضعیتِ ارسال", "Fulfilment"),
    "fulfill.preparing": ("🧰 در حال آماده‌سازی", "🧰 Preparing"),
    "fulfill.shipped": ("🚚 ارسال شد", "🚚 Shipped"),
    "fulfill.delivered": ("📦 تحویل داده شد", "📦 Delivered"),
    "fulfill.clear": ("✖️ برگشت (هنوز ارسال نشده)", "✖️ Undo (not shipped yet)"),
    "fulfill.none": ("شروع‌نشده", "Not started"),
    "fulfill.state": ("وضعیتِ ارسال: {state}", "Fulfilment: {state}"),
    "fulfill.code": (" · کد رهگیری: {code}", " · tracking: {code}"),
    "fulfill.updated": (" · آخرین تغییر: {when}", " · last change: {when}"),
    "fulfill.tracking_label": ("کد رهگیری (اختیاری، تا ۶۴ نویسه)", "Tracking code (optional, up to 64 chars)"),
    "fulfill.save": ("💾 ذخیره", "💾 Save"),
    "fulfill.saved": ("وضعیتِ ارسالِ سفارش #{id} ثبت شد.", "Fulfilment of order #{id} saved."),
    "fulfill.error": ("وضعیتِ ارسال ثبت نشد: ", "Could not save the fulfilment state: "),
    "fulfill.notify_sent": ("📬 پیامِ «ارسال شد» برای مشتری رفت.", "📬 The “shipped” notice was sent to the customer."),
    "fulfill.notify_failed": (
        "⚠️ پیامِ «ارسال شد» برای سفارش #{id} نرفت ({reason})؛ وضعیت ثبت شده و خودت خبرش کن.",
        "⚠️ The “shipped” notice for order #{id} was not sent ({reason}); the state is saved — tell the customer yourself.",
    ),
    "fulfill.notify_switch": ("📬 با «ارسال شد»، پیامِ کوتاهِ ارسال (+کد رهگیری) برای مشتری برود", "📬 Notify the customer when an order is marked shipped (+tracking code)"),
    # کارتِ «وضعیتِ پرداخت» — فقط خواندنی: هیچ مبلغی اینجا حساب یا نوشته نمی‌شه، فقط آنچه
    # از قبل در دیتابیس هست (سفارش، رسید، تأییدکننده) یک‌جا و جمع‌وجور نمایش داده می‌شه.
    "paystat.head": ("💳 وضعیتِ پرداخت", "💳 Payment status"),
    "paystat.method": ("روشِ پرداخت: {value}", "Payment method: {value}"),
    "paystat.total": ("مبلغِ سفارش: {value}", "Order total: {value}"),
    "paystat.receipt": ("مبلغِ خوانده‌شده از رسید: {value}", "Amount read from the receipt: {value}"),
    "paystat.receipt_none": ("رسیدی در دسترس نیست", "No receipt available"),
    "paystat.trace": ("کدِ پیگیری/رهگیری: {value}", "Trace/reference code: {value}"),
    "paystat.trace_none": ("کدِ پیگیری‌ای در دسترس نیست", "No trace/reference code available"),
    "paystat.match_ok": ("✅ مبلغِ رسید با سفارش می‌خونه", "✅ The receipt amount matches the order"),
    "paystat.match_bad": ("⚠️ مبلغِ رسید با سفارش نمی‌خونه (اختلاف: {diff})", "⚠️ The receipt amount does NOT match the order (difference: {diff})"),
    "paystat.match_none": ("رسید مبلغِ قابل‌مقایسه‌ای نداشت", "The receipt had no comparable amount"),
    "paystat.decided": ("تأییدکننده: {who}", "Confirmed by: {who}"),
    "paystat.rejected": ("این سفارش رد شده است", "This order was rejected"),
    "paystat.when": (" · آخرین تغییر: {when}", " · last update: {when}"),
    "paystat.gateway_waiting": ("درگاه هنوز نتیجه‌ای نفرستاده (پرداخت تأییدنشده)", "The gateway has not reported a result yet (payment unverified)"),
    "paystat.gateway_link": ("لینکِ پرداخت ساخته شد؛ در انتظارِ نتیجه‌ی درگاه", "A payment link was created; waiting for the gateway's result"),
    "paystat.gateway_verified": ("✅ تراکنشِ درگاه راستی‌آزمایی و ثبت شد", "✅ The gateway transaction was verified and recorded"),
    "paystat.gateway_late": ("⚠️ پرداختِ درگاه بعد از مهلتِ رزرو رسید؛ دستی تصمیم بگیر", "⚠️ The gateway payment arrived after the hold expired; decide manually"),
}


def _s(key: str, lang: str, **kw) -> str:
    fa, en = _S[key]
    text = en if lang == "en" else fa
    return text.format(**kw) if kw else text


def _updated_jalali(order: Order) -> str:
    """تاریخِ آخرین تغییرِ سفارش به جلالی (UTC ذخیره می‌شه، به وقتِ تهران نمایش داده می‌شه)."""
    try:
        ts = datetime.strptime(order.updated_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        return jalali.format_dt(ts)
    except (ValueError, OverflowError, OSError, jalali.JalaliError):
        return ""


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


def _receipt_verdict(page: ft.Page, order: Order, receipt: dict, lang: str) -> tuple[str, str, ft.FontWeight]:
    """نظرِ برنامه دربارهٔ مبلغِ رسید + رنگش. این فقط راهنمایِ چشمیِ مالک است، نه داورِ
    نهایی: ``amount_mismatch`` هرگز سفارش را رد نمی‌کند و ``amount_ok`` هم تأیید نمی‌کند."""
    state = receipt.get("match_state") or "none"
    amount = int(receipt.get("amount_irr") or 0)
    total = int(order.total_irr or 0)
    if state == "amount_ok":
        return t("orders.receipt.amount_ok", lang, amount=f"{amount:,}"), theme.SUCCESS, ft.FontWeight.W_600
    if state == "amount_mismatch":
        diff = total - amount
        word = t("orders.receipt.less", lang) if diff > 0 else t("orders.receipt.more", lang)
        return (
            t(
                "orders.receipt.amount_mismatch", lang,
                receipt_amount=f"{amount:,}", order_amount=f"{total:,}", diff=f"{abs(diff):,}", word=word,
            ),
            theme.DANGER,
            ft.FontWeight.W_700,
        )
    return t("orders.receipt.amount_none", lang), theme.text_secondary(page), ft.FontWeight.NORMAL


def _has_mismatch(receipts: list) -> bool:
    return any((r.get("match_state") or "none") == "amount_mismatch" for r in receipts)


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
            order_store.confirm(order_id, by="app")  # N11: چه کسی تأیید کرد
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

    def notify_shipment(order: Order) -> None:
        """اعلانِ «ارسال شد» دقیقاً مثلِ تایید: وضعیت در دیتابیس *قبلاً* ثبت شده؛ شکستِ ارسال
        فقط به مالک هشدار می‌دهد و چیزی را پس نمی‌گیرد. رباتِ خاموش = بی‌صدا رد می‌شیم."""
        if manager is None:
            return
        try:
            manager.send_message_sync(order.platform, order.chat_id, build_order_shipped_text(order))
            ui["notice"] = _s("fulfill.notify_sent", lang)
        except BotManagerError as exc:
            ui["error"] = _s("fulfill.notify_failed", lang, id=order.id, reason=str(exc))

    def apply_fulfillment(order_id: int, state: str, tracking: str) -> None:
        """فقط وضعیتِ فیزیکیِ سفارش عوض می‌شه — هیچ منطقِ پولی اینجا نیست. پیامِ «ارسال شد»
        فقط برایِ گذارِ *اول* به «shipped» می‌ره (اصلاحِ کد رهگیری، مشتری را دوباره بمباران نمی‌کند)."""
        previous = order_store.get(order_id)
        already_shipped = previous is not None and previous.fulfillment == FULFILL_SHIPPED
        ui["notice"] = ""
        try:
            order = order_store.set_fulfillment(order_id, state, tracking_code=tracking, by="app")
            ui["error"] = ""
            ui["notice"] = _s("fulfill.saved", lang, id=order.id)
        except OrderError as exc:
            ui["error"] = _s("fulfill.error", lang) + str(exc)
            render_list()
            page.update()
            return
        render_list()
        page.update()
        if state == FULFILL_SHIPPED and not already_shipped and settings is not None and getattr(settings, "notify_on_shipment", False):
            page.run_thread(lambda: (notify_shipment(order), render_list(), page.update()))

    def fulfillment_block(order: Order) -> ft.Control:
        """کارتِ «ارسال» روی سفارشِ تأییدشده: دکمه‌های رو‌به‌جلو + فیلدِ کد رهگیری + خطِ وضعیت."""
        tracking = ft.TextField(
            key=f"tracking_{order.id}", label=_s("fulfill.tracking_label", lang), value=order.tracking_code,
            width=260, text_align=ft.TextAlign.LEFT, border_radius=10, dense=True,
        )
        buttons: list[ft.Control] = []
        if order.fulfillment == "":
            buttons.append(
                ft.OutlinedButton(
                    key=f"fulfill_preparing_{order.id}", content=_s("fulfill.preparing", lang), icon=ft.Icons.HANDYMAN_ROUNDED,
                    on_click=lambda e, oid=order.id, fld=tracking: apply_fulfillment(oid, FULFILL_PREPARING, (fld.value or "")),
                )
            )
        elif order.fulfillment == FULFILL_PREPARING:
            buttons.append(
                ft.Button(
                    key=f"fulfill_shipped_{order.id}", content=_s("fulfill.shipped", lang), icon=ft.Icons.LOCAL_SHIPPING_ROUNDED,
                    bgcolor=theme.SUCCESS, color="#FFFFFF",
                    on_click=lambda e, oid=order.id, fld=tracking: apply_fulfillment(oid, FULFILL_SHIPPED, (fld.value or "")),
                )
            )
            buttons.append(
                ft.OutlinedButton(
                    key=f"fulfill_clear_{order.id}", content=_s("fulfill.clear", lang), icon=ft.Icons.UNDO_ROUNDED,
                    on_click=lambda e, oid=order.id: apply_fulfillment(oid, "", ""),  # پاک‌کردنِ «همه‌چیز» — کد هم می‌ره
                )
            )
        elif order.fulfillment == FULFILL_SHIPPED:
            buttons.append(
                ft.Button(
                    key=f"fulfill_delivered_{order.id}", content=_s("fulfill.delivered", lang), icon=ft.Icons.INVENTORY_2_ROUNDED,
                    bgcolor=theme.SUCCESS, color="#FFFFFF",
                    on_click=lambda e, oid=order.id, fld=tracking: apply_fulfillment(oid, FULFILL_DELIVERED, (fld.value or "")),
                )
            )
        if order.fulfillment:  # «ذخیره» روی وضعیتِ خالی بی‌معنی است (کد بدونِ هیچ مرحله‌ای)
            buttons.append(
                ft.OutlinedButton(
                    key=f"tracking_save_{order.id}", content=_s("fulfill.save", lang), icon=ft.Icons.SAVE_ROUNDED,
                    on_click=lambda e, oid=order.id, st=order.fulfillment, fld=tracking: apply_fulfillment(oid, st, (fld.value or "")),
                )
            )
        state_line = _s("fulfill.state", lang, state=_s(f"fulfill.{order.fulfillment}", lang) if order.fulfillment else _s("fulfill.none", lang))
        if order.tracking_code:
            state_line += _s("fulfill.code", lang, code=order.tracking_code)
        when = _updated_jalali(order)
        if when:
            state_line += _s("fulfill.updated", lang, when=when)
        return ft.Container(
            key=f"fulfill_{order.id}",
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            border_radius=12,
            border=ft.Border.all(1, theme.border_color(page)),
            bgcolor=f"{theme.PRIMARY}08",
            content=ft.Column(
                spacing=8,
                controls=[
                    ft.Text(state_line, key=f"fulfill_state_{order.id}", size=12.5, weight=ft.FontWeight.W_600),
                    ft.Row(spacing=8, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[tracking, *buttons]),
                ],
            ),
        )

    def receipts_of(order: Order) -> list:
        """رسیدهایِ این سفارش از تازه به قدیم (dict هایِ همون جدولِ payment_receipts)."""
        rows = list(getattr(order, "receipts", None) or [])
        if rows:
            return sorted(rows, key=lambda r: int(r.get("id") or 0), reverse=True)
        try:  # سفارشی که دستی ساخته شده (بدونِ hydrate) — از خودِ فروشگاه می‌خونیم
            return list(order_store.receipts_for(order.id))
        except Exception:  # noqa: BLE001 — رسید نداشتن هرگز نباید صفحه را بشکنه
            return []

    def payment_status_block(order: Order) -> ft.Control:
        """کارتِ «وضعیتِ پرداخت»: یک نگاهِ جمع‌وجور به آنچه همین حالا ثبت شده — روش، مبلغ،
        رسیدِ مشتری، کدِ پیگیری، تطابق، تأییدکننده و نتیجه‌ی راستی‌آزماییِ درگاه.

        هیچ عددی اینجا حساب نمی‌شه و چیزی نوشته نمی‌شه؛ فقط خواندن."""
        method = t(f"orders.payment_method.{order.payment_method or 'none'}", lang)
        receipts = receipts_of(order)
        newest = receipts[0] if receipts else None
        lines: list[ft.Control] = [
            ft.Text(_s("paystat.head", lang), key=f"paystat_head_{order.id}", size=13, weight=ft.FontWeight.W_700),
            ft.Text(_s("paystat.method", lang, value=method), key=f"paystat_method_{order.id}", size=12),
            ft.Text(_s("paystat.total", lang, value=_format_price(order.total_irr, lang)), key=f"paystat_total_{order.id}", size=12),
        ]
        if newest is not None:
            amount = int(newest.get("amount_irr") or 0)
            lines.append(
                ft.Text(
                    _s("paystat.receipt", lang, value=_format_price(amount, lang)) if amount > 0 else _s("paystat.receipt_none", lang),
                    key=f"paystat_receipt_{order.id}", size=12,
                )
            )
            state = newest.get("match_state") or "none"
            diff = order.total_irr - amount
            if state == "amount_ok":
                match_text, match_color, match_weight = _s("paystat.match_ok", lang), theme.SUCCESS, ft.FontWeight.W_600
            elif state == "amount_mismatch":
                match_text, match_color, match_weight = (
                    _s("paystat.match_bad", lang, diff=_format_price(abs(diff), lang)), theme.DANGER, ft.FontWeight.W_700
                )
            else:
                match_text, match_color, match_weight = _s("paystat.match_none", lang), theme.text_secondary(page), ft.FontWeight.NORMAL
            lines.append(ft.Text(match_text, key=f"paystat_match_{order.id}", size=12.5, color=match_color, weight=match_weight))
        else:
            lines.append(ft.Text(_s("paystat.receipt_none", lang), key=f"paystat_receipt_{order.id}", size=12, color=theme.text_secondary(page)))

        trace = (newest or {}).get("trace_code") if newest else ""
        trace = trace or order.payment_reference
        lines.append(
            ft.Text(
                _s("paystat.trace", lang, value=trace) if trace else _s("paystat.trace_none", lang),
                key=f"paystat_trace_{order.id}", size=12, color=theme.text_secondary(page) if not trace else theme.TEXT_PRIMARY_LIGHT,
            )
        )

        who = order_store.confirmed_by(order.id) if order.status == STATUS_CONFIRMED else ""
        decision = _s("paystat.decided", lang, who=who) if who else (_s("paystat.rejected", lang) if order.status == STATUS_REJECTED else "")
        if decision:
            when = _updated_jalali(order)
            if when:
                decision += _s("paystat.when", lang, when=when)
            lines.append(ft.Text(decision, key=f"paystat_decision_{order.id}", size=12, color=theme.ACCENT_DARK))

        if order.payment_method == METHOD_BALE_PAY:
            if order.paid_late:
                gateway_text, gateway_color = _s("paystat.gateway_late", lang), theme.DANGER
            elif order.status in (STATUS_PAID, STATUS_CONFIRMED) and order.payment_reference:
                gateway_text, gateway_color = _s("paystat.gateway_verified", lang), theme.SUCCESS
            elif (order.payment_url or order.gateway_ref) and order.status == STATUS_PENDING_PAYMENT:
                gateway_text, gateway_color = _s("paystat.gateway_link", lang), theme.ACCENT_DARK
            else:
                gateway_text, gateway_color = _s("paystat.gateway_waiting", lang), theme.text_secondary(page)
            lines.append(ft.Text(gateway_text, key=f"paystat_gateway_{order.id}", size=12, color=gateway_color, weight=ft.FontWeight.W_600))

        return ft.Container(
            key=f"paystat_{order.id}",
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            border_radius=12,
            border=ft.Border.all(1, theme.border_color(page)),
            bgcolor=f"{theme.ACCENT}08",
            content=ft.Column(spacing=4, controls=lines),
        )

    def receipt_panel(order: Order) -> Optional[ft.Control]:
        """پنلِ رسید: متنِ خواناتر، عکسِ واقعیِ رسید، کدِ رهگیری و نظرِ برنامه دربارهٔ مبلغ.

        هیچ دکمهٔ «قبولِ خودکار» اینجا نیست — تصمیم با مالک است؛ ما فقط چیزی که مشتری
        فرستاده را کامل و خوانا نشان می‌دهیم."""
        receipts = receipts_of(order)
        if not receipts:
            return None
        rows: list[ft.Control] = [
            ft.Row(
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(ft.Icons.RECEIPT_LONG_ROUNDED, size=16, color=theme.PRIMARY),
                    ft.Text(t("orders.receipts.title", lang), size=12.5, weight=ft.FontWeight.W_600),
                    ft.Text(t("orders.receipts.count", lang, n=len(receipts)), size=11.5, color=theme.text_secondary(page)),
                ],
            )
        ]
        if _has_mismatch(receipts):
            rows.append(
                ft.Text(t("orders.receipts.mismatch_banner", lang), size=12, weight=ft.FontWeight.W_700, color=theme.DANGER)
            )
        for idx, r in enumerate(receipts[:5]):
            kind = r.get("kind") or "text"
            inner: list[ft.Control] = [
                ft.Text(
                    t("orders.receipt.image_label" if kind == "image" else "orders.receipt.text_label", lang, n=idx + 1),
                    size=11.5, color=theme.text_secondary(page), weight=ft.FontWeight.W_500,
                )
            ]
            if kind == "image" and r.get("file_path"):
                inner.append(
                    ft.Image(
                        key=f"receipt_img_{order.id}_{idx}", src=r["file_path"], width=240, height=240,
                        fit=ft.BoxFit.CONTAIN, border_radius=10,
                    )
                )
            body = (r.get("body") or "").strip()
            if body:
                inner.append(
                    ft.Container(
                        padding=10, border_radius=10, bgcolor=f"{theme.PRIMARY}0A",
                        content=ft.Text(body, key=f"receipt_body_{order.id}_{idx}", size=12.5, selectable=True, expand=True),
                    )
                )
            verdict, color, weight = _receipt_verdict(page, order, r, lang)
            inner.append(ft.Text(verdict, key=f"receipt_state_{order.id}_{idx}", size=12.5, color=color, weight=weight))
            facts = []
            if r.get("trace_code"):
                facts.append(t("orders.receipt.trace", lang, code=r["trace_code"]))
            if r.get("card_last4"):
                facts.append(t("orders.receipt.card_last4", lang, last4=r["card_last4"]))
            if facts:
                inner.append(
                    ft.Text(" · ".join(facts), key=f"receipt_trace_{order.id}_{idx}", size=11.5, selectable=True, color=theme.text_secondary(page))
                )
            rows.append(
                ft.Container(
                    key=f"receipt_{order.id}_{idx}",
                    padding=ft.Padding.symmetric(horizontal=12, vertical=10),
                    border_radius=12,
                    border=ft.Border.all(1, theme.border_color(page)),
                    content=ft.Column(spacing=6, controls=inner),
                )
            )
        rows.append(ft.Text(t("orders.receipts.manual_note", lang), size=11.5, color=theme.ACCENT_DARK))
        return ft.Container(
            key=f"receipts_{order.id}",
            padding=ft.Padding.symmetric(horizontal=14, vertical=12),
            border_radius=12,
            bgcolor=f"{theme.ACCENT}0C",
            content=ft.Column(spacing=8, controls=rows),
        )

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
        if order.payment_method or receipts_of(order) or order.status in (STATUS_PAID, STATUS_CONFIRMED, STATUS_REJECTED):
            controls.append(payment_status_block(order))
        if order.status == STATUS_CONFIRMED and order.delivered_ts != -1:
            delivered = order.delivered_ts > 0
            controls.append(ft.Text(_delivery_label(delivered, lang), key=f"delivery_{order.id}", size=11.5, color=theme.SUCCESS if delivered else theme.DANGER))
            if not delivered and manager is not None:
                controls.append(ft.OutlinedButton(key=f"redeliver_{order.id}", content=_redeliver_label(lang), icon=ft.Icons.SEND_ROUNDED,
                                                  on_click=lambda e, oid=order.id: handle_redeliver(oid)))
        if order.status == STATUS_CONFIRMED:
            controls.append(fulfillment_block(order))
        if order.payment_reference:
            controls.append(
                ft.Text(f"{t('orders.reference_label', lang)}: {order.payment_reference}", size=11, color=theme.text_secondary(page))
            )
        panel = receipt_panel(order)
        if panel is not None:
            controls.append(panel)
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

    # ------------------------------------------ صفِ «منتظرِ بررسیِ شما» (بالای لیست)
    attention_title = ft.Text(t("orders.attention.title", lang), key="attention_title", size=15, weight=ft.FontWeight.W_700)
    attention_summary = ft.Text("", key="attention_summary", size=12, color=theme.ACCENT_DARK)
    attention_rows = ft.Column(key="attention_rows", spacing=8)
    attention_box = ft.Container(
        key="attention_box",
        padding=ft.Padding.symmetric(horizontal=16, vertical=14),
        border_radius=14,
        bgcolor=f"{theme.ACCENT}0F",
        border=ft.Border.all(1, theme.ACCENT_DARK),
        content=ft.Column(
            spacing=8,
            controls=[
                ft.Row(
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[ft.Icon(ft.Icons.NOTIFICATIONS_ACTIVE_ROUNDED, size=18, color=theme.ACCENT_DARK), attention_title],
                ),
                attention_summary,
                attention_rows,
                ft.Text(t("orders.attention.manual_note", lang), size=11.5, color=theme.text_secondary(page)),
            ],
        ),
    )

    def newest_receipt(order: Order) -> Optional[dict]:
        receipts = receipts_of(order)
        return receipts[0] if receipts else None

    def render_attention() -> None:
        """سفارش‌های «پرداخت‌شده» از تازه به قدیم — همان صفِ ``receipts_needing_attention()``
        با دانه‌بندیِ سفارش. دکمهٔ تأیید/رد روی خودِ کارتِ سفارش می‌مونه (این‌جا تکرار نمی‌شه)."""
        try:
            pending = [o for o in order_store.list(status=STATUS_PAID)]
        except Exception:  # noqa: BLE001 — دیتابیسِ سفارش‌ها در حالتِ مشاوره ممکن است نباشد
            pending = []
        pending.sort(key=lambda o: o.id, reverse=True)
        attention_box.visible = bool(pending)
        attention_summary.value = t("orders.attention.summary", lang, n=len(pending))
        rows: list[ft.Control] = []
        for order in pending[:10]:
            receipt = newest_receipt(order)
            if receipt is None:
                if order.payment_method == METHOD_BALE_PAY:
                    detail, color = t("orders.attention.no_receipt.bale_pay", lang), theme.text_secondary(page)
                elif order.payment_method == METHOD_CARD_TO_CARD:
                    detail, color = t("orders.attention.no_receipt.card", lang), theme.ACCENT_DARK
                else:
                    detail, color = t("orders.attention.no_receipt", lang), theme.text_secondary(page)
            else:
                detail, color, weight = _receipt_verdict(page, order, receipt, lang)
                if receipt.get("kind") == "image":
                    detail = t("orders.attention.image_prefix", lang) + " " + detail
            lines = [
                t(
                    "orders.attention.line", lang,
                    id=order.id, amount=_format_price(order.total_irr, lang),
                    method=t(f"orders.payment_method.{order.payment_method or 'none'}", lang),
                )
            ]
            who = " · ".join(x for x in (order.customer_name, order.customer_phone) if x)
            if who:
                lines.append(who)
            rows.append(
                ft.Container(
                    key=f"attention_{order.id}",
                    padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                    border_radius=10,
                    bgcolor=theme.card_bgcolor(page),
                    content=ft.Column(
                        spacing=3,
                        controls=[
                            ft.Text(" · ".join(lines), size=12.5, weight=ft.FontWeight.W_600),
                            ft.Text(detail, size=11.5, color=color),
                        ],
                    ),
                )
            )
        if len(pending) > 10:
            rows.append(ft.Text(t("orders.attention.more", lang, n=len(pending) - 10), size=11.5, color=theme.text_secondary(page)))
        attention_rows.controls = rows

    def render_list() -> None:
        render_attention()
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

    # سوییچِ «اعلانِ ارسال به مشتری» فقط وقتی کارتِ تنظیمات هست (settings داده شده) — همان سبکی که پرداخت‌ها مقدار را زنده می‌نویسن
    notify_switch = None
    if settings is not None:
        def handle_notify_toggle(e) -> None:
            settings.notify_on_shipment = bool(e.control.value)
            if save_callback is not None:
                save_callback()

        notify_switch = ft.Switch(
            key="notify_on_shipment",
            label=_s("fulfill.notify_switch", lang),
            value=bool(getattr(settings, "notify_on_shipment", False)),
            active_color=theme.SUCCESS,
            on_change=handle_notify_toggle,
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
                attention_box,
                filter_dropdown,
                *( [notify_switch] if notify_switch is not None else [] ),
                error_text,
                notice_text,
                list_column,
            ],
        ),
    )
