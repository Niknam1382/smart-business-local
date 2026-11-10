"""
صفحه‌ی «گفتگوها» (فاز ۳): لیست مکالمه‌های تلگرام در یه ستون، جزئیات
مکالمه‌ی انتخاب‌شده (تاریخچه‌ی پیام‌ها، سوییچ حافظه، بلاک/رفع‌بلاک) در ستون
کناری. گفتگوهای «بله» هم از همان دیتابیس لیست و خوانده می‌شن؛ از قلم ۲۴ گفتگوی
تازه‌ی بله هم ساخته می‌شه (پیام‌رسان فقط از آیکن/برچسبش معلوم می‌شه).

داده مستقیم از ``manager.store`` (SQLite) خونده می‌شه — همون منبعی که ترد
ربات‌ها ذخیره می‌کنه؛ هیچ callback بین‌تردی‌ای درکار نیست. هر ~۲ ثانیه
(LiveRefresher) لیست و جزئیات دوباره از دیتابیس خونده می‌شن تا پیام‌های
تازه بدون نیاز به ترک صفحه دیده بشن.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Optional

import flet as ft

from app import theme
from app.core import jalali
from app.core import report_pdf, report_xlsx
from app.core.bot_manager import BotManagerError
from app.core.conversations import ConversationSummary
from app.i18n import STRINGS, t
from app.screens.common import card, open_folder, page_header
from app.screens.live import LiveRefresher

_PLATFORM_ICON = {"telegram": ft.Icons.SEND_ROUNDED, "bale": ft.Icons.CHAT_BUBBLE_OUTLINE_ROUNDED}


logger = logging.getLogger(__name__)

_MAX_PERSONAL = 3000  # هم‌سقف با BotManager.send_to_customer

# متن‌های «پیامِ شخصی به مشتری» (N6) — محلی تا i18n.py بیش از این بزرگ نشه
_P = {
    "owner": ("شما", "You"),
    "hint": ("پیامت را برای این مشتری بنویس…", "Write your message to this customer…"),
    "template": ("قالبِ آماده", "Quick reply"),
    "send": ("بفرست", "Send"),
    "note": ("مشتری پیام را به‌شکلِ «💬 فروشگاه: …» می‌بیند.", "The customer sees it as “💬 Shop: …”."),
    "sent": ("✅ پیام فرستاده شد.", "✅ Message sent."),
    "failed": ("پیام فرستاده نشد؛ دوباره امتحان کن.", "The message was not sent; please try again."),
    "empty": ("اول متنِ پیام را بنویس.", "Write the message first."),
    "blocked": ("این مشتری بلاک شده؛ برای پیام‌دادن اول بلاکش را بردار.", "This customer is blocked; unblock them to send a message."),
    "stopped": ("این مشتری با /stop دریافتِ پیام را لغو کرده؛ بهش پیام نده.", "This customer opted out with /stop; do not message them."),
    "off": ("ربات‌ها خاموشن؛ برای پیام‌دادن اول روشنشان کن.", "The bots are off; turn them on to send a message."),
    "tpl.1": ("سلام! سفارش شما در حال بررسی است.", "Hi! Your order is being reviewed."),
    "tpl.2": ("سفارش شما ارسال شد و به‌زودی به دستتان می‌رسد.", "Your order has been shipped and will arrive soon."),
    "tpl.3": ("ممنون از صبرتان؛ تا چند دقیقه‌ی دیگر پاسخ می‌دهم.", "Thanks for your patience; I'll reply in a few minutes."),
    "tpl.4": ("متأسفانه این کالا فعلاً موجود نیست؛ جایگزین پیشنهاد بدهم؟", "Sorry, this item is out of stock for now; shall I suggest an alternative?"),
    "tpl.5": ("ممنون از خریدتان 🙏", "Thank you for your purchase 🙏"),
    # گزارشِ رسمیِ گفتگوها (بخش ۸ از master prompt) — تاریخچه‌ی گفتگویِ انتخاب‌شده یا فهرستِ گفتگوها
    "export.hint": ("گزارشِ رسمیِ گفتگوها:", "Formal report of the chats:"),
    "export.xlsx": ("خروجِ اکسل", "Excel export"),
    "export.pdf": ("خروجِ PDF", "PDF export"),
    "export.done": ("✅ گزارشِ {n} سطری ساخته شد: {path}", "✅ Report with {n} rows created: {path}"),
    "export.failed": ("ساختنِ فایل ناموفق بود: {error}", "Could not create the file: {error}"),
    # ── قلم ۶: پرمصرف‌ها + کارتِ مشخصاتِ مشتری + مدیریتِ شخصی‌سازی‌شده (سقفِ AI) ──
    # این کلیدها محلیِ همین صفحه‌اند (i18n.py دست‌نخورده). نام‌هایی که بعداً ارزشِ ارتقا به i18n دارند:
    # chats.sort.*  chats.id.*  chats.limit.*  chats.open_customer
    "sort.label": ("مرتب‌سازی", "Sort"),
    "sort.recent": ("تازه‌ترین", "Recent"),
    "sort.volume": ("پرمصرف‌ترین", "Most used"),
    "id.title": ("مشخصاتِ مشتری", "Customer details"),
    "id.name": ("نام", "Name"),
    "id.username": ("نامِ کاربری", "Username"),
    "id.id": ("شناسه", "ID"),
    "id.platform": ("پیام‌رسان", "Messenger"),
    "id.first": ("اولینِ دیدار", "First seen"),
    "id.last": ("آخرینِ دیدار", "Last seen"),
    "id.messages": ("مجموعِ پیام‌ها", "Total messages"),
    "id.orders": ("سفارش‌ها", "Orders"),
    "id.language": ("زبان", "Language"),
    "id.tags": ("برچسب‌ها", "Tags"),
    "id.blocked": ("بلاک", "Blocked"),
    "id.unreachable": ("دست‌نیافتنی", "Unreachable"),
    "id.yes": ("بله", "yes"),
    "id.no": ("خیر", "no"),
    "id.none": ("این گفتگو هنوز در فهرستِ مشتریان نیست؛ مشخصاتِ پایه از خودِ گفتگو نشان داده می‌شه.", "This chat isn’t in the customer list yet; basic details come from the chat itself."),
    "limit.label": ("سقفِ پاسخِ AI در روز", "Daily AI answer limit"),
    "limit.hint": ("خالی = سراسری · ۰ = بدونِ AI", "Empty = global cap · 0 = no AI"),
    "limit.save": ("ذخیره‌ی سقف", "Save limit"),
    "limit.saved": ("✅ سقفِ شخصی ذخیره شد.", "✅ Personal limit saved."),
    "limit.bad": ("سقف باید عددی بین ۰ تا ۱۰۰۰ باشد (یا خالی).", "The limit must be a number between 0 and 1000 (or empty)."),
    "open.customer": ("باز کردنِ پرونده‌ی مشتری", "Open customer record"),
}


def tp(key: str, lang: str, **kw) -> str:
    fa, en = _P[key]
    text = en if lang == "en" else fa
    return text.format(**kw) if kw else text


def _format_time(raw: str) -> str:
    """``created_at`` توی دیتابیس UTC و به‌شکل ``YYYY-MM-DD HH:MM:SS``ه. برای
    نمایش به وقت محلی تبدیل می‌شه؛ هر فرمت غیرمنتظره بی‌خطر همون خام برمی‌گرده
    (هیچ‌وقت نباید به‌خاطر یه رشته‌ی عجیب کل صفحه کرش کنه)."""
    try:
        dt_utc = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return raw or ""
    return jalali.format_chat_time(dt_utc.timestamp())  # جلالی، به وقتِ تهران


def build(
    page: ft.Page, lang: str, manager, on_open_bots: Callable[[], None],
    on_open_customer: Optional[Callable[[str, str], None]] = None,
) -> tuple[ft.Control, Callable[[], None]]:
    state = {"platform": None, "chat_id": None, "initialized": False, "sort": "recent", "limit_for": None}
    last = {"list_snap": None, "detail_snap": None}
    clear_armed = {"key": None}  # کلید مکالمه‌ای که منتظر کلیک تاییدیه برای پاک‌کردن تاریخچه‌ست

    list_view = ft.ListView(expand=True, spacing=2, padding=ft.Padding.symmetric(vertical=4))
    detail_area = ft.Column(key="detail_area", expand=True, spacing=12)
    bots_off_banner = ft.Container(key="bots_off_banner", visible=False)

    # ------------------------------------------------- پیامِ شخصی به مشتری (N6)
    # این کادر عمداً *بیرونِ* detail_area است: detail_area با هر پیامِ تازه بازسازی می‌شه و متنِ نیمه‌نوشته را پاک می‌کرد.
    personal_note = ft.Text(key="personal_note", size=12, color=theme.text_secondary(page))
    personal_result = ft.Text(key="personal_result", size=12, visible=False)
    personal_input = ft.TextField(
        key="personal_input", hint_text=tp("hint", lang), multiline=True, min_lines=1, max_lines=4, max_length=_MAX_PERSONAL,
        expand=True, border_radius=10,
    )
    personal_send = ft.FilledButton(key="personal_send", content=tp("send", lang), icon=ft.Icons.SEND_ROUNDED)
    personal_template = ft.Dropdown(
        key="personal_template", hint_text=tp("template", lang), border_radius=10, width=220,
        options=[ft.DropdownOption(key=str(i), text=tp(f"tpl.{i}", lang)[:34]) for i in range(1, 6)],
    )
    personal_box = ft.Container(key="personal_box", visible=False)

    def show_result(message: str, ok: bool) -> None:
        personal_result.value = message
        personal_result.color = theme.SUCCESS if ok else theme.DANGER
        personal_result.visible = True

    def personal_block_reason() -> str:
        """چرا الان نباید پیام فرستاد؟ (خالی = می‌شه). همان قانون‌های سمتِ سرور، فقط برای نمایشِ زودهنگام."""
        platform, chat_id = state["platform"], state["chat_id"]
        if manager.store.is_blocked(platform, chat_id):
            return tp("blocked", lang)
        customers = getattr(manager, "customers", None)
        customer = customers.get(platform, chat_id) if customers is not None else None
        if customer is not None and customer.opted_out:
            return tp("stopped", lang)
        if not manager.is_running():
            return tp("off", lang)
        return ""

    def refresh_composer() -> None:
        personal_box.visible = bool(state["chat_id"])
        if not state["chat_id"]:
            return
        reason = personal_block_reason()
        personal_note.value = reason or tp("note", lang)
        personal_note.color = theme.ACCENT_DARK if reason else theme.text_secondary(page)
        personal_input.disabled = personal_send.disabled = personal_template.disabled = bool(reason)

    def on_template(e=None) -> None:
        key = personal_template.value
        if key:
            personal_input.value = tp(f"tpl.{key}", lang)
            personal_template.value = None  # تا دوباره همان قالب هم قابل‌انتخاب باشد
            personal_result.visible = False
            page.update()

    def on_send_personal(e=None) -> None:
        platform, chat_id = state["platform"], state["chat_id"]
        text = (personal_input.value or "").strip()
        if not chat_id:
            return
        if not text:
            show_result(tp("empty", lang), False)
            page.update()
            return
        personal_send.disabled = True
        page.update()

        def work() -> None:
            try:
                manager.send_to_customer_sync(platform, chat_id, text)
            except BotManagerError as exc:
                ok, message = False, str(exc)
            except Exception:  # noqa: BLE001 — UI هرگز نباید به‌خاطرِ خطای ارسال بشکنه
                logger.exception("ارسالِ پیامِ شخصی ناموفق بود")
                ok, message = False, tp("failed", lang)
            else:
                ok, message = True, tp("sent", lang)
            if state["platform"] == platform and state["chat_id"] == chat_id:
                if ok:
                    personal_input.value = ""
                show_result(message, ok)
            refresh(force=True)  # پیامِ تازه در تاریخچه + بازتعیینِ فعال/غیرفعالِ دکمه
            page.update()

        page.run_thread(work)

    personal_send.on_click = on_send_personal
    personal_template.on_select = on_template
    personal_box.content = card(
        page,
        ft.Column(
            spacing=8,
            controls=[
                ft.Row(controls=[personal_template, personal_note], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=12),
                ft.Row(controls=[personal_input, personal_send], vertical_alignment=ft.CrossAxisAlignment.END, spacing=10),
                personal_result,
            ],
        ),
        padding=14,
    )

    # ------------------------------------------------- گزارشِ اکسل/PDFِ گفتگوها
    export_result = ft.Text(key="chats_export_result", size=12, visible=False)

    def show_export(message: str, ok: bool) -> None:
        export_result.value, export_result.color, export_result.visible = message, theme.SUCCESS if ok else theme.DANGER, bool(message)

    def on_report(fmt: str, _e=None) -> None:
        """تاریخچه‌ی گفتگویِ انتخاب‌شده (نقش/زمانِ جلالی + میلادی/متن) و اگر چیزی انتخاب نشده باشد
        فهرستِ گفتگوها را در فایلِ اکسل یا PDFِ راست‌به‌چپ می‌نویسد. فایل در ``<داده>/reports``
        می‌نشیند و پوشه‌اش باز می‌شود — همان تجربه‌ی فاکتور؛ هیچ پیامی تغییر/حذف نمی‌شود."""

        def work() -> None:
            platform, chat_id = state["platform"], state["chat_id"]
            try:
                if chat_id:
                    conv = next((c for c in manager.store.list_conversations(platform=platform) if c.chat_id == chat_id), None)
                    data = report_xlsx.transcript_report(
                        manager.store.get_messages(platform, chat_id, limit=report_xlsx.MAX_ROWS),
                        conversation=conv, shop_name=report_xlsx.shop_name_of(manager))
                else:
                    data = report_xlsx.conversations_report(manager.store.list_conversations(),
                                                            shop_name=report_xlsx.shop_name_of(manager))
                path = report_pdf.write_pdf(data) if fmt == "pdf" else report_xlsx.write_xlsx(data)
            except report_xlsx.ReportError as exc:  # «چیزی برای خروجی گرفتن نیست» / شکستِ PDF
                show_export(str(exc), False)
            except OSError as exc:
                show_export(tp("export.failed", lang, error=str(exc)), False)
            else:
                show_export(tp("export.done", lang, n=data.count, path=str(path)), True)
                open_folder(path.parent)
            page.update()

        page.run_thread(work)

    export_row = ft.Row(
        spacing=10,
        wrap=True,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Text(tp("export.hint", lang), size=12.5, color=theme.text_secondary(page)),
            ft.OutlinedButton(key="chats_export_xlsx", content=tp("export.xlsx", lang),
                              icon=ft.Icons.TABLE_VIEW, on_click=lambda e: on_report("xlsx")),
            ft.OutlinedButton(key="chats_export_pdf", content=tp("export.pdf", lang),
                              icon=ft.Icons.PICTURE_AS_PDF_ROUNDED, on_click=lambda e: on_report("pdf")),
            export_result,
        ],
    )

    def platform_label(platform: str) -> str:
        # ردیف‌هایِ قدیمیِ «بله» هنوز در دیتابیس ممکن است؛ برچسبشان سالم نمایش داده می‌شه.
        key = f"chats.platform.{platform}"
        return t(key, lang) if key in STRINGS else platform

    # ---------------------------------------------------------------- لیست
    def conversation_row(c: ConversationSummary) -> ft.Control:
        selected = (c.platform, c.chat_id) == (state["platform"], state["chat_id"])
        preview = (c.last_message_preview or "").replace("\n", " ")
        return ft.Container(
            key=f"conv_{c.platform}_{c.chat_id}",
            padding=ft.Padding.symmetric(horizontal=14, vertical=10),
            border_radius=10,
            bgcolor=f"{theme.ACCENT}1A" if selected else None,
            ink=True,
            on_click=lambda e, c=c: select(c.platform, c.chat_id),
            content=ft.Column(
                spacing=2,
                controls=[
                    ft.Row(
                        spacing=6,
                        controls=[
                            ft.Icon(_PLATFORM_ICON.get(c.platform, ft.Icons.CHAT_ROUNDED), size=14, color=theme.text_secondary(page)),
                            ft.Text(
                                c.display_name or c.chat_id,
                                size=13,
                                weight=ft.FontWeight.W_600,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                expand=True,
                            ),
                            ft.Icon(ft.Icons.BLOCK_ROUNDED, size=13, color=theme.DANGER) if c.blocked else ft.Container(),
                            ft.Container(
                                key=f"conv_count_{c.platform}_{c.chat_id}",
                                padding=ft.Padding.symmetric(horizontal=6, vertical=1),
                                border_radius=10,
                                bgcolor=f"{theme.PRIMARY}1F",
                                content=ft.Text(str(c.msg_count), size=10.5, color=theme.PRIMARY),
                            ),
                        ],
                    ),
                    ft.Text(
                        preview or "—",
                        size=12,
                        color=theme.text_secondary(page),
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                ],
            ),
        )

    def render_list(convs: list[ConversationSummary]) -> None:
        # مهم: همیشه همین list_view مونته‌شده رو جهش می‌دیم (نه سوییچ بین
        # دو درخت کنترل متفاوت در build) — وگرنه وقتی اولین مکالمه بعد از
        # ساخته‌شدن صفحه (لیست خالی) می‌رسه، تغییرش هیچ‌وقت روی صفحه دیده
        # نمی‌شه، چون کنترلِ نمایش‌داده‌شده از قبل «حالت خالی» بوده.
        convs = apply_sort(convs)
        if not convs:
            list_view.controls = [
                ft.Container(
                    padding=24,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=10,
                        controls=[
                            ft.Icon(ft.Icons.FORUM_OUTLINED, size=36, color=theme.text_secondary(page)),
                            ft.Text(
                                t("chats.empty", lang),
                                size=12,
                                color=theme.text_secondary(page),
                                text_align=ft.TextAlign.CENTER,
                            ),
                        ],
                    ),
                )
            ]
            return
        list_view.controls = [conversation_row(c) for c in convs]

    # -------------------------------------------------------------- جزئیات
    def message_bubble(role: str, content: str, created_at: str) -> ft.Control:
        is_user = role == "user"
        is_owner = role == "owner"  # N6: پیامِ شخصیِ مالک از همین برنامه
        bubble = ft.Container(
            padding=ft.Padding.symmetric(horizontal=14, vertical=10),
            border_radius=12,
            bgcolor=theme.card_bgcolor(page) if is_user else (f"{theme.ACCENT}1F" if is_owner else f"{theme.PRIMARY}14"),
            border=ft.Border.all(1, theme.border_color(page)),
            content=ft.Column(
                spacing=4,
                tight=True,
                controls=[
                    ft.Row(
                        spacing=6,
                        controls=[
                            ft.Text(
                                tp("owner", lang) if is_owner else t("chats.customer" if is_user else "chats.bot", lang),
                                size=11,
                                weight=ft.FontWeight.W_600,
                                color=theme.text_secondary(page) if is_user else (theme.ACCENT_DARK if is_owner else theme.PRIMARY),
                            ),
                            ft.Text(_format_time(created_at), size=11, color=theme.text_secondary(page)),
                        ],
                    ),
                    ft.Text(content, size=13, selectable=True),
                ],
            ),
        )
        return ft.Row(
            alignment=ft.MainAxisAlignment.START if is_user else ft.MainAxisAlignment.END,
            controls=[ft.Container(content=bubble, width=520)],
        )

    def select(platform: str, chat_id: str) -> None:
        state["platform"], state["chat_id"] = platform, chat_id
        clear_armed["key"] = None
        personal_input.value = ""  # پیامِ نیمه‌نوشته مالِ مشتریِ قبلی بود
        personal_template.value = None
        personal_result.visible = False
        sync_limit_field(platform, chat_id)  # فیلدِ سقف با مقادیرِ همین مکالمه پر می‌شه
        refresh(force=True)
        page.update()

    def on_memory_change(platform: str, chat_id: str, value: bool) -> None:
        manager.store.set_memory_enabled(platform, chat_id, value)
        refresh(force=True)
        page.update()

    def on_block_toggle(platform: str, chat_id: str, currently_blocked: bool) -> None:
        manager.store.set_blocked(platform, chat_id, not currently_blocked)
        refresh(force=True)
        page.update()

    def on_clear_history(platform: str, chat_id: str) -> None:
        # تاییدِ دوکلیکی درجا (به‌جای دیالوگ) — عمل مخرب و برگشت‌ناپذیره،
        # ولی نمی‌خوایم یه کلیک اشتباهی کل تاریخچه رو از دست بده.
        key = (platform, chat_id)
        if clear_armed.get("key") == key:
            manager.store.clear_history(platform, chat_id)
            clear_armed["key"] = None
            refresh(force=True)
        else:
            clear_armed["key"] = key
            render_detail()
        page.update()

    # ───────────────── قلم ۶: کنترل‌هایِ مرتب‌سازی و مدیریتِ شخصی‌سازی‌شده ─────────────────
    # این کنترل‌ها یک‌بار ساخته می‌شن و بیرونِ بازسازیِ detail_area زنده می‌مونن تا متنِ نیمه‌نوشته‌ی
    # فیلدِ سقف با هر پیامِ تازه پاک نشه (همان دلیلی که personal_box بیرونِ detail_area است).
    sort_control = ft.Dropdown(
        key="chats_sort", label=tp("sort.label", lang), value="recent", border_radius=10, width=220,
        options=[ft.DropdownOption(key="recent", text=tp("sort.recent", lang)), ft.DropdownOption(key="volume", text=tp("sort.volume", lang))],
    )
    daily_limit_field = ft.TextField(
        key="daily_limit_input", label=tp("limit.label", lang), hint_text=tp("limit.hint", lang),
        width=150, border_radius=10, keyboard_type=ft.KeyboardType.NUMBER,
    )
    daily_limit_note = ft.Text(key="daily_limit_note", size=12, visible=False)
    open_customer_button = ft.OutlinedButton(
        key="open_customer_button", content=tp("open.customer", lang), icon=ft.Icons.PERSON_SEARCH_ROUNDED,
        visible=on_open_customer is not None,
    )

    def apply_sort(convs: list[ConversationSummary]) -> list[ConversationSummary]:
        # «پرمصرف‌ترین» = بیشترینِ تعدادِ پیام (از شمارشِ خودِ دیتابیس)؛ در تساوی، تازه‌ترین اول.
        if state["sort"] == "volume":
            return sorted(convs, key=lambda c: (-c.msg_count, c.platform, c.chat_id))
        return convs

    def _format_ts(ts: int) -> str:
        return jalali.format_dt(ts) if ts else "—"

    def sync_limit_field(platform: str, chat_id: str) -> None:
        value = manager.store.get_limit_override(platform, chat_id)
        daily_limit_field.value = "" if value is None else str(value)
        daily_limit_note.visible = False
        state["limit_for"] = (platform, chat_id)

    def on_sort_change(e=None) -> None:
        if e is not None:
            state["sort"] = e.control.value or state["sort"]
        refresh(force=True)
        page.update()

    def on_save_limit(e=None) -> None:
        platform, chat_id = state["platform"], state["chat_id"]
        if not chat_id:
            return
        try:
            saved = manager.store.set_limit_override(platform, chat_id, daily_limit_field.value)
        except ValueError:
            daily_limit_note.value, daily_limit_note.color, daily_limit_note.visible = tp("limit.bad", lang), theme.DANGER, True
            page.update()
            return
        daily_limit_field.value = "" if saved is None else str(saved)
        daily_limit_note.value, daily_limit_note.color, daily_limit_note.visible = tp("limit.saved", lang), theme.SUCCESS, True
        refresh(force=True)
        page.update()

    def open_customer_record(e=None) -> None:
        platform, chat_id = state["platform"], state["chat_id"]
        if chat_id and on_open_customer is not None:
            on_open_customer(platform, chat_id)

    sort_control.on_select = on_sort_change
    open_customer_button.on_click = open_customer_record

    def _id_fact(label_key: str, value: str, key: str = "") -> ft.Control:
        return ft.Row(
            spacing=8,
            controls=[ft.Text(tp(label_key, lang) + ":", size=12, color=theme.text_secondary(page)),
                      ft.Text(value or "—", size=12.5, selectable=True, key=key or None)],
        )

    def identity_card(conv: Optional[ConversationSummary]) -> ft.Control:
        """کارتِ هویتِ مشتری: نام/یوزرنیم/شناسه/پلتفرم/اولین و آخرینِ دیدار/مجموعِ پیام‌ها/سفارش‌ها/زبان/
        بلاک و دست‌نیافتنی/برچسب‌ها. هرچه از CRM در دسترس باشد از همان جا؛ بقیه از خودِ گفتگو (بدونِ حدس)."""
        platform, chat_id = state["platform"], state["chat_id"]
        customer = None
        customers = getattr(manager, "customers", None)
        if customers is not None:
            try:
                customer = customers.get(platform, chat_id)
            except Exception:  # noqa: BLE001 — خرابیِ CRM هرگز نباید صفحه‌ی گفتگو را بخواباند
                customer = None
        is_blocked = bool(customer.blocked) if customer is not None else bool(conv and conv.blocked)
        unreachable = bool(customer.unreachable) if customer is not None else False
        name = customer.display_name if customer is not None and customer.display_name else (conv.display_name if conv and conv.display_name else chat_id)
        messages = conv.msg_count if conv else 0
        rows = [
            ft.Text(tp("id.title", lang), size=13.5, weight=ft.FontWeight.W_700),
            *([] if customer is not None else [ft.Text(tp("id.none", lang), size=11.5, color=theme.text_secondary(page), italic=True)]),
            _id_fact("id.name", name),
            _id_fact("id.username", f"@{customer.username}" if customer and customer.username else "—"),
            _id_fact("id.id", chat_id),
            _id_fact("id.platform", platform_label(platform)),
            _id_fact("id.first", _format_ts(customer.first_seen_ts) if customer else "—"),
            _id_fact("id.last", _format_ts(customer.last_seen_ts) if customer else "—"),
            _id_fact("id.messages", str(messages)),
            _id_fact("id.orders", str(customer.orders_count) if customer else "—"),
            _id_fact("id.language", (customer.language_code if customer else "") or "—"),
            _id_fact("id.tags", ", ".join(customer.tags) if customer and customer.tags else "—"),
            _id_fact("id.blocked", tp("id.yes" if is_blocked else "id.no", lang)),
            _id_fact("id.unreachable", tp("id.yes" if unreachable else "id.no", lang)),
        ]
        return ft.Container(
            key="identity_card",
            padding=12,
            border_radius=10,
            border=ft.Border.all(1, theme.border_color(page)),
            bgcolor=theme.card_bgcolor(page),
            content=ft.Column(spacing=3, controls=rows),
        )

    def management_row(conv: Optional[ConversationSummary]) -> ft.Control:
        """ردیفِ مدیریتِ شخصی‌سازی: سقفِ روزانه‌ی AI + ذخیره + پرش به پرونده‌ی مشتری.
        (بلاک/رفعِ بلاک و حافظه در همان هدرِ همیشگی با key ثابتِ ``block_button``/``memory_switch`` هستند.)"""
        return ft.Container(
            key="management_row",
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            border_radius=10,
            border=ft.Border.all(1, theme.border_color(page)),
            content=ft.Row(
                wrap=True, spacing=12, run_spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    daily_limit_field,
                    ft.OutlinedButton(key="daily_limit_save", content=tp("limit.save", lang), icon=ft.Icons.SAVE_ROUNDED, on_click=on_save_limit),
                    open_customer_button,
                    daily_limit_note,
                ],
            ),
        )

    def render_detail() -> None:
        platform, chat_id = state["platform"], state["chat_id"]
        if not chat_id:
            detail_area.controls = [
                ft.Container(
                    expand=True,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Text(t("chats.select_hint", lang), size=14, color=theme.text_secondary(page)),
                )
            ]
            return

        convs = {c.chat_id: c for c in manager.store.list_conversations(platform=platform)}
        conv = convs.get(chat_id)
        display_name = conv.display_name if conv else chat_id
        blocked = conv.blocked if conv else False
        memory_on = conv.memory_enabled if conv else True

        messages = manager.store.get_messages(platform, chat_id)
        history_view = ft.ListView(
            expand=True,
            spacing=10,
            auto_scroll=True,
            controls=(
                [message_bubble(m.role, m.content, m.created_at) for m in messages]
                if messages
                else [ft.Text(t("chats.no_messages", lang), size=13, color=theme.text_secondary(page))]
            ),
        )

        header = ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                ft.Row(
                    spacing=8,
                    controls=[
                        ft.Icon(_PLATFORM_ICON.get(platform, ft.Icons.CHAT_ROUNDED), color=theme.PRIMARY, size=20),
                        ft.Text(display_name, size=16, weight=ft.FontWeight.W_700),
                        ft.Text(f"· {platform_label(platform)}", size=12, color=theme.text_secondary(page)),
                        (
                            ft.Container(
                                padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                                border_radius=20,
                                bgcolor=f"{theme.DANGER}22",
                                content=ft.Text(t("chats.blocked_badge", lang), size=11, color=theme.DANGER),
                            )
                            if blocked
                            else ft.Container()
                        ),
                    ],
                ),
                ft.Row(
                    spacing=16,
                    controls=[
                        ft.Row(
                            spacing=6,
                            controls=[
                                ft.Switch(
                                    key="memory_switch",
                                    value=memory_on,
                                    active_color=theme.SUCCESS,
                                    on_change=lambda e, pl=platform, cid=chat_id: on_memory_change(pl, cid, e.control.value),
                                ),
                                ft.Text(t("chats.memory", lang), size=12),
                            ],
                        ),
                        ft.OutlinedButton(
                            key="clear_history_button",
                            content=(
                                t("chats.clear_history_confirm", lang)
                                if clear_armed.get("key") == (platform, chat_id)
                                else t("chats.clear_history", lang)
                            ),
                            icon=ft.Icons.DELETE_OUTLINE_ROUNDED,
                            style=(
                                ft.ButtonStyle(color=theme.DANGER)
                                if clear_armed.get("key") == (platform, chat_id)
                                else None
                            ),
                            on_click=lambda e, pl=platform, cid=chat_id: on_clear_history(pl, cid),
                        ),
                        ft.OutlinedButton(
                            key="block_button",
                            content=t("chats.unblock", lang) if blocked else t("chats.block", lang),
                            icon=ft.Icons.LOCK_OPEN_ROUNDED if blocked else ft.Icons.BLOCK_ROUNDED,
                            on_click=lambda e, pl=platform, cid=chat_id, b=blocked: on_block_toggle(pl, cid, b),
                        ),
                    ],
                ),
            ],
        )

        # اگر برای این مکالمه هنوز فیلدِ سقف همگام نشده (مثلاً انتخابِ خودکارِ اولیه)، همین‌جا پر می‌شه.
        if state["limit_for"] != (platform, chat_id):
            sync_limit_field(platform, chat_id)

        detail_area.controls = [
            header,
            identity_card(conv),
            management_row(conv),
            ft.Text(t("chats.memory_help", lang), size=11, color=theme.text_secondary(page)),
            (
                ft.Container(
                    padding=10,
                    border_radius=8,
                    bgcolor=f"{theme.DANGER}14",
                    content=ft.Text(t("chats.blocked_note", lang), size=12, color=theme.DANGER),
                )
                if blocked
                else ft.Container(height=0)
            ),
            ft.Container(expand=True, content=history_view),
        ]

    # ----------------------------------------------------------- تازه‌سازی
    def snapshot():
        convs = manager.store.list_conversations()
        platform, chat_id = state["platform"], state["chat_id"]
        detail = (
            tuple((m.role, m.content, m.created_at) for m in manager.store.get_messages(platform, chat_id))
            if chat_id
            else ()
        )
        conv_now = next((c for c in convs if (c.platform, c.chat_id) == (platform, chat_id)), None)
        list_snap = tuple((c.platform, c.chat_id, c.display_name, c.last_message_preview, c.blocked, c.msg_count, c.daily_ai_limit) for c in convs)
        detail_snap = (detail, conv_now.memory_enabled if conv_now else None, conv_now.blocked if conv_now else None)
        return convs, list_snap, detail_snap

    def refresh(force: bool = False) -> None:
        convs, list_snap, detail_snap = snapshot()
        if not state["initialized"] and convs:
            state["platform"], state["chat_id"] = convs[0].platform, convs[0].chat_id
            state["initialized"] = True
            _, list_snap, detail_snap = snapshot()
        if force or list_snap != last["list_snap"]:
            render_list(convs)
            last["list_snap"] = list_snap
        if force or detail_snap != last["detail_snap"]:
            render_detail()
            last["detail_snap"] = detail_snap
        bots_off_banner.visible = not manager.is_running()
        refresh_composer()

    def tick() -> None:
        refresh()
        page.update()

    refresh(force=True)
    refresher = LiveRefresher(page, tick, interval=2.0)
    refresher.start()

    bots_off_banner.content = ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        controls=[
            ft.Row(
                spacing=8,
                controls=[
                    ft.Icon(ft.Icons.INFO_OUTLINE_ROUNDED, color=theme.ACCENT_DARK, size=18),
                    ft.Text(t("chats.bots_off", lang), size=13, color=theme.ACCENT_DARK),
                ],
            ),
            ft.TextButton(t("chats.open_bots", lang), on_click=lambda e: on_open_bots()),
        ],
    )
    bots_off_banner.padding = ft.Padding.symmetric(horizontal=16, vertical=10)
    bots_off_banner.border_radius = 10
    bots_off_banner.bgcolor = f"{theme.ACCENT}14"
    bots_off_banner.visible = not manager.is_running()

    body = ft.Row(
        expand=True,
        spacing=16,
        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        controls=[
            ft.Container(
                width=300,
                content=ft.Column(
                    spacing=8,
                    controls=[ft.Row(controls=[sort_control], wrap=True), card(page, list_view, padding=8)],
                ),
            ),
            ft.Column(
                expand=True,
                spacing=12,
                controls=[ft.Container(expand=True, content=card(page, detail_area)), personal_box],
            ),
        ],
    )

    # قابِ این صفحه دو-ستونه است: ستون‌ها ارتفاعِ کاملِ پنجره را می‌گیرن و اسکرول داخلِ
    # خودِ لیست‌ها است؛ به‌همین‌خاطر screen_frame (که ستونِ اسکرول‌پذیر دارد) اینجا کاربرد ندارد —
    # ولی حاشیه‌ها همان ۲۸/۲۰ و فاصله‌ها از توکن‌هایِ تم است.
    control = ft.Container(
        expand=True,
        padding=ft.Padding.symmetric(horizontal=28, vertical=20),
        content=ft.Column(
            expand=True,
            spacing=theme.SPACE_MD,
            controls=[
                page_header(page, ft.Icons.FORUM_OUTLINED, t("chats.title", lang), t("chats.subtitle", lang)),
                bots_off_banner,
                export_row,
                body,
            ],
        ),
    )
    return control, refresher.stop
