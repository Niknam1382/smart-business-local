# Building & releasing · ساخت و انتشار (نسخه‌ی ۱.۰.۰)

> **Status.** `.github/workflows/release.yml` builds **Windows and Linux** on GitHub's real runners. It has
> run on GitHub: the Windows job (installer + single file) and the Linux job (`tar.gz` + checksums) are
> green. The macOS job was red at *Install Python dependencies* — on the arm64 runner `llama-cpp-python`
> has no ready wheel and must be compiled from source, which failed even with `cmake`/`ninja` installed —
> so **macOS is no longer built**; a Mac user runs the app from source (`scripts/run-from-source.sh`).
> Verified locally (on this working copy): `scripts/package_release.py` and its tests pass on Python 3.12,
> the artefact layout is unit-tested, the checksums step (`sha256sum -c`) was dry-run against a fake
> `dist/`, and the `fpdf2` dependency gate was run both with a healthy env and with a shadowing legacy
> `fpdf` module (it refuses the build). Not verified here: a real `flet pack` build and the Inno Setup
> compile — those only prove out on the runners.
>
> **If an old `.github/workflows/build-windows.yml` still exists in your repository, delete it** —
> `release.yml` replaces it (otherwise both run on every tag).

## What this release does · چه کاری انجام می‌دهد

- **The portable / USB edition is gone** (removed by the product owner). No `portable.flag`, no
  `SmartBusinessData/` folder, no `README-PORTABLE.txt`, no `*-portable.zip`. `app/core/paths.py` has no
  portable helpers anymore; user data lives only in the OS standard folder
  (`%APPDATA%\SmartBusinessLocal`, `~/Library/Application Support/SmartBusinessLocal`,
  `$XDG_DATA_HOME/SmartBusinessLocal`).
- **Zarinpal is deleted** and the AI is **local-only** (llama.cpp + GGUF, downloaded at runtime), so no
  release contains an API key, a payment callback URL or a model file. Bale Pay is a payment gateway; Bale chat is a separate, optional messenger and neither may leak its token into a release asset.
- **No platform is `experimental`.** Windows and Linux each produce a real artefact and each can fail the
  run; fragile spots are called out in comments instead of being silently ignored. macOS produces no
  artefact (see *Status* above) — that is a decision, not a silenced failure.
- **The Inno Setup installer is part of the Windows chain** (no `continue-on-error`): without the
  portable zip there is no fallback delivery for Windows users.
- **A dependency gate runs before the build** and fails loudly if `fpdf` is the legacy pyfpdf package
  (see below) — a real incident where `fpdf 1.7.2` was installed instead of `fpdf2` silently broke every
  Persian PDF invoice with `UnicodeDecodeError: cp1252` inside `add_font`.

## English

### Release steps

1. Put the final code on `main` and make sure **Actions → CI** is green.
2. Set the version in `app/version.py` (e.g. `1.0.0`) and update `CHANGELOG.md`. The workflow's first
   step refuses a tag that does not match `app/version.py`, so bump **before** tagging.
3. Tag and push (the tag must be exactly `v` + that version):

```bash
git tag -a v1.0.0 -m "v1.0.0"
git push origin v1.0.0
```

4. **Actions → Release builds** runs on the three OSes: dependency gate → `flet pack` (PyInstaller) →
   Inno Setup (Windows) → `scripts/package_release.py`. When every job is green a **GitHub Release** is
   created for the tag with all files below plus one combined `SHA256SUMS.txt`.
5. Without a tag you can build manually: Actions → Release builds → **Run workflow** (artifacts only, no
   Release).

### What users download

