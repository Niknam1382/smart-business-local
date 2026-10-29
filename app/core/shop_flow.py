"""
فروشگاهِ دکمه‌ایِ قطعی (R1): کاتالوگ صفحه‌بندی‌شده، کارت محصول، سبد، چک‌اوتِ مرحله‌ایِ قابل‌تنظیم، پرداخت،
پیگیریِ سفارش، سؤالات متداول و دکمه‌های سفارشی — بدونِ هیچ فرضی درباره‌ی پلتفرم (فقط ``FlowResult`` برمی‌گردونه).

اصول:
- ``callback_data`` فشرده (≤۶۴ بایت) به شکلِ ``c:<فعل>:<آرگومان…>``؛ تعدادها «مقصد» هستن (``set_qty``) تا
  دابل‌تپ idempotent باشه؛ دادهٔ ناشناخته/قدیمی/خراب هرگز exception نمی‌ده (پیامِ دوستانه + منو).
- هر مشتری پردازشش پشتِ یه قفلِ سریالی می‌شه (دابل‌تپِ «نهایی کردن» دو سفارش نمی‌سازه).
- وضعیتِ چک‌اوت در SQLite (``checkout_sessions``) تا ری‌استارت چیزی رو گم نکنه.
- AI هیچ‌وقت سبد/سفارش/پرداخت رو تغییر نمی‌ده؛ متنِ آزادِ مشتری (وقتی وسطِ ویزارد نیست) ``consumed=False`` برمی‌گردونه.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import zlib
from typing import Awaitable, Callable, Optional

from app.core import checkout_fields as cf
from app.core import custom_buttons, modes, shop_texts, ui_glyphs
from app.core.bot_pipeline import IncomingMessage
from app.core.cart import MAX_QTY_PER_LINE, CartStore, CheckoutSession, CheckoutSessionStore
from app.core.discounts import DiscountError, DiscountStore
from app.core.orders import (
    METHOD_CARD_TO_CARD,
    STATUS_CONFIRMED,
    STATUS_EXPIRED,
    STATUS_PENDING_PAYMENT,
    UNLIMITED,
    OrderError,
    OrderStore,
    build_order_summary_text,
)
from app.core.owner_console import order_alert_text
from app.core.payments import PaymentError, PaymentHooks, PaymentService, reservation_active
from app.core.products import ProductStore
from app.core.store_agent import MAX_EXPIRED_UNPAID_PER_DAY, MAX_ORDERS_PER_HOUR, sanitize_display_name
from app.core.ui import Btn, FlowResult, UiMessage, safe_url

logger = logging.getLogger(__name__)

PAGE_MIN, PAGE_MAX = 2, 12
FAQ_PAGE_SIZE = 6
ORDERS_LIST_LIMIT = 8
LABEL_MAX = 48
CAPTION_MAX = 1000
REF_TTL_SECONDS = 600
_COMMANDS = {
    "/start": "menu", "/menu": "menu", "/help": "guide", "/products": "products", "/cart": "cart",
    "/checkout": "checkout", "/orders": "orders", "/faq": "faq",
}
# menu.checkout / menu.orders_old فقط برای کیبوردهای قدیمیِ مشتری‌ها (۱.۰.۰) نگه داشته شدن؛ دیگه در منو نمایش داده نمی‌شن
_MENU_KEYS = (
    ("menu.products", "products"), ("menu.cart", "cart"), ("menu.checkout", "checkout"), ("menu.orders", "orders"),
    ("menu.orders_old", "orders"), ("menu.guide", "guide"), ("menu.faq", "faq"), ("menu.lead", "lead"),
)
GUIDE_DIRECT_CUSTOM = 2  # بیش از این تعداد دکمه‌ی سفارشی ⇒ «بیشتر»
GUIDE_PAGE_SIZE = 6
CART_NAME_MAX = 22
# فعل‌هایی که فقط در حالتِ فروشگاه (سبد/سفارش) معنی دارن؛ در حالت‌های پاسخ‌گویی/سرنخ بی‌اثرن
_SHOP_VERBS = frozenset({"k", "l", "p", "q", "a", "cart", "s", "cl", "fix", "co", "pm", "o", "od", "oc", "op", "opm", "paid", "dc", "dr", "inv"})
_SHOP_ACTIONS = frozenset({"products", "cart", "checkout", "orders"})


class _Stale(Exception):
    """callback قدیمی/خراب — پیامِ دوستانه + منو."""


def _norm(text: str) -> str:
    cleaned = (text or "").replace("\u200c", " ").replace("\u200f", "").replace("\u200e", "")
    return " ".join(cleaned.split()).lower()


def _clip(text: str, limit: int = LABEL_MAX) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _cid(name: str) -> str:
    return format(zlib.crc32(name.encode("utf-8")) & 0xFFFFFF, "06x")


def _money(irr: int) -> str:
    return f"{int(irr):,}"


class _Ctx:
    __slots__ = ("flow", "ev", "settings", "lang", "cb", "mode")

    def __init__(self, flow: "ShopFlow", ev: IncomingMessage):
        self.flow = flow
        self.ev = ev
        self.settings = flow.get_settings()
        self.lang = shop_texts.resolve_lang(self.settings, ev.language_code)
        self.cb = bool(ev.callback_data)
        self.mode = modes.resolve_mode(self.settings, ev.platform)

    @property
    def platform(self) -> str:
        return self.ev.platform

    @property
    def chat(self) -> str:
        return str(self.ev.chat_id)

    def t(self, key: str, **params) -> str:
        return shop_texts.render(self.settings, key, self.lang, **params)

    def price(self, irr: int) -> str:
        return self.t("ui.price", amount=_money(irr))

    @property
    def glyphs(self) -> ui_glyphs.Glyphs:
        return ui_glyphs.for_platform(self.platform, self.lang)


class ShopFlow:
    def __init__(
        self,
        get_settings: Callable[[], object],
        product_store: ProductStore,
        order_store: OrderStore,
        payments: Optional[PaymentService],
        hooks: PaymentHooks,
        carts: Optional[CartStore] = None,
        sessions: Optional[CheckoutSessionStore] = None,
    ):
        self.get_settings = get_settings
        self.products = product_store
        self.orders = order_store
        self.payments = payments
        self.hooks = hooks
        self.carts = carts or CartStore(order_store)
        self.sessions = sessions or CheckoutSessionStore(order_store)
        self.discounts = DiscountStore(order_store)  # N8
        self.support_handler: Optional[Callable[[IncomingMessage], Awaitable[FlowResult]]] = None  # R5 (handoff)
        self.support_end_handler: Optional[Callable[[IncomingMessage], Awaitable[FlowResult]]] = None
        self._locks: dict = {}
        self.invoice_handler: Optional[Callable[[str, str, int], Awaitable[str]]] = None  # N19: (platform, chat, order_id) ← "sent"|"unavailable"|"failed"
        self.invoice_visible: Callable[[], bool] = lambda: True  # N19: دکمه‌ی «🧾 فاکتور» فقط وقتی فروشنده فاکتور را راه انداخته
        self.attention = None  # AttentionInbox (اختیاری): سرنخ‌ها در «نیاز به توجه» می‌مونن تا مالک «انجام شد» بزنه
        self.methods_filter: Optional[Callable[[list], list]] = None  # پیش‌نمایشِ داخل برنامه: فقط روش‌های بی‌خطر

    # ================================================================ ورودی ====

    async def handle(self, ev: IncomingMessage) -> FlowResult:
        lock = self._locks.setdefault((ev.platform, str(ev.chat_id)), asyncio.Lock())
        async with lock:
            ctx = _Ctx(self, ev)
            try:
                return await (self._on_callback(ctx) if ctx.cb else self._on_text(ctx))
            except _Stale:
                return self._stale(ctx)
            except Exception:  # noqa: BLE001 — خرابیِ جریان نباید ربات رو بکشه
                logger.exception("خطا در جریانِ فروشگاهِ دکمه‌ای")
                return FlowResult([UiMessage(ctx.t("ui.error"))], answer=ctx.t("ui.error"))

    def _stale(self, ctx: _Ctx) -> FlowResult:
        res = self._menu_result(ctx)
        res.answer = ctx.t("ui.stale")
        return res

    # ---------------------------------------------------------------- متن ----

    async def _on_text(self, ctx: _Ctx) -> FlowResult:
        ev = ctx.ev
        text = (ev.text or "").strip()
        action = None
        if text.startswith("/"):
            action = _COMMANDS.get(text.split()[0].split("@")[0].lower())
        if action is None:
            action = self._match_menu(ctx, text)
        if action is not None and not self._action_allowed(ctx, action):
            action = None  # در این حالت منو چنین چیزی نداره؛ متنِ مشتری مثلِ پیامِ آزاد (AI) رفتار می‌کنه
        session = self.sessions.get(ctx.platform, ctx.chat)
        if session is not None and session.step == "ref":
            if action is None and text:
                return await self._save_reference(ctx, session, text)
            self.sessions.clear(ctx.platform, ctx.chat)
            session = None
        if session is not None and session.step == "code":
            if action is None and text:
                return await self._apply_code(ctx, text)
            self.sessions.clear(ctx.platform, ctx.chat)
            session = None
        if session is not None:
            if action is not None:
                session.data["pending"] = action
                self.sessions.put(ctx.platform, ctx.chat, session.step, session.data)
                return FlowResult([UiMessage(ctx.t("co.continue_or_cancel"), [[Btn(ctx.t("co.resume"), "c:ck:r"), Btn(ctx.t("co.cancel"), "c:ck:x")]])])
            return await self._wizard_input(ctx, session, ev.phone or text)
        if action is not None:
            return await self._run_action(ctx, action)
        if ev.phone and not text:
            await self.hooks.notify_owner(f"📞 {sanitize_display_name(ev.display_name) or ctx.chat} ({ctx.platform}): {_clip(ev.phone, 30)}")
            return FlowResult([UiMessage(ctx.t("ui.contact_saved"), menu=self._menu_rows(ctx))])
        return FlowResult(consumed=False)

    @staticmethod
    def _action_allowed(ctx: _Ctx, action: str) -> bool:
        if action in _SHOP_ACTIONS:
            return ctx.mode.cart
        if action == "faq":
            return ctx.mode.faq
        if action == "lead":
            return ctx.mode.fields
        return True  # menu / guide در همه‌ی حالت‌ها

    def _label_actions(self, ctx: _Ctx) -> list:
        pairs = []
        for lang in dict.fromkeys([ctx.lang, *shop_texts.SUPPORTED_LANGS]):
            for key, action in _MENU_KEYS:
                pairs.append((_norm(shop_texts.render(ctx.settings, key, lang)), action))
        for b in custom_buttons.visible(ctx.settings, ctx.platform):
            pairs.append((_norm(b.display), f"b:{b.id}"))
        return pairs

    def _match_menu(self, ctx: _Ctx, text: str) -> Optional[str]:
        n = _norm(text)
        if not n:
            return None
        for label, action in self._label_actions(ctx):
            if n == label or (action == "cart" and n.startswith(label + " (")):
                return action
        return None

    async def _run_action(self, ctx: _Ctx, action: str) -> FlowResult:
        if (action in _SHOP_ACTIONS and not ctx.mode.cart) or (action == "faq" and not ctx.mode.faq) or (action == "lead" and not ctx.mode.fields):
            raise _Stale()
        if action == "lead":
            return await self._start_lead(ctx)
        if action == "menu":
            return self._welcome(ctx)
        if action == "guide":
            return self._guide_view(ctx, 1) if ctx.mode.cart else self._welcome(ctx)
        if action == "products":
            return self._categories_view(ctx)
        if action == "cart":
            return self._cart_view(ctx)
        if action == "checkout":
            return await self._start_checkout(ctx)
        if action == "orders":
            return self._orders_view(ctx)
        if action == "faq":
            return self._faq_view(ctx, 1)
        if action.startswith("b:"):
            return await self._run_custom(ctx, action[2:])
        raise _Stale()

    # ------------------------------------------------------------------ منو ----

    def _menu_rows(self, ctx: _Ctx) -> list:
        n = self.carts.count(ctx.platform, ctx.chat)
        if ctx.mode.cart:
            # N5: فقط چهار دکمه؛ «نهایی کردن» داخلِ پیامِ سبد است و سؤالات متداول/دکمه‌های سفارشی زیرِ «راهنما»
            return [[ctx.t("menu.products"), ctx.t("menu.cart") + (f" ({n})" if n else "")], [ctx.t("menu.orders"), ctx.t("menu.guide")]]
        rows: list = []
        extra = []
        if ctx.mode.fields and not ctx.mode.cart:
            extra.append(ctx.t("menu.lead"))
        if ctx.mode.faq and getattr(ctx.settings, "faq_items", None):
            extra.append(ctx.t("menu.faq"))
        extra += [b.display for b in custom_buttons.visible(ctx.settings, ctx.platform)]
        rows += [extra[i : i + 2] for i in range(0, len(extra), 2)]
        return rows

    def _menu_result(self, ctx: _Ctx, text: Optional[str] = None) -> FlowResult:
        return FlowResult([UiMessage(text or ctx.t("menu.hint"), menu=self._menu_rows(ctx))])

    def _welcome(self, ctx: _Ctx) -> FlowResult:
        name = sanitize_display_name(ctx.ev.display_name) or ""
        text = ctx.t("menu.welcome", name=name).replace("  ", " ").strip()
        if getattr(ctx.settings, "ai_disclosure_enabled", True):
            text += "\n\n" + ctx.t("privacy.ai_disclosure")
        return self._menu_result(ctx, text)

    # ============================================================== callback ====

    async def _on_callback(self, ctx: _Ctx) -> FlowResult:
        parts = (ctx.ev.callback_data or "").split(":")
        if len(parts) < 2 or parts[0] != "c":
            raise _Stale()
        handler = getattr(self, f"_cb_{parts[1]}", None)
        if handler is None or (parts[1] in _SHOP_VERBS and not ctx.mode.cart):
            raise _Stale()
        try:
            return await handler(ctx, parts[2:])
        except (ValueError, IndexError) as exc:
            raise _Stale() from exc

    async def _cb_n(self, ctx, a):  # بدون عمل (شمارنده‌ی صفحه/تعداد)
        return FlowResult(consumed=True)

    async def _cb_m(self, ctx, a):
        return self._menu_result(ctx)

    async def _cb_g(self, ctx, a):
        if not ctx.mode.cart:
            return self._menu_result(ctx)
        return self._guide_view(ctx, int(a[0]) if a else 1)

    async def _cb_k(self, ctx, a):
        return self._categories_view(ctx)

    async def _cb_l(self, ctx, a):
        return self._list_view(ctx, a[0], int(a[1]))

    async def _cb_p(self, ctx, a):
        return self._product_view(ctx, int(a[0]), a[1], int(a[2]))

    async def _cb_q(self, ctx, a):
        return self._product_view(ctx, int(a[0]), a[2], int(a[3]), qty=int(a[1]), kb_only=True)

    async def _cb_a(self, ctx, a):
        pid, qty, catid, page = int(a[0]), int(a[1]), a[2], int(a[3])
        product, avail = self._sellable_product(pid)
        if product is None:
            res = self._list_view(ctx, catid, page)
            res.answer = ctx.t("cat.gone")
            return res
        qty = max(1, min(qty, self._max_qty(ctx, avail)))
        self.carts.set_qty(ctx.platform, ctx.chat, pid, qty)
        return self._product_view(ctx, pid, catid, page, qty=qty, kb_only=True, answer=ctx.t("prod.added"))

    async def _cb_cart(self, ctx, a):
        return self._cart_view(ctx)

    async def _cb_dc(self, ctx, a):  # N8: «کد تخفیف» ← منتظرِ متنِ کد
        if not self.carts.get(ctx.platform, ctx.chat):
            return self._cart_view(ctx)
        self.sessions.put(ctx.platform, ctx.chat, "code", {}, ttl=600)
        return FlowResult([UiMessage(ctx.t("disc.ask"), [[Btn(ctx.t("menu.cart"), "c:cart")]], edit=ctx.cb)])

    async def _cb_dr(self, ctx, a):
        self.discounts.clear_cart_code(ctx.platform, ctx.chat)
        return self._cart_view(ctx, notice=ctx.t("disc.removed"))

    async def _apply_code(self, ctx: _Ctx, text: str) -> FlowResult:
        lines = self.carts.get(ctx.platform, ctx.chat)
        if not lines:
            self.sessions.clear(ctx.platform, ctx.chat)
            return self._cart_view(ctx)
        try:
            self.discounts.try_set_code(ctx.platform, ctx.chat, text, lines)
        except DiscountError as exc:
            if exc.code == "locked":
                self.sessions.clear(ctx.platform, ctx.chat)
                msg = ctx.t("disc.err.locked", n=max(1, math.ceil(exc.retry_after / 60)))
            else:
                self.sessions.put(ctx.platform, ctx.chat, "code", {}, ttl=600)  # می‌تونه دوباره بفرسته
                msg = ctx.t(f"disc.err.{'unknown' if exc.code == 'inactive' else exc.code}")
            return FlowResult([UiMessage(msg, [[Btn(ctx.t("menu.cart"), "c:cart")]])])
        self.sessions.clear(ctx.platform, ctx.chat)
        return self._cart_view(ctx, notice=ctx.t("disc.applied", code=self.discounts.cart_code(ctx.platform, ctx.chat)))

    def _discount_lines(self, ctx: _Ctx, prev) -> list:
        out = [ctx.t("cart.discount", code=c.code, amount=_money(a)) for c, a in prev.applied]
        if prev.discount:
            out.append(ctx.t("cart.payable", amount=_money(prev.final)))
        return out

    async def _cb_s(self, ctx, a):
        pid, n = int(a[0]), int(a[1])
        if n > 0:
            product, avail = self._sellable_product(pid)
            n = min(n, self._max_qty(ctx, avail)) if product is not None else 0
        self.carts.set_qty(ctx.platform, ctx.chat, pid, n)
        return self._cart_view(ctx)

    async def _cb_cl(self, ctx, a):
        if a and a[0] == "y":
            self.carts.clear(ctx.platform, ctx.chat)
            res = self._cart_view(ctx)
            res.answer = ctx.t("cart.cleared")
            return res
        rows = [[Btn(ctx.t("cart.clear_yes"), "c:cl:y"), Btn(ctx.t("ui.back"), "c:cart")]]
        return FlowResult([UiMessage(ctx.t("cart.clear_confirm"), rows, edit=True)])

    async def _cb_fix(self, ctx, a):
        for pid, qty in self.carts.get(ctx.platform, ctx.chat):
            product, avail = self._sellable_product(pid)
            if product is None:
                self.carts.set_qty(ctx.platform, ctx.chat, pid, 0)
            elif qty > avail:
                self.carts.set_qty(ctx.platform, ctx.chat, pid, avail)
        res = self._cart_view(ctx)
        res.answer = ctx.t("cart.fixed")
        return res

    async def _cb_co(self, ctx, a):
        return await self._start_checkout(ctx)

    async def _cb_ck(self, ctx, a):
        return await self._checkout_button(ctx, a)

    async def _cb_pm(self, ctx, a):
        return await self._create_order(ctx, a[0])

    async def _cb_o(self, ctx, a):
        return self._orders_view(ctx)

    async def _cb_od(self, ctx, a):
        return self._order_view(ctx, int(a[0]))

    async def _cb_inv(self, ctx, a):
        """N19: «🧾 فاکتور» — فقط مالکِ همان سفارشِ تاییدشده؛ ارسال از مسیرِ ``invoice_handler`` (idempotent/محدودشده)."""
        order = self._own_order(ctx, int(a[0]))
        status = "unavailable"
        if self.invoice_handler is not None and order.status == STATUS_CONFIRMED:
            status = await self.invoice_handler(ctx.platform, ctx.chat, order.id)
        key = {"sent": "inv.sent", "failed": "inv.failed"}.get(status, "inv.unavailable")
        return FlowResult([UiMessage(ctx.t(key))], answer=ctx.t(key))

    async def _cb_oc(self, ctx, a):
        return self._cancel_order(ctx, int(a[0]), confirmed=len(a) > 1 and a[1] == "y")

    async def _cb_op(self, ctx, a):
        order = self._own_order(ctx, int(a[0]))
        if not (reservation_active(order) or order.status == STATUS_EXPIRED):
            return FlowResult([UiMessage(ctx.t("ord.not_payable"), edit=True)], answer=ctx.t("ord.not_payable"))
        return self._method_buttons(ctx, f"c:opm:{order.id}:", back=f"c:od:{order.id}")

    async def _cb_opm(self, ctx, a):
        order = self._own_order(ctx, int(a[0]))
        if not reservation_active(order):
            return FlowResult([UiMessage(ctx.t("ord.not_payable"), edit=True)], answer=ctx.t("ord.not_payable"))
        return FlowResult([UiMessage(ctx.t("co.created", order_id=order.id), edit=True), *await self._instruction(ctx, order, a[1])])

    async def _cb_paid(self, ctx, a):
        return await self._claim_card_payment(ctx, int(a[0]))

    async def _cb_f(self, ctx, a):
        return self._faq_view(ctx, int(a[0]))

    async def _cb_fa(self, ctx, a):
        return self._faq_answer(ctx, int(a[0]))

    async def _cb_hx(self, ctx, a):
        if self.support_end_handler is None:
            raise _Stale()
        return await self.support_end_handler(ctx.ev)

    async def _cb_b(self, ctx, a):
        return await self._run_custom(ctx, a[0])

    def suggestion_cards(self, platform: str, chat_id: str, product_ids: list, language_code: str = "") -> list:
        """کارتِ محصول (با «افزودن به سبد» و «جزئیات») برای ابزارِ ``suggest_products`` — فقط محصولاتِ قابل‌فروش."""
        ctx = _Ctx(self, IncomingMessage(platform, str(chat_id), "", "", language_code=language_code))
        cards = []
        for pid in product_ids:
            product, avail = self._sellable_product(int(pid))
            if product is None:
                continue
            lines = [product.name, ctx.price(product.price_irr)]
            if product.description:
                lines += ["", " ".join(product.description.split())[:300]]
            rows = [[Btn(ctx.t("prod.add"), f"c:a:{product.id}:1:-:1")], [Btn(ctx.glyphs.details, f"c:p:{product.id}:-:1")]]
            photo = product.photo_path if product.photo_path and os.path.isfile(product.photo_path) else ""
            cards.append(UiMessage("\n".join(lines)[:CAPTION_MAX], rows, photo=photo))
        return cards

    # ============================================================== کاتالوگ ====

    def _sellable_product(self, pid: int) -> tuple:
        product = self.products.get(pid)
        if product is None or not product.active:
            return None, 0
        avail = self.orders.available_quantity(pid)
        return (product, avail) if avail > 0 else (None, 0)

    def _sellable(self) -> list:
        out = []
        for product in self.products.list():
            avail = self.orders.available_quantity(product.id)
            if avail > 0:
                out.append((product, avail))
        return out

    @staticmethod
    def _max_qty(ctx: _Ctx, avail: int) -> int:
        cap = max(1, min(int(getattr(ctx.settings, "max_qty_per_item", 10) or 10), MAX_QTY_PER_LINE))
        return cap if avail >= UNLIMITED else max(1, min(cap, avail))

    def _categories_view(self, ctx: _Ctx) -> FlowResult:
        counts: dict = {}
        for product, _avail in self._sellable():
            if product.category:
                counts[product.category] = counts.get(product.category, 0) + 1
        if not counts:
            return self._list_view(ctx, "-", 1)
        rows = [[Btn(_clip(f"🗂 {name} ({n})"), f"c:l:{_cid(name)}:1")] for name, n in sorted(counts.items())]
        rows.append([Btn(ctx.t("cat.all"), "c:l:-:1")])
        return FlowResult([UiMessage(ctx.t("cat.choose_category"), rows, edit=ctx.cb)])

    def _list_view(self, ctx: _Ctx, catid: str, page: int) -> FlowResult:
        sellable = self._sellable()
        categories = sorted({p.category for p, _ in sellable if p.category})
        title = ctx.t("cat.title")
        if catid != "-":
            name = next((c for c in categories if _cid(c) == catid), None)
            if name is None:
                catid = "-"
            else:
                sellable = [(p, a) for p, a in sellable if p.category == name]
                title += f" — {name}"
        if not sellable:
            return FlowResult([UiMessage(ctx.t("cat.empty"), edit=ctx.cb)])
        size = max(PAGE_MIN, min(int(getattr(ctx.settings, "catalog_page_size", 6) or 6), PAGE_MAX))
        pages = max(1, math.ceil(len(sellable) / size))
        page = max(1, min(page, pages))
        rows = []
        for product, _avail in sellable[(page - 1) * size : page * size]:
            icon = "💾" if product.is_digital else "📦"
            rows.append([Btn(_clip(f"{icon} {product.name} — {ctx.price(product.price_irr)}"), f"c:p:{product.id}:{catid}:{page}")])
        if pages > 1:
            nav = []
            if page > 1:
                nav.append(Btn(ctx.t("cat.prev"), f"c:l:{catid}:{page - 1}"))
            nav.append(Btn(ctx.t("cat.page", page=page, pages=pages), "c:n"))
            if page < pages:
                nav.append(Btn(ctx.t("cat.next"), f"c:l:{catid}:{page + 1}"))
            rows.append(nav)
        bottom = [Btn(self._cart_label(ctx), "c:cart")]
        if categories:
            bottom.append(Btn(ctx.t("cat.categories"), "c:k"))
        rows.append(bottom)
        return FlowResult([UiMessage(title, rows, edit=ctx.cb)])

    def _cart_label(self, ctx: _Ctx) -> str:
        n = self.carts.count(ctx.platform, ctx.chat)
        return ctx.t("menu.cart") + (f" ({n})" if n else "")

    def _product_view(self, ctx: _Ctx, pid: int, catid: str, page: int, qty: Optional[int] = None, kb_only: bool = False, answer: str = "") -> FlowResult:
        product, avail = self._sellable_product(pid)
        if product is None:
            res = self._list_view(ctx, catid, page)
            res.answer = ctx.t("cat.gone")
            return res
        max_q = self._max_qty(ctx, avail)
        cur = self.carts.quantity(ctx.platform, ctx.chat, pid)
        qty = max(1, min(qty if qty is not None else (cur or 1), max_q))
        lines = [product.name, ctx.price(product.price_irr)]
        if product.description:
            lines += ["", product.description]
        lines.append("")
        lines.append(ctx.t("prod.type_digital") if product.is_digital else ctx.t("prod.type_physical"))
        if avail < UNLIMITED:
            lines.append(ctx.t("prod.stock", n=avail))
        text = "\n".join(lines)
        tail = f":{catid}:{page}"
        g = ctx.glyphs
        rows = [
            [Btn(g.minus, f"c:q:{pid}:{max(1, qty - 1)}{tail}"), Btn(str(qty), "c:n"), Btn(g.plus, f"c:q:{pid}:{min(max_q, qty + 1)}{tail}")],
            [Btn(ctx.t("prod.update") if cur else ctx.t("prod.add"), f"c:a:{pid}:{qty}{tail}")],
        ]
        if cur:
            rows.append([Btn(ctx.t("prod.in_cart", n=cur), "c:n")])
            rows.append([Btn(ctx.t("prod.view_cart"), "c:cart"), Btn(ctx.t("prod.continue"), f"c:l:{catid}:{page}")])
        else:
            rows.append([Btn(ctx.t("ui.back"), f"c:l:{catid}:{page}"), Btn(self._cart_label(ctx), "c:cart")])
        photo = product.photo_path if product.photo_path and os.path.isfile(product.photo_path) else ""
        msg = UiMessage(text[:CAPTION_MAX] if photo else text, rows, photo=photo, edit=ctx.cb, keyboard_only=kb_only)
        return FlowResult([msg], answer=answer)

    # ================================================================== سبد ====

    def _cart_problems(self, ctx: _Ctx, lines: list) -> list:
        """``[(pid, نام, نوع('gone'|'short'), موجودی)]``"""
        problems = []
        for pid, qty in lines:
            product = self.products.get(pid)
            avail = self.orders.available_quantity(pid) if product is not None and product.active else 0
            if product is None or not product.active or avail <= 0:
                problems.append((pid, product.name if product else str(pid), "gone", 0))
            elif qty > avail:
                problems.append((pid, product.name, "short", avail))
        return problems

    def _cart_view(self, ctx: _Ctx, answer: str = "", notice: str = "") -> FlowResult:
        lines = self.carts.get(ctx.platform, ctx.chat)
        if not lines:
            rows = [[Btn(ctx.t("menu.products"), "c:k")]]
            return FlowResult([UiMessage(ctx.t("cart.empty"), rows, edit=ctx.cb)], answer=answer)
        prev = self.discounts.preview(ctx.platform, ctx.chat, lines)
        if prev.manual_error:  # کدِ دستی دیگه معتبر نیست (مثلاً سبد عوض شد) ← برداشته می‌شه
            self.discounts.clear_cart_code(ctx.platform, ctx.chat)
            notice = notice or ctx.t("cart.code_gone")
        text = ([notice, ""] if notice else []) + [ctx.t("cart.title"), ""]
        rows = []
        total = 0
        g = ctx.glyphs
        for pid, qty in lines:
            product = self.products.get(pid)
            if product is None:
                continue
            total += product.price_irr * qty
            text.append(ctx.t("cart.line", qty=qty, name=product.name, amount=_money(product.price_irr * qty)))
            # N5: هر قلم یک ردیف [ − ] تعداد× نام [ + ]؛ با تعدادِ ۱، «−» به «حذف» تبدیل می‌شه (تعدادِ مقصد ۰ = حذفِ قلم)
            rows.append([
                Btn(g.remove if qty <= 1 else g.minus, f"c:s:{pid}:{qty - 1}"),
                Btn(_clip(f"{qty}× {product.name}", CART_NAME_MAX), "c:n"),
                Btn(g.plus, f"c:s:{pid}:{qty + 1}"),
            ])
        problems = self._cart_problems(ctx, lines)
        text += ["", ctx.t("cart.total", amount=_money(total)), *self._discount_lines(ctx, prev)]
        for _pid, name, kind, avail in problems:
            text.append(ctx.t("cart.warn_gone", name=name) if kind == "gone" else ctx.t("cart.warn_short", name=name, n=avail))
        if problems:
            text += ["", ctx.t("cart.fix_hint")]  # N3: هر پیام می‌گه قدمِ بعد چیه
        text += ["", ctx.t("cart.note", minutes=int(getattr(ctx.settings, "reservation_minutes", 15) or 15))]
        if problems:
            rows.append([Btn(ctx.t("cart.fix"), "c:fix")])
        if prev.manual_code:
            rows.append([Btn(ctx.t("cart.code_remove"), "c:dr")])
        elif self.discounts.has_manual_codes():
            rows.append([Btn(ctx.t("cart.code"), "c:dc")])
        rows.append([Btn(ctx.t("cart.clear"), "c:cl"), Btn(ctx.t("cart.checkout"), "c:co")])  # ردیفِ پایانی: خالی‌کردن | ثبتِ سفارش
        return FlowResult([UiMessage("\n".join(text), rows, edit=ctx.cb)], answer=answer)

    # ============================================================== چک‌اوت ====

    def _methods(self) -> list:
        if self.payments is None:
            return []
        methods = self.payments.available_methods(bale_running=self.hooks.bale_client() is not None)
        return self.methods_filter(methods) if self.methods_filter is not None else methods

    def _method_buttons(self, ctx: _Ctx, prefix: str, back: str) -> FlowResult:
        methods = self._methods()
        if not methods:
            return FlowResult([UiMessage(ctx.t("co.no_payment"), edit=ctx.cb)], answer=ctx.t("co.no_payment"))
        rows = [[Btn(ctx.t(f"co.method.{m}"), f"{prefix}{m}")] for m in methods]
        rows.append([Btn(ctx.t("ui.back"), back)])
        return FlowResult([UiMessage(ctx.t("co.choose_payment"), rows, edit=ctx.cb)])

    def _applicable_fields(self, ctx: _Ctx, lines: list) -> list:
        kinds = [(self.products.get(pid).is_digital if self.products.get(pid) else False) for pid, _q in lines]
        fields = cf.load_fields(ctx.settings)
        return cf.fields_for_cart(fields, has_physical=any(not k for k in kinds), has_digital=any(kinds))

    async def _start_checkout(self, ctx: _Ctx) -> FlowResult:
        lines = self.carts.get(ctx.platform, ctx.chat)
        if not lines:
            return self._cart_view(ctx)
        pending = [o for o in self.orders.active_for_chat(ctx.platform, ctx.chat) if o.status == STATUS_PENDING_PAYMENT]
        if pending:
            rows = [[Btn(ctx.t("ord.title"), f"c:od:{pending[0].id}")]]
            return FlowResult([UiMessage(ctx.t("co.pending_exists", order_id=pending[0].id), rows, edit=ctx.cb)])
        recent_hour, expired_day = self.orders.recent_activity(ctx.platform, ctx.chat)
        if recent_hour >= MAX_ORDERS_PER_HOUR or expired_day >= MAX_EXPIRED_UNPAID_PER_DAY:
            return FlowResult([UiMessage(ctx.t("co.too_many"), edit=ctx.cb)], answer=ctx.t("co.too_many"))
        if self._cart_problems(ctx, lines):
            res = self._cart_view(ctx)
            res.messages.insert(0, UiMessage(ctx.t("co.stock_problem"), edit=False))
            return res
        if not self._methods():
            return FlowResult([UiMessage(ctx.t("co.no_payment"), edit=ctx.cb)], answer=ctx.t("co.no_payment"))
        fields = self._applicable_fields(ctx, lines)
        data = {"fields": [f.id for f in fields], "answers": {}, "idx": 0, "edit_only": False}
        if not fields:
            self.sessions.put(ctx.platform, ctx.chat, "summary", data)
            return self._summary_view(ctx, self.sessions.get(ctx.platform, ctx.chat))
        self.sessions.put(ctx.platform, ctx.chat, "field", data)
        return self._prompt_view(ctx, self.sessions.get(ctx.platform, ctx.chat))

    def _session_fields(self, ctx: _Ctx, session: CheckoutSession) -> list:
        by_id = {f.id: f for f in cf.load_fields(ctx.settings)}
        return [by_id[i] for i in session.data.get("fields", []) if i in by_id]

    def _prompt_view(self, ctx: _Ctx, session: CheckoutSession, error: str = "") -> FlowResult:
        fields = self._session_fields(ctx, session)
        idx = int(session.data.get("idx", 0))
        if idx >= len(fields):
            return self._summary_view(ctx, session)
        f = fields[idx]
        text = ctx.t("co.step", i=idx + 1, n=len(fields), prompt=f.prompt)
        if error:
            text = ctx.t("co.invalid", error=error) + "\n\n" + text
        rows: list = []
        if f.type == "choice":
            for i in range(0, len(f.choices), 2):
                rows.append([Btn(_clip(c, 28), f"c:ck:p:{i + j}") for j, c in enumerate(f.choices[i : i + 2])])
        nav = []
        if idx > 0 and not session.data.get("edit_only"):
            nav.append(Btn(ctx.t("co.back"), "c:ck:b"))
        if not f.required:
            nav.append(Btn(ctx.t("co.skip"), "c:ck:s"))
        nav.append(Btn(ctx.t("co.cancel"), "c:ck:x"))
        rows.append(nav)
        return FlowResult([UiMessage(text, rows, edit=ctx.cb and not error)])

    async def _wizard_input(self, ctx: _Ctx, session: CheckoutSession, raw: str) -> FlowResult:
        if session.step != "field":
            return FlowResult([UiMessage(ctx.t("menu.hint"))])
        fields = self._session_fields(ctx, session)
        idx = int(session.data.get("idx", 0))
        if idx >= len(fields):
            return self._summary_view(ctx, session)
        ok, value = cf.validate_value(fields[idx], raw)
        if not ok:
            return self._prompt_view(ctx, session, error=value)
        session.data.setdefault("answers", {})[fields[idx].id] = value
        return await self._advance(ctx, session)

    async def _advance(self, ctx: _Ctx, session: CheckoutSession) -> FlowResult:
        fields = self._session_fields(ctx, session)
        if session.data.get("edit_only"):
            session.data["edit_only"] = False
            session.data["idx"] = len(fields)
        else:
            session.data["idx"] = int(session.data.get("idx", 0)) + 1
        if session.data["idx"] >= len(fields) and session.data.get("kind") == "lead":
            return await self._finish_lead(ctx, session, fields)
        if session.data["idx"] >= len(fields):
            self.sessions.put(ctx.platform, ctx.chat, "summary", session.data)
            return self._summary_view(ctx, self.sessions.get(ctx.platform, ctx.chat))
        self.sessions.put(ctx.platform, ctx.chat, "field", session.data)
        return self._prompt_view(ctx, session)

    def _summary_view(self, ctx: _Ctx, session: CheckoutSession) -> FlowResult:
        lines = self.carts.get(ctx.platform, ctx.chat)
        text = [ctx.t("co.summary_title"), ""]
        total = 0
        for pid, qty in lines:
            product = self.products.get(pid)
            if product is None:
                continue
            total += product.price_irr * qty
            text.append(ctx.t("cart.line", qty=qty, name=product.name, amount=_money(product.price_irr * qty)))
        text += [ctx.t("cart.total", amount=_money(total)), *self._discount_lines(ctx, self.discounts.preview(ctx.platform, ctx.chat, lines)), ""]
        fields = self._session_fields(ctx, session)
        answers = session.data.get("answers", {})
        rows = []
        for i, f in enumerate(fields):
            text.append(ctx.t("ord.info", label=f.label, value=_clip(answers.get(f.id, "—"), 200)))
        rows.append([Btn(ctx.t("co.confirm"), "c:ck:ok")])
        if fields:  # N3: فقط ۳ گزینه‌ی هم‌زمان؛ انتخابِ اطلاعاتِ قابل‌ویرایش در پیامِ بعدی
            rows.append([Btn(ctx.t("co.edit_info"), "c:ck:e:0" if len(fields) == 1 else "c:ck:ed")])
        rows.append([Btn(ctx.t("co.cancel"), "c:ck:x")])
        return FlowResult([UiMessage("\n".join(text), rows, edit=ctx.cb)])

    def _edit_pick_view(self, ctx: _Ctx, session: CheckoutSession) -> FlowResult:
        fields = self._session_fields(ctx, session)
        rows = []
        for i in range(0, len(fields), 2):
            rows.append([Btn(_clip(ctx.t("co.edit", label=f.label), 28), f"c:ck:e:{i + j}") for j, f in enumerate(fields[i : i + 2])])
        rows.append([Btn(ctx.t("ui.back"), "c:ck:r")])  # «r» = برگشت به خلاصه (مرحله‌ی summary دست‌نخورده می‌ماند)
        return FlowResult([UiMessage(ctx.t("co.edit_pick"), rows, edit=ctx.cb)])

    async def _checkout_button(self, ctx: _Ctx, a: list) -> FlowResult:
        session = self.sessions.get(ctx.platform, ctx.chat)
        sub = a[0]
        if session is None:
            return FlowResult([UiMessage(ctx.t("co.no_session"), edit=True)], answer=ctx.t("co.no_session"))
        if sub == "x":
            self.sessions.clear(ctx.platform, ctx.chat)
            return FlowResult([UiMessage(ctx.t("co.cancelled"), edit=True)], answer=ctx.t("co.cancelled"))
        if sub == "r":  # ادامه بعد از وقفه‌ی منو
            session.data.pop("pending", None)
            self.sessions.put(ctx.platform, ctx.chat, session.step, session.data)
            res = self._summary_view(ctx, session) if session.step == "summary" else (
                self._method_buttons(ctx, "c:pm:", "c:ck:r") if session.step == "pay" else self._prompt_view(ctx, session)
            )
            return res
        if session.step == "pay" and sub != "ok":
            session.step = "summary"
        fields = self._session_fields(ctx, session)
        if sub == "b":
            session.data["idx"] = max(0, int(session.data.get("idx", 0)) - 1)
            self.sessions.put(ctx.platform, ctx.chat, "field", session.data)
            return self._prompt_view(ctx, session)
        if sub == "s":
            idx = int(session.data.get("idx", 0))
            if idx < len(fields) and not fields[idx].required:
                return await self._advance(ctx, session)
            raise _Stale()
        if sub == "p":
            idx = int(session.data.get("idx", 0))
            choice = fields[idx].choices[int(a[1])]
            ok, value = cf.validate_value(fields[idx], choice)
            if not ok:
                raise _Stale()
            session.data.setdefault("answers", {})[fields[idx].id] = value
            return await self._advance(ctx, session)
        if sub == "ed":
            return self._edit_pick_view(ctx, session)
        if sub == "e":
            session.data["idx"] = int(a[1])
            session.data["edit_only"] = True
            if not 0 <= session.data["idx"] < len(fields):
                raise _Stale()
            self.sessions.put(ctx.platform, ctx.chat, "field", session.data)
            return self._prompt_view(ctx, session)
        if sub == "ok":
            lines = self.carts.get(ctx.platform, ctx.chat)
            if not lines or self._cart_problems(ctx, lines):
                self.sessions.clear(ctx.platform, ctx.chat)
                res = self._cart_view(ctx)
                res.messages.insert(0, UiMessage(ctx.t("co.stock_problem"), edit=False))
                return res
            missing = [f for f in fields if f.required and not session.data.get("answers", {}).get(f.id)]
            if missing:
                session.data["idx"] = fields.index(missing[0])
                self.sessions.put(ctx.platform, ctx.chat, "field", session.data)
                return self._prompt_view(ctx, session)
            self.sessions.put(ctx.platform, ctx.chat, "pay", session.data)
            return self._method_buttons(ctx, "c:pm:", "c:ck:r")
        raise _Stale()

    def _legacy_columns(self, fields: list, answers: dict) -> tuple:
        name = phone = address = ""
        for f in fields:
            value = answers.get(f.id, "")
            if f.id == "name":
                name = value
            elif f.type == "phone" and not phone:
                phone = value
            elif f.id == "address":
                address = value
        return name, phone, address

    async def _create_order(self, ctx: _Ctx, method: str) -> FlowResult:
        session = self.sessions.get(ctx.platform, ctx.chat)
        if session is None or session.step != "pay":
            return FlowResult([UiMessage(ctx.t("co.no_session"), edit=True)], answer=ctx.t("co.no_session"))
        if method not in self._methods():
            raise _Stale()
        lines = self.carts.get(ctx.platform, ctx.chat)
        answers = {k: v for k, v in session.data.get("answers", {}).items() if v}
        fields = self._session_fields(ctx, session)
        name, phone, address = self._legacy_columns(fields, answers)
        try:
            order_id = self.orders.create(
                ctx.platform, ctx.chat, lines, payment_method="", note=answers.get("notes", ""),
                reserve_minutes=int(getattr(ctx.settings, "reservation_minutes", 15) or 15),
                customer_name=name, customer_phone=phone, customer_address=address, customer_info=answers,
                discount_code=self.discounts.cart_code(ctx.platform, ctx.chat), auto_discounts=True,
            )
        except DiscountError as exc:  # N8: کد وسطِ راه نامعتبر شد (ظرفیت پر، مهلت، ...) ← بدونِ سفارش، برگشت به سبد
            self.sessions.clear(ctx.platform, ctx.chat)
            self.discounts.clear_cart_code(ctx.platform, ctx.chat)
            return self._cart_view(ctx, notice=ctx.t(f"disc.err.{'unknown' if exc.code in ('inactive', 'locked') else exc.code}"))
        except OrderError as exc:
            self.sessions.clear(ctx.platform, ctx.chat)
            res = self._cart_view(ctx)
            res.messages.insert(0, UiMessage(str(exc), edit=False))
            return res
        self.carts.clear(ctx.platform, ctx.chat)
        self.discounts.clear_cart_code(ctx.platform, ctx.chat)
        self.sessions.clear(ctx.platform, ctx.chat)
        order = self.orders.get(order_id)
        head = UiMessage(ctx.t("co.created", order_id=order_id) + "\n\n" + build_order_summary_text(order), edit=True, log=True)
        return FlowResult([head, *await self._instruction(ctx, order, method), self._menu_result(ctx).messages[0]], answer=ctx.t("co.created", order_id=order_id))

    async def _instruction(self, ctx: _Ctx, order, method: str) -> list:
        """پیام(های) دستورِ پرداخت؛ خطای ساختِ دستور هرگز متنِ خامِ مخصوصِ مدل رو به مشتری نشون نمی‌ده."""
        rows: list = [[Btn(ctx.t("ord.title"), f"c:od:{order.id}")]]
        try:
            ins = await self.payments.build_instruction(order, method, self.hooks)
        except PaymentError as exc:
            logger.warning("ساخت دستورِ پرداخت برای سفارش %s ناموفق: %s", order.id, exc)
            if self.attention is not None:
                self.attention.add("payment_failed", str(order.id), str(exc))
            return [UiMessage(ctx.t("co.pay_failed"), [[Btn(ctx.t("ord.pay"), f"c:op:{order.id}")], *rows], log=True)]
        url_rows = [[Btn(label, url=url)] for label, url in ins.buttons if safe_url(url)]
        extra = [[Btn(ctx.t("pay.claim"), f"c:paid:{order.id}")]] if method == METHOD_CARD_TO_CARD else []
        return [UiMessage(ins.text, url_rows + extra + rows, log=True)]

    # ===================================================== جمع‌آوریِ سرنخ (R2) ====

    async def _start_lead(self, ctx: _Ctx) -> FlowResult:
        fields = [f for f in cf.load_fields(ctx.settings) if f.applies_to != "physical"]  # آدرس/کدپستیِ کالای فیزیکی به سرنخ ربطی نداره
        if not fields:
            raise _Stale()
        data = {"kind": "lead", "fields": [f.id for f in fields], "answers": {}, "idx": 0, "edit_only": False}
        self.sessions.put(ctx.platform, ctx.chat, "field", data)
        return self._prompt_view(ctx, self.sessions.get(ctx.platform, ctx.chat))

    async def _finish_lead(self, ctx: _Ctx, session: CheckoutSession, fields: list) -> FlowResult:
        self.sessions.clear(ctx.platform, ctx.chat)
        answers = session.data.get("answers", {})
        label = sanitize_display_name(ctx.ev.display_name) or ctx.chat
        details = "\n".join(f"{f.label}: {_clip(answers.get(f.id, '—'), 300)}" for f in fields)
        await self.hooks.notify_owner(shop_texts.render(ctx.settings, "lead.owner", "fa", label=label, platform=ctx.platform, details=details))
        if self.attention is not None:
            self.attention.add("lead", f"{ctx.platform}:{ctx.chat}", " | ".join(f"{f.label}: {answers.get(f.id, '—')}" for f in fields))
        return FlowResult([UiMessage(ctx.t("lead.done"), menu=self._menu_rows(ctx), log=True)], answer=ctx.t("lead.done"))

    # ============================================================ پیگیری ====

    def _own_order(self, ctx: _Ctx, order_id: int):
        order = self.orders.get(order_id)
        if order is None or order.platform != ctx.platform or str(order.chat_id) != ctx.chat:
            raise _Stale()
        return order

    def _status_label(self, ctx: _Ctx, order) -> str:
        return ctx.t(f"ord.status.{order.status}")

    def _orders_view(self, ctx: _Ctx) -> FlowResult:
        orders = [o for o in self.orders.list_for_chat(ctx.platform, ctx.chat) if o is not None][:ORDERS_LIST_LIMIT]
        if not orders:
            return FlowResult([UiMessage(ctx.t("ord.none"), edit=ctx.cb)])
        rows = [
            [Btn(_clip(ctx.t("ord.line", id=o.id, status=self._status_label(ctx, o), amount=_money(o.total_irr))), f"c:od:{o.id}")]
            for o in orders
        ]
        return FlowResult([UiMessage(ctx.t("ord.title"), rows, edit=ctx.cb)])

    def _order_view(self, ctx: _Ctx, order_id: int) -> FlowResult:
        order = self._own_order(ctx, order_id)
        text = [build_order_summary_text(order), self._status_label(ctx, order)]
        if order.status == STATUS_PENDING_PAYMENT and order.seconds_left():
            text.append(ctx.t("ord.left", minutes=max(1, math.ceil(order.seconds_left() / 60))))
        labels = {f.id: f.label for f in cf.load_fields(ctx.settings)}
        for key, value in order.customer_info.items():
            text.append(ctx.t("ord.info", label=labels.get(key, key), value=_clip(str(value), 200)))
        rows = []
        if order.status == STATUS_PENDING_PAYMENT:
            rows.append([Btn(ctx.t("ord.pay"), f"c:op:{order.id}"), Btn(ctx.t("ord.cancel"), f"c:oc:{order.id}")])
            if order.payment_method == METHOD_CARD_TO_CARD:
                rows.append([Btn(ctx.t("pay.claim"), f"c:paid:{order.id}")])
        if order.status == STATUS_CONFIRMED and order.total_irr > 0 and self.invoice_handler is not None and self.invoice_visible():
            rows.append([Btn(ctx.t("inv.button"), f"c:inv:{order.id}")])
        rows.append([Btn(ctx.t("ui.back"), "c:o")])
        return FlowResult([UiMessage("\n".join(text), rows, edit=ctx.cb)])

    def _cancel_order(self, ctx: _Ctx, order_id: int, confirmed: bool) -> FlowResult:
        order = self._own_order(ctx, order_id)
        if order.status != STATUS_PENDING_PAYMENT:
            return FlowResult([UiMessage(ctx.t("ord.cannot_cancel"), edit=True)], answer=ctx.t("ord.cannot_cancel"))
        if not confirmed:
            rows = [[Btn(ctx.t("ord.cancel_yes"), f"c:oc:{order.id}:y"), Btn(ctx.t("ui.back"), f"c:od:{order.id}")]]
            return FlowResult([UiMessage(ctx.t("ord.cancel_confirm", order_id=order.id), rows, edit=True)])
        try:
            self.orders.cancel(order.id)
        except OrderError:
            return FlowResult([UiMessage(ctx.t("ord.cannot_cancel"), edit=True)], answer=ctx.t("ord.cannot_cancel"))
        return FlowResult([UiMessage(ctx.t("ord.cancelled", order_id=order.id), edit=True)], answer=ctx.t("ord.cancelled", order_id=order.id))

    async def _claim_card_payment(self, ctx: _Ctx, order_id: int) -> FlowResult:
        order = self._own_order(ctx, order_id)
        bad = FlowResult([UiMessage(ctx.t("pay.claim_bad"))], answer=ctx.t("pay.claim_bad"))
        if order.status not in (STATUS_PENDING_PAYMENT, STATUS_EXPIRED) or order.payment_method != METHOD_CARD_TO_CARD:
            return bad
        try:
            self.orders.mark_paid(order.id, METHOD_CARD_TO_CARD, "")
        except OrderError:
            return bad
        fresh = self.orders.get(order.id)
        await self.hooks.notify_owner(order_alert_text(fresh, "needs_confirm"))
        self.sessions.put(ctx.platform, ctx.chat, "ref", {"order_id": order.id}, ttl=REF_TTL_SECONDS)
        return FlowResult([UiMessage(ctx.t("pay.claim_done"), log=True)], answer=ctx.t("pay.received"))

    async def _save_reference(self, ctx: _Ctx, session: CheckoutSession, text: str) -> FlowResult:
        self.sessions.clear(ctx.platform, ctx.chat)
        order_id = int(session.data.get("order_id", 0))
        order = self.orders.get(order_id)
        if order is None or order.platform != ctx.platform or str(order.chat_id) != ctx.chat or not self.orders.set_reference(order_id, cf.normalize_input(text, 100)):
            return FlowResult(consumed=False)
        await self.hooks.notify_owner(f"🧾 شماره پیگیریِ سفارش #{order_id}: {cf.normalize_input(text, 100)}")
        return FlowResult([UiMessage(ctx.t("pay.ref_saved"), log=True)])

    # ================================================================ FAQ ====

    # ============================================================ راهنما (N5) ====

    @staticmethod
    def _guide_button(ctx: _Ctx, button) -> Btn:
        """لینک‌ها مستقیم دکمه‌ی URL می‌شن (یک لمس)؛ بقیه از راهِ callbackِ دکمه‌ی سفارشی."""
        if button.action == "url" and safe_url(str(button.config.get("url", ""))):
            return Btn(_clip(button.display, 30), url=str(button.config["url"]).strip())
        return Btn(_clip(button.display, 30), f"c:b:{button.id}")

    def _guide_view(self, ctx: _Ctx, page: int = 1) -> FlowResult:
        customs = custom_buttons.visible(ctx.settings, ctx.platform)
        rest = customs[GUIDE_DIRECT_CUSTOM:]
        rows: list = []
        if page <= 1:
            if ctx.mode.faq and self._faq_items(ctx):
                rows.append([Btn(ctx.t("menu.faq"), "c:f:1")])
            rows += [[self._guide_button(ctx, b)] for b in customs[:GUIDE_DIRECT_CUSTOM]]
            if rest:
                rows.append([Btn(ctx.t("guide.more"), "c:g:2")])
        else:
            pages = max(1, math.ceil(len(rest) / GUIDE_PAGE_SIZE))
            page = max(2, min(page, pages + 1))
            start = (page - 2) * GUIDE_PAGE_SIZE
            rows += [[self._guide_button(ctx, b)] for b in rest[start : start + GUIDE_PAGE_SIZE]]
            nav = [Btn(ctx.t("ui.back"), f"c:g:{page - 1}")]
            if page - 1 < pages:
                nav.append(Btn(ctx.t("guide.more"), f"c:g:{page + 1}"))
            rows.append(nav)
        text = ctx.t("guide.title") + "\n\n" + ctx.t("guide.body")
        return FlowResult([UiMessage(text, rows, edit=ctx.cb)])

    def _faq_items(self, ctx: _Ctx) -> list:
        raw = getattr(ctx.settings, "faq_items", None)
        return [i for i in raw if isinstance(i, dict) and str(i.get("q", "")).strip() and str(i.get("a", "")).strip()] if isinstance(raw, list) else []

    def _faq_view(self, ctx: _Ctx, page: int) -> FlowResult:
        items = self._faq_items(ctx)
        if not items:
            return FlowResult([UiMessage(ctx.t("faq.empty"), edit=ctx.cb)])
        pages = max(1, math.ceil(len(items) / FAQ_PAGE_SIZE))
        page = max(1, min(page, pages))
        rows = [[Btn(_clip(str(item["q"])), f"c:fa:{i}")] for i, item in list(enumerate(items))[(page - 1) * FAQ_PAGE_SIZE : page * FAQ_PAGE_SIZE]]
        if pages > 1:
            nav = []
            if page > 1:
                nav.append(Btn(ctx.t("cat.prev"), f"c:f:{page - 1}"))
            nav.append(Btn(ctx.t("cat.page", page=page, pages=pages), "c:n"))
            if page < pages:
                nav.append(Btn(ctx.t("cat.next"), f"c:f:{page + 1}"))
            rows.append(nav)
        return FlowResult([UiMessage(ctx.t("faq.title"), rows, edit=ctx.cb)])

    def _faq_answer(self, ctx: _Ctx, idx: int) -> FlowResult:
        items = self._faq_items(ctx)
        if not 0 <= idx < len(items):
            raise _Stale()
        item = items[idx]
        rows = [[Btn(ctx.t("faq.back"), f"c:f:{idx // FAQ_PAGE_SIZE + 1}")]]
        return FlowResult([UiMessage(f"❓ {item['q']}\n\n{item['a']}", rows, edit=True)])

    # ===================================================== دکمه‌های سفارشی ====

    async def _run_custom(self, ctx: _Ctx, button_id: str) -> FlowResult:
        button = next((b for b in custom_buttons.visible(ctx.settings, ctx.platform) if b.id == button_id), None)
        if button is None:
            raise _Stale()
        cfg = button.config
        action = button.action
        if action == "url":
            url = str(cfg.get("url", ""))
            text = str(cfg.get("caption") or button.label)
            if not safe_url(url):
                return FlowResult([UiMessage(f"{text}\n{url}")])
            return FlowResult([UiMessage(text, [[Btn(_clip(button.label, 30), url=url)]])])
        if action == "text":
            return FlowResult([UiMessage(str(cfg.get("text", "")))])
        if action == "phone":
            phone = str(cfg.get("phone", "")).strip()
            name = getattr(ctx.settings, "user_name", "") or button.label
            return FlowResult([UiMessage(f"📞 {phone}"), UiMessage(contact=(phone, name))])
        if action == "support":
            if self.support_handler is None:
                return FlowResult([UiMessage(ctx.t("ui.no_support"))])
            return await self.support_handler(ctx.ev)
        if action == "ask_ai":
            return FlowResult(consumed=False, ai_text=str(cfg.get("question", "")))
        if action == "share_contact":
            return FlowResult([UiMessage(ctx.t("custom.share_contact"), menu=self._menu_rows(ctx), request_contact=ctx.t("co.share_phone"))])
        mapping = {"open_catalog": "products", "open_cart": "cart", "open_orders": "orders", "checkout": "checkout"}
        if action in mapping:
            return await self._run_action(ctx, mapping[action])
        raise _Stale()
