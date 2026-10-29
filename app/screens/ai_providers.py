"""صفحه‌ی «ارائه‌دهنده‌های AI» (N16): چند API، چند مدل، ترتیبِ زنجیره، تست، وضعیتِ زنده و تاریخچه‌ی جابه‌جایی.

ترتیبِ کارت‌ها = ترتیبِ زنجیره (اولی «اصلی»). کلیدها رمزنگاری می‌شن و هرگز نمایش داده نمی‌شن. قیمتِ مدل‌ها را خودت وارد می‌کنی (دلار به‌ازای ۱ میلیون توکن)؛
آدرس‌های پیش‌تنظیم فقط «مثال»‌اند و بدونِ قیمت — با مستنداتِ سرویس‌دهنده‌ات تطبیق بده.
"""

from __future__ import annotations

import time

import flet as ft

from app import theme
from app.core import ai_providers as ap
from app.core import crypto
from app.core.settings import save_settings
from app.screens import common

PRESETS = (
    ("openai", "OpenAI", "https://api.openai.com/v1"),
    ("openrouter", "OpenRouter", "https://openrouter.ai/api/v1"),
    ("groq", "Groq", "https://api.groq.com/openai/v1"),
    ("together", "Together AI", "https://api.together.xyz/v1"),
    ("deepseek", "DeepSeek", "https://api.deepseek.com/v1"),
    ("ollama", "Ollama (محلی/local)", "http://localhost:11434/v1"),
)
_S = {
    "title": ("ارائه‌دهنده‌های AI", "AI providers"),
    "subtitle": ("چند API و مدل ذخیره کن؛ اگه یکی از کار افتاد، ربات خودکار سراغِ بعدی می‌ره و حافظه‌ی گفتگو از دست نمی‌ره.", "Save several APIs and models; if one fails the bot switches automatically and keeps the conversation memory."),
    "chain_note": ("ترتیبِ زنجیره: از بالا به پایین؛ اولی «اصلی»ه و هر پاسخ از اون شروع می‌شه.", "Chain order: top to bottom; the first is primary and every reply starts there."),
    "empty": ("هنوز ارائه‌دهنده‌ای اضافه نکرده‌ای.", "No providers yet."),
    "legacy": ("API فعلیِ تو (تنظیماتِ قدیمی) هنوز به‌عنوان ارائه‌دهنده‌ی ۱ کار می‌کنه. برای ویرایشِ چند مدل، تبدیلش کن.", "Your current API (old settings) works as provider 1. Convert it to edit several models."),
    "migrate": ("تبدیل به ارائه‌دهنده‌ی ۱", "Convert to provider 1"),
    "primary": ("اصلی", "Primary"), "backup": ("پشتیبان", "Backup"),
    "st.ok": ("سالم", "Healthy"), "st.slow": ("کند", "Slow"), "st.down": ("قطع", "Down"), "st.disabled": ("غیرفعال", "Disabled"),
    "enabled": ("فعال", "Enabled"), "delete": ("حذف", "Delete"), "sure": ("مطمئنی؟ دوباره بزن", "Sure? Tap again"),
    "test": ("تست", "Test"), "test_ok": ("✅ {ms} میلی‌ثانیه · {tok} توکن · ابزار: {tools}", "✅ {ms} ms · {tok} tokens · tools: {tools}"),
    "tools_yes": ("پشتیبانی می‌شه", "supported"), "tools_no": ("نه", "no"), "tools_unknown": ("نامشخص", "unknown"),
    "test_fail": ("❌ {err}", "❌ {err}"),
    "price_in": ("قیمتِ ورودی ($/۱M)", "Input price ($/1M)"), "price_out": ("قیمتِ خروجی ($/۱M)", "Output price ($/1M)"), "ctx": ("حداکثرِ context", "Max context"),
    "add_model": ("نامِ مدلِ جدید", "New model name"), "add_model_btn": ("افزودنِ مدل", "Add model"),
    "new": ("ارائه‌دهنده‌ی جدید", "New provider"), "preset": ("مثال (آدرسِ رایج)", "Example (common URL)"),
    "name": ("نام", "Name"), "url": ("آدرس (https://…/v1)", "Address (https://…/v1)"), "key": ("کلیدِ API", "API key"),
    "models": ("مدل‌ها (با ویرگول جدا کن؛ اولی اصلی)", "Models (comma-separated; first is primary)"), "timeout": ("زمانِ هر تلاش (ثانیه، اختیاری)", "Per-try timeout (s, optional)"),
    "add": ("افزودن", "Add"), "added": ("✅ ارائه‌دهنده اضافه شد.", "✅ Provider added."),
    "need_models": ("حداقل یک نامِ مدل بنویس.", "Write at least one model name."), "need_key": ("کلیدِ API لازمه (برای موتورِ محلی هر چیزی بنویس).", "An API key is required (anything for local engines)."),
    "chain": ("تنظیماتِ جابه‌جایی", "Failover settings"), "attempt": ("زمانِ هر تلاش (ثانیه)", "Per-try timeout (s)"), "total": ("زمانِ کلِ پاسخ (ثانیه)", "Total time per reply (s)"),
    "targets": ("حداکثرِ هدف برای هر پاسخ", "Max targets per reply"), "conc": ("درخواستِ هم‌زمان به‌ازای هر API", "Concurrent requests per API"),
    "local": ("مدلِ محلی آخرین پناه باشد (اگه دانلود شده)", "Local model as last resort (if downloaded)"),
    "save": ("ذخیره", "Save"), "saved": ("✅ ذخیره شد.", "✅ Saved."), "bad": ("«{label}» درست نیست.", "“{label}” is not valid."),
    "history": ("۲۰ جابه‌جاییِ آخر", "Last 20 switches"), "history_empty": ("هنوز جابه‌جایی‌ای رخ نداده.", "No switches yet."),
    "hist_line": ("{t} — {frm} ← {to} ({why})", "{t} — {frm} → {to} ({why})"), "hist_none": ("هیچ‌کدام", "none"),
    "up": ("بالا", "Up"), "down": ("پایین", "Down"),
}