| File | For |
|---|---|
| `SmartBusinessLocal-<v>-windows-setup.exe` | Windows installer — per-user (`%LOCALAPPDATA%\Programs`), no admin, Start Menu entry, optional desktop shortcut. Uninstall keeps all data. |
| `SmartBusinessLocal-<v>-windows.exe` | Windows single file — double-click and run (no installer, no uninstall entry). |
| `SmartBusinessLocal-<v>-linux.tar.gz` | Linux — contains the single binary `SmartBusinessLocal`. |
| `SHA256SUMS.txt` | checksums of everything above (`hash␣␣name`, usable with `sha256sum -c`). |

`scripts/package_release.py` writes them; it also *collects* the installer (Inno Setup writes it straight
into `release/`) so it lands in the checksum list, and it refuses to package anything that looks like
user data or a model: `receipts/`, `models/`, `product_photos/`, `backups/`, `invoices/`, `exports/`,
`logs/`, `*.db*`, `settings.json`, `secret.key`, `*.log`, `heartbeat.json` and **any `.gguf`** — models
must never ship inside an installer; the app downloads them at runtime.

### Installing per platform · نصب روی هر سیستم‌عامل

**Windows.** Run `…-windows-setup.exe`. SmartScreen says "unknown publisher" → *More info → Run anyway*
(there is no code-signing certificate yet). Silent/one-click form used by the in-app updater:
`…-windows-setup.exe /SILENT /SP- /NORESTART /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS`.

**macOS — no binary.** The release has no Mac artefact: on GitHub's arm64 macOS runner
`llama-cpp-python` (the local model runtime) has no ready wheel and its source build fails. On a Mac,
run the app from source: `bash scripts/run-from-source.sh` (creates a venv, installs requirements,
starts the window) — the app itself, the shop, payments and invoices work there; only the packaged
`.app` does not exist. To ship a Mac build later, pin a `llama-cpp-python` version that publishes a
`macosx arm64` wheel and add the `macos` row back to the matrix in `release.yml`.

**Linux.**

```bash
sha256sum -c SHA256SUMS.txt                       # check the download first
tar -xzf SmartBusinessLocal-<v>-linux.tar.gz      # tar keeps the +x bit (no chmod needed)
./SmartBusinessLocal                              # or: nohup ./SmartBusinessLocal &
```

tar.gz (not zip) is used deliberately: in tar the permission and symlink information is part of the
format and every extractor restores it, while zip stores it only in an `external_attr` field that
non-GNU extractors (`python -m zipfile -e`, some GUI archive managers) silently drop — the user would get
a 0644 binary and have to `chmod +x`. Flet's Linux desktop is a GTK/WebKitGTK webview, so the user's
machine needs these libraries (they are installed in the CI job to prove the binary starts):
`libgtk-3-0 libwebkit2gtk-4.1-0 libjavascriptcoregtk-4.1-0 libsoup-3.0-0 libayatana-appindicator3-1
librsvg2-2 libgomp1` (`libgomp1` is also required to import `llama_cpp`; `fontconfig` arrives with GTK).
On Debian/Ubuntu: `sudo apt install libgtk-3-0 libwebkit2gtk-4.1-0 libsoup-3.0-0 libgomp1`. Fedora:
`sudo dnf install gtk3 webkit2gtk4.1 libsoup3 libgomp`. Persian fonts are not required — Vazirmatn ships
inside the bundle.

### Verifying a download · بررسیِ سلامتِ فایل

`SHA256SUMS.txt` lists `hash␣␣filename` for every asset in the release.

```bash
# Linux
sha256sum -c SHA256SUMS.txt
# macOS
shasum -a 256 -c SHA256SUMS.txt
```

```powershell
# Windows (PowerShell) — compare the printed hash with SHA256SUMS.txt
Get-FileHash -Algorithm SHA256 .\SmartBusinessLocal-1.0.0-windows-setup.exe
```

Hashes are published in the same GitHub Release, so they prove *integrity* (a corrupt or tampered
download), not *authorship* — for that see the signing section below.

### Local build (any OS)

