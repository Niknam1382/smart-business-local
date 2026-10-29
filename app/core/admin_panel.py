"""پنلِ مدیریتِ داخلِ ربات (N11): همان «اپِ موبایلِ بدونِ نصب»ِ مالک و مدیران.

* ``/id`` — **برای هر کسی** جواب می‌ده و شناسه‌ی عددیِ خودش را نشون می‌ده (برای افزودنِ مدیر با شناسه).
* ``/start admin_<توکن>`` — پذیرشِ دعوتِ یک‌بارمصرف (لینکِ عمیق/QR). توکنِ ناشناخته *بی‌صدا* رد می‌شه (مثلِ ``/start`` عادی)؛
  توکنِ شناخته‌شده‌ی منقضی/استفاده‌شده پیامِ روشن می‌گیره (فقط دعوت‌شده‌ها آن را دارن).
* اولین پیامِ یک شناسه‌ی «در انتظار» (افزوده‌شده با شناسه) دسترسی را فعال می‌کنه.
* ``/admin`` — منوی دکمه‌ای؛ فقط برای مالک/مدیرانِ فعال. بقیه هیچ پاسخی نمی‌گیرن (قابلیت لو نمی‌ره).

**امنیت:** هر دکمه (``adm:<عمل>[:آرگومان]``) سمتِ سرور با ``role_of`` + جدولِ قابلیت‌ها (``ROUTES``) سنجیده می‌شه؛ مجوز هرگز از
متنِ callback خوانده نمی‌شه. callbackِ جعلی از غیرمدیر بی‌اثر و بی‌صداست؛ از مدیرِ فاقدِ قابلیت «دسترسی نداری» می‌گیره.
ردِ سفارش یک مرحله تأیید دارد (چون به مشتری خبر می‌ده).
"""

from __future__ import annotations

import asyncio
import calendar
import logging
import re
import time
from typing import Callable, Optional

from app.core import admins as am
from app.core.admins import AdminStore
from app.core.orders import STATUS_CONFIRMED, STATUS_PAID, STATUS_PENDING_PAYMENT
from app.core.owner_console import _money, order_details
from app.core.products import ProductError
from app.core.ui import Btn, FlowResult, UiMessage, deliver

logger = logging.getLogger(__name__)

CB = "adm:"
_INVITE_RE = re.compile(r"/start(?:@\w+)?\s+admin_([A-Za-z0-9_-]{8,64})")
_PAGE = 8
_STOCK_STEPS = (1, 5, 10)
_LOW_STOCK = 3

_INVITE_TEXTS = {
    "expired": "⌛ این لینک دعوت منقضی شده. از مالکِ فروشگاه بخواه لینکِ تازه بسازه.",
    "used": "⚠️ این لینک دعوت قبلاً استفاده شده. از مالکِ فروشگاه بخواه لینکِ تازه بسازه.",
    "wrong_platform": "⚠️ این لینک برای پیام‌رسانِ دیگه‌ای ساخته شده؛ از مالک بخواه برای همین پیام‌رسان لینک بسازه.",
    "owner": "تو همین حالا مالکِ این فروشگاهی. ✅ برای باز کردنِ پنل /admin رو بفرست.",
}


def _command(text: str) -> str:
    parts = (text or "").strip().split()
    return parts[0].split("@")[0].lower() if parts else ""


def _local_day_start(now: float) -> int:
    t = time.localtime(now)
    return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))


def _utc_epoch(stamp: str) -> int:
    try:
        return calendar.timegm(time.strptime(stamp, "%Y-%m-%d %H:%M:%S"))
    except (ValueError, TypeError):
        return 0


def _back(label: str = "◀️ منو", data: str = CB + "home") -> list:
    return [Btn(label, data)]


