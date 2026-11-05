# PUBLISHING — انتشارِ عمومیِ پروژه · Publishing the project

> **ترتیب پیشنهادی:** ۱) روی رباتِ واقعیِ خودت یک خریدِ کامل با مبلغِ کم را از اول تا آخر انجام بده (محصول ← سبد ← فرم ← کارت‌به‌کارت/بله‌پی ← آلارمِ رسید ← تأیید ← فاکتور ← تحویل) ← ۲) آپلود روی GitHub ← ۳) انتشار (Release) ← ۴) معرفی.
> *Order: smoke-test a real purchase on your own bot → upload → release → promote. Never promote before step 1.*

## ۱) آپلود با GitHub Desktop
1. `File → Add local repository…` ← پوشه‌ی پروژه (اگه گیت نداره: *Create a repository*). نام پیشنهادی: `smart-business-local`.
2. اگه تاریخچه‌ی commitهای واقعی داری، همون رو نگه دار (برای رزومه ارزش داره).
3. `Publish repository` ← **Public**. توکن، `settings.json`، `secret.key` و `*.db` هرگز نباید وارد repo بشن (`.gitignore` پوشش داده؛ قبل از commit یک‌بار `git status` رو نگاه کن).
4. توی صفحه‌ی repo: **About** (توضیحِ کوتاه) + **Topics**: `telegram-bot`, `local-ai`, `gguf`, `bale-pay`, `ai-assistant`, `ecommerce`, `persian`, `farsi`, `flet`, `python`, `open-source`, `offline-first`.
5. اسکرین‌شات‌های واقعی بگیر (صفحه‌ی خانه، تجربه‌ی ربات، پیش‌نمایش، یک گفتگوی دکمه‌ای) و توی `docs/images/` بذار و به README اضافه کن (README الان جای تصویر نداره عمداً).
6. `Settings → Actions → General`: اجازه‌ی اجرای workflowها. `Security`: فعال‌کردنِ Dependabot و Private vulnerability reporting.

## ۲) انتشار (Release)
1. `app/version.py` و `CHANGELOG.md` رو به‌روز کن (هدف: `1.0.0`) — **قبل از تگ**، چون ورک‌فلو تگ را با `app/version.py` مقایسه می‌کنه و نخواندنش ساخت را متوقف می‌کنه.
2. `git tag -a v1.0.0 -m "v1.0.0" && git push origin v1.0.0` (یا از GitHub Desktop: Create tag). workflowِ **Release builds** روی ویندوز و لینوکس می‌سازه و این فایل‌ها را به Release پیوست می‌کنه:
   `SmartBusinessLocal-1.0.0-windows-setup.exe` · `…-windows.exe` · `…-linux.tar.gz` · `SHA256SUMS.txt`.
   **باینریِ macOS ساخته نمی‌شه** (روی رانرِ آرمِ مک `llama-cpp-python` wheelِ آماده ندارد و بیلد از سورس می‌شکنه)؛ کاربرِ مک با `bash scripts/run-from-source.sh` از سورس اجراش می‌کنه. علت و راه برگرداندنِ بیلدِ مک در [`RELEASING.md`](RELEASING.md) است.
   **نسخه‌ی قابل‌حمل (فلش) وجود ندارد** — هیچ `portable.flag` / `SmartBusinessData/` / zipِ portable نمی‌سازه؛ همه‌ی داده‌ها توی پوشه‌ی استانداردِ سیستم (`%APPDATA%\SmartBusinessLocal` و معادل‌هایش) می‌مونن. (جزئیات: [`RELEASING.md`](RELEASING.md))
3. فایل‌های Release را روی یک ویندوزِ تمیز تست کن (نصب‌کننده و exe تک‌فایل) — SmartScreen هشدار می‌ده؛ طبیعی‌ه (امضای دیجیتال نداریم). روی لینوکس `tar -xzf …` (مجوز اجرا داخلِ tar هست، `chmod` لازم نیست).
4. پیش از معرفی، هشِ فایل‌ها را خودت بررسی کن: `sha256sum -c SHA256SUMS.txt` (لینوکس/مک) یا `Get-FileHash -Algorithm SHA256 <file>` (ویندوز). همین دستور را در متنِ Release هم برای کاربر بنویس.
5. اگه workflow قرمز شد: jobِ قرمز ← stepِ قرمز ← Annotation/Summary ← در صورت نیاز Artifactِ `build-logs-<os>` و انتهای `logs/*.log`. راهنمای «چطور لاگِ شکسته را بخوانیم» در [`RELEASING.md`](RELEASING.md) است (مثلاً پیامِ `fpdf` یعنی بسته‌ی قدیمیِ pyfpdf جایش گرفته و فاکتورهای فارسی می‌شکنن).

