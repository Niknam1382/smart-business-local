"""
کنسولِ مالک داخلِ پیام‌رسان: صاحب فروشگاه بدون باز کردنِ برنامه از همون تلگرام/بله‌ی خودش
سفارش‌ها رو می‌بینه و تایید/رد می‌کنه.

چرا لازمه: کارت‌به‌کارت (رایج‌ترین روش) همیشه تایید دستی می‌خواد؛ اگه مالک از «پرداخت شد» خبردار
نشه، مشتری ساعت‌ها منتظر می‌مونه تا مالک اتفاقی اپ رو باز کنه. پس:

- **ثبتِ مالک با کدِ یک‌بارمصرف:** از اپ «ساخت کد اتصال» رو می‌زنی، از چتِ شخصیت ``/owner <کد>``
  رو به ربات می‌فرستی. کد ۱۰ دقیقه اعتبار داره و یک‌بار مصرفه؛ حدسِ کد برای غریبه عملاً ناممکنه
  (۵۰ بیت + سقفِ پیام در دقیقه). پیامِ ``/owner`` با کدِ نامعتبر از چتِ غریبه *بی‌صدا* مثلِ
  پیامِ عادی به AI می‌ره — وجودِ قابلیت لو نمی‌ره.
- **فرمان‌ها فقط از چتِ ثبت‌شده‌ی مالک** و فقط وقتی کاملاً شکلِ فرمان داشته باشن (``/confirm 12``،
  ``تایید 12`` ...). هر متنِ دیگه‌ای از چتِ مالک به AI می‌ره (برای تستِ ربات با حسابِ خودش).
- **اعلان‌ها:** پرداختِ منتظرِ تایید، فروشِ تایید‌شده‌ی خودکار (مشخصاتِ تحویل)، پرداختِ دیررس،
  و درخواستِ «نیاز به پیگیری» از طرفِ AI.
"""

from __future__ import annotations

import logging
import re
import secrets
import time
from typing import Awaitable, Callable, Optional

from app.core import admins as admins_mod
from app.core import checkout_fields as cf
from app.core.orders import (
    METHOD_BALE_PAY,
    METHOD_CARD_TO_CARD,
    METHOD_ZARINPAL,
    STATUS_CONFIRMED,
    STATUS_PAID,
    STATUS_PENDING_PAYMENT,
    Order,
    OrderError,
    build_order_confirmed_text,
    build_order_rejected_text,
)

logger = logging.getLogger(__name__)

LINK_CODE_TTL_SECONDS = 600
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # بدون حروفِ گیج‌کننده (O/0، I/1)
_CODE_LENGTH = 10
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

_ALIASES = {
    "help": {"help", "راهنما", "کمک", "owner"},
    "orders": {"orders", "سفارش‌ها", "سفارشها", "سفارش_ها"},
    "order": {"order", "سفارش"},
    "confirm": {"confirm", "تایید", "تأیید"},
    "reject": {"reject", "رد"},
    "stock": {"stock", "موجودی"},
    "unlink": {"unlink", "قطع"},
}
_NEEDS_ID = {"order", "confirm", "reject"}

METHOD_FA = {METHOD_CARD_TO_CARD: "کارت‌به‌کارت", METHOD_BALE_PAY: "بله‌پی", METHOD_ZARINPAL: "زرین‌پال"}

_COMMAND_CAPS = {
    "orders": admins_mod.CAP_ORDERS_VIEW,
    "order": admins_mod.CAP_ORDERS_VIEW,
    "confirm": admins_mod.CAP_ORDERS_DECIDE,
    "reject": admins_mod.CAP_ORDERS_DECIDE,
    "stock": admins_mod.CAP_STOCK_VIEW,
    "unlink": admins_mod.CAP_OWNER_UNLINK,
}

_HELP_LINES = [
    (admins_mod.CAP_ORDERS_VIEW, "/orders — سفارش‌های منتظر تایید"),
    (admins_mod.CAP_ORDERS_VIEW, "/order 12 — جزئیات سفارش"),
    (admins_mod.CAP_ORDERS_DECIDE, "/confirm 12 — تایید (موجودی کم می‌شه + فاکتور برای مشتری)"),
    (admins_mod.CAP_ORDERS_DECIDE, "/reject 12 — رد (به مشتری اطلاع داده می‌شه)"),
    (admins_mod.CAP_STOCK_VIEW, "/stock — کالاهای کم‌موجود/تمام‌شده"),
    (admins_mod.CAP_OWNER_UNLINK, "/unlink — قطعِ این چت از کنسول مالک"),
    (admins_mod.CAP_PANEL, "/admin — پنلِ دکمه‌ای (سفارش‌ها، موجودی، آمار، پشتیبانی)"),
    (admins_mod.CAP_PANEL, "/id — شناسه‌ی عددیِ این چت"),
]

