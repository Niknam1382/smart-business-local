"""
«پیش‌نمایشِ مشتری» (R8): ربات رو بدونِ تلگرام و بدونِ توکن، همین‌جا امتحان کن — همان
``ShopFlow`` و همان ``ConversationPipeline`` واقعی (پلتفرمِ «preview»؛ موجودی رزرو می‌شه،
«پاک‌کردنِ پیش‌نمایش» سفارش‌های باز را لغو می‌کنه).

قلم ۳ مستر‌پرامپت: پاسخِ هوش مصنوعی و دکمه‌ها باید در پیش‌نمایش دیده بشن. پیش‌تر فقط جریانِ
دکمه‌ها اجرا می‌شد و متنِ آزاد یادداشتِ «AI در پیش‌نمایش کار نمی‌کنه» می‌گرفت؛ حالا همان پیام
به پایپ‌لاینِ واقعی می‌ره، پس پاسخِ مدل و کارت‌های محصول با دکمه‌هایشان همین‌جا می‌نشینن.
مدل که انتخاب/دانلود نشده باشد همان یادداشت صادق می‌گوید چرا (رباتِ واقعی هم بی‌مدل ساکت است).

فقط پرداختِ کارت‌به‌کارت در پیش‌نمایش فعال است (هیچ درگاهِ واقعی صدا زده نمی‌شه).
"""

from __future__ import annotations

import concurrent.futures
from typing import Optional

import flet as ft

from app import theme
from app.core import ai_engine, paths
from app.core.answer_cache import AnswerCache
from app.core.bot_pipeline import ConversationPipeline, IncomingMessage
from app.core.conversations import ConversationStore
from app.core.orders import METHOD_CARD_TO_CARD, STATUS_PENDING_PAYMENT
from app.core.payments import PaymentHooks, PaymentService
from app.core.qa_agent import QaAgent
from app.core.shop_flow import ShopFlow
from app.core.ui import FlowResult, UiMessage
from app.screens import common

PREVIEW_PLATFORM = "preview"
PREVIEW_CHAT = "preview-1"
MAX_LOG = 80
_TEXT = {
    "title": ("پیش‌نمایشِ مشتری", "Customer preview"),
    "help": ("ربات رو همین‌جا امتحان کن: دکمه‌های منو و دکمه‌های داخلِ پیام‌ها مثلِ تلگرام کار می‌کنن.", "Try the bot right here: menu and inline buttons work just like on Telegram."),
    "input": ("پیام به ربات…", "Message the bot…"),
    "send": ("ارسال", "Send"),
    "reset": ("پاک‌کردنِ پیش‌نمایش", "Reset preview"),
    "no_ai": ("پاسخِ AI ساخته نمی‌شه: مدلی انتخاب یا دانلود نشده (صفحه‌ی «هوش مصنوعی»). دکمه‌ها و سفارش مثلِ قبل کار می‌کنن.",
              "No AI answer: no model is selected or downloaded yet (see the AI page). Buttons and ordering still work."),
    "start": ("شروع (/start)", "Start (/start)"),
}


def _tx(key: str, lang: str) -> str:
    fa, en = _TEXT[key]
    return en if lang == "en" else fa


