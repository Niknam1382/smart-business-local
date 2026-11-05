"""کارت «تنظیمات پرداخت و سفارش‌گیری» (فقط حالت فروشگاه) — بالای صفحه‌ی «سفارش‌ها».

نسخه‌ی ۱.۰.۰ دو روشِ پرداخت دارد، هر دو کاملاً مالِ خودِ صاحب فروشگاه (پولی از اپ رد نمی‌شه):

* **کارت‌به‌کارت (دستی)**: شماره کارت و نام صاحب کارت مستقیم به مشتری نشون داده می‌شه
  (راز نیستن، پس رمزنگاری نمی‌شن). مشتری «پرداخت کردم» می‌زند و رسید (متن یا عکس)
  می‌فرستد. برنامه مبلغِ رسید را با سفارش مقایسه می‌کند و به مالک هشدار می‌دهد، ولی
  **تأیید همیشه دستیِ خودِ توست** — پول در حسابِ خودت است و هیچ درگاهی نیست که از آن
  استعلام بگیری.
* **بله‌پی**: درگاهِ پرداختِ بله. دو اعتبارنامه لازم است — توکنِ **رباتِ پرداختِ بله**
  (از @balebotfather؛ این ربات فقط فاکتور می‌فرستد و هیچ چتی را پاسخ نمی‌دهد) و
  **توکنِ کیف‌پول/درگاه** (provider token از بله). هر دو مثلِ کلیدِ API رمزنگاری می‌شن.
  مسیرِ پیش‌فرض «لینکِ مستقیم» است (createInvoiceLink — مشتری تلگرامی با یک کلیک
  پرداخت می‌کند)؛ اگر بله لینک ندهد یا «دیپ‌لینک» را انتخاب کنی، لینکِ رباتِ پرداخت
  (ble.ir/<bot>?start=pay_…) به مشتری داده می‌شه.

بله دیگر پیام‌رسانِ ربات نیست؛ برای همین توکنِ آن **این‌جا** وارد می‌شه، نه در صفحه‌ی
«ربات‌ها».

بخش «رزرو و تأییدِ سفارش»: مدتِ رزروِ موجودی و تأییدِ خودکارِ پرداختِ *درگاهی*.
دکمه‌های «تست اتصال» یک تماسِ آزمایشیِ واقعی می‌زنن و پیامِ دقیقِ خطا را نشون می‌دن.

همه‌ی مقدارها زنده خونده می‌شن (همون شیء settings). تنها نکته: رباتِ پرداختِ بله با
روشن‌شدنِ ربات‌ها بالا می‌آید — اگر توکن‌ها را بعد از روشن‌شدن دادی، یک بار از صفحه‌ی
«ربات‌ها» ری‌استارت لازم است.
"""

from __future__ import annotations

import flet as ft

from app import theme
from app.core.bale_pay import is_test_provider_token
from app.core.orders import METHOD_BALE_PAY, METHOD_CARD_TO_CARD
from app.core.payments import describe_provider_token, normalize_provider_token
from app.i18n import t
from app.screens import shipping_card
from app.screens.common import card, section_header

MIN_RESERVE, MAX_RESERVE = 1, 240

_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_SEPARATORS = " -_\u200c\u200f\u200e:"


def normalize_card_number(raw: str, error_message: str = "") -> str:
    """شماره کارت (ارقام فارسی/عربی، با فاصله یا خط‌تیره) → ``6219-8610-1234-5678``.

    خالی مجاز است (یعنی کارت‌به‌کارت خاموش). هر چیزِ غیرِ ۱۶ رقم ⇒ ``ValueErrorِ`` فارسی،
    تا ورودیِ نصفه روی دیسک نره و لینکِ پرداختِ مشتری مبلغِ غلط نگیره."""
    text = (raw or "").translate(_DIGIT_MAP)
    stripped = "".join(ch for ch in text if ch not in _SEPARATORS)
    if not stripped.strip():
        return ""
    if not (stripped.isdigit() and len(stripped) == 16):
        raise ValueError(error_message or t("pay.card.number_invalid", "fa"))
    return "-".join(stripped[i : i + 4] for i in range(0, 16, 4))