```bash
pip install -r requirements-dev.txt
flet pack run.py --name SmartBusinessLocal --add-data "assets:assets" \
  --pyinstaller-build-args=--collect-all=llama_cpp -y        # Windows: --add-data "assets;assets"
# Windows only, before packaging: installer/SmartBusinessLocal.iss → release/
iscc /DAppVersion=1.0.0 installer\SmartBusinessLocal.iss
python scripts/package_release.py --os linux --dist dist --out release    # windows | macos | linux
```

> The PyInstaller argument **must** be written `--pyinstaller-build-args=--collect-all=llama_cpp`
> (with `=`); the space-separated form fails with `unrecognized arguments`. `--collect-all=llama_cpp` is
> required because `llama_cpp` loads native `.pyd`/`.so` files that PyInstaller does not see from the
> imports alone.

### How to read a failed build log · چطور لاگِ شکسته را بخوانیم

Every sensitive step pipes its output into `logs/<step>.log` and, on failure, prints the tail of that log
as a GitHub **annotation** and into the run **Summary** (via `scripts/ci_fail_report.sh`) — this exists
because one release once failed with only `exit code 1` and no cause. Order of reading:

1. Open the run → the red job (Windows/Linux) → the red **step**.
2. Read the annotation/Summary first: it is the last 80 lines of the real log.
3. Still unclear? Download **`build-logs-<os>`** from the run's *Artifacts* list
   (`logs/install.log`, `logs/system-deps.log`, `logs/build.log`, `logs/installer.log`,
   `logs/package.log`; retained 14 days) and read the **bottom** of the matching file.

Common failures and what they actually mean:

| Symptom | Cause / fix |
|---|---|
| Step *Dependency gate* red, mentions `pyfpdf` / `fpdf.__version__: 1.7.2` | The legacy `fpdf` package shadows `fpdf2`. On that machine: `python -m pip uninstall -y fpdf` then `python -m pip install --force-reinstall "fpdf2>=2.8.5"`. Never add `fpdf` to any requirements file. |
| `UnicodeDecodeError: cp1252` inside `add_font` (only at runtime) | Same root cause as above — it is why the gate exists. |
| `unrecognized arguments: --collect-all=llama_cpp` | The `=` form of `--pyinstaller-build-args=` was dropped. |
| `ModuleNotFoundError: llama_cpp` in the built app | `--collect-all=llama_cpp` missing, or the wheel index in `requirements.txt` did not provide a wheel for that Python/architecture. |
| `fatal: No files found with "...\dist\SmartBusinessLocal.exe"` | The `flet pack` step failed earlier — read `logs/build.log`, not this one. |
| `خروجیِ ساخت برای linux پیدا نشد؛ داخلِ dist: …` | Packaging cannot see the build output; the message lists what is actually in `dist/`. |
| `❌ در «dist» فایلِ داده‌ی کاربر/مدل هست …` | A `receipts/`, `models/`, `*.gguf`, `*.db`, `settings.json` or `secret.key` reached the build tree. Delete it; never ship user data or models. |
| Inno Setup step red: `ISCC.exe not found` | `choco install innosetup` failed. The workflow now searches every `Inno Setup *` folder and `PATH`, so a runner that moved Inno 6 → Inno 7 is no longer a build failure; read `logs/installer.log`. |
| macOS build (removed) | The macOS job failed at *Install Python dependencies*: `llama-cpp-python` has only an sdist and the arm64 runner cannot build it (three `ERROR: Exception:` lines in `logs/install.log`). It is out of the matrix until a wheel exists — do not re-add it without proof. |
| CI red with only `exit code 2` and no reason | Fixed: the test step now tees to `logs/pytest.log`, prints the tail as an annotation and uploads the log artifact — read `pytest-log` in the run's Artifacts. |
| Linux: `error while loading shared libraries: libwebkit2gtk-4.1.so.0` | The system-packages step did not install (or the package names changed); fix the apt list in the workflow. |

### Things to know

