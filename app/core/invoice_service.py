"""
سرویسِ فاکتور (N19): صدور + PDF + ارسالِ خودکار/دستی به مشتری و مالک + «فاکتورِ تستی» (قلم ۸).

- **idempotent:** وضعیتِ ارسال در ``invoices.sent_json``؛ فاکتورِ ارسال‌شده بدونِ ``force`` دوباره نمی‌رود (قفلِ هر فاکتور
  جلوی ارسالِ هم‌زمانِ دوبار را می‌گیره).
- **retry با backoff** (۳ تلاشِ فوری با فاصله‌ی افزایشی) برای خطای گذرا؛ بلاک‌شده/دسترس‌ناپذیر/لغوکرده = بدونِ تلاش.
- **شکست ⇒** «نیاز به توجه» + فاکتورِ متنی به‌عنوانِ جایگزین (یک‌بار) + دکمه‌ی «ارسالِ دوباره» در صفحه‌ی مالی؛
  حلقه‌ی نگهداری با فاصله‌ی افزایشی تا ۵ تلاش دوباره می‌سنجد.
- PDFها مشتق‌اند (از snapshot، قطعی)؛ فقط کش‌اند و با ``/forget`` پاک می‌شن؛ هر زمان دوباره ساخته می‌شن.
- **``preview()``:** فاکتورِ *نمونه* از تنظیماتِ جاری می‌سازد (هیچ سفارش/دیتابیس/شبکه‌ای در کار نیست) و همانِ
  مسیرِ رندرِ فاکتورِ واقعی را می‌رود، تا مالک بعد از شخصی‌سازیِ متن‌ها نتیجه را روی کاغذ ببیند. فایل در همان
  پوشه‌ی PDFها می‌نشیند و هر بار *بازنویسی* می‌شود (idempotent)؛ هیچ پیامی به مشتری نمی‌رود.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional

from app.core import invoice_pdf, jalali
from app.core.invoices import Invoice, InvoiceError, InvoiceStore, compute_totals, seller_snapshot

logger = logging.getLogger(__name__)

MAX_AUTO_ATTEMPTS = 5
RETRY_DELAYS = (1.0, 4.0)  # بین تلاش‌های فوری (ثانیه)
CUSTOMER_COOLDOWN_SECONDS = 20  # «🧾 فاکتور»ِ مشتری: سقفِ تکرار
NEXT_TRY_BASE_SECONDS = 120
MAX_TRACKED_ENTRIES = 2000  # سقفِ دیک‌هایِ حافظه (قفل/خاموشی): برنامه هفته‌ها روشن می‌ماند
_SAFE_NUMBER = re.compile(r"[^A-Za-z0-9._-]+")

# ---- فاکتورِ تستی (قلم ۸) ----
# «-» در شماره‌ی صادرشده هرگز تولید نمی‌شود (``_prefix`` فقط [A-Za-z0-9] می‌گذارد)، پس این شماره با
# هیچ فاکتورِ واقعی و هیچ ردیفی در دیتابیس قاطی نمی‌شود.
PREVIEW_NUMBER = "TEST-000001"
PREVIEW_ORDER_ID = 4287
PREVIEW_DISCOUNT_IRR = 50_000
PREVIEW_SHIPPING_IRR = 80_000
# مبالغِ نمونه «با مالیات»ند (همان قراردادِ ریاضیِ فاکتورِ واقعی) تا خطِ مالیات هم درست دیده شود.
PREVIEW_LINES = (
    {"name": "کفشِ روزمره (نمونه)", "qty": 1, "unit_irr": 850_000, "total_irr": 850_000},
    {"name": "جورابِ نخی (نمونه)", "qty": 3, "unit_irr": 90_000, "total_irr": 270_000},
    {"name": "کمربِ چرمی (نمونه)", "qty": 1, "unit_irr": 430_000, "total_irr": 430_000},
)
PREVIEW_BUYER = {
    # «نمونه» در نام و در شناسه هست تا اگر فاکتور گم شد، کسی آن را فاکتورِ واقعی نگیرد
    "name": "مشتریِ نمونه (فاکتورِ تستی)",
    "phone": "09120000000",
    "address": "تهران، خیابانِ نمونه، پلاک ۱۲ (آدرسِ آزمایشی)",
    "trace": "TR-000001",
    "tracking": "",
    "buyer_id": "sample-1",
    "shipping_method": "پست پیشتاز (نمونه)",
    "anonymized": False,
}


def safe_pdf_name(number: str) -> str:
    """شمارهٔ فاکتور *از دیسک هم می‌آید* (بازگردانیِ پشتیبانِ نسخه‌ی ۱)، پس نامِ فایل از آن
    مستقیم ساخته نمی‌شه: «../» یا هر جداکنندهٔ مسیر نمی‌تونه PDF را بیرونِ پوشه بنویسد/پاک کند."""
    clean = _SAFE_NUMBER.sub("", str(number or ""))[:64].strip(".")
    return f"{clean or 'invoice'}.pdf"


def invoices_dir() -> Path:
    from app.core.paths import get_app_data_dir

    path = get_app_data_dir() / "invoices"
    path.mkdir(parents=True, exist_ok=True)
    return path


def invoice_text(inv: Invoice, digits: Optional[str] = None) -> str:
    """فاکتورِ متنیِ ساده (جایگزینِ PDF) — همان ترتیب و همان معنایِ PDF: مالیات «از این مبلغ» است.

    متن‌هایِ شخصی‌سازی‌شده (برچسب‌ها/نامِ فروشگاه) اینجا هم اعمال می‌شن تا نسخه‌یِ متنی و PDFِ
    یکِ فاکتور یکی باشند."""
    d = digits or inv.seller.get("digits", "fa")
    lang = "en" if getattr(inv, "lang", "fa") == "en" else "fa"
    labels = inv.seller.get("labels") if isinstance(inv.seller.get("labels"), dict) else None
    rial = invoice_pdf.label("rial", lang)
    m = lambda n: f"{invoice_pdf.money(n, d)} {rial}"  # noqa: E731
    title = invoice_pdf.label("credit" if inv.is_credit else "sale", lang, labels)
    lines = [f"🧾 {title} {inv.number}", jalali.format_ts(inv.issued_ts, digits=d), invoice_pdf.seller_name(inv.seller)]
    for it in inv.lines:
        lines.append(f"- {it.get('name', '')} ×{it.get('qty', 0)} = {m(it.get('total_irr', 0))}")
    lines.append(f"{invoice_pdf.label('subtotal', lang, labels)}: {m(inv.subtotal_irr)}")
    if inv.discount_irr:
        lines.append(f"{invoice_pdf.label('discount', lang, labels)}: −{m(inv.discount_irr)}")
    if inv.shipping_irr:
        lines.append(f"{invoice_pdf.label('shipping', lang, labels)}: {m(inv.shipping_irr)}")
    lines.append(f"{invoice_pdf.label('refund' if inv.is_credit else 'final', lang, labels)}: {m(inv.total_irr)}")
    if inv.tax_irr:
        rate = (inv.seller.get("vat_rate_bp", 0) or 0) / 100
        lines.append(f"{invoice_pdf.label('vat', lang, labels)} {invoice_pdf._num(f'{rate:g}', d)}٪: {m(inv.tax_irr)}")
    thanks = invoice_pdf.clean(inv.seller.get("thanks", ""), 200)
    if thanks:
        lines.append(thanks)
    return "\n".join(x for x in lines if x)


def preview_invoice(settings, lang: Optional[str] = None, issued_ts: Optional[int] = None) -> Invoice:
    """``Invoice``ِ *ساختگیِ* فاکتورِ تستی — از تنظیماتِ جاری، بدونِ هیچ دیتابیسی.

    همان ``seller_snapshot`` و همان ``compute_totals``ِ فاکتورِ واقعی خوانده می‌شن (مالیات/ارسال طبقِ
    تنظیمات)، فقط اقلام و خریدار نمونه‌اند و ``seller["preview"]=True`` علامتِ «نمونه» است."""
    seller = dict(seller_snapshot(settings))
    seller["preview"] = True
    lines = [dict(item) for item in PREVIEW_LINES]
    total = sum(int(item["total_irr"]) for item in lines) - PREVIEW_DISCOUNT_IRR + PREVIEW_SHIPPING_IRR
    totals = compute_totals(lines, total, PREVIEW_DISCOUNT_IRR, seller["vat_enabled"], seller["vat_rate_bp"])
    lang = lang if lang in ("fa", "en") else ("en" if getattr(settings, "language", "fa") == "en" else "fa")
    return Invoice(
        0, PREVIEW_NUMBER, "sale", PREVIEW_ORDER_ID, 0, int(issued_ts if issued_ts is not None else time.time()),
        seller, dict(PREVIEW_BUYER), lines, totals["subtotal_irr"], totals["discount_irr"], totals["shipping_irr"],
        totals["tax_irr"], totals["total_irr"], "card_to_card", "paid", "", lang, {},
    )


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
        return Path(self._dir()) / safe_pdf_name(inv.number)

    def render_bytes(self, inv: Invoice) -> bytes:
        """همانِ یکِ مسیرِ رندر: فاکتورِ واقعی (از snapshot) و فاکتورِ تستی هر دو از این عبور می‌کنند."""
        ref = ""
        if inv.is_credit:
            base = self.store.get(inv.ref_invoice_id)
            ref = base.number if base else ""
        return invoice_pdf.render(inv, ref_number=ref, order_label=f"سفارش #{inv.order_id}")

    def ensure_pdf(self, inv: Invoice) -> Path:
        """PDFِ ذخیره‌شده یا ساختِ دوباره از snapshot (قطعی). ``InvoicePdfError`` اگه ساخته نشه."""
        path = self.path_of(inv)
        if path.is_file() and path.stat().st_size > 0:
            return path
        data = self.render_bytes(inv)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        if not inv.pdf_sha256:
            self.store.set_pdf_hash(inv.id, hashlib.sha256(data).hexdigest())
        return path

    # ------------------------------------------------------- فاکتورِ تستی
    def preview_bytes(self, lang: Optional[str] = None, now: Optional[int] = None) -> bytes:
        """بایتِ PDFِ «فاکتورِ تستی» (قلم ۸): snapshotِ نمونه از تنظیمات جاری ← *همان* رندرِ فاکتورِ واقعی.

        دیتابیس را نمی‌خواند و نمی‌نویسد، شمارنده را مصرف نمی‌کند و هیچ فرستنده‌ای صدا نمی‌زند."""
        return self.render_bytes(preview_invoice(self._settings(), lang=lang, issued_ts=now))

    def preview(self, lang: Optional[str] = None, now: Optional[int] = None) -> Path:
        """فاکتورِ تستی در همان پوشه‌ی PDFها (``invoices_dir()``)؛ هر بار بازنویسیِ همان فایل ⇒ idempotent."""
        data = self.preview_bytes(lang=lang, now=now)
        folder = Path(self._dir())
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / safe_pdf_name(PREVIEW_NUMBER)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        return path

    def delete_files(self, numbers: list) -> None:
        for number in numbers:
            try:
                (Path(self._dir()) / safe_pdf_name(number)).unlink(missing_ok=True)
            except OSError:
                logger.warning("حذفِ PDFِ فاکتور ناموفق بود", exc_info=True)

    # ---------------------------------------------------------------- صدور
    def _invoice_lang(self) -> str:
        """زبانِ فاکتور = زبانِ برنامه‌ی فروشنده (قلم ۱۰: ستونِ lang دیگر تزئینی نیست)."""
        return "en" if getattr(self._settings(), "language", "fa") == "en" else "fa"

    def issue(self, order) -> Invoice:
        """فاکتورِ فروش (idempotent) + PDF؛ خطای PDF فاکتور را نمی‌اندازد (متنی fallback است)."""
        inv = self.store.issue_sale(order, self._settings(), lang=self._invoice_lang(), now=int(self._clock()))
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
        lock = self._locks.get(invoice_id)
        if lock is None:
            self._prune_locks()
            lock = self._locks.setdefault(invoice_id, asyncio.Lock())
        return lock

    def _prune_locks(self) -> None:
        """قفلِ هر فاکتور تا ابد در حافظه نمی‌مونه؛ برنامه هفته‌ها روشن می‌ماند و فاکتور جمع می‌شه.

        فقط قفل‌هایِ *آزاد* و به‌ترتیبِ قدیمی حذف می‌شن، پس دو ارسالِ هم‌زمانِ یک فاکتور
        هرگز هم‌زمان نمی‌شوند (قفلِ در حالِ استفاده هیچ‌وقت نمی‌رود)."""
        if len(self._locks) < MAX_TRACKED_ENTRIES:
            return
        for inv_id in [k for k, lk in self._locks.items() if not lk.locked()]:
            self._locks.pop(inv_id, None)
            if len(self._locks) < MAX_TRACKED_ENTRIES - MAX_TRACKED_ENTRIES // 4:
                break

    def _mark_cooldown(self, key: tuple) -> None:
        """سقفِ «دوباره نکوب» هم باید کران‌دار باشد: کلید آن (پلتفرم، چت، فاکتور) است و
        مشتری‌ها زیاد می‌شوند."""
        now = self._clock()
        if len(self._cooldown) >= MAX_TRACKED_ENTRIES:
            for stale in [k for k, ts in self._cooldown.items() if now - ts >= CUSTOMER_COOLDOWN_SECONDS]:
                self._cooldown.pop(stale, None)
            if len(self._cooldown) >= MAX_TRACKED_ENTRIES:
                for k in list(self._cooldown)[: MAX_TRACKED_ENTRIES // 4]:
                    self._cooldown.pop(k, None)
        self._cooldown[key] = now

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
        self._mark_cooldown(key)
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