HELP_TEXT = "🛠 کنسول مالک\n" + "\n".join(line for _cap, line in _HELP_LINES) + "\nفارسی هم می‌شه: «تایید 12»، «رد 12»، «سفارش‌ها»، «موجودی»."


def help_text(role: str) -> str:
    """راهنمای مخصوصِ نقش؛ مالک = ``HELP_TEXT`` کامل."""
    if role == admins_mod.ROLE_OWNER or not role:
        return HELP_TEXT
    lines = [line for cap, line in _HELP_LINES if admins_mod.can(role, cap)]
    return f"🛠 پنلِ {admins_mod.ROLE_LABEL_FA.get(role, role)}\n" + "\n".join(lines)


def _money(irr: int) -> str:
    return f"{irr:,} ریال"


_label_provider: Optional[Callable[[], dict]] = None


def set_label_provider(provider: Optional[Callable[[], dict]]) -> None:
    """``provider()`` → ``{شناسه‌ی فیلد: برچسب}`` (فیلدهای چک‌اوتِ فعلیِ صاحب فروشگاه)؛ BotManager وصلش می‌کنه."""
    global _label_provider
    _label_provider = provider


def extra_info_lines(order: Order) -> list:
    """فیلدهای چک‌اوتی که در ستون‌های قدیمیِ سفارش (نام/موبایل/آدرس/توضیح) نیستن — مثلِ کدپستی، شهر، ایمیل، درخواست."""
    try:
        labels = _label_provider() if _label_provider is not None else {}
    except Exception:  # noqa: BLE001
        labels = {}
    labels = {**{f.id: f.label for f in cf.default_fields("fa")}, **labels}
    legacy_ids = {"name", "address", "notes"}  # این‌ها در ستون‌های قدیمیِ سفارش (و خطوطِ بالا) نمایش داده می‌شن
    return [
        f"{labels.get(key, key)}: {value}"
        for key, value in order.customer_info.items()
        if value and key not in legacy_ids and value != order.customer_phone
    ]


def order_details(order: Order) -> str:
    items = "، ".join(f"{i.product_name}×{i.quantity}" for i in order.items)
    lines = [f"#{order.id} — {items}", f"مبلغ: {_money(order.total_irr)}"]
    if order.discount_irr > 0:
        lines.append(f"تخفیف: {_money(order.discount_irr)}" + (f" (کد {order.discount_code})" if order.discount_code else ""))
    if order.payment_method:
        lines.append(f"روش: {METHOD_FA.get(order.payment_method, order.payment_method)}")
    if order.payment_reference:
        lines.append(f"پیگیری: {order.payment_reference}")
    who = " · ".join(x for x in (order.customer_name, order.customer_phone) if x)
    if who:
        lines.append(f"مشتری: {who}")
    if order.customer_address:
        lines.append(f"آدرس: {order.customer_address}")
    if order.note:
        lines.append(f"توضیح: {order.note}")
    lines.extend(extra_info_lines(order))
    lines.append(f"پیام‌رسان: {order.platform}")
    return "\n".join(lines)


def order_alert_text(order: Order, kind: str) -> str:
    """kind: ``needs_confirm`` (پرداخت شد، منتظر تاییدِ مالک)، ``sale`` (تایید خودکار شد)."""
    if kind == "sale":
        head = f"🛒 فروش جدید — سفارش #{order.id} تایید خودکار شد؛ آماده‌ی ارسال کن."
        tail = ""
    else:
        head = f"💰 پرداختِ سفارش #{order.id} ثبت شد و منتظر تاییدته."
        tail = f"\n\nتایید: /confirm {order.id}\nرد: /reject {order.id}"
        if order.payment_method == METHOD_CARD_TO_CARD:
            tail = "\n⚠️ کارت‌به‌کارت است؛ قبل از تایید، واریز رو توی حسابت چک کن." + tail
    late = "\n⚠️ پرداخت بعد از پایان مهلت رزرو رسیده؛ موجودی رو چک کن." if order.paid_late else ""
    return f"{head}{late}\n\n{order_details(order)}{tail}"


