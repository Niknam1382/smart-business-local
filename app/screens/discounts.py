"""صفحه‌ی «تخفیف و کمپین» (N8): ساختِ کدِ تخفیف (با قالب‌های آماده)، آمارِ هر کد، و کمپین (پیامِ همگانی + کد، فوری یا زمان‌بندی‌شده).

مبلغ‌ها در UI «تومان» تایپ می‌شن و داخلِ برنامه ریال (×۱۰) ذخیره می‌شن. محاسبه‌ی تخفیف فقط در ``app.core.discounts`` است؛ این صفحه فقط فرم و نمایشه.
"""

from __future__ import annotations

import logging
import secrets
import string
import time
from datetime import datetime
from typing import Optional

import flet as ft

from app import theme
from app.core import broadcast as bc
from app.core import discounts as dc
from app.core.campaigns import CampaignError
from app.screens import common

logger = logging.getLogger(__name__)
_FA = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٬,", "01234567890123456789  ")

_S = {
    "title": ("تخفیف و کمپین", "Discounts & campaigns"),
    "subtitle": ("کدِ تخفیف بساز، تخفیفِ خودکار بذار، و با یک پیام به مشتری‌ها خبر بده.", "Create discount codes, automatic discounts, and announce them to customers."),
    "codes": ("کدهای تخفیف", "Discount codes"),
    "codes_empty": ("هنوز کدی نساخته‌ای. از «کدِ جدید» شروع کن.", "No codes yet. Start with “New code”."),
    "new": ("کدِ جدید", "New code"),
    "preset": ("قالبِ آماده", "Ready-made template"),
    "preset.none": ("از صفر", "From scratch"),
    "code": ("کد (حروفِ انگلیسی/عدد)", "Code (letters/digits)"),
    "gen": ("ساختِ کدِ تصادفی", "Generate a random code"),
    "kind": ("نوعِ تخفیف", "Discount type"),
    "kind.percent": ("درصدی", "Percent"),
    "kind.fixed": ("مبلغِ ثابت", "Fixed amount"),
    "value_pct": ("درصد (۱ تا ۹۹)", "Percent (1–99)"),
    "value_fixed": ("مبلغِ تخفیف (تومان)", "Discount amount (Toman)"),
    "max": ("سقفِ تخفیف (تومان، اختیاری)", "Max discount (Toman, optional)"),
    "min": ("حداقلِ جمعِ سبد (تومان)", "Minimum cart total (Toman)"),
    "scope": ("مشمولِ", "Applies to"),
    "scope.all": ("همه‌ی محصولات", "All products"),
    "scope.products": ("محصولاتِ انتخابی", "Selected products"),
    "scope.categories": ("دسته‌های انتخابی", "Selected categories"),
    "categories": ("نامِ دسته‌ها (با ویرگول جدا کن)", "Category names (comma-separated)"),
    "total": ("سقفِ کلِ استفاده (۰ = نامحدود)", "Total uses limit (0 = unlimited)"),
    "per": ("سقفِ هر مشتری (۰ = نامحدود)", "Per-customer limit (0 = unlimited)"),
    "prev": ("حداقلِ خریدهای قبلی", "Minimum previous purchases"),
    "first": ("فقط اولین خرید", "First purchase only"),
    "platform": ("پیام‌رسان", "Messenger"),
    "platform.all": ("هر دو", "Both"),
    "platform.telegram": ("تلگرام", "Telegram"),
    "platform.bale": ("بله", "Bale"),
    "start": ("شروع (YYYY-MM-DD یا با ساعت، اختیاری)", "Start (YYYY-MM-DD, optional time)"),
    "end": ("پایان (YYYY-MM-DD یا با ساعت، اختیاری)", "End (YYYY-MM-DD, optional time)"),
    "auto": ("خودکار اعمال شود (مشتری کدی وارد نمی‌کنه)", "Apply automatically (customer types no code)"),
    "stack": ("با تخفیف‌های دیگه جمع شود", "Can combine with other discounts"),
    "note": ("یادداشت (فقط برای خودت)", "Note (for you only)"),
    "create": ("ساختنِ کد", "Create code"),
    "created": ("✅ کدِ «{code}» ساخته شد.", "✅ Code “{code}” created."),
    "bad_number": ("«{label}» باید عددِ درست باشه.", "“{label}” must be a valid number."),
    "bad_date": ("تاریخ باید مثلِ 2026-12-31 یا 2026-12-31 18:30 باشه.", "Date must look like 2026-12-31 or 2026-12-31 18:30."),
    "pick_products": ("محصولاتِ مشمول", "Eligible products"),
    "active": ("فعال", "Active"),
    "delete": ("حذف", "Delete"),
    "delete_sure": ("مطمئنی؟ دوباره بزن", "Sure? Press again"),
    "delete_used": ("این کد قبلاً استفاده شده؛ فقط غیرفعال می‌شه.", "This code has been used; it is only deactivated."),
    "badge_auto": ("خودکار", "Auto"),
    "badge_stack": ("قابل‌جمع", "Stackable"),
    "badge_off": ("غیرفعال", "Inactive"),
    "uses": ("استفاده: {n}{limit}", "Uses: {n}{limit}"),
    "sales": ("سفارشِ پرداخت‌شده: {n} · فروش: {rev} تومان · تخفیفِ داده‌شده: {disc} تومان", "Paid orders: {n} · sales: {rev} Toman · discount given: {disc} Toman"),
    "percent_desc": ("{v}٪ تخفیف", "{v}% off"),
    "fixed_desc": ("{v} تومان تخفیف", "{v} Toman off"),
    "campaigns": ("کمپین‌ها", "Campaigns"),
    "camp_new": ("کمپینِ جدید", "New campaign"),
    "camp_name": ("نامِ کمپین", "Campaign name"),
    "camp_text": ("متنِ پیام", "Message text"),
    "camp_code": ("کدِ همراهِ پیام", "Code to include"),
    "camp_code.none": ("بدونِ کد", "No code"),
    "camp_when": ("زمانِ ارسال (خالی = همین حالا؛ YYYY-MM-DD HH:MM)", "Send at (empty = now; YYYY-MM-DD HH:MM)"),
    "camp_who": ("گیرندگان: {n} نفر", "Recipients: {n}"),
    "camp_who_none": ("با این فیلترها هیچ مشتریِ مجازی نیست.", "No eligible customers for these filters."),
    "camp_create": ("ثبتِ کمپین", "Save campaign"),
    "camp_created": ("✅ کمپین ثبت شد؛ {when}.", "✅ Campaign saved; {when}."),
    "camp_now": ("به‌زودی شروع می‌شه", "it starts shortly"),
    "camp_at": ("در {t} شروع می‌شه", "it starts at {t}"),
    "camp_empty": ("هنوز کمپینی نساخته‌ای.", "No campaigns yet."),
    "camp_status.scheduled": ("زمان‌بندی‌شده", "Scheduled"),
    "camp_status.running": ("در حال ارسال", "Sending"),
    "camp_status.done": ("تمام شد", "Done"),
    "camp_status.failed": ("شروع نشد", "Failed to start"),
    "camp_status.cancelled": ("لغو شد", "Cancelled"),
    "camp_cancel": ("لغو", "Cancel"),
    "camp_stats": ("رسید {sent} از {n} · استفاده از کد: {uses} · فروش: {rev} تومان", "Delivered {sent} of {n} · code uses: {uses} · sales: {rev} Toman"),
    "bots_note": ("ارسالِ کمپین فقط وقتی انجام می‌شه که ربات‌ها روشن باشن.", "Campaigns are sent only while the bots are running."),
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
}


