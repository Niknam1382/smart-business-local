"""
متن‌های ثابتِ ربات (R13): همه‌ی پیام‌هایی که *مشتری* می‌بینه، کلیدی با ``fa``/``en``.

- زبانِ ربات از ``settings.bot_language``: ``fa`` (پیش‌فرض) | ``en`` | ``auto`` (از ``language_code`` کاربر).
- صاحبِ فروشگاه هر کلید رو (برای هر زبان) override می‌کنه: ``settings.bot_texts = {"fa": {کلید: متن}, "en": {...}}``.
  ذخیره فقط با ``set_override`` که placeholderها رو اعتبارسنجی می‌کنه (ناشناخته ⇒ رد).
- متنِ پیش‌فرضِ فارسیِ پیام‌های قدیمی **بدونِ تغییر** اینجا منتقل شده (تست‌های قبلی سبزن).
- ``t(key, **params)``: ارائه‌دهنده‌ی تنظیمات رو یک‌بار با ``configure(lambda: settings)`` وصل کن
  (BotManager این کار رو می‌کنه)؛ بدونِ آن، متنِ پیش‌فرضِ فارسی برمی‌گرده. رندر هرگز exception نمی‌ده.
"""

from __future__ import annotations

import string
from typing import Callable, Optional

SUPPORTED_LANGS = ("fa", "en")
MAX_TEXT_LEN = 1500

_REG: dict = {}
_provider: Optional[Callable[[], object]] = None
_formatter = string.Formatter()


class TextError(ValueError):
    """خطای اعتبارسنجیِ متنِ سفارشی (پیامِ فارسیِ قابل‌نمایش)."""


_RESERVED_PLACEHOLDERS = {"key", "lang", "settings"}  # با آرگومان‌های t()/render() تداخل می‌کنن


def _t(key: str, fa: str, en: Optional[str] = None) -> None:
    _REG[key] = {"fa": fa, "en": en if en is not None else fa}
    for text in (fa, en or fa):
        clash = _RESERVED_PLACEHOLDERS & {name for _lit, name, _spec, _conv in _formatter.parse(text) if name}
        if clash:
            raise ValueError(f"placeholderِ رزروشده در «{key}»: {sorted(clash)}")


def configure(provider: Optional[Callable[[], object]]) -> None:
    """``provider()`` باید شیءِ تنظیمات (``AppSettings``) رو برگردونه؛ ``None`` = فقط پیش‌فرض‌ها."""
    global _provider
    _provider = provider


# ------------------------------------------------------------------ پرس‌وجو ----


def keys() -> list:
    return sorted(_REG)


def has(key: str) -> bool:
    return key in _REG


def default(key: str, lang: str = "fa") -> str:
    entry = _REG[key]
    return entry.get(lang) or entry["fa"]


def _fields(template: str) -> list:
    """نام‌های placeholder؛ ``TextError`` اگه قالب خراب باشه."""
    try:
        parsed = list(_formatter.parse(template))
    except ValueError as exc:
        raise TextError("آکولادهای متن درست بسته نشده‌ان.") from exc
    out = []
    for _lit, name, spec, conv in parsed:
        if name is None:
            continue
        if not name.isidentifier() or spec or conv:
            raise TextError(f"placeholderِ «{{{name}}}» نامعتبره؛ فقط {{نام}} ساده مجازه.")
        out.append(name)
    return out


def placeholders(key: str) -> set:
    """placeholderهای مجازِ یه کلید = آن‌هایی که متنِ پیش‌فرضش (فارسی/انگلیسی) استفاده می‌کنه."""
    names: set = set()
    for lang in SUPPORTED_LANGS:
        names.update(_fields(_REG[key][lang]))
    return names


def resolve_lang(settings, user_language_code: Optional[str] = None) -> str:
    mode = getattr(settings, "bot_language", "fa") if settings is not None else "fa"
    if mode == "auto":
        return "en" if (user_language_code or "").lower().startswith("en") else "fa"
    return mode if mode in SUPPORTED_LANGS else "fa"


# ---------------------------------------------------------------- override ----


def validate_override(key: str, text: str) -> None:
    if key not in _REG:
        raise TextError(f"کلیدِ متنِ «{key}» وجود نداره.")
    if len(text) > MAX_TEXT_LEN:
        raise TextError(f"متن خیلی بلنده (حداکثر {MAX_TEXT_LEN} کاراکتر).")
    if any(ord(ch) < 32 and ch not in "\n\t" for ch in text):
        raise TextError("متن کاراکترِ کنترلیِ غیرمجاز داره.")
    unknown = set(_fields(text)) - placeholders(key)
    if unknown:
        allowed = "، ".join(f"{{{n}}}" for n in sorted(placeholders(key))) or "هیچ"
        raise TextError(f"placeholderِ ناشناخته: {', '.join(sorted(unknown))} — مجاز: {allowed}")


