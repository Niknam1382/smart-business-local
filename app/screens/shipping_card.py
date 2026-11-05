"""«روش‌هایِ ارسال»: فهرستِ خودِ مالک از روش‌ها/هزینه‌ها — پیش‌فرضِ خالی یعنی هیچ‌چیز عوض نمی‌شه.

هر ردیف ``{id, name, price_irr, free_over_irr, active}`` است. ``free_over_irr`` آستانه‌ای است که اگر
جمعِ کلِ سبد (بعد از تخفیف) از آن بیشتر/مساوی باشد، هزینه صفر حساب می‌شه. هیچ مبلغی اینجا به سفارش
اضافه نمی‌شه — فقط تعریف؛ تصمیم‌گیریِ واقعی داخلِ ``shop_flow`` و ``orders`` انجام می‌شه.
"""

from __future__ import annotations

import uuid

import flet as ft

from app import theme
from app.core.settings import normalize_shipping_methods
from app.screens import common

_S = {
    "title": {"fa": "🚚 روش‌هایِ ارسال", "en": "🚚 Shipping methods"},
    "intro": {
        "fa": "تا وقتی اینجا هیچ روشِ فعالی نباشد، هیچ سفارشی هزینه‌ی ارسال نمی‌گیرد و از مشتری هیچ سؤالی پرسیده نمی‌شود. یک روش اضافه کن تا فعال شود.",
        "en": "While no method here is active, no order ever gets a shipping cost and customers are never asked. Add a method to turn it on.",
    },
    "name": {"fa": "نامِ روش (مثلاً «پست پیشتاز»)", "en": "Method name (e.g. “Postal service”)"},
    "price": {"fa": "هزینه (ریال)", "en": "Cost (RIAL)"},
    "free_over": {"fa": "ارسالِ رایگان بالای (ریال، اختیاری)", "en": "Free above (RIAL, optional)"},
    "active": {"fa": "فعال", "en": "Active"},
    "add": {"fa": "افزودنِ روش", "en": "Add method"},
    "delete": {"fa": "حذف", "en": "Remove"},
    "empty": {"fa": "هنوز روشی اضافه نشده — ارسال فعلاً خاموش است.", "en": "No method yet — shipping is still off."},
    "row": {"fa": "{name} · {price}", "en": "{name} · {price}"},
    "row_free": {"fa": " · رایگان بالای {amount}", "en": " · free above {amount}"},
    "row_off": {"fa": " (خاموش)", "en": " (off)"},
    "saved": {"fa": "ذخیره شد.", "en": "Saved."},
    "added": {"fa": "روشِ ارسال اضافه شد.", "en": "Shipping method added."},
    "removed": {"fa": "روشِ ارسال حذف شد.", "en": "Shipping method removed."},
    "need_name": {"fa": "اول یک نام برایِ روش بنویس.", "en": "Write a name for the method first."},
    "need_price": {"fa": "هزینه باید یک عددِ ریالیِ صحیح باشد.", "en": "The cost must be a valid RIAL number."},
    "too_many": {"fa": "بیش از {n} روشِ ارسال نمی‌شه گذاشت — اول یکی را حذف کن.", "en": "At most {n} methods — remove one first."},
}

MAX_NAME = 60
_MAX_METHODS = 12


def _s(key: str, lang: str, **kw) -> str:
    entry = _S[key]
    text = entry["en"] if lang == "en" else entry["fa"]
    return text.format(**kw) if kw else text


def _money(irr: int) -> str:
    return f"{int(irr):,} ریال" if irr else "رایگان"


