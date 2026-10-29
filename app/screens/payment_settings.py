"""کارت «تنظیمات پرداخت و سفارش‌گیری» (فقط حالت فروشگاه) — بالای صفحه‌ی «سفارش‌ها».

سه روش پرداخت، هر سه کاملاً مالِ خودِ صاحب فروشگاه (پولی از اپ رد نمی‌شه):
- کارت‌به‌کارت دستی: شماره کارت + نام صاحب کارت (راز نیست؛ مستقیم به مشتری نشون
  داده می‌شه، پس رمزنگاری نمی‌شه). تایید همیشه دستیه.
- بله‌پی: سوییچ + provider_token (اعتبارنامه؛ مثل کلید API رمزنگاری می‌شه). لینکش
  از طریق ربات بله ساخته می‌شه — پس فقط وقتی معنی داره که ربات بله وصل باشه.
- زرین‌پال: سوییچ + مرچنت‌کد (۳۶ کاراکتر، رمزنگاری می‌شه) + حالت آزمایشی. چون اپ
  آدرس عمومی نداره، پرداخت با استعلامِ دوره‌ایِ verify فهمیده می‌شه.

بخش «سفارش‌گیری هوشمند»: مدتِ رزروِ موجودی، تایید خودکارِ پرداختِ آنلاین، و اطلاعاتِ
اجباریِ مشتری (تلفن/آدرس). دکمه‌های «تست اتصال» یه تماسِ آزمایشیِ *واقعی* می‌زنن و
پیامِ دقیقِ خطا رو نشون می‌دن — برای وقتی که لینکِ پرداخت به مشتری نمی‌رسه.

همه‌ی مقدارها زنده خونده می‌شن (همون شیء settings) — تغییرها ری‌استارت ربات نمی‌خوان؛
تنها استثنا: وصل‌کردنِ ربات بله بعد از روشن‌شدنِ ربات‌ها (برای بله‌پی ری‌استارت لازمه).
"""

from __future__ import annotations

import flet as ft

from app import theme
from app.core.orders import METHOD_BALE_PAY, METHOD_ZARINPAL
from app.core.payments import normalize_provider_token
from app.core.payments import normalize_card_number
from app.core.zarinpal import is_valid_merchant_id
from app.i18n import t
from app.screens.common import card, section_header

MIN_RESERVE, MAX_RESERVE = 1, 240