def S(key: str, lang: str, **kw) -> str:
    fa, en = _S[key]
    text = en if lang == "en" else fa
    return text.format(**kw) if kw else text


def parse_toman(text, allow_empty: bool = True) -> Optional[int]:
    """«۵۰٬۰۰۰» ← ۵۰۰۰۰۰ ریال؛ خالی ← ۰؛ نامعتبر ← ``None``."""
    raw = str(text or "").translate(_FA).replace(" ", "")
    if not raw:
        return 0 if allow_empty else None
    return int(raw) * 10 if raw.isdigit() and len(raw) <= 12 else None


def parse_count(text) -> Optional[int]:
    raw = str(text or "").translate(_FA).replace(" ", "")
    if not raw:
        return 0
    return int(raw) if raw.isdigit() and len(raw) <= 9 else None


def parse_when(text) -> Optional[int]:
    """``2026-12-31`` یا ``2026-12-31 18:30`` (ساعتِ محلی) ← ثانیه‌ی یونیکس؛ خالی ← ۰؛ نامعتبر ← ``None``."""
    raw = str(text or "").translate(_FA).strip()
    if not raw:
        return 0
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(raw, fmt).timestamp())
        except ValueError:
            continue
    return None


def _toman(irr: int) -> str:
    return f"{int(irr) // 10:,}"


