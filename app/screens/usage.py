"""صفحه‌ی «مصرف و هزینه» (N1) + کنترل‌های بهینه‌سازیِ توکن (N18).

عددها از ردیف‌های واقعیِ ``ai_calls`` می‌آیند؛ هر جا سرویس شمارنده نفرستاده «تخمینی» نوشته می‌شود. قیمت‌ها را کاربر وارد می‌کند
(صفحه‌ی «ارائه‌دهنده‌های AI») و مدلِ بی‌قیمت جدا گزارش می‌شود؛ هیچ قیمتِ پیش‌فرضِ ساختگی نداریم.
"""

from __future__ import annotations

import time
from decimal import Decimal

import flet as ft

from app import theme
from app.core import ai_cache, ai_usage as u
from app.core.settings import save_settings
from app.screens import common

_S = {
    "title": ("مصرف و هزینه", "Usage & cost"),
    "subtitle": ("ببین هوش مصنوعی چقدر توکن و پول مصرف می‌کنه و چطور کم‌خرج‌ترش کنی.", "See how many tokens and how much money the AI uses, and how to cut it."),
    "today": ("امروز", "Today"), "d7": ("۷ روز", "7 days"), "d30": ("۳۰ روز", "30 days"), "all": ("کل", "All time"),
    "period_line": ("{calls} پاسخ · {tokens} توکن · هزینه: {cost}", "{calls} replies · {tokens} tokens · cost: {cost}"),
    "avg": ("میانگینِ هر پاسخ: {p} توکنِ ورودی + {c} توکنِ خروجی (۳۰ روزِ اخیر){est}", "Average per reply: {p} input + {c} output tokens (last 30 days){est}"),
    "est": (" — بخشی تخمینی", " — partly estimated"),
    "no_data": ("هنوز مصرفی ثبت نشده.", "No usage recorded yet."),
    "unpriced": ("⚠️ {n} توکن مالِ مدل‌هایی بود که قیمت نداری؛ در هزینه نیامده. قیمتشان را در «ارائه‌دهنده‌های AI» بنویس.", "⚠️ {n} tokens belong to models without a price and are not in the cost. Add prices under “AI providers”."),
    "calc": ("محاسبه‌گرِ هزینه", "Cost calculator"),
    "calc_reply": ("هر پاسخ (میانگین): {a} · هر ۱۰۰ پاسخ: {b}", "Per reply (avg): {a} · per 100 replies: {b}"),
    "calc_month": ("این ماه تا الان: {a} · پیش‌بینیِ پایانِ ماه: {b}", "This month so far: {a} · month-end forecast: {b}"),
    "budget_line": ("بودجه‌ی ماهانه: {limit} — مصرف‌شده: {spent}", "Monthly budget: {limit} — spent: {spent}"),
    "whatif": ("چه می‌شود اگر…", "What if…"),
    "wi_customers": ("مشتری در روز", "Customers per day"), "wi_questions": ("پرسش به‌ازای هر مشتری", "Questions per customer"),
    "wi_model": ("مدل", "Model"), "wi_calc": ("حساب کن", "Calculate"),
    "wi_result": ("هزینه‌ی تقریبیِ یک ماه: {c}", "Approx. cost for a month: {c}"),
    "wi_need_price": ("اول برای یک مدل قیمت وارد کن.", "Enter a price for a model first."),
    "wi_bad": ("عددها باید درست باشند.", "Numbers must be valid."),
    "top": ("پرمصرف‌ترین گفتگوها (۳۰ روز)", "Heaviest chats (30 days)"),
    "chart": ("توکنِ مصرفی در ۳۰ روزِ اخیر", "Tokens used in the last 30 days"),
    "breakdown": ("ورودیِ هر پاسخ از چه تشکیل شده؟ (میانگین، تخمینی)", "What makes up each reply's input? (average, estimated)"),
    "breakdown_line": ("پرامپت و قوانین: {s} · تاریخچه: {h} · پیامِ مشتری: {m}", "Prompt & rules: {s} · history: {h} · customer message: {m}"),
    "tip_history": ("💡 بیشترِ ورودی تاریخچه‌ی گفتگوست؛ «تعدادِ پیام‌های حافظه» را در تنظیمات کم کن.", "💡 Most input is chat history; lower the memory message count in settings."),
    "tip_prompt": ("💡 پرامپت بلنده؛ کوتاه‌ترش کن یا بخش‌های بی‌استفاده را بردار.", "💡 The prompt is long; shorten it or drop unused parts."),
    "saved": ("صرفه‌جویی (تخمینی): {t} توکن از کوتاه‌سازی/کش — کشِ پاسخ: {h} بار", "Savings (estimated): {t} tokens from trimming/caching — response cache hits: {h}"),
    "settings": ("هزینه و بودجه", "Cost & budget"),
    "rate": ("نرخِ دلار (تومان)", "USD rate (Toman)"),
    "unit": ("واحدِ نمایش", "Display unit"), "unit.usd": ("دلار", "USD"), "unit.toman": ("تومان", "Toman"), "unit.irr": ("ریال", "Rial"),
    "budget": ("بودجه‌ی ماهانه (دلار؛ خالی = بدونِ بودجه)", "Monthly budget (USD; empty = none)"),
    "action": ("وقتی بودجه تموم شد", "When the budget runs out"),
    "action.warn": ("فقط هشدار بده", "Only warn me"), "action.stop": ("AI رو قطع کن", "Stop the AI"), "action.local": ("برو سراغِ مدلِ محلی", "Switch to the local model"),
    "opt": ("بهینه‌سازیِ توکن", "Token optimization"),
    "opt_hist": ("پنجره‌ی هوشمندِ تاریخچه (پیشنهادی)", "Smart history window (recommended)"),
    "opt_max": ("سقفِ خروجی به‌تناسبِ پرسش (پیشنهادی)", "Output cap by question (recommended)"),
    "opt_cache": ("کشِ پاسخِ یکسان", "Identical-answer cache"),
    "opt_cache_hint": ("فقط پرسشِ اولِ گفتگو و بدونِ اطلاعاتِ شخصی؛ فقط در حافظه و با هر تغییرِ محصول/تنظیمات خودکار پاک می‌شود. پیش‌فرض خاموش.", "Only first-turn questions without personal data; in memory only and cleared on any product/settings change. Off by default."),
    "ttl": ("ماندگاریِ کش (دقیقه)", "Cache lifetime (minutes)"),
    "cache_stats": ("کش: {h} هیت · {m} میس · {t} توکن صرفه‌جویی", "Cache: {h} hits · {m} misses · {t} tokens saved"),
    "clear_cache": ("پاک‌کردنِ کش", "Clear cache"), "cleared": ("کش پاک شد.", "Cache cleared."),
    "save": ("ذخیره", "Save"), "saved_ok": ("✅ ذخیره شد.", "✅ Saved."), "bad": ("«{label}» درست نیست.", "“{label}” is not valid."),
}


