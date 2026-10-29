"""صفحه‌ی «مالی و فاکتور» (N19): داشبورد، فاکتورها، دفتر، تنظیمات.

**ابزارِ کمکیِ مدیریتِ فروشگاه است، نه حسابداریِ رسمی و نه اتصال به «سامانه‌ی مودیان».** همه‌ی عددها از دفترِ append-only و
سفارش‌های واقعی می‌آن (``app/core/finance.py``)؛ هیچ آمارِ ساختگی/شمارنده‌ی جدا نیست.
"""

from __future__ import annotations

import re
import time
from decimal import Decimal, InvalidOperation
from typing import Optional

import flet as ft

from app import theme
from app.core import finance as fin
from app.core import jalali
from app.core.invoice_pdf import money as pdf_money  # noqa: F401  (هم‌خانواده‌ی قالبِ پولیِ PDF)
from app.core.invoices import InvoiceError
from app.core.settings import save_settings
from app.screens import common
from app.screens.discounts import parse_toman

_S = {
    "title": ("مالی و فاکتور", "Finance & invoices"),
    "subtitle": ("فروش، هزینه، سود و فاکتور — ابزارِ کمکیِ مدیریتِ فروشگاه؛ جایگزینِ حسابدارِ رسمی و سامانه‌ی مودیان نیست.", "Sales, costs, profit and invoices — a helper for running the shop; not a replacement for an accountant or the tax system."),
    "tab_dash": ("داشبورد", "Dashboard"), "tab_inv": ("فاکتورها", "Invoices"), "tab_led": ("دفتر", "Ledger"), "tab_set": ("تنظیمات", "Settings"),
    "p_today": ("امروز", "Today"), "p_7": ("۷ روز", "7 days"), "p_month": ("این ماه", "This month"), "p_prev": ("ماهِ قبل", "Last month"), "p_all": ("کل", "All"),
    "k_sales": ("فروشِ خالص", "Net sales"), "k_orders": ("سفارش", "Orders"), "k_gross": ("ناخالص (قبل از تخفیف)", "Gross (before discounts)"),
    "k_disc": ("تخفیف‌ها", "Discounts"), "k_refund": ("برگشتی", "Refunds"), "k_cogs": ("بهای کالای فروخته‌شده", "Cost of goods sold"),
    "k_gp": ("سودِ ناخالص", "Gross profit"), "k_exp": ("هزینه‌ها", "Expenses"), "k_np": ("سودِ خالص", "Net profit"),
    "k_inv": ("ارزشِ موجودی (به بهای تمام‌شده)", "Inventory value (at cost)"), "k_wait": ("منتظرِ تایید", "Awaiting confirmation"), "k_pend": ("در انتظارِ پرداخت", "Awaiting payment"),
    "unit_toman": ("تومان", "Toman"), "unit_irr": ("ریال", "IRR"),
    "warn_cost": ("⚠️ بهای تمام‌شده‌ی {n} سفارش کامل ثبت نشده؛ سودِ ناخالص بیشتر از واقعیت نشان داده می‌شه. بهای محصولات را در «محصولات» وارد کن.", "⚠️ {n} order(s) have incomplete cost data; gross profit is overstated. Enter product costs under Products."),
    "by_method": ("درآمد بر اساس روش", "Income by method"), "top_products": ("پرفروش‌ترین‌ها", "Top products"), "top_customers": ("بهترین مشتری‌ها", "Top customers"), "by_cat": ("هزینه‌ها بر اساس دسته", "Expenses by category"),
    "daily": ("درآمدِ روزانه", "Daily income"), "none": ("هنوز داده‌ای نیست.", "No data yet."), "export": ("خروجیِ CSV", "Export CSV"),
    "exported": ("✅ ذخیره شد: {path}", "✅ Saved: {path}"), "open_folder": ("باز کردنِ پوشه", "Open folder"),
    "inv_search": ("جستجو (شماره/نامِ خریدار/شماره‌ی سفارش)", "Search (number / buyer / order id)"), "inv_none": ("فاکتوری نیست.", "No invoices."),
    "inv_row": ("{number} — {date} — {buyer} — {total} {unit}", "{number} — {date} — {buyer} — {total} {unit}"),
    "inv_sent": ("✅ ارسال شده", "✅ Sent"), "inv_fail": ("❌ ارسال نشد", "❌ Not sent"), "inv_wait": ("— ارسال نشده", "— Not sent"),
    "resend": ("ارسالِ دوباره", "Resend"), "credit": ("فاکتورِ برگشتی", "Credit note"), "credit_sure": ("مطمئنی؟ دوباره بزن", "Sure? Click again"),
    "credit_back": ("کالا برگشت داده شد (بهای کالا هم برگردد)", "Goods returned (also reverse cost of goods)"),
    "make_pdf": ("ساخت/نمایشِ PDF", "Build/show PDF"), "pdf_ok": ("PDF آماده است: {path}", "PDF ready: {path}"),
    "issue_order": ("شماره‌ی سفارش برای صدورِ فاکتور", "Order id to issue an invoice for"), "issue": ("صدورِ فاکتور", "Issue invoice"),
    "issued": ("✅ فاکتور {number} صادر شد.", "✅ Invoice {number} issued."), "sent_ok": ("✅ برای مشتری فرستاده شد.", "✅ Sent to the customer."),
    "send_off": ("ربات‌ها خاموشن؛ اول روشنشون کن.", "Bots are off; turn them on first."), "send_skip": ("ارسال نشد: {why}", "Not sent: {why}"),
    "credit_done": ("✅ فاکتورِ برگشتی {number} صادر و در دفتر ثبت شد.", "✅ Credit note {number} issued and posted."),
    "led_kind": ("نوع", "Type"), "kind_income": ("درآمد", "Income"), "kind_expense": ("هزینه", "Expense"), "kind_cogs": ("بهای کالا", "COGS"), "kind_refund": ("برگشتی", "Refund"),
    "led_cat": ("دسته", "Category"), "led_amount": ("مبلغ ({unit})", "Amount ({unit})"), "led_account": ("حساب", "Account"), "led_date": ("تاریخِ جلالی (خالی = الان)", "Jalali date (empty = now)"),
    "led_note": ("توضیح", "Note"), "led_add": ("ثبت", "Add"), "led_added": ("✅ ثبت شد.", "✅ Added."), "reverse": ("برگشت‌زدن", "Reverse"), "reversed": ("✅ برگشت خورد.", "✅ Reversed."),
    "led_filter": ("فیلتر", "Filter"), "all": ("همه", "All"), "led_none": ("ردیفی نیست.", "No entries."), "tag_rev": ("[برگشت‌خورده]", "[reversed]"), "tag_reversal": ("[ردیفِ برگشت]", "[reversal]"),
    "bad": ("«{label}» درست نیست.", "“{label}” is not valid."),
    "s_seller": ("اطلاعاتِ فروشنده روی فاکتور", "Seller details on invoices"), "s_name": ("نامِ فروشگاه", "Shop name"), "s_legal": ("نامِ حقیقی/حقوقی", "Legal name"),
    "s_nid": ("شناسه‌ی ملی/اقتصادی", "National / economic id"), "s_addr": ("نشانی", "Address"), "s_phone": ("تلفن", "Phone"),
    "s_logo": ("لوگو (مسیرِ فایلِ PNG/JPG، حداکثر ۳۰۰ کیلوبایت)", "Logo (PNG/JPG path, max 300 KB)"), "s_color": ("رنگِ اصلی (#RRGGBB)", "Accent color (#RRGGBB)"), "s_footer": ("متنِ پایینِ فاکتور", "Invoice footer text"),
    "s_vat": ("مالیات بر ارزش افزوده را روی فاکتور نشان بده (قیمت‌ها «با مالیات» حساب می‌شن)", "Show VAT on invoices (prices are treated as VAT-inclusive)"),
    "s_vat_rate": ("نرخِ مالیات (٪)", "VAT rate (%)"), "s_vat_hint": ("نرخِ عمومیِ ۱۴۰۵ طبقِ سازمانِ امورِ مالیاتی ۱۰٪ اعلام شده؛ هر زمان تغییر کرد همین‌جا عوضش کن.", "The general 2026 rate was announced as 10%; change it here if it changes."),
    "s_num": ("شماره‌گذاری", "Numbering"), "s_prefix": ("پیشوند", "Prefix"), "s_start": ("شماره‌ی شروع", "Start number"), "s_year": ("سالِ جلالی در شماره (شمارنده هر سال از نو)", "Jalali year in the number (counter restarts yearly)"),
    "s_paper": ("اندازه‌ی کاغذ", "Paper size"), "s_digits": ("ارقام", "Digits"), "digits_fa": ("فارسی", "Persian"), "digits_en": ("لاتین", "Latin"),
    "s_auto": ("ارسالِ خودکارِ فاکتور", "Automatic invoice sending"), "auto_off": ("خاموش", "Off"), "auto_on": ("بعد از تاییدِ سفارش", "After order confirmation"),
    "s_owner_copy": ("نسخه‌ای هم برای من (مالک) بفرست", "Also send me (owner) a copy"),
    "s_fees": ("کارمزدِ درگاه (٪ از مبلغِ هر فروش؛ به‌عنوانِ هزینه ثبت می‌شه)", "Gateway fees (% of each sale; recorded as an expense)"), "s_fee_bale": ("کارمزدِ بله‌پی (٪)", "Bale Pay fee (%)"), "s_fee_zp": ("کارمزدِ زرین‌پال (٪)", "Zarinpal fee (%)"),
    "s_unit": ("واحدِ نمایش", "Display unit"), "s_mgr": ("به «مدیر» اجازه‌ی دیدنِ خلاصه‌ی مالی در ربات را بده", "Let “manager” admins view the finance summary in the bot"),
    "save": ("ذخیره", "Save"), "saved": ("✅ ذخیره شد.", "✅ Saved."),
    "no_shop": ("این بخش فقط در حالتِ «فروشگاه» هست.", "This section is only available in Shop mode."),
}


