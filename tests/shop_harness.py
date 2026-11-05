"""ابزارِ تستِ فروشگاهِ دکمه‌ای: ShopFlow با فروشگاه‌های واقعی (SQLite موقت) و بدونِ هیچ پلتفرمی.

نسخه‌ی ۱.۰.۰ دو حالتِ کاری دارد (``app/core/modes.py``): ``advisor`` (مشاوره‌ای، بدونِ دکمه) و
``shop_buttons`` (فروشگاهی). ``business_mode`` همان «store» / «consultant» است؛ ``shop_mode`` و
``faq_support``/``lead_capture`` حذف شده‌اند، پس این Harness هیچ‌کدام از آن‌ها را نمی‌پذیرد."""

import asyncio

from app.core.bot_pipeline import IncomingMessage
from app.core.orders import METHOD_CARD_TO_CARD, OrderStore
from app.core.payments import PaymentHooks, PaymentService
from app.core.products import ProductStore
from app.core.settings import AppSettings
from app.core.shop_flow import ShopFlow


def run(coro):
    return asyncio.run(coro)


class Harness:
    def __init__(self, tmp_path, *, card=True, business_mode="store", **settings_kwargs):
        self.settings = AppSettings(business_mode=business_mode, **settings_kwargs)
        if card:
            self.settings.card_to_card_number = "6037991234567890"
            self.settings.card_to_card_holder_name = "علی رضایی"
        self.products = ProductStore(tmp_path / "products.db")
        self.orders = OrderStore(tmp_path / "orders.db", product_store=self.products)
        self.owner_alerts: list = []
        # هوک‌هایِ پرداختِ ضبط‌شده: آلارمِ «پرداخت/رسید» و ذخیره‌ی پیوستِ مشتری
        self.claims: list = []  # [(order, payload)] ← hooks.payment_claim
        self.saved_attachments: list = []  # [(platform, chat_id, attachment)] ← hooks.attachment_saver
        self.attachment_paths: list = []  # مسیرهایی که نوبت‌به‌نوبت برگردانده می‌شن (خالی = "")

        async def notify(text: str) -> bool:
            self.owner_alerts.append(text)
            return True

        def payment_claim(order, receipt) -> None:
            self.claims.append((order, receipt))

        async def attachment_saver(platform, chat_id, attachment) -> str:
            self.saved_attachments.append((platform, chat_id, attachment))
            return self.attachment_paths.pop(0) if self.attachment_paths else ""

        self.hooks = PaymentHooks(
            notify_owner=notify, payment_claim=payment_claim, attachment_saver=attachment_saver
        )
        self.payments = PaymentService(self.orders, self.products, self.settings)
        self.flow = self.new_flow()

    def new_flow(self) -> ShopFlow:
        return ShopFlow(lambda: self.settings, self.products, self.orders, self.payments, self.hooks)

    def add_product(self, name="کالا 1", price=1000, stock=50, **kw):
        return self.products.add(name, price, stock, **kw)

    def card_order(self, pid=None, qty=1, chat="1", platform="telegram"):
        """سفارشِ کارت‌به‌کارتِ «در انتظار پرداخت» (بدونِ عبور از ویزارد) تا تست‌های رسید سریع بمانن."""
        pid = pid if pid is not None else self.add_product()
        oid = self.orders.create(platform, chat, [(pid, qty)])
        self.orders.set_payment_info(oid, METHOD_CARD_TO_CARD)
        return oid

    def say(self, text, chat="1", platform="telegram", **kw):
        return run(self.flow.handle(IncomingMessage(platform, chat, "علی", text, **kw)))

    def tap(self, data, chat="1", platform="telegram", message_id="10"):
        return run(self.flow.handle(IncomingMessage(platform, chat, "علی", "", callback_data=data, callback_id="cb1", message_id=message_id)))


def datas(res) -> list:
    return [b.data for m in res.messages for row in m.rows for b in row if b.data]


def labels(res) -> list:
    return [b.label for m in res.messages for row in m.rows for b in row]


def menu(res) -> list:
    """کیبوردِ پایدارِ پاسخ (فقط چیزی که مشتری پایینِ چت می‌بیند)."""
    return [row for m in res.messages for row in (m.menu or [])]


def texts(res) -> str:
    return "\n".join(m.text for m in res.messages if m.text)


def find(res, prefix):
    """اولین callback_data که با prefix شروع می‌شه."""
    return next((d for d in datas(res) if d.startswith(prefix)), None)