def S(key: str, lang: str, **kw) -> str:
    fa, en = _S[key]
    text = en if lang == "en" else fa
    return text.format(**kw) if kw else text


def build(page: ft.Page, lang: str, settings, manager) -> ft.Control:
    secondary = theme.text_secondary(page)
    usage = manager.usage
    now = time.time()
    prices = u.model_prices(settings)
    day0 = int(now // 86400 * 86400)
    periods = [("today", day0), ("d7", day0 - 6 * 86400), ("d30", day0 - 29 * 86400), ("all", 0)]

    def money(usd: Decimal) -> str:
        return u.fmt_money(usd, settings)

    def n(x: int) -> str:
        return f"{int(x):,}"

    # ---- کارت‌های بازه
    cards = []
    unpriced_total = 0
    for key, since in periods:
        by_model = usage.by_model(since)
        t = usage.totals(since)
        cost, unpriced = u.cost_of(by_model, prices)
        if key == "all":
            unpriced_total = unpriced
        cards.append(common.card(page, ft.Column(spacing=4, controls=[
            ft.Text(S(key, lang), size=13, color=secondary),
            ft.Text(S("period_line", lang, calls=n(t.ok_calls), tokens=n(t.tokens), cost=money(cost)), size=13.5, weight=ft.FontWeight.W_600),
        ]), padding=12))
    act = usage.activity(day0 - 29 * 86400)
    t30 = usage.totals(day0 - 29 * 86400)
    avg_line = S("no_data", lang)
    if t30.ok_calls:
        avg_line = S("avg", lang, p=n(round(t30.prompt / t30.ok_calls)), c=n(round(t30.completion / t30.ok_calls)), est=S("est", lang) if act["estimated"] else "")

    # ---- محاسبه‌گر
    month_by_model = usage.by_model(u.month_start_ts(now))
    month_cost, _unp = u.cost_of(month_by_model, prices)
    avg_cost = Decimal(0)
    if t30.ok_calls:
        avg_cost = u.cost_of(usage.by_model(day0 - 29 * 86400), prices)[0] / t30.ok_calls
    calc_lines = [
        ft.Text(S("calc_reply", lang, a=money(avg_cost), b=money(avg_cost * 100)), size=13),
        ft.Text(S("calc_month", lang, a=money(month_cost), b=money(u.forecast_month(month_cost, now))), size=13),
    ]
    limit = u.dec(settings.ai_budget_monthly_usd)
    if limit > 0:
        calc_lines.append(ft.Text(S("budget_line", lang, limit=money(limit), spent=money(month_cost)), size=13, color=theme.DANGER if month_cost >= limit else secondary))

    # ---- چه می‌شود اگر
    wi_customers = ft.TextField(key="us_wi_customers", label=S("wi_customers", lang), width=150, border_radius=10,
                                value=str(max(1, round(act["chats"] / 30))) if act["chats"] else "50")
    wi_questions = ft.TextField(key="us_wi_questions", label=S("wi_questions", lang), width=170, border_radius=10,
                                value=str(max(1, round(act["calls"] / max(1, act["chats"])))) if act["chats"] else "3")
    priced = [(k, v) for k, v in prices.items()]
    wi_model = ft.Dropdown(key="us_wi_model", label=S("wi_model", lang), width=220, border_radius=10, value=(f"{priced[0][0][0]}/{priced[0][0][1]}" if priced else None),
                           options=[ft.DropdownOption(key=f"{k[0]}/{k[1]}", text=k[1]) for k, _v in priced])
    wi_out = ft.Text("", key="us_wi_result", size=13.5, weight=ft.FontWeight.W_600)

    def on_whatif(_e=None) -> None:
        try:
            cust, qs = int(str(wi_customers.value).strip()), int(str(wi_questions.value).strip())
            assert 0 < cust <= 1_000_000 and 0 < qs <= 10_000
        except (ValueError, AssertionError):
            wi_out.value, wi_out.color = S("wi_bad", lang), theme.DANGER
            page.update()
            return
        key = tuple((wi_model.value or "").split("/", 1))
        price = prices.get(key) if len(key) == 2 else None
        if price is None:
            wi_out.value, wi_out.color = S("wi_need_price", lang), theme.DANGER
        else:
            avg = (round(t30.prompt / t30.ok_calls), round(t30.completion / t30.ok_calls)) if t30.ok_calls else (1500, 300)
            wi_out.value, wi_out.color = S("wi_result", lang, c=money(u.what_if(cust, qs, avg, price))), theme.PRIMARY
        page.update()

    # ---- نمودار و پرمصرف‌ها
    daily = usage.daily(30)
    peak = max((t for _d, _c, t in daily), default=0) or 1
    chart = ft.Row(key="us_chart", spacing=2, vertical_alignment=ft.CrossAxisAlignment.END, height=90,
                   controls=[ft.Container(width=8, height=max(2, int(86 * t / peak)), bgcolor=theme.PRIMARY if t else theme.border_color(page), border_radius=2, tooltip=f"{d}: {n(t)}") for d, _c, t in daily])
    tops = usage.top_chats(day0 - 29 * 86400, 5)
    top_col = ft.Column(spacing=2, controls=[ft.Text(f"{p}:{c} — {n(k)} پاسخ · {n(t)} توکن" if lang != "en" else f"{p}:{c} — {n(k)} replies · {n(t)} tokens", size=12.5, color=secondary) for p, c, k, t in tops]
                        or [ft.Text(S("no_data", lang), size=12.5, color=secondary)])
    bd = usage.input_breakdown(day0 - 29 * 86400)
    tips = []
    total_in = (bd["system"] + bd["history"] + bd["message"]) or 1
    if bd["calls"] and bd["history"] / total_in > 0.5:
        tips.append(S("tip_history", lang))
    if bd["calls"] and bd["system"] / total_in > 0.4:
        tips.append(S("tip_prompt", lang))
    hits, saved_cache = usage.cache_hits(0)
    saved_total = usage.totals(0).saved

    # ---- تنظیمات
    notice = ft.Text("", key="us_notice", size=12.5, visible=False)
    rate_tf = ft.TextField(key="us_rate", label=S("rate", lang), width=180, border_radius=10, value=settings.usd_to_irr_rate or "")
    unit_dd = ft.Dropdown(key="us_unit", label=S("unit", lang), width=150, border_radius=10, value=settings.cost_display_unit or "usd",
                          options=[ft.DropdownOption(key=k, text=S(f"unit.{k}", lang)) for k in ("usd", "toman", "irr")])
    budget_tf = ft.TextField(key="us_budget", label=S("budget", lang), width=260, border_radius=10, value=settings.ai_budget_monthly_usd or "")
    action_dd = ft.Dropdown(key="us_action", label=S("action", lang), width=240, border_radius=10, value=settings.ai_budget_action or "warn",
                            options=[ft.DropdownOption(key=k, text=S(f"action.{k}", lang)) for k in ("warn", "stop", "local")])
    hist_sw = ft.Switch(key="us_opt_history", label=S("opt_hist", lang), value=settings.token_opt_history_window)
    max_sw = ft.Switch(key="us_opt_max", label=S("opt_max", lang), value=settings.token_opt_max_tokens)
    cache_sw = ft.Switch(key="us_opt_cache", label=S("opt_cache", lang), value=settings.token_opt_response_cache)
    ttl_tf = ft.TextField(key="us_ttl", label=S("ttl", lang), width=170, border_radius=10, value=str(settings.token_opt_cache_ttl_minutes))
    cache_stat = ft.Text("", key="us_cache_stats", size=12, color=secondary)

    def refresh_cache_stat() -> None:
        st = ai_cache.CACHE.stats()
        cache_stat.value = S("cache_stats", lang, h=st["hits"], m=st["misses"], t=n(st["tokens_saved"]))

    def show(text: str, ok: bool = True) -> None:
        notice.value, notice.color, notice.visible = text, theme.SUCCESS if ok else theme.DANGER, bool(text)

    def on_save(_e=None) -> None:
        rate, budget = (rate_tf.value or "").strip(), (budget_tf.value or "").strip()
        if rate and u.dec(rate) <= 0:
            show(S("bad", lang, label=S("rate", lang)), False)
        elif budget and u.dec(budget) <= 0:
            show(S("bad", lang, label=S("budget", lang)), False)
        else:
            try:
                ttl = int(str(ttl_tf.value).strip())
                assert 1 <= ttl <= 1440
            except (ValueError, AssertionError):
                show(S("bad", lang, label=S("ttl", lang)), False)
                page.update()
                return
            settings.usd_to_irr_rate, settings.cost_display_unit = rate, unit_dd.value or "usd"
            settings.ai_budget_monthly_usd, settings.ai_budget_action = budget, action_dd.value or "warn"
            settings.token_opt_history_window, settings.token_opt_max_tokens = bool(hist_sw.value), bool(max_sw.value)
            settings.token_opt_response_cache, settings.token_opt_cache_ttl_minutes = bool(cache_sw.value), ttl
            ai_cache.invalidate_all()  # تغییرِ تنظیمات ⇒ کش خالی
            save_settings(settings)
            show(S("saved_ok", lang), True)
        page.update()

    def on_clear(_e=None) -> None:
        ai_cache.invalidate_all()
        refresh_cache_stat()
        show(S("cleared", lang), True)
        page.update()

    refresh_cache_stat()
    head = lambda key: ft.Text(S(key, lang), size=15, weight=ft.FontWeight.W_700)  # noqa: E731
    body = [
        common.page_header(page, ft.Icons.INSIGHTS_ROUNDED, S("title", lang), S("subtitle", lang)),
        ft.Row(spacing=10, wrap=True, controls=cards),
        ft.Text(avg_line, key="us_avg", size=13, color=secondary),
        *([ft.Text(S("unpriced", lang, n=n(unpriced_total)), key="us_unpriced", size=12.5, color=theme.DANGER)] if unpriced_total else []),
        common.card(page, ft.Column(spacing=8, controls=[head("calc"), *calc_lines]), padding=14),
        common.card(page, ft.Column(spacing=10, controls=[head("whatif"), ft.Row(spacing=10, wrap=True, controls=[wi_customers, wi_questions, wi_model, ft.FilledButton(key="us_wi_calc", content=S("wi_calc", lang), on_click=on_whatif)]), wi_out]), padding=14),
        common.card(page, ft.Column(spacing=8, controls=[head("chart"), chart]), padding=14),
        common.card(page, ft.Column(spacing=6, controls=[head("top"), top_col]), padding=14),
        common.card(page, ft.Column(spacing=6, controls=[head("breakdown"),
                    ft.Text(S("breakdown_line", lang, s=n(bd["system"]), h=n(bd["history"]), m=n(bd["message"])) if bd["calls"] else S("no_data", lang), size=13),
                    *[ft.Text(tip, size=12.5, color=theme.ACCENT_DARK) for tip in tips],
                    ft.Text(S("saved", lang, t=n(saved_total), h=n(hits)), key="us_saved", size=12.5, color=secondary)]), padding=14),
        common.card(page, ft.Column(spacing=12, controls=[
            head("settings"),
            ft.Row(spacing=10, wrap=True, controls=[rate_tf, unit_dd, budget_tf, action_dd]),
            head("opt"), hist_sw, max_sw, cache_sw, ft.Text(S("opt_cache_hint", lang), size=11.5, color=secondary),
            ft.Row(spacing=10, wrap=True, controls=[ttl_tf, ft.TextButton(key="us_clear_cache", content=S("clear_cache", lang), icon=ft.Icons.CLEANING_SERVICES_ROUNDED, on_click=on_clear)]),
            cache_stat,
            ft.FilledButton(key="us_save", content=S("save", lang), icon=ft.Icons.SAVE_ROUNDED, on_click=on_save), notice,
        ]), padding=14),
    ]
    return ft.Container(expand=True, padding=ft.Padding.symmetric(horizontal=32, vertical=24), content=ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=14, controls=body))