def S(key: str, lang: str, **kw) -> str:
    fa, en = _S[key]
    text = en if lang == "en" else fa
    return text.format(**kw) if kw else text


def parse_percent_bp(text, maximum_bp: int = fin.MAX_BP) -> Optional[int]:
    """«۱٫۵» یا «1.5» ← ۱۵۰ basis point؛ خالی ← ۰؛ نامعتبر/منفی/بیش از سقف ← ``None``."""
    raw = jalali.en_digits(str(text or "")).replace("٫", ".").replace(",", ".").replace("٪", "").replace("%", "").strip()
    if not raw:
        return 0
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    bp = int((value * 100).to_integral_value())
    return bp if 0 <= bp <= maximum_bp and value * 100 == bp else None


def parse_amount(text, unit: str) -> Optional[int]:
    """مبلغِ تایپ‌شده به ریال: واحدِ «تومان» ← ×۱۰؛ «ریال» همان عدد. نامعتبر/غیرمثبت ← ``None``."""
    if unit == "irr":
        raw = jalali.en_digits(str(text or "")).replace(",", "").replace("٬", "").replace(" ", "")
        return int(raw) if raw.isdigit() and 0 < int(raw) <= fin.MAX_AMOUNT else None
    value = parse_toman(text, allow_empty=False)
    return value if value and 0 < value <= fin.MAX_AMOUNT else None


