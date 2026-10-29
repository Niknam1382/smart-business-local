"""صفحه‌ی «پیامِ همگانی» (N7): نوشتنِ پیام، انتخابِ مخاطب با شمارشِ زنده، پیش‌نمایش، ارسالِ آزمایشی به خودت، شروعِ دومرحله‌ای،
و تاریخچه‌ی ارسال‌ها با پیشرفتِ زنده و توقف/ادامه/لغو.

بی‌خطر به‌صورتِ پیش‌فرض: فقط به مشتریانی که خودشان پیام داده‌اند و بلاک/لغو (/stop) نکرده‌اند؛ پانویسِ «برای توقف /stop» روشن؛ سقفِ روزانه؛
نرخِ امنِ ارسال؛ ارسالِ بعدی تا تمامِ ارسالِ قبلی ممکن نیست. ارسالِ واقعی را موتورِ داخلِ لوپِ ربات‌ها انجام می‌دهد (این صفحه فقط صف را می‌سازد).
"""

from __future__ import annotations

import logging
from datetime import datetime

import flet as ft

from app import theme
from app.core import broadcast as bc
from app.core.bot_manager import BotManagerError
from app.screens import common
from app.screens.live import LiveRefresher

logger = logging.getLogger(__name__)

_S = {
    "title": ("پیامِ همگانی", "Broadcast"),
    "subtitle": ("یک پیام برای همه‌ی مشتریان (یا بخشی از آن‌ها) — با رعایتِ محدودیتِ تلگرام/بله و حریمِ مشتری.", "One message to all your customers (or a segment) — respecting Telegram/Bale limits and customer privacy."),
    "bots_off": ("ربات‌ها خاموشن؛ ارسال‌های در جریان تا روشن‌شدنِ ربات‌ها منتظر می‌مونن.", "The bots are off; running broadcasts wait until you turn them on."),
    "compose": ("پیامِ تازه", "New message"),
    "text": ("متنِ پیام", "Message text"),
    "text_hint": ("مثلاً: تخفیفِ ویژه‌ی آخرِ هفته! فقط تا جمعه…", "e.g. Weekend special! Only until Friday…"),
    "photo_add": ("افزودنِ عکس", "Add photo"),
    "photo_change": ("تعویضِ عکس", "Change photo"),
    "photo_remove": ("حذفِ عکس", "Remove photo"),
    "photo_none": ("بدونِ عکس", "No photo"),
    "photo_caption": ("با عکس، متن حداکثر ۱۰۰۰ نویسه می‌شه.", "With a photo the text is limited to 1000 characters."),
    "btn_label": ("عنوانِ دکمه (اختیاری)", "Button title (optional)"),
    "btn_url": ("لینکِ دکمه", "Button link"),
    "footer": ("پانویسِ «برای توقف /stop» (پیشنهادی)", "“Send /stop to unsubscribe” footer (recommended)"),
    "audience": ("مخاطب", "Audience"),
    "platform": ("پیام‌رسان", "Messenger"),
    "platform.all": ("هر دو", "Both"),
    "platform.telegram": ("تلگرام", "Telegram"),
    "platform.bale": ("بله", "Bale"),
    "purchase": ("خرید", "Purchases"),
    "purchase.all": ("همه", "Everyone"),
    "purchase.buyers": ("فقط خریداران", "Buyers only"),
    "purchase.no_orders": ("هنوز خرید نکرده‌ها", "Never bought"),
    "activity": ("فعالیت", "Activity"),
    "activity.all": ("همه", "Everyone"),
    "activity.active_7d": ("فعال در ۷ روزِ اخیر", "Active in the last 7 days"),
    "activity.active_30d": ("فعال در ۳۰ روزِ اخیر", "Active in the last 30 days"),
    "activity.inactive_30d": ("غیرفعال بیش از ۳۰ روز", "Inactive for 30+ days"),
    "activity.new_7d": ("جدید (۷ روزِ اخیر)", "New (last 7 days)"),
    "language": ("زبان", "Language"),
    "language.all": ("همه", "All"),
    "language.fa": ("فارسی", "Persian"),
    "language.en": ("انگلیسی", "English"),
    "language.other": ("بقیه", "Other"),
    "tag": ("برچسب (اختیاری)", "Tag (optional)"),
    "who": ("گیرندگان: {n} نفر{detail}", "Recipients: {n}{detail}"),
    "who_none": ("با این فیلترها هیچ مشتریِ مجازی نیست.", "No eligible customers match these filters."),
    "who_note": ("فقط کسانی که پیام داده‌اند و بلاک/لغو نکرده‌اند.", "Only people who have messaged you and haven't been blocked or opted out."),
    "preview": ("پیش‌نمایش", "Preview"),
    "preview_empty": ("(متنِ پیام را بنویس تا اینجا ببینی)", "(type your message to preview it here)"),
    "test": ("ارسالِ آزمایشی به خودم", "Send a test to myself"),
    "start": ("شروعِ ارسال…", "Start sending…"),
    "confirm_text": ("این پیام برای {n} نفر فرستاده می‌شه و برگشت‌پذیر نیست (فقط می‌تونی متوقف/لغو کنی). مطمئنی؟", "This message goes to {n} people and cannot be recalled (you can only pause/cancel). Sure?"),
    "confirm_yes": ("بله، بفرست", "Yes, send"),
    "confirm_no": ("انصراف", "Cancel"),
    "started": ("✅ ارسالِ #{id} شروع شد. پیشرفتش را پایین می‌بینی.", "✅ Broadcast #{id} started. Follow its progress below."),
    "started_off": ("ارسال در صف است ولی ربات‌ها خاموشن؛ با روشن‌شدنشان شروع می‌شه.", "It's queued, but the bots are off; it starts when you turn them on."),
    "test_ok": ("✅ پیامِ آزمایشی برایت فرستاده شد ({where}).", "✅ Test message sent to you ({where})."),
    "test_fail": ("❌ {where}: {detail}", "❌ {where}: {detail}"),
    "test_failed": ("پیامِ آزمایشی فرستاده نشد؛ دوباره امتحان کن.", "The test message wasn't sent; try again."),
    "history": ("ارسال‌های قبلی", "Previous broadcasts"),
    "history_empty": ("هنوز پیامِ همگانی نفرستاده‌ای.", "You haven't sent a broadcast yet."),
    "status.running": ("در حال ارسال", "Sending"),
    "status.paused": ("متوقف", "Paused"),
    "status.done": ("تمام شد", "Done"),
    "status.cancelled": ("لغو شد", "Cancelled"),
    "counts": ("رسید {sent} · دسترس‌ناپذیر {unreachable} · ناموفق {failed} · کنار گذاشته {skipped} · مانده {pending}", "Delivered {sent} · Unreachable {unreachable} · Failed {failed} · Skipped {skipped} · Left {pending}"),
    "pause": ("توقف", "Pause"),
    "resume": ("ادامه", "Resume"),
    "cancel": ("لغو", "Cancel"),
    "cancel_sure": ("مطمئنی؟ دوباره بزن", "Sure? Press again"),
    "settings": ("تنظیماتِ ارسال", "Sending settings"),
    "cap": ("سقفِ تعدادِ ارسال در ۲۴ ساعت", "Max broadcasts per 24 hours"),
    "rate_tg": ("سرعتِ تلگرام (پیام در ثانیه)", "Telegram speed (messages/second)"),
    "rate_bale": ("سرعتِ بله (پیام در ثانیه)", "Bale speed (messages/second)"),
    "footer_default": ("پانویسِ /stop به‌صورتِ پیش‌فرض روشن باشه", "Footer on by default"),
    "settings_save": ("ذخیره", "Save"),
    "saved": ("ذخیره شد.", "Saved."),
    "range": ("«{label}» باید عددی بینِ {lo} و {hi} باشه.", "“{label}” must be a number between {lo} and {hi}."),
    "settings_note": ("سرعتِ پایین‌تر امن‌تره؛ اگه تلگرام/بله «کُند کن» گفت، موتور خودش صبر می‌کنه و آهسته‌تر می‌شه.", "Lower speed is safer; if Telegram/Bale says “slow down” the engine waits and slows itself."),
    "errors_title": ("دلیلِ خطاها:", "Error reasons:"),
}