def describe(code: dc.DiscountCode, lang: str) -> str:
    base = S("percent_desc", lang, v=code.value) if code.kind == dc.KIND_PERCENT else S("fixed_desc", lang, v=_toman(code.value))
    extra = []
    if code.min_subtotal_irr:
        extra.append(("حداقلِ سبد " if lang != "en" else "min cart ") + _toman(code.min_subtotal_irr))
    if code.first_order_only:
        extra.append(S("first", lang))
    return base + ("  ·  " + " · ".join(extra) if extra else "")


def _fmt_time(ts: int) -> str:
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return ""


def build(page: ft.Page, lang: str, manager, product_store) -> ft.Control:
    secondary = theme.text_secondary(page)
    store, camps, svc = manager.discounts, manager.campaigns, manager.broadcasts
    ui = {"armed": None, "products": set()}

    def dd(key: str, label: str, group: str, values: list, width: int = 190, value: str = None) -> ft.Dropdown:
        return ft.Dropdown(key=key, label=label, border_radius=10, width=width, value=value or values[0],
                           options=[ft.DropdownOption(key=v, text=S(f"{group}.{v}", lang)) for v in values])

    def tf(key: str, label: str, width: int = 220, **kw) -> ft.TextField:
        return ft.TextField(key=key, label=label, border_radius=10, width=width, **kw)

    # ------------------------------------------------------------ فرمِ کدِ جدید ----
    notice = ft.Text("", key="dc_notice", size=12.5, visible=False, selectable=True)
    preset_dd = ft.Dropdown(
        key="dc_preset", label=S("preset", lang), border_radius=10, width=320, value="none",
        options=[ft.DropdownOption(key="none", text=S("preset.none", lang)), *[ft.DropdownOption(key=pid, text=title) for pid, title, _c in dc.presets()]],
    )
    code_tf, gen_btn = tf("dc_code", S("code", lang), 200, max_length=dc.CODE_MAX), None
    kind_dd = dd("dc_kind", S("kind", lang), "kind", [dc.KIND_PERCENT, dc.KIND_FIXED], 170)
    value_tf = tf("dc_value", S("value_pct", lang), 190)
    max_tf = tf("dc_max", S("max", lang), 230)
    min_tf = tf("dc_min", S("min", lang), 230)
    scope_dd = dd("dc_scope", S("scope", lang), "scope", list(dc.APPLIES), 200)
    cats_tf = tf("dc_cats", S("categories", lang), 360, visible=False)
    prods_col = ft.Column(key="dc_products", spacing=2, visible=False, height=160, scroll=ft.ScrollMode.AUTO)
    total_tf, per_tf, prev_tf = tf("dc_total", S("total", lang), 230), tf("dc_per", S("per", lang), 230), tf("dc_prev", S("prev", lang), 190)
    first_sw = ft.Switch(key="dc_first", label=S("first", lang), value=False)
    platform_dd = dd("dc_platform", S("platform", lang), "platform", ["all", "telegram", "bale"], 150)
    start_tf, end_tf = tf("dc_start", S("start", lang), 250), tf("dc_end", S("end", lang), 250)
    auto_sw = ft.Switch(key="dc_auto", label=S("auto", lang), value=False)
    stack_sw = ft.Switch(key="dc_stack", label=S("stack", lang), value=False)
    note_tf = tf("dc_note", S("note", lang), 360, max_length=200)

    def show(text: str, ok: bool = True) -> None:
        notice.value, notice.color, notice.visible = text, theme.SUCCESS if ok else theme.DANGER, bool(text)

    def refresh_kind(_e=None) -> None:
        pct = kind_dd.value == dc.KIND_PERCENT
        value_tf.label = S("value_pct" if pct else "value_fixed", lang)
        max_tf.visible = pct
        page.update()

    def refresh_scope(_e=None) -> None:
        cats_tf.visible = scope_dd.value == dc.APPLIES_CATEGORIES
        prods_col.visible = scope_dd.value == dc.APPLIES_PRODUCTS
        page.update()

    def fill_products() -> None:
        rows = []
        for p in product_store.list()[:80]:
            def on_toggle(e, pid=p.id) -> None:
                (ui["products"].add if e.control.value else ui["products"].discard)(pid)
            rows.append(ft.Checkbox(key=f"dc_prod_{p.id}", label=p.name, value=p.id in ui["products"], on_change=on_toggle))
        prods_col.controls = rows or [ft.Text("—", size=12, color=secondary)]

    def apply_preset(_e=None) -> None:
        for pid, _title, tpl in dc.presets():
            if pid != preset_dd.value:
                continue
            kind_dd.value = tpl.kind
            value_tf.value = str(tpl.value if tpl.kind == dc.KIND_PERCENT else tpl.value // 10)
            min_tf.value = str(tpl.min_subtotal_irr // 10) if tpl.min_subtotal_irr else ""
            total_tf.value = str(tpl.total_limit) if tpl.total_limit else ""
            per_tf.value = str(tpl.per_customer_limit) if tpl.per_customer_limit else ""
            first_sw.value, auto_sw.value, stack_sw.value = tpl.first_order_only, tpl.auto_apply, tpl.stackable
            start_tf.value = _fmt_time(tpl.starts_ts) if tpl.starts_ts else ""
            end_tf.value = _fmt_time(tpl.ends_ts) if tpl.ends_ts else ""
            refresh_kind()

    def on_gen(_e=None) -> None:
        code_tf.value = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        page.update()

    def on_create(_e=None) -> None:
        bad = lambda label: show(S("bad_number", lang, label=label), False) or page.update()  # noqa: E731
        raw_value = str(value_tf.value or "").translate(_FA).replace(" ", "")
        if not raw_value.isdigit():
            return bad(value_tf.label)
        value = int(raw_value) if kind_dd.value == dc.KIND_PERCENT else int(raw_value) * 10
        max_irr, min_irr = parse_toman(max_tf.value), parse_toman(min_tf.value)
        total, per, prev = parse_count(total_tf.value), parse_count(per_tf.value), parse_count(prev_tf.value)
        for label, v in ((max_tf.label, max_irr), (min_tf.label, min_irr), (total_tf.label, total), (per_tf.label, per), (prev_tf.label, prev)):
            if v is None:
                return bad(label)
        starts, ends = parse_when(start_tf.value), parse_when(end_tf.value)
        if starts is None or ends is None:
            show(S("bad_date", lang), False)
            page.update()
            return
        targets: list = []
        if scope_dd.value == dc.APPLIES_PRODUCTS:
            targets = sorted(ui["products"])
        elif scope_dd.value == dc.APPLIES_CATEGORIES:
            targets = [c.strip() for c in (cats_tf.value or "").replace("،", ",").split(",") if c.strip()]
        code = dc.DiscountCode(
            0, code_tf.value or "", kind_dd.value, value, max_discount_irr=max_irr if kind_dd.value == dc.KIND_PERCENT else 0,
            min_subtotal_irr=min_irr, applies=scope_dd.value, targets=targets, first_order_only=bool(first_sw.value), min_prev_orders=prev,
            per_customer_limit=per, total_limit=total, starts_ts=starts, ends_ts=ends,
            platforms=[] if platform_dd.value in (None, "all") else [platform_dd.value], stackable=bool(stack_sw.value),
            auto_apply=bool(auto_sw.value), note=note_tf.value or "",
        )
        try:
            store.create(code)
        except dc.DiscountConfigError as exc:
            show(str(exc), False)
            page.update()
            return
        show(S("created", lang, code=code.code), True)
        code_tf.value = value_tf.value = max_tf.value = min_tf.value = total_tf.value = per_tf.value = prev_tf.value = note_tf.value = ""
        start_tf.value = end_tf.value = ""
        render_codes()
        render_camp_codes()
        page.update()

    # ------------------------------------------------------------ فهرستِ کدها ----
    codes_col = ft.Column(key="dc_list", spacing=10)

    def act_toggle(cid: int, value: bool) -> None:
        store.set_active(cid, value)
        render_codes()
        render_camp_codes()
        page.update()

    def act_delete(cid: int) -> None:
        if ui["armed"] != ("code", cid):
            ui["armed"] = ("code", cid)
            render_codes()
            page.update()
            return
        ui["armed"] = None
        if not store.delete(cid):
            store.set_active(cid, False)
            show(S("delete_used", lang), True)
        render_codes()
        render_camp_codes()
        page.update()

    def render_codes() -> None:
        rows = store.list()
        if not rows:
            codes_col.controls = [ft.Text(S("codes_empty", lang), size=12.5, color=secondary)]
            return
        items = []
        for c in rows:
            st = store.stats(c.id)
            badges = [S("badge_auto", lang)] if c.auto_apply else []
            badges += [S("badge_stack", lang)] if c.stackable else []
            badges += [] if c.active else [S("badge_off", lang)]
            limit = f" / {c.total_limit}" if c.total_limit else ""
            armed = ui["armed"] == ("code", c.id)
            items.append(common.card(page, ft.Column(spacing=6, controls=[
                ft.Row(spacing=10, controls=[
                    ft.Text(c.code, size=16, weight=ft.FontWeight.W_700, selectable=True),
                    ft.Text(" · ".join(badges), size=11.5, color=theme.ACCENT_DARK),
                    ft.Container(expand=True),
                    ft.Switch(key=f"dc_active_{c.id}", label=S("active", lang), value=c.active, on_change=lambda e, cid=c.id: act_toggle(cid, bool(e.control.value))),
                    ft.TextButton(key=f"dc_del_{c.id}", content=S("delete_sure" if armed else "delete", lang), icon=ft.Icons.DELETE_OUTLINE_ROUNDED, on_click=lambda _e, cid=c.id: act_delete(cid)),
                ]),
                ft.Text(describe(c, lang), size=13),
                ft.Text(S("uses", lang, n=c.used_count, limit=limit), size=12, color=secondary),
                ft.Text(S("sales", lang, n=st.uses, rev=_toman(st.revenue_irr), disc=_toman(st.discount_irr)), size=12, color=secondary),
            ]), padding=14))
        codes_col.controls = items

    # ------------------------------------------------------------ کمپین ----
    camp_notice = ft.Text("", key="cm_notice", size=12.5, visible=False, selectable=True)
    camp_name = tf("cm_name", S("camp_name", lang), 260, max_length=60)
    camp_text = ft.TextField(key="cm_text", label=S("camp_text", lang), border_radius=10, multiline=True, min_lines=3, max_lines=8, max_length=bc.MAX_TEXT)
    camp_code = ft.Dropdown(key="cm_code", label=S("camp_code", lang), border_radius=10, width=260, value="0", options=[])
    camp_when = tf("cm_when", S("camp_when", lang), 330)
    c_platform = dd("cm_platform", S("platform", lang), "platform", ["all", "telegram", "bale"], 150)
    c_purchase = dd("cm_purchase", S("purchase", lang), "purchase", list(bc.PURCHASES), 190)
    c_activity = dd("cm_activity", S("activity", lang), "activity", list(bc.ACTIVITIES), 230)
    camp_who = ft.Text("", key="cm_who", size=13.5, weight=ft.FontWeight.W_600)
    camp_col = ft.Column(key="cm_list", spacing=10)

    def camp_show(text: str, ok: bool = True) -> None:
        camp_notice.value, camp_notice.color, camp_notice.visible = text, theme.SUCCESS if ok else theme.DANGER, bool(text)

    def render_camp_codes() -> None:
        active = store.list(only_active=True)
        camp_code.options = [ft.DropdownOption(key="0", text=S("camp_code.none", lang)), *[ft.DropdownOption(key=str(c.id), text=c.code) for c in active]]
        if camp_code.value not in {o.key for o in camp_code.options}:
            camp_code.value = "0"

    def audience() -> bc.Audience:
        pick = lambda v: "" if v in (None, "all") else v  # noqa: E731
        return bc.Audience(platform=pick(c_platform.value), purchase=c_purchase.value or bc.PURCHASE_ALL, activity=c_activity.value or bc.ACTIVITY_ALL)

    def refresh_who(_e=None) -> None:
        try:
            s = svc.summary(audience())
        except bc.BroadcastError as exc:
            camp_who.value, camp_who.color = str(exc), theme.DANGER
        else:
            camp_who.value, camp_who.color = (S("camp_who", lang, n=s.total), theme.PRIMARY) if s.total else (S("camp_who_none", lang), theme.DANGER)
        if _e is not None:
            page.update()

    def on_camp_create(_e=None) -> None:
        when = parse_when(camp_when.value)
        if when is None:
            camp_show(S("bad_date", lang), False)
            page.update()
            return
        try:
            camps.create(camp_name.value or "", camp_text.value or "", audience(), code_id=int(camp_code.value or 0), start_ts=when)
        except (CampaignError, ValueError) as exc:
            camp_show(str(exc), False)
            page.update()
            return
        started = S("camp_at", lang, t=_fmt_time(when)) if when and when > time.time() else S("camp_now", lang)
        camp_show(S("camp_created", lang, when=started), True)
        camp_name.value = camp_text.value = camp_when.value = ""
        render_camps()
        page.update()

    def on_camp_cancel(cid: int) -> None:
        camps.cancel(cid)
        render_camps()
        page.update()

    def render_camps() -> None:
        rows = camps.list(20)
        if not rows:
            camp_col.controls = [ft.Text(S("camp_empty", lang), size=12.5, color=secondary)]
            return
        items = []
        for c in rows:
            st = camps.stats(c.id)
            color = {"running": theme.PRIMARY, "done": theme.SUCCESS, "failed": theme.DANGER}.get(c.status, secondary)
            lines = [ft.Row(spacing=10, controls=[
                ft.Text(c.name, size=15, weight=ft.FontWeight.W_700),
                ft.Text(S(f"camp_status.{c.status}", lang), size=12, color=color),
                ft.Container(expand=True),
                *([ft.TextButton(key=f"cm_cancel_{c.id}", content=S("camp_cancel", lang), on_click=lambda _e, cid=c.id: on_camp_cancel(cid))] if c.status == "scheduled" else []),
            ])]
            if c.status == "scheduled":
                lines.append(ft.Text(_fmt_time(c.start_ts), size=12, color=secondary))
            if c.error:
                lines.append(ft.Text(c.error, size=12, color=theme.DANGER, selectable=True))
            if c.broadcast_id:
                lines.append(ft.Text(S("camp_stats", lang, sent=st.sent, n=st.audience, uses=st.code_uses, rev=_toman(st.revenue_irr)), size=12, color=secondary))
            items.append(common.card(page, ft.Column(spacing=4, controls=lines), padding=14))
        camp_col.controls = items

    # ------------------------------------------------------------ سیم‌کشی ----
    preset_dd.on_select = apply_preset
    kind_dd.on_select = refresh_kind
    scope_dd.on_select = refresh_scope
    gen_btn = ft.TextButton(key="dc_gen", content=S("gen", lang), icon=ft.Icons.AUTO_AWESOME_ROUNDED, on_click=on_gen)
    for control in (c_platform, c_purchase, c_activity):
        control.on_select = refresh_who

    fill_products()
    refresh_kind()
    render_codes()
    render_camp_codes()
    refresh_who()
    render_camps()

    new_card = common.card(page, ft.Column(spacing=12, controls=[
        ft.Text(S("new", lang), size=15, weight=ft.FontWeight.W_700),
        preset_dd,
        ft.Row(spacing=10, wrap=True, controls=[code_tf, gen_btn]),
        ft.Row(spacing=10, wrap=True, controls=[kind_dd, value_tf, max_tf, min_tf]),
        ft.Row(spacing=10, wrap=True, controls=[scope_dd, cats_tf]),
        prods_col,
        ft.Row(spacing=10, wrap=True, controls=[total_tf, per_tf, prev_tf, platform_dd]),
        ft.Row(spacing=10, wrap=True, controls=[start_tf, end_tf]),
        ft.Row(spacing=16, wrap=True, controls=[first_sw, auto_sw, stack_sw]),
        note_tf,
        ft.FilledButton(key="dc_create", content=S("create", lang), icon=ft.Icons.ADD_ROUNDED, on_click=on_create),
        notice,
    ]))
    camp_card = common.card(page, ft.Column(spacing=12, controls=[
        ft.Text(S("camp_new", lang), size=15, weight=ft.FontWeight.W_700),
        ft.Row(spacing=10, wrap=True, controls=[camp_name, camp_code]),
        camp_text,
        ft.Row(spacing=10, wrap=True, controls=[c_platform, c_purchase, c_activity]),
        camp_who,
        camp_when,
        ft.Text(S("bots_note", lang), size=11.5, color=secondary),
        ft.FilledButton(key="cm_create", content=S("camp_create", lang), icon=ft.Icons.CAMPAIGN_ROUNDED, on_click=on_camp_create),
        camp_notice,
    ]))
    return ft.Container(
        expand=True,
        padding=ft.Padding.symmetric(horizontal=32, vertical=24),
        content=ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=14, controls=[
            common.page_header(page, ft.Icons.LOCAL_OFFER_ROUNDED, S("title", lang), S("subtitle", lang)),
            ft.Text(S("codes", lang), size=15, weight=ft.FontWeight.W_700),
            codes_col,
            new_card,
            ft.Text(S("campaigns", lang), size=15, weight=ft.FontWeight.W_700),
            camp_col,
            camp_card,
        ]),
    )
