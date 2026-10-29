"""کارتِ «داده و ایمنی» توی تنظیمات: محلِ داده/حالت قابل‌حمل، پشتیبان‌گیری، بازگردانی،
فایلِ تشخیصی و بازنشانیِ کارخانه (دکمه‌ی ریست).

اصول:
- هر کارِ فایلی با ``page.run_thread`` انجام می‌شه (رابط یخ نزنه)؛ ربات‌ها قبل از بازگردانی/
  بازنشانی خاموش می‌شن، چون دیتابیس‌ها زیر دستِ ترد ربات‌ان.
- بازنشانی دو قفل داره: باید کلمه‌ی «ریست/RESET» تایپ بشه تا دکمه فعال بشه، و پیش‌فرض
  قبلش یه پشتیبانِ کامل گرفته می‌شه — پس اشتباهِ کاربر برگشت‌پذیره.
- بازگردانی همیشه قبلش از وضعیتِ فعلی یه پشتیبانِ ایمنی می‌سازه (backup.restore_backup).
- بعد از موفقیت ``on_data_changed(kind, message)`` صدا زده می‌شه: main.py تنظیمات رو از
  دیسک دوباره می‌خونه و یا به معرفی برمی‌گرده (reset) یا همین صفحه رو با پیام نشون می‌ده.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import flet as ft

from app import theme
from app.core import backup, paths
from app.core import settings as settings_module
from app.core.backup import BackupError
from app.i18n import t
from app.screens import common as common_screen
from app.screens.common import card, get_or_create_file_picker, section_header
from app.version import __version__

RESET_WORDS = ("reset", "ریست")


def build(
    page: ft.Page,
    lang: str,
    state,
    on_data_changed: Optional[Callable[[str, str], None]] = None,
    manager=None,
    data_dir: Optional[Path] = None,
    notice: str = "",
) -> ft.Control:
    data = Path(data_dir) if data_dir is not None else paths.get_app_data_dir()
    mode = paths.data_dir_mode()

    result = ft.Text(notice, key="data_result", size=12.5, selectable=True, color=theme.SUCCESS if notice else None)

    def say(message: str, ok: bool = True) -> None:
        result.value = message
        result.color = theme.SUCCESS if ok else theme.DANGER
        page.update()

    def working() -> None:
        result.value = t("data.working", lang)
        result.color = theme.text_secondary(page)
        page.update()

    def fail(exc: Exception) -> None:
        say(str(exc) if isinstance(exc, BackupError) else t("data.error", lang, error=str(exc)[:160]), False)

    def stop_bots() -> None:
        if manager is not None and manager.is_running():
            manager.stop(timeout=10)

    def finish(kind: str, message: str) -> None:
        if on_data_changed is not None:
            on_data_changed(kind, message)
        else:
            say(message)

    # ------------------------------------------------------------ محل داده
    def on_open_folder(e=None) -> None:
        if not common_screen.open_folder(data):
            say(t("data.open_folder_failed", lang), False)

    location = ft.Column(
        spacing=4,
        controls=[
            ft.Text(t("data.location", lang), size=13, color=theme.text_secondary(page)),
            ft.Text(str(data), key="data_path", size=12.5, selectable=True),
            ft.Text(t(f"data.mode.{mode}", lang), key="data_mode", size=12, color=theme.text_secondary(page)),
            ft.Text(f"{t('data.version', lang)}: {__version__}", size=12, color=theme.text_secondary(page)),
            ft.OutlinedButton(key="data_open_folder", content=t("data.open_folder", lang), icon=ft.Icons.FOLDER_OPEN_ROUNDED, on_click=on_open_folder),
        ],
    )

    # ------------------------------------------------------------ پشتیبان
    secrets_switch = ft.Switch(key="backup_secrets", label=t("data.backup.secrets", lang), value=True)

    def on_backup(e=None) -> None:
        working()

        def work() -> None:
            try:
                path = backup.create_backup(include_secrets=bool(secrets_switch.value), data_dir=data)
            except Exception as exc:  # noqa: BLE001
                fail(exc)
                return
            refresh_backups()
            say(t("data.backup.done", lang, path=str(path)))

        page.run_thread(work)

    backup_button = ft.Button(
        key="backup_now",
        content=t("data.backup.now", lang),
        icon=ft.Icons.SAVE_ALT_ROUNDED,
        bgcolor=theme.PRIMARY,
        color="#FFFFFF",
        on_click=on_backup,
    )

    # ------------------------------------------------------------ بازگردانی
    restore_dropdown = ft.Dropdown(
        key="restore_pick",
        label=t("data.restore.pick", lang),
        options=[],
        border_radius=10,
        width=380,
    )

    def refresh_backups() -> None:
        files = backup.list_backups(data)
        restore_dropdown.options = [ft.DropdownOption(key=str(p), text=p.name) for p in files]
        if restore_dropdown.value not in {str(p) for p in files}:
            restore_dropdown.value = None

    refresh_backups()

    def do_restore(path: Path) -> None:
        working()

        def work() -> None:
            try:
                stop_bots()
                safety = backup.restore_backup(path, data_dir=data)
                settings_module.reload_into(state)
            except Exception as exc:  # noqa: BLE001
                fail(exc)
                return
            refresh_backups()
            finish("restore", t("data.restore.done", lang, safety=str(safety) if safety else "—"))

        page.run_thread(work)

    def on_restore(e=None) -> None:
        if not restore_dropdown.value:
            say(t("data.restore.need_pick", lang), False)
            return
        do_restore(Path(restore_dropdown.value))

    async def on_restore_file(e=None) -> None:
        picker = get_or_create_file_picker(page)
        try:
            picked = await picker.pick_files(
                dialog_title=t("data.restore.file", lang),
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["zip"],
                allow_multiple=False,
            )
        except ft.FletUnsupportedPlatformException:
            picked = None  # حالت وب/تست — انتخاب فایل فقط توی دسکتاپ واقعی هست
        if picked:
            do_restore(Path(picked[0].path))

    restore_button = ft.OutlinedButton(
        key="restore_btn",
        content=t("data.restore.btn", lang),
        icon=ft.Icons.SETTINGS_BACKUP_RESTORE_ROUNDED,
        on_click=on_restore,
    )
    restore_file_button = ft.TextButton(
        key="restore_file",
        content=t("data.restore.file", lang),
        icon=ft.Icons.FOLDER_OPEN_ROUNDED,
        on_click=on_restore_file,
    )

    # ------------------------------------------------------------ تشخیص
    def on_diagnostics(e=None) -> None:
        working()

        def work() -> None:
            try:
                path = backup.export_diagnostics(data_dir=data)
            except Exception as exc:  # noqa: BLE001
                fail(exc)
                return
            say(t("data.diag.done", lang, path=str(path)))

        page.run_thread(work)

    diagnostics_button = ft.OutlinedButton(
        key="diagnostics_btn",
        content=t("data.diag.btn", lang),
        icon=ft.Icons.BUG_REPORT_OUTLINED,
        on_click=on_diagnostics,
    )

    # ------------------------------------------------------------ بازنشانی
    reset_backup_switch = ft.Switch(key="reset_backup", label=t("data.reset.backup", lang), value=True)
    reset_models_switch = ft.Switch(key="reset_models", label=t("data.reset.models", lang), value=False)

    def confirmed() -> bool:
        return (reset_confirm.value or "").strip().lower() in RESET_WORDS

    def on_confirm_change(e=None) -> None:
        reset_button.disabled = not confirmed()
        page.update()

    reset_confirm = ft.TextField(
        key="reset_confirm",
        label=t("data.reset.confirm_label", lang),
        border_radius=10,
        width=280,
        on_change=on_confirm_change,
    )

    def on_reset(e=None) -> None:
        if not confirmed():
            return
        working()
        keep_models = not bool(reset_models_switch.value)
        make_backup = bool(reset_backup_switch.value)

        def work() -> None:
            try:
                stop_bots()
                backup_path = backup.factory_reset(data_dir=data, keep_models=keep_models, make_backup=make_backup)
                settings_module.reload_into(state)
            except Exception as exc:  # noqa: BLE001
                fail(exc)
                return
            reset_confirm.value = ""
            reset_button.disabled = True
            refresh_backups()
            finish("reset", t("data.reset.done", lang, backup=str(backup_path) if backup_path else "—"))

        page.run_thread(work)

    reset_button = ft.Button(
        key="reset_btn",
        content=t("data.reset.btn", lang),
        icon=ft.Icons.DELETE_FOREVER_ROUNDED,
        bgcolor=theme.DANGER,
        color="#FFFFFF",
        disabled=True,
        on_click=on_reset,
    )

    def on_shop_reset(e=None) -> None:
        if not (shop_reset_confirm.value or "").strip().lower() in RESET_WORDS:
            return
        working()
        make_backup = bool(reset_backup_switch.value)

        def work() -> None:
            try:
                stop_bots()
                backup_path = backup.shop_data_reset(data_dir=data, make_backup=make_backup)
            except Exception as exc:  # noqa: BLE001
                fail(exc)
                return
            shop_reset_confirm.value = ""
            refresh_backups()
            finish("shop_reset", t("data.shopreset.done", lang, backup=str(backup_path) if backup_path else "—"))

        page.run_thread(work)

    shop_reset_confirm = ft.TextField(key="shop_reset_confirm", label=t("data.reset.confirm_label", lang), border_radius=10, width=280)
    shop_reset_button = ft.Button(key="shop_reset_btn", content=t("data.shopreset.btn", lang), icon=ft.Icons.DELETE_SWEEP_OUTLINED,
                                  bgcolor=theme.DANGER, color="#FFFFFF", on_click=on_shop_reset)
    shop_reset_tile = ft.ExpansionTile(
        title=ft.Text(t("data.shopreset.title", lang), size=13, weight=ft.FontWeight.W_500, color=theme.DANGER),
        controls=[
            ft.Container(
                padding=ft.Padding.only(left=8, right=8, bottom=12),
                content=ft.Column(
                    spacing=10,
                    controls=[
                        ft.Text(t("data.shopreset.help", lang), size=12, color=theme.text_secondary(page)),
                        ft.Row(spacing=12, wrap=True, controls=[shop_reset_confirm, shop_reset_button]),
                    ],
                ),
            )
        ],
    )

    reset_tile = ft.ExpansionTile(
        title=ft.Text(t("data.reset.title", lang), size=13, weight=ft.FontWeight.W_500, color=theme.DANGER),
        controls=[
            ft.Container(
                padding=ft.Padding.only(left=8, right=8, bottom=12),
                content=ft.Column(
                    spacing=10,
                    controls=[
                        ft.Text(t("data.reset.help", lang), size=12, color=theme.text_secondary(page)),
                        reset_backup_switch,
                        reset_models_switch,
                        ft.Row(spacing=12, wrap=True, controls=[reset_confirm, reset_button]),
                    ],
                ),
            )
        ],
    )

    return card(
        page,
        ft.Column(
            spacing=14,
            controls=[
                section_header(ft.Icons.SHIELD_OUTLINED, t("data.title", lang)),
                location,
                ft.Divider(height=1),
                ft.Text(t("data.backup.title", lang), size=13.5, weight=ft.FontWeight.W_600),
                secrets_switch,
                ft.Row(spacing=12, wrap=True, controls=[backup_button]),
                ft.Text(t("data.restore.title", lang), size=13.5, weight=ft.FontWeight.W_600),
                ft.Row(
                    spacing=12,
                    wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[restore_dropdown, restore_button, restore_file_button],
                ),
                ft.Text(t("data.diag.title", lang), size=13.5, weight=ft.FontWeight.W_600),
                ft.Text(t("data.diag.help", lang), size=12, color=theme.text_secondary(page)),
                ft.Row(spacing=12, wrap=True, controls=[diagnostics_button]),
                result,
                shop_reset_tile,
                reset_tile,
            ],
        ),
    )
