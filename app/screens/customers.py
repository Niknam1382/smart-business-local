"""صفحه‌ی «مشتریان» (N12 — CRM): فهرستِ قابل‌جست‌وجو/فیلتر/مرتب‌سازی، کارتِ جزئیات و خروجیِ CSV.

داده فقط روی همین کامپیوتره (جدولِ ``customers`` در دیتابیسِ مکالمه‌ها). آمارِ خرید از دیتابیسِ سفارش‌ها محاسبه می‌شه.
شماره‌ی تلفن فقط اگه خودِ مشتری با دکمه‌ی «اشتراکِ شماره» داده باشه نشون داده می‌شه. «بلاک» همان بلاکِ گفتگوهاست.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional

import flet as ft

from app import theme
from app.core import customers as crm
from app.core.bot_manager import BotManagerError
from app.core.paths import get_app_data_dir
from app.i18n import t
from app.screens import common
from app.screens.common import card, page_header

MAX_ROWS = 200
_ORDER_ROWS = 5
_CHAT_ROWS = 6
_PLATFORM_ICON = {"telegram": ft.Icons.SEND_ROUNDED, "bale": ft.Icons.CHAT_BUBBLE_OUTLINE_ROUNDED}


def _stamp(ts: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "—"


def _money(amount: int, lang: str) -> str:
    return f"{amount:,} {t('products.price_suffix', lang)}"


def _platform_label(platform: str, lang: str) -> str:
    key = f"chats.platform.{platform}"
    return t(key, lang) if platform in ("telegram", "bale") else platform


def build(page: ft.Page, lang: str, manager, order_store=None, export_dir: Optional[Callable[[], Path]] = None) -> ft.Control:
    store = manager.customers
    secondary = theme.text_secondary(page)
    ui = {"search": "", "filter": crm.FILTER_ALL, "sort": crm.SORT_LAST_SEEN, "platform": "", "selected": None, "armed": False, "notice": "", "ok": True, "export_dir": ""}
    body = ft.Column(spacing=12)

    def refresh() -> None:
        body.controls = detail_view() if ui["selected"] else list_view()
        try:
            page.update()
        except Exception:  # noqa: BLE001
            pass

    def say(message: str, ok: bool = True) -> None:
        ui["notice"], ui["ok"] = message, ok

    def notice_line() -> list:
        if not ui["notice"]:
            return []
        controls: list = [ft.Text(ui["notice"], key="customers_notice", size=12.5, color=theme.SUCCESS if ui["ok"] else theme.DANGER)]
        if ui["export_dir"]:
            controls.append(ft.TextButton(key="customers_open_folder", content=t("customers.open_folder", lang), icon=ft.Icons.FOLDER_OPEN_ROUNDED, on_click=lambda e: common.open_folder(ui["export_dir"])))
        return [ft.Column(spacing=2, controls=controls)]

    # ------------------------------------------------------------------ فهرست ----

    def query() -> list:
        return store.list(search=ui["search"], flt=ui["filter"], sort=ui["sort"], platform=ui["platform"] or None)

    def on_search(e) -> None:
        ui["search"] = (e.control.value or "").strip()
        refresh()

    def on_filter(e) -> None:
        ui["filter"] = e.control.value or crm.FILTER_ALL
        refresh()

    def on_sort(e) -> None:
        ui["sort"] = e.control.value or crm.SORT_LAST_SEEN
        refresh()

    def on_platform(e) -> None:
        ui["platform"] = "" if e.control.value in (None, "", "all") else e.control.value
        refresh()

    def on_export(_e=None) -> None:
        folder = export_dir() if export_dir is not None else get_app_data_dir() / "exports"
        path = folder / f"customers-{time.strftime('%Y%m%d-%H%M%S')}.csv"
        try:
            rows = query()
            headers = [t(f"customers.csv.{col}", lang) if col in _CSV_KEYS else col for col in crm.CustomerStore.CSV_COLUMNS]
            count = store.export_csv(path, rows, headers=headers)
        except OSError as exc:
            say(t("customers.export_failed", lang, error=str(exc)), ok=False)
            ui["export_dir"] = ""
        else:
            say(t("customers.export_done", lang, n=count, path=str(path)))
            ui["export_dir"] = str(folder)
        refresh()

    def dropdown(key: str, label: str, options: list, value: str, handler, width: int = 190) -> ft.Dropdown:
        return ft.Dropdown(key=key, label=label, border_radius=10, width=width, value=value, on_select=handler, options=[ft.DropdownOption(key=k, text=txt) for k, txt in options])

    def row_for(c: crm.Customer) -> ft.Control:
        info = [f"@{c.username}"] if c.username else []
        info.append(t("customers.row.orders", lang, n=c.orders_count) + (f" · {_money(c.total_spent_irr, lang)}" if c.orders_count else "") if c.orders_count else t("customers.row.no_orders", lang))
        flags = [t(f"customers.flag.{name}", lang).split(" (")[0] for name, on in (("blocked", c.blocked), ("opted_out", c.opted_out), ("unreachable", c.unreachable)) if on]
        return ft.Container(
            key=f"customer_row_{c.platform}_{c.user_id}",
            on_click=lambda e, c=c: open_detail(c),
            ink=True,
            padding=ft.Padding.symmetric(horizontal=14, vertical=10),
            border_radius=12,
            bgcolor=theme.card_bgcolor(page),
            border=ft.Border.all(1, theme.border_color(page)),
            content=ft.Row(
                spacing=12,
                controls=[
                    ft.Icon(_PLATFORM_ICON.get(c.platform, ft.Icons.PERSON_ROUNDED), size=20, color=theme.PRIMARY),
                    ft.Column(
                        expand=True, spacing=2, tight=True,
                        controls=[
                            ft.Text(c.display_name, size=14, weight=ft.FontWeight.W_600),
                            ft.Text(" · ".join(info), size=12, color=secondary),
                        ],
                    ),
                    *([ft.Text(" · ".join(flags), size=11.5, color=theme.DANGER)] if flags else []),
                    ft.Text(_stamp(c.last_seen_ts), size=11.5, color=secondary),
                ],
            ),
        )

    def list_view() -> list:
        everyone = store.count()
        rows = query()
        shown = rows[:MAX_ROWS]
        controls: list = [
            ft.Row(
                wrap=True, spacing=10, run_spacing=10,
                controls=[
                    ft.TextField(key="customers_search", label=t("customers.search", lang), value=ui["search"], border_radius=10, width=340, on_change=on_search, prefix_icon=ft.Icons.SEARCH_ROUNDED),
                    dropdown("customers_filter", t("customers.filter", lang), [(f, t(f"customers.filter.{f}", lang)) for f in crm.FILTERS], ui["filter"], on_filter),
                    dropdown("customers_sort", t("customers.sort", lang), [(s_, t(f"customers.sort.{s_}", lang)) for s_ in crm.SORTS], ui["sort"], on_sort),
                    dropdown("customers_platform", t("customers.platform", lang), [("all", t("customers.platform.all", lang)), ("telegram", _platform_label("telegram", lang)), ("bale", _platform_label("bale", lang))], ui["platform"] or "all", on_platform, width=170),
                    ft.OutlinedButton(key="customers_export", content=t("customers.export", lang), icon=ft.Icons.FILE_DOWNLOAD_ROUNDED, on_click=on_export),
                ],
            ),
            *notice_line(),
            ft.Text(t("customers.count", lang, shown=len(rows), total=everyone), key="customers_count", size=12.5, color=secondary),
        ]
        if not rows:
            controls.append(card(page, ft.Text(t("customers.empty" if everyone == 0 else "customers.no_match", lang), key="customers_empty", color=secondary)))
        else:
            controls.extend(row_for(c) for c in shown)
            if len(rows) > MAX_ROWS:
                controls.append(ft.Text(t("customers.truncated", lang, n=MAX_ROWS), key="customers_truncated", size=12, color=secondary))
        return controls

    # ------------------------------------------------------------------ جزئیات ----

    def open_detail(c: crm.Customer) -> None:
        ui.update(selected=(c.platform, c.user_id), armed=False, notice="", export_dir="")
        refresh()

    def close_detail(_e=None) -> None:
        ui.update(selected=None, armed=False, notice="", export_dir="")
        refresh()

    def current() -> Optional[crm.Customer]:
        return store.get(*ui["selected"]) if ui["selected"] else None

    def fact(label_key: str, value: str, key: str = "") -> ft.Control:
        return ft.Row(spacing=8, controls=[ft.Text(t(label_key, lang) + ":", size=12.5, color=secondary), ft.Text(value, size=13, selectable=True, key=key or None)])

    def detail_view() -> list:
        c = current()
        if c is None:  # مثلاً /forget همین الان پاکش کرد
            ui["selected"] = None
            return list_view()
        platform, user_id = c.platform, c.user_id
        calls, tokens = store.token_usage(platform, user_id)
        tags_field = ft.TextField(key="customer_tags", label=t("customers.tags", lang), value=", ".join(c.tags), border_radius=10)
        notes_field = ft.TextField(key="customer_notes", label=t("customers.notes", lang), value=c.notes, multiline=True, min_lines=3, max_lines=6, border_radius=10)
        message_field = ft.TextField(key="customer_message", label=t("customers.message", lang), hint_text=t("customers.message_hint", lang), multiline=True, min_lines=2, max_lines=5, border_radius=10)

        def on_save(_e=None) -> None:
            store.set_tags(platform, user_id, tags_field.value or "")
            store.set_notes(platform, user_id, notes_field.value or "")
            say(t("customers.saved", lang))
            refresh()

        def on_block(_e=None) -> None:
            now_blocked = not manager.store.is_blocked(platform, user_id)
            manager.store.ensure_conversation(platform, user_id)  # ردیفِ مکالمه (جایگاهِ بلاک) حتماً باشه
            manager.store.set_blocked(platform, user_id, now_blocked)
            say(t("customers.blocked_ok" if now_blocked else "customers.unblocked_ok", lang))
            refresh()

        def on_optout(e) -> None:
            store.set_opted_out(platform, user_id, bool(e.control.value))
            refresh()

        def on_send(_e=None) -> None:
            text = (message_field.value or "").strip()
            if not text:
                return

            def work() -> None:
                try:
                    manager.send_to_customer_sync(platform, user_id, text)  # N6: همان قوانینِ صفحه‌ی گفتگوها (بلاک/لغو/پیشوند/نقشِ owner)
                except BotManagerError as exc:
                    say(t("customers.send_failed", lang, error=str(exc)), ok=False)
                else:
                    say(t("customers.sent", lang))
                refresh()

            page.run_thread(work)

        def on_delete(_e=None) -> None:
            if not ui["armed"]:
                ui["armed"] = True
                refresh()
                return
            store.delete(platform, user_id)
            ui.update(selected=None, armed=False)
            say(t("customers.deleted", lang))
            refresh()

        flags = [t(f"customers.flag.{name}", lang) for name, on in (("blocked", c.blocked), ("opted_out", c.opted_out), ("unreachable", c.unreachable)) if on]
        profile = card(
            page,
            ft.Column(
                spacing=6,
                controls=[
                    ft.Text(c.display_name, key="customer_name", size=19, weight=ft.FontWeight.W_700),
                    *([ft.Text(" · ".join(flags), key="customer_flags", size=12.5, color=theme.DANGER)] if flags else []),
                    fact("customers.d.platform", _platform_label(platform, lang)),
                    fact("customers.d.id", user_id),
                    fact("customers.d.username", f"@{c.username}" if c.username else "—"),
                    fact("customers.d.language", c.language_code or "—"),
                    fact("customers.d.premium", t("customers.d.yes" if c.is_premium else "customers.d.no", lang)),
                    fact("customers.d.phone", c.phone or t("customers.d.phone_none", lang), key="customer_phone"),
                    fact("customers.d.first_seen", _stamp(c.first_seen_ts)),
                    fact("customers.d.last_seen", _stamp(c.last_seen_ts)),
                    fact("customers.d.messages", str(c.msg_count)),
                    fact("customers.d.orders", str(c.orders_count)),
                    fact("customers.d.spent", _money(c.total_spent_irr, lang)),
                    fact("customers.d.last_order", _stamp(c.last_order_ts)),
                    fact("customers.d.tokens", t("customers.d.tokens_value", lang, calls=calls, tokens=f"{tokens:,}")),
                ],
            ),
        )
        actions = card(
            page,
            ft.Column(
                spacing=10,
                controls=[
                    tags_field,
                    notes_field,
                    ft.OutlinedButton(key="customer_save", content=t("customers.save", lang), on_click=on_save),
                    ft.Row(
                        wrap=True, spacing=10,
                        controls=[
                            ft.OutlinedButton(key="customer_block", content=t("customers.unblock" if c.blocked else "customers.block", lang), icon=ft.Icons.BLOCK_ROUNDED, on_click=on_block),
                            ft.Switch(key="customer_optout", label=t("customers.optout", lang), value=c.opted_out, on_change=on_optout),
                        ],
                    ),
                ],
            ),
        )
        message_card = card(
            page,
            ft.Column(spacing=8, controls=[message_field, ft.OutlinedButton(key="customer_send", content=t("customers.send", lang), icon=ft.Icons.SEND_ROUNDED, on_click=on_send)]),
        )
        orders_controls: list = [ft.Text(t("customers.orders_title", lang), size=14, weight=ft.FontWeight.W_700)]
        recent = list(order_store.list_for_chat(platform, user_id))[:_ORDER_ROWS] if order_store is not None else []  # تازه‌ترین اول
        if not recent:
            orders_controls.append(ft.Text(t("customers.no_orders", lang), size=12.5, color=secondary))
        for order in recent:
            orders_controls.append(ft.Text(f"#{order.id} · {t(f'orders.status.{order.status}', lang)} · {_money(order.total_irr, lang)}", size=12.5, selectable=True))
        history = manager.store.get_messages(platform, user_id, limit=_CHAT_ROWS)
        chat_controls: list = [ft.Text(t("customers.chat_title", lang), size=14, weight=ft.FontWeight.W_700)]
        if not history:
            chat_controls.append(ft.Text(t("customers.no_chat", lang), size=12.5, color=secondary))
        for message in history:
            text = (message.content or "").replace("\n", " ")
            chat_controls.append(ft.Text(f"{t(f'customers.role.{message.role}', lang) if message.role in ('user', 'assistant', 'owner') else message.role}: {text[:140]}", size=12.5, color=secondary))
        return [
            ft.TextButton(key="customers_back", content=t("customers.back", lang), icon=ft.Icons.ARROW_BACK_ROUNDED, on_click=close_detail),
            *notice_line(),
            profile,
            actions,
            message_card,
            card(page, ft.Column(spacing=6, controls=orders_controls)),
            card(page, ft.Column(spacing=6, controls=chat_controls)),
            ft.TextButton(key="customer_delete", content=t("customers.delete_confirm" if ui["armed"] else "customers.delete", lang), icon=ft.Icons.DELETE_OUTLINE_ROUNDED, on_click=on_delete),
        ]

    body.controls = list_view()
    return ft.Column(
        expand=True, spacing=14, scroll=ft.ScrollMode.AUTO,
        controls=[page_header(page, ft.Icons.PEOPLE_ROUNDED, t("customers.title", lang), t("customers.subtitle", lang)), body],
    )


# سرستون‌های CSV (کلیدِ i18n: customers.csv.<ستون>)؛ در i18n ثبت می‌شن
_CSV_KEYS = {
    "platform", "user_id", "name", "username", "phone", "language", "first_seen", "last_seen", "messages", "orders", "total_spent",
    "last_order", "tags", "notes", "blocked", "opted_out", "unreachable",
}
