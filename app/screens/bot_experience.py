"""
صفحه‌ی «تجربه‌ی ربات» (R8): همه‌ی چیزهایی که مشتری توی ربات می‌بینه و صاحب فروشگاه بدونِ برنامه‌نویسی تنظیم می‌کنه.

بخش‌ها: حالت و منو · فیلدهای چک‌اوت · دکمه‌های منو · سؤالات متداول · متن‌ها · ساعت کاری و پشتیبانی · مصرف و محدودیت ·
صندوقِ «نیاز به توجه» · پیش‌نمایشِ مشتری. همه‌ی مقدارها روی همان شیء settings نوشته و بلافاصله ذخیره می‌شن (ری‌استارتِ
ربات لازم نیست). هر ورودیِ نامعتبر با پیامِ فارسیِ روشن رد می‌شه و چیزی ذخیره نمی‌شه.
"""

from __future__ import annotations

import flet as ft

from app import theme
from app.core import checkout_fields as cf
from app.core import custom_buttons as cb
from app.core import modes, working_hours
from app.screens import bot_profile_card, customer_preview, quick_setup_card, required_channels_card, texts_editor
from app.screens.common import card, page_header

_S = {
    "title": ("تجربه‌ی ربات", "Bot experience"),
    "subtitle": ("آنچه مشتری توی ربات می‌بینه: حالت، دکمه‌ها، فرم سفارش، متن‌ها و پشتیبانی.", "What customers see in the bot: mode, buttons, order form, texts and support."),
    "saved": ("✅ ذخیره شد.", "✅ Saved."),
    "sec.mode": ("حالت و منو", "Mode & menu"),
    "sec.fields": ("فیلدهای فرم سفارش", "Checkout fields"),
    "sec.buttons": ("دکمه‌های منو", "Menu buttons"),
    "sec.faq": ("سؤالات متداول", "FAQ"),
    "sec.texts": ("متن‌های ربات", "Bot texts"),
    "sec.hours": ("ساعت کاری و پشتیبانی", "Working hours & support"),
    "sec.limits": ("مصرف و محدودیت", "Usage & limits"),
    "sec.inbox": ("نیاز به توجه", "Needs attention"),
    "sec.preview": ("پیش‌نمایشِ مشتری", "Customer preview"),
    "mode.label": ("حالتِ ربات", "Bot mode"),
    "mode.advisor": ("مشاوره (گفتگو با هوش مصنوعی)", "Consulting (chat with AI)"),
    "mode.shop_buttons": ("فروشگاه (دکمه‌ای)", "Shop (buttons)"),
    "mode.shop_ai": ("سفارش با AI (آزمایشی)", "AI ordering (experimental)"),
    "mode.faq_support": ("پاسخ‌گویی + پشتیبانی", "Answers + support"),
    "mode.lead_capture": ("جمع‌آوریِ درخواست (سرنخ)", "Collect requests (leads)"),
    "tab.quick": ("شروع سریع", "Quick start"),
    "tab.shop": ("فروشگاه", "Shop"),
    "tab.messages": ("پیام‌ها", "Messages"),
    "tab.advanced": ("پیشرفته", "Advanced"),
    "sec.catalog": ("نمایشِ محصولات", "Product display"),
    "sec.adv_modes": ("حالت‌های آزمایشی و پیشرفته", "Experimental & advanced modes"),
    "adv_modes.switch": ("نمایشِ «سفارش با AI» و «جمع‌آوریِ درخواست» در فهرستِ حالت‌ها", "Show “AI ordering” and “Collect requests” in the mode list"),
    "adv_modes.note": ("این دو حالت برای کاربرهای حرفه‌ایه. حالتِ پیشنهادی «فروشگاه (دکمه‌ای)» ساده‌تر و مطمئن‌تره.", "These two modes are for power users. “Shop (buttons)” is simpler and more reliable."),
    "shop.only": ("این تب مخصوصِ فروشگاه است؛ برای حالتِ مشاوره یا پشتیبانی لازم نیست.", "This tab is for shops; it isn't needed for consulting or support."),
    "lang.label": ("زبانِ ربات", "Bot language"),
    "lang.fa": ("فارسی", "Persian"),
    "lang.en": ("English", "English"),
    "lang.auto": ("خودکار (بر اساسِ زبانِ مشتری)", "Auto (customer's language)"),
    "page_size": ("تعدادِ محصول در هر صفحه (۲ تا ۱۲)", "Products per page (2–12)"),
    "max_qty": ("سقفِ تعدادِ هر محصول در یک سفارش", "Max quantity per product per order"),
    "disclosure": ("خطِ «این ربات با هوش مصنوعی کار می‌کنه» در /start", "Show the “this bot uses AI” line on /start"),
    "save": ("ذخیره", "Save"),
    "add": ("افزودن", "Add"),
    "edit": ("ویرایش", "Edit"),
    "delete": ("حذف", "Delete"),
    "cancel": ("انصراف", "Cancel"),
    "f.id": ("شناسه‌ی داخلی (انگلیسی؛ خالی = خودکار)", "Internal ID (latin; empty = automatic)"),
    "f.advanced": ("گزینه‌های حرفه‌ای (اختیاری)", "Advanced options (optional)"),
    "ftype.text": ("متن", "Text"), "ftype.phone": ("شماره‌ی موبایل", "Mobile number"), "ftype.number": ("عدد", "Number"),
    "ftype.choice": ("انتخابی (چند گزینه)", "Choice (several options)"), "ftype.location": ("موقعیتِ مکانی", "Location"), "ftype.email": ("ایمیل", "Email"),
    "applies.all": ("همه‌ی سفارش‌ها", "All orders"), "applies.physical": ("فقط کالای فیزیکی", "Physical goods only"), "applies.digital": ("فقط محصولِ دیجیتال", "Digital products only"),
    "f.label": ("برچسب", "Label"),
    "f.prompt": ("متنِ پرسش", "Question text"),
    "f.type": ("نوع", "Type"),
    "f.required": ("اجباری", "Required"),
    "f.applies": ("اعمال برای", "Applies to"),
    "f.regex": ("الگوی دقیقِ ورودی (برای حرفه‌ای‌ها، اختیاری)", "Exact input pattern (for experts, optional)"),
    "f.choices": ("گزینه‌ها (هر خط یکی — فقط نوعِ انتخابی)", "Choices (one per line — choice type only)"),
    "f.min": ("حداقل طول", "Min length"),
    "f.max": ("حداکثر طول", "Max length"),
    "f.template": ("قالبِ آماده", "Template"),
    "f.apply_template": ("اعمالِ قالب", "Apply template"),
    "f.defaults": ("بازگشت به پیش‌فرض", "Restore defaults"),
    "tpl.physical": ("کالای فیزیکی", "Physical goods"),
    "tpl.digital": ("محصولِ دیجیتال", "Digital product"),
    "tpl.services": ("خدمات", "Services"),
    "b.action": ("عملِ دکمه", "Button action"),
    "b.emoji": ("ایموجی", "Emoji"),
    "b.value": ("مقدار", "Value"),
    "b.url": ("لینک (http/https)", "Link (http/https)"),
    "b.phone": ("شماره‌ی تماس", "Phone number"),
    "b.text": ("متنِ پاسخ", "Reply text"),
    "b.question": ("پرسشی که به AI داده می‌شه", "Question sent to the AI"),
    "b.platforms": ("پلتفرم‌ها", "Platforms"),
    "act.url": ("لینک", "Link"), "act.text": ("پاسخ متنی", "Text reply"), "act.phone": ("تماس", "Call"),
    "act.support": ("پشتیبانیِ انسانی", "Human support"), "act.open_catalog": ("باز کردنِ محصولات", "Open catalog"),
    "act.open_cart": ("باز کردنِ سبد", "Open cart"), "act.open_orders": ("باز کردنِ پیگیری", "Open tracking"),
    "act.checkout": ("نهایی کردنِ سفارش", "Checkout"), "act.ask_ai": ("پرسش از AI", "Ask AI"), "act.share_contact": ("اشتراکِ شماره", "Share contact"),
    "faq.q": ("سؤال", "Question"), "faq.a": ("پاسخ", "Answer"), "faq.limit": ("حداکثر ۳۰ سؤال.", "Max 30 entries."),
    "t.key": ("کلیدِ متن", "Text key"), "t.lang": ("زبان", "Language"), "t.default": ("متنِ پیش‌فرض", "Default text"),
    "t.override": ("متنِ سفارشیِ شما (خالی = پیش‌فرض)", "Your custom text (empty = default)"),
    "t.reset": ("بازگشت به پیش‌فرض", "Reset to default"),
    "h.enabled": ("ساعتِ کاری فعال باشه", "Enable working hours"),
    "h.hint": ("مثلاً 09:00-17:00 یا چند بازه با کاما: 09:00-13:00, 16:00-20:00 (خالی = تعطیل)", "e.g. 09:00-17:00, or several with commas (empty = closed)"),
    "h.message": ("پیامِ خارج از ساعتِ کاری", "Off-hours message"),
    "h.timeout": ("بسته‌شدنِ خودکارِ گفتگوی پشتیبانی بعد از (ساعت)", "Auto-close support chats after (hours)"),
    "h.note": ("ساعتِ کاری فقط برای پیامِ پشتیبانیه؛ فروش ۲۴ ساعته‌ست. منطقه‌ی زمانی: تهران.", "Working hours only affect support messages; selling is 24/7. Timezone: Tehran."),
    "d.mon": ("دوشنبه", "Mon"), "d.tue": ("سه‌شنبه", "Tue"), "d.wed": ("چهارشنبه", "Wed"), "d.thu": ("پنجشنبه", "Thu"),
    "d.fri": ("جمعه", "Fri"), "d.sat": ("شنبه", "Sat"), "d.sun": ("یکشنبه", "Sun"),
    "l.today": ("امروز: {calls} پاسخِ AI از {cap}، حدود {tokens} توکن، {chats} گفتگو", "Today: {calls} AI answers of {cap}, ~{tokens} tokens, {chats} chats"),
    "l.per_chat": ("سقفِ روزانه برای هر چت (۰ = بدونِ سقف)", "Daily cap per chat (0 = unlimited)"),
    "l.total": ("سقفِ روزانه‌ی کل (۰ = بدونِ سقف)", "Daily total cap (0 = unlimited)"),
    "l.kill": ("قطعِ اضطراریِ AI (دکمه‌ها و پرداخت کار می‌کنن)", "AI kill switch (buttons and payments keep working)"),
    "l.retention": ("نگه‌داریِ داده (روز؛ ۰ = برای همیشه)", "Data retention (days; 0 = forever)"),
    "i.empty": ("چیزی نیاز به توجه نداره ✅", "Nothing needs attention ✅"),
    "i.orders_waiting": ("⏳ {n} سفارشِ پرداخت‌شده منتظرِ تأییدِ توئه (صفحه‌ی سفارش‌ها)", "⏳ {n} paid order(s) waiting for your confirmation (Orders page)"),
    "i.done": ("انجام شد", "Done"), "i.all": ("همه انجام شد", "Mark all done"),
    "i.support_no_owner": ("مشتری پشتیبانی خواست ولی مالکی ثبت نشده", "Customer asked for support but no owner is linked"),
    "i.delivery_failed": ("تحویلِ دیجیتال نرسید", "Digital delivery failed"),
    "i.inventory_short": ("موجودیِ ناکافی بعد از بازیابی", "Insufficient stock after recovery"),
    "i.bio_confirm": ("بیوگرافیِ فعلیِ ربات رو ببین و تأیید کن (صفحه‌ی «پروفایلِ ربات»)", "Review and confirm the bot's current bio (“Bot profile” page)"),
    "i.bio_too_long": ("متنِ بیوگرافی با خطِ اعتبار از ۱۲۰ کاراکتر بیشتره؛ کوتاهش کن (صفحه‌ی «پروفایلِ ربات»)", "The bio plus the credit line exceeds 120 characters; shorten it (“Bot profile” page)"),
    "i.low_stock": ("موجودیِ یک محصول کم شد؛ انبار را بررسی کن (صفحه‌ی «محصولات»)", "A product is running low; check your stock (“Products” page)"),
    "i.invoice_send": ("ارسالِ فاکتور برای مشتری ناموفق بود؛ از صفحه‌ی «مالی ← فاکتورها» دوباره بفرست", "Sending an invoice to a customer failed; resend it from Finance → Invoices"),
    "i.channel_check": ("بررسیِ عضویتِ کانال خطا می‌ده؛ ربات رو ادمینِ کانال کن (تنظیماتِ «تجربه‌ی ربات» ← پیشرفته)", "Channel membership check is failing; make the bot an admin of the channel (“Bot experience” → Advanced)"),
    "i.broadcast": ("ارسالِ همگانی متوقف شد؛ صفحه‌ی «پیامِ همگانی» را ببین", "A broadcast was paused; see the “Broadcast” page"),
    "i.lead": ("درخواستِ جدید", "New request"), "i.ai_cap": ("سقفِ AI", "AI cap"), "i.payment_failed": ("خطای پرداخت", "Payment error"), "i.other": ("سایر", "Other"),
}


