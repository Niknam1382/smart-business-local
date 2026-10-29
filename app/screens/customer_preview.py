"""
«پیش‌نمایشِ مشتری» (R8): ربات رو بدونِ تلگرام/بله و بدونِ توکن، همین‌جا امتحان کن — دقیقاً همان ``ShopFlow`` واقعی با
سفارش‌های واقعی (پلتفرمِ «preview»؛ موجودی رزرو می‌شه، «پاک‌کردنِ پیش‌نمایش» سفارش‌های باز رو لغو می‌کنه).
فقط پرداختِ کارت‌به‌کارت در پیش‌نمایش فعاله (هیچ درگاهِ واقعی صدا زده نمی‌شه)؛ متنِ آزاد به AI نمی‌ره.
"""

from __future__ import annotations

import concurrent.futures

import flet as ft

from app import theme
from app.core.bot_pipeline import IncomingMessage
from app.core.orders import METHOD_CARD_TO_CARD, STATUS_PENDING_PAYMENT
from app.core.payments import PaymentHooks, PaymentService
from app.core.shop_flow import ShopFlow
from app.core.ui import FlowResult, UiMessage
from app.screens import common

PREVIEW_PLATFORM = "preview"
PREVIEW_CHAT = "preview-1"
_TEXT = {
    "title": ("پیش‌نمایشِ مشتری", "Customer preview"),
    "help": ("ربات رو همین‌جا امتحان کن: دکمه‌های منو و دکمه‌های داخلِ پیام‌ها مثلِ تلگرام/بله کار می‌کنن.", "Try the bot right here: menu and inline buttons work like Telegram/Bale."),
    "input": ("پیام به ربات…", "Message the bot…"),
    "send": ("ارسال", "Send"),
    "reset": ("پاک‌کردنِ پیش‌نمایش", "Reset preview"),
    "ai_note": ("(در پیش‌نمایش پاسخِ AI ساخته نمی‌شه؛ در ربات واقعی این پیام به هوش مصنوعی می‌رسه.)", "(AI replies are not generated in the preview; in the real bot this goes to the AI.)"),
    "start": ("شروع (/start)", "Start (/start)"),
}


def _tx(key: str, lang: str) -> str:
    fa, en = _TEXT[key]
    return en if lang == "en" else fa