def period_range(key: str, now: Optional[float] = None) -> tuple:
    now = now if now is not None else time.time()
    t0, t1 = jalali.today_range(now)
    jy, jm, _jd = jalali.ts_to_jalali(now)
    if key == "today":
        return t0, t1
    if key == "7":
        return t0 - 6 * 86400, t1
    if key == "month":
        return jalali.month_range(jy, jm)
    if key == "prev":
        return jalali.month_range(jy - 1, 12) if jm == 1 else jalali.month_range(jy, jm - 1)
    return 0, 2**40


def build(page: ft.Page, lang: str, manager, settings, product_store=None) -> ft.Control:
    secondary = theme.text_secondary(page)
    finance, invoices = manager.finance, manager.invoices
    header = common.page_header(page, ft.Icons.ACCOUNT_BALANCE_WALLET_ROUNDED, S("title", lang), S("subtitle", lang))
    if finance is None:
        return ft.Container(expand=True, padding=ft.Padding.symmetric(horizontal=32, vertical=24), content=ft.Column(spacing=14, controls=[header, ft.Text(S("no_shop", lang), size=14, color=secondary)]))

    st = {"tab": "dash", "period": "month", "kind": "", "query": "", "credit": None}
    unit = lambda: "irr" if settings.finance_unit == "irr" else "toman"  # noqa: E731
    unit_label = lambda: S(f"unit_{unit()}", lang)  # noqa: E731

    def show_money(irr: int) -> str:
        value = int(irr) if unit() == "irr" else fin.round_div(abs(int(irr)), 10) * (1 if irr >= 0 else -1)
        return f"{value:,}"

    notice = ft.Text("", key="fn_notice", size=12.5, visible=False)
    body = ft.Column(spacing=14)

    def say(text: str, ok: bool = True) -> None:
        notice.value, notice.color, notice.visible = text, theme.SUCCESS if ok else theme.DANGER, bool(text)

    def kpi(key: str, irr, tag: str, bad: bool = False) -> ft.Control:
        return common.card(page, ft.Column(spacing=2, controls=[
            ft.Text(S(key, lang), size=12, color=secondary),
            ft.Text(f"{show_money(irr)} {unit_label()}", key=tag, size=15, weight=ft.FontWeight.W_700, color=theme.DANGER if bad else None),
        ]), padding=12)

    # ----------------------------------------------------------------- داشبورد
    def dash() -> list:
        a, b = period_range(st["period"])
        r = finance.report(a, b)

        def chip(k: str) -> ft.Control:
            return (ft.FilledButton if st["period"] == k else ft.OutlinedButton)(key=f"fn_period_{k}", content=S(f"p_{k}", lang), on_click=lambda _e, kk=k: (st.update(period=kk), render()))

        def listing(title_key: str, rows: list, tag: str) -> ft.Control:
            lines = [ft.Text(x, size=12.5, color=secondary) for x in rows] or [ft.Text(S("none", lang), size=12.5, color=secondary)]
            return common.card(page, ft.Column(spacing=4, controls=[ft.Text(S(title_key, lang), size=14, weight=ft.FontWeight.W_700), ft.Column(key=tag, spacing=2, controls=lines)]), padding=14)

        peak = max((abs(v) for _d, v in r.by_day), default=0) or 1
        bars = ft.Row(key="fn_daily", spacing=2, vertical_alignment=ft.CrossAxisAlignment.END, height=80, wrap=False, controls=[
            ft.Container(width=8, height=max(2, int(76 * max(0, v) / peak)), bgcolor=theme.PRIMARY, border_radius=2, tooltip=f"{d}: {show_money(v)}") for d, v in r.by_day[-45:]])
        controls: list = [
            ft.Row(spacing=8, wrap=True, controls=[chip(k) for k in ("today", "7", "month", "prev", "all")]),
            ft.Row(spacing=10, wrap=True, controls=[
                kpi("k_sales", r.sales_net, "fn_k_sales"), ft.Container(content=common.card(page, ft.Column(spacing=2, controls=[ft.Text(S("k_orders", lang), size=12, color=secondary), ft.Text(str(r.orders_count), key="fn_k_orders", size=15, weight=ft.FontWeight.W_700)]), padding=12)),
                kpi("k_gross", r.gross_sales, "fn_k_gross"), kpi("k_disc", r.discounts, "fn_k_disc"), kpi("k_refund", r.refunds, "fn_k_refund"),
                kpi("k_cogs", r.cogs, "fn_k_cogs"), kpi("k_gp", r.gross_profit, "fn_k_gp", r.gross_profit < 0), kpi("k_exp", r.expenses, "fn_k_exp"),
                kpi("k_np", r.net_profit, "fn_k_np", r.net_profit < 0), kpi("k_wait", r.receivables_waiting, "fn_k_wait"), kpi("k_pend", r.receivables_pending, "fn_k_pend"), kpi("k_inv", r.inventory_value, "fn_k_inv"),
            ]),
        ]
        if r.missing_cost_orders:
            controls.append(ft.Text(S("warn_cost", lang, n=r.missing_cost_orders), key="fn_warn_cost", size=12.5, color=theme.DANGER))
        controls += [
            common.card(page, ft.Column(spacing=6, controls=[ft.Text(S("daily", lang), size=14, weight=ft.FontWeight.W_700), bars]), padding=14),
            listing("by_method", [f"{fin.ACCOUNT_LABEL_FA.get(k, k)}: {show_money(v)} {unit_label()}" for k, v in r.by_method.items()], "fn_by_method"),
            listing("top_products", [f"{n} — {q} × — {show_money(v)} {unit_label()}" for n, q, v in r.by_product[:5]], "fn_top_products"),
            listing("top_customers", [f"{p}:{c} {nm} — {show_money(v)} {unit_label()}" for p, c, nm, v in r.top_customers], "fn_top_customers"),
            listing("by_cat", [f"{n}: {show_money(v)} {unit_label()}" for n, v in r.by_category], "fn_by_cat"),
        ]
        return controls

    # ----------------------------------------------------------------- فاکتورها
    def inv_status(inv) -> str:
        cust = inv.sent.get("customer")
        return S("inv_wait", lang) if not cust else S("inv_sent" if cust.get("ok") else "inv_fail", lang)

    def do_resend(inv_id: int) -> None:
        try:
            out = manager.send_invoice(inv_id)
        except Exception as exc:  # noqa: BLE001 — BotManagerError (ربات خاموش) و غیره
            say(str(exc) or S("send_off", lang), False)
        else:
            why = out.split(":", 1)[1] if ":" in out else ""
            say(S("sent_ok", lang) if out == "sent" else S("send_skip", lang, why=why or out), out == "sent")
        render()

    def do_pdf(inv_id: int) -> None:
        inv = invoices.store.get(inv_id)
        try:
            path = invoices.ensure_pdf(inv)
        except Exception as exc:  # noqa: BLE001
            say(str(exc), False)
        else:
            say(S("pdf_ok", lang, path=path), True)
            common.open_folder(path.parent)
        page.update()

    def do_credit(inv_id: int) -> None:
        if st["credit"] != inv_id:  # دو مرحله‌ای: اول «مطمئنی؟»
            st["credit"] = inv_id
            render()
            return
        st["credit"] = None
        try:
            cn = invoices.credit_note(inv_id, cogs_back=bool(back_sw.value))
            say(S("credit_done", lang, number=cn.number), True)
        except InvoiceError as exc:
            say(str(exc), False)
        render()

    back_sw = ft.Switch(key="fn_credit_back", label=S("credit_back", lang), value=False)
    issue_tf = ft.TextField(key="fn_issue_order", label=S("issue_order", lang), width=220, border_radius=10)

    def do_issue(_e=None) -> None:
        raw = jalali.en_digits(issue_tf.value or "").lstrip("#").strip()
        order = order_lookup(int(raw)) if raw.isdigit() else None
        if order is None:
            say(S("bad", lang, label=S("issue_order", lang)), False)
        else:
            try:
                inv = invoices.issue(order)
                say(S("issued", lang, number=inv.number), True)
            except InvoiceError as exc:
                say(str(exc), False)
        render()

    def order_lookup(order_id: int):
        return finance._orders.get(order_id)  # noqa: SLF001 — همان OrderStoreِ مدیر

    search_tf = ft.TextField(key="fn_inv_search", label=S("inv_search", lang), width=340, border_radius=10, value=st["query"],
                             on_submit=lambda e: (st.update(query=e.control.value or ""), render()))

    def invs() -> list:
        rows = []
        for inv in invoices.store.list(st["query"], limit=100):
            buyer = inv.buyer.get("name") or "—"
            title = S("inv_row", lang, number=inv.number, date=jalali.format_ts(inv.issued_ts), buyer=buyer, total=show_money(inv.total_irr), unit=unit_label())
            actions = [ft.TextButton(key=f"fn_inv_pdf_{inv.id}", content=S("make_pdf", lang), on_click=lambda _e, i=inv.id: do_pdf(i))]
            if not inv.is_credit:
                actions.append(ft.TextButton(key=f"fn_inv_resend_{inv.id}", content=S("resend", lang), on_click=lambda _e, i=inv.id: do_resend(i)))
                if invoices.store.return_note_for(inv.id) is None:
                    actions.append(ft.TextButton(key=f"fn_inv_credit_{inv.id}", content=S("credit_sure" if st["credit"] == inv.id else "credit", lang), on_click=lambda _e, i=inv.id: do_credit(i)))
            rows.append(ft.Column(spacing=2, controls=[ft.Text(("↩️ " if inv.is_credit else "") + title, size=13, weight=ft.FontWeight.W_600), ft.Text(inv_status(inv), size=12, color=secondary), ft.Row(spacing=6, wrap=True, controls=actions)]))
        return rows or [ft.Text(S("inv_none", lang), size=13, color=secondary)]

    def invoices_tab() -> list:
        return [
            ft.Row(spacing=10, wrap=True, controls=[search_tf, ft.OutlinedButton(key="fn_inv_find", content=S("led_filter", lang), on_click=lambda _e: (st.update(query=search_tf.value or ""), render()))]),
            ft.Row(spacing=10, wrap=True, controls=[issue_tf, ft.FilledButton(key="fn_issue", content=S("issue", lang), on_click=do_issue), back_sw]),
            common.card(page, ft.Column(key="fn_inv_list", spacing=10, controls=invs()), padding=14),
        ]

    # --------------------------------------------------------------------- دفتر
    kind_dd = ft.Dropdown(key="fn_led_kind", label=S("led_kind", lang), width=150, border_radius=10, value="expense",
                          options=[ft.DropdownOption(key=k, text=S(f"kind_{k}", lang)) for k in fin.MANUAL_KINDS])
    cat_dd = ft.Dropdown(key="fn_led_cat", label=S("led_cat", lang), width=200, border_radius=10)
    amount_tf = ft.TextField(key="fn_led_amount", width=190, border_radius=10)
    acct_dd = ft.Dropdown(key="fn_led_account", label=S("led_account", lang), width=150, border_radius=10, value="cash",
                          options=[ft.DropdownOption(key=k, text=fin.ACCOUNT_LABEL_FA[k]) for k in fin.ACCOUNTS])
    date_tf = ft.TextField(key="fn_led_date", label=S("led_date", lang), width=200, border_radius=10)
    note_tf = ft.TextField(key="fn_led_note", label=S("led_note", lang), width=300, border_radius=10, max_length=fin.MAX_NOTE)
    filter_dd = ft.Dropdown(key="fn_led_filter", label=S("led_filter", lang), width=160, border_radius=10, value=st["kind"] or "all",
                            options=[ft.DropdownOption(key="all", text=S("all", lang)), *[ft.DropdownOption(key=k, text=S(f"kind_{k}", lang)) for k in fin.KINDS]],
                            on_select=lambda e: (st.update(kind="" if e.control.value == "all" else e.control.value), render()))

    def fill_categories(_e=None) -> None:
        cats = finance.categories(kind_dd.value or "expense")
        cat_dd.options = [ft.DropdownOption(key=c["key"], text=c["name"]) for c in cats]
        if cat_dd.value not in {c["key"] for c in cats}:
            cat_dd.value = cats[0]["key"] if cats else None

    kind_dd.on_select = lambda e: (fill_categories(), page.update())

    def do_add(_e=None) -> None:
        amount = parse_amount(amount_tf.value, unit())
        if amount is None:
            say(S("bad", lang, label=S("led_amount", lang, unit=unit_label())), False)
            return page.update()
        ts = None
        if (date_tf.value or "").strip():
            try:
                ts = jalali.parse_date_ts(date_tf.value) + 12 * 3600
            except jalali.JalaliError as exc:
                say(str(exc), False)
                return page.update()
        try:
            finance.add_entry(kind_dd.value, amount, cat_dd.value or "", acct_dd.value or "cash", note_tf.value or "", ts=ts)
        except fin.FinanceError as exc:
            say(str(exc), False)
            return page.update()
        amount_tf.value = note_tf.value = date_tf.value = ""
        say(S("led_added", lang), True)
        render()

    def do_reverse(eid: int) -> None:
        try:
            finance.reverse(eid)
            say(S("reversed", lang), True)
        except fin.FinanceError as exc:
            say(str(exc), False)
        render()

    def do_export(_e=None) -> None:
        from app.core.paths import get_app_data_dir

        folder = get_app_data_dir() / "exports"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"ledger-{jalali.format_ts(time.time(), digits='en').replace('/', '-')}.csv"
        path.write_text(finance.export_csv(), encoding="utf-8")
        say(S("exported", lang, path=path), True)
        common.open_folder(folder)
        page.update()

    def ledger_tab() -> list:
        fill_categories()
        amount_tf.label = S("led_amount", lang, unit=unit_label())
        rows = []
        for e in finance.list_entries(kind=st["kind"], limit=200):
            tag = S("tag_reversal", lang) if e.reverses_id else (S("tag_rev", lang) if e.reversed_by_id else "")
            sign = -1 if e.reverses_id else 1
            line = f"{jalali.format_ts(e.ts)} — {S(f'kind_{e.kind}', lang)} — {e.category} — {show_money(sign * e.amount_irr)} {unit_label()} {tag} {e.note}".strip()
            can_rev = not (e.reverses_id or e.reversed_by_id)
            rows.append(ft.Row(spacing=6, controls=[ft.Text(line, size=12.5, expand=True), *([ft.TextButton(key=f"fn_led_rev_{e.id}", content=S("reverse", lang), on_click=lambda _e, i=e.id: do_reverse(i))] if can_rev else [])]))
        return [
            common.card(page, ft.Column(spacing=10, controls=[ft.Row(spacing=10, wrap=True, controls=[kind_dd, cat_dd, amount_tf, acct_dd, date_tf]), ft.Row(spacing=10, wrap=True, controls=[note_tf, ft.FilledButton(key="fn_led_add", content=S("led_add", lang), icon=ft.Icons.ADD_ROUNDED, on_click=do_add)])]), padding=14),
            ft.Row(spacing=10, wrap=True, controls=[filter_dd, ft.OutlinedButton(key="fn_led_export", content=S("export", lang), icon=ft.Icons.DOWNLOAD_ROUNDED, on_click=do_export)]),
            common.card(page, ft.Column(key="fn_led_list", spacing=4, controls=rows or [ft.Text(S("led_none", lang), size=13, color=secondary)]), padding=14),
        ]

    # ------------------------------------------------------------------ تنظیمات
    def pct(bp: int) -> str:
        return f"{bp / 100:g}"

    f = {
        "name": ft.TextField(key="fn_set_name", label=S("s_name", lang), width=260, border_radius=10, value=settings.invoice_seller_name),
        "legal": ft.TextField(key="fn_set_legal", label=S("s_legal", lang), width=260, border_radius=10, value=settings.invoice_seller_legal_name),
        "nid": ft.TextField(key="fn_set_nid", label=S("s_nid", lang), width=200, border_radius=10, value=settings.invoice_seller_national_id),
        "addr": ft.TextField(key="fn_set_addr", label=S("s_addr", lang), width=420, border_radius=10, value=settings.invoice_seller_address),
        "phone": ft.TextField(key="fn_set_phone", label=S("s_phone", lang), width=200, border_radius=10, value=settings.invoice_seller_phone),
        "logo": ft.TextField(key="fn_set_logo", label=S("s_logo", lang), width=420, border_radius=10, value=settings.invoice_logo_path),
        "color": ft.TextField(key="fn_set_color", label=S("s_color", lang), width=170, border_radius=10, value=settings.invoice_color),
        "footer": ft.TextField(key="fn_set_footer", label=S("s_footer", lang), width=420, border_radius=10, value=settings.invoice_footer),
        "vat": ft.Switch(key="fn_set_vat", label=S("s_vat", lang), value=settings.invoice_vat_enabled),
        "vat_rate": ft.TextField(key="fn_set_vat_rate", label=S("s_vat_rate", lang), width=150, border_radius=10, value=pct(settings.invoice_vat_rate_bp)),
        "prefix": ft.TextField(key="fn_set_prefix", label=S("s_prefix", lang), width=120, border_radius=10, value=settings.invoice_number_prefix),
        "start": ft.TextField(key="fn_set_start", label=S("s_start", lang), width=140, border_radius=10, value=str(settings.invoice_number_start)),
        "year": ft.Switch(key="fn_set_year", label=S("s_year", lang), value=settings.invoice_number_use_year),
        "paper": ft.Dropdown(key="fn_set_paper", label=S("s_paper", lang), width=120, border_radius=10, value=settings.invoice_paper, options=[ft.DropdownOption(key=k, text=k) for k in ("A4", "A5")]),
        "digits": ft.Dropdown(key="fn_set_digits", label=S("s_digits", lang), width=130, border_radius=10, value=settings.invoice_digits, options=[ft.DropdownOption(key=k, text=S(f"digits_{k}", lang)) for k in ("fa", "en")]),
        "auto": ft.Dropdown(key="fn_set_auto", label=S("s_auto", lang), width=240, border_radius=10, value=settings.invoice_auto_send, options=[ft.DropdownOption(key="off", text=S("auto_off", lang)), ft.DropdownOption(key="after_confirm", text=S("auto_on", lang))]),
        "owner": ft.Switch(key="fn_set_owner_copy", label=S("s_owner_copy", lang), value=settings.invoice_send_owner_copy),
        "fee_bale": ft.TextField(key="fn_set_fee_bale", label=S("s_fee_bale", lang), width=170, border_radius=10, value=pct(settings.finance_fee_bp_bale_pay)),
        "fee_zp": ft.TextField(key="fn_set_fee_zp", label=S("s_fee_zp", lang), width=170, border_radius=10, value=pct(settings.finance_fee_bp_zarinpal)),
        "unit": ft.Dropdown(key="fn_set_unit", label=S("s_unit", lang), width=140, border_radius=10, value=settings.finance_unit, options=[ft.DropdownOption(key=k, text=S(f"unit_{k}", lang)) for k in ("toman", "irr")]),
        "mgr": ft.Switch(key="fn_set_mgr", label=S("s_mgr", lang), value=settings.finance_manager_access),
    }

    def do_save(_e=None) -> None:
        vat_bp, bale_bp, zp_bp = parse_percent_bp(f["vat_rate"].value), parse_percent_bp(f["fee_bale"].value), parse_percent_bp(f["fee_zp"].value)
        start = jalali.en_digits(f["start"].value or "").strip()
        logo = (f["logo"].value or "").strip()
        checks = [
            (vat_bp is None or vat_bp == 0 and f["vat"].value, "s_vat_rate"), (bale_bp is None, "s_fee_bale"), (zp_bp is None, "s_fee_zp"),
            (not start.isdigit() or not 1 <= int(start) <= 10**9, "s_start"),
            (not re.fullmatch(r"#[0-9a-fA-F]{6}", (f["color"].value or "").strip()), "s_color"),
            (bool(logo) and not logo_ok(logo), "s_logo"),
        ]
        for bad, label in checks:
            if bad:
                say(S("bad", lang, label=S(label, lang)), False)
                return page.update()
        settings.invoice_seller_name, settings.invoice_seller_legal_name = fin.clean_text(f["name"].value, 80), fin.clean_text(f["legal"].value, 80)
        settings.invoice_seller_national_id, settings.invoice_seller_address = fin.clean_text(f["nid"].value, 20), fin.clean_text(f["addr"].value, 200)
        settings.invoice_seller_phone, settings.invoice_logo_path = fin.clean_text(f["phone"].value, 30), logo
        settings.invoice_color, settings.invoice_footer = f["color"].value.strip(), fin.clean_text(f["footer"].value, 200)
        settings.invoice_vat_enabled, settings.invoice_vat_rate_bp = bool(f["vat"].value), vat_bp or settings.invoice_vat_rate_bp
        settings.invoice_number_prefix = re.sub(r"[^A-Za-z0-9]", "", f["prefix"].value or "")[:6]
        settings.invoice_number_start, settings.invoice_number_use_year = int(start), bool(f["year"].value)
        settings.invoice_paper, settings.invoice_digits = f["paper"].value or "A4", f["digits"].value or "fa"
        settings.invoice_auto_send, settings.invoice_send_owner_copy = f["auto"].value or "off", bool(f["owner"].value)
        settings.finance_fee_bp_bale_pay, settings.finance_fee_bp_zarinpal = bale_bp, zp_bp
        settings.finance_unit, settings.finance_manager_access = f["unit"].value or "toman", bool(f["mgr"].value)
        save_settings(settings)
        say(S("saved", lang), True)
        render()

    def logo_ok(path: str) -> bool:
        from app.core.invoice_pdf import _load_logo

        return _load_logo(path) is not None

    def settings_tab() -> list:
        head = lambda key: ft.Text(S(key, lang), size=15, weight=ft.FontWeight.W_700)  # noqa: E731
        return [common.card(page, ft.Column(spacing=12, controls=[
            head("s_seller"), ft.Row(spacing=10, wrap=True, controls=[f["name"], f["legal"], f["nid"], f["phone"]]), f["addr"], f["logo"], ft.Row(spacing=10, wrap=True, controls=[f["color"], f["paper"], f["digits"]]), f["footer"],
            head("s_vat"), f["vat"], ft.Row(spacing=10, wrap=True, controls=[f["vat_rate"]]), ft.Text(S("s_vat_hint", lang), size=11.5, color=secondary),
            head("s_num"), ft.Row(spacing=10, wrap=True, controls=[f["prefix"], f["start"]]), f["year"],
            head("s_auto"), ft.Row(spacing=10, wrap=True, controls=[f["auto"]]), f["owner"],
            ft.Text(S("s_fees", lang), size=13, weight=ft.FontWeight.W_600), ft.Row(spacing=10, wrap=True, controls=[f["fee_bale"], f["fee_zp"]]),
            ft.Row(spacing=10, wrap=True, controls=[f["unit"]]), f["mgr"],
            ft.FilledButton(key="fn_set_save", content=S("save", lang), icon=ft.Icons.SAVE_ROUNDED, on_click=do_save),
        ]), padding=16)]

    # -------------------------------------------------------------------- قاب
    tabs = {"dash": dash, "inv": invoices_tab, "led": ledger_tab, "set": settings_tab}

    def render(update: bool = True) -> None:
        switcher = ft.Row(spacing=8, wrap=True, controls=[
            (ft.FilledButton if st["tab"] == k else ft.OutlinedButton)(key=f"fn_tab_{k}", content=S(f"tab_{k}", lang), on_click=lambda _e, kk=k: (st.update(tab=kk), render()))
            for k in tabs])
        body.controls = [switcher, notice, *tabs[st["tab"]]()]
        if update:
            page.update()

    render(update=False)
    return ft.Container(expand=True, padding=ft.Padding.symmetric(horizontal=32, vertical=24), content=ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=14, controls=[header, body]))
