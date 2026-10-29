# Building & releasing · ساخت و انتشار

> **Status.** `.github/workflows/release.yml` builds Windows, macOS and Linux on GitHub's real runners. It has
> **not run on GitHub yet** — expect small first-run fixes. Already verified locally: the exact `flet pack`
> command is accepted by `flet-cli 1.0.1` for all three OSes, the packaging script and the portable layout are
> unit-tested (the shipped zip really activates portable mode), and a Linux PyInstaller build of the app was
> smoke-tested. **If an old `.github/workflows/build-windows.yml` still exists in your repository, delete it** —
> `release.yml` replaces it (otherwise both run on every tag).

## English

### Release steps

1. Put the final code on `main` and make sure **Actions → CI** is green.
2. Set the version in `app/version.py` (e.g. `1.0.0`) and update `CHANGELOG.md`.
3. Tag and push (the tag must be exactly `v` + that version; the workflow checks it):

```bash
git tag v1.0.0
git push origin v1.0.0
```

4. **Actions → Release builds** runs on Windows, macOS and Linux: tests (informational), `flet pack`
   (PyInstaller), `scripts/package_release.py`, and — on Windows — the Inno Setup installer. When all jobs
   finish, a **GitHub Release** for the tag gets every file below plus `SHA256SUMS.txt`.
5. Without a tag you can build manually: Actions → Release builds → **Run workflow** (artifacts only, no Release).

### What users download

| File | For |
|---|---|
| `SmartBusinessLocal-<v>-windows-setup.exe` | Windows installer (per-user, no admin; user data stays in `%APPDATA%` on uninstall) — *experimental until first run* |
| `SmartBusinessLocal-<v>-windows.exe` | Windows single file — double-click and run |
| `SmartBusinessLocal-<v>-windows-portable.zip` | USB edition for Windows (data lives next to the app) |
| `SmartBusinessLocal-<v>-macos-portable.zip` | USB edition for macOS (`.app`) — *experimental* |
| `SmartBusinessLocal-<v>-linux-portable.zip` | USB edition for Linux — *experimental* |
| `SHA256SUMS.txt` | checksums of everything above |

**Portable layout.** Each portable zip contains `SmartBusinessLocal-Portable/` with `portable.flag`,
`README-PORTABLE.txt`, `SmartBusinessData/` and one folder per OS (`Windows/`, `macOS/`, `Linux/`). The app
looks up to 5 folders above its executable for `portable.flag` / `SmartBusinessData`, so extracting several
zips into the **same folder** gives one drive that runs on every OS with one shared data folder.

### Local build (any OS)

```bash
pip install -r requirements-dev.txt
flet pack run.py --name SmartBusinessLocal --add-data "assets:assets" \
  --pyinstaller-build-args=--collect-all=llama_cpp -y        # Windows: --add-data "assets;assets"
python scripts/package_release.py --os linux --dist dist --out release   # windows | macos | linux
```

> The PyInstaller argument **must** be written `--pyinstaller-build-args=--collect-all=llama_cpp` (with `=`);
> the space-separated form fails with `unrecognized arguments`.

### Things to know

- **Not code-signed.** Windows SmartScreen shows "unknown publisher" (More info → Run anyway) and some antivirus
  products flag PyInstaller binaries. macOS Gatekeeper: right-click → Open the first time (not notarized).
  Real fix: a code-signing certificate (Windows) / Apple Developer ID + notarization (macOS). Meanwhile publish
  the SHA-256 sums (done automatically).
- **Experimental jobs.** macOS and Linux builds, the Inno Setup installer and the tests inside the release
  workflow are `continue-on-error` — they cannot break the Windows build. Remove the flags once green.
- **Local AI models are not bundled.** Users download them from inside the app (stored in the data folder).
- **`llama-cpp-python`** comes from the prebuilt-CPU-wheel index in `requirements.txt`; `--prefer-binary` makes
  pip pick an older wheel instead of compiling a newer source release. Pin the version if installation fails.