class OwnerConsole:
    def __init__(
        self,
        get_settings: Callable[[], object],
        order_store,
        product_store,
        deliver: Callable[[str, str, str, bool], Awaitable[bool]],
        save_settings: Callable[[], None],
        after_confirm: Optional[Callable] = None,
        handoff=None,
        admins=None,  # Optional[AdminStore] — N11: مدیرانِ غیرمالک با نقش
    ):
        """``deliver(platform, chat_id, text, log_history) -> bool`` — ارسال از طریق آداپتورِ زنده.
        ``after_confirm(order)`` (اختیاری، async): بعد از تأییدِ موفق صدا زده می‌شه — تحویلِ محصولِ دیجیتال."""
        self._get_settings = get_settings
        self._orders = order_store
        self._products = product_store
        self._deliver = deliver
        self._save = save_settings
        self._after_confirm = after_confirm
        self._handoff = handoff
        self._admins = admins
        self._code = ""
        self._code_expires = 0.0

    # ------------------------------------------------------------- ثبتِ مالک
    def new_link_code(self) -> str:
        self._code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
        self._code_expires = time.time() + LINK_CODE_TTL_SECONDS
        return self._code

    def _consume_code(self, candidate: str) -> bool:
        ok = bool(self._code) and time.time() < self._code_expires and secrets.compare_digest(candidate.upper(), self._code)
        if ok:
            self._code, self._code_expires = "", 0.0  # یک‌بارمصرف
        return ok

    def owner_chats(self) -> dict:
        chats = getattr(self._get_settings(), "owner_chats", None)
        return dict(chats) if isinstance(chats, dict) else {}

    def is_owner(self, platform: str, chat_id: str) -> bool:
        return self.owner_chats().get(platform) == str(chat_id)

    def role_of(self, platform: str, chat_id: str) -> str:
        """``owner`` برای چتِ ثبت‌شده‌ی مالک؛ وگرنه نقشِ مدیرِ فعال؛ وگرنه ``""`` (کسی که ادمین نیست)."""
        if self.is_owner(platform, chat_id):
            return admins_mod.ROLE_OWNER
        return self._admins.role_of(platform, str(chat_id)) if self._admins is not None else ""

    def actor_of(self, platform: str, chat_id: str) -> str:
        return f"{self.role_of(platform, chat_id) or 'unknown'}:{platform}:{chat_id}"

    def _audit(self, action: str, actor: str, detail: str) -> None:
        if self._admins is not None:
            try:
                self._admins.audit(action, actor=actor, detail=detail)
            except Exception:  # noqa: BLE001 — ممیزی هرگز تصمیمِ سفارش را خراب نمی‌کنه
                logger.debug("ثبتِ ممیزی ناموفق بود", exc_info=True)

    def unlink(self, platform: str) -> bool:
        settings = self._get_settings()
        chats = self.owner_chats()
        if platform not in chats:
            return False
        chats.pop(platform)
        settings.owner_chats = chats
        self._save()
        return True

    # ----------------------------------------------------------- پیام‌های ورودی
    async def handle(self, platform: str, chat_id: str, text: str, send, reply_to: str = "") -> bool:
        """True = پیام مالِ کنسول بود و پردازش شد (به AI نرو)؛ False = پیامِ عادیه."""
        stripped = (text or "").strip()

        match = re.fullmatch(r"/owner(?:@\w+)?\s+([A-Za-z0-9]{6,20})", stripped)
        if match and not self.is_owner(platform, chat_id):
            if not self._consume_code(match.group(1)):
                return False  # بی‌صدا: غریبه نباید بفهمه چنین قابلیتی هست
            settings = self._get_settings()
            chats = self.owner_chats()
            chats[platform] = str(chat_id)
            settings.owner_chats = chats
            self._save()
            await send("✅ این چت به‌عنوان «مالک فروشگاه» ثبت شد. از این به بعد اعلان سفارش‌ها اینجا میاد.\n\n" + HELP_TEXT)
            return True

        role = self.role_of(platform, chat_id)
        if not role:
            return False
        if self._handoff is not None and await self._handle_handoff(platform, chat_id, stripped, send, reply_to, role):
            return True
        parsed = self._parse(stripped)
        if parsed is None:
            return False
        command, arg, slashed = parsed
        needed = _COMMAND_CAPS.get(command)
        if needed is not None and not admins_mod.can(role, needed):
            if not slashed:
                return False  # کلمه‌ی عادی از مدیرِ محدود = گفتگوی عادی (بلعیده نمی‌شه)
            await send(f"⛔ نقشِ «{admins_mod.ROLE_LABEL_FA.get(role, role)}» به این دستور دسترسی نداره.")
            return True
        if command in _NEEDS_ID and arg is None:
            if not slashed:
                return False  # «رد شدم»، «سفارش دادم» ... = گفتگوی عادی
            await send("شماره‌ی سفارش رو هم بنویس؛ مثلاً /confirm 12")
            return True
        await send(await self._run(command, arg, platform, role=role, actor=self.actor_of(platform, chat_id)))
        return True

    @staticmethod
    def _parse(text: str):
        tokens = text.split()
        if not tokens or len(tokens) > 2:
            return None
        slashed = tokens[0].startswith("/")
        word = re.sub(r"@\w+$", "", tokens[0].lstrip("/")).lower()
        command = next((c for c, names in _ALIASES.items() if word in names), None)
        if command is None:
            return None
        arg = None
        if len(tokens) == 2:
            raw = tokens[1].lstrip("#").translate(_DIGITS)
            if not raw.isdigit():
                return None if not slashed else (command, -1, slashed)
            arg = int(raw)
        if command not in _NEEDS_ID and arg is not None:
            return None
        return command, arg, slashed

    async def _run(self, command: str, arg: Optional[int], platform: str, role: str = admins_mod.ROLE_OWNER, actor: str = "") -> str:
        if arg == -1:
            return "شماره‌ی سفارش باید عدد باشه؛ مثلاً /confirm 12"
        if command == "help":
            return help_text(role)
        if command == "unlink":
            self.unlink(platform)
            return "قطع شد؛ این چت دیگه اعلان نمی‌گیره. (دوباره از اپ کد بگیر تا وصل بشه.)"
        if command == "orders":
            return self._orders_text()
        if command == "stock":
            return self._stock_text()
        order = self._orders.get(arg)
        if order is None:
            return f"سفارش #{arg} پیدا نشد."
        if command == "order":
            return order_details(order) + f"\nوضعیت: {order.status}" + ("\n⚠️ پرداخت دیررس" if order.paid_late else "")
        if command == "confirm":
            return await self._confirm(order, actor)
        return await self._reject(order, actor)

    async def decide(self, command: str, order_id: int, actor: str) -> str:
        """تأیید/ردِ یک سفارش از هر مسیر (کنسولِ متنی یا دکمه‌ی پنل). **کنترلِ نقش با تماس‌گیرنده است** (``can(role, orders.decide)``)."""
        order = self._orders.get(order_id)
        if order is None:
            return f"سفارش #{order_id} پیدا نشد."
        return await (self._confirm(order, actor) if command == "confirm" else self._reject(order, actor))

    async def _handle_handoff(self, platform: str, chat_id: str, text: str, send, reply_to: str, role: str = admins_mod.ROLE_OWNER) -> bool:
        """/reply <ref> متن · /close <ref> · /handoffs · و Reply روی پیامِ فورواردشده‌ی مشتری."""
        from app.core.handoff import parse_ref

        deny = "⛔ نقشِ «%s» به پشتیبانی دسترسی نداره." % admins_mod.ROLE_LABEL_FA.get(role, role)
        match = re.fullmatch(r"/reply(?:@\w+)?\s+(\S+)\s+(.+)", text, re.S)
        if match:
            if not admins_mod.can(role, admins_mod.CAP_SUPPORT_REPLY):
                await send(deny)
                return True
            target = parse_ref(match.group(1))
            await send("❌ شناسه‌ی گفتگو نامعتبره؛ مثلاً /reply t123456 سلام" if target is None else await self._handoff.owner_reply(*target, match.group(2)))
            return True
        match = re.fullmatch(r"/close(?:@\w+)?\s+(\S+)", text)
        if match:
            if not admins_mod.can(role, admins_mod.CAP_SUPPORT_REPLY):
                await send(deny)
                return True
            target = parse_ref(match.group(1))
            await send("❌ شناسه‌ی گفتگو نامعتبره." if target is None else await self._handoff.owner_close(*target))
            return True
        if re.fullmatch(r"/handoffs?(?:@\w+)?", text):
            await send(self._handoff.owner_list() if admins_mod.can(role, admins_mod.CAP_SUPPORT_VIEW) else deny)
            return True
        if reply_to and text and not text.startswith("/") and admins_mod.can(role, admins_mod.CAP_SUPPORT_REPLY):
            target = self._handoff.lookup(platform, chat_id, reply_to)
            if target is not None:
                await send(await self._handoff.owner_reply(*target, text))
                return True
        return False

    async def _confirm(self, order: Order, actor: str = "") -> str:
        try:
            self._orders.confirm(order.id)
        except OrderError as exc:
            return f"❌ تایید نشد: {exc}"
        self._orders.set_confirmed_by(order.id, actor or "owner")  # N11: چه کسی تأیید کرد
        self._audit("order_confirmed", actor or "owner", f"#{order.id}")
        fresh = self._orders.get(order.id)
        delivered = await self._deliver(fresh.platform, fresh.chat_id, build_order_confirmed_text(fresh), True)
        tail = "فاکتور برای مشتری ارسال شد." if delivered else "⚠️ پیام برای مشتری نرفت؛ خودت خبرش کن."
        if self._after_confirm is not None:
            try:
                await self._after_confirm(fresh)
            except Exception:  # noqa: BLE001 — خطای تحویل نباید تاییدِ انجام‌شده رو خراب کنه
                logger.exception("تحویلِ دیجیتالِ سفارش %s", fresh.id)
        return f"✅ سفارش #{fresh.id} تایید شد و موجودی کم شد. {tail}\n\n{order_details(fresh)}"

    async def _reject(self, order: Order, actor: str = "") -> str:
        try:
            self._orders.reject(order.id)
        except OrderError as exc:
            return f"❌ رد نشد: {exc}"
        self._audit("order_rejected", actor or "owner", f"#{order.id}")
        fresh = self._orders.get(order.id)
        delivered = await self._deliver(fresh.platform, fresh.chat_id, build_order_rejected_text(fresh), True)
        tail = "به مشتری اطلاع داده شد." if delivered else "⚠️ پیام برای مشتری نرفت؛ خودت خبرش کن (و مبلغ رو برگردون)."
        return f"🚫 سفارش #{fresh.id} رد شد. {tail}"

    def _orders_text(self) -> str:
        waiting = [o for o in self._orders.list() if o.status == STATUS_PAID]
        pending = sum(1 for o in self._orders.list() if o.status == STATUS_PENDING_PAYMENT and o.seconds_left() > 0)
        if not waiting:
            return f"سفارشِ منتظر تایید نداری. ✅\n(در انتظار پرداختِ مشتری: {pending})"
        lines = [f"📋 منتظر تایید: {len(waiting)} (در انتظار پرداخت: {pending})"]
        for order in waiting[:10]:
            lines.append("• " + order_details(order).replace("\n", " | ") + ("  ⚠️دیررس" if order.paid_late else ""))
        lines.append("\nتایید: /confirm <شماره>   رد: /reject <شماره>")
        return "\n".join(lines)

    def _stock_text(self) -> str:
        rows = []
        for p in self._products.list():
            available = self._orders.available_quantity(p.id)
            if available < 3:
                rows.append(f"• {p.name}: " + ("تمام شده" if available == 0 else f"{available} عدد"))
        return "📦 کم‌موجود/تمام‌شده:\n" + "\n".join(rows) if rows else "همه‌ی کالاها موجودیِ کافی دارن. ✅"

    # ------------------------------------------------------------------ اعلان‌ها
    async def notify(self, text: str, to_managers: bool = False) -> bool:
        """به همه‌ی چت‌های ثبت‌شده‌ی مالک پیام می‌ده؛ True اگه حداقل به یکی رسید. ``to_managers``: مدیرانِ فعالِ دارای
        قابلیتِ «تأیید/ردِ سفارش» هم خبردار می‌شن (فقط اعلانِ سفارش؛ هشدارهای فنی/سقفِ AI فقط برای مالک)."""
        delivered = False
        targets = list(self.owner_chats().items())
        if to_managers and self._admins is not None:
            targets += [(a.platform, a.user_id) for a in self._admins.active_with(admins_mod.CAP_ORDERS_DECIDE)]
        for platform, chat_id in targets:
            try:
                if await self._deliver(platform, chat_id, text, False):
                    delivered = True
            except Exception:  # noqa: BLE001
                logger.exception("اعلان به مالک/مدیر (%s) ناموفق بود", platform)
        return delivered

    async def alert_order(self, order: Order) -> bool:
        """بعد از هر پرداختِ آنلاین: فروشِ تایید‌شده → «آماده‌ی ارسال»؛ پرداخت‌شده → «منتظر تاییدته»."""
        if order.status == STATUS_CONFIRMED:
            return await self.notify(order_alert_text(order, "sale"), to_managers=True)
        if order.status == STATUS_PAID:
            return await self.notify(order_alert_text(order, "needs_confirm"), to_managers=True)
        return False
