"""صفحه‌ی «مصرفِ هوش مصنوعی» — فقط محلی: شمارشِ پیام/توکن، زمانِ پاسخ، سقف‌هایِ روزانه و کلیدِ خاموشی.

در نسخه‌ی ۱.۰.۰ خبری از دلار/تومان/نرخِ ارز/بودجه نیست — مدل محلی پولی مصرف نمی‌کند؛
مصرفِ واقعیِ فروشنده **زمانِ CPU** است، پس این صفحه می‌گوید هر پاسخ چقدر طول می‌کشد،
هر ۱۰۰۰ توکن رویِ همین سیستم چنده، و امروز چند پیام به مدل داده‌ای نسبت به سقف‌ها.
عددها از ردیف‌های واقعیِ ``ai_calls`` می‌آیند؛ هر جا شمارنده نباشد «تخمینی» نوشته می‌شود.
"""

from __future__ import annotations

import time

import flet as ft

from app import theme
from app.core.settings import save_settings
from app.screens import common

_S = {
    "title": ("مصرفِ هوش مصنوعی", "AI usage"),
    "subtitle": ("هوش مصنوعیِ محلی پولی مصرف نمی‌کند؛ اینجا ببین چقدر توکن و چقدر زمانِ پردازنده می‌خواد.", "A local AI costs no money — see here how many tokens and how much CPU time it uses."),
    "today": ("امروز", "Today"), "d7": ("۷ روز", "7 days"), "d30": ("۳۰ روز", "30 days"), "all": ("کل", "All time"),
    "period_line": ("{calls} پاسخ · {tokens} توکن", "{calls} replies · {tokens} tokens"),
    "avg": ("میانگینِ هر پاسخ: {p} توکنِ ورودی + {c} توکنِ خروجی (۳۰ روزِ اخیر){est}", "Per reply average: {p} input + {c} output tokens (last 30 days){est}"),
    "est": (" — بخشی تخمینی", " — partly estimated"),
    "no_data": ("هنوز مصرفی ثبت نشده.", "No usage recorded yet."),
    "speed_title": ("سرعت رویِ سیستمِ تو", "Speed on your machine"),
    "speed_line": ("میانگینِ هر پاسخ {ms} میلی‌ثانیه · هر ۱٬۰۰۰ توکن ≈ {sec} ثانیه", "Each reply takes {ms} ms on average · each 1,000 tokens ≈ {sec} s"),
    "speed_none": ("برایِ محاسبه‌ی سرعت حداقل به چند پاسخِ ثبت‌شده نیاز است.", "Speed needs at least a few recorded replies."),
    "today_time": ("پردازشِ امروز: حدود {mins} دقیقه", "CPU time spent today: about {mins} min"),
    "caps_title": ("سقف‌ها و کنترل", "Caps & control"),
    "caps_line": ("امروز {used} پاسخ از سقفِ روزانه‌ی {cap}", "Today: {used} replies of the daily cap {cap}"),
    "caps_line_none": ("امروز {used} پاسخ — سقفِ روزانه‌ای تنظیم نشده (۰ = بدونِ سقف).", "Today: {used} replies — no daily cap set (0 = unlimited)."),
    "kill_on": ("🛑 کلیدِ خاموشیِ اضطراری روشن است — ربات الان با هوش مصنوعی جواب نمی‌دهد.", "🛑 The emergency kill switch is ON — the bot is not answering with AI right now."),
    "cap_chat": ("سقفِ پاسخ به هر مشتری در روز", "Replies per customer per day"),
    "cap_total": ("سقفِ کلِ پاسخ‌ها در روز", "Total replies per day"),
    "kill": ("خاموش‌کردنِ اضطراریِ همه‌ی پاسخ‌های AI", "Emergency stop for all AI replies"),
    "opt": ("کم‌تر‌کارکردنِ زمان (بهینه‌سازیِ توکن)", "Making replies faster (token optimization)"),
    "opt_hist": ("پنجره‌ی هوشمندِ تاریخچه (پیشنهادی)", "Smart history window (recommended)"),
    "opt_max": ("سقفِ خروجی به‌تناسبِ پرسش (پیشنهادی)", "Output cap by question (recommended)"),
    "chart": ("توکنِ مصرفی در ۳۰ روزِ اخیر", "Tokens used in the last 30 days"),
    "top": ("پرمصرف‌ترین گفتگوها (۳۰ روز)", "Heaviest chats (30 days)"),
    "top_line": ("{p}:{c} — {k} پاسخ · {t} توکن", "{p}:{c} — {k} replies · {t} tokens"),
    "breakdown": ("ورودیِ هر پاسخ از چه تشکیل شده؟ (میانگین، تخمینی)", "What makes up each reply's input? (average, estimated)"),
    "breakdown_line": ("پرامپت و قوانین: {s} · تاریخچه: {h} · پیامِ مشتری: {m}", "Prompt & rules: {s} · history: {h} · customer message: {m}"),
    "tip_history": ("💡 بیشترِ ورودی تاریخچه‌ی گفتگوست؛ «چند پیام اخیر به خاطر بسپاره» را کم کن.", "💡 Most input is chat history; lower the remembered-message count."),
    "tip_prompt": ("💡 پرامپت بلنده؛ کوتاه‌ترش کن یا بخش‌های بی‌استفاده را بردار — هر توکنِ اضافه یعنی زمانِ بیشتر.", "💡 The prompt is long; shorten it or drop unused parts — every extra token costs time."),
    "save": ("ذخیره", "Save"), "saved_ok": ("✅ ذخیره شد.", "✅ Saved."), "bad": ("«{label}» باید عددِ معتبر باشد.", "“{label}” must be a valid number."),
}


