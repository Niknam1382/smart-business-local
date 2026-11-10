"""پنلِ مدیریتِ داخلِ ربات (N11): همان «اپِ موبایلِ بدونِ نصب»ِ مالک و مدیران.

* ``/id`` — **برای هر کسی** جواب می‌ده و شناسه‌ی عددیِ خودش را نشون می‌ده (برای افزودنِ مدیر با شناسه).
* ``/start admin_<توکن>`` — پذیرشِ دعوتِ یک‌بارمصرف (لینکِ عمیق/QR). توکنِ ناشناخته *بی‌صدا* رد می‌شه (مثلِ ``/start`` عادی)؛
  توکنِ شناخته‌شده‌ی منقضی/استفاده‌شده پیامِ روشن می‌گیره (فقط دعوت‌شده‌ها آن را دارن).
* اولین پیامِ یک شناسه‌ی «در انتظار» (افزوده‌شده با شناسه) دسترسی را فعال می‌کنه.
* ``/admin`` — منوی دکمه‌ای؛ فقط برای مالک/مدیرانِ فعال. بقیه هیچ پاسخی نمی‌گیرن (قابلیت لو نمی‌ره).
* ``adm:set`` — کنترل‌پنلِ تنظیماتِ عملیاتی (قلم ۳): جدولِ ``app/core/settings_fields.py``، گروه‌به‌گروه،
  با مقدارِ فعلیِ هر تنظیم و دکمه‌هایِ روشن/خاموش و ‎+N/−N و «تایپِ مقدار».

**امنیت:** هر دکمه (``adm:<عمل>[:آرگومان]``) سمتِ سرور با ``role_of`` + جدولِ قابلیت‌ها (``ROUTES``) سنجیده می‌شه؛ مجوز هرگز از
متنِ callback خوانده نمی‌شه. callbackِ جعلی از غیرمدیر بی‌اثر و بی‌صداست؛ از مدیرِ فاقدِ قابلیت «دسترسی نداری» می‌گیره.
ردِ سفارش یک مرحله تأیید دارد (چون به مشتری خبر می‌ده).
**نوشتنِ تنظیمات** هم همین قاعده را دارد: قابلیتِ هر فیلد از *جدول* خوانده می‌شه (نه از callback)، مقدارِ
ارسال‌شده یک‌بار در ``settings_fields.validate`` سنجیده می‌شه، بعد ذخیره و در ممیزی ثبت می‌شه؛ اگر هر یک از
این‌ها نشود، هیچ مقداری عوض نمی‌شه.
"""

from __future__ import annotations

import asyncio
import calendar
import logging
import re
import time
from typing import Callable, Optional

from app.core import admins as am
from app.core import settings as settings_module
from app.core import settings_fields as sfields
from app.core.handoff import parse_ref as handoff_ref
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
_SETTINGS_LIMIT = 3800  # سقفِ امنِ طولِ پیامِ تنظیمات (تلگرام ۴۰۹۶ کاراکتر است)

# ------------------------------------------------------------------ متنِ مشترک ----

_NO_WRITE = "⛔ نقشِ تو به عوض‌کردنِ این تنظیم دسترسی نداره."
_NO_SETTINGS = "⚙️ تنظیماتِ برنامه به این پنل وصل نیست؛ از برنامه‌ی دسکتاپ استفاده کن."

_INVITE_TEXTS = {
    "expired": "⌛ این لینک دعوت منقضی شده. از مالکِ فروشگاه بخواه لینکِ تازه بسازه.",
    "used": "⚠️ این لینک دعوت قبلاً استفاده شده. از مالکِ فروشگاه بخواه لینکِ تازه بسازه.",
    "wrong_platform": "⚠️ این لینک برای پیام‌رسانِ دیگه‌ای ساخته شده؛ از مالک بخواه برای همین پیام‌رسان لینک بسازه.",
    "owner": "تو همین حالا مالکِ این فروشگاهی. ✅ برای باز کردنِ پنل /admin رو بفرست.",
}

