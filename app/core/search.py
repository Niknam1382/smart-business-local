"""جست‌وجوی سراسری (A2): یک کلمه، نتیجه در سه گروه — سفارش‌ها، کالاها، مشتریان.

همه‌ی جست‌وجوها پارامتری‌اند (LIKE با escape) و فقط از دیتابیسِ محلی می‌خوانند؛ هیچ درخواستِ
شبکه‌ای در این مسیر نیست. شمارشِ نتایج هم سقف دارد تا صفحه‌ی روی‌هایِ بزرگ کند نشود.
"""

from __future__ import annotations

from typing import Optional

GROUPS = ("orders", "products", "customers")
MIN_TERM = 1
DEFAULT_LIMIT = 25
MAX_LIMIT = 100


def global_search(term: str, orders=None, products=None, customers=None, limit: int = DEFAULT_LIMIT) -> dict:
    """``{"orders": [...], "products": [...], "customers": [...]}`` — گروه‌هایِ خالی هم می‌آیند
    تا مصرف‌کننده (صفحه یا تست) بدونِ شرط‌هایِ اختیاری کار کند."""
    clean = (term or "").strip()
    out: dict = {group: [] for group in GROUPS}
    if len(clean) < MIN_TERM:
        return out
    cap = max(1, min(int(limit), MAX_LIMIT))
    if orders is not None:
        out["orders"] = orders.search(clean, limit=cap)
    if products is not None:
        out["products"] = products.search(clean, limit=cap)
    if customers is not None:
        out["customers"] = customers.list(search=clean)[:cap]
    return out


def count(result: dict) -> int:
    return sum(len(rows or []) for rows in result.values())


def orders_of(result: dict) -> list:
    return result.get("orders") or []


def describe_order(order, money: str, status_label: str = "") -> str:
    """یک خطِ خوانا برای نتیجه‌ی سفارش: شماره، وضعیت، مبلغ و مشتری.

    ``status_label`` متنِ فارسیِ صفحه است؛ اگر داده نشد نامِ وضعیتِ خام نشان داده می‌شه (هیچ مقدارِ جدیدی ساخته نمی‌شه)."""
    who = (getattr(order, "customer_name", "") or "").strip() or getattr(order, "chat_id", "") or "—"
    bits = [f"#{order.id}", (status_label or "").strip() or getattr(order, "status", ""), money, who]
    return " · ".join(b for b in bits if b)


def describe_product(product, money: str) -> str:
    category = getattr(product, "category", "") or ""
    tail = f" · {category}" if category else ""
    return f"{product.name}{tail} · {money}"


def describe_customer(customer, platform_label: Optional[str] = None) -> str:
    name = (getattr(customer, "display_name", "") or getattr(customer, "name", "") or "").strip() or getattr(customer, "chat_id", "")
    bits = [str(name)]
    if getattr(customer, "orders_count", 0):
        bits.append(f"{customer.orders_count}×")
    if platform_label:
        bits.append(platform_label)
    return " · ".join(bits)