def set_override(settings, key: str, lang: str, text: str) -> None:
    """متنِ سفارشی رو (بعد از اعتبارسنجی) روی ``settings.bot_texts`` می‌نویسه؛ متنِ خالی = حذفِ override."""
    if lang not in SUPPORTED_LANGS:
        raise TextError("زبان باید fa یا en باشه.")
    text = (text or "").strip()
    store = {lg: dict(v) for lg, v in (getattr(settings, "bot_texts", None) or {}).items() if isinstance(v, dict)}
    if not text:
        store.get(lang, {}).pop(key, None)
    else:
        validate_override(key, text)
        store.setdefault(lang, {})[key] = text
    settings.bot_texts = store


def _override(settings, key: str, lang: str) -> str:
    table = getattr(settings, "bot_texts", None) if settings is not None else None
    if not isinstance(table, dict):
        return ""
    value = (table.get(lang) or {}).get(key, "")
    return value if isinstance(value, str) else ""


# ------------------------------------------------------------------- رندر ----


def _format(template: str, params: dict) -> Optional[str]:
    try:
        return template.format(**params)
    except (KeyError, IndexError, ValueError, AttributeError):
        return None


def render(settings, key: str, lang: Optional[str] = None, **params) -> str:
    """رندرِ یک کلید با تنظیماتِ صریح. override معیوب/ناسازگار ⇒ پیش‌فرض؛ هرگز exception نمی‌ده."""
    if key not in _REG:
        return key
    lang = lang if lang in SUPPORTED_LANGS else resolve_lang(settings)
    custom = _override(settings, key, lang)
    if custom:
        out = _format(custom, params)
        if out is not None:
            return out
    base = default(key, lang)
    out = _format(base, params)
    return out if out is not None else base


def t(key: str, *, lang: Optional[str] = None, **params) -> str:
    settings = _provider() if _provider is not None else None
    return render(settings, key, lang, **params)


# ====================================================================== متن‌ها ====
# --- پرداخت (منتقل‌شده از payments.py؛ فارسیِ بدونِ تغییر) ---
_t("pay.order_invalid", "این سفارش دیگه معتبر نیست.", "This order is no longer valid.")
_t("pay.item_unavailable", "«{name}» دیگه به‌اندازه‌ی کافی موجود نیست.", "“{name}” is no longer available in that quantity.")
_t("pay.invoice_sent", "🧾 فاکتور سفارش #{order_id} همین بالا فرستاده شد؛ روی دکمه‌ی پرداختش بزن.",
   "🧾 The invoice for order #{order_id} was sent above — tap its pay button.")
_t("pay.link_invalid",
   "این لینک پرداخت معتبر نیست یا مهلتش تموم شده. از همون چتی که سفارش دادی دوباره درخواست پرداخت بده.",
   "This payment link is invalid or has expired. Request payment again from the chat where you placed the order.")
_t("pay.already_paid", "این سفارش قبلاً پرداخت شده ✅", "This order has already been paid ✅")
_t("pay.disabled", "پرداخت با بله‌پی الان فعال نیست.", "Bale Pay is not available right now.")
_t("pay.failed", "ساخت فاکتور الان ممکن نشد؛ چند لحظه‌ی دیگه دوباره امتحان کن.",
   "Could not create the invoice right now; please try again in a moment.")
_t("pay.received", "پرداختتون با موفقیت دریافت شد ✅", "Your payment was received ✅")
_t("pay.received_late",
   "⚠️ پرداختتون بعد از پایان مهلتِ رزرو رسید؛ فروشنده موجودی رو بررسی می‌کنه و اگه کالا موجود نباشه، مبلغ برگردونده می‌شه.",
   "⚠️ Your payment arrived after the reservation window ended; the seller will check stock and refund you if the item is unavailable.")
_t("pay.received_pending", "سفارشتون به‌زودی توسط فروشنده بررسی و نهایی می‌شه.",
   "Your order will be reviewed and finalized by the seller shortly.")
_t("pay.left", "⏳ تا {minutes} دقیقه‌ی دیگه موجودی برات رزرو شده.", "⏳ Your items are reserved for another {minutes} minute(s).")
_t("pay.amount", "مبلغ: {amount} ریال", "Amount: {amount} IRR")
_t("pay.card.title", "💳 پرداخت کارت‌به‌کارت — سفارش #{order_id}", "💳 Card-to-card payment — order #{order_id}")
_t("pay.card.amount", "مبلغ دقیق: {amount} ریال", "Exact amount: {amount} IRR")
_t("pay.card.number", "شماره کارت: {number}", "Card number: {number}")
_t("pay.card.holder", "به نام: {holder}", "Card holder: {holder}")
_t("pay.card.after",
   "بعد از واریز، همین‌جا بنویس «پرداخت کردم» (شماره پیگیری یا ۴ رقم آخر کارتت رو هم بنویسی، سریع‌تر بررسی می‌شه).",
   "After transferring, write “I paid” here (adding the reference number or last 4 digits of your card speeds up the check).")