def build(page: ft.Page, lang: str, settings, save_callback, manager=None) -> ft.Control:
    ui = {"card_error": "", "pay_error": "", "zp_error": "", "reserve_error": ""}

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

    bale_switch = ft.Switch(
        key="bale_pay_enabled", label=t("pay.bale.enable", lang), value=bool(settings.bale_pay_enabled),
        active_color=theme.SUCCESS,
    )
    bale_token = ft.TextField(
        key="bale_pay_token", label=t("pay.bale.token_label", lang), hint_text=t("pay.bale.token_hint", lang),
        value=settings.get_bale_pay_provider_token(), password=True, can_reveal_password=True,
        prefix_icon=ft.Icons.VPN_KEY_ROUNDED, text_align=ft.TextAlign.LEFT, border_radius=10,
    )
    pay_error = ft.Text("", key="pay_error", size=12, color=theme.DANGER, visible=False)
    bale_note = ft.Text("", key="bale_note", size=12)

    zp_switch = ft.Switch(
        key="zarinpal_enabled", label=t("pay.zarinpal.enable", lang), value=bool(settings.zarinpal_enabled),
        active_color=theme.SUCCESS,
    )
    zp_merchant = ft.TextField(
        key="zarinpal_merchant_id", label=t("pay.zarinpal.merchant_label", lang),
        hint_text=t("pay.zarinpal.merchant_hint", lang), value=settings.get_zarinpal_merchant_id(),
        password=True, can_reveal_password=True, prefix_icon=ft.Icons.VPN_KEY_ROUNDED,
        text_align=ft.TextAlign.LEFT, border_radius=10,
    )
    zp_sandbox = ft.Switch(key="zarinpal_sandbox", label=t("pay.zarinpal.sandbox", lang), value=bool(settings.zarinpal_sandbox))
    zp_callback = ft.TextField(
        key="zarinpal_callback_url", label=t("pay.zarinpal.callback_label", lang),
        hint_text=t("pay.zarinpal.callback_hint", lang), value=settings.zarinpal_callback_url,
        prefix_icon=ft.Icons.LINK_ROUNDED, text_align=ft.TextAlign.LEFT, border_radius=10,
    )
    zp_error = ft.Text("", key="zarinpal_error", size=12, color=theme.DANGER, visible=False)

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
    need_phone = ft.Switch(key="require_customer_phone", label=t("pay.smart.require_phone", lang), value=bool(settings.require_customer_phone))
    need_address = ft.Switch(key="require_customer_address", label=t("pay.smart.require_address", lang), value=bool(settings.require_customer_address))

    summary = ft.Text("", key="pay_summary", size=12.5, weight=ft.FontWeight.W_500)
    last_errors_text = ft.Text("", key="last_errors", size=12, color=theme.DANGER, visible=False)
    diag_bale_text = ft.Text("", key="diag_bale_result", size=12, visible=False)
    diag_zp_text = ft.Text("", key="diag_zarinpal_result", size=12, visible=False)

    # ------------------------------------------------------------- وضعیت
    def bale_bot_ready() -> bool:
        return bool(settings.bale_enabled and settings.get_bale_token())

    def zarinpal_ready() -> bool:
        return bool(settings.zarinpal_enabled and is_valid_merchant_id(settings.get_zarinpal_merchant_id()))

    def refresh_texts() -> None:
        active = []
        if settings.card_to_card_number:
            active.append(t("pay.method.card", lang))
        if settings.bale_pay_enabled and settings.get_bale_pay_provider_token() and bale_bot_ready():
            active.append(t("pay.method.bale", lang))
        if zarinpal_ready():
            active.append(t("pay.method.zarinpal", lang))

        if not bale_bot_ready():
            bale_note.value, bale_note.color = t("pay.bale.needs_bale_bot", lang), theme.ACCENT_DARK
        elif manager is not None and manager.is_running() and "bale" not in manager.started_platforms():
            bale_note.value, bale_note.color = t("pay.bale.needs_restart", lang), theme.ACCENT_DARK
        else:
            bale_note.value, bale_note.color = t("pay.bale.help", lang), theme.text_secondary(page)

        if not active:
            summary.value, summary.color = t("pay.summary.none", lang), theme.DANGER
        elif len(active) == 1:
            summary.value, summary.color = t("pay.summary.one", lang, method=active[0]), theme.SUCCESS
        else:
            summary.value, summary.color = t("pay.summary.many", lang, methods=" / ".join(active)), theme.SUCCESS

        for control, key in ((card_error, "card_error"), (pay_error, "pay_error"), (zp_error, "zp_error"), (reserve_error, "reserve_error")):
            control.value = ui[key]
            control.visible = bool(ui[key])

        errors = manager.payment_last_errors() if manager is not None else {}
        lines = []
        if errors.get(METHOD_BALE_PAY):
            lines.append(t("pay.diag.last_error", lang, method=t("pay.method.bale", lang), error=errors[METHOD_BALE_PAY]))
        if errors.get(METHOD_ZARINPAL):
            lines.append(t("pay.diag.last_error", lang, method=t("pay.method.zarinpal", lang), error=errors[METHOD_ZARINPAL]))
        last_errors_text.value = "\n".join(lines)
        last_errors_text.visible = bool(lines)

    def commit() -> None:
        save_callback()
        refresh_texts()
        page.update()

    # ----------------------------------------------------------- کارت‌به‌کارت
    def save_card(e=None) -> None:
        try:
            normalized = normalize_card_number(card_number.value or "")
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

    # ----------------------------------------------------------------- بله‌پی
    def save_bale_token(e=None) -> None:
        new = normalize_provider_token(bale_token.value or "")  # شماره کارتِ فارسی/با خط‌تیره → ۱۶ رقمِ لاتین
        bale_token.value = new
        if new != settings.get_bale_pay_provider_token():
            settings.set_bale_pay_provider_token(new)
            if not new and settings.bale_pay_enabled:
                settings.bale_pay_enabled = False  # بدون توکن، سوییچِ روشن یعنی وعده‌ی الکی
                bale_switch.value = False
            save_callback()
        ui["pay_error"] = ""
        refresh_texts()
        page.update()

    def on_bale_switch(e) -> None:
        wanted = bool(e.control.value)
        if wanted and not (bale_token.value or "").strip():
            e.control.value = False
            settings.bale_pay_enabled = False
            ui["pay_error"] = t("pay.bale.token_required", lang)
            refresh_texts()
            page.update()
            return
        if wanted:
            settings.set_bale_pay_provider_token(normalize_provider_token(bale_token.value or ""))
        settings.bale_pay_enabled = wanted
        ui["pay_error"] = ""
        commit()

    bale_token.on_blur = bale_token.on_submit = save_bale_token
    bale_switch.on_change = on_bale_switch

    # ---------------------------------------------------------------- زرین‌پال
    def save_zarinpal_fields(e=None) -> None:
        raw = (zp_merchant.value or "").strip()
        if raw and not is_valid_merchant_id(raw):
            ui["zp_error"] = t("pay.zarinpal.merchant_invalid", lang)
            refresh_texts()
            page.update()
            return  # مقدارِ قبلیِ معتبر دست‌نخورده می‌مونه
        ui["zp_error"] = ""
        if raw != settings.get_zarinpal_merchant_id():
            settings.set_zarinpal_merchant_id(raw)
            if not raw and settings.zarinpal_enabled:
                settings.zarinpal_enabled = False
                zp_switch.value = False
        settings.zarinpal_callback_url = (zp_callback.value or "").strip()
        commit()

    def on_zp_switch(e) -> None:
        wanted = bool(e.control.value)
        raw = (zp_merchant.value or "").strip()
        if wanted and not is_valid_merchant_id(raw):
            e.control.value = False
            settings.zarinpal_enabled = False
            ui["zp_error"] = t("pay.zarinpal.merchant_required", lang) if not raw else t("pay.zarinpal.merchant_invalid", lang)
            refresh_texts()
            page.update()
            return
        if wanted:
            settings.set_zarinpal_merchant_id(raw)
        settings.zarinpal_enabled = wanted
        ui["zp_error"] = ""
        commit()

    def on_zp_sandbox(e) -> None:
        settings.zarinpal_sandbox = bool(e.control.value)
        commit()

    zp_merchant.on_blur = zp_merchant.on_submit = save_zarinpal_fields
    zp_callback.on_blur = zp_callback.on_submit = save_zarinpal_fields
    zp_switch.on_change = on_zp_switch
    zp_sandbox.on_change = on_zp_sandbox

    # ---------------------------------------------------- سفارش‌گیری هوشمند
    def save_reserve(e=None) -> None:
        raw = (reserve.value or "").strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
        if not raw.isdigit() or not (MIN_RESERVE <= int(raw) <= MAX_RESERVE):
            ui["reserve_error"] = t("pay.smart.reserve_invalid", lang)
            refresh_texts()
            page.update()
            return
        ui["reserve_error"] = ""
        settings.reservation_minutes = int(raw)
        reserve.value = raw
        commit()

    def toggle(attr):
        def handler(e) -> None:
            setattr(settings, attr, bool(e.control.value))
            commit()

        return handler

    reserve.on_blur = reserve.on_submit = save_reserve
    auto_confirm.on_change = toggle("auto_confirm_gateway_payments")
    need_phone.on_change = toggle("require_customer_phone")
    need_address.on_change = toggle("require_customer_address")

    # ---------------------------------------------------------- تست اتصال
    def make_diag(method: str, out: ft.Text):
        def handler(e=None) -> None:
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
    return card(
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
                ft.Divider(height=1),
                subtitle(t("pay.bale.title", lang)),
                bale_switch,
                bale_token,
                pay_error,
                bale_note,
                *diag_button("diag_bale_pay", METHOD_BALE_PAY, diag_bale_text),
                ft.Divider(height=1),
                subtitle(t("pay.zarinpal.title", lang)),
                zp_switch,
                zp_merchant,
                zp_sandbox,
                zp_callback,
                zp_error,
                ft.Text(t("pay.zarinpal.help", lang), size=12, color=theme.text_secondary(page)),
                *diag_button("diag_zarinpal", METHOD_ZARINPAL, diag_zp_text),
                ft.Divider(height=1),
                subtitle(t("pay.smart.title", lang)),
                reserve,
                ft.Text(t("pay.smart.reserve_help", lang), size=12, color=theme.text_secondary(page)),
                reserve_error,
                auto_confirm,
                ft.Text(t("pay.smart.auto_confirm_help", lang), size=12, color=theme.text_secondary(page)),
                need_phone,
                need_address,
                ft.Divider(height=1),
                summary,
                last_errors_text,
            ],
        ),
    )
