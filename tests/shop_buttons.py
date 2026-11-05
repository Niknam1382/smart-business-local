"""ابزارِ مشترکِ تست‌های سرتاسری: مشتریِ واقعی که فقط با دکمه‌ها (و فرمِ سفارش) خرید می‌کنه.

سبد و سفارش فقط با دکمه‌هاست (AI هیچ‌چیزِ سبد را تغییر نمی‌ده)؛ پس همه‌ی تست‌های پرداخت از همین مسیر شروع می‌شن.
"""

from helpers import wait_until


def send(server, chat, text, needle, since=0):
    server.push_message(chat, text)
    assert wait_until(lambda: any(needle in m for m in server.sent_to(chat)[since:]), timeout=20), (needle, server.sent_to(chat))


def tap(server, chat, data, message_id=None):
    """کلیک روی دکمه (پیش‌فرض: روی آخرین پیامِ ربات)؛ منتظرِ answerCallbackQuery می‌مونه."""
    if message_id is None:
        message_id = (server.last_message(chat) or {}).get("message_id", 1)
    before = len(server.callback_answers)
    cb = server.push_callback_query(chat, data, message_id=message_id)
    assert wait_until(lambda: len(server.callback_answers) > before, timeout=20), (data, server.calls[-6:])
    assert server.callback_answers[-1]["callback_query_id"] == cb
    return cb


def buy(server, chat, pid, qty=1, method="card_to_card", name="مریم احمدی", before_method=None):
    """از «محصولات» تا انتخابِ روشِ پرداخت (``c:pm:<method>``).

    مثلِ مشتریِ واقعی: منوی محصولات ← جزئیات ← افزودن ← نهایی‌کردن ← نام/موبایل/آدرس ← (رد کردنِ کدپستی و توضیحات) ← تأیید ← روش.
    سفارشِ ساخته‌شده را با ``order_of`` پیدا کن."""
    send(server, chat, "🛍 محصولات", "محصولات")
    tap(server, chat, f"c:p:{pid}:-:1", message_id=server.last_message(chat)["message_id"])
    tap(server, chat, f"c:a:{pid}:{qty}:-:1")
    send(server, chat, "✅ نهایی کردن سفارش", "نام")
    send(server, chat, name, "موبایل")
    send(server, chat, "۰۹۱۲۱۲۳۴۵۶۷", "آدرس")
    send(server, chat, "شیراز، خیابان زند، پلاک ۵", "کدپستی")
    tap(server, chat, "c:ck:s")  # رد کردنِ کدپستی
    assert wait_until(lambda: "توضیحات" in server.last_message(chat)["text"] or any("توضیحات" in e["text"] for e in server.edits))
    tap(server, chat, "c:ck:s")  # رد کردنِ توضیحات ← خلاصه
    assert wait_until(lambda: "c:ck:ok" in server.callback_datas(chat))
    tap(server, chat, "c:ck:ok")
    if before_method:
        before_method()  # مثلاً تنظیمِ رفتارِ سرورِ جعلی درست قبل از انتخابِ روش
    tap(server, chat, f"c:pm:{method}")


def order_of(orders, chat, platform=None):
    """آخرین سفارشِ این چت (یا ``None``)."""
    mine = [o for o in orders.list() if o.chat_id == str(chat) and (platform is None or o.platform == platform)]
    return max(mine, key=lambda o: o.id) if mine else None