def S(key: str, lang: str, **kw) -> str:
    fa, en = _S[key]
    text = en if lang == "en" else fa
    return text.format(**kw) if kw else text


def build(page: ft.Page, lang: str, settings, on_change=None) -> ft.Control:
    secondary = theme.text_secondary(page)
    ui = {"armed": None}
    list_col = ft.Column(key="ap_list", spacing=12)
    hist_col = ft.Column(key="ap_history", spacing=2)
    notice = ft.Text("", key="ap_notice", size=12.5, visible=False)
    banner = ft.Column(key="ap_banner", spacing=6)

    def show(text: str, ok: bool = True) -> None:
        notice.value, notice.color, notice.visible = text, theme.SUCCESS if ok else theme.DANGER, bool(text)

    def commit(rerender: bool = True) -> None:
        save_settings(settings)
        if on_change:
            on_change()
        if rerender:
            render()
        page.update()

    def pdict(pid: str):
        return next((p for p in settings.ai_providers if p.get("id") == pid), None)

    def swap(seq: list, i: int, j: int) -> None:
        if 0 <= i < len(seq) and 0 <= j < len(seq):
            seq[i], seq[j] = seq[j], seq[i]

    def target_of(p: dict, m: dict) -> ap.Target:
        cfg = next((c for c in ap.parse_providers(settings) if c.id == p["id"]), None)
        mc = next((x for x in (cfg.models if cfg else []) if x.name == m["name"]), ap.ModelCfg(m["name"]))
        return ap.Target(cfg or ap.ProviderCfg(p["id"], p.get("name", ""), base_url=p.get("base_url", "")), mc)

    # ---- کارِ هر کارت
    def move_provider(pid: str, delta: int) -> None:
        i = next(k for k, p in enumerate(settings.ai_providers) if p["id"] == pid)
        swap(settings.ai_providers, i, i + delta)
        commit()

    def toggle_provider(pid: str, value: bool) -> None:
        pdict(pid)["enabled"] = value
        commit()

    def delete_provider(pid: str) -> None:
        if ui["armed"] != ("p", pid):
            ui["armed"] = ("p", pid)
            render()
            page.update()
            return
        ui["armed"] = None
        settings.ai_providers = [p for p in settings.ai_providers if p["id"] != pid]
        commit()

    def move_model(pid: str, name: str, delta: int) -> None:
        models = pdict(pid)["models"]
        i = next(k for k, m in enumerate(models) if m["name"] == name)
        swap(models, i, i + delta)
        commit()

    def toggle_model(pid: str, name: str, value: bool) -> None:
        for m in pdict(pid)["models"]:
            if m["name"] == name:
                m["enabled"] = value
        commit()

    def delete_model(pid: str, name: str) -> None:
        if ui["armed"] != ("m", pid, name):
            ui["armed"] = ("m", pid, name)
            render()
            page.update()
            return
        ui["armed"] = None
        p = pdict(pid)
        p["models"] = [m for m in p["models"] if m["name"] != name]
        commit()

    def edit_model(pid: str, name: str, field: str, raw: str) -> None:
        for m in pdict(pid)["models"]:
            if m["name"] == name:
                if field == "max_context_tokens":
                    m[field] = int(raw) if raw.strip().isdigit() else 0
                else:
                    m[field] = raw.strip()
        save_settings(settings)

    def add_model(pid: str, field: ft.TextField) -> None:
        name = (field.value or "").strip()
        p = pdict(pid)
        if name and all(m["name"] != name for m in p["models"]):
            p["models"].append({"name": name, "enabled": True, "max_context_tokens": 0, "tools_supported": None, "price_in": "", "price_out": ""})
            commit()

    def run_test(pid: str, name: str, out: ft.Text) -> None:
        p = pdict(pid)
        m = next(x for x in p["models"] if x["name"] == name)
        t = target_of(p, m)
        out.value, out.color = "…", secondary
        page.update()

        def worker() -> None:
            res = ap.test_target(t.provider, t.model, timeout=float(settings.ai_attempt_timeout or 15))
            if res["ok"]:
                tools = {True: S("tools_yes", lang), False: S("tools_no", lang), None: S("tools_unknown", lang)}[res["tools_supported"]]
                out.value, out.color = S("test_ok", lang, ms=res["latency_ms"], tok=res["tokens"], tools=tools), theme.SUCCESS
                if res["tools_supported"] is not None:
                    m["tools_supported"] = res["tools_supported"]
                    save_settings(settings)
            else:
                out.value, out.color = S("test_fail", lang, err=res["error"]), theme.DANGER
            page.update()

        page.run_thread(worker)

    # ---- نمایش
    def badge(t: ap.Target) -> ft.Control:
        state, why = ap.HEALTH.status(t, float(settings.ai_attempt_timeout or 15))
        color = {"ok": theme.SUCCESS, "slow": theme.ACCENT_DARK, "down": theme.DANGER, "disabled": secondary}[state]
        return ft.Text(S(f"st.{state}", lang) + (f" — {why}" if why else ""), size=12, color=color)

    def render() -> None:
        banner.controls = []
        if not settings.ai_providers and ap.parse_providers(settings):
            banner.controls = [ft.Text(S("legacy", lang), size=12.5, color=secondary),
                               ft.FilledButton(key="ap_migrate", content=S("migrate", lang), on_click=migrate)]
        cards = []
        for idx, p in enumerate(settings.ai_providers):
            pid = p["id"]
            rows = []
            for mi, m in enumerate(p.get("models", [])):
                t = target_of(p, m)
                name = m["name"]
                out = ft.Text("", key=f"ap_testout_{pid}_{mi}", size=12, selectable=True)
                armed = ui["armed"] == ("m", pid, name)
                rows.append(ft.Column(spacing=4, controls=[
                    ft.Row(spacing=8, wrap=True, controls=[
                        ft.Text(f"{mi + 1}. {name}", size=13.5, weight=ft.FontWeight.W_600), badge(t),
                        ft.Switch(key=f"ap_mon_{pid}_{mi}", value=m.get("enabled", True), on_change=lambda e, pid=pid, n=name: toggle_model(pid, n, bool(e.control.value))),
                        ft.IconButton(key=f"ap_mup_{pid}_{mi}", icon=ft.Icons.ARROW_UPWARD_ROUNDED, tooltip=S("up", lang), on_click=lambda _e, pid=pid, n=name: move_model(pid, n, -1)),
                        ft.IconButton(key=f"ap_mdown_{pid}_{mi}", icon=ft.Icons.ARROW_DOWNWARD_ROUNDED, tooltip=S("down", lang), on_click=lambda _e, pid=pid, n=name: move_model(pid, n, 1)),
                        ft.TextButton(key=f"ap_test_{pid}_{mi}", content=S("test", lang), on_click=lambda _e, pid=pid, n=name, o=out: run_test(pid, n, o)),
                        ft.TextButton(key=f"ap_mdel_{pid}_{mi}", content=S("sure" if armed else "delete", lang), on_click=lambda _e, pid=pid, n=name: delete_model(pid, n)),
                    ]),
                    ft.Row(spacing=8, wrap=True, controls=[
                        ft.TextField(key=f"ap_pin_{pid}_{mi}", label=S("price_in", lang), width=170, value=m.get("price_in", ""), border_radius=10, on_blur=lambda e, pid=pid, n=name: edit_model(pid, n, "price_in", e.control.value or "")),
                        ft.TextField(key=f"ap_pout_{pid}_{mi}", label=S("price_out", lang), width=170, value=m.get("price_out", ""), border_radius=10, on_blur=lambda e, pid=pid, n=name: edit_model(pid, n, "price_out", e.control.value or "")),
                        ft.TextField(key=f"ap_ctx_{pid}_{mi}", label=S("ctx", lang), width=150, value=str(m.get("max_context_tokens") or ""), border_radius=10, on_blur=lambda e, pid=pid, n=name: edit_model(pid, n, "max_context_tokens", e.control.value or "")),
                    ]),
                    out,
                ]))
            new_model = ft.TextField(key=f"ap_newmodel_{pid}", label=S("add_model", lang), width=240, border_radius=10)
            armed_p = ui["armed"] == ("p", pid)
            cards.append(common.card(page, ft.Column(spacing=10, controls=[
                ft.Row(spacing=8, wrap=True, controls=[
                    ft.Text(p.get("name", pid), size=16, weight=ft.FontWeight.W_700), ft.Text(S("primary" if idx == 0 else "backup", lang), size=12, color=theme.ACCENT_DARK),
                    ft.Text(p.get("base_url", ""), size=11.5, color=secondary, selectable=True), ft.Container(expand=True),
                    ft.Switch(key=f"ap_on_{pid}", label=S("enabled", lang), value=p.get("enabled", True), on_change=lambda e, pid=pid: toggle_provider(pid, bool(e.control.value))),
                    ft.IconButton(key=f"ap_up_{pid}", icon=ft.Icons.ARROW_UPWARD_ROUNDED, tooltip=S("up", lang), on_click=lambda _e, pid=pid: move_provider(pid, -1)),
                    ft.IconButton(key=f"ap_down_{pid}", icon=ft.Icons.ARROW_DOWNWARD_ROUNDED, tooltip=S("down", lang), on_click=lambda _e, pid=pid: move_provider(pid, 1)),
                    ft.TextButton(key=f"ap_del_{pid}", content=S("sure" if armed_p else "delete", lang), on_click=lambda _e, pid=pid: delete_provider(pid)),
                ]),
                *rows,
                ft.Row(spacing=8, controls=[new_model, ft.TextButton(key=f"ap_addmodel_{pid}", content=S("add_model_btn", lang), on_click=lambda _e, pid=pid, f=new_model: add_model(pid, f))]),
            ]), padding=14))
        list_col.controls = cards or [ft.Text(S("empty", lang), size=12.5, color=secondary)]
        evs = list(ap.HEALTH.events)
        hist_col.controls = [ft.Text(S("hist_line", lang, t=time.strftime("%m-%d %H:%M", time.localtime(e["ts"])), frm=e["from"], to=e["to"] or S("hist_none", lang), why=ap.REASON_FA.get(e["reason"], e["reason"]) if lang != "en" else e["reason"]), size=12, color=secondary) for e in evs] \
            or [ft.Text(S("history_empty", lang), size=12, color=secondary)]

    def migrate(_e=None) -> None:
        for cfg in ap.parse_providers(settings):
            settings.ai_providers.append(ap.provider_to_dict(cfg, crypto.encrypt(cfg.api_key) if cfg.api_key else ""))
        commit()

    # ---- فرمِ افزودن
    preset = ft.Dropdown(key="ap_preset", label=S("preset", lang), width=260, border_radius=10, options=[ft.DropdownOption(key=k, text=t) for k, t, _u in PRESETS])
    name_tf = ft.TextField(key="ap_name", label=S("name", lang), width=200, border_radius=10)
    url_tf = ft.TextField(key="ap_url", label=S("url", lang), width=380, border_radius=10)
    key_tf = ft.TextField(key="ap_key", label=S("key", lang), width=300, border_radius=10, password=True, can_reveal_password=True)
    models_tf = ft.TextField(key="ap_models", label=S("models", lang), width=380, border_radius=10)
    timeout_tf = ft.TextField(key="ap_timeout", label=S("timeout", lang), width=200, border_radius=10)

    def on_preset(_e=None) -> None:
        for k, title, url in PRESETS:
            if k == preset.value:
                url_tf.value = url
                name_tf.value = name_tf.value or title.split(" (")[0]
        page.update()

    def on_add(_e=None) -> None:
        try:
            url = ap.validate_base_url(url_tf.value or "")
        except ValueError as exc:
            show(str(exc), False)
            page.update()
            return
        models = [m.strip() for m in (models_tf.value or "").replace("،", ",").split(",") if m.strip()]
        if not models:
            show(S("need_models", lang), False)
            page.update()
            return
        if not (key_tf.value or "").strip():
            show(S("need_key", lang), False)
            page.update()
            return
        timeout = int(timeout_tf.value) if (timeout_tf.value or "").strip().isdigit() else 0
        pid = ap.new_provider_id()
        settings.ai_providers.append(ap.provider_to_dict(
            ap.ProviderCfg(pid, (name_tf.value or "").strip() or pid, ap.KIND_API, url, "", min(timeout, 120), True, [ap.ModelCfg(m) for m in dict.fromkeys(models)]),
            crypto.encrypt(key_tf.value.strip())))
        name_tf.value = url_tf.value = key_tf.value = models_tf.value = timeout_tf.value = ""
        preset.value = None
        show(S("added", lang), True)
        commit()

    # ---- تنظیماتِ زنجیره
    attempt = ft.TextField(key="ap_attempt", label=S("attempt", lang), width=170, border_radius=10, value=str(settings.ai_attempt_timeout))
    total = ft.TextField(key="ap_total", label=S("total", lang), width=170, border_radius=10, value=str(settings.ai_total_timeout))
    targets = ft.TextField(key="ap_targets", label=S("targets", lang), width=200, border_radius=10, value=str(settings.ai_max_targets))
    conc = ft.TextField(key="ap_conc", label=S("conc", lang), width=220, border_radius=10, value=str(settings.ai_provider_concurrency))
    local_sw = ft.Switch(key="ap_local", label=S("local", lang), value=settings.ai_local_fallback)

    def on_save_chain(_e=None) -> None:
        spec = (("ap_attempt", attempt, 3, 120, "attempt"), ("ap_total", total, 5, 300, "total"), ("ap_targets", targets, 1, 10, "targets"), ("ap_conc", conc, 1, 32, "conc"))
        vals = {}
        for key, field, lo, hi, label in spec:
            raw = (field.value or "").strip()
            if not raw.isdigit() or not lo <= int(raw) <= hi:
                show(S("bad", lang, label=S(label, lang)), False)
                page.update()
                return
            vals[key] = int(raw)
        settings.ai_attempt_timeout, settings.ai_total_timeout = vals["ap_attempt"], max(vals["ap_total"], vals["ap_attempt"])
        settings.ai_max_targets, settings.ai_provider_concurrency = vals["ap_targets"], vals["ap_conc"]
        settings.ai_local_fallback = bool(local_sw.value)
        show(S("saved", lang), True)
        commit(rerender=False)

    preset.on_select = on_preset
    render()
    new_card = common.card(page, ft.Column(spacing=10, controls=[
        ft.Text(S("new", lang), size=15, weight=ft.FontWeight.W_700), preset,
        ft.Row(spacing=10, wrap=True, controls=[name_tf, url_tf]), ft.Row(spacing=10, wrap=True, controls=[key_tf, models_tf, timeout_tf]),
        ft.FilledButton(key="ap_add", content=S("add", lang), icon=ft.Icons.ADD_ROUNDED, on_click=on_add),
    ]), padding=14)
    chain_card = common.card(page, ft.Column(spacing=10, controls=[
        ft.Text(S("chain", lang), size=15, weight=ft.FontWeight.W_700), ft.Row(spacing=10, wrap=True, controls=[attempt, total, targets, conc]), local_sw,
        ft.FilledButton(key="ap_save_chain", content=S("save", lang), icon=ft.Icons.SAVE_ROUNDED, on_click=on_save_chain),
    ]), padding=14)
    return ft.Container(expand=True, padding=ft.Padding.symmetric(horizontal=32, vertical=24), content=ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=14, controls=[
        common.page_header(page, ft.Icons.HUB_ROUNDED, S("title", lang), S("subtitle", lang)),
        ft.Text(S("chain_note", lang), size=12.5, color=secondary), banner, list_col, new_card, chain_card, notice,
        ft.Text(S("history", lang), size=15, weight=ft.FontWeight.W_700), hist_col,
    ]))