- Windows 10/11 64-bit. `--onefile` starts slowly on first launch (self-extraction); the installer edition and a
  future `--onedir` build avoid that.

### One-click install (N14b) — how it works and what you must do

Active only when **all** hold: the public key is set in `app/branding.py` (`UPDATE_PUBLIC_KEY_B64`), the release is not a draft /
pre-release, it carries `SHA256SUMS.txt` **and** `SHA256SUMS.txt.sig`, and the file for the running install type exists:

| Running as | Asset used | What happens |
|---|---|---|
| Installer edition (`unins000.exe` next to the exe) | `SmartBusinessLocal-<v>-windows-setup.exe` | silent setup (`/SILENT /SP- /NORESTART /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS`), then the app is reopened |
| Single exe | `SmartBusinessLocal-<v>-windows.exe` | the exe is swapped (old one kept as `.old` until the new one survives ~10 s) |
| Portable (`portable.flag`) | `SmartBusinessLocal-<v>-windows-portable.zip` | only `Windows/*` files are swapped; `SmartBusinessData/` and `portable.flag` are never touched |
| macOS / Linux binary | `…-macos-portable.zip` / `…-linux-portable.zip` | experimental: verified download to *Downloads* + instructions, no automatic swap |
| Source / headless / Docker | — | release page only |

Order of events: signature check (before the big download) → download (GitHub hosts only, size-capped) → SHA-256 → unpack →
`backups/before-update-*.zip` (aborts if it fails) → bots stopped → helper started → app exits → helper installs, reopens,
health-checks (non-zero exit within 10 s ⇒ rollback + reopen the old version) → `update_result.json` → one-time notice.
Everything else about a release (naming, `SHA256SUMS.txt`, signing with `scripts/sign_release.py`) is unchanged — **asset names
must keep the `package_release.py` pattern** (a unit test compares them).

### Update notice & signing (1.1)

The app checks GitHub's public *latest release* on start and every 24 h and shows a banner when a newer, non-draft,
non-pre-release version exists (tags containing `-`, e.g. `v1.1.0-alpha.1`, are published as pre-releases and never
announced). One-click installation (a later phase) will only run for a release that carries **`SHA256SUMS.txt`** (made by the
workflow) **and `SHA256SUMS.txt.sig`** (made by you, offline) — the signature is Ed25519, verified with the public key
compiled into `app/branding.py` (`UPDATE_PUBLIC_KEY_B64`).

One-time setup:

```
python scripts/make_signing_key.py --passphrase     # writes the private key OUTSIDE the repo, prints the public key
# paste the printed UPDATE_PUBLIC_KEY_B64 line into app/branding.py, commit, and release that version
```

Per release (≈ 30 s), after the workflow has published the Release:

```
python scripts/sign_release.py v1.2.0               # downloads SHA256SUMS.txt, signs it, writes SHA256SUMS.txt.sig
# GitHub → Releases → v1.2.0 → Edit → attach SHA256SUMS.txt.sig → Update release
```

Rules that keep users safe:
- **Never** commit, zip, chat or e-mail the private key. Keep several offline backups (USB stick, password manager): if it
  is lost you can no longer sign, and users must download the next version by hand. If it leaks, make a new key, change
  `UPDATE_PUBLIC_KEY_B64` and publish the next version manually.
- `sign_release.py` refuses to sign if your key does not match `UPDATE_PUBLIC_KEY_B64` (the app would reject the signature).
- Forgetting to sign is harmless: that version just stays "download manually".

### Next steps

1. First run of the workflow and fixing whatever it reveals.
2. Verify the installer and the macOS/Linux builds on real machines.
3. Code signing / notarization; an in-app "new version available" check.

---

## فارسی

