# PUBLISHING — انتشارِ عمومیِ پروژه · Publishing the project

> **ترتیب پیشنهادی:** ۱) [`TESTING_V1.md`](TESTING_V1.md) رو کامل بگذران ← ۲) آپلود روی GitHub ← ۳) انتشار (Release) ← ۴) معرفی.
> *Order: pass the manual checklist → upload → release → promote. Never promote before step 1.*

## ۱) آپلود با GitHub Desktop
1. `File → Add local repository…` ← پوشه‌ی پروژه (اگه گیت نداره: *Create a repository*). نام پیشنهادی: `smart-business-local`.
2. اگه تاریخچه‌ی commitهای واقعی داری، همون رو نگه دار (برای رزومه ارزش داره).
3. `Publish repository` ← **Public**. توکن، `settings.json`، `secret.key` و `*.db` هرگز نباید وارد repo بشن (`.gitignore` پوشش داده؛ قبل از commit یک‌بار `git status` رو نگاه کن).
4. توی صفحه‌ی repo: **About** (توضیحِ کوتاه) + **Topics**: `telegram-bot`, `bale-bot`, `ai-assistant`, `ecommerce`, `persian`, `farsi`, `flet`, `python`, `open-source`, `offline-first`.
5. اسکرین‌شات‌های واقعی بگیر (صفحه‌ی خانه، تجربه‌ی ربات، پیش‌نمایش، یک گفتگوی دکمه‌ای) و توی `docs/images/` بذار و به README اضافه کن (README الان جای تصویر نداره عمداً).
6. `Settings → Actions → General`: اجازه‌ی اجرای workflowها. `Security`: فعال‌کردنِ Dependabot و Private vulnerability reporting.

## ۲) انتشار (Release)
1. `app/version.py` و `CHANGELOG.md` رو به‌روز کن (الان `1.1.0`).
2. `git tag v1.1.0 && git push origin v1.1.0` (یا از GitHub Desktop: Create tag). workflowِ **Release builds** خودش ویندوز/مک/لینوکس رو می‌سازه و فایل‌ها + `SHA256SUMS.txt` رو به Release اضافه می‌کنه (جزئیات: [`RELEASING.md`](RELEASING.md)).
3. فایل‌های Release رو روی یک ویندوزِ تمیز تست کن (نصب‌کننده، exe تک‌فایل، zipِ قابل‌حمل) — SmartScreen هشدار می‌ده؛ طبیعی‌ه (امضای دیجیتال نداریم).
4. اگه workflow قرمز شد، لاگِ مرحله‌ی قرمز رو بفرست.

### امضای نسخه (برای نصبِ یک‌کلیکیِ کاربران) · Signing a release
نصبِ یک‌کلیکی فقط برای نسخه‌ای کار می‌کنه که فایلِ امضای Ed25519 (`SHA256SUMS.txt.sig`) داشته باشه و با **کلیدِ عمومیِ داخلِ برنامه** بخونه. این نسخه عمداً با `UPDATE_PUBLIC_KEY_B64 = ""` (خالی) تحویل شده؛ **تا کلیدِ خودت را نگذاری هیچ نسخه‌ای امضا/نصبِ خودکار نمی‌شه** و کاربر دستی دانلود می‌کنه (بی‌خطر).
1. یک‌بار، روی کامپیوترِ خودت: `python scripts/make_signing_key.py --passphrase` ← کلیدِ **خصوصی** بیرون از پوشه‌ی پروژه ساخته می‌شه و کلیدِ **عمومی** (یک خطِ `UPDATE_PUBLIC_KEY_B64 = "…"`) چاپ می‌شه.
2. آن خط را در `app/branding.py` بگذار، commit کن و **همان نسخه** را منتشر کن (کاربرانِ نسخه‌های قبلی که کلیدِ خالی دارن این نسخه را فقط دستی می‌گیرن؛ از نسخه‌ی بعد خودکار می‌شه).
3. بعد از هر Release (وقتی workflow تمام شد): `python scripts/sign_release.py v1.1.0` ← فایلِ `SHA256SUMS.txt.sig` ساخته می‌شه؛ در GitHub ← Releases ← Edit ← همان فایل را پیوست کن.
4. **کلیدِ خصوصی را هرگز** در repo، زیپ، چت یا ایمیل نگذار؛ چند نسخه‌ی آفلاین (فلش، مدیرِ رمز) نگه دار. گم شد ⇒ دیگر نمی‌تونی امضا کنی؛ لو رفت ⇒ کلیدِ تازه بساز و نسخه‌ی بعد را دستی منتشر کن. جزئیات: [`RELEASING.md`](RELEASING.md).
*English: the shipped build has an empty `UPDATE_PUBLIC_KEY_B64`, so one-click updates stay off until you run `scripts/make_signing_key.py`, paste the printed public key into `app/branding.py`, release that version and then sign each release with `scripts/sign_release.py`. Never share the private key.*

## ۳) معرفی
- یک پستِ کوتاهِ فارسی + یک GIF/ویدیوی ۳۰ ثانیه‌ای از خریدِ دکمه‌ای (مشتری → پرداخت → تأیید مالک → تحویل).
- جاهای مناسب: گروه‌های توسعه‌دهنده‌های ایرانی، کانال‌های تلگرام/بله مرتبط با فروشگاه‌های آنلاین، Reddit (r/selfhosted، r/Telegram)، Hacker News (Show HN)، Product Hunt.
- صادق باش: «رایگان، متن‌باز، روی سیستمِ خودت؛ جریانِ پول با دکمه، نه AI». هشدارِ «هنوز امضا ندارد» و «قبل از پولِ واقعی تست کن» رو بنویس — اعتماد می‌سازه.
- به Issueها سریع جواب بده؛ برچسبِ `good first issue` برای کارهای کوچک بذار.

## ۴) بعد از انتشار
- نسخه‌ی بعدی (۱.۱): بازخوردِ کاربران + بخشِ «Later» در [`ROADMAP.md`](ROADMAP.md). هر تغییرِ داده → یک مهاجرتِ جدید در `MIGRATIONS` (هرگز اسکیما رو دستی عوض نکن).
- برای نگه‌داریِ طولانی: امضای کد (ویندوز)، notarization (مک)، بررسیِ به‌روزرسانی داخلِ برنامه.