def build(page: ft.Page, lang: str, settings, save_callback) -> ft.Control:
    secondary = theme.text_secondary(page)
    note = ft.Text("", key="ship_note", size=12.5, visible=False, selectable=True)
    list_col = ft.Column(key="ship_rows", spacing=6)

    def show(text: str, ok: bool = True) -> None:
        note.value, note.color, note.visible = text, theme.SUCCESS if ok else theme.DANGER, bool(text)
        page.update()

    def current() -> list:
        return normalize_shipping_methods(getattr(settings, "shipping_methods", []) or [])

    def store(methods: list) -> None:
        settings.shipping_methods = methods
        save_callback()

    def render_rows() -> None:
        rows: list = []
        for m in current():
            label = _s("row", lang, name=m["name"], price=_money(m["price_irr"]))
            if m["free_over_irr"]:
                label += _s("row_free", lang, amount=_money(m["free_over_irr"]))
            if not m["active"]:
                label += _s("row_off", lang)

            active_box = ft.Checkbox(key=f"ship_active_{m['id']}", value=bool(m["active"]))

            def on_toggle(_e=None, method_id=m["id"], control=active_box) -> None:
                wanted = bool(control.value)
                store([{**x, "active": wanted} if x["id"] == method_id else x for x in current()])
                render_rows()
                show(_s("saved", lang))

            def on_delete(_e=None, method_id=m["id"]) -> None:
                store([x for x in current() if x["id"] != method_id])
                render_rows()
                show(_s("removed", lang))

            active_box.on_change = on_toggle
            rows.append(
                ft.Row(
                    key=f"ship_row_{m['id']}",
                    spacing=8,
                    wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Text(label, size=13, weight=ft.FontWeight.W_600),
                        active_box,
                        ft.TextButton(key=f"ship_del_{m['id']}", content=_s("delete", lang), on_click=on_delete),
                    ],
                )
            )
        list_col.controls = rows or [ft.Text(_s("empty", lang), size=12.5, color=secondary)]

    name_tf = ft.TextField(key="ship_name", label=_s("name", lang), border_radius=10, width=250, max_length=MAX_NAME)
    price_tf = ft.TextField(
        key="ship_price", label=_s("price", lang), border_radius=10, width=150, keyboard_type=ft.KeyboardType.NUMBER, text_align=ft.TextAlign.LEFT
    )
    free_tf = ft.TextField(
        key="ship_free_over", label=_s("free_over", lang), border_radius=10, width=190, keyboard_type=ft.KeyboardType.NUMBER, text_align=ft.TextAlign.LEFT
    )

    def parse_number(raw: str):
        """عددِ ریالیِ فیلدِ UI — فارسی/عربیِ digits هم می‌پذیرد؛ متنِ بی‌معنی ⇒ ``None`` (صفرِ بی‌سروصدا نه)."""
        text = (raw or "").strip().replace("٬", "").replace(",", "")
        if not text:
            return 0
        return int(text) if all(ch.isdigit() for ch in text) else None

    def on_add(_e=None) -> None:
        name = (name_tf.value or "").strip()[:MAX_NAME]
        if not name:
            show(_s("need_name", lang), False)
            return
        existing = current()
        if len(existing) >= _MAX_METHODS:
            show(_s("too_many", lang, n=_MAX_METHODS), False)
            return
        price = parse_number(price_tf.value)
        free_over = parse_number(free_tf.value)
        if price is None or free_over is None:
            show(_s("need_price", lang), False)
            return
        store([*existing, {"id": uuid.uuid4().hex[:12], "name": name, "price_irr": price, "free_over_irr": free_over, "active": True}])
        name_tf.value = price_tf.value = free_tf.value = ""
        render_rows()
        show(_s("added", lang))

    render_rows()
    return common.card(
        page,
        ft.Column(
            key="shipping_methods_card",
            spacing=10,
            controls=[
                ft.Text(_s("title", lang), size=15, weight=ft.FontWeight.W_700),
                ft.Text(_s("intro", lang), size=12.5, color=secondary),
                list_col,
                ft.Row(spacing=10, wrap=True, vertical_alignment=ft.CrossAxisAlignment.START, controls=[name_tf, price_tf, free_tf]),
                ft.FilledButton(key="ship_add", content=_s("add", lang), icon=ft.Icons.ADD_ROUNDED, on_click=on_add),
                note,
            ],
        ),
    )