- **Not code-signed.** Windows SmartScreen shows "unknown publisher"; some antivirus products flag
  PyInstaller binaries. Real fix: a code-signing certificate (Windows). Meanwhile the
  SHA-256 sums are published automatically.
- **Local AI models are not bundled** and are refused by the packager. Users download them inside the
  app into the data folder (`models/`); a 2–6 GB disk is expected.
- **`llama-cpp-python`** comes from the prebuilt-CPU-wheel index in `requirements.txt` /
  `requirements-headless.txt`; `--prefer-binary` makes pip pick an older wheel instead of compiling a
  newer source release. Pin the version if installation fails.
- **Headless/Docker is not part of a Release.** `docker compose up -d` builds it from
  `requirements-headless.txt`; see the volume note in `Dockerfile` / `docker-compose.yml` (models need
  space, and no callback port/keys are needed any more).
- Windows 10/11 64-bit. `--onefile` starts slowly on first launch (self-extraction); a future `--onedir`
  build (and the installer that already tolerates it) avoids that.

### Update notice, one-click install & signing

The app checks GitHub's public *latest release* on start and every 24 h and shows a banner when a newer,
non-draft, non-pre-release version exists (tags containing `-`, e.g. `v1.0.0-alpha.1`, are published as
pre-releases and never announced). One-click installation runs only when **all** of these hold: the
public key is set in `app/branding.py` (`UPDATE_PUBLIC_KEY_B64` — **it is set in this release**, so a
signed Release installs with one click and an unsigned one only opens the download page), the release
carries `SHA256SUMS.txt` **and**
`SHA256SUMS.txt.sig`, and the asset for the running install type exists:

| Running as | Asset used | What happens |
|---|---|---|
| Installer edition (`unins000.exe` next to the exe) | `SmartBusinessLocal-<v>-windows-setup.exe` | silent setup (`/SILENT /SP- /NORESTART /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS`), then the app is reopened |
| Single exe | `SmartBusinessLocal-<v>-windows.exe` | the exe is swapped (old one kept as `.old` until the new one survives ~10 s) |
| Linux (and a Mac running from source) | — | manual: the app opens the release page / downloads the file and shows the instructions above |
| Source / headless / Docker | — | release page only |

Order of events (Windows): signature check (before the big download) → download (GitHub only, size-capped)
→ SHA-256 → unpack → `backups/before-update-*.zip` (aborts if it fails) → bots stopped → helper started →
app exits → helper installs, reopens, health-checks (non-zero exit within 10 s ⇒ rollback) →
`update_result.json` → one-time notice. **Asset names must keep the `package_release.py` pattern** —
a unit test compares them.

One-time signing setup:

```
python scripts/make_signing_key.py --passphrase   # writes the private key OUTSIDE the repo, prints the public key
# paste the printed UPDATE_PUBLIC_KEY_B64 line into app/branding.py, commit, and release that version
```

Per release (≈ 30 s), after the workflow published the Release:

```
python scripts/sign_release.py v1.0.0   # downloads SHA256SUMS.txt, signs it, writes SHA256SUMS.txt.sig
# add --passphrase ONLY if the key file itself is encrypted; this project's key is not, and
# passing the flag then makes signing fail with "کلید خوانده نشد (رمز اشتباه است یا فایل خراب)".
# GitHub → Releases → v1.0.0 → Edit → attach SHA256SUMS.txt.sig → Update release
```

Rules that keep users safe:
- **Never** commit, zip, chat or e-mail the private key. Keep several offline backups (USB stick, password
  manager): if it is lost you can no longer sign and users must download the next version by hand. If it
  leaks, make a new key, change `UPDATE_PUBLIC_KEY_B64` and publish the next version manually.
- `sign_release.py` refuses to sign if your key does not match `UPDATE_PUBLIC_KEY_B64`.
- Forgetting to sign is harmless: that version just stays "download manually".

### Next steps