def S(key: str, lang: str, **kw) -> str:
    fa, en = _S[key]
    text = en if lang == "en" else fa
    return text.format(**kw) if kw else text


def build(page: ft.Page, lang: str, settings, manager) -> ft.Control:
    secondary = theme.text_secondary(page)
    usage = manager.usage
    now = time.time()
    day0 = int(now // 86400 * 86400)
    periods = [("today", day0), ("d7", day0 - 6 * 86400), ("d30", day0 - 29 * 86400), ("all", 0)]

    def n(x: int) -> str:
        return f"{int(x):,}"

    # ---- کارت‌های بازه (بدونِ هیچ پولی)
    cards = []
    for key, since in periods:
        t_ = usage.totals(since)
        cards.append(ft.Container(
            key=f"us_{key}",
            padding=12, border_radius=12, width=210,
            border=ft.Border.all(1, theme.border_color(page)),
            content=ft.Column(spacing=4, controls=[
                ft.Text(S(key, lang), size=12.5, color=secondary),
                ft.Text(S("period_line", lang, calls=n(t_.ok_calls), tokens=n(t_.tokens)), size=13, weight=ft.FontWeight.W_600),
            ]),
        ))
    t30 = usage.totals(day0 - 29 * 86400)
    act = usage.activity(day0 - 29 * 86400)
    today = usage.totals(day0)
    avg_line = S("no_data", lang)
    if t30.ok_calls:
        avg_line = S("avg", lang, p=n(round(t30.prompt / t30.ok_calls)), c=n(round(t30.completion / t30.ok_calls)),
                     est=S("est", lang) if act["estimated"] else "")

    # ---- سرعت: زمانِ هر پاسخ و «هر ۱۰۰۰ توکن چنده» روی همین سیستم
    avg_ms = usage.avg_latency_ms(day0 - 29 * 86400)
    avg_tokens = round((t30.prompt + t30.completion) / t30.ok_calls) if t30.ok_calls else 0
    speed_lines = []
    if avg_ms and avg_tokens:
        secs_per_1k = avg_ms / avg_tokens  # میلی‌ثانیه به‌ازای توکن == ثانیه به‌ازای ۱۰۰۰ توکن
        speed_lines.append(S("speed_line", lang, ms=n(avg_ms), sec=f"{secs_per_1k:.1f}"))
        ms_per_token = avg_ms / avg_tokens
        if today.tokens:
            speed_lines.append(S("today_time", lang, mins=f"{today.tokens * ms_per_token / 60000:.1f}"))
    else:
        speed_lines.append(S("speed_none", lang))

    # ---- سقف‌های امروز
    cap_total = int(getattr(settings, "max_ai_messages_per_day_total", 0) or 0)
    if cap_total:
        caps_line = S("caps_line", lang, used=n(today.ok_calls), cap=n(cap_total))
    else:
        caps_line = S("caps_line_none", lang, used=n(today.ok_calls))

    # ---- نمودار و پرمصرف‌ها
    daily = usage.daily(30)
    peak = max((tk for _d, _c, tk in daily), default=0) or 1
    chart = ft.Row(key="us_chart", spacing=2, vertical_alignment=ft.CrossAxisAlignment.END, height=90,
                   controls=[ft.Container(width=8, height=max(2, int(86 * tk / peak)), bgcolor=theme.PRIMARY if tk else theme.border_color(page),
                                          border_radius=2, tooltip=f"{d}: {n(tk)}") for d, _c, tk in daily])
    tops = usage.top_chats(day0 - 29 * 86400, 5)
    top_col = ft.Column(spacing=2, controls=[ft.Text(S("top_line", lang, p=p, c=c, k=n(k), t=n(tk)), size=12.5, color=secondary)
                                             for p, c, k, tk in tops]
                        or [ft.Text(S("no_data", lang), size=12.5, color=secondary)])
    bd = usage.input_breakdown(day0 - 29 * 86400)
    tips = []
    total_in = (bd["system"] + bd["history"] + bd["message"]) or 1
    if bd["calls"] and bd["history"] / total_in > 0.5:
        tips.append(S("tip_history", lang))
    if bd["calls"] and bd["system"] / total_in > 0.4:
        tips.append(S("tip_prompt", lang))

    # ---- کنترل‌ها (سقف‌ها + کلیدِ خاموشی + بهینه‌سازیِ توکن)
    notice = ft.Text("", key="us_notice", size=12.5, visible=False)
    cap_chat_tf = ft.TextField(key="us_cap_chat", label=S("cap_chat", lang), width=230, border_radius=10,
                               value=str(int(getattr(settings, "max_ai_messages_per_chat_per_day", 0) or 0)))
    cap_total_tf = ft.TextField(key="us_cap_total", label=S("cap_total", lang), width=230, border_radius=10,
                                value=str(cap_total))
    kill_sw = ft.Switch(key="us_kill", label=S("kill", lang), value=bool(getattr(settings, "ai_kill_switch", False)))
    hist_sw = ft.Switch(key="us_opt_history", label=S("opt_hist", lang), value=bool(getattr(settings, "token_opt_history_window", True)))
    max_sw = ft.Switch(key="us_opt_max", label=S("opt_max", lang), value=bool(getattr(settings, "token_opt_max_tokens", True)))

    def show(text: str, ok: bool) -> None:
        notice.value, notice.color, notice.visible = text, theme.SUCCESS if ok else theme.DANGER, bool(text)

    def on_save(_e=None) -> None:
        for field, label, hi in ((cap_chat_tf, S("cap_chat", lang), 1_000_000), (cap_total_tf, S("cap_total", lang), 10_000_000)):
            raw = (field.value or "").strip()
            if not raw.isdigit() or int(raw) > hi:
                show(S("bad", lang, label=label), False)
                page.update()
                return
        settings.max_ai_messages_per_chat_per_day = int((cap_chat_tf.value or "0").strip())
        settings.max_ai_messages_per_day_total = int((cap_total_tf.value or "0").strip())
        settings.ai_kill_switch = bool(kill_sw.value)
        settings.token_opt_history_window = bool(hist_sw.value)
        settings.token_opt_max_tokens = bool(max_sw.value)
        save_settings(settings)
        kill_banner.value = S("kill_on", lang) if settings.ai_kill_switch else ""
        kill_banner.visible = bool(settings.ai_kill_switch)
        cap_status.value = (S("caps_line", lang, used=n(today.ok_calls), cap=n(settings.max_ai_messages_per_day_total))
                            if settings.max_ai_messages_per_day_total else S("caps_line_none", lang, used=n(today.ok_calls)))
        show(S("saved_ok", lang), True)
        page.update()

    kill_banner = ft.Text("", key="us_kill_banner", size=13, color=theme.DANGER,
                          visible=bool(getattr(settings, "ai_kill_switch", False)))
    kill_banner.value = S("kill_on", lang) if getattr(settings, "ai_kill_switch", False) else ""
    cap_status = ft.Text(caps_line, key="us_caps_status", size=13, weight=ft.FontWeight.W_600)
    head = lambda key: ft.Text(S(key, lang), size=15, weight=ft.FontWeight.W_700)  # noqa: E731

    body = [
        common.page_header(page, ft.Icons.INSIGHTS_ROUNDED, S("title", lang), S("subtitle", lang)),
        kill_banner,
        ft.Row(spacing=10, wrap=True, controls=cards),
        ft.Text(avg_line, key="us_avg", size=13, color=secondary),
        ft.Text(caps_line, size=13, color=secondary),
        common.card(page, ft.Column(spacing=8, controls=[head("speed_title"), cap_status,
                                                          *[ft.Text(line, size=13) for line in speed_lines]]), padding=14),
        common.card(page, ft.Column(spacing=8, controls=[head("chart"), chart]), padding=14),
        common.card(page, ft.Column(spacing=6, controls=[head("top"), top_col]), padding=14),
        common.card(page, ft.Column(spacing=6, controls=[head("breakdown"),
                    ft.Text(S("breakdown_line", lang, s=n(bd["system"]), h=n(bd["history"]), m=n(bd["message"])) if bd["calls"] else S("no_data", lang), size=13),
                    *[ft.Text(tip, size=12.5, color=theme.INFO) for tip in tips]]), padding=14),
        common.card(page, ft.Column(spacing=10, controls=[
            head("caps_title"),
            ft.Row(spacing=10, wrap=True, controls=[cap_chat_tf, cap_total_tf]),
            kill_sw, head("opt"), hist_sw, max_sw,
            common.primary(S("save", lang), key="us_save", icon=ft.Icons.SAVE_ROUNDED, on_click=on_save), notice,
        ]), padding=14),
    ]
    return ft.Container(expand=True, padding=ft.Padding.symmetric(horizontal=32, vertical=24),
                        content=ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=14, controls=body))