_t("pay.bale.native", "🧾 فاکتور بله‌پی برای سفارش #{order_id} همین بالا توی چت فرستاده شد؛ روی دکمه‌ی پرداختش بزن.",
   "🧾 The Bale Pay invoice for order #{order_id} was sent above in this chat — tap its pay button.")
_t("pay.bale.link.title", "🔗 پرداخت با بله‌پی — سفارش #{order_id}", "🔗 Pay with Bale Pay — order #{order_id}")
_t("pay.bale.link.open", "روی دکمه‌ی زیر بزن تا ربات بله باز بشه؛ بعد «شروع / Start» رو بزن و فاکتور همون‌جا برات میاد.",
   "Tap the button below to open the Bale bot, then press “Start” and the invoice will arrive there.")
_t("pay.bale.link.manual", "اگه خودکار شروع نشد، توی ربات بله این پیام رو بفرست: /pay {order_id} {code}",
   "If it does not start automatically, send this message in the Bale bot: /pay {order_id} {code}")
_t("pay.bale.button", "💳 پرداخت با بله‌پی", "💳 Pay with Bale Pay")
_t("pay.link.title", "🔗 پرداخت آنلاین با {label} — سفارش #{order_id}", "🔗 Pay online with {label} — order #{order_id}")
_t("pay.link.cta", "[برای پرداخت اینجا بزن]({url})", "[Tap here to pay]({url})")
_t("pay.link.button", "💳 پرداخت با {label}", "💳 Pay with {label}")
_t("pay.after_auto", "بعد از پرداخت، خودکار سفارشت تایید می‌شه و همین‌جا خبرت می‌کنم.",
   "After payment your order is confirmed automatically and I'll let you know right here.")
_t("pay.after_manual", "بعد از پرداخت، همین‌جا خبرت می‌کنم و فروشنده سفارش رو تایید می‌کنه.",
   "After payment I'll let you know right here and the seller will confirm your order.")
# --- سفارش (منتقل‌شده از orders.py / bot_manager.py) ---
_t("order.head", "سفارش #{order_id}", "Order #{order_id}")
_t("order.item", "- {name} ×{qty} = {amount} ریال", "- {name} ×{qty} = {amount} IRR")
_t("order.total", "جمع کل: {amount} ریال", "Total: {amount} IRR")
_t("ai.filtered", "ببخشید، نمی‌تونم به این پیام جواب بدم. سؤالِ دیگه‌ای داری بپرس یا از منو کمک بگیر.", "Sorry, I can't answer that message. Ask something else or use the menu.")
_t("order.subtotal", "جمعِ اقلام: {amount} ریال", "Subtotal: {amount} IRR")
_t("order.discount", "تخفیف: −{amount} ریال", "Discount: −{amount} IRR")
_t("order.rejected_head", "متأسفانه سفارش #{order_id} توسط فروشنده تایید نشد. 😔",
   "Unfortunately order #{order_id} was not approved by the seller. 😔")
_t("order.rejected_tail", "اگه مبلغی پرداخت کرده‌ای، فروشنده مبلغ رو برمی‌گردونه یا خودش باهات تماس می‌گیره.",
   "If you paid anything, the seller will refund you or contact you directly.")
_t("order.confirmed_head", "سفارشتون تایید شد 🎉", "Your order is confirmed 🎉")
_t("order.confirmed_tail", "ممنون از خریدتون!", "Thank you for your purchase!")
_t("order.expired", "⏳ مهلتِ پرداختِ سفارش #{order_id} تموم شد و موجودی‌ها آزاد شدن. اگه هنوز می‌خوای، بگو تا دوباره برات ثبتش کنم.",
   "⏳ The payment window for order #{order_id} has ended and the items were released. Tell me if you still want it and I'll place it again.")
_t("order.expired_card_hint", "اگه همین الان واریز کرده‌ای، بنویس «پرداخت کردم» تا به فروشنده اطلاع بدم.",
   "If you've just transferred the money, write “I paid” and I'll tell the seller.")
