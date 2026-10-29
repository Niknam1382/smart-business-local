"""ابزارِ تستِ فروشگاهِ دکمه‌ای: ShopFlow با فروشگاه‌های واقعی (SQLite موقت) و بدونِ هیچ پلتفرمی."""

import asyncio

from app.core.bot_pipeline import IncomingMessage
from app.core.orders import OrderStore
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

        async def notify(text: str) -> bool:
            self.owner_alerts.append(text)
            return True

        self.hooks = PaymentHooks(notify_owner=notify)
        self.payments = PaymentService(self.orders, self.products, self.settings)
        self.flow = self.new_flow()

    def new_flow(self) -> ShopFlow:
        return ShopFlow(lambda: self.settings, self.products, self.orders, self.payments, self.hooks)

    def say(self, text, chat="1", platform="telegram", **kw):
        return run(self.flow.handle(IncomingMessage(platform, chat, "علی", text, **kw)))

    def tap(self, data, chat="1", platform="telegram", message_id="10"):
        return run(self.flow.handle(IncomingMessage(platform, chat, "علی", "", callback_data=data, callback_id="cb1", message_id=message_id)))


def datas(res) -> list:
    return [b.data for m in res.messages for row in m.rows for b in row if b.data]


def labels(res) -> list:
    return [b.label for m in res.messages for row in m.rows for b in row]


def texts(res) -> str:
    return "\n".join(m.text for m in res.messages if m.text)


def find(res, prefix):
    """اولین callback_data که با prefix شروع می‌شه."""
    return next((d for d in datas(res) if d.startswith(prefix)), None)
