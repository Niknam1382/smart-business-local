"""صفحه‌ی «هوش مصنوعی» در نوارِ کناری — مدیریتِ کاملِ مدلِ محلی.

بدونِ API: کارتِ سخت‌افزار، فهرستِ مدل‌ها با پیشنهادِ بر پایه‌ی رم/دیسک،
دانلودِ تک‌کلیکی با پیشرفت/توقف/ادامه/حذف/راستی‌آزمایی، واردکردنِ فایلِ GGUFِ
آماده، بخشِ «پیشرفته» (پوشهٔ مدل، توکنِ زمینه، ترد، لایه‌ی GPU، کلیدِ خاموشی،
سقف‌هایِ روزانه) و دکمه‌ی «آزمایشِ مدل» که صادقانه نتیجه را می‌گوید.

کارت‌ها و مدیریتِ دانلود از `ai_select.ModelHub` می‌آیند (همان اجزای آنبوردینگ)؛
این فایل فقط پوسته + بخشِ پیشرفته + آزمایش را اضافه می‌کند. هیچ کاری (دانلود،
راستی‌آزمایی، آزمایشِ مدل) روی تردِ UI اجرا نمی‌شه؛ پیشرفت با `common.start_ticker`
polled می‌شه.
"""

from __future__ import annotations

import flet as ft

from app import theme
from app.core import ai_engine, hardware, model_catalog
from app.i18n import t
from app.screens import ai_select, common


def build(page: ft.Page, lang: str, settings, save_callback) -> ft.Control:
    hub = ai_select.ModelHub(page, lang, settings, save_callback)
    hw = hub.hw()
    hw_card = ai_select.build_hardware_card(page, lang, hw, free_gb=hub.path_free_gb())
    advanced = _AdvancedSection(page, lang, settings, save_callback, hub)
    test_card = _build_test_section(page, lang, settings)

    root = common.screen_frame(
        page,
        common.page_header(page, ft.Icons.SMART_TOY_ROUNDED, t("ai_setup.title", lang), t("ai_setup.subtitle", lang)),
        [hw_card, hub.control, test_card, advanced.control],
        key="ai_setup_frame",
    )
    hub.control.data = {"tick": hub.tick, "hub": hub}
    common.start_ticker(page, root, hub.tick, seconds=2)
    return root


# ============================== آزمایشِ مدل ==============================


def _build_test_section(page: ft.Page, lang: str, settings) -> ft.Control:
    """دکمه‌ی «آزمایشِ مدل»: یک پرسشِ ثابتِ فارسی روی مدلِ فعلی — نتیجه یا خطا را همان‌جا چاپ می‌کند."""
    result = ft.Text("", key="ai_test_result", size=12.5, selectable=True)
    spinner = ft.ProgressRing(width=18, height=18, visible=False)
    spinner.key = "ai_test_spinner"

    def handle(_e=None) -> None:
        result.value = t("ai_setup.test.running", lang)
        result.color = theme.text_secondary(page)
        spinner.visible = True
        page.update()

        def worker() -> None:
            engine = None
            try:
                engine = ai_engine.build_engine_from_settings(settings)
                ok, text = engine.self_test()
            except ai_engine.AiEngineError as exc:
                ok, text = False, t("ai_setup.test.error_prefix", lang) + str(exc)
            except Exception as exc:  # noqa: BLE001 — هیچ crashِ داخلِ llama نباید صفحه را ببندد
                ok, text = False, t("ai_setup.test.error_prefix", lang) + type(exc).__name__
            finally:
                spinner.visible = False
            if not ok and not text.startswith(t("ai_setup.test.error_prefix", lang)):
                text = t("ai_setup.test.error_prefix", lang) + text
            result.value = text
            result.color = theme.SUCCESS if ok else theme.DANGER
            try:
                if engine is not None:
                    engine.unload()
            except Exception:  # noqa: BLE001
                pass
            page.update()

        page.run_thread(worker)

    test_btn = common.primary_button(t("ai_setup.test.btn", lang), handle, icon=ft.Icons.SCIENCE_ROUNDED)
    test_btn.key = "ai_test_btn"

    return common.card(
        page,
        ft.Column(
            spacing=10,
            controls=[
                common.section_header(ft.Icons.BOLT_ROUNDED, t("ai_setup.test.title", lang)),
                ft.Text(t("ai_setup.test.desc", lang), size=12, color=theme.text_secondary(page)),
                ft.Row(spacing=10, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[test_btn, spinner, result]),
            ],
        ),
        padding=16,
    )


# ============================== بخشِ پیشرفته ==============================