_t("inv.button", "🧾 فاکتور", "🧾 Invoice")
_t("inv.sent", "✅ فاکتور برات فرستاده شد.", "✅ Your invoice was sent.")
_t("inv.failed", "فاکتور الان فرستاده نشد؛ کمی بعد دوباره امتحان کن یا به فروشنده بگو.", "The invoice couldn't be sent right now; try again shortly or tell the seller.")
_t("inv.unavailable", "فاکتورِ این سفارش در دسترس نیست.", "No invoice is available for this order.")
_t("inv.caption", "🧾 فاکتور {number} — سفارش #{order_id}", "🧾 Invoice {number} — order #{order_id}")
_t("inv.text_head", "🧾 فاکتور {number} (نسخه‌ی متنی)", "🧾 Invoice {number} (text copy)")
_t("ai.fallback", "ببخشید، متوجه نشدم. می‌تونید دوباره بگید چه کمکی از من برمیاد؟",
   "Sorry, I didn't understand. Could you tell me again how I can help?")

# ====================================================== فروشگاهِ دکمه‌ای (R1) ====
# --- منوی اصلی ---
_t("menu.products", "🛍 محصولات", "🛍 Products")
_t("menu.cart", "🧺 سبد خرید", "🧺 Cart")
_t("menu.checkout", "✅ نهایی کردن سفارش", "✅ Checkout")
_t("menu.orders", "📦 سفارش‌هام", "📦 My orders")
_t("menu.orders_old", "📦 پیگیری سفارش", "📦 Track order")  # برچسبِ قدیمیِ کیبوردِ مشتری (فقط برای تشخیص؛ نمایش داده نمی‌شه)
_t("menu.guide", "ℹ️ راهنما", "ℹ️ Help")
_t("menu.faq", "❓ سؤالات متداول", "❓ FAQ")
_t("menu.welcome", "سلام {name} 👋\nبه فروشگاه خوش اومدی! از منوی پایین هر کاری خواستی انجام بده؛ سؤالی هم داشتی همین‌جا بنویس.",
   "Hi {name} 👋\nWelcome to the shop! Use the menu below, or just type a question.")
_t("menu.hint", "از منوی پایین انتخاب کن 👇", "Choose from the menu below 👇")
_t("ui.stale", "این دکمه دیگه معتبر نیست؛ منو رو برات باز کردم.", "That button is no longer valid; I opened the menu for you.")
_t("ui.error", "یه مشکلی پیش اومد؛ دوباره امتحان کن.", "Something went wrong; please try again.")
_t("ui.back", "↩️ بازگشت", "↩️ Back")
_t("ui.price", "{amount} ریال", "{amount} IRR")
# --- کاتالوگ ---
_t("cat.title", "🛍 محصولات", "🛍 Products")
_t("cat.choose_category", "یه دسته انتخاب کن:", "Choose a category:")
_t("cat.all", "📚 همه‌ی محصولات", "📚 All products")
_t("cat.categories", "🗂 دیدنِ دسته‌ها", "🗂 Browse categories")
_t("cat.empty", "فعلاً محصولی برای نمایش نیست.", "There are no products to show right now.")
_t("cat.prev", "◀ قبلی", "◀ Prev")
_t("cat.next", "بعدی ▶", "Next ▶")
_t("cat.page", "{page}/{pages}", "{page}/{pages}")
_t("cat.gone", "این محصول دیگه موجود نیست؛ برگشتم به لیست.", "That product is no longer available; back to the list.")
_t("prod.type_digital", "💾 دیجیتال", "💾 Digital")
_t("prod.type_physical", "📦 فیزیکی", "📦 Physical")
_t("prod.stock", "موجودی: {n} عدد", "In stock: {n}")
_t("prod.add", "🧺 افزودن به سبد", "🧺 Add to cart")
_t("prod.update", "🧺 ثبتِ تعدادِ جدید", "🧺 Update quantity")
_t("prod.in_cart", "✅ در سبد: {n}", "✅ In cart: {n}")
_t("prod.added", "به سبد اضافه شد 🧺", "Added to cart 🧺")
_t("prod.max", "حداکثر {n} عدد", "Max {n}")
_t("prod.view_cart", "🧺 مشاهده‌ی سبد", "🧺 View cart")
_t("prod.continue", "🛍 ادامه‌ی خرید", "🛍 Keep shopping")
# --- سبد ---
_t("cart.title", "🧺 سبد خرید", "🧺 Your cart")
_t("cart.empty", "سبد خریدت خالیه. از «🛍 محصولات» چیزی اضافه کن.", "Your cart is empty. Add something from “🛍 Products”.")
_t("cart.line", "{qty}× {name} — {amount}", "{qty}× {name} — {amount}")
_t("cart.total", "جمع کل: {amount} ریال", "Total: {amount} IRR")
_t("cart.note", "ℹ️ سبد رزرو نیست؛ موجودی با ثبتِ سفارش برای {minutes} دقیقه رزرو می‌شه.",
   "ℹ️ The cart does not reserve stock; stock is reserved for {minutes} minutes once you place the order.")