def _run(coro):
    """coroutine را روی تردِ تازه (با event loop خودش) اجرا می‌کنه — از هر handlerِ Flet امنه.

    مدلِ محلی روی CPU گاهی یک دقیقه و بیشتر وقت می‌بره، پس سقفِ انتظارش خیلی بلندتر از یک
    درخواستِ شبکه‌ای است."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        import asyncio

        return pool.submit(lambda: asyncio.run(coro)).result(timeout=300)


class PreviewTransport:
    """پیش‌نمایش همان UiMessage‌های واقعی را با دکمه‌های واقعی نشان می‌دهد (ویرایش و حذف هم همین‌جا)."""

    def __init__(self, log: list):
        self._log = log
        self._by_id: dict = {}
        self._next = 0
        self.menu: Optional[list] = None

    def reset(self) -> None:
        self._by_id.clear()
        self._next = 0
        self.menu = None

    async def send_ui(self, chat_id: str, msg: UiMessage) -> Optional[str]:
        self._next += 1
        message_id = f"pv{self._next}"
        self._by_id[message_id] = msg
        self._log.append(("bot", msg))
        if msg.menu is not None:
            self.menu = msg.menu
        return message_id

    async def edit_ui(self, chat_id: str, message_id: str, msg: UiMessage) -> bool:
        old = self._by_id.get(message_id)
        if old is None:
            return False
        self._by_id[message_id] = msg
        for index, (kind, payload) in enumerate(self._log):
            if kind == "bot" and payload is old:
                self._log[index] = ("bot", msg)
                break
        if msg.menu is not None:
            self.menu = msg.menu
        return True

    async def delete_message(self, chat_id: str, message_id: str) -> None:
        msg = self._by_id.pop(message_id, None)
        if msg is not None:
            self._log[:] = [row for row in self._log if not (row[0] == "bot" and row[1] is msg)]

    async def answer_callback(self, callback_id: str, text: str = "", alert: bool = False) -> None:
        if text:
            self._log.append(("bot", UiMessage(text)))


def build(page: ft.Page, lang: str, settings, product_store, order_store) -> ft.Control:
    async def _noop(_text: str) -> bool:
        return True

    hooks = PaymentHooks(notify_owner=_noop)
    flow = ShopFlow(lambda: settings, product_store, order_store, PaymentService(order_store, product_store, settings), hooks)
    flow.methods_filter = lambda methods: [m for m in methods if m == METHOD_CARD_TO_CARD]
    ui: dict = {"log": [], "menu": []}
    transport = PreviewTransport(ui["log"])
    state: dict = {"pipeline": None}

    def pipeline() -> ConversationPipeline:
        """مغزِ واقعیِ ربات برایِ پیش‌نمایش: ادغامِ پیام خاموش (هر پیام فوراً پاسخ می‌گیره) و بدونِ کش."""
        if state["pipeline"] is None:
            state["pipeline"] = ConversationPipeline(
                settings,
                store=ConversationStore(db_path=paths.get_app_data_dir() / "preview_conversations.db"),
                shop_flow=flow,
                qa_agent=QaAgent(product_store, order_store, flow),
                debounce_wait=0.0,
                debounce_max_wait=1.0,
                answer_cache=AnswerCache(ttl_seconds=0),
            )
        return state["pipeline"]

    chat = ft.Column(key="preview_chat", spacing=8, scroll=ft.ScrollMode.AUTO, height=360)
    menu_row = ft.Row(key="preview_menu", spacing=6, wrap=True)
    entry = ft.TextField(key="preview_input", hint_text=_tx("input", lang), border_radius=10, expand=True)

    def trim() -> None:
        del ui["log"][:-MAX_LOG]

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
        trim()

    def message(text: str = "", callback_data: str = "") -> IncomingMessage:
        return IncomingMessage(
            PREVIEW_PLATFORM, PREVIEW_CHAT, "پیش‌نمایش", text,
            callback_data=callback_data, callback_id="p" if callback_data else "", language_code=lang,
        )

    def ask(text: str, callback_data: str) -> None:
        if not ai_engine.engine_readiness(settings)[0]:
            # بی‌مدل همان کاری که رباتِ واقعی می‌کنه: اول جریانِ دکمه‌ها (برچسبِ منو هم متن است)؛
            # هرچه جریانِ ربات نبود پاسخِ مدل می‌خواست — که اینجا صادقانه گفته می‌شه.
            result = _run(flow.handle(message(text, callback_data)))
            absorb(result)
            if not result.consumed or result.ai_text:
                ui["log"].append(("bot", UiMessage(_tx("no_ai", lang))))
            trim()
            return

        async def go() -> None:
            async def send(sent_text: str, buttons=None) -> None:
                ui["log"].append(("bot", UiMessage(sent_text)))

            brain = pipeline()
            await brain.handle_incoming(message(text, callback_data), send, transport)
            await brain.flush(PREVIEW_PLATFORM, PREVIEW_CHAT)

        _run(go())
        if transport.menu is not None:
            ui["menu"] = transport.menu
        trim()

    def say(text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        ui["log"].append(("me", text))
        ask(text, "")
        entry.value = ""
        render()
        page.update()

    def tap(data: str) -> None:
        ask("", data)
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
        transport.reset()
        state["pipeline"] = None
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