1. Fix whatever the first real runs reveal (Linux webview libraries were the likely spot; the Windows
   chain now builds).
2. Verify the installer and the Linux build on real machines; publish the Release once both jobs are green.
3. Code signing (a Windows Authenticode certificate) so SmartScreen stops warning. Update signing
   (`UPDATE_PUBLIC_KEY_B64`) is already in the app, so one-click updates go live as soon as a Release
   is signed with `scripts/sign_release.py`.
4. One-click install needs the per-release signature (see above); without it the app only opens the
   download page. The updater knows only
   two install kinds on Windows (`windows_setup`, `windows_exe`); Linux gets a verified
   download of the new archive instead of an in-app install. Re-adding macOS to the matrix needs a
   `llama-cpp-python` wheel for that platform first.

---

## فارسی

### مراحل انتشار

۱. کدِ نهایی روی `main` و **Actions ← CI** سبز.
۲. نسخه را در `app/version.py` بنویس (مثلاً `1.0.0`) و `CHANGELOG.md` را به‌روز کن — **قبل از تگ**، چون
   اولین گامِ ورک‌فلو تگ را با `app/version.py` مقایسه می‌کنه و نخواندنش را رد می‌کنه.
۳. `git tag -a v1.0.0 -m "v1.0.0" && git push origin v1.0.0`.
۴. **Actions ← Release builds** روی هر سه سیستم‌عامل: دروازه‌ی وابستگی ← `flet pack` ← Inno Setup
   (ویندوز) ← `scripts/package_release.py`. وقتی همه سبز شدن، Release ساخته می‌شه و همه‌ی فایل‌ها به‌علاوه‌ی
   یک `SHA256SUMS.txt`ِ جامع پیوست می‌شن.
۵. بدون تگ: Actions ← Release builds ← **Run workflow** (فقط Artifact، بدون Release).

### کاربر چی دانلود می‌کنه؟

| فایل | برای |
|---|---|
| `…-windows-setup.exe` | نصب‌کننده‌ی ویندوز: برای کاربرِ فعلی، بدون ادمین، میان‌بر منوی شروع؛ با حذفِ برنامه هیچ داده‌ای پاک نمی‌شه |
| `…-windows.exe` | فایلِ تکیِ ویندوز — دابل‌کلیک و اجرا |
| `…-linux.tar.gz` | فایلِ اجراییِ لینوکس (tar چون مجوزها و symlink را بومی نگه می‌داره؛ لازم به `chmod`) |
| `SHA256SUMS.txt` | چک‌سامِ همه‌ی فایل‌ها |

**نسخه‌ی قابل‌حمل حذف شده:** دیگر `portable.flag`، `SmartBusinessData/` یا `README-PORTABLE.txt` هیچ‌جا
نمی‌سازه. داده‌ی کاربر فقط توی پوشه‌ی استانداردِ سیستمه.

**تحویلِ لینوکس چرا tar.gz است؟** در tar مجوز و symlink بخشی از خودِ قالب‌اند و هر ابزارِ باز‌کردنی آن‌ها
را برمی‌گردونه؛ در zip این اطلاعات فقط چند bit در `external_attr` است که ابزارهای غیرِ GNU (مثل
`python -m zipfile -e` یا بعضی نرم‌افزارهای فشرده) نادیده می‌گیرنش و فایلِ اجرایی با مجوز ۰۶۴۴ به کاربر
می‌رسه. برای مک باینری ساخته نمی‌شه (بالای همین‌جا علتش نوشته شده)؛ کاربرِ مک با
`bash scripts/run-from-source.sh` برنامه را از سورس بالا می‌آره.

### نکته‌ها

- **امضای دیجیتال نداره.** ویندوز SmartScreen «ناشناس» نشون می‌ده (More info ← Run anyway) و بعضی
  آنتی‌ویروس‌ها فایل‌های PyInstaller را مشکوک می‌دونن.
  راه‌حلِ جدی: گواهیِ امضای کد (ویندوز).
