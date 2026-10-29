"""«پروفایلِ ربات» (N17): متنِ بیوگرافیِ فروشنده + خطِ اعتبارِ قفل‌شده + وضعیتِ همگام‌سازی روی تلگرام و بله.

شفاف و بی‌خطر: خطِ اعتبار فقط‌خواندنی و همیشه دیده می‌شه؛ متنِ فعلیِ ربات بدونِ تأیید تغییر نمی‌کنه؛ بیشتر از ۱۲۰ کاراکتر
کوتاه نمی‌شه (خطا می‌دهد)؛ بله اگه تنظیمِ خودکار نداشته باشه «متنِ پیشنهادی» با دکمه‌ی کپی می‌ده.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import flet as ft

from app import theme
from app.core import bot_profile, paths
from app.core.bot_manager import BotManagerError
from app.screens import common

logger = logging.getLogger(__name__)

ICON_SOURCE = Path(__file__).resolve().parents[2] / "assets" / "icons" / "app-icon-512.png"

_S = {
    "title": ("پروفایلِ ربات (بیوگرافی)", "Bot profile (bio)"),
    "intro": (
        "این برنامه یک خطِ کوچکِ اعتبار («ساخته‌شده با کسب‌وکار هوشمند») به بیوگرافیِ ربات اضافه می‌کنه تا مشتری‌ها بدونن ربات با چه ابزاری ساخته شده. "
        "فقط همین خط، فقط در بیوگرافی؛ هیچ‌چیزِ دیگه‌ای در پیام‌ها، سفارش‌ها و پرداخت‌ها اضافه نمی‌شه. متنِ خودت رو می‌تونی کنارش بنویسی.",
        "This app adds one small credit line (“Made with Smart Business”) to the bot's bio so customers know what it was built with. "
        "Only that line, only in the bio; nothing is added to messages, orders or payments. You can write your own text next to it.",
    ),
    "text": ("متنِ بیوگرافیِ شما", "Your bio text"),
    "credit": ("خطِ اعتبار (قفل‌شده)", "Credit line (locked)"),
    "preview": ("پیش‌نمایشِ نهایی", "Final preview"),
    "save": ("ذخیره و اعمال", "Save & apply"),
    "saved": ("✅ ذخیره شد.", "✅ Saved."),
    "saved_later": ("✅ ذخیره شد؛ بعد از روشن‌شدنِ ربات خودکار اعمال می‌شه.", "✅ Saved; it will be applied automatically once the bot is running."),
    "too_long": ("متنِ تو {over} کاراکتر بیشتر از حدِ مجازه؛ کوتاهش کن (سقف {limit}).", "Your text is {over} characters over the limit; shorten it (max {limit})."),
    "refresh": ("به‌روزرسانیِ وضعیت", "Refresh status"),
    "st.telegram": ("تلگرام", "Telegram"),
    "st.bale": ("بله", "Bale"),
    "st.none": ("هنوز ربات وصل/روشن نشده", "The bot is not connected/running yet"),
    "st.ok": ("✅ روی ربات اعمال شده", "✅ Applied on the bot"),
    "st.updated": ("✅ همین الان روی ربات اعمال شد", "✅ Just applied on the bot"),
    "st.needs_confirm": ("⏸ منتظرِ تأییدِ شما (پایین)", "⏸ Waiting for your confirmation (below)"),
    "st.too_long": ("⚠️ بیوگرافی {over} کاراکتر بلنده؛ کوتاهش کن", "⚠️ The bio is {over} characters too long; shorten it"),
    "st.unsupported": ("ℹ️ بله تنظیمِ خودکارِ بیوگرافی رو پشتیبانی نمی‌کنه؛ متنِ پیشنهادی پایینه", "ℹ️ Bale doesn't support automatic bios; a suggested text is below"),
    "st.retry": ("⏳ الان نشد؛ خودکار دوباره تلاش می‌شه", "⏳ Couldn't right now; it will retry automatically"),
    "confirm.title": ("بیوگرافیِ فعلیِ رباتت این‌ه:", "Your bot's current bio is:"),
    "confirm.body": ("با تأیید، خطِ اعتبار به انتهای همین متن اضافه می‌شه (متنِ خودت دست نمی‌خوره).", "If you confirm, the credit line is added to the end of this text (your text is untouched)."),
    "confirm.yes": ("تأیید و افزودنِ خطِ اعتبار", "Confirm and add the credit line"),
    "confirm.no": ("فعلاً نه", "Not now"),
    "bale.title": ("متنِ پیشنهادی برای بله (خودت در پنلِ ربات‌سازِ بله بگذار):", "Suggested text for Bale (paste it yourself in Bale's bot panel):"),
    "bale.copy": ("کپیِ متن", "Copy text"),
    "bale.copied": ("کپی شد", "Copied"),
    "bale.retry": ("امتحانِ دوباره‌ی تنظیمِ خودکار", "Retry automatic setup"),
    "icon.title": ("پیشنهاد: آیکنِ برنامه رو عکسِ پروفایلِ ربات بگذار", "Tip: use the app icon as the bot's profile picture"),
    "icon.save": ("ذخیره‌ی آیکن در پوشه‌ی داده", "Save the icon in the data folder"),
    "icon.saved": ("آیکن ذخیره شد: {path}", "Icon saved: {path}"),
    "icon.failed": ("ذخیره‌ی آیکن نشد.", "Couldn't save the icon."),
}


def S(key: str, lang: str, **kw) -> str:
    fa, en = _S[key]
    text = en if lang == "en" else fa
    return text.format(**kw) if kw else text


def _credit_lang(settings) -> str:
    return "en" if getattr(settings, "bot_language", "fa") == "en" else "fa"


def build(page: ft.Page, lang: str, settings, save_callback, manager=None) -> ft.Control:
    secondary = theme.text_secondary(page)
    clang = _credit_lang(settings)

    bio = ft.TextField(key="bio_text", label=S("text", lang), value=getattr(settings, "bot_bio_text", "") or "", border_radius=10, expand=True)
    counter = ft.Text(bot_profile.counter(bio.value, clang), key="bio_counter", size=11.5, color=secondary)
    credit = ft.Text(f"🔒 {bot_profile.credit(clang)}", key="bio_credit", size=12.5, color=secondary, selectable=True)
    preview = ft.Text("", key="bio_preview", size=13, weight=ft.FontWeight.W_600, selectable=True)
    note = ft.Text("", key="bio_note", size=12.5, visible=False)
    st_tg = ft.Text("", key="bio_status_telegram", size=12.5)
    st_bale = ft.Text("", key="bio_status_bale", size=12.5)

    confirm_existing = ft.Text("", key="bio_confirm_existing", size=13, selectable=True)
    confirm_yes = ft.Button(key="bio_confirm_yes", content=S("confirm.yes", lang))
    confirm_no = ft.TextButton(key="bio_confirm_no", content=S("confirm.no", lang))
    confirm_box = ft.Container(
        key="bio_confirm_box",
        visible=False,
        padding=12,
        border_radius=10,
        bgcolor=f"{theme.ACCENT}1A",
        content=ft.Column(spacing=8, controls=[ft.Text(S("confirm.title", lang), size=13, weight=ft.FontWeight.W_600), confirm_existing, ft.Text(S("confirm.body", lang), size=12, color=secondary), ft.Row(spacing=8, controls=[confirm_yes, confirm_no])]),
    )

    bale_text = ft.Text("", key="bio_bale_suggested", size=13, selectable=True)
    bale_copied = ft.Text(S("bale.copied", lang), key="bio_bale_copied", size=12, color=theme.SUCCESS, visible=False)
    bale_box = ft.Container(
        key="bio_bale_box",
        visible=False,
        content=ft.Column(
            spacing=6,
            controls=[
                ft.Text(S("bale.title", lang), size=12.5, color=secondary),
                bale_text,
                ft.Row(
                    spacing=8,
                    wrap=True,
                    controls=[
                        ft.OutlinedButton(key="bio_bale_copy", content=S("bale.copy", lang), icon=ft.Icons.CONTENT_COPY_ROUNDED),
                        ft.TextButton(key="bio_bale_retry", content=S("bale.retry", lang)),
                        bale_copied,
                    ],
                ),
            ],
        ),
    )

    def say(text: str, ok: bool = True) -> None:
        note.value, note.color, note.visible = text, (theme.SUCCESS if ok else theme.DANGER), bool(text)

    def current_text() -> str:
        return bot_profile.clean(bio.value)

    def update_preview() -> bool:
        text = current_text()
        counter.value = bot_profile.counter(text, clang)
        try:
            preview.value = bot_profile.compose(text, clang)
            preview.color = None
            return True
        except bot_profile.BioTooLong as exc:
            preview.value = S("too_long", lang, over=exc.over, limit=bot_profile.seller_limit(clang))
            preview.color = theme.DANGER
            return False

    def reports() -> dict:
        try:
            return dict(manager.profile_reports()) if manager is not None else {}
        except Exception:  # noqa: BLE001
            return {}

    def describe(report) -> str:
        if report is None:
            return S("st.none", lang)
        if report.status == bot_profile.STATUS_OK:
            return S("st.ok", lang)
        if report.status == bot_profile.STATUS_UPDATED:
            return S("st.updated", lang)
        if report.status == bot_profile.STATUS_NEEDS_CONFIRM:
            return S("st.needs_confirm", lang)
        if report.status == bot_profile.STATUS_TOO_LONG:
            return S("st.too_long", lang, over=report.over)
        if report.status == bot_profile.STATUS_UNSUPPORTED:
            return S("st.unsupported", lang)
        return S("st.retry", lang)

    def refresh_status() -> None:
        found = reports()
        st_tg.value = f"{S('st.telegram', lang)}: {describe(found.get('telegram'))}"
        st_bale.value = f"{S('st.bale', lang)}: {describe(found.get('bale'))}"
        waiting = [r for r in found.values() if r.status == bot_profile.STATUS_NEEDS_CONFIRM]
        confirm_box.visible = bool(waiting) and not getattr(settings, "bot_bio_confirmed", False)
        if waiting:
            existing = waiting[0].existing
            confirm_existing.value = "\n".join(f"«{text}»" + (f" ({code})" if code else "") for code, text in existing.items())
        unsupported = getattr(settings, "bale_bio_supported", None) is False or (found.get("bale") is not None and found["bale"].status == bot_profile.STATUS_UNSUPPORTED)
        bale_box.visible = bool(unsupported)
        bale_text.value = bot_profile.suggested_bio(current_text(), clang)

    def run_sync(done_text: str = "") -> None:
        def work() -> None:
            try:
                manager.sync_profiles_now()
                say(done_text or S("saved", lang), True)
            except BotManagerError:
                say(S("saved_later", lang), True)
            except Exception:  # noqa: BLE001
                logger.warning("همگام‌سازیِ بیوگرافی از UI ناموفق بود", exc_info=True)
                say(S("saved_later", lang), True)
            refresh_status()
            page.update()

        if manager is None:
            say(S("saved_later", lang), True)
            refresh_status()
            page.update()
            return
        page.run_thread(work)

    def on_change(e=None) -> None:
        update_preview()
        bale_text.value = bot_profile.suggested_bio(current_text(), clang)
        page.update()

    def on_save(e=None) -> None:
        if not update_preview():
            say(preview.value, False)
            page.update()
            return
        settings.bot_bio_text = current_text()
        save_callback()
        run_sync()

    def on_confirm(e=None) -> None:
        settings.bot_bio_confirmed = True
        save_callback()
        confirm_box.visible = False
        run_sync()

    def on_decline(e=None) -> None:
        confirm_box.visible = False
        page.update()

    def on_copy(e=None) -> None:
        if common.copy_text(page, bale_text.value or ""):
            bale_copied.visible = True
            page.update()

    def on_retry(e=None) -> None:
        if manager is not None:
            manager.reset_bale_bio_probe()
        else:
            settings.bale_bio_supported = None
            save_callback()
        run_sync()

    bio.on_change = on_change
    confirm_yes.on_click, confirm_no.on_click = on_confirm, on_decline
    bale_box.content.controls[2].controls[0].on_click = on_copy
    bale_box.content.controls[2].controls[1].on_click = on_retry

    icon_note = ft.Text("", key="bio_icon_note", size=12, visible=False)

    def on_save_icon(e=None) -> None:
        try:
            target = paths.get_app_data_dir() / "exports"
            target.mkdir(parents=True, exist_ok=True)
            destination = target / "smart-business-icon.png"
            shutil.copyfile(ICON_SOURCE, destination)
            icon_note.value, icon_note.color = S("icon.saved", lang, path=str(destination)), theme.SUCCESS
            common.open_folder(target)
        except OSError:
            icon_note.value, icon_note.color = S("icon.failed", lang), theme.DANGER
        icon_note.visible = True
        page.update()

    update_preview()
    refresh_status()
    controls = [
        ft.Text(S("intro", lang), key="bio_intro", size=12.5, color=secondary),
        ft.Row(spacing=10, controls=[bio]),
        counter,
        ft.Text(S("credit", lang), size=12, color=secondary),
        credit,
        ft.Text(S("preview", lang), size=12, color=secondary),
        preview,
        confirm_box,
        ft.Row(spacing=8, wrap=True, controls=[ft.Button(key="bio_save", content=S("save", lang), icon=ft.Icons.CHECK_ROUNDED, on_click=on_save), ft.TextButton(key="bio_refresh", content=S("refresh", lang), on_click=lambda e: (refresh_status(), page.update()))]),
        note,
        st_tg,
        st_bale,
        bale_box,
        ft.Row(
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Image(src=common.APP_ICON_ASSET, width=44, height=44, fit=ft.BoxFit.CONTAIN),
                ft.Column(spacing=2, expand=True, controls=[ft.Text(S("icon.title", lang), size=12.5), ft.TextButton(key="bio_icon_save", content=S("icon.save", lang), on_click=on_save_icon)]),
            ],
        ),
        icon_note,
    ]
    return common.card(
        page,
        ft.ExpansionTile(
            key="sec_profile",
            expanded=False,
            title=ft.Text(S("title", lang), size=14.5, weight=ft.FontWeight.W_600),
            controls=[ft.Container(padding=ft.Padding.only(left=6, right=6, bottom=12), content=ft.Column(spacing=10, controls=controls))],
        ),
        padding=6,
    )