class _AdvancedSection:
    """کارتِ تاشو — بیرونی‌ترین ظرف تنها چیزی است که visible می‌شه (هیچ کنترلِ
    نامرئیِ تو‌در‌تو نیست تا «کادرِ خالی» بسازه)."""

    def __init__(self, page: ft.Page, lang: str, settings, save_callback, hub):
        self.page = page
        self.lang = lang
        self.settings = settings
        self.save = save_callback
        self.hub = hub
        self._open = False

        self.toggle = ft.TextButton(
            key="adv_toggle",
            content=t("ai_setup.adv_title", lang),
            icon=ft.Icons.TUNE_ROUNDED,
            on_click=lambda e: self.set_open(not self._open),
        )
        self.area = ft.Container(key="adv_area", visible=False, width=560)
        self.area.content = self._fields()
        self.control = ft.Column(spacing=10, controls=[self.toggle, self.area])

    def set_open(self, value: bool) -> None:
        self._open = bool(value)
        self.area.visible = self._open  # فقط ظرفِ بیرونی؛ بچه‌ها همیشه مرئی‌ان
        if self._open:
            self.refresh_storage()
        self.page.update()

    # ------------------------------------------------------------ فیلدها

    def _fields(self) -> ft.Control:
        lang = self.lang
        s = self.settings
        self.storage_path_text = ft.Text(str(s.get_model_storage_dir()), size=12.5, selectable=True, weight=ft.FontWeight.W_500)
        self.storage_path_text.key = "adv_storage_path"
        self.free_text = ft.Text("", size=12, color=theme.text_secondary(self.page))
        self.free_text.key = "adv_free"

        self.ctx_field = ft.TextField(key="adv_ctx", label=t("ai_setup.adv_ctx_label", lang), width=170, border_radius=10,
                                      value=str(s.ai_context_tokens) if s.ai_context_tokens else "",
                                      hint_text=t("ai_setup.adv_auto", lang))
        self.ctx_note = ft.Text("", size=11.5, color=theme.text_secondary(self.page))
        self.ctx_note.key = "adv_ctx_note"

        self.threads_field = ft.TextField(key="adv_threads", label=t("ai_setup.adv_threads_label", lang), width=170, border_radius=10,
                                          value=str(s.ai_threads) if s.ai_threads else "",
                                          hint_text=t("ai_setup.adv_auto", lang))
        self.threads_note = ft.Text("", size=11.5, color=theme.text_secondary(self.page))
        self.threads_note.key = "adv_threads_note"

        self.gpu_field = ft.TextField(key="adv_gpu", label=t("ai_setup.adv_gpu_label", lang), width=170, border_radius=10,
                                      value=str(s.ai_gpu_layers) if s.ai_gpu_layers else "",
                                      hint_text=t("ai_setup.adv_auto", lang))
        self.gpu_note = ft.Text(t("ai_setup.adv_gpu_hint", lang), size=11.5, color=theme.text_secondary(self.page))
        self.gpu_note.key = "adv_gpu_note"

        self.kill_switch = ft.Switch(key="adv_kill", label=t("ai_setup.adv_kill_label", lang), value=bool(s.ai_kill_switch))
        self.cap_chat_field = ft.TextField(key="adv_cap_chat", label=t("ai_setup.adv_cap_chat_label", lang), width=220, border_radius=10,
                                           value=str(s.max_ai_messages_per_chat_per_day))
        self.cap_total_field = ft.TextField(key="adv_cap_total", label=t("ai_setup.adv_cap_total_label", lang), width=220, border_radius=10,
                                            value=str(s.max_ai_messages_per_day_total))
        self.notice = ft.Text("", key="adv_notice", size=12, visible=False)

        def auto_text(value: int, auto: int) -> str:
            return t("ai_setup.adv_auto_value", lang, n=f"{auto}") if not value else t("ai_setup.adv_manual_value", lang, n=f"{value}")

        self._auto_text = auto_text
        self._refresh_autos()

        save_btn = ft.Button(
            content=ft.Text(t("ai_setup.adv_save", lang), size=14, weight=ft.FontWeight.W_600),
            bgcolor=theme.PRIMARY, color="#FFFFFF", height=42, on_click=self.on_save,
        )
        save_btn.key = "adv_save"

        return ft.Column(
            spacing=12,
            controls=[
                common.section_header(ft.Icons.FOLDER_OPEN_ROUNDED, t("ai_setup.local.storage_label", lang)),
                ft.Row(spacing=8, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    self.storage_path_text,
                    ft.TextButton(t("ai_setup.local.storage_change", lang), icon=ft.Icons.FOLDER_OPEN_ROUNDED,
                                  on_click=self.change_dir, key="adv_storage_btn"),
                ]),
                self.free_text,
                ft.Divider(height=1, color=theme.border_color(self.page)),
                common.section_header(ft.Icons.TUNE_ROUNDED, t("ai_setup.adv_engine_title", lang)),
                ft.Row(spacing=10, wrap=True, controls=[self.ctx_field, self.ctx_note]),
                ft.Row(spacing=10, wrap=True, controls=[self.threads_field, self.threads_note]),
                ft.Row(spacing=10, wrap=True, controls=[self.gpu_field, self.gpu_note]),
                ft.Divider(height=1, color=theme.border_color(self.page)),
                common.section_header(ft.Icons.SHIELD_ROUNDED, t("ai_setup.adv_limits_title", lang)),
                ft.Row(spacing=10, wrap=True, controls=[self.cap_chat_field, self.cap_total_field]),
                self.kill_switch,
                ft.Row(spacing=10, wrap=True, controls=[save_btn]),
                self.notice,
            ],
        )

    def _refresh_autos(self) -> None:
        hw = self.hub.hw()
        entry = model_catalog.get_entry(self.settings.model_id or "")
        if entry is None:
            entry = model_catalog.recommend(hw, path_free_gb=self.hub.path_free_gb())
        auto_ctx = model_catalog.auto_context_tokens(hw, entry) if entry else 4096
        auto_threads = model_catalog.auto_threads(hw)

        def as_int(raw: str) -> int:
            return int(raw) if (raw or "").strip().isdigit() else 0

        self.ctx_note.value = self._auto_text(as_int(self.ctx_field.value), auto_ctx)
        self.threads_note.value = self._auto_text(as_int(self.threads_field.value), auto_threads)
        if as_int(self.gpu_field.value):
            self.gpu_note.value = t("ai_setup.adv_gpu_hint", self.lang)
        else:
            self.gpu_note.value = t("ai_setup.adv_gpu_auto", self.lang)

    # ------------------------------------------------------------ کارها

    def refresh_storage(self) -> None:
        self.storage_path_text.value = str(self.settings.get_model_storage_dir())
        free = hardware.free_disk_gb_at(self.settings.get_model_storage_dir())
        self.free_text.value = (t("ai_setup.local.free_space", self.lang) + f": {free:.1f} GB") if free is not None else ""

    async def change_dir(self, _e=None) -> None:
        picker = common.get_or_create_file_picker(self.page)
        try:
            selected = await picker.get_directory_path(dialog_title=t("ai_setup.local.storage_change", self.lang))
        except ft.FletUnsupportedPlatformException:
            selected = None  # وب/تست — انتخابِ پوشه فقط روی دسکتاپ
        if selected:
            self.settings.model_storage_path = str(selected)
            self.save()
            self.refresh_storage()
            self.hub.render()
            self.page.update()

    def on_save(self, _e=None) -> None:
        lang = self.lang
        spec = (
            (self.ctx_field, t("ai_setup.adv_ctx_label", lang), 0, 131072),
            (self.threads_field, t("ai_setup.adv_threads_label", lang), 0, 256),
            (self.gpu_field, t("ai_setup.adv_gpu_label", lang), 0, 999),
            (self.cap_chat_field, t("ai_setup.adv_cap_chat_label", lang), 0, 1_000_000),
            (self.cap_total_field, t("ai_setup.adv_cap_total_label", lang), 0, 10_000_000),
        )
        values = {}
        for field, label, lo, hi in spec:
            raw = (field.value or "").strip()
            if raw == "":
                values[field.key] = 0
                continue
            if not raw.isdigit() or not lo <= int(raw) <= hi:
                self._show(t("ai_setup.adv_bad", lang, label=label), False)
                self.page.update()
                return
            values[field.key] = int(raw)
        self.settings.ai_context_tokens = values["adv_ctx"]
        self.settings.ai_threads = values["adv_threads"]
        self.settings.ai_gpu_layers = values["adv_gpu"]
        self.settings.max_ai_messages_per_chat_per_day = values["adv_cap_chat"]
        self.settings.max_ai_messages_per_day_total = values["adv_cap_total"]
        self.settings.ai_kill_switch = bool(self.kill_switch.value)
        self.save()
        self._refresh_autos()
        self.hub.render()
        self._show(t("ai_setup.adv_saved", lang), True)
        self.page.update()

    def _show(self, text: str, ok: bool) -> None:
        self.notice.value = text
        self.notice.color = theme.SUCCESS if ok else theme.DANGER
        self.notice.visible = bool(text)
