; نصب‌کننده‌ی ویندوز (Inno Setup 6.3+) — توسط .github/workflows/release.yml ساخته می‌شه:
;   ISCC /DAppVersion=1.0.0 installer\SmartBusinessLocal.iss     (از ریشه‌ی پروژه، بعد از «flet pack» و *قبل* از package_release.py)
; The Windows installer is built by release.yml; scripts/package_release.py then picks the produced
; SmartBusinessLocal-<v>-windows-setup.exe up and puts it in SHA256SUMS.txt.
;
; نصب برای کاربرِ فعلی (PrivilegesRequired=lowest) ⇒ بدونِ ادمین، در {localappdata}\Programs.
; Install is per-user, no admin rights required.
;
; نسخه‌ی ۱.۰.۰: «حالتِ قابل‌حمل/فلش» حذف شده؛ هیچ portable.flag و SmartBusinessData ساخته/نصب نمی‌شه.
; No portable/USB edition — no portable.flag, no SmartBusinessData folder.
; داده‌ی کاربر %APPDATA%\SmartBusinessLocal می‌مونه و حذفِ برنامه به آن دست نمی‌زنه
; (پشتیبان‌ها، سفارش‌ها، رسیدها، مدل‌های AI و توکن‌ها سر جاشونن). User data is never touched on uninstall.
;
; ⚠️ این فایل UTF-8 with BOM ذخیره می‌شه: کامپایلرِ Inno Setup بدونِ BOM فایل را با codepageِ
; سیستم (cp1252) می‌خونه و متنِ فارسیِ رشته‌ها خراب می‌شه. / Save as UTF-8 WITH BOM or the Persian strings break.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{59361F63-0A07-4BF2-9FA0-F6F19AB13709}
AppName=Smart Business Local
AppVerName=Smart Business Local {#AppVersion}
AppVersion={#AppVersion}
AppPublisher=Mohammad Mahdi
AppPublisherURL=https://github.com/niknam1382/smart-business-local
AppSupportURL=https://github.com/niknam1382/smart-business-local/issues
AppUpdatesURL=https://github.com/niknam1382/smart-business-local/releases
DefaultDirName={autopf}\SmartBusinessLocal
DefaultGroupName=Smart Business Local
DisableProgramGroupPage=yes
DisableWelcomePage=no
OutputDir=..\release
OutputBaseFilename=SmartBusinessLocal-{#AppVersion}-windows-setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=6.1sp1
WizardStyle=modern
UninstallDisplayName=Smart Business Local
UninstallDisplayIcon={app}\SmartBusinessLocal.exe
SetupIconFile=..\assets\icons\app.ico
LicenseFile=..\LICENSE
VersionInfoVersion={#AppVersion}
VersionInfoProductName=Smart Business Local
; N14b — نصبِ یک‌کلیکیِ به‌روزرسانی: برنامه با app/core/app_mutex.py این میوتکس را می‌سازه؛ نصب‌کننده می‌فهمه باز است،
; آن را می‌بنده (CloseApplications) و بعد از نصب دوباره باز می‌کنه (RestartApplications). نصبِ بی‌صدا / silent install:
; SmartBusinessLocal-<v>-windows-setup.exe /SILENT /SP- /NORESTART /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS
AppMutex=SmartBusinessLocalAppMutex
CloseApplications=yes
RestartApplications=yes

[Tasks]
Name: "desktopicon"; Description: "میان‌برِ دسکتاپ بساز / Create a desktop shortcut"; GroupDescription: "میان‌برها / Shortcuts:"; Flags: unchecked

[Files]
; خروجیِ flet pack (تک‌فایل). اگر ساخت روزی onedir شد، خطِ بعد پوشه را بی‌خطر اضافه می‌کنه.
; The single-file build; the second entry is a no-op until the build ever becomes a folder.
Source: "..\dist\SmartBusinessLocal.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\SmartBusinessLocal\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\Smart Business Local"; Filename: "{app}\SmartBusinessLocal.exe"
Name: "{autoprograms}\حذفِ برنامه / Uninstall Smart Business Local"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Smart Business Local"; Filename: "{app}\SmartBusinessLocal.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SmartBusinessLocal.exe"; Description: "اجرای Smart Business Local / Launch Smart Business Local"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; عمداً خالی است: هیچ فایلِ کاربری پاک نمی‌شه. / Intentionally empty — nothing of the user's data is deleted.

[Code]
// آدرسِ پوشه‌ی داده روی این سیستم (همان منطقِ app/core/paths.py).
// Data folder location, mirroring app/core/paths.py.
function DataDirHint(): String;
begin
  Result := ExpandConstant('{userappdata}\SmartBusinessLocal');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    Log('Smart Business Local installed. Data folder: ' + DataDirHint());
end;

procedure CurUninstallStepChanged(UninstallStep: TUninstallStep);
begin
  if UninstallStep = usPostUninstall then
    MsgBox(
      'برنامه حذف شد، ولی اطلاعاتِ شما دست‌نخورده باقی مانده است:' + #13#10 +
      DataDirHint() + #13#10 +
      ' (تنظیمات، محصولات، سفارش‌ها، رسیدهای پرداخت، پشتیبان‌ها، مدل‌های هوش مصنوعی و کلیدِ رمزنگاری)' + #13#10 +
      'برای پاک‌کردنِ کامل، این پوشه را دستی حذف کنید.' + #13#10 + #13#10 +
      'The app was removed, but your data was kept — nothing of it is deleted by the uninstaller:' + #13#10 +
      DataDirHint() + #13#10 +
      ' (settings, products, orders, payment receipts, backups, AI models and the encryption key)' + #13#10 +
      'Delete that folder manually if you want a clean removal.',
      mbInformation, MB_OK);
end;