> **وضعیت.** ورک‌فلوی `.github/workflows/release.yml` روی ماشین‌های واقعیِ گیت‌هاب برای ویندوز، مک و لینوکس
> می‌سازه و **هنوز روی GitHub اجرا نشده**؛ ممکنه اولین اجرا نیاز به اصلاحِ کوچک داشته باشه. این‌ها از قبل محلی
> آزمایش شدن: دستورِ دقیقِ `flet pack` با flet-cli ۱.۰.۱ برای هر سه سیستم‌عامل پذیرفته می‌شه، اسکریپتِ
> بسته‌بندی و چیدمانِ Portable تست واحد دارن (zipِ تحویلی واقعاً حالت قابل‌حمل رو فعال می‌کنه) و یه ساختِ
> PyInstaller روی لینوکس smoke-test شده. **اگه فایلِ قدیمیِ `build-windows.yml` هنوز توی مخزنت هست پاکش کن** —
> `release.yml` جاش رو می‌گیره (وگرنه با هر تگ هر دو اجرا می‌شن).

### اعلانِ نسخه‌ی تازه و امضا (۱.۱)

برنامه هنگامِ شروع و هر ۲۴ ساعت «آخرین نسخه»ی GitHub رو می‌پرسه و اگه نسخه‌ی تازه‌تری (غیرِ draft و غیرِ پیش‌انتشار) باشه یک نوار نشون
می‌ده. تگ‌هایی که «-» دارن (مثلِ `v1.1.0-alpha.1`) پیش‌انتشار منتشر می‌شن و هرگز اعلام نمی‌شن. نصبِ یک‌کلیکی (فازِ ۲؛ جزئیات در بخشِ انگلیسیِ «One-click install») فقط برای نسخه‌ای
اجرا می‌شه که **`SHA256SUMS.txt`** (از workflow) و **`SHA256SUMS.txt.sig`** (از تو، آفلاین) داشته باشه؛ امضا Ed25519 است و با کلیدِ عمومیِ
داخلِ `app/branding.py` (`UPDATE_PUBLIC_KEY_B64`) بررسی می‌شه.

یک‌بار:

```
python scripts/make_signing_key.py --passphrase     # کلیدِ خصوصی را بیرون از مخزن می‌نویسه و کلیدِ عمومی را چاپ می‌کنه
# خطِ UPDATE_PUBLIC_KEY_B64 چاپ‌شده را در app/branding.py بگذار، commit کن و همان نسخه را منتشر کن
```

برای هر نسخه (≈ ۳۰ ثانیه)، بعد از اینکه workflow ریلیز را منتشر کرد:

```
python scripts/sign_release.py v1.2.0               # SHA256SUMS.txt را می‌گیره، امضا می‌کنه و SHA256SUMS.txt.sig را می‌نویسه
# GitHub ← Releases ← v1.2.0 ← Edit ← فایلِ SHA256SUMS.txt.sig را پیوست کن ← Update release
```

قاعده‌هایی که کاربرها را امن نگه می‌دارن:
- کلیدِ خصوصی را **هرگز** در گیت/زیپ/چت/ایمیل نذار. چند پشتیبانِ آفلاین بگیر (فلش، مدیرِ رمز): اگه گم بشه دیگه نمی‌تونی امضا کنی و کاربرها
  باید نسخه‌ی بعد را دستی دانلود کنن. اگه لو رفت: کلیدِ تازه بساز، `UPDATE_PUBLIC_KEY_B64` را عوض کن و نسخه‌ی بعد را دستی منتشر کن.
- `sign_release.py` اگه کلیدِ تو با `UPDATE_PUBLIC_KEY_B64` یکی نباشه امضا نمی‌کنه (برنامه امضا را رد می‌کرد).
- فراموش‌کردنِ امضا بی‌خطره: همان نسخه فقط «دانلودِ دستی» می‌مونه.

### مراحل انتشار

۱. کدِ نهایی رو روی `main` بذار و مطمئن شو **Actions ← CI** سبزه.
۲. نسخه رو توی `app/version.py` بنویس (مثلاً `1.0.0`) و `CHANGELOG.md` رو به‌روز کن.
۳. تگ بزن و پوش کن (تگ باید دقیقاً `v` + همون نسخه باشه؛ ورک‌فلو چک می‌کنه):