### امضای نسخه (برای نصبِ یک‌کلیکیِ کاربران) · Signing a release
نصبِ یک‌کلیکی فقط برای نسخه‌ای کار می‌کنه که فایلِ امضای Ed25519 (`SHA256SUMS.txt.sig`) داشته باشه و با **کلیدِ عمومیِ داخلِ برنامه** بخونه. کلیدِ عمومیِ سازنده از همین نخستین انتشار در `app/branding.py` (`UPDATE_PUBLIC_KEY_B64`) گذاشته شده، پس به‌محضِ امضاکردنِ همین Release، نصبِ خودکار برای کاربران فعال است؛ هر فایلِ بی‌امضا هرگز خودکار نصب نمی‌شود و فقط صفحه‌ی دانلود باز می‌شه.
1. یک‌بار، روی کامپیوترِ خودت: `python scripts/make_signing_key.py --passphrase` ← کلیدِ **خصوصی** بیرون از پوشه‌ی پروژه ساخته می‌شه و کلیدِ **عمومی** (یک خطِ `UPDATE_PUBLIC_KEY_B64 = "…"`) چاپ می‌شه.
2. آن خط را در `app/branding.py` بگذار، commit کن و **همان نسخه** را منتشر کن (اگر کلید عوض شود، کاربرانِ نسخه‌ی قبلی دیگر امضایِ تو را می‌سنجند و باید دستی ارتقا بگیرند).
3. بعد از هر Release (وقتی workflow تمام شد): `python scripts/sign_release.py v1.0.0 --passphrase` ← فایلِ `SHA256SUMS.txt.sig` ساخته می‌شه؛ در GitHub ← Releases ← Edit ← همان فایل را پیوست کن.
4. **کلیدِ خصوصی را هرگز** در repo، زیپ، چت یا ایمیل نگذار؛ چند نسخه‌ی آفلاین (فلش، مدیرِ رمز) نگه دار. گم شد ⇒ دیگر نمی‌تونی امضا کنی؛ لو رفت ⇒ کلیدِ تازه بساز و نسخه‌ی بعد را دستی منتشر کن. جزئیات: [`RELEASING.md`](RELEASING.md).
*English: this first release already ships the author's Ed25519 public key in `app/branding.py`, so as soon as a Release carries `SHA256SUMS.txt.sig` its update installs with one click. To sign: run `scripts/make_signing_key.py --passphrase` once, paste the printed public key into `app/branding.py`, release that version, then after every release run `scripts/sign_release.py <tag> --passphrase` and attach the produced `SHA256SUMS.txt.sig` to the Release. A build with no signature is never auto-installed — the app only opens the download page. Never share the private key.*

## ۳) معرفی
- متنِ معرفی را از روی [`BOT_FEATURES.fa.txt`](BOT_FEATURES.fa.txt) بساز: کلِ فایل را به یک مدلِ AI بده و همان‌جا خواسته‌ات را بنویس (بخشِ ۳۲ فایل یک قالبِ آماده دارد). بخش‌های ۲۴ و ۲۸ آن فایل را حذف نکن — همان‌ها نگهش می‌دارن ادعایِ دروغ (سایتِ فروشگاهی، درگاهِ زرین‌پال، اپ موبایل، حسابداریِ رسمی، آمارِ ساختگی) تولید نکنه.
- یک پستِ کوتاهِ فارسی + یک GIF/ویدیوی ۳۰ ثانیه‌ای از خریدِ دکمه‌ای (مشتری → پرداخت → تأیید مالک → تحویل).
- جاهای مناسب: گروه‌های توسعه‌دهنده‌های ایرانی، کانال‌های تلگرام/بله مرتبط با فروشگاه‌های آنلاین، Reddit (r/selfhosted، r/Telegram)، Hacker News (Show HN)، Product Hunt.
- صادق باش: «رایگان، متن‌باز، روی سیستمِ خودت؛ جریانِ پول با دکمه، نه AI». هشدارِ «هنوز امضا ندارد» و «قبل از پولِ واقعی تست کن» رو بنویس — اعتماد می‌سازه.
- به Issueها سریع جواب بده؛ برچسبِ `good first issue` برای کارهای کوچک بذار.

## ۴) بعد از انتشار
- نسخه‌های بعدی: بازخوردِ کاربران + بخشِ «Later» در [`ROADMAP.md`](ROADMAP.md). عددِ تازه را فقط در `app/version.py` بنویس (تستِ `tests/test_version_consistency.py` نگه می‌دارد badge و CHANGELOG همان را بخوانند). هر تغییرِ داده → یک مهاجرتِ جدید در `MIGRATIONS` (هرگز اسکیما رو دستی عوض نکن).
- برای نگه‌داریِ طولانی: امضای کد (ویندوز)، بررسیِ به‌روزرسانی داخلِ برنامه، و (اگر wheelِ آماده‌ی
  `llama-cpp-python` برای مک پیدا شد) برگرداندنِ بیلدِ macOS به matrix.
- یادت باشه فایلِ مدل (`*.gguf`) و هر داده‌ی کاربری (`receipts/`, `models/`, `settings.json`, `secret.key`, `*.db`) هرگز نباید در مخزن یا در بسته‌ی نصب باشه — `.gitignore` و گامِ «بسته‌بندی» (scripts/package_release.py) هم‌زمان جلوی این کار را می‌گیرن.