def S(key: str, lang: str, **kw) -> str:
    fa, en = _S[key]
    text = en if lang == "en" else fa
    return text.format(**kw) if kw else text


def _fmt_time(ts: int) -> str:
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return ""


def build(page: ft.Page, lang: str, settings, save_callback, manager) -> tuple:
    secondary = theme.text_secondary(page)
    svc = manager.broadcasts
    ui = {"photo": "", "confirm": False, "armed": None}
    preview_lang = "en" if lang == "en" else "fa"

    # ----------------------------------------------------------------- کنترل‌ها ----
    notice = ft.Text("", key="bc_notice", size=12.5, visible=False, selectable=True)
    text_tf = ft.TextField(
        key="bc_text", label=S("text", lang), hint_text=S("text_hint", lang), multiline=True, min_lines=4, max_lines=10,
        max_length=bc.MAX_TEXT, border_radius=10,
    )
    photo_label = ft.Text(S("photo_none", lang), key="bc_photo_label", size=12.5, color=secondary)
    photo_buttons = ft.Row(spacing=8, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    btn_label_tf = ft.TextField(key="bc_button_label", label=S("btn_label", lang), border_radius=10, width=240, max_length=bc.MAX_BUTTON_LABEL)
    btn_url_tf = ft.TextField(key="bc_button_url", label=S("btn_url", lang), hint_text="https://…", border_radius=10, width=360)
    footer_sw = ft.Switch(key="bc_footer", label=S("footer", lang), value=bool(getattr(settings, "broadcast_footer_enabled", True)))

    def dd(key: str, label: str, group: str, values: list, width: int = 190) -> ft.Dropdown:
        return ft.Dropdown(
            key=key, label=label, border_radius=10, width=width, value=values[0],
            options=[ft.DropdownOption(key=v, text=S(f"{group}.{v}", lang)) for v in values],
        )

    platform_dd = dd("bc_platform", S("platform", lang), "platform", ["all", "telegram", "bale"], 150)
    purchase_dd = dd("bc_purchase", S("purchase", lang), "purchase", list(bc.PURCHASES), 190)
    activity_dd = dd("bc_activity", S("activity", lang), "activity", list(bc.ACTIVITIES), 230)
    language_dd = dd("bc_language", S("language", lang), "language", ["all", "fa", "en", "other"], 150)
    tag_tf = ft.TextField(key="bc_tag", label=S("tag", lang), border_radius=10, width=180, max_length=64)
    who_text = ft.Text("", key="bc_who", size=13.5, weight=ft.FontWeight.W_600)
    preview_box = ft.Container(key="bc_preview", padding=ft.Padding.symmetric(horizontal=14, vertical=10), border_radius=12, bgcolor=f"{theme.PRIMARY}14", width=420)
    confirm_text = ft.Text("", key="bc_confirm_text", size=13, color=theme.ACCENT_DARK)
    confirm_row = ft.Container(key="bc_confirm_row", visible=False, padding=12, border_radius=10, bgcolor=f"{theme.ACCENT}14")
    history_col = ft.Column(key="bc_history", spacing=10)
    bots_banner = ft.Container(key="bc_bots_off", visible=False, padding=ft.Padding.symmetric(horizontal=16, vertical=10), border_radius=10, bgcolor=f"{theme.ACCENT}14")

    def show(text: str, ok: bool = True) -> None:
        notice.value, notice.color, notice.visible = text, theme.SUCCESS if ok else theme.DANGER, bool(text)

    # --------------------------------------------------------------- مقدارِ فرم ----
    def audience() -> bc.Audience:
        pick = lambda v: "" if v in (None, "all") else v  # noqa: E731
        return bc.Audience(
            platform=pick(platform_dd.value), purchase=purchase_dd.value or bc.PURCHASE_ALL, activity=activity_dd.value or bc.ACTIVITY_ALL,
            tag=tag_tf.value or "", language=pick(language_dd.value),
        )

    def content() -> bc.Content:
        return bc.Content(text_tf.value or "", ui["photo"], btn_label_tf.value or "", btn_url_tf.value or "", bool(footer_sw.value))

    # ------------------------------------------------------------------ نمایش ----
    def refresh_who() -> None:
        try:
            s = svc.summary(audience())
        except bc.BroadcastError as exc:
            who_text.value, who_text.color = str(exc), theme.DANGER
            return
        if s.total == 0:
            who_text.value, who_text.color = S("who_none", lang), theme.DANGER
            return
        detail = " (" + " · ".join(f"{S('platform.' + p, lang)} {n}" for p, n in s.per_platform.items()) + ")" if len(s.per_platform) > 1 else ""
        who_text.value, who_text.color = S("who", lang, n=s.total, detail=detail), theme.PRIMARY

    def refresh_preview() -> None:
        c = content()
        text = (c.text or "").strip()
        lines = []
        if ui["photo"]:
            lines.append(ft.Row(spacing=6, controls=[ft.Icon(ft.Icons.IMAGE_OUTLINED, size=16, color=secondary), ft.Text(photo_label.value, size=11.5, color=secondary)]))
        lines.append(ft.Text(bc.compose(bc.Content(text, footer=c.footer), settings, preview_lang) if text else S("preview_empty", lang), size=13, selectable=True))
        if c.button_label:
            lines.append(ft.Container(padding=ft.Padding.symmetric(horizontal=12, vertical=6), border_radius=8, bgcolor=f"{theme.ACCENT}26", content=ft.Text(c.button_label, size=12.5, color=theme.ACCENT_DARK)))
        preview_box.content = ft.Column(spacing=6, tight=True, controls=lines)

    def refresh_photo_ui() -> None:
        photo_label.value = ui["photo"].replace("\\", "/").rsplit("/", 1)[-1] if ui["photo"] else S("photo_none", lang)
        photo_buttons.controls = [
            ft.OutlinedButton(key="bc_photo_pick", content=S("photo_change" if ui["photo"] else "photo_add", lang), icon=ft.Icons.IMAGE_OUTLINED, on_click=pick_photo),
            *([ft.TextButton(key="bc_photo_clear", content=S("photo_remove", lang), on_click=clear_photo)] if ui["photo"] else []),
            photo_label,
        ]

    def refresh_form(_e=None) -> None:
        ui["confirm"] = False
        confirm_row.visible = False
        refresh_who()
        refresh_preview()
        page.update()

    def refresh_banner() -> None:
        running = manager.is_running()
        bots_banner.visible = not running
        bots_banner.content = ft.Row(spacing=8, controls=[ft.Icon(ft.Icons.INFO_OUTLINE_ROUNDED, color=theme.ACCENT_DARK, size=18), ft.Text(S("bots_off", lang), size=13, color=theme.ACCENT_DARK)])

    # ------------------------------------------------------------------- عکس ----
    def set_photo(path: str) -> bool:
        try:
            stored = bc.store_photo(path)
        except bc.BroadcastError as exc:
            show(str(exc), False)
            page.update()
            return False
        bc.delete_photo(ui["photo"])  # عکسِ قبلیِ ارسال‌نشده
        ui["photo"] = stored
        show("", True)
        refresh_photo_ui()
        refresh_form()
        return True

    async def pick_photo(_e=None) -> None:
        picker = common.get_or_create_file_picker(page)
        try:
            result = await picker.pick_files(dialog_title=S("photo_add", lang), file_type=ft.FilePickerFileType.IMAGE, allow_multiple=False)
        except ft.FletUnsupportedPlatformException:
            result = None  # حالتِ وب/تست
        if result:
            set_photo(result[0].path)

    def clear_photo(_e=None) -> None:
        bc.delete_photo(ui["photo"])
        ui["photo"] = ""
        refresh_photo_ui()
        refresh_form()

    # ----------------------------------------------------------------- اقدام‌ها ----
    def on_test(_e=None) -> None:
        try:
            c = bc.validate_content(content(), settings)
        except bc.BroadcastError as exc:
            show(str(exc), False)
            page.update()
            return

        def work() -> None:
            try:
                results = manager.broadcast_test_sync(c)
            except (bc.BroadcastError, BotManagerError) as exc:
                show(str(exc), False)
            except Exception:  # noqa: BLE001 — UI هرگز نباید بشکنه
                logger.exception("ارسالِ آزمایشیِ پیامِ همگانی ناموفق بود")
                show(S("test_failed", lang), False)
            else:
                good = [S(f"platform.{p}", lang) for p, ok, _d in results if ok]
                bad = [S("test_fail", lang, where=S(f"platform.{p}", lang), detail=d) for p, ok, d in results if not ok]
                if bad:
                    show("\n".join(bad), False)
                else:
                    show(S("test_ok", lang, where="، ".join(good) if lang != "en" else ", ".join(good)), True)
            page.update()

        page.run_thread(work)

    def on_start(_e=None) -> None:
        try:
            bc.validate_content(content(), settings)
            s = svc.summary(audience())
            if s.total == 0:
                raise bc.BroadcastError(S("who_none", lang))
        except bc.BroadcastError as exc:
            show(str(exc), False)
            page.update()
            return
        ui["confirm"] = True
        confirm_text.value = S("confirm_text", lang, n=s.total)
        confirm_row.visible = True
        show("", True)
        page.update()

    def on_confirm(_e=None) -> None:
        try:
            bid = svc.start(content(), audience())
        except bc.BroadcastError as exc:
            ui["confirm"] = False
            confirm_row.visible = False
            show(str(exc), False)
            page.update()
            return
        ui.update(photo="", confirm=False)  # عکس حالا مالِ ارسال است (پاک نشود)
        confirm_row.visible = False
        text_tf.value = btn_label_tf.value = btn_url_tf.value = ""
        show(S("started", lang, id=bid) + ("" if manager.is_running() else " " + S("started_off", lang)), True)
        refresh_photo_ui()
        refresh_preview()
        refresh_who()
        render_history(force=True)
        page.update()

    def on_cancel_confirm(_e=None) -> None:
        ui["confirm"] = False
        confirm_row.visible = False
        page.update()

    # -------------------------------------------------------------- تاریخچه ----
    last = {"snap": None}

    def history_snapshot() -> tuple:
        rows = svc.history(10)
        return tuple((b.id, b.status, tuple(sorted(b.counts.items()))) for b in rows) + (manager.is_running(), ui["armed"]), rows

    def render_history(force: bool = False) -> None:
        snap, rows = history_snapshot()
        if not force and snap == last["snap"]:
            return
        last["snap"] = snap
        refresh_banner()
        if not rows:
            history_col.controls = [ft.Text(S("history_empty", lang), size=12.5, color=secondary)]
            return
        items = []
        for b in rows:
            c = {k: b.counts.get(k, 0) for k in bc.ROW_STATUSES}
            total = max(b.total, 1)
            color = {bc.STATUS_RUNNING: theme.PRIMARY, bc.STATUS_PAUSED: theme.ACCENT_DARK, bc.STATUS_DONE: theme.SUCCESS, bc.STATUS_CANCELLED: secondary}.get(b.status, secondary)
            controls = []
            if b.status == bc.STATUS_RUNNING:
                controls.append(ft.OutlinedButton(key=f"bc_pause_{b.id}", content=S("pause", lang), icon=ft.Icons.PAUSE_ROUNDED, on_click=lambda _e, bid=b.id: act(svc.pause, bid)))
            if b.status == bc.STATUS_PAUSED:
                controls.append(ft.FilledButton(key=f"bc_resume_{b.id}", content=S("resume", lang), icon=ft.Icons.PLAY_ARROW_ROUNDED, on_click=lambda _e, bid=b.id: act(svc.resume, bid)))
            if b.status in bc.ACTIVE_STATUSES:
                armed = ui["armed"] == b.id
                controls.append(ft.TextButton(key=f"bc_cancel_{b.id}", content=S("cancel_sure" if armed else "cancel", lang), icon=ft.Icons.CANCEL_OUTLINED, on_click=lambda _e, bid=b.id: cancel(bid)))
            errors = svc.store.errors(b.id, 3) if (c[bc.ROW_FAILED] or c[bc.ROW_UNREACHABLE]) else []
            snippet = " ".join(b.text.split())
            items.append(
                common.card(
                    page,
                    ft.Column(
                        key=f"bc_item_{b.id}",
                        spacing=6,
                        controls=[
                            ft.Row(spacing=10, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                                ft.Text(f"#{b.id}", size=13.5, weight=ft.FontWeight.W_700),
                                ft.Text(S(f"status.{b.status}", lang), size=12.5, weight=ft.FontWeight.W_600, color=color),
                                ft.Text(_fmt_time(b.started_ts), size=11.5, color=secondary),
                            ]),
                            ft.Text(snippet[:90] + ("…" if len(snippet) > 90 else ""), size=12.5, color=secondary),
                            ft.ProgressBar(value=b.processed / total, color=color, bgcolor=f"{secondary}22"),
                            ft.Text(S("counts", lang, **c), size=12),
                            *([ft.Text(S("errors_title", lang), size=11.5, color=secondary), *[ft.Text(f"• {n}× {text}", size=11.5, color=theme.DANGER, selectable=True) for text, n in errors]] if errors else []),
                            ft.Row(spacing=8, controls=controls) if controls else ft.Container(),
                        ],
                    ),
                    padding=14,
                )
            )
        history_col.controls = items

    def act(fn, bid: int) -> None:
        fn(bid)
        ui["armed"] = None
        render_history(force=True)
        page.update()

    def cancel(bid: int) -> None:
        if ui["armed"] == bid:  # تأییدِ دوکلیکیِ درجا (لغو برگشت‌ناپذیر است)
            act(svc.cancel, bid)
            return
        ui["armed"] = bid
        render_history(force=True)
        page.update()

    # --------------------------------------------------------------- تنظیمات ----
    cap_tf = ft.TextField(key="bc_cap", label=S("cap", lang), border_radius=10, width=300, value=str(svc.cap()))
    rate_tg_tf = ft.TextField(key="bc_rate_tg", label=S("rate_tg", lang), border_radius=10, width=300, value=str(int(getattr(settings, "broadcast_rate_telegram", 20))))
    rate_bale_tf = ft.TextField(key="bc_rate_bale", label=S("rate_bale", lang), border_radius=10, width=300, value=str(int(getattr(settings, "broadcast_rate_bale", 5))))
    footer_default_sw = ft.Switch(key="bc_footer_default", label=S("footer_default", lang), value=bool(getattr(settings, "broadcast_footer_enabled", True)))
    settings_note = ft.Text("", key="bc_settings_note", size=12.5, visible=False)

    def int_in(raw, rng, label) -> int:
        digits = str(raw or "").strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
        lo, hi = rng
        if not digits.isdigit() or not lo <= int(digits) <= hi:
            raise ValueError(S("range", lang, label=label, lo=lo, hi=hi))
        return int(digits)

    def save_settings(_e=None) -> None:
        try:
            cap = int_in(cap_tf.value, bc.DAILY_CAP_RANGE, S("cap", lang))
            rate_tg = int_in(rate_tg_tf.value, bc.RATE_LIMITS["telegram"], S("rate_tg", lang))
            rate_bale = int_in(rate_bale_tf.value, bc.RATE_LIMITS["bale"], S("rate_bale", lang))
        except ValueError as exc:
            settings_note.value, settings_note.color, settings_note.visible = str(exc), theme.DANGER, True
            page.update()
            return
        settings.broadcast_daily_cap, settings.broadcast_rate_telegram, settings.broadcast_rate_bale = cap, rate_tg, rate_bale
        settings.broadcast_footer_enabled = bool(footer_default_sw.value)
        save_callback()
        settings_note.value, settings_note.color, settings_note.visible = S("saved", lang), theme.SUCCESS, True
        page.update()

    settings_tile = common.card(
        page,
        ft.ExpansionTile(
            key="bc_settings",
            title=ft.Text(S("settings", lang), size=14.5, weight=ft.FontWeight.W_600),
            controls=[
                ft.Container(
                    padding=ft.Padding.only(left=6, right=6, bottom=12),
                    content=ft.Column(spacing=10, controls=[
                        ft.Text(S("settings_note", lang), size=12, color=secondary),
                        ft.Row(spacing=10, wrap=True, controls=[cap_tf, rate_tg_tf, rate_bale_tf]),
                        footer_default_sw,
                        ft.FilledButton(key="bc_settings_save", content=S("settings_save", lang), on_click=save_settings),
                        settings_note,
                    ]),
                )
            ],
        ),
        padding=6,
    )

    # ---------------------------------------------------------------- اتصال‌ها ----
    for control in (text_tf, btn_label_tf, btn_url_tf, tag_tf):
        control.on_change = refresh_form
    footer_sw.on_change = refresh_form
    for control in (platform_dd, purchase_dd, activity_dd, language_dd):
        control.on_select = refresh_form

    confirm_row.content = ft.Column(spacing=8, controls=[
        confirm_text,
        ft.Row(spacing=8, controls=[
            ft.FilledButton(key="bc_confirm", content=S("confirm_yes", lang), icon=ft.Icons.SEND_ROUNDED, on_click=on_confirm),
            ft.TextButton(key="bc_confirm_no", content=S("confirm_no", lang), on_click=on_cancel_confirm),
        ]),
    ])

    compose_card = common.card(
        page,
        ft.Column(spacing=12, controls=[
            ft.Text(S("compose", lang), size=15, weight=ft.FontWeight.W_700),
            text_tf,
            photo_buttons,
            ft.Text(S("photo_caption", lang), size=11.5, color=secondary),
            ft.Row(spacing=10, wrap=True, controls=[btn_label_tf, btn_url_tf]),
            footer_sw,
            ft.Text(S("audience", lang), size=14, weight=ft.FontWeight.W_700),
            ft.Row(spacing=10, wrap=True, controls=[platform_dd, purchase_dd, activity_dd, language_dd, tag_tf]),
            who_text,
            ft.Text(S("who_note", lang), size=11.5, color=secondary),
            ft.Text(S("preview", lang), size=13.5, weight=ft.FontWeight.W_600),
            preview_box,
            ft.Row(spacing=10, wrap=True, controls=[
                ft.OutlinedButton(key="bc_test", content=S("test", lang), icon=ft.Icons.SCIENCE_OUTLINED, on_click=on_test),
                ft.FilledButton(key="bc_start", content=S("start", lang), icon=ft.Icons.CAMPAIGN_ROUNDED, on_click=on_start),
            ]),
            confirm_row,
            notice,
        ]),
    )

    def tick() -> None:
        render_history()
        page.update()

    refresh_photo_ui()
    refresh_who()
    refresh_preview()
    render_history(force=True)
    refresher = LiveRefresher(page, tick, interval=2.0)
    refresher.start()

    def cleanup() -> None:
        refresher.stop()
        bc.delete_photo(ui["photo"])  # عکسِ انتخاب‌شده‌ای که هیچ‌وقت ارسال نشد

    control = ft.Container(
        expand=True,
        padding=ft.Padding.symmetric(horizontal=32, vertical=24),
        content=ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=14,
            controls=[
                common.page_header(page, ft.Icons.CAMPAIGN_ROUNDED, S("title", lang), S("subtitle", lang)),
                bots_banner,
                compose_card,
                ft.Text(S("history", lang), size=15, weight=ft.FontWeight.W_700),
                history_col,
                settings_tile,
            ],
        ),
    )
    return control, cleanup