```bash
git tag v1.0.0
git push origin v1.0.0
```

۴. **Actions ← Release builds** روی ویندوز، مک و لینوکس اجرا می‌شه: تست (اطلاع‌رسانی)، `flet pack`،
   `scripts/package_release.py` و — روی ویندوز — نصب‌کننده‌ی Inno Setup. وقتی همه تموم شدن، یه **Release** برای
   همون تگ ساخته می‌شه که همه‌ی فایل‌های جدولِ بالا + `SHA256SUMS.txt` بهش پیوسته.
۵. بدون تگ هم می‌شه دستی ساخت: Actions ← Release builds ← **Run workflow** (فقط Artifact، بدون Release).

### کاربر چی دانلود می‌کنه؟

| فایل | برای |
|---|---|
| `…-windows-setup.exe` | نصب‌کننده‌ی ویندوز (برای کاربر فعلی، بدون ادمین؛ با حذفِ برنامه داده‌ها می‌مونن) — *تا اولین اجرا آزمایشی* |
| `…-windows.exe` | فایلِ تکیِ ویندوز — دابل‌کلیک و اجرا |
| `…-windows-portable.zip` | نسخه‌ی فلشِ ویندوز (داده‌ها کنارِ برنامه) |
| `…-macos-portable.zip` | نسخه‌ی فلشِ مک — *آزمایشی* |
| `…-linux-portable.zip` | نسخه‌ی فلشِ لینوکس — *آزمایشی* |
| `SHA256SUMS.txt` | چک‌سامِ همه‌ی فایل‌ها |

**چیدمانِ Portable.** هر zipِ قابل‌حمل شاملِ `SmartBusinessLocal-Portable/` با `portable.flag`،
`README-PORTABLE.txt`، `SmartBusinessData/` و یه پوشه برای هر سیستم‌عامله. برنامه تا ۵ پوشه بالاتر از فایلِ
اجرایی‌اش دنبالِ `portable.flag`/`SmartBusinessData` می‌گرده؛ پس چند zip رو توی **یک پوشه** باز کنی، یه فلش
داری که روی هر سیستم‌عاملی با یه پوشه‌ی داده‌ی مشترک اجرا می‌شه.

### نکته‌ها

- **امضای دیجیتال نداره.** ویندوز SmartScreen «ناشناس» نشون می‌ده (More info ← Run anyway) و بعضی آنتی‌ویروس‌ها
  فایل‌های PyInstaller رو مشکوک می‌دونن. مک: بار اول راست‌کلیک ← Open. راه‌حلِ جدی: گواهیِ امضای کد (ویندوز) و
  Apple Developer ID + notarization (مک). فعلاً هشِ SHA-256 خودکار منتشر می‌شه.
- **Jobهای آزمایشی:** ساختِ مک/لینوکس، نصب‌کننده و تست‌های داخلِ ورک‌فلو `continue-on-error`ان؛ نمی‌تونن ساختِ
  ویندوز رو خراب کنن. بعد از سبز شدن، این گزینه‌ها رو بردار.
- **مدل‌های محلیِ هوش مصنوعی داخلِ فایل نیستن:** کاربر از خودِ برنامه دانلود می‌کنه (توی پوشه‌ی داده).
- **`llama-cpp-python`** از ایندکسِ wheelهای آماده‌ی CPU (`requirements.txt`) میاد؛ `--prefer-binary` باعث می‌شه
  به‌جای کامپایل نسخه‌ی تازه‌ی سورس، نسخه‌ی قدیمی‌ترِ دارای wheel نصب بشه. اگه نصب شکست خورد، نسخه رو پین کن.
- ویندوز ۱۰ و ۱۱ (۶۴ بیتی). حالت `--onefile` بار اولِ اجرا کنده؛ نصب‌کننده و ساختِ `--onedir`ِ آینده این رو حل می‌کنن.
