; نصب‌کننده‌ی ویندوز (Inno Setup 6) — توسط .github/workflows/release.yml ساخته می‌شه:
;   iscc /DAppVersion=1.0.0 installer\SmartBusinessLocal.iss     (از ریشه‌ی پروژه، بعد از «flet pack»)
; نصب برای کاربرِ فعلی انجام می‌شه (بدون نیاز به ادمین). داده‌ی کاربر توی %APPDATA%\SmartBusinessLocal می‌مونه
; و حذفِ برنامه بهش دست نمی‌زنه (پشتیبان‌ها، سفارش‌ها و توکن‌ها سر جاشونن).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{59361F63-0A07-4BF2-9FA0-F6F19AB13709}
AppName=Smart Business Local
AppVersion={#AppVersion}
AppPublisher=Mohammad Mahdi
DefaultDirName={autopf}\SmartBusinessLocal
DefaultGroupName=Smart Business Local
DisableProgramGroupPage=yes
OutputDir=..\release
OutputBaseFilename=SmartBusinessLocal-{#AppVersion}-windows-setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
UninstallDisplayName=Smart Business Local
UninstallDisplayIcon={app}\SmartBusinessLocal.exe
SetupIconFile=..\assets\icons\app.ico
; N14b — نصبِ یک‌کلیکیِ به‌روزرسانی: برنامه با app/core/app_mutex.py این میوتکس را می‌سازه؛ نصب‌کننده می‌فهمه باز است،
; آن را می‌بنده (CloseApplications) و بعد از نصب دوباره باز می‌کنه (RestartApplications). نصبِ بی‌صدا:
; SmartBusinessLocal-<v>-windows-setup.exe /SILENT /SP- /NORESTART /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS
AppMutex=SmartBusinessLocalAppMutex
CloseApplications=yes
RestartApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\SmartBusinessLocal.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Smart Business Local"; Filename: "{app}\SmartBusinessLocal.exe"
Name: "{autodesktop}\Smart Business Local"; Filename: "{app}\SmartBusinessLocal.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SmartBusinessLocal.exe"; Description: "Launch Smart Business Local"; Flags: nowait postinstall skipifsilent