_t("cart.warn_short", "⚠️ از «{name}» فقط {n} عدد موجوده.", "⚠️ Only {n} of “{name}” left.")
_t("cart.warn_gone", "⚠️ «{name}» دیگه موجود نیست.", "⚠️ “{name}” is no longer available.")
_t("cart.fix", "🔧 سبدم رو درست کن", "🔧 Fix my cart")
_t("cart.fix_hint", "برای ادامه «🔧 سبدم رو درست کن» رو بزن تا موجودی‌ها اعمال بشه.", "To continue, tap “🔧 Fix my cart” to apply the available stock.")
_t("cart.fixed", "سبد درست شد. حالا می‌تونی «✅ ثبتِ سفارش» رو بزنی.", "Your cart is fixed. You can now tap “✅ Place order”.")
_t("cart.clear", "🧹 خالی‌کردنِ سبد", "🧹 Empty cart")
_t("cart.clear_confirm", "سبد کاملاً خالی بشه؟", "Empty the whole cart?")
_t("cart.clear_yes", "✅ بله، خالی کن", "✅ Yes, clear it")
_t("cart.cleared", "سبد خالی شد. برای خرید از «🛍 محصولات» شروع کن.", "Your cart is empty. Start from “🛍 Products” to shop.")
_t("cart.checkout", "✅ ثبتِ سفارش", "✅ Place order")
# --- کدِ تخفیف (N8) ---
_t("cart.discount", "🎟 تخفیف ({code}): −{amount} ریال", "🎟 Discount ({code}): −{amount} IRR")
_t("cart.payable", "مبلغِ قابل‌پرداخت: {amount} ریال", "Amount to pay: {amount} IRR")
_t("cart.code", "🎟 کد تخفیف", "🎟 Discount code")
_t("cart.code_remove", "✖️ حذفِ کد", "✖️ Remove code")
_t("cart.code_gone", "ℹ️ کدِ تخفیفِ قبلی دیگه معتبر نیست؛ مبلغ بدونِ اون حساب شد.", "ℹ️ Your earlier discount code is no longer valid; the amount was calculated without it.")
_t("disc.ask", "کدِ تخفیفت رو همین‌جا بنویس و بفرست. برای انصراف «🧺 سبد خرید» رو بزن.", "Type and send your discount code here. To go back, tap “🧺 Cart”.")
_t("disc.applied", "✅ کدِ «{code}» اعمال شد. ببین مبلغِ جدید توی سبد:", "✅ Code “{code}” applied. See the new amount in your cart:")
_t("disc.removed", "کدِ تخفیف برداشته شد.", "Discount code removed.")
_t("disc.err.unknown", "این کد معتبر نیست. دوباره بفرست یا «🧺 سبد خرید» رو بزن.", "That code isn't valid. Send it again or tap “🧺 Cart”.")
_t("disc.err.not_started", "این کد هنوز شروع نشده؛ بعداً امتحانش کن.", "This code hasn't started yet; try again later.")
_t("disc.err.expired", "مهلتِ این کد تموم شده.", "This code has expired.")
_t("disc.err.min_subtotal", "جمعِ سبدت به حداقلِ لازم برای این کد نرسیده؛ چند تا محصولِ دیگه اضافه کن.", "Your cart is below the minimum for this code; add a few more items.")
_t("disc.err.not_applicable", "این کد روی محصولاتِ سبدِ تو اعمال نمی‌شه.", "This code doesn't apply to the items in your cart.")
_t("disc.err.first_only", "این کد فقط برای اولین خریده.", "This code is for first purchases only.")
_t("disc.err.min_prev", "این کد فقط برای مشتریانِ قدیمی‌تره.", "This code is for returning customers only.")
_t("disc.err.platform", "این کد توی این پیام‌رسان فعال نیست.", "This code isn't active on this messenger.")
_t("disc.err.per_customer", "قبلاً از این کد استفاده کرده‌ای.", "You've already used this code.")
_t("disc.err.exhausted", "ظرفیتِ این کد پر شده.", "This code has reached its limit.")
_t("disc.err.locked", "تلاشِ ناموفقِ زیاد بود. {n} دقیقه‌ی دیگه دوباره امتحان کن.", "Too many wrong tries. Try again in {n} minutes.")
_t("disc.err.too_low", "با این کد مبلغ از حداقلِ قابل‌پرداخت کمتر می‌شه؛ کدِ دیگه‌ای امتحان کن.", "With this code the amount would fall below the minimum payable; try another code.")
# --- چک‌اوت ---
_t("co.cancel", "✖️ لغوِ ثبتِ سفارش", "✖️ Cancel order")
_t("co.back", "↩️ مرحله‌ی قبل", "↩️ Previous step")
_t("co.skip", "⏭ ردش کن", "⏭ Skip")
_t("co.share_phone", "📱 ارسالِ شماره‌ی من", "📱 Send my number")
_t("co.step", "({i}/{n}) {prompt}", "({i}/{n}) {prompt}")
_t("co.invalid", "⚠️ {error}", "⚠️ {error}")
_t("co.summary_title", "📝 خلاصه‌ی سفارش", "📝 Order summary")
_t("co.edit", "✏️ ویرایشِ {label}", "✏️ Edit {label}")
_t("co.edit_info", "✏️ ویرایشِ اطلاعات", "✏️ Edit my details")
_t("co.edit_pick", "کدوم اطلاعات رو می‌خوای تغییر بدی؟", "Which detail do you want to change?")
_t("co.confirm", "✅ تأیید و پرداخت", "✅ Confirm & pay")
_t("co.choose_payment", "روش پرداخت رو انتخاب کن:", "Choose a payment method:")
_t("co.no_payment", "الان هیچ روش پرداختی فعال نیست؛ لطفاً با فروشنده هماهنگ کن.", "No payment method is available right now; please contact the seller.")
_t("co.continue_or_cancel", "ثبتِ سفارشت هنوز تموم نشده. ادامه بدیم یا لغوش کنیم؟", "Your order isn't finished yet. Continue or cancel it?")
_t("co.resume", "▶️ ادامه‌ی ثبتِ سفارش", "▶️ Continue order")
_t("co.cancelled", "ثبتِ سفارش لغو شد. سبدت سر جاشه؛ هر وقت آماده بودی «🧺 سبد خرید» رو باز کن.", "Checkout cancelled. Your cart is still here; open “🧺 Cart” whenever you're ready.")
_t("co.no_session", "ثبتِ سفارشی در جریان نیست. اگه سفارش دادی، از «📦 سفارش‌هام» ببینش.",
   "There is no checkout in progress. If you already ordered, see “📦 My orders”.")