class AdminPanel:
    def __init__(
        self,
        admins: AdminStore,
        console,
        orders,
        products,
        handoff=None,
        clock: Callable[[], float] = time.time,
        discounts=None,
        finance=None,
        invoices=None,
        get_settings: Callable[[], object] = lambda: None,
    ):
        self._admins = admins
        self._console = console
        self._orders = orders
        self._products = products
        self._handoff = handoff
        self._clock = clock
        self._discounts = discounts  # N8 (اختیاری)
        self._finance = finance  # N19 (اختیاری)
        self._invoices = invoices  # N19 (اختیاری)
        self._get_settings = get_settings
        # عمل → (قابلیتِ لازم, هندلر, تعدادِ دقیقِ آرگومان). **تنها منبعِ مجوزِ دکمه‌ها** — عملِ ناشناخته یا تعدادِ آرگومانِ
        # نادرست بی‌اثره (callbackِ دست‌ساز با آرگومانِ اضافه هم رد می‌شه).
        self._routes: dict = {
            "home": (am.CAP_PANEL, self._home, 0),
            "ord": (am.CAP_ORDERS_VIEW, self._orders_list, 0),
            "od": (am.CAP_ORDERS_VIEW, self._order_card, 1),
            "ok": (am.CAP_ORDERS_DECIDE, self._order_confirm, 1),
            "no": (am.CAP_ORDERS_DECIDE, self._order_reject_ask, 1),
            "nox": (am.CAP_ORDERS_DECIDE, self._order_reject, 1),
            "stk": (am.CAP_STOCK_VIEW, self._low_stock, 0),
            "prd": (am.CAP_STOCK_VIEW, self._products_list, 0),
            "sp": (am.CAP_STOCK_VIEW, self._product_card, 1),
            "sa": (am.CAP_STOCK_EDIT, self._stock_adjust, 2),
            "tg": (am.CAP_PRODUCTS_TOGGLE, self._product_toggle, 1),
            "sts": (am.CAP_STATS_VIEW, self._stats, 0),
            "sup": (am.CAP_SUPPORT_VIEW, self._support, 0),
            "dsc": (am.CAP_DISCOUNTS_TOGGLE, self._discounts_list, 0),
            "dtg": (am.CAP_DISCOUNTS_TOGGLE, self._discount_toggle, 1),
            "fin": (am.CAP_FINANCE_VIEW, self._finance_summary, 0),
            "inv": (am.CAP_INVOICE_RESEND, self._invoice_resend, 1),
        }

    # ------------------------------------------------------------- ورودی ----

    async def handle(self, message, send, transport, rate_ok: Callable[[], bool] = lambda: True) -> bool:
        """``True`` = این پیام مالِ پنل بود و پردازش شد (به بقیه‌ی مسیرها نرو)."""
        platform, chat_id = message.platform, str(message.chat_id)
        if message.callback_data:
            if not message.callback_data.startswith(CB):
                return False
            result = await self._on_callback(message)
            await deliver(transport, chat_id, result, callback_id=message.callback_id, source_message_id=message.message_id)
            return True
        text = (message.text or "").strip()
        name = " ".join(p for p in (getattr(message, "first_name", ""), getattr(message, "last_name", "")) if p) or message.display_name
        username = getattr(message, "username", "")

        if _command(text) == "/id":
            if not rate_ok():
                return True
            await send(f"🆔 شناسه‌ی عددیِ تو: {chat_id}\n(برای مدیر شدن، همین عدد رو به مالکِ فروشگاه بده.)")
            return True

        invite = _INVITE_RE.fullmatch(text)
        if invite:
            if not rate_ok():
                return True
            return await self._accept(invite.group(1), message, name, username, send, transport)

        activated = self._admins.activate_if_pending(platform, chat_id, name, username)
        if activated is not None:
            await self._welcome(activated.role, chat_id, transport, prefix="✅ دسترسیِ مدیریتِ تو فعال شد.")
            if text.startswith("/"):
                return True

        role = self._admins.role_of(platform, chat_id)
        if role:
            self._admins.touch(platform, chat_id, name, username)
            if _command(text) in ("/admin", "/panel") and am.can(role, am.CAP_PANEL):
                await deliver(transport, chat_id, FlowResult(messages=[self._menu(role, edit=False)]))
                return True
        return False

    async def _accept(self, token: str, message, name: str, username: str, send, transport) -> bool:
        result = self._admins.accept_invite(token, message.platform, str(message.chat_id), name, username)
        if result.status == "unknown":
            return False  # بی‌صدا: /start عادی
        if result.status != "ok":
            await send(_INVITE_TEXTS.get(result.status, _INVITE_TEXTS["used"]))
            return True
        await self._welcome(result.role, str(message.chat_id), transport, prefix=f"✅ به‌عنوان «{am.ROLE_LABEL_FA[result.role]}» به مدیریتِ این فروشگاه اضافه شدی.")
        return True

    async def _welcome(self, role: str, chat_id: str, transport, prefix: str) -> None:
        menu = self._menu(role, edit=False, intro=prefix)
        await deliver(transport, chat_id, FlowResult(messages=[menu]))

    # ------------------------------------------------------------- callback ----

    async def _on_callback(self, message) -> FlowResult:
        platform, chat_id = message.platform, str(message.chat_id)
        role = self._admins.role_of(platform, chat_id)
        if not role:
            logger.warning("callbackِ پنلِ مدیریت از غیرمدیر (%s/%s) نادیده گرفته شد", platform, chat_id)
            return FlowResult()  # بی‌صدا و بی‌اثر
        parts = message.callback_data.split(":")
        route = self._routes.get(parts[1] if len(parts) > 1 else "")
        if route is None:
            return FlowResult()
        capability, handler, arity = route
        if len(parts) - 2 != arity:
            return FlowResult()
        if not self._can(role, capability):
            return FlowResult(answer="⛔ دسترسیِ نقشِ تو به این بخش نیست.", alert=True)
        try:
            return await handler(role, platform, chat_id, parts[2:])
        except (ValueError, IndexError):
            return FlowResult()
        except Exception:  # noqa: BLE001 — خطای یک دکمه نباید ربات را بشکنه
            logger.exception("خطا در دکمه‌ی پنلِ مدیریت")
            return FlowResult(answer="خطایی رخ داد؛ دوباره امتحان کن.", alert=True)

    def attach_finance(self, finance, invoices) -> None:
        """N19: سرویس‌های مالی بعد از ساخته‌شدنشان وصل می‌شن (ترتیبِ ساختِ BotManager)."""
        self._finance, self._invoices = finance, invoices

    def _can(self, role: str, capability: str) -> bool:
        grant = bool(getattr(self._get_settings(), "finance_manager_access", False))
        return am.can_effective(role, capability, grant)

    @staticmethod
    def _edit(text: str, rows: Optional[list] = None) -> FlowResult:
        return FlowResult(messages=[UiMessage(text=text, rows=rows or [], edit=True)])

    # ------------------------------------------------------------------ منو ----

    def _menu(self, role: str, edit: bool, intro: str = "") -> UiMessage:
        waiting = sum(1 for o in self._orders.list() if o.status == STATUS_PAID) if am.can(role, am.CAP_ORDERS_VIEW) else 0
        support = len(self._handoff.list_open()) if (self._handoff is not None and am.can(role, am.CAP_SUPPORT_VIEW)) else 0
        rows: list = []
        if am.can(role, am.CAP_ORDERS_VIEW):
            rows.append([Btn(f"🧾 سفارش‌های منتظر ({waiting})", CB + "ord")])
        if am.can(role, am.CAP_STOCK_VIEW):
            rows.append([Btn("📦 موجودیِ کم", CB + "stk"), Btn("🏷 محصولات", CB + "prd")])
        if am.can(role, am.CAP_STATS_VIEW):
            rows.append([Btn("📊 آمارِ امروز", CB + "sts")])
        if am.can(role, am.CAP_SUPPORT_VIEW):
            rows.append([Btn(f"🙋 پشتیبانی ({support})", CB + "sup")])
        if self._discounts is not None and am.can(role, am.CAP_DISCOUNTS_TOGGLE):
            rows.append([Btn("🎟 کدهای تخفیف", CB + "dsc")])
        if self._finance is not None and self._can(role, am.CAP_FINANCE_VIEW):
            rows.append([Btn("💰 خلاصه‌ی مالی", CB + "fin")])
        head = f"🛠 پنلِ مدیریت — نقش: {am.ROLE_LABEL_FA.get(role, role)}"
        text = (intro + "\n\n" if intro else "") + head + "\nدستورهای متنی: /orders · /stock · /handoffs · /id"
        return UiMessage(text=text, rows=rows, edit=edit)

    async def _home(self, role, platform, chat_id, args) -> FlowResult:
        return FlowResult(messages=[self._menu(role, edit=True)])

    # --------------------------------------------------------------- سفارش‌ها ----

    async def _orders_list(self, role, platform, chat_id, args) -> FlowResult:
        waiting = [o for o in self._orders.list() if o.status == STATUS_PAID]
        pending = sum(1 for o in self._orders.list() if o.status == STATUS_PENDING_PAYMENT and o.seconds_left() > 0)
        if not waiting:
            return self._edit(f"سفارشِ منتظر تایید نداری. ✅\n(در انتظار پرداختِ مشتری: {pending})", [_back()])
        decide = am.can(role, am.CAP_ORDERS_DECIDE)
        lines = [f"📋 منتظر تایید: {len(waiting)} (در انتظار پرداخت: {pending})"]
        rows: list = []
        for order in waiting[:_PAGE]:
            lines.append(f"• #{order.id} — {_money(order.total_irr)}" + (" ⚠️دیررس" if order.paid_late else ""))
            row = [Btn(f"🔎 #{order.id}", f"{CB}od:{order.id}")]
            if decide:
                row = [Btn(f"✅ #{order.id}", f"{CB}ok:{order.id}"), Btn(f"❌ #{order.id}", f"{CB}no:{order.id}")] + row
            rows.append(row)
        if len(waiting) > _PAGE:
            lines.append(f"… و {len(waiting) - _PAGE} سفارشِ دیگر (از اپ یا /orders ببین).")
        rows.append(_back())
        return self._edit("\n".join(lines), rows)

    def _need_order(self, args):
        order = self._orders.get(int(args[0]))
        if order is None:
            raise ValueError("no order")
        return order

    async def _order_card(self, role, platform, chat_id, args) -> FlowResult:
        order = self._need_order(args)
        text = order_details(order) + f"\nوضعیت: {order.status}" + ("\n⚠️ پرداخت دیررس" if order.paid_late else "")
        confirmer = self._orders.confirmed_by(order.id)
        if confirmer:
            text += f"\nتأییدکننده: {confirmer}"
        rows: list = []
        if order.status == STATUS_PAID and am.can(role, am.CAP_ORDERS_DECIDE):
            rows.append([Btn("✅ تایید", f"{CB}ok:{order.id}"), Btn("❌ رد", f"{CB}no:{order.id}")])
        if order.status == STATUS_CONFIRMED and order.total_irr > 0 and self._invoices is not None and self._can(role, am.CAP_INVOICE_RESEND):
            rows.append([Btn("🧾 ارسالِ مجددِ فاکتور", f"{CB}inv:{order.id}")])
        rows.append(_back("◀️ سفارش‌ها", CB + "ord"))
        return self._edit(text, rows)

    async def _finance_summary(self, role, platform, chat_id, args) -> FlowResult:
        from app.core import jalali

        t0, t1 = jalali.today_range(self._clock())
        jy, jm, _jd = jalali.ts_to_jalali(self._clock())
        m0, m1 = jalali.month_range(jy, jm)
        lines = ["💰 خلاصه‌ی مالی (ابزارِ کمکی؛ جایگزینِ حسابدارِ رسمی نیست)"]
        for label, a, b in (("امروز", t0, t1), (f"این ماه ({jalali.MONTHS_FA[jm - 1]})", m0, m1)):
            r = self._finance.report(a, b, top_n=0)
            lines.append(f"\n{label}:\nفروشِ خالص: {_money(r.sales_net)} ریال ({r.orders_count} سفارش)\nهزینه‌ها: {_money(r.expenses)} ریال\nسودِ خالص: {_money(r.net_profit)} ریال")
        return self._edit("\n".join(lines), [_back()])

    async def _invoice_resend(self, role, platform, chat_id, args) -> FlowResult:
        order = self._need_order(args)
        if order.status != STATUS_CONFIRMED or order.total_irr <= 0 or self._invoices is None:
            return FlowResult(answer="برای این سفارش فاکتور صادر نمی‌شه.", alert=True)
        try:
            inv = await asyncio.to_thread(self._invoices.issue, order)
        except Exception:  # noqa: BLE001
            return FlowResult(answer="صدورِ فاکتور ناموفق بود.", alert=True)
        outcome = await self._invoices.send_customer(inv.id, force=True)
        if outcome == "sent":
            return FlowResult(answer="✅ فاکتور برای مشتری فرستاده شد.")
        reason = {"skipped:blocked": "مشتری بلاک شده.", "skipped:unreachable": "مشتری دیگه قابلِ پیام‌دادن نیست.", "skipped:forgotten": "مشتری درخواستِ حذفِ اطلاعاتش را داده."}.get(outcome, "ارسال ناموفق بود؛ بعداً دوباره امتحان کن.")
        return FlowResult(answer="⚠️ " + reason, alert=True)

    async def _order_confirm(self, role, platform, chat_id, args) -> FlowResult:
        order = self._need_order(args)
        text = await self._console.decide("confirm", order.id, self._console.actor_of(platform, chat_id))
        return self._edit(text, [_back("◀️ سفارش‌ها", CB + "ord")])

    async def _order_reject_ask(self, role, platform, chat_id, args) -> FlowResult:
        order = self._need_order(args)
        return self._edit(
            f"❌ سفارش #{order.id} رد بشه؟ (به مشتری اطلاع داده می‌شه و برگشتِ مبلغ با خودته)",
            [[Btn("بله، رد کن", f"{CB}nox:{order.id}"), Btn("انصراف", CB + "ord")]],
        )

    async def _order_reject(self, role, platform, chat_id, args) -> FlowResult:
        order = self._need_order(args)
        text = await self._console.decide("reject", order.id, self._console.actor_of(platform, chat_id))
        return self._edit(text, [_back("◀️ سفارش‌ها", CB + "ord")])

    # ----------------------------------------------------------- موجودی/محصول ----

    def _available(self, product) -> int:
        return self._orders.available_quantity(product.id)

    async def _low_stock(self, role, platform, chat_id, args) -> FlowResult:
        low = [p for p in self._products.list(include_inactive=True) if not p.unlimited_stock and self._available(p) < _LOW_STOCK]
        if not low:
            return self._edit("همه‌ی کالاها موجودیِ کافی دارن. ✅", [_back()])
        rows = [[Btn(f"{p.name[:28]} — {self._available(p)}", f"{CB}sp:{p.id}")] for p in low[:_PAGE]]
        rows.append(_back())
        return self._edit("📦 کم‌موجود/تمام‌شده (برای تغییرِ سریع روی کالا بزن):", rows)

    async def _products_list(self, role, platform, chat_id, args) -> FlowResult:
        products = self._products.list(include_inactive=True)
        if not products:
            return self._edit("هنوز محصولی ثبت نشده.", [_back()])
        rows = [[Btn(("🟢 " if p.active else "🔴 ") + p.name[:30], f"{CB}sp:{p.id}")] for p in products[:_PAGE + 4]]
        rows.append(_back())
        extra = f"\n(فقط {_PAGE + 4} محصولِ اول؛ بقیه را از اپ ببین.)" if len(products) > _PAGE + 4 else ""
        return self._edit("🏷 محصولات:" + extra, rows)

    def _product_view(self, role: str, product) -> FlowResult:
        stock = "نامحدود" if product.unlimited_stock else f"{product.stock_quantity} (قابل‌فروشِ الان: {self._available(product)})"
        text = f"📦 {product.name}\nقیمت: {_money(product.price_irr)}\nموجودی: {stock}\nوضعیت: {'فعال 🟢' if product.active else 'غیرفعال 🔴'}"
        rows: list = []
        if am.can(role, am.CAP_STOCK_EDIT) and not product.unlimited_stock:
            rows.append([Btn(f"➕{n}", f"{CB}sa:{product.id}:{n}") for n in _STOCK_STEPS])
            rows.append([Btn("➖1", f"{CB}sa:{product.id}:-1"), Btn("➖5", f"{CB}sa:{product.id}:-5")])
        if am.can(role, am.CAP_PRODUCTS_TOGGLE):
            rows.append([Btn("🔴 غیرفعال کن" if product.active else "🟢 فعال کن", f"{CB}tg:{product.id}")])
        rows.append(_back("◀️ محصولات", CB + "prd"))
        return self._edit(text, rows)

    def _need_product(self, args):
        product = self._products.get(int(args[0]))
        if product is None:
            raise ValueError("no product")
        return product

    async def _product_card(self, role, platform, chat_id, args) -> FlowResult:
        return self._product_view(role, self._need_product(args))

    async def _stock_adjust(self, role, platform, chat_id, args) -> FlowResult:
        product = self._need_product(args)
        delta = int(args[1])
        if delta == 0 or abs(delta) > 100:
            raise ValueError("bad delta")
        try:
            self._products.adjust_stock(product.id, delta)
        except ProductError as exc:
            return FlowResult(answer=str(exc)[:150], alert=True)
        self._admins.audit("stock_changed", actor=self._console.actor_of(platform, chat_id), detail=f"#{product.id} {delta:+d}")
        return self._product_view(role, self._products.get(product.id))

    def _discounts_view(self) -> FlowResult:
        codes = self._discounts.list()[:20]
        if not codes:
            return self._edit("هنوز کدِ تخفیفی نساخته‌ای (از داخلِ برنامه بساز).", [_back()])
        lines = ["🎟 کدهای تخفیف (برای فعال/غیرفعال‌کردن بزن):", ""]
        rows = []
        for c in codes:
            tag = "🟢" if c.active else "🔴"
            lines.append(f"{tag} {c.code} — {c.used_count}{f' / {c.total_limit}' if c.total_limit else ''} استفاده")
            rows.append([Btn(f"{'🔴 غیرفعال' if c.active else '🟢 فعال'}: {c.code}", f"{CB}dtg:{c.id}")])
        rows.append(_back())
        return self._edit("\n".join(lines), rows)

    async def _discounts_list(self, role, platform, chat_id, args) -> FlowResult:
        return self._discounts_view()

    async def _discount_toggle(self, role, platform, chat_id, args) -> FlowResult:
        code = self._discounts.get(int(args[0]))
        if code is None:
            raise ValueError("no code")
        self._discounts.set_active(code.id, not code.active)
        self._admins.audit("discount_toggled", actor=self._console.actor_of(platform, chat_id), detail=f"#{code.id} {'off' if code.active else 'on'}")
        return self._discounts_view()

    async def _product_toggle(self, role, platform, chat_id, args) -> FlowResult:
        product = self._need_product(args)
        self._products.set_active(product.id, not product.active)
        self._admins.audit("product_toggled", actor=self._console.actor_of(platform, chat_id), detail=f"#{product.id} {'off' if product.active else 'on'}")
        return self._product_view(role, self._products.get(product.id))

    # ------------------------------------------------------------ آمار/پشتیبانی ----

    async def _stats(self, role, platform, chat_id, args) -> FlowResult:
        start = _local_day_start(self._clock())
        new = confirmed = revenue = waiting = pending = 0
        for order in self._orders.list():
            if _utc_epoch(order.created_at) >= start:
                new += 1
            if order.status == STATUS_CONFIRMED and _utc_epoch(order.updated_at) >= start:
                confirmed += 1
                revenue += order.total_irr
            if order.status == STATUS_PAID:
                waiting += 1
            elif order.status == STATUS_PENDING_PAYMENT and order.seconds_left() > 0:
                pending += 1
        support = len(self._handoff.list_open()) if self._handoff is not None else 0
        text = (
            "📊 آمارِ امروز\n"
            f"• سفارشِ جدید: {new}\n• تاییدشده: {confirmed} (جمع: {_money(revenue)})\n"
            f"• منتظرِ تایید: {waiting} · در انتظارِ پرداخت: {pending}\n• گفتگوی پشتیبانیِ باز: {support}"
        )
        return self._edit(text, [_back()])

    async def _support(self, role, platform, chat_id, args) -> FlowResult:
        if self._handoff is None:
            return self._edit("پشتیبانی فعال نیست.", [_back()])
        text = self._handoff.owner_list()
        if am.can(role, am.CAP_SUPPORT_REPLY):
            text += "\n\nپاسخ: /reply <شناسه> متن (یا روی پیامِ فورواردشده Reply بزن)"
        return self._edit(text, [_back()])
