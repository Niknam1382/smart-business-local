# مشارکت | Contributing

ممنون که می‌خوای کمک کنی! | Thanks for helping!

## راه‌اندازی | Setup

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-test.txt                    # برای تست | for tests
pip install -r requirements-dev.txt                     # برای اجرا و بسته‌بندی | to run & package
python -m pytest                                        # همه‌ی تست‌ها | all tests
ruff check app tests                                    # lint
python run.py                                           # اجرای برنامه | run the app
```

## قواعد | Ground rules

1. **هر باگ/قابلیت = تست.** تست‌ها روی سرورهای جعلیِ Bot API/زرین‌پال/OpenAI اجرا می‌شن
   (`tests/fake_*.py`)؛ برای تغییرِ پرداخت/سفارش، تستِ سرتاسریِ ربات‌های واقعی روی سرور جعلی بنویس
   (نمونه: `tests/test_commerce_e2e.py`).
2. **پول و موجودی فقط سمتِ برنامه.** مدل زبانی هیچ‌وقت منبعِ حقیقتِ قیمت، موجودی یا تاییدِ پرداخت
   نیست. ایجنتِ پرسش‌وپاسخ (`app/core/qa_agent.py`) فقط‌خواندنی است و **هیچ ابزارِ سبد/سفارش/پرداختی** نباید به AI داده بشه؛ تغییرِ سبد و ثبتِ سفارش فقط با دکمه‌هاست (`shop_flow.py`) و `chat_id` هرگز
   پارامترِ ابزار نشه.
3. **اسرار هیچ‌وقت توی لاگ/خطای UI نیان** (`app/core/redact.py`). توکن‌ها فقط رمزنگاری‌شده ذخیره می‌شن.
4. **پیام‌های کاربر فارسی و محاوره‌ای/خودمونی‌ان** (نه رسمیِ ترجمه‌ای). متن‌ها از `app/i18n.py`
   می‌آن (فارسی + انگلیسی).
5. نسخه‌ی `flet` و `aiogram` عمداً پین شده؛ ارتقا فقط با اجرای کاملِ تست.
6. تغییرِ مهم رو توی `CHANGELOG.md` بنویس.

## ساختار | Layout

نگاهِ کلی: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). راهنمای مالک برای راه‌اندازی و تستِ دستی روی رباتِ واقعی: [`docs/SHOP_SETUP.fa.md`](docs/SHOP_SETUP.fa.md).