_t("co.pending_exists", "یه سفارشِ پرداخت‌نشده (#{order_id}) داری؛ اول از «📦 سفارش‌هام» همون رو پرداخت یا لغو کن.",
   "You already have an unpaid order (#{order_id}); first pay or cancel it from “📦 My orders”.")
_t("co.too_many", "تعدادِ سفارش‌های اخیرِ تو زیاد بوده؛ برای حفظِ موجودیِ بقیه، چند وقتِ دیگه دوباره امتحان کن.",
   "You've placed many orders recently; to keep stock fair for others, please try again later.")
_t("co.stock_problem", "⚠️ موجودیِ بعضی اقلام تغییر کرده:", "⚠️ Stock changed for some items:")
_t("co.created", "✅ سفارش #{order_id} ثبت شد.", "✅ Order #{order_id} placed.")
_t("co.pay_failed", "ساختنِ دستورِ پرداخت الان ممکن نشد. سفارشت ثبت شده؛ از «📦 سفارش‌هام» دوباره امتحان کن یا روشِ دیگه‌ای بزن.",
   "Could not prepare the payment right now. Your order is saved; try again from “📦 My orders” or pick another method.")
_t("co.method.card_to_card", "💳 کارت‌به‌کارت", "💳 Card to card")
_t("co.method.bale_pay", "💳 بله‌پی", "💳 Bale Pay")
_t("co.method.zarinpal", "💳 زرین‌پال", "💳 Zarinpal")
# --- پیگیری سفارش ---
_t("ord.title", "📦 سفارش‌های من", "📦 My orders")
_t("ord.none", "هنوز سفارشی نداری. از «🛍 محصولات» شروع کن.", "You have no orders yet. Start from “🛍 Products”.")
_t("ord.line", "#{id} — {status} — {amount}", "#{id} — {status} — {amount}")
_t("ord.status.pending_payment", "⏳ در انتظار پرداخت", "⏳ Awaiting payment")
_t("ord.status.paid", "💳 پرداخت‌شده؛ منتظر تایید", "💳 Paid; awaiting confirmation")
_t("ord.status.confirmed", "✅ تایید شده", "✅ Confirmed")
_t("ord.status.rejected", "❌ رد شده", "❌ Rejected")
_t("ord.status.cancelled", "🚫 لغو شده", "🚫 Cancelled")
_t("ord.status.expired", "⌛ منقضی شده", "⌛ Expired")
_t("ord.left", "⏳ {minutes} دقیقه‌ی دیگه تا پایانِ رزرو", "⏳ {minutes} min left on your reservation")
_t("ord.cancel", "❌ لغو سفارش", "❌ Cancel order")
_t("ord.cancel_confirm", "سفارش #{order_id} لغو بشه؟", "Cancel order #{order_id}?")
_t("ord.cancel_yes", "✅ بله، لغو کن", "✅ Yes, cancel it")
_t("ord.cancelled", "سفارش #{order_id} لغو شد. اگه خواستی دوباره از «🛍 محصولات» سفارش بده.", "Order #{order_id} was cancelled. You can order again from “🛍 Products”.")
_t("ord.cannot_cancel", "این سفارش دیگه قابل‌لغو نیست.", "This order can no longer be cancelled.")
_t("ord.pay", "💳 پرداخت", "💳 Pay")
_t("ord.not_found", "این سفارش پیدا نشد؛ فهرستت رو از «📦 سفارش‌هام» ببین.", "Order not found; check your list under “📦 My orders”.")
_t("ord.not_payable", "این سفارش دیگه قابل‌پرداخت نیست (مهلتش تموم شده یا پرداخت شده).", "This order can no longer be paid (expired or already paid).")
_t("ord.info", "{label}: {value}", "{label}: {value}")
# --- سؤالات متداول ---
_t("faq.title", "❓ سؤالات متداول", "❓ Frequently asked questions")
_t("faq.empty", "هنوز سؤالی ثبت نشده؛ سؤالت رو همین‌جا بنویس.", "No questions yet; just type yours here.")
_t("faq.back", "↩️ فهرست سؤال‌ها", "↩️ All questions")
# --- زیرمنوی «راهنما» (N5) ---
_t("guide.title", "ℹ️ راهنما", "ℹ️ Help")
_t("guide.body", "برای خرید از «🛍 محصولات» شروع کن. سؤالی داشتی همین‌جا بنویس یا یکی از گزینه‌های زیر رو بزن.",
   "To shop, start with “🛍 Products”. If you have a question, just type it here or pick an option below.")