def S(key: str, lang: str, **kw) -> str:
    fa, en = _S[key]
    text = en if lang == "en" else fa
    return text.format(**kw) if kw else text


def build(page: ft.Page, lang: str, settings, save_callback, product_store, order_store, manager=None) -> ft.Control:
    is_store = getattr(settings, "business_mode", "") == "store"

    def note_control(key: str) -> ft.Text:
        return ft.Text("", key=key, size=12, visible=False)

    def show(note: ft.Text, text: str, ok: bool) -> None:
        note.value = text
        note.color = theme.SUCCESS if ok else theme.DANGER
        note.visible = bool(text)
        page.update()

    def dd(key: str, label: str, options: list, value, width: int = 260, on_select=None) -> ft.Dropdown:
        return ft.Dropdown(key=key, label=label, border_radius=10, width=width, value=value, on_select=on_select,
                           options=[ft.DropdownOption(key=k, text=text) for k, text in options])

    def tile(key: str, title: str, controls: list, expanded: bool = False) -> ft.Control:
        return card(page, ft.ExpansionTile(key=key, expanded=expanded, title=ft.Text(title, size=14.5, weight=ft.FontWeight.W_600), controls=[
            ft.Container(padding=ft.Padding.only(left=6, right=6, bottom=12), content=ft.Column(spacing=10, controls=controls))]), padding=6)

    def int_field(raw: str, lo: int, hi: int, label: str) -> int:
        digits = cf.normalize_input(raw or "", 12).replace(",", "")
        if not digits.lstrip("-").isdigit() or not lo <= int(digits) <= hi:
            raise ValueError(f"«{label}» باید عددی بینِ {lo} و {hi} باشه." if lang != "en" else f"“{label}” must be a number between {lo} and {hi}.")
        return int(digits)

    # ============================================================ ۱) حالت و منو
    current_mode = modes.resolve_mode(settings).id
    advanced_modes = ("shop_ai", "lead_capture")  # N3: زیرِ «پیشرفته»
    show_adv_modes = ft.Switch(key="exp_show_advanced_modes", label=S("adv_modes.switch", lang), value=current_mode in advanced_modes)

    def mode_options() -> list:
        ids = [m for m in modes.mode_ids() if (is_store or not modes.MODES[m].needs_store) and (m not in advanced_modes or show_adv_modes.value or m == current_mode)]
        return [(m, S(f"mode.{m}", lang)) for m in ids]

    mode_dd = dd("exp_mode", S("mode.label", lang), mode_options(), current_mode, 340)

    def on_adv_modes(e=None) -> None:
        mode_dd.options = [ft.DropdownOption(key=k, text=text) for k, text in mode_options()]
        page.update()

    show_adv_modes.on_change = on_adv_modes
    lang_dd = dd("exp_lang", S("lang.label", lang), [(k, S(f"lang.{k}", lang)) for k in ("fa", "en", "auto")], settings.bot_language if settings.bot_language in ("fa", "en", "auto") else "fa", 260)
    page_size = ft.TextField(key="exp_page_size", label=S("page_size", lang), value=str(settings.catalog_page_size), border_radius=10, width=260)
    max_qty = ft.TextField(key="exp_max_qty", label=S("max_qty", lang), value=str(settings.max_qty_per_item), border_radius=10, width=260)
    disclosure = ft.Switch(key="exp_disclosure", label=S("disclosure", lang), value=bool(settings.ai_disclosure_enabled))
    mode_note = note_control("exp_mode_note")
    catalog_note = note_control("exp_catalog_note")

    def save_mode(e=None, note: ft.Text = None) -> None:
        note = note or mode_note
        try:
            size = int_field(page_size.value, 2, 12, S("page_size", lang))
            qty = int_field(max_qty.value, 1, 99, S("max_qty", lang))
        except ValueError as exc:
            show(note, str(exc), False)
            return
        settings.shop_mode = mode_dd.value or modes.DEFAULT_STORE_MODE
        settings.bot_language = lang_dd.value or "fa"
        settings.catalog_page_size, settings.max_qty_per_item = size, qty
        settings.ai_disclosure_enabled = bool(disclosure.value)
        save_callback()
        show(note, S("saved", lang), True)

    # N3: بخشِ پایه فقط حالت/زبان/هشدارِ هوش مصنوعی؛ اندازه‌ی صفحه و حداکثرِ تعداد در تبِ «فروشگاه»
    mode_section = tile("sec_mode", S("sec.mode", lang), [mode_dd, lang_dd, disclosure,
                                                          ft.Button(key="exp_mode_save", content=S("save", lang), on_click=save_mode), mode_note], expanded=True)
    catalog_section = tile("sec_catalog", S("sec.catalog", lang), [ft.Row(spacing=10, wrap=True, controls=[page_size, max_qty]),
                                                                    ft.Button(key="exp_catalog_save", content=S("save", lang), on_click=lambda e: save_mode(note=catalog_note)), catalog_note], expanded=True)

    def on_wizard_applied() -> None:
        """بعد از «راه‌اندازیِ سریع»: کنترل‌های همین صفحه را با تنظیماتِ تازه هماهن‌گ کن."""
        mode_dd.value = modes.resolve_mode(settings).id
        page_size.value, max_qty.value = str(settings.catalog_page_size), str(settings.max_qty_per_item)
        disclosure.value = bool(settings.ai_disclosure_enabled)
        ui_f["fields"] = [dict(vars(f)) for f in cf.load_fields(settings)]
        render_fields()
        on_adv_modes()

    wizard_section = quick_setup_card.build(page, lang, settings, save_callback, on_wizard_applied)

    # ====================================================== ۲) فیلدهای چک‌اوت
    ui_f: dict = {"fields": [dict(vars(f)) for f in cf.load_fields(settings)], "edit": None}
    f_list = ft.Column(key="exp_fields_list", spacing=6)
    f_note = note_control("exp_fields_note")
    f_id = ft.TextField(key="fld_id", label=S("f.id", lang), border_radius=10, width=200)
    f_label = ft.TextField(key="fld_label", label=S("f.label", lang), border_radius=10, width=240)
    f_prompt = ft.TextField(key="fld_prompt", label=S("f.prompt", lang), border_radius=10)
    f_type = dd("fld_type", S("f.type", lang), [(k, S(f"ftype.{k}", lang)) for k in cf.FIELD_TYPES], "text", 200)
    f_applies = dd("fld_applies", S("f.applies", lang), [(k, S(f"applies.{k}", lang)) for k in cf.APPLIES_TO], "all", 200)
    f_required = ft.Switch(key="fld_required", label=S("f.required", lang), value=True)
    f_regex = ft.TextField(key="fld_regex", label=S("f.regex", lang), border_radius=10)
    f_choices = ft.TextField(key="fld_choices", label=S("f.choices", lang), border_radius=10, multiline=True, min_lines=2, max_lines=5)
    f_min = ft.TextField(key="fld_min", label=S("f.min", lang), border_radius=10, width=130, value="0")
    f_max = ft.TextField(key="fld_max", label=S("f.max", lang), border_radius=10, width=130, value="200")
    f_form = ft.Container(key="exp_field_form", visible=False, content=ft.Column(spacing=8, controls=[
        ft.Row(spacing=10, wrap=True, controls=[f_label, f_type, f_applies]), f_prompt, f_required, f_choices,
        ft.ExpansionTile(key="fld_advanced", expanded=False, title=ft.Text(S("f.advanced", lang), size=13), controls=[
            ft.Container(padding=ft.Padding.only(left=6, right=6, bottom=8), content=ft.Column(spacing=8, controls=[f_id, f_regex, ft.Row(spacing=10, controls=[f_min, f_max])]))]),
        ft.Row(spacing=8, controls=[ft.Button(key="fld_save", content=S("save", lang), on_click=lambda e: save_field()),
                                    ft.TextButton(key="fld_cancel", content=S("cancel", lang), on_click=lambda e: close_field_form())])]))

    def persist_fields(new_list: list) -> bool:
        error = cf.validate_all(new_list)
        if error:
            show(f_note, error, False)
            return False
        ui_f["fields"] = new_list
        settings.checkout_fields = new_list
        save_callback()
        render_fields()
        show(f_note, S("saved", lang), True)
        return True

    def render_fields() -> None:
        rows = []
        for i, f in enumerate(ui_f["fields"]):
            info = f"{f['label']}  ·  {S('ftype.' + str(f['type']), lang)}  ·  {'●' if f.get('required', True) else '○'}  ·  {S('applies.' + str(f.get('applies_to', 'all')), lang)}"
            rows.append(ft.Row(spacing=4, controls=[
                ft.Text(info, size=13, expand=True),
                ft.IconButton(key=f"fld_up_{i}", icon=ft.Icons.ARROW_UPWARD_ROUNDED, on_click=lambda e, i=i: move_field(i, -1)),
                ft.IconButton(key=f"fld_down_{i}", icon=ft.Icons.ARROW_DOWNWARD_ROUNDED, on_click=lambda e, i=i: move_field(i, 1)),
                ft.IconButton(key=f"fld_edit_{i}", icon=ft.Icons.EDIT_OUTLINED, tooltip=S("edit", lang), on_click=lambda e, i=i: open_field_form(i)),
                ft.IconButton(key=f"fld_del_{i}", icon=ft.Icons.DELETE_OUTLINE_ROUNDED, tooltip=S("delete", lang), on_click=lambda e, i=i: delete_field(i)),
            ]))
        f_list.controls = rows

    def move_field(i: int, delta: int) -> None:
        j = i + delta
        if 0 <= j < len(ui_f["fields"]):
            items = list(ui_f["fields"])
            items[i], items[j] = items[j], items[i]
            persist_fields(items)

    def delete_field(i: int) -> None:
        items = [f for k, f in enumerate(ui_f["fields"]) if k != i]
        if not items:
            show(f_note, "حداقل یک فیلد لازمه." if lang != "en" else "At least one field is required.", False)
            return
        persist_fields(items)

    def open_field_form(i=None) -> None:
        ui_f["edit"] = i
        f = ui_f["fields"][i] if i is not None else {"id": "", "label": "", "prompt": "", "type": "text", "required": True, "applies_to": "all", "regex": "", "choices": [], "min_len": 0, "max_len": 200}
        f_id.value, f_label.value, f_prompt.value = f["id"], f["label"], f["prompt"]
        f_type.value, f_applies.value, f_required.value = f.get("type", "text"), f.get("applies_to", "all"), bool(f.get("required", True))
        f_regex.value, f_choices.value = f.get("regex", ""), "\n".join(f.get("choices", []))
        f_min.value, f_max.value = str(f.get("min_len", 0)), str(f.get("max_len", 200))
        f_form.visible = True
        page.update()

    def close_field_form() -> None:
        f_form.visible = False
        page.update()

    def save_field() -> None:
        try:
            lo, hi = int(cf.normalize_input(f_min.value or "0", 6) or 0), int(cf.normalize_input(f_max.value or "200", 6) or 200)
        except ValueError:
            show(f_note, S("f.min", lang) + "/" + S("f.max", lang) + " ?", False)
            return
        taken = {f["id"] for f in ui_f["fields"]}
        auto = next(f"f{n}" for n in range(1, 100) if f"f{n}" not in taken)  # شناسه‌ی داخلی را کاربرِ عادی لازم نیست بنویسه
        item = {"id": (f_id.value or "").strip() or auto, "label": (f_label.value or "").strip(), "prompt": (f_prompt.value or "").strip(), "type": f_type.value or "text",
                "required": bool(f_required.value), "applies_to": f_applies.value or "all", "regex": (f_regex.value or "").strip(),
                "choices": [c.strip() for c in (f_choices.value or "").splitlines() if c.strip()], "min_len": lo, "max_len": hi}
        items = list(ui_f["fields"])
        if ui_f["edit"] is None:
            items.append(item)
        else:
            items[ui_f["edit"]] = item
        if persist_fields(items):
            f_form.visible = False
            page.update()

    tpl_dd = dd("fld_template", S("f.template", lang), [(k, S(f"tpl.{k}", lang)) for k in ("physical", "digital", "services")], "physical", 220)

    def apply_template(e=None) -> None:
        chosen = cf.templates("en" if lang == "en" else "fa").get(tpl_dd.value or "physical", [])
        persist_fields([dict(vars(f)) for f in chosen])

    def restore_defaults(e=None) -> None:
        settings.checkout_fields = []
        save_callback()
        ui_f["fields"] = [dict(vars(f)) for f in cf.load_fields(settings)]
        render_fields()
        show(f_note, S("saved", lang), True)

    render_fields()
    fields_section = tile("sec_fields", S("sec.fields", lang), [
        f_list, ft.Row(spacing=8, wrap=True, controls=[ft.Button(key="fld_add", content=S("add", lang), icon=ft.Icons.ADD_ROUNDED, on_click=lambda e: open_field_form(None)),
                                                       tpl_dd, ft.OutlinedButton(key="fld_apply_tpl", content=S("f.apply_template", lang), on_click=apply_template),
                                                       ft.TextButton(key="fld_defaults", content=S("f.defaults", lang), on_click=restore_defaults)]),
        f_form, f_note])

    # ======================================================== ۳) دکمه‌های منو
    ui_b: dict = {"buttons": [dict(b) for b in (settings.custom_buttons or []) if isinstance(b, dict)], "edit": None}
    b_list = ft.Column(key="exp_buttons_list", spacing=6)
    b_note = note_control("exp_buttons_note")
    b_id = ft.TextField(key="btn_id", label=S("f.id", lang), border_radius=10, width=160)
    b_label = ft.TextField(key="btn_label", label=S("f.label", lang), border_radius=10, width=220)
    b_emoji = ft.TextField(key="btn_emoji", label=S("b.emoji", lang), border_radius=10, width=100)
    b_action = dd("btn_action", S("b.action", lang), [(a, S(f"act.{a}", lang)) for a in cb.ACTIONS], "text", 240)
    b_value = ft.TextField(key="btn_value", label=S("b.value", lang), border_radius=10, multiline=True, min_lines=1, max_lines=4)
    b_tg = ft.Switch(key="btn_tg", label="Telegram", value=True)
    b_bale = ft.Switch(key="btn_bale", label="Bale", value=True)
    b_form = ft.Container(key="exp_button_form", visible=False, content=ft.Column(spacing=8, controls=[
        ft.Row(spacing=10, wrap=True, controls=[b_label, b_emoji, b_action]), b_value, ft.Row(spacing=12, controls=[b_tg, b_bale]),
        ft.ExpansionTile(key="btn_advanced", expanded=False, title=ft.Text(S("f.advanced", lang), size=13), controls=[ft.Container(padding=ft.Padding.only(left=6, right=6, bottom=8), content=b_id)]),
        ft.Row(spacing=8, controls=[ft.Button(key="btn_save", content=S("save", lang), on_click=lambda e: save_button()),
                                    ft.TextButton(key="btn_cancel", content=S("cancel", lang), on_click=lambda e: (setattr(b_form, "visible", False), page.update()))])]))
    _VALUE_KEY = {"url": "url", "phone": "phone", "text": "text", "ask_ai": "question"}

    def persist_buttons(items: list) -> bool:
        error = cb.validate_all(items)
        if error:
            show(b_note, error, False)
            return False
        ui_b["buttons"] = items
        settings.custom_buttons = items
        save_callback()
        render_buttons()
        show(b_note, S("saved", lang), True)
        return True

    def render_buttons() -> None:
        b_list.controls = [
            ft.Row(spacing=4, controls=[
                ft.Text(f"{b.get('emoji', '')} {b.get('label', '')}  ·  {S('act.' + b.get('action', 'text'), lang)}", size=13, expand=True),
                ft.IconButton(key=f"btn_edit_{i}", icon=ft.Icons.EDIT_OUTLINED, tooltip=S("edit", lang), on_click=lambda e, i=i: open_button_form(i)),
                ft.IconButton(key=f"btn_del_{i}", icon=ft.Icons.DELETE_OUTLINE_ROUNDED, tooltip=S("delete", lang),
                              on_click=lambda e, i=i: persist_buttons([x for k, x in enumerate(ui_b["buttons"]) if k != i])),
            ]) for i, b in enumerate(ui_b["buttons"])
        ]

    def open_button_form(i=None) -> None:
        ui_b["edit"] = i
        b = ui_b["buttons"][i] if i is not None else {"id": "", "label": "", "emoji": "", "action": "text", "config": {}, "platforms": ["telegram", "bale"]}
        b_id.value, b_label.value, b_emoji.value, b_action.value = b.get("id", ""), b.get("label", ""), b.get("emoji", ""), b.get("action", "text")
        b_value.value = str((b.get("config") or {}).get(_VALUE_KEY.get(b.get("action", "text"), "text"), ""))
        plats = b.get("platforms", ["telegram", "bale"])
        b_tg.value, b_bale.value = "telegram" in plats, "bale" in plats
        b_form.visible = True
        page.update()

    def save_button() -> None:
        action = b_action.value or "text"
        config = {_VALUE_KEY[action]: (b_value.value or "").strip()} if action in _VALUE_KEY else {}
        taken_b = {b["id"] for b in ui_b["buttons"]}
        auto_b = next(f"b{n}" for n in range(1, 100) if f"b{n}" not in taken_b)
        item = {"id": (b_id.value or "").strip() or auto_b, "label": (b_label.value or "").strip(), "emoji": (b_emoji.value or "").strip(), "action": action,
                "config": config, "platforms": [p for p, on in (("telegram", b_tg.value), ("bale", b_bale.value)) if on]}
        items = list(ui_b["buttons"])
        if ui_b["edit"] is None:
            items.append(item)
        else:
            items[ui_b["edit"]] = item
        if persist_buttons(items):
            b_form.visible = False
            page.update()

    render_buttons()
    buttons_section = tile("sec_buttons", S("sec.buttons", lang), [
        b_list, ft.Button(key="btn_add", content=S("add", lang), icon=ft.Icons.ADD_ROUNDED, on_click=lambda e: open_button_form(None)), b_form, b_note])

    # ================================================== ۴) سؤالات متداول
    ui_q: dict = {"items": [dict(i) for i in (settings.faq_items or []) if isinstance(i, dict)]}
    q_list = ft.Column(key="exp_faq_list", spacing=6)
    q_note = note_control("exp_faq_note")
    q_q = ft.TextField(key="faq_q", label=S("faq.q", lang), border_radius=10)
    q_a = ft.TextField(key="faq_a", label=S("faq.a", lang), border_radius=10, multiline=True, min_lines=2, max_lines=6)

    def persist_faq(items: list) -> None:
        ui_q["items"] = items
        settings.faq_items = items
        save_callback()
        render_faq()

    def render_faq() -> None:
        q_list.controls = [ft.Row(spacing=4, controls=[
            ft.Text(str(it.get("q", ""))[:70], size=13, expand=True),
            ft.IconButton(key=f"faq_del_{i}", icon=ft.Icons.DELETE_OUTLINE_ROUNDED, tooltip=S("delete", lang),
                          on_click=lambda e, i=i: persist_faq([x for k, x in enumerate(ui_q["items"]) if k != i]))]) for i, it in enumerate(ui_q["items"])]

    def add_faq(e=None) -> None:
        q, a = (q_q.value or "").strip(), (q_a.value or "").strip()
        if not q or not a:
            show(q_note, S("faq.q", lang) + " / " + S("faq.a", lang) + " ؟" if lang != "en" else "Question and answer are required.", False)
            return
        if len(ui_q["items"]) >= 30:
            show(q_note, S("faq.limit", lang), False)
            return
        persist_faq([*ui_q["items"], {"q": q[:200], "a": a[:800]}])
        q_q.value = q_a.value = ""
        show(q_note, S("saved", lang), True)

    render_faq()
    faq_section = tile("sec_faq", S("sec.faq", lang), [q_list, q_q, q_a, ft.Button(key="faq_add", content=S("add", lang), icon=ft.Icons.ADD_ROUNDED, on_click=add_faq), q_note])

    # ======================================================== ۵) پیام‌های ربات (N3)
    texts_section = texts_editor.build(page, lang, settings, save_callback)

    # ========================================== ۶) ساعت کاری و پشتیبانی
    wh = settings.working_hours if isinstance(settings.working_hours, dict) else {}
    h_enabled = ft.Switch(key="wh_enabled", label=S("h.enabled", lang), value=bool(wh.get("enabled")))
    day_fields = {d: ft.TextField(key=f"wh_{d}", label=S(f"d.{d}", lang), border_radius=10, width=210, hint_text="09:00-17:00",
                                  value=", ".join((wh.get("days") or {}).get(d, []))) for d in ("sat", "sun", "mon", "tue", "wed", "thu", "fri")}
    h_message = ft.TextField(key="wh_message", label=S("h.message", lang), border_radius=10, value=str(wh.get("message", "")))
    h_timeout = ft.TextField(key="wh_timeout", label=S("h.timeout", lang), border_radius=10, width=300, value=str(settings.handoff_timeout_hours))
    h_note = note_control("wh_note")

    def save_hours(e=None) -> None:
        days = {d: [p.strip() for p in (f.value or "").split(",") if p.strip()] for d, f in day_fields.items()}
        days = {d: v for d, v in days.items() if v}
        raw = {"enabled": bool(h_enabled.value), "tz": "Asia/Tehran", "days": days, "message": (h_message.value or "").strip()}
        error = working_hours.validate(raw)
        if error:
            show(h_note, error, False)
            return
        try:
            timeout = int_field(h_timeout.value, 1, 720, S("h.timeout", lang))
        except ValueError as exc:
            show(h_note, str(exc), False)
            return
        settings.working_hours, settings.handoff_timeout_hours = raw, timeout
        save_callback()
        show(h_note, S("saved", lang), True)

    hours_section = tile("sec_hours", S("sec.hours", lang), [
        ft.Text(S("h.note", lang), size=12, color=theme.text_secondary(page)), h_enabled, ft.Text(S("h.hint", lang), size=11, color=theme.text_secondary(page)),
        ft.Row(spacing=10, wrap=True, controls=list(day_fields.values())), h_message, h_timeout, ft.Button(key="wh_save", content=S("save", lang), on_click=save_hours), h_note])

    # ========================================== ۷) مصرف و محدودیت
    def usage_text() -> str:
        limits = getattr(manager, "limits", None) if manager is not None else None
        try:
            totals = limits.totals() if limits is not None else {"ai_calls": 0, "tokens_est": 0, "chats": 0, "cap_total": settings.max_ai_messages_per_day_total}
        except Exception:  # noqa: BLE001
            totals = {"ai_calls": 0, "tokens_est": 0, "chats": 0, "cap_total": settings.max_ai_messages_per_day_total}
        cap = totals["cap_total"] or "∞"
        return S("l.today", lang, calls=totals["ai_calls"], cap=cap, tokens=totals["tokens_est"], chats=totals["chats"])

    usage_info = ft.Text(usage_text(), key="lim_usage", size=13)
    l_chat = ft.TextField(key="lim_per_chat", label=S("l.per_chat", lang), border_radius=10, width=320, value=str(settings.max_ai_messages_per_chat_per_day))
    l_total = ft.TextField(key="lim_total", label=S("l.total", lang), border_radius=10, width=320, value=str(settings.max_ai_messages_per_day_total))
    l_retention = ft.TextField(key="lim_retention", label=S("l.retention", lang), border_radius=10, width=320, value=str(settings.retention_days))
    l_note = note_control("lim_note")

    def toggle_kill(e=None) -> None:  # اثرِ فوری، بدونِ نیاز به دکمه‌ی «ذخیره»
        settings.ai_kill_switch = bool(l_kill.value)
        save_callback()
        show(l_note, S("saved", lang), True)

    l_kill = ft.Switch(key="lim_kill", label=S("l.kill", lang), value=bool(settings.ai_kill_switch), on_change=toggle_kill)

    def save_limits(e=None) -> None:
        try:
            per_chat = int_field(l_chat.value, 0, 100000, S("l.per_chat", lang))
            total = int_field(l_total.value, 0, 1000000, S("l.total", lang))
            retention = int_field(l_retention.value, 0, 3650, S("l.retention", lang))
        except ValueError as exc:
            show(l_note, str(exc), False)
            return
        settings.max_ai_messages_per_chat_per_day, settings.max_ai_messages_per_day_total, settings.retention_days = per_chat, total, retention
        save_callback()
        usage_info.value = usage_text()
        show(l_note, S("saved", lang), True)

    limits_section = tile("sec_limits", S("sec.limits", lang), [usage_info, l_kill, ft.Row(spacing=10, wrap=True, controls=[l_chat, l_total, l_retention]),
                                                                 ft.Button(key="lim_save", content=S("save", lang), on_click=save_limits), l_note])

    # ============================================ ۸) نیاز به توجه
    inbox_col = ft.Column(key="exp_inbox_list", spacing=6)
    inbox = getattr(manager, "attention", None) if manager is not None else None

    def render_inbox() -> None:
        items = inbox.list_open() if inbox is not None else []
        waiting = order_store.count_by_status("paid") if order_store is not None else 0
        head = [ft.Text(S("i.orders_waiting", lang, n=waiting), key="inbox_orders_waiting", size=13, color=theme.DANGER)] if waiting else []
        if not items:
            inbox_col.controls = head or [ft.Text(S("i.empty", lang), size=13, color=theme.text_secondary(page))]
            return
        inbox_col.controls = head + [ft.Row(spacing=6, controls=[
            ft.Text(f"{S('i.' + it.type, lang)} — {it.ref} {it.detail}".strip(), size=13, expand=True),
            ft.TextButton(key=f"inbox_done_{it.id}", content=S("i.done", lang), on_click=lambda e, i=it.id: (inbox.handle(i), render_inbox(), page.update()))]) for it in items]

    def inbox_all(e=None) -> None:
        if inbox is not None:
            inbox.handle_all()
        render_inbox()
        page.update()

    render_inbox()
    inbox_section = tile("sec_inbox", S("sec.inbox", lang), [inbox_col, ft.TextButton(key="inbox_all", content=S("i.all", lang), on_click=inbox_all)])

    # ============================================ پروفایلِ ربات (N17)
    profile_section = bot_profile_card.build(page, lang, settings, save_callback, manager)

    # ============================================ عضویتِ اجباریِ کانال (N13)
    channels_section = required_channels_card.build(page, lang, settings, save_callback, manager)

    # ================================================ ۹) پیش‌نمایش
    preview_section = tile("sec_preview", S("sec.preview", lang), [customer_preview.build(page, lang, settings, product_store, order_store)])

    adv_modes_section = tile("sec_adv_modes", S("sec.adv_modes", lang), [ft.Text(S("adv_modes.note", lang), size=12.5, color=theme.text_secondary(page)), show_adv_modes])

    # N3: چهار تب (شروع سریع · فروشگاه · پیام‌ها · پیشرفته)؛ همه‌ی کنترل‌ها همیشه در درخت‌اند (فقط نمایش عوض می‌شه)
    shop_hint = ft.Text(S("shop.only", lang), key="exp_shop_hint", size=12.5, color=theme.text_secondary(page), visible=not is_store)
    tab_defs = [
        ("quick", S("tab.quick", lang), [wizard_section, mode_section, profile_section, preview_section]),
        ("shop", S("tab.shop", lang), [shop_hint, catalog_section, fields_section, buttons_section]),
        ("messages", S("tab.messages", lang), [texts_section, faq_section]),
        ("advanced", S("tab.advanced", lang), [hours_section, channels_section, limits_section, inbox_section, adv_modes_section]),
    ]
    panels = {tid: ft.Column(key=f"exp_panel_{tid}", spacing=14, visible=(tid == "quick"), controls=ctrls) for tid, _label, ctrls in tab_defs}
    tab_buttons: dict = {}
    current_tab = {"id": "quick"}

    def style_tabs() -> None:
        for tid, btn in tab_buttons.items():
            selected = tid == current_tab["id"]
            btn.style = ft.ButtonStyle(
                bgcolor=theme.PRIMARY if selected else None,
                color="#FFFFFF" if selected else None,
                shape=ft.RoundedRectangleBorder(radius=10),
            )

    def select_tab(tid: str) -> None:
        current_tab["id"] = tid
        for pid, panel in panels.items():
            panel.visible = pid == tid
        style_tabs()
        page.update()

    for tid, label, _ctrls in tab_defs:
        tab_buttons[tid] = ft.TextButton(key=f"exp_tab_{tid}", content=label, on_click=lambda e, t=tid: select_tab(t))
    style_tabs()

    return ft.Container(
        expand=True,
        padding=ft.Padding.symmetric(horizontal=32, vertical=24),
        content=ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=14, controls=[
            page_header(page, ft.Icons.TUNE_ROUNDED, S("title", lang), S("subtitle", lang)),
            ft.Row(key="exp_tabs", spacing=8, wrap=True, controls=list(tab_buttons.values())),
            *panels.values(),
        ]),
    )
