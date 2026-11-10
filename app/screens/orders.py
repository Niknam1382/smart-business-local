"""صفحه‌ی «سفارش‌ها» (فقط حالت فروشگاه) — دیدن سفارش‌ها، رسیدهایِ کارت‌به‌کارت و
تایید/رد سفارش‌های پرداخت‌شده.

بخش «منتظرِ بررسیِ شما» بالای لیست، سفارش‌های «پرداخت‌شده» را از تازه به قدیم
نشان می‌دهد: همان‌هایی که مشتری پرداخت را اعلام کرده (کارت‌به‌کارت) یا درگاه
پرداختشان را تأیید کرده و هنوز تأییدِ نهاییِ تو لازم است.
**تأییدِ کارت‌به‌کارت همیشه دستی است** — این صفحه هیچ‌وقت چیزی را خودکار تأیید
نمی‌کند؛ فقط رسید (متن یا عکس)، کدِ رهگیری و نظرِ برنامه دربارهٔ مبلغ را نشان می‌دهد.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import flet as ft

from app import theme
from app.core import jalali, shop_texts
from app.core import report_pdf, report_xlsx
from app.core.bot_manager import BotManagerError
from app.core.owner_console import extra_info_lines
from app.core.orders import (
    FULFILL_DELIVERED,
    FULFILL_PREPARING,
    FULFILL_SHIPPED,
    METHOD_BALE_PAY,
    METHOD_CARD_TO_CARD,
    STATUS_CANCELLED,
    STATUS_CLOSED,
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
    build_order_fulfillment_text,
)
from app.i18n import t
from app.screens import owner_settings, payment_settings
from app.screens.common import card, get_or_create_file_picker, open_folder, page_header, screen_frame

logger = logging.getLogger(__name__)

_ALL_STATUSES = [
    STATUS_PENDING_PAYMENT, STATUS_PAID, STATUS_CONFIRMED, STATUS_REJECTED, STATUS_CANCELLED,
    STATUS_EXPIRED, STATUS_CLOSED,
]
_PLATFORM_ICON = {"telegram": ft.Icons.SEND_ROUNDED, "bale": ft.Icons.CHAT_BUBBLE_OUTLINE_ROUNDED}

# قلم ۵: کنشگرِ همین صفحه «app» است — دقیقاً همان چیزی که دکمه‌ی تأیید می‌فرستد
# (``order_store.confirm(order_id, by="app")``). نامِ واقعیِ ادمین/مدیر فقط در سمتِ ربات
# (owner_console/admin_panel با ``actor_of``) معلوم است و آنجا ممیزی می‌شود.
_ACTOR = "app"

# فایلِ ارسالی برای مشتری: همان قراردادِ اعتبارسنجیِ ``broadcast.MAX_PHOTO_BYTES`` و
# ``products._ALLOWED_PHOTO_EXTENSIONS`` (پسوند + حجم)، فقط با سقفِ بزرگ‌تر چون اینجا
# بارنامه/PDF/فشرده هم فرستاده می‌شود.
MAX_FILE_BYTES = 20 * 1024 * 1024
SENDABLE_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".txt", ".csv",
    ".xlsx", ".docx", ".zip", ".rar", ".7z",
)
MAX_CAPTION_CHARS = 1000  # همان سقفِ کپشنِ ``telegram_adapter.send_document_strict``


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
    "fulfill.notify_switch": ("📬 با هر تغییرِ وضعیتِ ارسال (آماده‌سازی / ارسال شد / تحویل شد) به مشتری خبر بده", "📬 Message the customer on every fulfilment change (preparing / shipped / delivered)"),
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
    # گزارشِ رسمیِ اکسل/PDF (بخش ۸ از master prompt) — همان فیلترِ وضعیتِ فعالِ همین صفحه
    "export.hint": ("گزارشِ رسمیِ همین فهرست:", "Formal report for this list:"),
    "export.xlsx": ("خروجِ اکسل", "Excel export"),
    "export.pdf": ("خروجِ PDF", "PDF export"),
    "export.done": ("✅ گزارشِ {n} سطری ساخته شد: {path}", "✅ Report with {n} rows created: {path}"),
    "export.failed": ("ساختنِ فایل ناموفق بود: {error}", "Could not create the file: {error}"),
    # ---- برچسبِ وضعیت و فیلترها («بسته‌شده» کلیدِ app/i18n ندارد؛ اینجا دو زبانه است) ----
    "status.closed": ("بسته‌شده", "Closed"),
    "filter.open": ("همه (به‌جز بسته‌شده‌ها)", "All except closed"),
    "filter.closed": ("سفارش‌های بسته‌شده", "Closed orders"),
    # ---- «میزِ سفارش» (قلم ۵): پیام/فایل/کد رهگیری/تحویل + بستنِ سفارش ----
    "desk.head": ("🗂 میزِ سفارش — پیام، فایل و بستن", "🗂 Order desk — message, file, close"),
    "desk.target": ("فرستادن برایِ همین مشتری: {platform} · {chat_id}", "Sends go to this customer: {platform} · {chat_id}"),
    "desk.msg_label": ("متنِ پیام — همان متن، کپشنِ فایل هم می‌شود", "Message text — the same field is used as the file caption"),
    "desk.send": ("📤 پیام به مشتری", "📤 Message the customer"),
    "desk.file": ("📎 ارسال فایل", "📎 Send a file"),
    "desk.pick_title": ("فایلی برایِ فرستادن به این مشتری انتخاب کن", "Pick a file to send this customer"),
    "desk.tracking": ("🔎 فرستادنِ کد رهگیری", "🔎 Send the tracking code"),
    "desk.delivered": ("📦 تحویل شد", "📦 Delivered"),
    "desk.sent": ("✅ پیامِ تو برای مشتریِ سفارش #{id} رفت.", "✅ Your message for order #{id} was sent."),
    "desk.send_failed": ("⚠️ پیام نرفت: {reason}", "⚠️ Nothing was sent: {reason}"),
    "desk.file_sent": ("✅ فایلِ «{name}» با کپشنِ {caption} برای مشتریِ سفارش #{id} رفت.", "✅ “{name}” (caption: {caption}) was sent for order #{id}."),
    "desk.file_sent_plain": ("✅ فایلِ «{name}» برای مشتریِ سفارش #{id} رفت.", "✅ “{name}” was sent for order #{id}."),
    "desk.file_failed": ("⚠️ فایل نرفت: {reason}", "⚠️ The file was not sent: {reason}"),
    "desk.empty": ("اول متنِ پیام را بنویس.", "Write the message first."),
    "desk.no_bot": (
        "⚠️ ربات روشن/وصل نیست؛ هیچ چیزی برای مشتری نرفته است. اول از صفحه‌ی «ربات‌ها» روشنش کن.",
        "⚠️ The bot is not running, so nothing was sent. Turn it on from the “Bots” screen first.",
    ),
    "desk.caption_long": (
        "کپشنِ فایل بیشتر از {n} نویسه است؛ کوتاه‌اش کن (پیامِ طولانی را جدا بفرست).",
        "The caption is longer than {n} characters — shorten it (send long text separately).",
    ),
    "desk.file_missing": ("فایلِ انتخاب‌شده پیدا نشد یا خوانده نشد.", "The picked file was not found or could not be read."),
    "desk.file_type": ("این نوعِ فایل فرستاده نمی‌شود. مجاز: {types}", "That file type is not sent. Allowed: {types}"),
    "desk.file_big": ("حجمِ فایل بیشتر از {mb} مگابایت است؛ خلاصه‌اش کن یا لینک بفرست.", "The file is above {mb} MB — compress it or send a link."),
    "desk.no_tracking": (
        "برایِ این سفارش کد رهگیری ثبت نشده؛ اول در «وضعیتِ ارسال» کد را بنویس و ذخیره کن.",
        "This order has no tracking code yet — write and save one under “Fulfilment” first.",
    ),
    "desk.gone": ("این سفارش دیگه وجود نداره.", "This order no longer exists."),
    "desk.close": ("🔒 بستنِ سفارش", "🔒 Close the order"),
    "desk.close_sure": ("✅ مطمئنم؛ ببند", "✅ Yes, close it"),
    "desk.close_arm": (
        "اگر یک بارِ دیگر بزنی، سفارش بسته می‌شود و از فهرستِ کاری بیرون می‌رود. پول و موجودی دست نمی‌خورد.",
        "One more click closes the order and drops it from your working list. Money and stock are untouched.",
    ),
    "desk.close_hint": (
        "بستن یعنی پیام‌ها و ارسالِ این مشتری تمام شده؛ هیچ داده‌ای پاک نمی‌شود و سفارش فقط به "
        "فیلترِ «سفارش‌های بسته‌شده» می‌رود.",
        "Closing means the messaging and delivery for this customer are done; nothing is deleted — the order only "
        "moves to the “Closed orders” filter.",
    ),
    "desk.closed": ("✅ سفارش #{id} بسته شد و از فهرستِ کاری بیرون رفت.", "✅ Order #{id} was closed and left your working list."),
    "desk.close_failed": ("بستنِ سفارش انجام نشد: ", "Could not close the order: "),
    "desk.closed_readonly": (
        "🔒 این سفارش بسته شده است و این‌جا فقط خواندنی نمایش داده می‌شود. بستن هیچ راهِ بازکردنِ خودکار "
        "ندارد (از «بسته‌شده» هیچ حرکتِ مجازی تعریف نشده، چون پول و موجودی نباید دوباره باز شود)؛ اگر "
        "کاری باقی مانده، در «گفتگوها» به همان مشتری پیام بده یا سفارشِ تازه‌ای ثبت کن.",
        "🔒 This order is closed and is shown read-only here. Closing has no automatic way back (nothing is a valid "
        "transition out of “closed”, because money and stock must not be re-applied); if something is still due, "
        "message the customer from “Chats” or create a new order.",
    ),
}



def _s(key: str, lang: str, **kw) -> str:
    fa, en = _S[key]
    text = en if lang == "en" else fa
    return text.format(**kw) if kw else text


def _status_label(status: str, lang: str) -> str:
    """برچسبِ فارسی/انگلیسیِ وضعیت. «بسته‌شده» کلیدِ ``app/i18n`` ندارد (و آن فایل دست‌نخورده می‌ماند)،
    پس همین‌جا دو زبانه تعریف شده — وگرنه صفحه «orders.status.closed» خام به کاربر نشان می‌داد."""
    if status == STATUS_CLOSED:
        return _s("status.closed", lang)
    return t(f"orders.status.{status}", lang)


def _file_problem(path: str, lang: str) -> str:
    """چرا این فایل را *نمی‌فرستیم*؟ ``""`` یعنی سالم است.

    همان قراردادِ ``broadcast.store_photo`` (پوندِ مجاز + سقفِ حجم + خواندنِ فایل) — قبل ازِ هر
    تماسِ شبکه، تا «فایلِ بی‌اعتبار» هرگز به‌عنوانِ ارسال‌شده ثبت نشود."""
    if not path:
        return _s("desk.file_missing", lang)
    src = Path(path)
    if src.suffix.lower() not in SENDABLE_EXTENSIONS:
        return _s("desk.file_type", lang, types="، ".join(SENDABLE_EXTENSIONS))
    try:
        size = src.stat().st_size
    except (OSError, ValueError):
        return _s("desk.file_missing", lang)
    if size > MAX_FILE_BYTES:
        return _s("desk.file_big", lang, mb=MAX_FILE_BYTES // (1024 * 1024))
    if size == 0:
        return _s("desk.file_missing", lang)
    return ""


def _updated_jalali(order: Order) -> str:
    """تاریخِ آخرین تغییرِ سفارش به جلالی (UTC ذخیره می‌شه، به وقتِ تهران نمایش داده می‌شه)."""
    try:
        ts = datetime.strptime(order.updated_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        return jalali.format_dt(ts)
    except (ValueError, OverflowError, OSError, jalali.JalaliError):
        return ""


def _status_color(status: str) -> str:
    return {
        STATUS_PENDING_PAYMENT: theme.WARNING,
        STATUS_PAID: theme.ACCENT,
        STATUS_CONFIRMED: theme.SUCCESS,
        STATUS_REJECTED: theme.DANGER,
        STATUS_CANCELLED: theme.DANGER,
        STATUS_EXPIRED: theme.TEXT_SECONDARY_LIGHT,
        STATUS_CLOSED: theme.TEXT_SECONDARY_LIGHT,
    }.get(status, theme.INFO)


def _format_price(amount: int, lang: str) -> str:
    return f"{amount:,} {t('products.price_suffix', lang)}"


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
    ui = {"filter": "", "error": "", "notice": "", "armed": None}
    list_column = ft.Column(spacing=12)
    error_text = ft.Text("", key="orders_error", size=12, color=theme.DANGER, visible=False)
    notice_text = ft.Text("", key="orders_notice", size=12, color=theme.SUCCESS, visible=False)
    desk_fields: dict = {}  # order_id -> فیلدِ متنِ «میزِ سفارش» (برایِ خالی‌کردن بعد از ارسالِ موفق)

    def show_status() -> None:
        """نتیجه‌ی یک کارِ فقط-شبکه‌ای را نشان بده، **بدونِ بازسازیِ لیست** — متنِ تایپ‌شده‌ی
        ادمین نباید به‌خاطرِ یک ارسالِ ناموفق پاک بشه (برعکسِ render_list که کارت‌ها را از نو می‌سازد)."""
        error_text.value, error_text.visible = ui["error"], bool(ui["error"])
        notice_text.value, notice_text.visible = ui["notice"], bool(ui["notice"])

    def say(error: str = "", notice: str = "") -> None:
        ui["error"], ui["notice"] = error, notice
        show_status()
        page.update()

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
            manager.send_message_sync(order.platform, order.chat_id, build_order_fulfillment_text(order))
            ui["notice"] = _s("fulfill.notify_sent", lang)
        except BotManagerError as exc:
            ui["error"] = _s("fulfill.notify_failed", lang, id=order.id, reason=str(exc))

    def apply_fulfillment(order_id: int, state: str, tracking: str) -> None:
        """فقط وضعیتِ فیزیکیِ سفارش عوض می‌شه — هیچ منطقِ پولی اینجا نیست. پیامِ «ارسال شد»
        فقط برایِ گذارِ *اول* به «shipped» می‌ره (اصلاحِ کد رهگیری، مشتری را دوباره بمباران نمی‌کند)."""
        previous = order_store.get(order_id)
        previous_state = previous.fulfillment if previous is not None else ""
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
        should_notify = (bool(state) and state != previous_state and settings is not None
                         and bool(getattr(settings, "notify_on_fulfillment", True)))
        if should_notify:
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

    # ------------------------------------------------- «میزِ سفارش» (قلم ۵: پیام، فایل، بستن)
    def _can_send(attr: str) -> bool:
        """ربات/اتصال‌ها باید باشد و *هم* مسیرِ درستِ ارسال را داشته باشد (قلم ۵: متن و فایل
        هر دو «سخت»ند — خطا می‌دهند، پس هیچ‌وقت چیزی را «رفته» حساب نمی‌کنیم مگر اینکه واقعاً برود)."""
        return manager is not None and callable(getattr(manager, attr, None))

    def send_desk_text(order_id: int, raw: str) -> None:
        """پیامِ خصوصیِ ادمین به مشتریِ همین سفارش — از همان مسیرِ ``send_to_customer_sync``
        (قوانینِ صفحه‌ی گفتگوها: بلاک/لغو/پیشوندِ «فروشگاه» و ثبت در تاریخچه با نقشِ ``owner``)."""
        order = order_store.get(order_id)
        if order is None:
            say(error=_s("desk.gone", lang))
            return
        text = (raw or "").strip()
        if not text:
            say(error=_s("desk.empty", lang))
            return
        if not _can_send("send_to_customer_sync"):
            say(error=_s("desk.no_bot", lang))
            return

        def work() -> None:
            try:
                manager.send_to_customer_sync(order.platform, order.chat_id, text)
            except BotManagerError as exc:
                say(error=_s("desk.send_failed", lang, reason=str(exc)))
            except Exception as exc:  # noqa: BLE001 — شکستِ ارسال هرگز «موفق» حساب نمی‌شود
                logger.exception("ارسالِ پیامِ ادمین از صفحه‌ی سفارش‌ها ناموفق بود")
                say(error=_s("desk.send_failed", lang, reason=f"{type(exc).__name__}: {exc}"))
            else:
                field = desk_fields.get(order_id)
                if field is not None:
                    field.value = ""
                say(notice=_s("desk.sent", lang, id=order.id))

        page.run_thread(work)

    def send_desk_file(order_id: int, path: str) -> None:
        """فایل با همان مسیرِ سختِ فاکتور (``send_file_to_customer_sync``) می‌رود: اگر نرود،
        ``BotManagerError`` فارسی بالا می‌آید و همین‌جا نمایش داده می‌شود — ثبت می‌شود که *نرفته*."""
        order = order_store.get(order_id)
        if order is None:
            say(error=_s("desk.gone", lang))
            return
        problem = _file_problem(path, lang)
        if problem:
            say(error=problem)
            return
        field = desk_fields.get(order_id)
        caption = ((field.value if field is not None else "") or "").strip()
        if len(caption) > MAX_CAPTION_CHARS:
            say(error=_s("desk.caption_long", lang, n=MAX_CAPTION_CHARS))
            return
        if not _can_send("send_file_to_customer_sync"):
            say(error=_s("desk.no_bot", lang))
            return

        def work() -> None:
            try:
                manager.send_file_to_customer_sync(order.platform, order.chat_id, path, caption)
            except BotManagerError as exc:
                say(error=_s("desk.file_failed", lang, reason=str(exc)))
            except Exception as exc:  # noqa: BLE001
                logger.exception("ارسالِ فایل به مشتری از صفحه‌ی سفارش‌ها ناموفق بود")
                say(error=_s("desk.file_failed", lang, reason=type(exc).__name__))
            else:
                if field is not None:
                    field.value = ""
                name = Path(path).name
                if caption:
                    say(notice=_s("desk.file_sent", lang, name=name, caption=caption, id=order.id))
                else:
                    say(notice=_s("desk.file_sent_plain", lang, name=name, id=order.id))

        page.run_thread(work)

    async def pick_desk_file(order_id: int) -> None:
        """دیالوگِ انتخاب فایلِ سیستم‌عامل (همان الگوی ``broadcast``/``products``): یک فایل، بدونِ
        چندانتخابی. روی وب/تست دیالوگ نیست ⇒ ``FletUnsupportedPlatformException`` و هیچ چیزی فرستاده نمی‌شود."""
        if not _can_send("send_file_to_customer_sync"):
            say(error=_s("desk.no_bot", lang))
            return
        picker = get_or_create_file_picker(page)
        try:
            result = await picker.pick_files(
                dialog_title=_s("desk.pick_title", lang), allow_multiple=False,
                file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=list(SENDABLE_EXTENSIONS),
            )
        except ft.FletUnsupportedPlatformException:
            result = None
        if result:
            send_desk_file(order_id, result[0].path)

    def send_tracking_code(order_id: int) -> None:
        """اقدامِ سریع: کد رهگیریِ ثبت‌شده با همان متنِ همیشگیِ ربات (``ord.tracking`` — «🔎 کد رهگیری: …»)
        برایِ مشتری می‌رود، نه با متنِ تازه‌نویس‌شده."""
        order = order_store.get(order_id)
        if order is None:
            say(error=_s("desk.gone", lang))
            return
        if not order.tracking_code:
            say(error=_s("desk.no_tracking", lang))
            return
        send_desk_text(order_id, shop_texts.t("ord.tracking", code=order.tracking_code))

    def handle_close(order_id: int) -> None:
        try:
            order_store.close(order_id, by=_ACTOR)  # ممیزیِ ``by`` در لاگِ ``app.core.orders`` ثبت می‌شود
        except OrderError as exc:
            ui["armed"] = None
            ui["error"] = _s("desk.close_failed", lang) + str(exc)
            ui["notice"] = ""
            render_list()
            page.update()
            return
        ui["armed"] = None
        ui["error"] = ""
        ui["notice"] = _s("desk.closed", lang, id=order_id)
        render_list()
        page.update()

    def handle_close_arm(order_id: int) -> None:
        """تأییدِ دو مرحله‌ای (همان الگوی ``ui["armed"]`` در admins/broadcast/customers): کلیکِ اول
        فقط آماده می‌کند و متنِ دکمه عوض می‌شود؛ کلیکِ دوم می‌بندد."""
        if ui["armed"] != order_id:
            ui["armed"] = order_id
            ui["error"] = ""
            ui["notice"] = _s("desk.close_arm", lang)
            render_list()
            page.update()
            return
        handle_close(order_id)

    def order_desk_block(order: Order) -> ft.Control:
        """بخشِ جداِ سفارشِ تأییدشده: پیام/فایل به همان مشتری، کد رهگیری، تحویل، و بستنِ سفارش.

        روی هر کلیک فقط *خوانده* یا *ارسال* می‌شود؛ هیچ مبلغ و هیچ موجودی اینجا عوض نمی‌شود.
        شکستِ ارسال (ربات خاموش، مشتری بلاک/دسترس‌ناپذیر) با دلیلِ فارسی نشان داده می‌شود."""
        msg = ft.TextField(
            key=f"desk_msg_{order.id}", label=_s("desk.msg_label", lang),
            multiline=True, min_lines=2, max_lines=5, width=430, dense=True, border_radius=10,
        )
        desk_fields[order.id] = msg
        actions: list[ft.Control] = [
            ft.Button(
                key=f"desk_send_{order.id}", content=_s("desk.send", lang), icon=ft.Icons.SEND_ROUNDED,
                bgcolor=theme.ACCENT, color="#FFFFFF",
                on_click=lambda e, oid=order.id, fld=msg: send_desk_text(oid, fld.value),
            ),
            ft.OutlinedButton(
                key=f"desk_file_{order.id}", content=_s("desk.file", lang), icon=ft.Icons.ATTACH_FILE_ROUNDED,
                on_click=lambda e, oid=order.id: pick_desk_file(oid),
            ),
            ft.OutlinedButton(
                key=f"desk_tracking_{order.id}", content=_s("desk.tracking", lang),
                icon=ft.Icons.TRACK_CHANGES_ROUNDED, on_click=lambda e, oid=order.id: send_tracking_code(oid),
            ),
        ]
        if order.fulfillment == FULFILL_SHIPPED:  # «تحویل شد» فقط از «ارسال شد» مجاز است (FULFILL._FORWARD)
            actions.append(
                ft.Button(
                    key=f"desk_delivered_{order.id}", content=_s("desk.delivered", lang),
                    icon=ft.Icons.INVENTORY_2_ROUNDED, bgcolor=theme.SUCCESS, color="#FFFFFF",
                    on_click=lambda e, oid=order.id: apply_fulfillment(oid, FULFILL_DELIVERED, order.tracking_code),
                )
            )
        armed = ui["armed"] == order.id
        return ft.Container(
            key=f"desk_{order.id}",
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            border_radius=12,
            border=ft.Border.all(1, theme.border_color(page)),
            bgcolor=f"{theme.ACCENT}0A",
            content=ft.Column(
                spacing=8,
                controls=[
                    ft.Text(_s("desk.head", lang), size=13, weight=ft.FontWeight.W_700),
                    ft.Text(
                        _s("desk.target", lang, platform=order.platform, chat_id=order.chat_id),
                        key=f"desk_target_{order.id}", size=11.5, color=theme.text_secondary(page), selectable=True,
                    ),
                    msg,
                    ft.Row(spacing=8, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=actions),
                    ft.Row(
                        spacing=8,
                        wrap=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Button(
                                key=f"desk_close_{order.id}",
                                content=_s("desk.close_sure" if armed else "desk.close", lang),
                                icon=ft.Icons.CHECK_ROUNDED if armed else ft.Icons.LOCK_ROUNDED,
                                bgcolor=theme.DANGER, color="#FFFFFF",
                                on_click=lambda e, oid=order.id: handle_close_arm(oid),
                            ),
                            ft.Text(
                                _s("desk.close_arm", lang) if armed else _s("desk.close_hint", lang),
                                key=f"desk_close_hint_{order.id}", size=11.5,
                                color=theme.DANGER if armed else theme.text_secondary(page),
                            ),
                        ],
                    ),
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

        who = order_store.confirmed_by(order.id) if order.status in (STATUS_CONFIRMED, STATUS_CLOSED) else ""
        decision = _s("paystat.decided", lang, who=who) if who else (_s("paystat.rejected", lang) if order.status == STATUS_REJECTED else "")
        if decision:
            when = _updated_jalali(order)
            if when:
                decision += _s("paystat.when", lang, when=when)
            lines.append(ft.Text(decision, key=f"paystat_decision_{order.id}", size=12, color=theme.INFO))

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
        rows.append(ft.Text(t("orders.receipts.manual_note", lang), size=11.5, color=theme.WARNING))
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
                    content=ft.Text(_status_label(order.status, lang), size=11.5, color=_status_color(order.status), weight=ft.FontWeight.W_500),
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
        if order.payment_method or receipts_of(order) or order.status in (STATUS_PAID, STATUS_CONFIRMED, STATUS_REJECTED, STATUS_CLOSED):
            controls.append(payment_status_block(order))
        if order.status == STATUS_CONFIRMED:
            controls.append(fulfillment_block(order))
            controls.append(order_desk_block(order))
        elif order.status == STATUS_CLOSED:
            controls.append(
                ft.Text(
                    _s("desk.closed_readonly", lang), key=f"closed_note_{order.id}", size=12,
                    color=theme.ACCENT_DARK, selectable=True,
                )
            )
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

    def visible_orders() -> list:
        """فهرستِ همین صفحه.

        قلم ۵: پیش‌فرض («همه») هیچ سفارشِ **بسته‌شده‌ای** نشان داده نمی‌شود — بسته‌شدن یعنی «از
        لیستِ کاری بیرون برو»، نه پاک‌شدن. فیلترِ «سفارش‌های بسته‌شده» همان‌ها را می‌آورد و معنایِ
        بقیه‌ی فیلترها (تک‌وضعیتی) مثلِ قبل است."""
        status = ui["filter"] or None
        orders = order_store.list(status=status)
        if status is None:
            orders = [o for o in orders if o.status != STATUS_CLOSED]
        return orders

    def render_list() -> None:
        render_attention()
        desk_fields.clear()  # کارت‌ها از نو ساخته می‌شوند؛ فیلدهایِ سفارش‌های رفته نماند
        orders = visible_orders()
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

    def do_report(fmt: str, _e=None) -> None:
        """گزارشِ رسمیِ **همان فهرستِ فیلترشده** (وضعیتِ انتخابی) در فایلِ اکسل یا PDFِ راست‌به‌چپ.

        فایل در ``<داده>/reports`` ساخته می‌شود و پوشه‌اش باز می‌شود — همان تجربه‌ی فاکتور. هیچ
        سفارشی اینجا تغییر نمی‌کند: فقط خواندنِ سطور و نوشتنِ فایل. «همه» دقیقاً مثلِ فهرستِ
        صفحه، سفارش‌های بسته‌شده را ندارد."""

        def work() -> None:
            try:
                data = report_xlsx.orders_report(visible_orders(),
                                                 shop_name=report_xlsx.shop_name_of(settings or manager))
                path = report_pdf.write_pdf(data) if fmt == "pdf" else report_xlsx.write_xlsx(data)
            except report_xlsx.ReportError as exc:  # «چیزی برای خروجی گرفتن نیست» / شکستِ PDF
                ui["error"], ui["notice"] = str(exc), ""
            except OSError as exc:
                ui["error"], ui["notice"] = _s("export.failed", lang, error=str(exc)), ""
            except Exception as exc:  # noqa: BLE001 — دیتابیسِ سفارش‌ها در حالتِ مشاوره ممکن است نباشد
                ui["error"], ui["notice"] = _s("export.failed", lang, error=type(exc).__name__), ""
            else:
                ui["error"], ui["notice"] = "", _s("export.done", lang, n=data.count, path=str(path))
                open_folder(path.parent)
            render_list()
            page.update()

        page.run_thread(work)

    report_row = ft.Row(
        spacing=10,
        wrap=True,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Text(_s("export.hint", lang), size=12.5, color=theme.text_secondary(page)),
            ft.OutlinedButton(key="orders_export_xlsx", content=_s("export.xlsx", lang),
                              icon=ft.Icons.TABLE_VIEW, on_click=lambda e: do_report("xlsx")),
            ft.OutlinedButton(key="orders_export_pdf", content=_s("export.pdf", lang),
                              icon=ft.Icons.PICTURE_AS_PDF_ROUNDED, on_click=lambda e: do_report("pdf")),
        ],
    )

    def handle_filter_change(e) -> None:
        ui["filter"] = e.control.value
        ui["armed"] = None  # آمادگیِ «بستن» مالِ کارتِ قبلیِ صفحه است
        render_list()
        page.update()

    filter_dropdown = ft.Dropdown(
        key="status_filter",
        label=_s("filter.open", lang),
        value="",
        width=230,
        border_radius=10,
        options=[ft.DropdownOption(key="", text=_s("filter.open", lang))]
        + [
            ft.DropdownOption(key=s, text=_s("filter.closed", lang) if s == STATUS_CLOSED else _status_label(s, lang))
            for s in _ALL_STATUSES
        ],
        on_select=handle_filter_change,
    )

    # سوییچِ «اعلانِ ارسال به مشتری» فقط وقتی کارتِ تنظیمات هست (settings داده شده) — همان سبکی که پرداخت‌ها مقدار را زنده می‌نویسن
    notify_switch = None
    if settings is not None:
        def handle_notify_toggle(e) -> None:
            settings.notify_on_fulfillment = bool(e.control.value)
            if save_callback is not None:
                save_callback()

        notify_switch = ft.Switch(
            key="notify_on_fulfillment",
            label=_s("fulfill.notify_switch", lang),
            value=bool(getattr(settings, "notify_on_fulfillment", True)),
            active_color=theme.SUCCESS,
            on_change=handle_notify_toggle,
        )

    render_list()

    return screen_frame(
        page,
        page_header(page, ft.Icons.RECEIPT_LONG_ROUNDED, t("orders.title", lang), t("orders.subtitle", lang)),
        [
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
                report_row,
                *( [notify_switch] if notify_switch is not None else [] ),
                error_text,
                notice_text,
                list_column,
        ],
        key="orders_page",
    )