_t("guide.more", "بیشتر ◀", "More ▶")
# --- تحویلِ دیجیتال (R4) ---
_t("deliver.head", "📬 تحویلِ سفارش #{order_id}", "📬 Delivery for order #{order_id}")
_t("deliver.item", "• {name}:", "• {name}:")
_t("deliver.key", "کلید/لایسنس: {secret}", "Key/licence: {secret}")
_t("deliver.failed_owner", "⚠️ تحویلِ دیجیتالِ سفارش #{order_id} به مشتری نرسید ({reason}). دوباره تلاش می‌شه؛ اگه نشد دستی بفرست.",
   "⚠️ Digital delivery for order #{order_id} did not reach the customer ({reason}). It will be retried; otherwise send it manually.")
_t("pay.claim", "✅ پرداخت کردم", "✅ I paid")
_t("pay.claim_done", "ممنون! پرداختت ثبت شد و منتظر تأییدِ فروشنده‌ست. اگه خواستی شماره‌ی پیگیری یا ۴ رقم آخرِ کارتت رو همین‌جا بنویس.",
   "Thanks! Your payment was recorded and is awaiting the seller's confirmation. If you like, send the reference number or last 4 card digits here.")
_t("pay.claim_bad", "برای این سفارش نمی‌شه «پرداخت کردم» زد (روشِ کارت‌به‌کارت انتخاب نشده یا سفارش بسته شده).",
   "You can't mark this order as paid (card-to-card wasn't chosen or the order is closed).")
_t("pay.ref_saved", "شماره‌ی پیگیری ثبت شد ✅ فروشنده به‌زودی پرداختت رو بررسی می‌کنه.", "Reference saved ✅ The seller will check your payment soon.")
_t("ui.contact_saved", "شماره‌ات رو گرفتم و به فروشنده اطلاع می‌دم ✅", "Got your number; I'll let the seller know ✅")
_t("ui.no_support", "پشتیبانیِ انسانی الان فعال نیست.", "Human support isn't available right now.")
_t("custom.share_contact", "برای ارسالِ شماره‌ات روی دکمه‌ی پایین بزن:", "Tap the button below to share your number:")
# --- پشتیبانیِ انسانی (R5) ---
_t("handoff.started", "✅ درخواستت ثبت شد. از الان هر پیامی بنویسی مستقیم به پشتیبان می‌رسه؛ وقتی کارت تموم شد «پایان گفتگو» رو بزن.",
   "✅ Request received. From now on every message you write goes straight to our support; press “End chat” when you're done.")
_t("handoff.offhours", "⏰ الان خارج از ساعتِ کاریِ ما هستیم؛ پیامت ثبت می‌شه و در اولین فرصت جواب می‌دیم.",
   "⏰ We're outside working hours right now; your message is saved and we'll reply as soon as possible.")