- **مدل‌های هوش مصنوعی داخلِ بسته نیستن** و اسکریپتِ بسته‌بندی هر `.gguf` را رد می‌کنه؛ کاربر از خودِ
  برنامه دانلود می‌کنه (توی `models/` در پوشه‌ی داده؛ ۲ تا ۶+ گیگ جا لازم است).
- **هیچ jobی experimental نیست.** شکستِ مک یا لینوکس ساخت را قرمز می‌کنه؛ نقاطِ شکننده در کامنت‌ها
  نوشته شدن تا کسی وسوسه نشه با `continue-on-error` آن‌ها را خاموش کنه.
- **`llama-cpp-python`** از ایندکسِ wheelهای آماده‌ی CPU میاد؛ `--prefer-binary` باعث می‌شه به‌جای
  کامپایلِ نسخه‌ی تازه، wheelِ قدیمی‌تر نصب بشه. اگه نصب شکست خورد، نسخه رو پین کن.
- ویندوز ۱۰ و ۱۱ (۶۴ بیتی). حالت `--onefile` بار اول کنده.

### چطور لاگِ شکسته را بخوانیم

هر گامِ حساس خروجی‌اش را در `logs/*.log` می‌نویسه و موقعِ شکست، ته‌ی لاگ را به‌صورت **Annotation** و در
**Summary** نمایش می‌ده (`scripts/ci_fail_report.sh`) — این قابلیت بعد از نسخه‌ای اضافه شد که با فقط
«exit code 1» شکست و هیچ علّی دیدنی نبود. ترتیبِ خواندن: jobِ قرمز ← stepِ قرمز ← Annotation/Summary ←
در صورت نیاز دانلودِ Artifactِ `build-logs-<os>` و خواندنِ انتهای فایلِ مربوط
(`install.log` · `system-deps.log` · `build.log` · `installer.log` · `package.log`).
پیامِ «Dependency gate» که گفت `fpdf` نسخه‌ی ۱.۷.۲ است یعنی بسته‌ی قدیمیِ pyfpdf جایش را گرفته و
فاکتورهای فارسی می‌شکنن: `pip uninstall -y fpdf` بعد `pip install --force-reinstall "fpdf2>=2.8.5"`.

### امضا و به‌روزرسانی

مقدارِ `UPDATE_PUBLIC_KEY_B64` در `app/branding.py` پر است، پس هر Releaseای که
`SHA256SUMS.txt.sig` داشته باشه با یک کلیک نصب می‌شه (پشتیبانِ خودکار + بازگشتِ خودکار اگر بالا نیاد)؛
Releaseِ بی‌امضا فقط صفحه‌ی دانلود را باز می‌کنه.
یک‌بار (فقط یک‌بار): `python scripts/make_signing_key.py --passphrase` (کلیدِ خصوصی بیرون از مخزن
ساخته می‌شه؛ کلیدِ عمومی چاپ می‌شه) ← آن خط را در `app/branding.py` بگذار و commit کن ← بعد از هر Release:
`python scripts/sign_release.py v1.0.0` (کلیدِ این ماشین بی‌رمز است؛ اگر بعداً کلیدِ رمزدار ساختی
فقط همان‌وقت `--passphrase` اضافه کن، وگرنه امضا با «کلید خوانده نشد» می‌شکنه) ← فایلِ
`SHA256SUMS.txt.sig` را به Release پیوست کن.
کلیدِ خصوصی را هرگز در گیت/زیپ/چت/ایمیل نذار و چند پشتیبانِ آفلاین ازش داشته باش؛ لو رفت ⇒ کلیدِ تازه +
انتشارِ دستیِ نسخه‌ی بعد. فراموش‌کردنِ امضا بی‌خطره: همان نسخه فقط «دانلودِ دستی» می‌مونه.
