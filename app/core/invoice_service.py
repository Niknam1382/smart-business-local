"""
سرویسِ فاکتور (N19): صدور + PDF + ارسالِ خودکار/دستی به مشتری و مالک.

- **idempotent:** وضعیتِ ارسال در ``invoices.sent_json``؛ فاکتورِ ارسال‌شده بدونِ ``force`` دوباره نمی‌رود (قفلِ هر فاکتور
  جلوی ارسالِ هم‌زمانِ دوبار را می‌گیره).
- **retry با backoff** (۳ تلاشِ فوری با فاصله‌ی افزایشی) برای خطای گذرا؛ بلاک‌شده/دسترس‌ناپذیر/لغوکرده = بدونِ تلاش.
- **شکست ⇒** «نیاز به توجه» + فاکتورِ متنی به‌عنوانِ جایگزین (یک‌بار) + دکمه‌ی «ارسالِ دوباره» در صفحه‌ی مالی؛
  حلقه‌ی نگهداری با فاصله‌ی افزایشی تا ۵ تلاش دوباره می‌سنجد.
- PDFها مشتق‌اند (از snapshot، قطعی)؛ فقط کش‌اند و با ``/forget`` پاک می‌شن؛ هر زمان دوباره ساخته می‌شن.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional

from app.core import invoice_pdf, jalali
from app.core.invoices import Invoice, InvoiceError, InvoiceStore

logger = logging.getLogger(__name__)

MAX_AUTO_ATTEMPTS = 5
RETRY_DELAYS = (1.0, 4.0)  # بین تلاش‌های فوری (ثانیه)
CUSTOMER_COOLDOWN_SECONDS = 20  # «🧾 فاکتور»ِ مشتری: سقفِ تکرار
NEXT_TRY_BASE_SECONDS = 120


def invoices_dir() -> Path:
    from app.core.paths import get_app_data_dir

    path = get_app_data_dir() / "invoices"
    path.mkdir(parents=True, exist_ok=True)
    return path


def invoice_text(inv: Invoice, digits: Optional[str] = None) -> str:
    """فاکتورِ متنیِ ساده (جایگزینِ PDF)."""
    d = digits or inv.seller.get("digits", "fa")
    m = lambda n: invoice_pdf.money(n, d)  # noqa: E731
    title = "فاکتور برگشتی" if inv.is_credit else "فاکتور فروش"
    lines = [f"🧾 {title} {inv.number}", jalali.format_ts(inv.issued_ts, digits=d), inv.seller.get("name", "")]
    for it in inv.lines:
        lines.append(f"- {it.get('name', '')} ×{it.get('qty', 0)} = {m(it.get('total_irr', 0))} ریال")
    lines.append(f"جمعِ اقلام: {m(inv.subtotal_irr)} ریال")
    if inv.discount_irr:
        lines.append(f"تخفیف: −{m(inv.discount_irr)} ریال")
    if inv.shipping_irr:
        lines.append(f"ارسال/سایر: {m(inv.shipping_irr)} ریال")
    if inv.tax_irr:
        lines.append(f"شاملِ مالیات بر ارزش افزوده: {m(inv.tax_irr)} ریال")
    lines.append(f"مبلغِ نهایی: {m(inv.total_irr)} ریال")
    return "\n".join(x for x in lines if x)


class InvoiceService:
    def __init__(
        self,
        order_store,
        get_settings: Callable[[], object],
        *,
        doc_sender: Optional[Callable[[str, str, str, str], Awaitable[None]]] = None,  # (platform, chat_id, path, caption)
        text_sender: Optional[Callable[[str, str, str], Awaitable[None]]] = None,  # (platform, chat_id, text)
        can_send: Optional[Callable[[str, str], str]] = None,  # (platform, chat_id) → "" یا دلیلِ ممنوعیت
        on_unreachable: Optional[Callable[[str, str, BaseException], None]] = None,
        attention_add: Optional[Callable[[str, str, str], None]] = None,
        attention_clear: Optional[Callable[[str, str], None]] = None,
        owner_chats: Optional[Callable[[], dict]] = None,
        directory: Optional[Callable[[], Path]] = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.time,
    ):
        self._orders = order_store
        self.store = InvoiceStore(order_store)
        self._settings = get_settings
        self._doc, self._text, self._can = doc_sender, text_sender, can_send
        self._on_unreachable, self._att_add, self._att_clear = on_unreachable, attention_add, attention_clear
        self._owner_chats = owner_chats or (lambda: {})
        self._dir = directory or invoices_dir
        self._sleep, self._clock = sleep, clock
        self._locks: dict = {}
        self._cooldown: dict = {}
        self.finance = None  # FinanceStore (اختیاری): فاکتورِ برگشتی ردیفِ «برگشتی» می‌سازه
        order_store.add_anonymize_listener(self.delete_files)

    # ----------------------------------------------------------- فایل/PDF
    def path_of(self, inv: Invoice) -> Path:
        return Path(self._dir()) / f"{inv.number}.pdf"

    def ensure_pdf(self, inv: Invoice) -> Path:
        """PDFِ ذخیره‌شده یا ساختِ دوباره از snapshot (قطعی). ``InvoicePdfError`` اگه ساخته نشه."""
        path = self.path_of(inv)
        if path.is_file() and path.stat().st_size > 0:
            return path
        ref = ""
        if inv.is_credit:
            base = self.store.get(inv.ref_invoice_id)
            ref = base.number if base else ""
        data = invoice_pdf.render(inv, ref_number=ref, order_label=f"سفارش #{inv.order_id}")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        if not inv.pdf_sha256:
            self.store.set_pdf_hash(inv.id, hashlib.sha256(data).hexdigest())
        return path

    def delete_files(self, numbers: list) -> None:
        for number in numbers:
            try:
                (Path(self._dir()) / f"{number}.pdf").unlink(missing_ok=True)
            except OSError:
                logger.warning("حذفِ PDFِ فاکتور ناموفق بود", exc_info=True)

    # ---------------------------------------------------------------- صدور
    def issue(self, order) -> Invoice:
        """فاکتورِ فروش (idempotent) + PDF؛ خطای PDF فاکتور را نمی‌اندازد (متنی fallback است)."""
        inv = self.store.issue_sale(order, self._settings(), now=int(self._clock()))
        try:
            self.ensure_pdf(inv)
        except Exception:  # noqa: BLE001
            logger.warning("PDFِ فاکتور %s ساخته نشد؛ فاکتورِ متنی fallback است", inv.number, exc_info=True)
        return inv

    def credit_note(self, sale_id: int, cogs_back: bool = False) -> Invoice:
        """فاکتورِ برگشتیِ کامل + ردیفِ «برگشتی» در دفتر (اگه دفتر وصل باشه)."""
        inv = self.store.issue_credit_note(sale_id, self._settings(), now=int(self._clock()))
        if self.finance is not None:
            self.finance.post_credit_note(inv, cogs_back=cogs_back, now=int(self._clock()))
        try:
            self.ensure_pdf(inv)
        except Exception:  # noqa: BLE001
            logger.warning("PDFِ فاکتورِ برگشتی ساخته نشد", exc_info=True)
        return inv

    # --------------------------------------------------------------- ارسال
    def _lock(self, invoice_id: int) -> asyncio.Lock:
        return self._locks.setdefault(invoice_id, asyncio.Lock())

    def _caption(self, inv: Invoice) -> str:
        from app.core import shop_texts

        return shop_texts.render(self._settings(), "inv.caption", None, number=inv.number, order_id=inv.order_id)

    async def _deliver(self, platform: str, chat_id: str, inv: Invoice) -> None:
        if self._doc is None:
            raise RuntimeError("ارسالِ فایل راه‌اندازی نشده.")
        path = self.ensure_pdf(inv)
        await self._doc(platform, chat_id, str(path), self._caption(inv))

    def _auto_wait(self, inv: Invoice) -> str:
        """دلیلِ صبر برای ارسالِ *خودکار* (سقفِ تلاش/backoff)؛ داخلِ قفل بررسی می‌شه تا دو حلقه‌ی هم‌زمان دوبار نکوبن."""
        cust = inv.sent.get("customer", {})
        attempts = int(cust.get("attempts", 0))
        if attempts >= MAX_AUTO_ATTEMPTS:
            return "attempt_cap"
        if attempts and self._clock() < cust.get("ts", 0) + NEXT_TRY_BASE_SECONDS * (2 ** (attempts - 1)):
            return "backoff"
        return ""

    async def send_customer(self, invoice_id: int, force: bool = False, auto: bool = False) -> str:
        """``sent`` | ``skipped:<دلیل>`` | ``failed:<شرح>``. بدونِ ``force`` هرگز دوبار نمی‌فرسته؛ ``auto`` سقف/backoff را اعمال می‌کنه."""
        async with self._lock(invoice_id):
            inv = self.store.get(invoice_id)
            if inv is None:
                return "skipped:missing"
            order = self._orders.get(inv.order_id)
            if order is None:
                return "skipped:no_order"
            if inv.anonymized:
                return "skipped:forgotten"
            if not force and inv.sent.get("customer", {}).get("ok"):
                return "skipped:already"
            if auto and not force and (wait := self._auto_wait(inv)):
                return f"skipped:{wait}"
            reason = self._can(order.platform, str(order.chat_id)) if self._can else ""
            if reason:
                return f"skipped:{reason}"
            return await self._attempt(inv, order.platform, str(order.chat_id), "customer")

    async def _attempt(self, inv: Invoice, platform: str, chat_id: str, target: str) -> str:
        last = ""
        for n in range(len(RETRY_DELAYS) + 1):
            try:
                await self._deliver(platform, chat_id, inv)
            except Exception as exc:  # noqa: BLE001
                from app.core.adapter_common import looks_unreachable

                last = f"{type(exc).__name__}: {exc}"[:160]
                if self._on_unreachable:
                    self._on_unreachable(platform, chat_id, exc)
                if looks_unreachable(exc) or n >= len(RETRY_DELAYS):
                    break
                await self._sleep(RETRY_DELAYS[n])
                continue
            self.store.record_send(inv.id, target, True, now=int(self._clock()))
            if target == "customer" and self._att_clear:
                self._att_clear("invoice_send", str(inv.id))
            return "sent"
        state = self.store.record_send(inv.id, target, False, last, now=int(self._clock()))
        if target == "customer":
            if self._att_add:
                self._att_add("invoice_send", str(inv.id), f"{inv.number}: {last}"[:200])
            if state["attempts"] == 1 and self._text is not None:  # جایگزینِ متنی فقط یک‌بار
                try:
                    await self._text(platform, chat_id, invoice_text(inv))
                except Exception:  # noqa: BLE001
                    logger.debug("فاکتورِ متنیِ جایگزین هم نرفت", exc_info=True)
        return f"failed:{last}"

    async def send_owner_copy(self, invoice_id: int) -> str:
        chats = dict(self._owner_chats() or {})
        if not chats:
            return "skipped:no_owner"
        async with self._lock(invoice_id):
            inv = self.store.get(invoice_id)
            if inv is None:
                return "skipped:missing"
            if inv.sent.get("owner", {}).get("ok"):
                return "skipped:already"
            result = "failed:no_owner_reachable"
            for platform, chat_id in chats.items():
                outcome = await self._attempt(inv, platform, str(chat_id), "owner")
                if outcome == "sent":
                    return "sent"
                result = outcome
            return result

    async def send_for_customer_button(self, platform: str, chat_id: str, order_id: int) -> str:
        """دکمه‌ی «🧾 فاکتور»ِ مشتری: فقط سفارشِ خودش؛ در صورتِ نبودنِ فاکتور صادر می‌شه؛ سقفِ تکرار."""
        order = self._orders.get(order_id)
        if order is None or order.platform != platform or str(order.chat_id) != str(chat_id) or order.status != "confirmed":
            return "unavailable"
        now = self._clock()
        key = (platform, str(chat_id), order_id)
        if now - self._cooldown.get(key, -1e9) < CUSTOMER_COOLDOWN_SECONDS:
            return "sent"  # دابل‌تپ: بی‌صدا (قبلاً رفته)
        self._cooldown[key] = now
        try:
            inv = await asyncio.to_thread(self.issue, order)
        except InvoiceError:
            return "unavailable"
        out = await self.send_customer(inv.id, force=True)
        return "sent" if out == "sent" else "failed"

    async def process_pending(self, limit: int = 20) -> int:
        """حلقه‌ی نگهداری: (۱) ثبتِ دفترِ جاافتاده‌ها در FinanceStore جداست؛ اینجا صدورِ فاکتورِ جاافتاده + ارسالِ خودکارِ عقب‌افتاده.
        فقط وقتی ``invoice_auto_send=after_confirm``. تعدادِ تلاشِ ارسال را برمی‌گردونه."""
        settings = self._settings()
        if getattr(settings, "invoice_auto_send", "off") != "after_confirm":
            return 0
        for oid in await asyncio.to_thread(self.store.sale_missing_for_confirmed, limit):
            order = self._orders.get(oid)
            if order is not None:
                try:
                    await asyncio.to_thread(self.issue, order)
                except Exception:  # noqa: BLE001
                    logger.warning("صدورِ فاکتورِ سفارش %s ناموفق بود", oid, exc_info=True)
        tried = 0
        now = self._clock()
        for inv in await asyncio.to_thread(self.store.list, "", "sale", 200):
            cust = inv.sent.get("customer", {})
            if cust.get("ok") or inv.anonymized:
                if getattr(settings, "invoice_send_owner_copy", False) and not inv.sent.get("owner", {}).get("ok") and not inv.sent.get("owner", {}).get("attempts", 0) >= MAX_AUTO_ATTEMPTS:
                    await self.send_owner_copy(inv.id)
                continue
            attempts = int(cust.get("attempts", 0))
            if attempts >= MAX_AUTO_ATTEMPTS:
                continue
            if attempts and now < cust.get("ts", 0) + NEXT_TRY_BASE_SECONDS * (2 ** (attempts - 1)):
                continue
            if tried >= limit:
                break
            tried += 1
            outcome = await self.send_customer(inv.id, auto=True)
            if outcome == "sent" and getattr(settings, "invoice_send_owner_copy", False):
                await self.send_owner_copy(inv.id)
        return tried