_t("handoff.end", "✖️ پایان گفتگو با پشتیبان", "✖️ End chat with support")
_t("handoff.ended", "گفتگوی پشتیبانی بسته شد. هر وقت خواستی دوباره از منو درخواست بده.", "The support chat was closed. Request it again from the menu any time.")
_t("handoff.timeout", "گفتگوی پشتیبانی به‌خاطرِ بی‌فعالیتی بسته شد. اگه هنوز کمک می‌خوای دوباره درخواست بده.",
   "The support chat was closed due to inactivity. Request it again if you still need help.")
_t("handoff.owner_reply", "💬 پشتیبان: {text}", "💬 Support: {text}")
# --- سقفِ مصرفِ AI (R10-۳) ---
_t("limit.chat", "برای جلوگیری از سوءاستفاده، امروز به سقفِ پرسش‌وپاسخ با هوش مصنوعی رسیدی. از منوی پایین استفاده کن یا فردا دوباره بپرس.",
   "To prevent abuse you've reached today's limit of AI answers. Use the menu below or ask again tomorrow.")
_t("limit.total", "پاسخ‌گوییِ هوشمندِ فروشگاه برای امروز به سقفش رسیده؛ لطفاً از منوی پایین استفاده کن یا کمی بعد دوباره بپرس.",
   "The shop's AI answers have reached today's limit; please use the menu below or try again later.")
_t("limit.kill", "پاسخ‌گوییِ هوشمند موقتاً غیرفعاله؛ از منوی پایین استفاده کن یا با پشتیبانی صحبت کن.",
   "AI answers are temporarily disabled; please use the menu below or talk to support.")
# --- حریمِ خصوصی (R10-۴) ---
_t("privacy.ai_disclosure", "🤖 پاسخ‌های متنیِ این ربات با هوش مصنوعی تولید می‌شه و ممکنه اشتباه کنه؛ سفارش و پرداخت فقط با دکمه‌هاست.",
   "🤖 The text answers of this bot are generated by AI and may be wrong; orders and payments are handled only with the buttons.")
_t("privacy.forgotten", "✅ تاریخچه‌ی گفتگو، سبد و ثبتِ سفارشِ نیمه‌کاره‌ات پاک شد و اطلاعاتِ شخصیِ سفارش‌های بسته‌شده‌ات حذف شد. سفارش‌های در جریان برای پیگیری باقی می‌مونن.",
   "✅ Your chat history, cart and unfinished checkout were deleted, and personal details on your closed orders were removed. Open orders stay so you can track them.")
# --- پیامِ شخصیِ مالک (N6)، پیامِ همگانی و لغوِ اشتراک (N7) ---
_t("owner.direct", "💬 فروشگاه: {text}", "💬 Shop: {text}")
_t("broadcast.footer", "برای توقفِ دریافتِ پیام‌های همگانی، /stop رو بفرست.", "To stop receiving broadcast messages, send /stop.")
_t("broadcast.stopped", "✅ دیگه پیامِ همگانی برات نمی‌فرستیم. پاسخ به سؤال‌هات و پیگیریِ سفارش‌ها مثلِ قبل کار می‌کنه. هر وقت خواستی دوباره /start رو بزن.",
   "✅ You won't get broadcast messages anymore. Answers to your questions and order tracking keep working. Send /start any time to opt back in.")
_t("broadcast.resumed", "✅ دوباره پیام‌های همگانی برات فعال شد؛ هر وقت خواستی /stop رو بفرست.", "✅ Broadcast messages are back on for you; send /stop any time to turn them off.")
# --- عضویتِ اجباریِ کانال (N13) ---
_t("channel.required", "📢 برای استفاده از ربات، اول توی کانالِ زیر عضو شو و بعد دکمه‌ی «عضو شدم» رو بزن.", "📢 To use this bot, please join the channel below first, then tap “I joined”.")
_t("channel.join", "📢 {title}", "📢 {title}")
_t("channel.joined", "✅ عضو شدم", "✅ I joined")
_t("channel.still_missing", "هنوز عضو نشدی؛ اول عضو شو، بعد دوباره بزن.", "You haven't joined yet — join first, then tap again.")
_t("channel.confirmed", "✅ عضویتت تأیید شد؛ خوش اومدی!", "✅ Membership confirmed — welcome!")
# --- حالتِ «جمع‌آوریِ سرنخ» (R2) ---
_t("menu.lead", "📝 ثبت درخواست", "📝 Send a request")
_t("lead.done", "✅ درخواستت ثبت شد؛ به‌زودی باهات تماس می‌گیریم.", "✅ Your request was received; we'll contact you soon.")
_t("lead.owner", "📝 درخواستِ جدید از «{label}» ({platform}):\n{details}", "📝 New request from “{label}” ({platform}):\n{details}")