# نمایشِ وضعیتِ «ارسال» در کارتِ سفارش (فقط خواندنی — تغییرش از صفحه‌ی «سفارش‌ها»ی اپ است)
_FULFILL_FA = {"preparing": "🧰 در حال آماده‌سازی", "shipped": "🚚 ارسال شده", "delivered": "📦 تحویل شده"}


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


def _hint(role: str) -> str:
    """یک خطِ راهنما زیرِ منو: همه‌چیز دکمه است و کارهایِ سنگین‌تر در اپِ دسکتاپ‌اند."""
    return "\nهمه‌چیز با همین دکمه‌ها انجام می‌شه. برای بازِکردنِ دوباره: /admin — کارهایِ سنگین‌تر در برنامه‌ی دسکتاپ است."


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
        save_settings: Optional[Callable[[], None]] = None,
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
        # قلم ۳: ذخیره‌ی تنظیمات روی دیسک. تزریق نشده ⇒ خودِ ``settings.save_settings`` (همان
        # نمونه‌ای که ``get_settings`` می‌دهد) — پس بدونِ تغییرِ BotManager هم نوشتن پایدار می‌ماند.
        self._save_settings = save_settings
        # ۲۲: «حالتِ پاسخِ دکمه‌ای» — برای هر مدیر، گفتگویی که منتظرِ متنِ پاسخ است
        self._reply_target: dict = {}
        # قلم ۳: «حالتِ تایپِ مقدار» (کلیدِ تنظیم) و «مقدارِ تایپ‌شدهٔ منتظرِ ذخیره» — هر دو به (پلتفرم، چت)
        self._entry_target: dict = {}
        self._entry_pending: dict = {}
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
            "sr": (am.CAP_SUPPORT_REPLY, self._support_open, 1),
            "sw": (am.CAP_SUPPORT_REPLY, self._support_cancel, 0),
            "sc": (am.CAP_SUPPORT_REPLY, self._support_close, 1),
            "dsc": (am.CAP_DISCOUNTS_TOGGLE, self._discounts_list, 0),
            "dtg": (am.CAP_DISCOUNTS_TOGGLE, self._discount_toggle, 1),
            "fin": (am.CAP_FINANCE_VIEW, self._finance_summary, 0),
            "inv": (am.CAP_INVOICE_RESEND, self._invoice_resend, 1),
            # --- قلم ۳: کنترل‌پنلِ تنظیماتِ عملیاتی (دیدن = settings.view، نوشتن = settings.edit +
            # مجوزِ خودِ فیلد؛ جدولِ فیلدها در ``settings_fields`` است و ``permission`` آن از callback خوانده نمی‌شه) ---
            "set": (am.CAP_SETTINGS_VIEW, self._settings_menu, 0),
            "sg": (am.CAP_SETTINGS_VIEW, self._settings_group, 1),
            "sf": (am.CAP_SETTINGS_VIEW, self._setting_field, 1),
            "sb": (am.CAP_SETTINGS_EDIT, self._setting_toggle, 1),
            "sn": (am.CAP_SETTINGS_EDIT, self._setting_step, 2),
            "so": (am.CAP_SETTINGS_EDIT, self._setting_choice, 2),
            "se": (am.CAP_SETTINGS_EDIT, self._setting_entry, 1),
            "ssv": (am.CAP_SETTINGS_EDIT, self._setting_save, 0),
            "ssc": (am.CAP_SETTINGS_EDIT, self._setting_cancel, 0),
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

        pending = await self.pending_reply(message)
        if pending is not None:
            await deliver(transport, chat_id, pending)
            return True

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
        """قابلیتِ نقش + دو اعطایِ اختیاریِ مالک (هر دو از *تنظیماتِ سرور* خوانده می‌شن، نه از callback)."""
        settings = self._get_settings()
        return am.can_effective(
            role, capability,
            bool(getattr(settings, "finance_manager_access", False)),
            bool(getattr(settings, "managers_can_edit_settings", False)),
        )

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
        if self._can(role, am.CAP_SETTINGS_VIEW):  # قلم ۳: کنترل‌پنلِ تنظیماتِ عملیاتی (دیدن برای مدیر هم مجاز است)
            rows.append([Btn("⚙️ تنظیماتِ عملیاتی", CB + "set")])
        head = f"🛠 پنلِ مدیریت — نقش: {am.ROLE_LABEL_FA.get(role, role)}"
        # قلم ۲۲: پنل با دکمه است، نه دستورِ متنی — پس دیگر /orders و /stock تبلیغ نمی‌شن.
        text = (intro + "\n\n" if intro else "") + head + _hint(role)
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
        if getattr(order, "fulfillment", ""):
            text += "\nارسال: " + _FULFILL_FA.get(order.fulfillment, order.fulfillment)
            if getattr(order, "tracking_code", ""):
                text += f" · کد {order.tracking_code}"
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
        sessions = self._handoff.list_open()
        if not sessions:
            return self._edit(self._handoff.owner_list(), [_back()])
        lines = [f"🙋 {len(sessions)} گفتگوی پشتیبانیِ باز:"]
        rows: list = []
        for session in sessions[:_PAGE]:
            if am.can(role, am.CAP_SUPPORT_REPLY):
                rows.append([Btn(f"💬 {session.customer_label[:22]}", f"{CB}sr:{session.ref}"), Btn("✕ بستن", f"{CB}sc:{session.ref}")])
            else:
                lines.append(f"• {session.customer_label} [{session.ref}]")
        if am.can(role, am.CAP_SUPPORT_REPLY):
            lines.append("روی نامِ مشتری بزن و بعد همان‌جا بنویس؛ پیام مستقیم به او می‌رسه.")
        rows.append(_back())
        return self._edit("\n".join(lines), rows)

    # ------------------------------------------------- ۲۲) پاسخِ دکمه‌ای به پشتیبانی ----

    async def _support_open(self, role, platform, chat_id, args) -> FlowResult:
        target = handoff_ref(args[0])
        if target is None or self._handoff.get(*target) is None:
            return FlowResult(answer="این گفتگو دیگر باز نیست.", alert=True)
        self._entry_target.pop((platform, chat_id), None)  # دو حالتِ «منتظرِ متن» هم‌زمان معنا ندارد
        self._reply_target[(platform, chat_id)] = target
        return self._edit(
            f"💬 حالتِ پاسخ به «{self._label_of(target)}» روشن شد.\n\n"
            "هر پیامی که از این لحظه بفرستی (بدونِ /) مستقیم به همین مشتری می‌رسه.\n"
            "اگر پشیمان شدی «انصراف» را بزن.",
            [[Btn("انصراف", CB + "sw"), Btn("◀️ گفتگوها", CB + "sup")]],
        )

    async def _support_cancel(self, role, platform, chat_id, args) -> FlowResult:
        self._reply_target.pop((platform, chat_id), None)
        return await self._support(role, platform, chat_id, [])

    async def _support_close(self, role, platform, chat_id, args) -> FlowResult:
        target = handoff_ref(args[0])
        if target is None:
            return FlowResult(answer="این گفتگو دیگر باز نیست.", alert=True)
        self._reply_target.pop((platform, chat_id), None)
        outcome = await self._handoff.owner_close(*target)
        listing = await self._support(role, platform, chat_id, [])
        listing.messages[0].text = outcome + "\n\n" + listing.messages[0].text
        return listing

    def _label_of(self, target) -> str:
        session = self._handoff.get(*target) if self._handoff is not None else None
        return session.customer_label if session else target[1]

    async def pending_reply(self, message) -> Optional[FlowResult]:
        """۲۲: متنِ آزادِ مدیر، وقتی حالتِ پاسخ روشن است، به همان مشتری می‌رسه — بدونِ /reply.
        قلم ۳: همان حالتِ «منتظرِ متن» برایِ تایپِ مقدارِ یک تنظیم هم کار می‌کنه (بدونِ هیچ دستوری)."""
        where = (message.platform, str(message.chat_id))
        typed = (message.text or "").strip()
        key = self._entry_target.get(where)
        if key is not None:
            return await self._setting_typed(message, key, typed)
        target = self._reply_target.get(where)
        if target is None or self._handoff is None:
            return None
        text = typed
        if not text or text.startswith("/"):
            return None  # مدیر دارد دستورِ دیگری می‌دهد؛ حالتِ پاسخ دست‌نخورده می‌ماند
        answer = await self._handoff.owner_reply(*target, text)
        self._reply_target.pop(where, None)
        return FlowResult(messages=[UiMessage(answer + "\n\nبرای پاسخِ بعدی دوباره از «پشتیبانی» دکمه را بزن.")])

    # ================== ۳) کنترل‌پنلِ تنظیماتِ عملیاتی (جدول: settings_fields.py) ==================
    #
    # هر مسیرِ نوشتن یک قاعده دارد: ``find_field`` (کلید از جدول، نه از callback) → ``_can(role,
    # field.permission)`` → ``validate`` → نوشتن → ``save`` → ممیزی → قلابِ تغییر. اگر یکی از
    # این‌ها نشود، آلارمِ فارسی می‌آید و **هیچ مقداری عوض نمی‌شود**.

    def _settings(self):
        return self._get_settings()

    def _alert(self, text: str) -> FlowResult:
        return FlowResult(answer=text, alert=True)

    def _actor(self, platform: str, chat_id: str) -> str:
        return self._console.actor_of(platform, chat_id)

    def _persist_settings(self) -> bool:
        """ذخیره روی دیسک: ``save_settings`` تزریق‌شده (BotManager) وگرنه خودِ ماژولِ تنظیمات."""
        settings = self._settings()
        if settings is None:
            return False
        try:
            if self._save_settings is not None:
                self._save_settings()
            else:
                settings_module.save_settings(settings)
        except Exception:  # noqa: BLE001 — پنل نباید به‌خاطرِ دیسک/رمزنگاری بشکنه
            logger.exception("ذخیره‌ی تنظیمات از پنلِ مدیریت ناموفق بود")
            return False
        return True

    def _field_of(self, key: str):
        """فیلدِ جدول با این کلید؛ ``(None, آلارم)`` اگر نبود یا تنظیمات در دسترس نیست."""
        settings = self._settings()
        if settings is None:
            return None, self._alert(_NO_SETTINGS)
        return sfields.find_field(settings, key), None

    # ------------------------------------------------------------- نمایشِ فهرست ----

    def _settings_menu_view(self, role: str, note: str = "") -> FlowResult:
        settings = self._settings()
        if settings is None:
            return self._edit(_NO_SETTINGS, [_back()])
        can_write = self._can(role, sfields.PERM_WRITE)
        lines = [
            "⚙️ کنترل‌پنلِ تنظیماتِ عملیاتی",
            f"نقشِ تو: {am.ROLE_LABEL_FA.get(role, role)} — " + ("دیدن و عوض‌کردن ✅" if can_write else "فقط دیدن 👁 (عوض‌کردن را مالک باید روشن کند)"),
        ]
        rows: list = []
        for gid, fa, _en in sfields.groups():
            fields = sfields.fields_for(settings, gid)
            if not fields and gid != "ship":
                continue
            lines.append("")
            lines.append(fa)
            if gid == "ship":
                lines.append("  " + sfields.shipping_summary(settings))
            for f in fields:
                lines.append(f"  • {f.label()}: {sfields.chip(f, sfields.read(settings, f))}")
            rows.append([Btn(fa[:32], f"{CB}sg:{gid}")])
        text = "\n".join(lines)
        if len(text) > _SETTINGS_LIMIT:
            text = text[:_SETTINGS_LIMIT] + "\n…"
        return self._edit((note + "\n\n" + text) if note else text, rows + [_back()])

    async def _settings_menu(self, role, platform, chat_id, args) -> FlowResult:
        return self._settings_menu_view(role)

    def _settings_group_view(self, role: str, gid: str, note: str = "") -> FlowResult:
        settings = self._settings()
        if settings is None:
            return self._edit(_NO_SETTINGS, [_back(data=CB + "set")])
        fields = sfields.fields_for(settings, gid)
        title = sfields.group_label(gid)
        lines = [title]
        if gid == "ship":
            lines.append(sfields.shipping_summary(settings))
        if not fields:
            lines.append("اینجا چیزی برای تنظیم نیست.")
        rows: list = []
        for f in fields:
            value = sfields.read(settings, f)
            lines.append(f"  • {f.label()}: {sfields.chip(f, value)}")
            rows.append([Btn(f"{f.label()[:28]} — {sfields.chip(f, value)[:18]}", f"{CB}sf:{f.key}")])
        rows.append(_back("◀️ تنظیمات", CB + "set"))
        text = "\n".join(lines)
        return self._edit((note + "\n\n" + text) if note else text, rows)

    async def _settings_group(self, role, platform, chat_id, args) -> FlowResult:
        gid = args[0]
        if gid not in sfields.GROUP_IDS:
            return self._alert("این بخشِ تنظیمات شناخته‌شده نیست.")
        return self._settings_group_view(role, gid)

    def _field_view(self, role: str, f, note: str = "", mode_note: str = "") -> FlowResult:
        """کارتِ یک تنظیم: مقدارِ فعلی + کنترل‌هایِ مناسبِ نوعش (دکمه، نه دستور)."""
        settings = self._settings()
        value = sfields.read(settings, f)
        can_write = self._can(role, f.permission)
        lines = [f"🔧 {f.label()}", f"مقدارِ فعلی: {sfields.chip(f, value)}"]
        if note:
            lines.append(note)
        if mode_note:
            lines.append(mode_note)
        bounds = f.bounds()
        if bounds:
            lines.append(bounds)
        if f.hint_fa:
            lines.append("ℹ️ " + f.hint_fa)
        if f.needs_restart:
            lines.append("♻️ این مقدار با راه‌اندازیِ دوباره‌ی ربات کامل اثر می‌کند.")
        if f.permission == sfields.PERM_GRANT:
            lines.append("🔐 فقط مالک: این تنظیم دسترسیِ نقشِ «مدیر» را عوض می‌کند.")
        if not can_write:
            lines.append("👁 نقشِ تو فقط دیدنِ این تنظیم را دارد.")
        rows: list = []
        if can_write:
            if f.kind == sfields.KIND_BOOL:
                rows.append([Btn("⛔ خاموش کن" if value else "✅ روشن کن", f"{CB}sb:{f.key}")])
            elif f.kind in (sfields.KIND_INT, sfields.KIND_FLOAT):
                rows.append([Btn(f"➕{s:g}", f"{CB}sn:{f.key}:{s}") for s in f.steps])
                rows.append([Btn(f"➖{s:g}", f"{CB}sn:{f.key}:{-s}") for s in f.steps])
            elif f.kind == sfields.KIND_CHOICE:
                rows.append([Btn(("✅ " if option == value else "") + label, f"{CB}so:{f.key}:{option}") for option, label in f.choices])
            if f.kind != sfields.KIND_BOOL:
                rows.append([Btn("✏️ تایپِ مقدار", f"{CB}se:{f.key}")])
        rows.append([Btn("◀️ " + sfields.group_label(f.group)[:26], f"{CB}sg:{f.group}")])
        rows.append(_back("◀️ تنظیمات", CB + "set"))
        return self._edit("\n".join(lines), rows)

    async def _setting_field(self, role, platform, chat_id, args) -> FlowResult:
        f, denied = self._field_of(args[0])
        if denied is not None:
            return denied
        if f is None:
            return self._alert("این تنظیم در فهرستِ تنظیماتِ پنل نیست.")
        self._entry_target.pop((platform, chat_id), None)
        self._entry_pending.pop((platform, chat_id), None)
        return self._field_view(role, f)

    # ------------------------------------------------------------------ نوشتن ----

    def _commit(self, role, platform, chat_id, f, candidate) -> FlowResult:
        """سنجشِ نهایی ⇒ اعمال ⇒ ذخیره ⇒ ممیزی ⇒ قلابِ تغییر (همه‌ی مسیرهایِ نوشتن از اینجا رد می‌شن)."""
        settings = self._settings()
        if not self._can(role, f.permission):
            return self._alert(_NO_WRITE)
        try:
            value = sfields.apply(settings, f, candidate)
        except sfields.FieldError as exc:
            return self._alert("⛔ " + str(exc))
        except Exception:  # noqa: BLE001 — دادهٔ غیرمنتظرهٔ دیسک/فیلد مشتق
            logger.exception("اعمالِ تنظیمِ %s ناموفق بود", f.key)
            return self._alert("⛔ این تنظیم عوض نشد؛ بعداً دوباره امتحان کن.")
        if not self._persist_settings():
            return self._alert("⛔ مقدار عوض شد ولی روی دیسک ذخیره نشد؛ از برنامه‌ی دسکتاپ استفاده کن.")
        self._admins.audit("settings_changed", actor=self._actor(platform, chat_id), detail=sfields.audit_detail(f, value))
        restarted = sfields.after_change(f, settings)
        fresh = sfields.read(settings, f)
        note = f"✅ {f.label()} شد: {sfields.chip(f, fresh)}" + (" — ربات هم راه‌اندازیِ دوباره شد." if restarted else "")
        return self._field_view(role, f, note=note)

    async def _setting_toggle(self, role, platform, chat_id, args) -> FlowResult:
        f, denied = self._field_of(args[0])
        if denied is not None:
            return denied
        if f is None:
            return self._alert("این تنظیم در فهرستِ تنظیماتِ پنل نیست.")
        if f.kind != sfields.KIND_BOOL:
            return self._alert("این تنظیم دکمهٔ روشن/خاموش ندارد.")
        return self._commit(role, platform, chat_id, f, not bool(sfields.read(self._settings(), f)))

    async def _setting_step(self, role, platform, chat_id, args) -> FlowResult:
        f, denied = self._field_of(args[0])
        if denied is not None:
            return denied
        if f is None:
            return self._alert("این تنظیم در فهرستِ تنظیماتِ پنل نیست.")
        settings = self._settings()
        try:
            # گام باید یکی از گام‌هایِ خودِ فیلد باشد (دکمهٔ جعلیِ ‎+9999 رد می‌شه) و مقدارِ بعدی
            # از *تنظیماتِ سرور* حساب می‌شه، نه از مقدارِ ارسالیِ callback.
            candidate = sfields.next_value(settings, f, sfields.parse_step(f, args[1]))
        except sfields.FieldError as exc:
            return self._alert("⛔ " + str(exc))
        return self._commit(role, platform, chat_id, f, candidate)

    async def _setting_choice(self, role, platform, chat_id, args) -> FlowResult:
        f, denied = self._field_of(args[0])
        if denied is not None:
            return denied
        if f is None or f.kind != sfields.KIND_CHOICE:
            return self._alert("این تنظیم گزینه‌هایِ فهرست‌شده ندارد.")
        return self._commit(role, platform, chat_id, f, args[1])

    async def _setting_entry(self, role, platform, chat_id, args) -> FlowResult:
        """✏️ «تایپِ مقدار»: همان ماشینِ حالتِ پاسخِ ۲۲ — بعد از این دکمه، یک پیامِ متنیِ ساده
        (بدونِ /) مقدارِ تازه است؛ نه دستوری و نه فرمتِ خاص."""
        f, denied = self._field_of(args[0])
        if denied is not None:
            return denied
        if f is None:
            return self._alert("این تنظیم در فهرستِ تنظیماتِ پنل نیست.")
        if not self._can(role, f.permission):
            return self._alert(_NO_WRITE)
        self._reply_target.pop((platform, chat_id), None)
        self._entry_pending.pop((platform, chat_id), None)
        self._entry_target[(platform, chat_id)] = f.key
        return self._field_view(role, f, mode_note="✏️ حالتِ تایپ روشن شد: فقط مقدار را بنویس (مثلاً " + self._sample(f) + ")؛ بدونِ / و بدونِ نامِ تنظیم.")

    @staticmethod
    def _sample(f) -> str:
        if f.kind == sfields.KIND_TEXT:
            return "۰۲۱۸۸۰۰۰۰۰۰" if f.pattern else "متنِ دلخواه"
        if f.kind == sfields.KIND_FLOAT:
            return "12.5"
        if f.kind == sfields.KIND_CHOICE and f.choices:
            return str(f.choices[0][0])
        return str(int(f.minimum or 0) + 5)

    async def _setting_typed(self, message, key: str, typed: str) -> Optional[FlowResult]:
        """متنِ آزادِ مدیر در حالتِ تایپِ مقدار → سنجشِ کامل → «منتظرِ ذخیره» (یک بار تأییدِ دکمه‌ای)."""
        platform, chat_id = message.platform, str(message.chat_id)
        where = (platform, chat_id)
        if not typed or typed.startswith("/"):
            return None  # دارد دستورِ دیگری می‌دهد؛ حالتِ تایپ دست‌نخورده می‌ماند
        role = self._admins.role_of(platform, chat_id)
        settings = self._settings()
        f = sfields.find_field(settings, key) if (role and settings is not None) else None
        if f is None:
            self._entry_target.pop(where, None)
            return FlowResult(messages=[UiMessage(_NO_SETTINGS if settings is None else "⚙️ آن تنظیم دیگر در فهرست نیست؛ از «تنظیماتِ عملیاتی» دوباره شروع کن.")])
        if not self._can(role, f.permission):
            self._entry_target.pop(where, None)
            return FlowResult(messages=[UiMessage(_NO_WRITE)])
        try:
            staged = sfields.validate(settings, f, typed)
        except sfields.FieldError as exc:
            # حالتِ تایپ **روشن می‌ماند** تا همان‌جا دوباره بنویسد (کرانه‌ها در کارتِ پایین آمده).
            return FlowResult(
                messages=[UiMessage(
                    f"🔧 {f.label()}\n⛔ {exc}\n"
                    f"مقدارِ فعلی دست‌نخورده ماند: {sfields.chip(f, sfields.read(settings, f))}\n"
                    f"{f.bounds()}\nهمین‌جا دوباره فقط مقدار را بنویس.",
                    [[Btn("انصراف", CB + "ssc"), Btn("✏️ تایپِ مقدار", f"{CB}se:{f.key}")]],
                )]
            )
        self._entry_target.pop(where, None)
        self._entry_pending[where] = (f.key, staged)
        return FlowResult(
            messages=[UiMessage(
                f"🔧 {f.label()}\nمقدارِ فعلی: {sfields.chip(f, sfields.read(settings, f))}\n"
                f"مقدارِ تازه: {sfields.chip(f, staged)}\n\nذخیره بشه؟",
                [[Btn("✅ بله، ذخیره کن", CB + "ssv"), Btn("انصراف", CB + "ssc")]],
            )]
        )

    async def _setting_save(self, role, platform, chat_id, args) -> FlowResult:
        """``ssv`` — مقدارِ تایپ‌شدهٔ *سنجیده‌شده* را می‌نویسد (دوباره سنجیده می‌شه، چون ممکن است
        تنظیمِ دیگری در همین فاصله عوض شده باشد و قاعدهٔ مشترکشان دیگر نخواند)."""
        where = (platform, chat_id)
        pending = self._entry_pending.pop(where, None)
        if pending is None:
            return self._alert("چیزی برای ذخیره نمانده؛ «تایپِ مقدار» را بزن و مقدار را بنویس.")
        key, staged = pending
        f, denied = self._field_of(key)
        if denied is not None:
            return denied
        if f is None:
            return self._alert("آن تنظیم دیگر در فهرستِ تنظیماتِ پنل نیست.")
        if not self._can(role, f.permission):
            return self._alert(_NO_WRITE)
        try:
            staged = sfields.validate(self._settings(), f, staged)
        except sfields.FieldError as exc:
            return self._alert("⛔ " + str(exc))
        return self._commit(role, platform, chat_id, f, staged)

    async def _setting_cancel(self, role, platform, chat_id, args) -> FlowResult:
        where = (platform, chat_id)
        self._entry_pending.pop(where, None)
        self._entry_target.pop(where, None)
        return self._settings_menu_view(role, note="↩️ انصراف؛ هیچ مقداری عوض نشد.")
