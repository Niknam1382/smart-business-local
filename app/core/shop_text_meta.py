"""متادیتای ویرایشگرِ متن‌های ربات (N3) — برای هر کلید: عنوانِ ساده، گروه، «کِی نمایش داده می‌شه»، سطح (پایه/پیشرفته)،
و نامِ فارسیِ متغیرها با مثال. هدف: کاربر هرگز کلیدِ فنی (``pay.card.after``) یا placeholderِ خام (``{order_id}``) نبینه.

* داخلِ کادرِ ویرایش، متغیرها به شکلِ «{شماره‌ی سفارش}» نشان داده می‌شن (``to_display``) و موقعِ ذخیره به ``{order_id}`` برمی‌گردن
  (``from_display``)؛ مقدارِ ذخیره‌شده همان قالبِ قدیمی است، پس هیچ مهاجرتی لازم نیست.
* ``preview`` با مقدارهای نمونه (مثلاً «سفارش #12») متن را همان‌طور که مشتری می‌بینه نشان می‌ده.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.core import shop_texts

LEVEL_BASIC = "basic"
LEVEL_ADVANCED = "advanced"

# (id, عنوانِ فارسی, English, «کِی نمایش داده می‌شه» پیش‌فرضِ گروه فارسی, English)
GROUPS = (
    ("welcome", "شروع و منو", "Start & menu", "هنگامِ باز کردنِ ربات و منوها", "When the bot is opened and for menus"),
    ("catalog", "محصولات", "Products", "هنگامِ دیدنِ محصولات", "While browsing products"),
    ("cart", "سبد خرید", "Cart", "هنگامِ کار با سبد خرید", "While using the cart"),
    ("checkout", "ثبتِ سفارش", "Checkout", "هنگامِ ثبتِ سفارش (پرسیدنِ اطلاعات)", "While placing an order (asking for details)"),
    ("payment", "پرداخت", "Payment", "هنگامِ پرداختِ سفارش", "While paying for an order"),
    ("orders", "سفارش‌ها", "Orders", "هنگامِ دیدن و پیگیریِ سفارش‌ها", "While viewing or tracking orders"),
    ("delivery", "تحویلِ دیجیتال", "Digital delivery", "هنگامِ تحویلِ محصولِ دیجیتال", "When a digital product is delivered"),
    ("support", "پشتیبانی و درخواست", "Support & requests", "هنگامِ پشتیبانی و ثبتِ درخواست", "During support and request handling"),
    ("system", "سایر پیام‌ها", "Other messages", "پیام‌های عمومی و خطاها", "General messages and errors"),
)
_GROUP = {g[0]: g for g in GROUPS}

# key | group | level | عنوانِ فارسی | English title | «کِی» (اختیاری؛ خالی = پیش‌فرضِ گروه) | when (EN)
_TABLE = """
ai.fallback|system|basic|وقتی ربات سؤال رو نفهمید|When the bot doesn't understand|وقتی هوش مصنوعی نتونه جواب بده یا سؤال نامفهوم باشه|When the AI can't answer or the question is unclear
broadcast.footer|system|advanced|پانویسِ پیامِ همگانی (راهنمای /stop)|Broadcast footer (/stop hint)|پایانِ هر پیامِ همگانی|End of every broadcast message
broadcast.resumed|system|advanced|تأییدِ فعال‌شدنِ دوباره‌ی پیامِ همگانی|Broadcast turned back on||
broadcast.stopped|system|advanced|تأییدِ لغوِ پیامِ همگانی (/stop)|Broadcast opt-out confirmed (/stop)||
cart.checkout|cart|advanced|دکمه‌ی «ثبتِ سفارش» در سبد|“Place order” button in the cart|زیرِ پیامِ سبد خرید|Under the cart message
cart.code|cart|advanced|دکمه‌ی «کد تخفیف»|“Discount code” button|زیرِ سبد، وقتی فروشگاه کدِ تخفیف داره|Under the cart when the shop has discount codes
cart.code_gone|cart|advanced|هشدارِ نامعتبر شدنِ کدِ تخفیف|Discount code no longer valid notice|وقتی کدِ تخفیفِ سبد دیگه معتبر نیست|When the cart's discount code stops being valid
cart.code_remove|cart|advanced|دکمه‌ی «حذفِ کد»|“Remove code” button|زیرِ سبد، وقتی کدی اعمال شده|Under the cart when a code is applied
cart.discount|cart|advanced|سطرِ تخفیف در سبد|Discount line in the cart||
cart.payable|cart|advanced|سطرِ «مبلغِ قابل‌پرداخت» در سبد|“Amount to pay” line in the cart||
disc.applied|cart|advanced|تأییدِ اعمالِ کدِ تخفیف|Discount code applied confirmation|بعد از فرستادنِ کدِ درست|After a valid code is sent
disc.ask|cart|advanced|درخواستِ کدِ تخفیف|Ask for the discount code|بعد از زدنِ دکمه‌ی «کد تخفیف»|After tapping the discount code button
disc.err.exhausted|cart|advanced|کد: ظرفیت پر شده|Code: limit reached||
disc.err.expired|cart|advanced|کد: مهلت تموم شده|Code: expired||
disc.err.first_only|cart|advanced|کد: فقط اولین خرید|Code: first purchase only||
disc.err.locked|cart|advanced|کد: تلاشِ زیادِ ناموفق|Code: too many wrong tries||
disc.err.min_prev|cart|advanced|کد: فقط مشتری قدیمی|Code: returning customers only||
disc.err.min_subtotal|cart|advanced|کد: سبد به حداقل نرسیده|Code: cart below minimum||
disc.err.not_applicable|cart|advanced|کد: روی سبد اعمال نمی‌شه|Code: doesn't apply to the cart||
disc.err.not_started|cart|advanced|کد: هنوز شروع نشده|Code: not started yet||
disc.err.per_customer|cart|advanced|کد: قبلاً استفاده شده|Code: already used||
disc.err.platform|cart|advanced|کد: در این پیام‌رسان فعال نیست|Code: not active on this messenger||
disc.err.too_low|cart|advanced|کد: مبلغ از حداقل کمتر می‌شه|Code: amount would be too low||
disc.err.unknown|cart|advanced|کد: نامعتبر|Code: not valid||
disc.removed|cart|advanced|تأییدِ برداشتنِ کدِ تخفیف|Discount code removed confirmation||
ai.filtered|system|advanced|پاسخِ ایمنِ فیلترِ محتوا|Content-filter safe reply|وقتی سرویسِ AI پیام را به‌خاطرِ سیاستِ محتوا رد می‌کنه|When the AI service refuses a message under its content policy
order.discount|orders|advanced|سطرِ تخفیفِ سفارش|Order discount line||
order.subtotal|orders|advanced|سطرِ «جمعِ اقلام» سفارش|Order subtotal line||
cart.clear|cart|advanced|دکمه‌ی «خالی‌کردنِ سبد»|“Empty the cart” button|زیرِ پیامِ سبد خرید|Under the cart message
cart.clear_confirm|cart|advanced|سؤالِ تأییدِ خالی‌کردنِ سبد|Confirm emptying the cart||
cart.clear_yes|cart|advanced|دکمه‌ی «بله، خالی کن»|“Yes, empty it” button||
cart.cleared|cart|advanced|پیامِ بعد از خالی‌شدنِ سبد|After the cart is emptied||
cart.empty|cart|basic|پیامِ سبدِ خالی|Empty cart message|وقتی مشتری سبدِ خالی رو باز می‌کنه|When a customer opens an empty cart
cart.fix|cart|advanced|دکمه‌ی «درست‌کردنِ سبد»|“Fix my cart” button|وقتی موجودیِ یک قلمِ سبد تغییر کرده|When an item's stock changed
cart.fix_hint|cart|advanced|راهنمای دکمه‌ی «درست‌کردنِ سبد»|Hint for the “Fix my cart” button|زیرِ هشدارهای موجودی در سبد|Under the stock warnings in the cart
cart.fixed|cart|advanced|پیامِ بعد از درست‌شدنِ سبد|After the cart is fixed||
cart.line|cart|advanced|سطرِ هر قلم در سبد|One cart line||
cart.note|cart|advanced|یادآوریِ رزروِ موجودی|Stock-reservation note|پایینِ سبد|Bottom of the cart
cart.title|cart|advanced|عنوانِ سبد خرید|Cart title||
cart.total|cart|advanced|سطرِ «جمع کل» سبد|Cart total line||
cart.warn_gone|cart|advanced|هشدارِ تمام‌شدنِ یک محصول در سبد|Item no longer available warning||
cart.warn_short|cart|advanced|هشدارِ کم‌بودنِ موجودی در سبد|Low stock warning||
cat.all|catalog|advanced|دکمه‌ی «همه‌ی محصولات»|“All products” button||
cat.categories|catalog|advanced|دکمه‌ی «دسته‌ها»|“Categories” button||
cat.choose_category|catalog|advanced|درخواستِ انتخابِ دسته|Ask to choose a category||
cat.empty|catalog|basic|پیامِ نبودنِ محصول|No products message|وقتی هنوز محصولی ثبت نشده یا همه تمام شده‌ن|When there are no products to show
cat.gone|catalog|advanced|پیامِ ناموجود شدنِ محصول|Product no longer available||
cat.next|catalog|advanced|دکمه‌ی «بعدی»|“Next” button||
cat.page|catalog|advanced|شماره‌ی صفحه‌ی لیستِ محصولات|Product list page number||
cat.prev|catalog|advanced|دکمه‌ی «قبلی»|“Previous” button||
cat.title|catalog|advanced|عنوانِ لیستِ محصولات|Product list title||
channel.confirmed|system|advanced|تأییدِ عضویت در کانال|Channel membership confirmed||
channel.join|system|advanced|دکمه‌ی لینکِ کانال|Channel link button||
channel.joined|system|advanced|دکمه‌ی «عضو شدم»|“I joined” button||
channel.required|system|advanced|پیامِ «اول عضو کانال شو»|“Join the channel first” message|وقتی مشتری عضوِ کانالِ اجباری نیست|When the customer hasn't joined the required channel
channel.still_missing|system|advanced|هشدارِ «هنوز عضو نشدی»|“You haven't joined yet” notice||
co.back|checkout|advanced|دکمه‌ی «برگشت به مرحله‌ی قبل»|“Back to previous step” button||
co.cancel|checkout|advanced|دکمه‌ی «لغوِ ثبتِ سفارش»|“Cancel checkout” button||
co.cancelled|checkout|advanced|پیامِ لغوِ ثبتِ سفارش|Order cancelled message||
co.choose_payment|checkout|advanced|درخواستِ انتخابِ روشِ پرداخت|Ask to choose a payment method||
co.confirm|checkout|advanced|دکمه‌ی «تأیید و انتخابِ پرداخت»|“Confirm and pay” button||
co.continue_or_cancel|checkout|advanced|وقتی مشتری وسطِ ثبتِ سفارش چیزِ دیگه‌ای می‌زنه|When a customer does something else mid-order||
co.created|checkout|advanced|پیامِ ثبتِ سفارش|Order created message||
co.edit|checkout|advanced|دکمه‌ی «ویرایشِ یک اطلاعات»|“Edit this detail” button||
co.edit_info|checkout|advanced|دکمه‌ی «ویرایشِ اطلاعات» در خلاصه‌ی سفارش|“Edit my details” button in the summary||
co.edit_pick|checkout|advanced|سؤالِ «کدوم اطلاعات رو تغییر بدی؟»|“Which detail to change?” question||
co.invalid|checkout|advanced|پیامِ ورودیِ نادرست|Invalid input message||
co.method.bale_pay|payment|advanced|نامِ روشِ پرداختِ بله‌پی|Bale Pay method name||
co.method.card_to_card|payment|advanced|نامِ روشِ پرداختِ کارت‌به‌کارت|Card-to-card method name||
co.method.zarinpal|payment|advanced|نامِ روشِ پرداختِ زرین‌پال|ZarinPal method name||
co.no_payment|checkout|advanced|پیامِ نبودنِ روشِ پرداخت|No payment method message||
co.no_session|checkout|advanced|پیامِ نبودنِ ثبتِ سفارشِ در جریان|No checkout in progress||
co.pay_failed|checkout|advanced|پیامِ ناموفق‌بودنِ ساختِ پرداخت|Payment could not be prepared||
co.pending_exists|checkout|advanced|پیامِ داشتنِ سفارشِ پرداخت‌نشده|Unpaid order already exists||
co.resume|checkout|advanced|دکمه‌ی «ادامه‌ی ثبتِ سفارش»|“Continue order” button||
co.share_phone|checkout|advanced|دکمه‌ی «ارسالِ شماره‌ی من»|“Send my number” button||
co.skip|checkout|advanced|دکمه‌ی «ردش کن»|“Skip” button||
co.step|checkout|advanced|شماره‌ی مرحله + سؤالِ فرم|Step number and form question||
co.stock_problem|checkout|advanced|هشدارِ تغییرِ موجودی هنگامِ ثبتِ سفارش|Stock changed during checkout||
co.summary_title|checkout|advanced|عنوانِ خلاصه‌ی سفارش|Order summary title||
co.too_many|checkout|advanced|پیامِ سفارش‌های پشت‌سرهمِ زیاد|Too many recent orders||
custom.share_contact|support|advanced|درخواستِ ارسالِ شماره‌ی تماس|Ask to share the phone number||
deliver.failed_owner|delivery|advanced|اعلانِ نرسیدنِ محصولِ دیجیتال (برای تو)|Digital delivery failed (for you)|فقط برای مالک؛ وقتی ارسالِ محصولِ دیجیتال به مشتری نرسید|Owner only; when a digital delivery fails
deliver.head|delivery|advanced|تیترِ پیامِ تحویلِ دیجیتال|Digital delivery heading||
deliver.item|delivery|advanced|سطرِ هر محصولِ دیجیتال|Digital delivery item line||
deliver.key|delivery|advanced|سطرِ کلید/لایسنس|License key line||
faq.back|support|advanced|دکمه‌ی «برگشت به فهرستِ سؤال‌ها»|“Back to questions” button||
faq.empty|support|advanced|پیامِ نبودنِ سؤالِ متداول|No FAQ yet||
faq.title|support|advanced|عنوانِ سؤالاتِ متداول|FAQ title||
guide.body|welcome|advanced|متنِ منوی «راهنما»|“Help” menu text||
guide.more|welcome|advanced|دکمه‌ی «بیشتر» در راهنما|“More” button in help||
guide.title|welcome|advanced|عنوانِ منوی «راهنما»|“Help” menu title||
handoff.end|support|advanced|دکمه‌ی «پایانِ گفتگو با پشتیبان»|“End support chat” button||
handoff.ended|support|advanced|پیامِ بسته‌شدنِ گفتگوی پشتیبانی|Support chat closed||
handoff.offhours|support|basic|پیامِ خارج از ساعتِ کاری|Outside working hours message|وقتی مشتری پشتیبان می‌خواد ولی ساعتِ کاری تموم شده|When a customer asks for support outside working hours
handoff.owner_reply|support|advanced|قالبِ پاسخِ پشتیبان به مشتری|Support reply format||
handoff.started|support|basic|پیامِ شروعِ گفتگو با پشتیبان|Support chat started|وقتی مشتری درخواستِ پشتیبانیِ انسانی می‌ده|When a customer asks for a human
handoff.timeout|support|advanced|پیامِ بسته‌شدنِ گفتگو به‌خاطرِ بی‌فعالیتی|Support chat closed (inactivity)||
lead.done|support|basic|پیامِ بعد از ثبتِ درخواست|After a request is submitted|وقتی مشتری فرمِ «ثبتِ درخواست» رو تموم می‌کنه|When a customer finishes the request form
lead.owner|support|advanced|اعلانِ درخواستِ جدید (برای تو)|New request alert (for you)|فقط برای مالک؛ وقتی درخواستِ جدیدی ثبت می‌شه|Owner only; when a new request arrives
limit.chat|system|advanced|پیامِ سقفِ روزانه‌ی گفتگوی هر مشتری|Per-customer daily AI limit||
limit.kill|system|advanced|پیامِ خاموش‌بودنِ پاسخ‌گوییِ هوشمند|AI answers switched off||
limit.total|system|advanced|پیامِ سقفِ کلِ روزانه‌ی هوشمند|Daily AI total limit reached||
menu.cart|welcome|advanced|دکمه‌ی منو: سبد خرید|Menu button: Cart||
menu.checkout|welcome|advanced|دکمه‌ی قدیمیِ «نهایی کردن» (فقط سازگاری)|Old “checkout” button (compat only)||
menu.faq|welcome|advanced|دکمه‌ی منو: سؤالات متداول|Menu button: FAQ||
menu.guide|welcome|advanced|دکمه‌ی منو: راهنما|Menu button: Help||
menu.hint|welcome|advanced|یادآوریِ استفاده از منو|Menu reminder||
menu.lead|welcome|advanced|دکمه‌ی منو: ثبتِ درخواست|Menu button: Submit request||
menu.orders|welcome|advanced|دکمه‌ی منو: سفارش‌هام|Menu button: My orders||
menu.orders_old|welcome|advanced|دکمه‌ی قدیمیِ «پیگیری سفارش» (فقط سازگاری)|Old “Track order” button (compat only)||
menu.products|welcome|advanced|دکمه‌ی منو: محصولات|Menu button: Products||
menu.welcome|welcome|basic|پیامِ خوش‌آمدگویی|Welcome message|وقتی مشتری ربات رو اول بار باز می‌کنه یا /start می‌زنه|When a customer first opens the bot or sends /start
ord.cancel|orders|advanced|دکمه‌ی «لغو سفارش»|“Cancel order” button||
ord.cancel_confirm|orders|advanced|سؤالِ تأییدِ لغوِ سفارش|Confirm order cancellation||
ord.cancel_yes|orders|advanced|دکمه‌ی «بله، لغو کن»|“Yes, cancel” button||
ord.cancelled|orders|advanced|پیامِ لغوِ سفارش|Order cancelled||
ord.cannot_cancel|orders|advanced|پیامِ غیرقابل‌لغو بودنِ سفارش|Order cannot be cancelled||
ord.info|orders|advanced|سطرِ اطلاعاتِ سفارش|Order info line||
ord.left|orders|advanced|یادآوریِ زمانِ باقی‌مانده|Time left reminder||
ord.line|orders|advanced|سطرِ هر سفارش در لیست|One order in the list||
ord.none|orders|advanced|پیامِ نداشتنِ سفارش|No orders yet||
ord.not_found|orders|advanced|پیامِ پیدا‌نشدنِ سفارش|Order not found||
ord.not_payable|orders|advanced|پیامِ غیرقابل‌پرداخت بودنِ سفارش|Order cannot be paid||
ord.pay|orders|advanced|دکمه‌ی «پرداخت»|“Pay” button||
ord.status.cancelled|orders|advanced|وضعیتِ «لغو شده»|Status: cancelled||
ord.status.confirmed|orders|advanced|وضعیتِ «تأیید شده»|Status: confirmed||
ord.status.expired|orders|advanced|وضعیتِ «منقضی شده»|Status: expired||
ord.status.paid|orders|advanced|وضعیتِ «پرداخت‌شده»|Status: paid||
ord.status.pending_payment|orders|advanced|وضعیتِ «در انتظارِ پرداخت»|Status: awaiting payment||
ord.status.rejected|orders|advanced|وضعیتِ «رد شده»|Status: rejected||
ord.title|orders|advanced|عنوانِ لیستِ سفارش‌ها|Orders list title||
order.confirmed_head|orders|basic|تیترِ پیامِ تأییدِ سفارش|Order confirmed heading|وقتی تو سفارشِ پرداخت‌شده رو تأیید می‌کنی|When you confirm a paid order
order.confirmed_tail|orders|basic|جمله‌ی پایانیِ تأییدِ سفارش|Order confirmed closing line|انتهای پیامِ تأییدِ سفارش|At the end of the order confirmation
order.expired|orders|advanced|پیامِ پایانِ مهلتِ پرداخت|Payment time expired||
inv.button|orders|advanced|دکمه‌ی «فاکتور» در جزئیاتِ سفارش|“Invoice” button in order details|زیرِ سفارشِ تاییدشده|Under a confirmed order
inv.caption|orders|advanced|عنوانِ فایلِ فاکتور|Invoice file caption|همراهِ فایلِ PDFِ فاکتور|With the invoice PDF
inv.failed|orders|advanced|وقتی فاکتور فرستاده نشد|When the invoice couldn't be sent||
inv.sent|orders|advanced|تأییدِ ارسالِ فاکتور|Invoice sent confirmation||
inv.text_head|orders|advanced|سرِ فاکتورِ متنی|Text invoice header|وقتی PDF ممکن نیست|When a PDF isn't possible
inv.unavailable|orders|advanced|وقتی فاکتور موجود نیست|When no invoice exists||
order.expired_card_hint|orders|advanced|یادآوریِ پرداختِ کارت‌به‌کارت بعد از انقضا|Card hint after expiry||
order.head|orders|advanced|تیترِ خلاصه‌ی سفارش|Order summary heading||
order.item|orders|advanced|سطرِ هر قلم در خلاصه‌ی سفارش|Order summary item line||
order.rejected_head|orders|advanced|تیترِ پیامِ ردِ سفارش|Order rejected heading||
order.rejected_tail|orders|basic|جمله‌ی پایانیِ ردِ سفارش|Order rejected closing line|وقتی تو سفارشی رو رد می‌کنی|When you reject an order
order.total|orders|advanced|سطرِ «جمع کل» سفارش|Order total line||
owner.direct|support|advanced|قالبِ پیامِ شخصیِ مالک به مشتری|Owner's personal message template|وقتی از برنامه برای یک مشتری پیام می‌فرستی|When you message a customer from the app
pay.after_auto|payment|advanced|یادآوریِ تأییدِ خودکار بعد از پرداخت|Auto-confirm reminder||
pay.after_manual|payment|advanced|یادآوریِ تأییدِ دستی بعد از پرداخت|Manual-confirm reminder||
pay.already_paid|payment|advanced|پیامِ «قبلاً پرداخت شده»|Already paid||
pay.amount|payment|advanced|سطرِ مبلغِ پرداخت|Payment amount line||
pay.bale.button|payment|advanced|دکمه‌ی «پرداخت با بله‌پی»|“Pay with Bale Pay” button||
pay.bale.link.manual|payment|advanced|راهنمای دستیِ بله‌پی|Bale Pay manual help||
pay.bale.link.open|payment|advanced|راهنمای بازکردنِ بله‌پی|How to open Bale Pay||
pay.bale.link.title|payment|advanced|عنوانِ پیامِ لینکِ بله‌پی|Bale Pay link title||
pay.bale.native|payment|advanced|پیامِ فاکتورِ بله‌پی (داخل بله)|Bale Pay invoice sent||
pay.card.after|payment|basic|راهنمای بعد از واریزِ کارت‌به‌کارت|After a card-to-card transfer|وقتی مشتری روشِ کارت‌به‌کارت رو انتخاب می‌کنه، زیرِ شماره‌کارت|When a customer picks card-to-card, under the card number
pay.card.amount|payment|advanced|سطرِ مبلغِ دقیقِ کارت‌به‌کارت|Card-to-card exact amount||
pay.card.holder|payment|advanced|سطرِ نامِ صاحبِ کارت|Card holder line||
pay.card.number|payment|advanced|سطرِ شماره‌کارت|Card number line||
pay.card.title|payment|advanced|عنوانِ پرداختِ کارت‌به‌کارت|Card-to-card title||
pay.claim|payment|advanced|دکمه‌ی «پرداخت کردم»|“I've paid” button||
pay.claim_bad|payment|advanced|پیامِ غیرمجازبودنِ «پرداخت کردم»|“I've paid” not allowed||
pay.claim_done|payment|basic|پیامِ بعد از «پرداخت کردم»|After “I've paid”|وقتی مشتری «پرداخت کردم» رو می‌زنه|When a customer taps “I've paid”
pay.disabled|payment|advanced|پیامِ غیرفعال‌بودنِ بله‌پی|Bale Pay disabled||
pay.failed|payment|advanced|پیامِ ناموفق‌بودنِ ساختِ فاکتور|Invoice creation failed||
pay.invoice_sent|payment|advanced|پیامِ فرستاده‌شدنِ فاکتور|Invoice sent||
pay.item_unavailable|payment|advanced|پیامِ ناموجود شدنِ قلمِ سفارش|Item no longer available||
pay.left|payment|advanced|یادآوریِ مهلتِ رزرو|Reservation time left||
pay.link.button|payment|advanced|دکمه‌ی «پرداخت آنلاین»|“Pay online” button||
pay.link.cta|payment|advanced|متنِ لینکِ پرداخت|Payment link text||
pay.link.title|payment|advanced|عنوانِ پیامِ لینکِ پرداخت|Payment link title||
pay.link_invalid|payment|advanced|پیامِ نامعتبریِ لینکِ پرداخت|Payment link invalid||
pay.order_invalid|payment|advanced|پیامِ نامعتبریِ سفارش|Order invalid||
pay.received|payment|basic|پیامِ دریافتِ پرداخت|Payment received|وقتی پرداختِ آنلاین با موفقیت رسید|When an online payment arrives
pay.received_late|payment|advanced|پیامِ پرداختِ دیرهنگام|Late payment received||
pay.received_pending|payment|advanced|پیامِ «منتظرِ بررسیِ فروشنده»|Waiting for seller review||
pay.ref_saved|payment|advanced|پیامِ ثبتِ شماره‌ی پیگیری|Reference number saved||
privacy.ai_disclosure|system|basic|هشدارِ «پاسخ‌ها با هوش مصنوعی‌ست»|“Answers are AI-generated” notice|اولین‌بارِ هر مشتری و بعد از هر ۷ روز|First time for each customer and every 7 days after
privacy.forgotten|system|advanced|پیامِ پاک‌شدنِ اطلاعاتِ مشتری|Customer data deleted||
prod.add|catalog|advanced|دکمه‌ی «افزودن به سبد»|“Add to cart” button||
prod.added|catalog|advanced|پیامِ افزوده‌شدن به سبد|Added to cart||
prod.continue|catalog|advanced|دکمه‌ی «ادامه‌ی خرید»|“Continue shopping” button||
prod.in_cart|catalog|advanced|نشانگرِ «در سبد»|“In cart” indicator||
prod.max|catalog|advanced|سطرِ حداکثرِ تعداد|Maximum quantity line||
prod.stock|catalog|advanced|سطرِ موجودی|Stock line||
prod.type_digital|catalog|advanced|برچسبِ «دیجیتال»|“Digital” label||
prod.type_physical|catalog|advanced|برچسبِ «فیزیکی»|“Physical” label||
prod.update|catalog|advanced|دکمه‌ی «ثبتِ تعدادِ جدید»|“Update quantity” button||
prod.view_cart|catalog|advanced|دکمه‌ی «دیدنِ سبد»|“View cart” button||
ui.back|system|advanced|دکمه‌ی «بازگشت»|“Back” button||
ui.contact_saved|system|advanced|پیامِ ثبتِ شماره‌ی تماس|Contact number saved||
ui.error|system|advanced|پیامِ خطای عمومی|General error||
ui.no_support|system|advanced|پیامِ غیرفعال‌بودنِ پشتیبانیِ انسانی|Human support not available||
ui.price|system|advanced|قالبِ نمایشِ قیمت|Price format||
ui.stale|system|advanced|پیامِ دکمه‌ی قدیمی|Old button message||
"""

# نامِ فارسی/انگلیسی و مثالِ هر متغیر (پیش‌فرض)؛ برای معنی‌های متفاوتِ همان نام، ``_KEY_VARS`` را ببین
_VARS = {
    "amount": ("مبلغ", "Amount", "1,200,000"),
    "code": ("کد", "Code", "A1B2C3"),
    "details": ("جزئیاتِ درخواست", "Request details", "نام: سارا"),
    "error": ("پیامِ خطا", "Error message", "شماره‌ی تلفن معتبر نیست"),
    "holder": ("نامِ صاحبِ کارت", "Card holder", "سارا احمدی"),
    "i": ("شماره‌ی مرحله", "Step number", "2"),
    "id": ("شماره‌ی سفارش", "Order number", "12"),
    "title": ("عنوانِ کانال", "Channel title", "کانال فروشگاه"),
    "label": ("عنوان", "Title", "نام و نام خانوادگی"),
    "minutes": ("تعدادِ دقیقه", "Minutes", "15"),
    "n": ("تعداد", "Count", "3"),
    "name": ("نامِ محصول", "Product name", "هدفون"),
    "number": ("شماره‌ی کارت", "Card number", "6037-99••-••••-1234"),
    "order_id": ("شماره‌ی سفارش", "Order number", "12"),
    "page": ("شماره‌ی صفحه", "Page number", "1"),
    "pages": ("تعدادِ کلِ صفحه‌ها", "Total pages", "3"),
    "platform": ("پیام‌رسان", "Platform", "تلگرام"),
    "prompt": ("متنِ سؤال", "Question", "نام و نام خانوادگی‌ات چیه؟"),
    "qty": ("تعداد", "Quantity", "2"),
    "reason": ("دلیل", "Reason", "ربات بلاک شده"),
    "secret": ("کلید/لایسنس", "License key", "ABCD-1234-EFGH"),
    "status": ("وضعیت", "Status", "⏳ در انتظار پرداخت"),
    "text": ("متنِ پیام", "Message text", "سلام، سفارشتون آماده‌ست"),
    "url": ("لینکِ پرداخت", "Payment link", "https://example.com/pay"),
    "value": ("مقدار", "Value", "09123456789"),
}
_KEY_VARS = {
    "disc.err.locked": {"n": ("تعدادِ دقیقه", "Minutes", "10")},
    "menu.welcome": {"name": ("نامِ مشتری", "Customer name", "سارا")},
    "cart.warn_short": {"n": ("تعدادِ موجود", "Available count", "3")},
    "prod.in_cart": {"n": ("تعدادِ داخلِ سبد", "Count in cart", "2")},
    "prod.max": {"n": ("حداکثرِ تعداد", "Maximum count", "10")},
    "prod.stock": {"n": ("تعدادِ موجود", "Available count", "5")},
    "co.step": {"n": ("تعدادِ کلِ مرحله‌ها", "Total steps", "4")},
    "co.edit": {"label": ("نامِ اطلاعات", "Detail name", "آدرس")},
    "lead.owner": {"label": ("نامِ دکمه/فرم", "Button/form name", "مشاوره‌ی رایگان")},
    "ord.info": {"label": ("عنوانِ اطلاعات", "Detail title", "آدرس"), "value": ("مقدارِ اطلاعات", "Detail value", "شیراز، خیابان زند")},
    "pay.link.button": {"label": ("نامِ درگاه", "Gateway name", "زرین‌پال")},
    "pay.link.title": {"label": ("نامِ درگاه", "Gateway name", "زرین‌پال")},
    "ord.line": {"id": ("شماره‌ی سفارش", "Order number", "12")},
}


# کلیدهایی که «برچسبِ دکمه»‌اند (برای سقفِ طول و هشدارِ کوتاه‌نویسی)
BUTTON_KEYS = frozenset({
    "cart.checkout", "cart.clear", "cart.clear_yes", "cart.code", "cart.code_remove", "cart.fix", "cat.all", "cat.categories", "cat.next", "cat.prev",
    "co.back", "co.cancel", "co.confirm", "co.edit", "co.edit_info", "co.method.bale_pay", "co.method.card_to_card", "co.method.zarinpal",
    "co.resume", "co.share_phone", "co.skip", "faq.back", "guide.more", "handoff.end", "menu.cart", "menu.checkout",
    "menu.faq", "menu.guide", "menu.lead", "menu.orders", "menu.orders_old", "menu.products", "ord.cancel", "ord.cancel_yes",
    "ord.pay", "pay.bale.button", "pay.claim", "pay.link.button", "prod.add", "prod.continue", "prod.update", "prod.view_cart",
    "ui.back", "channel.join", "channel.joined",
})
MAX_DEFAULT_LABEL = 28  # سقفِ طولِ برچسبِ پیش‌فرضِ دکمه (با مقدارِ نمونه)
MAX_LABEL = 40  # سقفِ برچسبِ دکمه‌ای که مالک می‌نویسه (تلگرام/بله بلندتر را می‌برن)


def is_button(key: str) -> bool:
    return key in BUTTON_KEYS


@dataclass(frozen=True)
class Var:
    name: str
    label: str
    example: str


@dataclass(frozen=True)
class TextMeta:
    key: str
    group: str
    level: str
    title: str
    when: str


def _parse_table() -> dict:
    out: dict = {}
    for line in _TABLE.strip().splitlines():
        parts = line.split("|")
        if len(parts) != 7:
            raise ValueError(f"سطرِ متادیتای نامعتبر: {line!r}")
        key, group, level, title_fa, title_en, when_fa, when_en = (p.strip() for p in parts)
        out[key] = (group, level, title_fa, title_en, when_fa, when_en)
    return out


_META = _parse_table()


def groups(lang: str = "fa") -> list:
    """``[(id, عنوان)]`` به‌ترتیبِ نمایش."""
    return [(g[0], g[2] if lang == "en" else g[1]) for g in GROUPS]


def group_title(group: str, lang: str = "fa") -> str:
    g = _GROUP.get(group)
    return (g[2] if lang == "en" else g[1]) if g else group


def meta(key: str, lang: str = "fa") -> TextMeta:
    """متادیتای یک کلید؛ کلیدِ ناشناخته ⇒ ``KeyError``."""
    group, level, title_fa, title_en, when_fa, when_en = _META[key]
    g = _GROUP[group]
    en = lang == "en"
    return TextMeta(key, group, level, title_en if en else title_fa, (when_en or g[4]) if en else (when_fa or g[3]))


def all_keys(level: Optional[str] = None, group: Optional[str] = None) -> list:
    """کلیدهای متن به ترتیبِ گروه‌ها؛ ``level``/``group`` اختیاری برای فیلتر."""
    order = {g[0]: i for i, g in enumerate(GROUPS)}
    keys = [k for k, (g, lv, *_rest) in _META.items() if (level is None or lv == level) and (group is None or g == group)]
    return sorted(keys, key=lambda k: (order[_META[k][0]], k))


# ---------------------------------------------------------------- متغیرها ----

def vars_for(key: str, lang: str = "fa") -> list:
    """متغیرهای مجازِ کلید به ترتیبِ اولین ظهور در متنِ پیش‌فرضِ فارسی، با نامِ فارسی/انگلیسی و مثال."""
    template = shop_texts.default(key, "fa")
    seen: list = []
    for name in shop_texts._fields(template) + shop_texts._fields(shop_texts.default(key, "en")):
        if name not in seen:
            seen.append(name)
    out = []
    for name in seen:
        fa, en, example = _KEY_VARS.get(key, {}).get(name) or _VARS[name]
        out.append(Var(name, en if lang == "en" else fa, example))
    return out


def sample_values(key: str) -> dict:
    return {v.name: v.example for v in vars_for(key)}


def to_display(key: str, text: str, lang: str = "fa") -> str:
    """``{order_id}`` ← ``{شماره‌ی سفارش}`` (برای نمایش در کادرِ ویرایش). متغیرِ ناشناخته دست‌نخورده می‌ماند."""
    labels = {v.name: v.label for v in vars_for(key, lang)}
    return re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", lambda m: "{" + labels[m.group(1)] + "}" if m.group(1) in labels else m.group(0), text or "")


def from_display(key: str, text: str, lang: str = "fa") -> str:
    """وارونِ ``to_display``: ``{شماره‌ی سفارش}`` → ``{order_id}``؛ توکنِ ناشناخته دست‌نخورده می‌ماند (اعتبارسنجی ردش می‌کنه)."""
    names = {v.label: v.name for v in vars_for(key, lang)}
    return re.sub(r"\{([^{}]+)\}", lambda m: "{" + names[m.group(1).strip()] + "}" if m.group(1).strip() in names else m.group(0), text or "")


def unknown_tokens(key: str, display_text: str, lang: str = "fa") -> list:
    """توکن‌های داخلِ ``{}`` که متغیرِ مجازِ این پیام نیستن (به‌ترتیب، بدونِ تکرار)."""
    valid = {v.label for v in vars_for(key, lang)} | {v.name for v in vars_for(key, lang)}
    bad: list = []
    for token in re.findall(r"\{([^{}]*)\}", display_text or ""):
        token = token.strip()
        if token not in valid and token not in bad:
            bad.append(token)
    return bad


def friendly_error(key: str, display_text: str, lang: str = "fa") -> str:
    """پیامِ خطای ساده (بدونِ اصطلاحِ فنی) برای متنِ ویرایش‌شده؛ رشته‌ی خالی = مشکلی نیست."""
    bad = unknown_tokens(key, display_text, lang)
    if bad:
        allowed = "، ".join("{" + v.label + "}" for v in vars_for(key, lang)) or ("none" if lang == "en" else "هیچ")
        if lang == "en":
            return f"“{{{bad[0]}}}” can't be used in this message. Use the variable buttons (allowed: {allowed})."
        return f"«{{{bad[0]}}}» توی این پیام قابل‌استفاده نیست. از دکمه‌های «درجِ متغیر» استفاده کن (مجاز: {allowed})."
    stray = re.sub(r"\{[^{}]*\}", "", display_text or "")
    if "{" in stray or "}" in stray:
        return "Unbalanced { } braces." if lang == "en" else "آکولادهای { } جور نیستن؛ متغیرها رو فقط با دکمه‌ها وارد کن."
    if is_button(key):
        rendered = shop_texts._format(from_display(key, display_text, lang), sample_values(key)) or display_text or ""
        if len(rendered.strip()) > MAX_LABEL:
            return f"Button labels must be short (max {MAX_LABEL} characters)." if lang == "en" else f"برچسبِ دکمه باید کوتاه باشه (حداکثر {MAX_LABEL} کاراکتر)."
    return ""


def preview(key: str, display_text: str, lang_ui: str = "fa") -> Optional[str]:
    """متن را با مقدارهای نمونه رندر می‌کنه (همان‌طور که مشتری می‌بینه). نامعتبر ⇒ ``None``."""
    raw = from_display(key, display_text, lang_ui)
    if friendly_error(key, display_text, lang_ui):
        return None
    return shop_texts._format(raw, sample_values(key))
