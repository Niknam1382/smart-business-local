"""«جست‌وجو» (A2): یک کلمه، نتیجه‌ها در سه گروه — سفارش‌ها، کالاها، مشتریان.

فقط از دیتابیسِ محلی می‌خواند (همه‌ی LIKEها پارامتری‌اند) و لینکِ «برو به صفحه‌ی …» همان چیزی است
که قبلاً دستی جست‌وجو می‌شد: صاحبِ فروشگاه شماره‌ی سفارش یا نیم‌نامِ مشتری را می‌نویسد و به همان
صفحه می‌رود. جزئیاتِ ناورداییِ مبلغ اینجا نیست: صفحه فقط نشان می‌دهد، چیزی عوض نمی‌کند.
"""

from __future__ import annotations

from typing import Callable

import flet as ft

from app import theme
from app.core import search as engine
from app.i18n import STRINGS, t
from app.screens import common
from app.screens.common import page_header, screen_frame

_S = {
    "title": {"fa": "جست‌وجوی سراسری", "en": "Global search"},
    "subtitle": {"fa": "شماره‌ی سفارش، نامِ کالا، نام یا شماره‌ی مشتری — همه‌جا یک‌جا.",
                 "en": "Order number, product name, customer name or phone — all in one place."},
    "hint": {"fa": "مثلاً: ۱۲۳، هدفون، علی رضایی", "en": "e.g. 123, headphones, Ali Rezaei"},
    "run": {"fa": "جست‌وجو", "en": "Search"},
    "orders": {"fa": "سفارش‌ها", "en": "Orders"},
    "products": {"fa": "کالاها", "en": "Products"},
    "customers": {"fa": "مشتریان", "en": "Customers"},
    "empty": {"fa": "چیزی پیدا نشد. یک‌دو حرفِ کافی است؛ اگر مطمئنی هست، املا را ساده‌تر بنویس.",
              "en": "Nothing found. A letter or two is enough — try a simpler spelling."},
    "idle": {"fa": "چیزی بنویس تا نتیجه‌ها بیایند.", "en": "Type something to see results."},
    "open": {"fa": "برو به این صفحه", "en": "Open this page"},
    "count": {"fa": "{n} نتیجه", "en": "{n} results"},
    "none_in": {"fa": "—", "en": "—"},
}


def _s(key: str, lang: str) -> str:
    entry = _S[key]
    return entry["en"] if lang == "en" else entry["fa"]


def _money(amount: int, lang: str) -> str:
    suffix = t("products.price_suffix", lang) if "products.price_suffix" in STRINGS else ("ریال" if lang != "en" else "RIAL")
    return f"{int(amount):,} {suffix}"


def build(page: ft.Page, lang: str, orders=None, products=None, customers=None,
          on_open: Callable[[str], None] | None = None) -> ft.Control:
    secondary = theme.text_secondary(page)
    state = {"term": "", "results": {group: [] for group in engine.GROUPS}, "searched": False}

    field = ft.TextField(
        key="gs_field",
        label=_s("hint", lang),
        value="",
        text_size=15,
        border_radius=12,
        on_submit=lambda _e: run(),
        on_change=lambda e: state.__setitem__("term", e.control.value or ""),
    )
    run_btn = common.primary(_s("run", lang), key="gs_run", icon=ft.Icons.SEARCH_ROUNDED, on_click=lambda _e: run())
    count_line = ft.Text("", key="gs_count", size=12.5, color=secondary)
    results = ft.Column(spacing=theme.SPACE_MD, key="gs_results", expand=True)

    def row(label: str, target: str, icon: str) -> ft.Control:
        controls = [ft.Text(label, size=13.5, expand=True)]
        if on_open is not None:
            controls.append(ft.IconButton(icon, key=f"gs_open_{target}", tooltip=_s("open", lang),
                                          icon_size=18, on_click=lambda _e, where=target: on_open(where)))
        return ft.Row(controls, spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def section(title: str, items: list, target: str, icon: str) -> ft.Control | None:
        if not items:
            return None
        head = ft.Text(title, size=13, weight=ft.FontWeight.BOLD, color=secondary)
        return ft.Column([head] + [row(text, target, icon) for text in items], spacing=2)

    def render() -> None:
        rows: list[ft.Control] = []
        if not state["searched"]:
            rows.append(ft.Text(_s("idle", lang), size=13.5, color=secondary))
        else:
            found = state["results"]
            rows = [
                section(_s("orders", lang), [engine.describe_order(o, _money(o.total_irr, lang), t(f"orders.status.{o.status}", lang)) for o in found["orders"]],
                        "orders", ft.Icons.RECEIPT_LONG_ROUNDED),
                section(_s("products", lang), [engine.describe_product(p, _money(p.price_irr, lang)) for p in found["products"]],
                        "products", ft.Icons.INVENTORY_2_ROUNDED),
                section(_s("customers", lang), [engine.describe_customer(c) for c in found["customers"]],
                        "customers", ft.Icons.PEOPLE_ROUNDED),
            ]
            rows = [r for r in rows if r is not None]
            if not rows:
                rows.append(ft.Text(_s("empty", lang), size=13.5, color=secondary))
        results.controls.clear()
        results.controls.extend(rows)
        count_line.value = _s("count", lang).format(n=engine.count(state["results"])) if state["searched"] else ""
        page.update()

    def run() -> None:
        state["results"] = engine.global_search(state["term"], orders=orders, products=products, customers=customers)
        state["searched"] = True
        render()

    render()
    header = page_header(page, ft.Icons.SEARCH_ROUNDED, _s("title", lang), _s("subtitle", lang))
    top = ft.Row([ft.Column([field], spacing=0, expand=True), run_btn], spacing=10,
                 vertical_alignment=ft.CrossAxisAlignment.CENTER)
    return screen_frame(page, header, [common.card(page, top), common.card(page, ft.Column([count_line, results], spacing=theme.SPACE_SM))])