def build(page: ft.Page, lang: str, settings, save_callback, manager=None) -> ft.Control:
    ui = {"card_error": "", "pay_error": "", "reserve_error": ""}

    # ------------------------------------------------------------ کنترل‌ها
    card_number = ft.TextField(
        key="card_number", label=t("pay.card.number_label", lang), hint_text="6219-8610-0000-0000",
        value=settings.card_to_card_number, prefix_icon=ft.Icons.CREDIT_CARD_ROUNDED,
        text_align=ft.TextAlign.LEFT, border_radius=10,
    )
    card_holder = ft.TextField(
        key="card_holder", label=t("pay.card.holder_label", lang), value=settings.card_to_card_holder_name,
        prefix_icon=ft.Icons.PERSON_OUTLINE_ROUNDED, border_radius=10,
    )
    card_error = ft.Text("", key="card_error", size=12, color=theme.DANGER, visible=False)
    card_manual_note = ft.Text(t("pay.card.manual_note", lang), size=12, color=theme.ACCENT_DARK)
    diag_card_text = ft.Text("", key="diag_card_result", size=12, visible=False)

    # ---------------------------------------------------- رسیدِ کارت‌به‌کارت
    receipt_check = ft.Switch(
        key="receipt_check_enabled", label=t("pay.receipt.check", lang),
        value=bool(getattr(settings, "receipt_check_enabled", True)), active_color=theme.SUCCESS,
    )
    receipt_amount_check = ft.Switch(
        key="receipt_amount_check", label=t("pay.receipt.amount_check", lang),
        value=bool(getattr(settings, "receipt_amount_check", True)), active_color=theme.SUCCESS,
    )
    alert_claim = ft.Switch(
        key="alert_on_payment_claim", label=t("pay.receipt.alert", lang),
        value=bool(getattr(settings, "alert_on_payment_claim", True)), active_color=theme.SUCCESS,
    )
    receipt_help = ft.Text(t("pay.receipt.help", lang), size=12, color=theme.text_secondary(page))
    receipt_manual = ft.Text(
        t("pay.receipt.always_manual", lang), size=12.5, weight=ft.FontWeight.W_600, color=theme.ACCENT_DARK
    )

    # ------------------------------------------------------------------ بله‌پی
    bale_switch = ft.Switch(
        key="bale_pay_enabled", label=t("pay.bale.enable", lang), value=bool(settings.bale_pay_enabled),
        active_color=theme.SUCCESS,
    )
    bale_bot_token = ft.TextField(
        key="ps_bale_bot_token", label=t("pay.bale.bot_label", lang), hint_text=t("pay.bale.bot_hint", lang),
        value=settings.get_bale_pay_bot_token(), password=True, can_reveal_password=True,
        prefix_icon=ft.Icons.SMART_TOY_ROUNDED, text_align=ft.TextAlign.LEFT, border_radius=10,
    )
    bale_bot_help = ft.Text(t("pay.bale.bot_help", lang), size=12, color=theme.text_secondary(page))
    bale_provider_token = ft.TextField(
        key="bale_pay_token", label=t("pay.bale.provider_label", lang), hint_text=t("pay.bale.provider_hint", lang),
        value=settings.get_bale_pay_provider_token(), password=True, can_reveal_password=True,
        prefix_icon=ft.Icons.VPN_KEY_ROUNDED, text_align=ft.TextAlign.LEFT, border_radius=10,
    )
    bale_provider_help = ft.Text(t("pay.bale.provider_help", lang), size=12, color=theme.text_secondary(page))
    bale_token_kind = ft.Text("", key="ps_bale_token_kind", size=12, color=theme.text_secondary(page))
    bale_test_warning = ft.Text(
        "", key="ps_bale_test_warning", size=12.5, weight=ft.FontWeight.W_600, color=theme.DANGER, visible=False
    )
    link_mode = ft.SegmentedButton(
        key="ps_link_mode",
        allow_multiple_selection=False,
        allow_empty_selection=False,
        selected=[settings.bale_pay_link_mode if settings.bale_pay_link_mode in ("auto", "deeplink") else "auto"],
        segments=[
            ft.Segment(value="auto", label=ft.Text(t("pay.bale.mode_auto", lang)), icon=ft.Icons.LINK_ROUNDED),
            ft.Segment(value="deeplink", label=ft.Text(t("pay.bale.mode_deeplink", lang)), icon=ft.Icons.SMART_TOY_ROUNDED),
        ],
    )
    link_mode_help = ft.Text(t("pay.bale.mode_help", lang), size=12, color=theme.text_secondary(page))
    pay_error = ft.Text("", key="pay_error", size=12, color=theme.DANGER, visible=False)
    bale_note = ft.Text("", key="bale_note", size=12)
    diag_bale_text = ft.Text("", key="diag_bale_result", size=12, visible=False)

    # ------------------------------------------------------- رزرو و تأییدِ سفارش
    reserve = ft.TextField(
        key="reservation_minutes", label=t("pay.smart.reserve_label", lang), value=str(settings.reservation_minutes),
        prefix_icon=ft.Icons.TIMER_OUTLINED, keyboard_type=ft.KeyboardType.NUMBER,
        text_align=ft.TextAlign.LEFT, border_radius=10,
    )
    reserve_error = ft.Text("", key="reserve_error", size=12, color=theme.DANGER, visible=False)
    auto_confirm = ft.Switch(
        key="auto_confirm_gateway_payments", label=t("pay.smart.auto_confirm", lang),
        value=bool(settings.auto_confirm_gateway_payments), active_color=theme.SUCCESS,
    )

    summary = ft.Text("", key="pay_summary", size=12.5, weight=ft.FontWeight.W_500)
    last_errors_text = ft.Text("", key="last_errors", size=12, color=theme.DANGER, visible=False)

    # ------------------------------------------------------------- وضعیت/متن‌ها
    def bale_running() -> bool:
        """رباتِ پرداختِ بله فقط با روشن بودنِ ربات‌ها بالا می‌آید."""
        return bool(manager is not None and manager.is_running())

    def bale_tokens_present() -> bool:
        """هر دو اعتبارنامه (رباتِ پرداخت + کیف‌پول) — خودِ ``bale_pay_configured()`` سوییچ را
        هم می‌سنجد، پس برای «آیا اجازه بدهم روشن شود» به آن نمی‌شود تکیه کرد."""
        return bool(settings.get_bale_pay_bot_token() and settings.get_bale_pay_provider_token())

    def refresh_texts() -> None:
        active = []
        if settings.card_to_card_number:
            active.append(t("pay.method.card", lang))
        if settings.bale_pay_configured():
            active.append(t("pay.method.bale", lang))

        provider = settings.get_bale_pay_provider_token()
        if not provider:
            bale_token_kind.value = ""
            bale_test_warning.visible = False
            bale_test_warning.value = ""
        else:
            bale_token_kind.value = t("pay.bale.token_kind", lang, kind=describe_provider_token(provider))
            test_only = is_test_provider_token(provider)
            bale_test_warning.visible = test_only
            bale_test_warning.value = t("pay.bale.test_token_warning", lang) if test_only else ""

        if not settings.get_bale_pay_bot_token() or not provider:
            bale_note.value, bale_note.color = t("pay.bale.both_required", lang), theme.ACCENT_DARK
        elif manager is not None and not bale_running():
            bale_note.value, bale_note.color = t("pay.bale.needs_bots_on", lang), theme.ACCENT_DARK
        else:
            bale_note.value, bale_note.color = t("pay.bale.flow_note", lang), theme.text_secondary(page)

        if not active:
            summary.value, summary.color = t("pay.summary.none", lang), theme.DANGER
        elif len(active) == 1:
            summary.value, summary.color = t("pay.summary.one", lang, method=active[0]), theme.SUCCESS
        else:
            summary.value, summary.color = t("pay.summary.many", lang, methods=" / ".join(active)), theme.SUCCESS

        for control, key in ((card_error, "card_error"), (pay_error, "pay_error"), (reserve_error, "reserve_error")):
            control.value = ui[key]
            control.visible = bool(ui[key])

        errors = manager.payment_last_errors() if manager is not None else {}
        lines = []
        if errors.get(METHOD_BALE_PAY):
            lines.append(t("pay.diag.last_error", lang, method=t("pay.method.bale", lang), error=errors[METHOD_BALE_PAY]))
        last_errors_text.value = "\n".join(lines)
        last_errors_text.visible = bool(lines)

    def commit() -> None:
        save_callback()
        refresh_texts()
        page.update()

    # ----------------------------------------------------------- کارت‌به‌کارت
    def save_card(e=None) -> None:
        try:
            normalized = normalize_card_number(card_number.value or "", t("pay.card.number_invalid", lang))
        except ValueError as exc:
            ui["card_error"] = str(exc)
            refresh_texts()
            page.update()
            return  # مقدارِ قبلیِ معتبر دست‌نخورده می‌مونه
        ui["card_error"] = ""
        card_number.value = normalized
        settings.card_to_card_number = normalized
        settings.card_to_card_holder_name = (card_holder.value or "").strip()
        commit()

    for field in (card_number, card_holder):
        field.on_blur = save_card
        field.on_submit = save_card

    def toggle(attr):
        def handler(e) -> None:
            setattr(settings, attr, bool(e.control.value))
            commit()

        return handler

    receipt_check.on_change = toggle("receipt_check_enabled")
    receipt_amount_check.on_change = toggle("receipt_amount_check")
    alert_claim.on_change = toggle("alert_on_payment_claim")

    # ----------------------------------------------------------------- بله‌پی
    def save_bale_bot_token(e=None) -> None:
        new = (bale_bot_token.value or "").strip()
        if new != settings.get_bale_pay_bot_token():
            settings.set_bale_pay_bot_token(new)
            if not new and settings.bale_pay_enabled:
                settings.bale_pay_enabled = False  # بدون توکن، سوییچِ روشن یعنی وعده‌ی الکی
                bale_switch.value = False
            ui["pay_error"] = ""
            save_callback()
        refresh_texts()
        page.update()

    def save_bale_provider_token(e=None) -> None:
        new = normalize_provider_token(bale_provider_token.value or "")  # کارتِ فارسی/با خط‌تیره → ۱۶ رقم
        bale_provider_token.value = new
        if new != settings.get_bale_pay_provider_token():
            settings.set_bale_pay_provider_token(new)
            if not new and settings.bale_pay_enabled:
                settings.bale_pay_enabled = False
                bale_switch.value = False
            ui["pay_error"] = ""
            save_callback()
        refresh_texts()
        page.update()

    def on_bale_switch(e) -> None:
        wanted = bool(e.control.value)
        if wanted and not bale_tokens_present():
            e.control.value = False
            settings.bale_pay_enabled = False
            ui["pay_error"] = t("pay.bale.both_required", lang)
            refresh_texts()
            page.update()
            return
        settings.bale_pay_enabled = wanted
        ui["pay_error"] = ""
        commit()

    def on_link_mode(e) -> None:
        selected = list(getattr(e.control, "selected", []) or [])
        settings.bale_pay_link_mode = "deeplink" if "deeplink" in selected else "auto"
        commit()

    bale_bot_token.on_blur = bale_bot_token.on_submit = save_bale_bot_token
    bale_provider_token.on_blur = bale_provider_token.on_submit = save_bale_provider_token
    bale_switch.on_change = on_bale_switch
    link_mode.on_change = on_link_mode

    # ---------------------------------------------------- سفارش‌گیری هوشمند
    def save_reserve(e=None) -> None:
        raw = (reserve.value or "").strip().translate(_DIGIT_MAP)
        if not raw.isdigit() or not (MIN_RESERVE <= int(raw) <= MAX_RESERVE):
            ui["reserve_error"] = t("pay.smart.reserve_invalid", lang)
            refresh_texts()
            page.update()
            return
        ui["reserve_error"] = ""
        settings.reservation_minutes = int(raw)
        reserve.value = raw
        commit()

    reserve.on_blur = reserve.on_submit = save_reserve
    auto_confirm.on_change = toggle("auto_confirm_gateway_payments")

    # ---------------------------------------------------------- تست اتصال
    def make_diag(method: str, out: ft.Text):
        def handler(e=None) -> None:
            save_card()  # اگر کاربر Enter نزده، همین مقدارِ روی صفحه تست بشه
            out.value, out.color, out.visible = t("pay.diag.running", lang), theme.text_secondary(page), True
            page.update()

            def work() -> None:
                ok, message = manager.diagnose_payment_sync(method)
                out.value, out.color, out.visible = message, (theme.SUCCESS if ok else theme.DANGER), True
                refresh_texts()
                page.update()

            page.run_thread(work)

        return handler

    def diag_button(key: str, method: str, out: ft.Text) -> list:
        if manager is None:
            return []
        return [
            ft.OutlinedButton(key=key, content=t("pay.diag.test", lang), icon=ft.Icons.NETWORK_CHECK_ROUNDED, on_click=make_diag(method, out)),
            out,
        ]

    refresh_texts()

    subtitle = lambda text: ft.Text(text, size=13.5, weight=ft.FontWeight.W_600)  # noqa: E731
    payment_card = card(
        page,
        ft.Column(
            spacing=14,
            controls=[
                section_header(ft.Icons.PAYMENTS_ROUNDED, t("pay.title", lang)),
                ft.Text(t("pay.subtitle", lang), size=12, color=theme.text_secondary(page)),
                subtitle(t("pay.card.title", lang)),
                card_number,
                card_holder,
                card_error,
                card_manual_note,
                *diag_button("diag_card_to_card", METHOD_CARD_TO_CARD, diag_card_text),
                ft.Divider(height=1),
                subtitle(t("pay.bale.title", lang)),
                bale_switch,
                bale_bot_token,
                bale_bot_help,
                bale_provider_token,
                bale_provider_help,
                bale_token_kind,
                bale_test_warning,
                ft.Text(t("pay.bale.mode_label", lang), size=12.5, weight=ft.FontWeight.W_500),
                link_mode,
                link_mode_help,
                pay_error,
                bale_note,
                *diag_button("diag_bale_pay", METHOD_BALE_PAY, diag_bale_text),
                ft.Divider(height=1),
                subtitle(t("pay.receipt.title", lang)),
                ft.Text(t("pay.receipt.subtitle", lang), size=12, color=theme.text_secondary(page)),
                receipt_check,
                receipt_help,
                receipt_amount_check,
                alert_claim,
                receipt_manual,
                ft.Divider(height=1),
                subtitle(t("pay.smart.title", lang)),
                reserve,
                ft.Text(t("pay.smart.reserve_help", lang), size=12, color=theme.text_secondary(page)),
                reserve_error,
                auto_confirm,
                ft.Text(t("pay.smart.auto_confirm_help", lang), size=12, color=theme.text_secondary(page)),
                ft.Divider(height=1),
                summary,
                last_errors_text,
            ],
        ),
    )
    # «روش‌هایِ ارسال» جدا و زیرِ همین کارت است — خالی باشد یعنی این قابلیت خاموش است.
    return ft.Column([payment_card, shipping_card.build(page, lang, settings, save_callback)], spacing=18)