def _run(coro):
    """coroutine رو روی یه تردِ تازه (با event loopِ خودش) اجرا می‌کنه — از داخلِ هر handlerِ Flet امنه."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        import asyncio

        return pool.submit(lambda: asyncio.run(coro)).result(timeout=60)


def build(page: ft.Page, lang: str, settings, product_store, order_store) -> ft.Control:
    async def _noop(_text: str) -> bool:
        return True

    hooks = PaymentHooks(notify_owner=_noop)
    flow = ShopFlow(lambda: settings, product_store, order_store, PaymentService(order_store, product_store, settings), hooks)
    flow.methods_filter = lambda methods: [m for m in methods if m == METHOD_CARD_TO_CARD]
    ui: dict = {"log": [], "menu": []}

    chat = ft.Column(key="preview_chat", spacing=8, scroll=ft.ScrollMode.AUTO, height=360)
    menu_row = ft.Row(key="preview_menu", spacing=6, wrap=True)
    entry = ft.TextField(key="preview_input", hint_text=_tx("input", lang), border_radius=10, expand=True)

    def bubble(kind: str, control: ft.Control) -> ft.Control:
        mine = kind == "me"
        return ft.Row(
            alignment=ft.MainAxisAlignment.END if mine else ft.MainAxisAlignment.START,
            controls=[ft.Container(
                padding=ft.Padding.symmetric(horizontal=12, vertical=8), border_radius=12, bgcolor=f"{theme.PRIMARY}22" if mine else theme.card_bgcolor(page),
                border=ft.Border.all(1, theme.border_color(page)), content=control,
            )],
        )

    def inline_buttons(msg: UiMessage) -> ft.Control:
        rows = []
        for row in msg.rows:
            buttons = []
            for b in row:
                if b.url:
                    buttons.append(ft.TextButton(content=f"🔗 {b.label}", on_click=lambda e, u=b.url: common.open_url(page, u)))
                else:
                    buttons.append(ft.OutlinedButton(content=b.label, key=f"cb:{b.data}", on_click=lambda e, d=b.data: tap(d)))
            rows.append(ft.Row(spacing=6, wrap=True, controls=buttons))
        return ft.Column(spacing=4, controls=rows)

    def render() -> None:
        controls: list = []
        for kind, payload in ui["log"]:
            if kind == "me":
                controls.append(bubble("me", ft.Text(payload, size=13)))
                continue
            msg: UiMessage = payload
            parts: list = []
            if msg.photo:
                parts.append(ft.Text("🖼", size=22))
            if msg.document:
                parts.append(ft.Text("📎 " + msg.document.rsplit("/", 1)[-1], size=12))
            if msg.contact:
                parts.append(ft.Text(f"📇 {msg.contact[1]} — {msg.contact[0]}", size=12))
            if msg.text:
                parts.append(ft.Text(msg.text, size=13, selectable=True))
            if msg.rows:
                parts.append(inline_buttons(msg))
            controls.append(bubble("bot", ft.Column(spacing=6, tight=True, controls=parts or [ft.Text("…")])))
        chat.controls = controls
        menu_row.controls = [
            ft.FilledTonalButton(content=label, key=f"menu:{label}", on_click=lambda e, l=label: say(l)) for row in ui["menu"] for label in row
        ]

    def absorb(result: FlowResult) -> None:
        for msg in result.messages:
            if msg.menu:
                ui["menu"] = msg.menu
            ui["log"].append(("bot", msg))
        if not result.consumed:
            ui["log"].append(("bot", UiMessage(_tx("ai_note", lang))))
        ui["log"] = ui["log"][-80:]

    def say(text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        ui["log"].append(("me", text))
        absorb(_run(flow.handle(IncomingMessage(PREVIEW_PLATFORM, PREVIEW_CHAT, "پیش‌نمایش", text, language_code=lang))))
        entry.value = ""
        render()
        page.update()

    def tap(data: str) -> None:
        absorb(_run(flow.handle(IncomingMessage(PREVIEW_PLATFORM, PREVIEW_CHAT, "پیش‌نمایش", "", callback_data=data, callback_id="p", message_id="0", language_code=lang))))
        render()
        page.update()

    def reset(e=None) -> None:
        for order in order_store.list_for_chat(PREVIEW_PLATFORM, PREVIEW_CHAT):
            if order.status == STATUS_PENDING_PAYMENT:
                try:
                    order_store.cancel(order.id)
                except Exception:  # noqa: BLE001 — لغوِ «بهترِ ممکن»؛ مهلتِ رزرو خودش آزادش می‌کنه
                    pass
        flow.carts.clear(PREVIEW_PLATFORM, PREVIEW_CHAT)
        flow.sessions.clear(PREVIEW_PLATFORM, PREVIEW_CHAT)
        ui["log"], ui["menu"] = [], []
        render()
        page.update()

    entry.on_submit = lambda e: say(entry.value)
    render()
    return ft.Column(
        spacing=10,
        controls=[
            ft.Text(_tx("help", lang), size=12, color=theme.text_secondary(page)),
            menu_row,
            ft.Container(padding=10, border_radius=12, bgcolor=f"{theme.PRIMARY}08", border=ft.Border.all(1, theme.border_color(page)), content=chat),
            ft.Row(spacing=8, controls=[
                entry,
                ft.Button(key="preview_send", content=_tx("send", lang), on_click=lambda e: say(entry.value)),
                ft.OutlinedButton(key="preview_start", content=_tx("start", lang), on_click=lambda e: say("/start")),
                ft.TextButton(key="preview_reset", content=_tx("reset", lang), on_click=reset),
            ]),
        ],
    )
