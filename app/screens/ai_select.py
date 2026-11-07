"""صفحه‌ی انتخاب مدل در آنبوردینگ + اجزای مشترک «کاتالوگ مدلِ محلی».

هیچ خبری از API نیست: کاربر سخت‌افزار خودش را می‌بیند، جدول مدل‌ها بر اساسِ
سخت‌افزار رتبه‌بندی شده، دانلود با یک کلیک (با نوارِ پیشرفت، توقف، ادامه و
حذف)، واردکردن فایل GGUFِ آماده و برگشت به فهرست. همین اجزا (کارتِ سخت‌افزار
و `ModelHub`) در صفحه‌ی «هوش مصنوعی» (`ai_setup.py`) هم دوباره استفاده می‌شن؛
آن صفحه علاوه بر این‌ها بخشِ «پیشرفته» و دکمه‌ی «آزمایشِ مدل» را هم دارد.

نکته‌ی فنی: دانلود روی تردِ UI اجرا **نمی‌شه** (`page.run_thread`) و پیشرفت با
تیکرِ مشترکِ پروژه (`common.start_ticker`) polled می‌شه. رکوردِ کارهایِ در حالِ
انجام در `_JOBS` سراسری نگه داشته می‌شه تا با جابه‌جاییِ بین صفحه‌ها دانلود
قطع نشه و صفحه‌ی جدید همان نوارِ پیشرفت را نشان بدهد.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import flet as ft

from app import theme
from app.core import ai_engine, downloader, hardware, model_catalog
from app.i18n import t
from app.screens import common

GIB = 1024**3
MB = 1024**2

# کارهایِ دانلودِ مشترک بینِ صفحه‌ها؛ کلید = مسیرِ مقصد. مقادیر: dictِ وضعیتِ کار.
_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()

_STATE_COLOR = {
    "recommended": theme.SUCCESS,
    "ok": theme.PRIMARY,
    "tight": theme.ACCENT_DARK,
    "no": theme.DANGER,
}


def stars(n: int) -> str:
    return "★" * max(0, min(5, n)) + "☆" * (5 - max(0, min(5, n)))


def _fmt_speed(bps: float) -> str:
    return f"{bps / MB:.1f} MB/s"


def _fmt_left(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60}:{s % 60:02d}"


def selected_model_name(settings) -> str:
    """نامِ قابل‌فهمِ مدلِ فعلی برایِ خطِ وضعیت (خالی یعنی انتخاب‌نشده)."""
    explicit = (getattr(settings, "model_file_path", "") or "").strip()
    if explicit:
        return Path(explicit).name
    entry = model_catalog.get_entry(getattr(settings, "model_id", "") or "")
    if entry is None:
        return ""
    return f"{entry.family} {entry.params} ({entry.quant})"


def build_hardware_block(page: ft.Page, lang: str, hw=None) -> ft.Control:
    """ردیفِ مقادیرِ سخت‌افزار (بدونِ کارتِ بیرونی) — برایِ استفاده در کارتِ مشترک."""
    hw = hw if hw is not None else hardware.detect()
    ram = f"{hw.ram_gb:.1f} GB" if hw.ram_gb is not None else "—"
    cores = str(hw.cpu_cores) if hw.cpu_cores else "—"
    cpu_model = hw.cpu_model or "—"
    if hw.gpu_model:
        gpu = f"{hw.gpu_model} ({hw.gpu_vram_gb:.1f} GB VRAM)" if hw.gpu_vram_gb is not None else hw.gpu_model
    else:
        gpu = t("ai.local.hw_gpu_none", lang)
    disk = f"{hw.free_disk_gb:.1f} GB" if hw.free_disk_gb is not None else "—"

    def inline(label: str, value: str) -> ft.Control:
        return ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                ft.Text(label, size=13, color=theme.text_secondary(page)),
                ft.Text(value, size=13, weight=ft.FontWeight.W_500),
            ],
        )

    def stacked(label: str, value: str) -> ft.Control:
        return ft.Column(spacing=2, controls=[
            ft.Text(label, size=13, color=theme.text_secondary(page)),
            ft.Text(value, size=13, weight=ft.FontWeight.W_500, selectable=True),
        ])

    return ft.Column(
        spacing=10,
        controls=[
            inline(t("ai.local.hw_ram", lang), ram),
            inline(t("ai.local.hw_cpu", lang), cores),
            stacked(t("ai.local.hw_cpu_model", lang), cpu_model),
            stacked(t("ai.local.hw_gpu", lang), gpu),
            inline(t("ai.local.hw_disk", lang), disk),
        ],
    )


def build_hardware_card(page: ft.Page, lang: str, hw=None, free_gb: float | None = None, storage_dir=None) -> ft.Control:
    """کارتِ مشخصاتِ سیستم + «چرا مهمه» + یادداشتِ صادقانه‌ی CPU/GPU + جایِ ذخیره‌ی مدل."""
    hw = hw if hw is not None else hardware.detect()
    block = build_hardware_block(page, lang, hw)
    if free_gb is not None and hw.free_disk_gb != free_gb:
        # فضایِ پوشه‌ی مدل با فضایِ درایوِ خانه فرق می‌کنه؛ همان عددِ جدول را عوض می‌کنیم.
        last_row = block.controls[4]
        last_row.controls[1].value = f"{free_gb:.1f} GB"
    extra = []
    if storage_dir is not None:
        extra.append(ft.Text(t("ai.local.storage_here", lang, path=str(storage_dir)), size=12, selectable=True,
                             color=theme.text_secondary(page), key="ai_storage_line"))
    card = common.card(
        page,
        ft.Column(
            spacing=12,
            controls=[
                common.section_header(ft.Icons.MEMORY_ROUNDED, t("ai_setup.local.hw_title", lang)),
                block,
                ft.Text(t("ai.local.hw_why", lang), size=12, color=theme.text_secondary(page)),
                ft.Text(t(model_catalog.gpu_acceleration_note(hw, ai_engine.gpu_offload_available()), lang), size=12, color=theme.ACCENT_DARK, italic=True),
                *extra,
            ],
        ),
        padding=18,
    )
    card.key = "hw_card"
    return card


class ModelHub:
    """کاتالوگِ مدل + مدیریتِ دانلود/واردکردنِ فایل، به‌شکلِ یک کنترلِ قابل‌استفاده‌ی دوباره.

    هر بار `render()` کلِ فهرست از نو ساخته می‌شه؛ داده‌هایِ دانلودِ در حالِ اجرا
    در `_JOBS` سراسری است، پس بازسازیِ صفحه (رفتن و برگشتن) دانلود را نمی‌کُشد.
    """

    def __init__(self, page: ft.Page, lang: str, settings, save_callback, on_change=None):
        self.page = page
        self.lang = lang
        self.settings = settings
        self.save = save_callback or (lambda: None)
        self.on_change = on_change  # مثلاً برایِ فعال‌کردنِ دکمه‌ی «بعدی» در آنبوردینگ
        self.control = ft.Column(key="model_hub", spacing=12)
        self._prog: dict = {}  # entry_id -> (bar, text, job)
        self._errors: dict = {}  # entry_id -> پیامِ خطایِ آخرین دانلود
        self._armed: dict = {}  # entry_id -> True (تأییدِ دو مرحله‌ایِ حذف)
        self._verify_results: dict = {}  # entry_id -> ft.Textِ نتیجه (با بازسازیِ کارت حفظ می‌شه)
        self._verify_holder: dict = {}  # entry_id -> ظرفِ جایِ نتیجه در کارتِ فعلی
        self._import_notice: tuple = ("", False)  # پیامِ «وارد کردن فایل» تا بازسازیِ بعد هم می‌مونه
        self.render()

    # ------------------------------------------------------------ ابزارها

    def hw(self):
        return hardware.detect()

    def path_free_gb(self):
        return hardware.free_disk_gb_at(self.settings.get_model_storage_dir())

    def _dest(self, entry) -> Path:
        return self.settings.get_model_storage_dir() / entry.filename

    def _job_for(self, dest: Path):
        with _JOBS_LOCK:
            return _JOBS.get(str(dest))

    def _status(self, entry) -> tuple:
        """(وضعیت، مسیر مقصد، کارِ در حالِ اجرا) — وضعیت ∈ absent/partial/downloading/downloaded/invalid."""
        dest = self._dest(entry)
        job = self._job_for(dest)
        if job is not None:
            return "downloading", dest, job
        if downloader.is_downloaded(dest, entry.size_bytes):
            return "downloaded", dest, None
        if downloader.partial_bytes(dest):
            return "partial", dest, None
        if dest.exists():
            return "invalid", dest, None
        return "absent", dest, None

    def is_current(self, entry) -> bool:
        return (self.settings.model_file_path or "").strip() == "" and (self.settings.model_id or "") == entry.id

    # ------------------------------------------------------------ کارها

    def select(self, entry, download: bool) -> None:
        self.settings.model_id = entry.id
        self.settings.model_file_path = ""
        self.save()
        if download:
            self.start_download(entry)
        else:
            self.render()
            self._notify()

    def start_download(self, entry) -> None:
        dest = self._dest(entry)
        key = str(dest)
        with _JOBS_LOCK:
            if key in _JOBS:
                return  # از قبل در جریانه (شاید از صفحه‌ی دیگر)
            base = downloader.partial_bytes(dest)
            job = {
                "entry": entry, "dest": dest, "base": base, "done": base,
                "total": entry.size_bytes, "started": time.time(), "cancel": False,
                "status": "running", "error": "",
            }
            _JOBS[key] = job
        self._errors.pop(entry.id, None)
        self.settings.model_id = entry.id
        self.settings.model_file_path = ""
        self.save()
        self.render()
        self._notify()

        def on_progress(downloaded: int, total: int) -> None:
            job["done"] = downloaded
            if total:
                job["total"] = total
            # نوار باید حتی اگر تیکرِ صفحه هنوز راه نیفتاده باشد جلو برود: خودِ تردِ دانلود هر
            # نیم‌ثانیه یک‌بار رنگ می‌کند (پیش از این مرگِ بی‌صدای تیکر = نوارِ خاموش تا پایانِ دانلود).
            now = time.time()
            if now - job.get("painted", 0.0) >= 0.5:
                job["painted"] = now
                self.tick()
                self._notify()

        def worker() -> None:
            try:
                downloader.download(
                    entry.urls, dest,
                    expected_sha256=entry.sha256,
                    expected_size=entry.size_bytes,
                    on_progress=on_progress,
                    should_cancel=lambda: bool(job.get("cancel")),
                    allowed_hosts=entry.allowed_hosts,
                )
                job["status"] = "done"
            except downloader.DownloadCancelled:
                job["status"] = "cancelled"
            except downloader.DownloadError as exc:  # IntegrityError زیرکلاسش است
                job["status"] = "failed"
                job["error"] = str(exc)
            except Exception as exc:  # noqa: BLE001 — هر crashِ غیرمنتظره باید به‌شکلِ خطا دیده بشه
                job["status"] = "failed"
                job["error"] = type(exc).__name__
            self._finish(key, job)

        self.page.run_thread(worker)

    def _finish(self, key: str, job: dict) -> None:
        with _JOBS_LOCK:
            if _JOBS.get(key) is job:
                _JOBS.pop(key, None)
        if job["status"] == "failed":
            self._errors[job["entry"].id] = job["error"] or t("ai_setup.local.download_failed", self.lang)
        self.render()
        self._notify()

    def cancel(self, entry) -> None:
        job = self._job_for(self._dest(entry))
        if job is not None:
            job["cancel"] = True

    def delete(self, entry) -> None:
        """دو مرحله‌ای: بارِ اول فقط «مطمئنی؟»، بارِ دوم حذفِ فایل (و .part)."""
        if not self._armed.get(entry.id):
            self._armed[entry.id] = True
            self.render()
            self._notify()
            return
        self._armed.pop(entry.id, None)
        downloader.delete_model(self._dest(entry))
        self._errors.pop(entry.id, None)
        self.render()
        self._notify()

    def verify(self, entry) -> None:
        dest = self._dest(entry)
        result = ft.Text("", key=f"verify_text_{entry.id}", size=12)

        def worker() -> None:
            ok, message = downloader.verify_file(dest, entry.sha256)
            if ok:
                result.value = t("ai.local.verify_ok", self.lang)
                result.color = theme.SUCCESS
            else:
                result.value = t("ai.local.verify_fail", self.lang) + (f" ({message})" if message else "")
                result.color = theme.DANGER
            self._verify_results[entry.id] = result
            self._swap_verify(entry, result)
            self._notify()

        self.page.run_thread(worker)

    # نتیجه‌ی راستی‌آزمایی داخلِ ظرفِ آماده‌ی کارت می‌نشیند (بدونِ بازسازیِ کلِ صفحه).
    def _swap_verify(self, entry, result: ft.Text) -> None:
        holder = self._verify_holder.get(entry.id)
        if holder is not None:
            holder.content = result
            self._notify()

    # ------------------------------------------------------------ نمایش

    def render(self) -> None:  # noqa: C901 — ساختارِ درختِ صفحه همین‌جا کامل تعیین می‌شه
        self._prog = {}
        self._verify_holder = {}
        lang = self.lang
        settings = self.settings
        hw = self.hw()
        free = self.path_free_gb()
        ranked = model_catalog.ranked_for(hw, path_free_gb=free)
        rec = model_catalog.recommend(hw, path_free_gb=free)
        imported = (settings.model_file_path or "").strip()

        controls: list[ft.Control] = [self._status_line(hw, free)]
        if imported:
            controls.append(self._imported_card(Path(imported)))
        else:
            cards = []
            for entry, state in ranked:
                cards.append(self._model_card(entry, state, hw, free, is_rec=rec is not None and rec.id == entry.id))
            controls.append(ft.Text(t("ai_setup.local.models_section_title", lang), size=15, weight=ft.FontWeight.W_600))
            controls.extend(cards)
        controls.append(self._import_card())
        self.control.controls = controls

    def _status_line(self, hw, free) -> ft.Control:
        ready, reason_key = ai_engine.engine_readiness(self.settings)
        name = selected_model_name(self.settings)
        color = theme.SUCCESS if ready else theme.text_secondary(self.page)
        text = t(reason_key, self.lang)
        if name:
            text = f"{name} — {text}"
        return ft.Text(text, key="ai_status_line", size=12.5, color=color)

    def _model_card(self, entry, state: str, hw, free, is_rec: bool) -> ft.Control:  # noqa: C901
        lang = self.lang
        status, dest, job = self._status(entry)
        badge_color = _STATE_COLOR.get(state, theme.PRIMARY)
        badge = ft.Container(
            key=f"badge_{entry.id}",
            padding=ft.Padding.symmetric(horizontal=10, vertical=3),
            border_radius=20,
            bgcolor=f"{badge_color}22",
            content=ft.Text(t(f"ai.local.state_{state}", lang), size=11.5, color=badge_color, weight=ft.FontWeight.W_600),
        )
        header = ft.Row(
            spacing=8,
            wrap=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Text(f"{entry.family} {entry.params} · {entry.quant}", size=14.5, weight=ft.FontWeight.W_700),
                badge,
            ],
        )
        specs = ft.Text(
            f"{entry.size_gb:.2f} GB · {t('ai.local.q_label', lang)} {stars(entry.quality)} · "
            f"{t('ai.local.speed_label', lang)} {stars(entry.speed)} · {entry.license}",
            size=12, color=theme.text_secondary(self.page),
        )
        blurb = ft.Text(entry.blurb.get(lang, ""), size=12.5)
        reason = ft.Text(t(model_catalog.reason_for(hw, entry, path_free_gb=free), lang), size=12, color=badge_color)

        body: list[ft.Control] = [header, specs, blurb, reason]
        if state == "no":
            body.append(ft.Text(t("ai.local.no_warn", lang), size=12, color=theme.DANGER))
        elif state == "tight":
            body.append(ft.Text(t("ai.local.tight_warn", lang), size=12, color=theme.ACCENT_DARK))

        selectable = state != "no"
        can_download = state in ("recommended", "ok", "tight")

        if status == "downloading" and job is not None:
            bar = ft.ProgressBar(value=min(1.0, (job["done"] / job["total"]) if job["total"] else 0), width=360, color=theme.ACCENT)
            text = ft.Text("", size=12, key=f"prog_text_{entry.id}")
            busy = ft.Button(
                content=ft.Text(t("ai.local.state_downloading", lang), size=14, weight=ft.FontWeight.W_600),
                bgcolor=f"{theme.PRIMARY}66", color="#FFFFFF", height=46, disabled=True,
            )
            busy.key = f"dl_btn_{entry.id}"
            body.extend([
                bar,
                text,
                busy,
                ft.TextButton(key=f"cancel_btn_{entry.id}", content=t("ai_setup.local.cancel", lang),
                              icon=ft.Icons.CANCEL_ROUNDED, icon_color=theme.DANGER,
                              on_click=lambda e, en=entry: self.cancel(en)),
            ])
            self._prog[entry.id] = (bar, text, job)
        elif status == "downloaded":
            used = f" · {t('ai.local.used_mark', lang)}" if self.is_current(entry) else ""
            holder = ft.Container()
            self._verify_holder[entry.id] = holder
            body.append(
                ft.Row(spacing=8, wrap=True, controls=[
                    ft.Text(t("ai.local.ready_note", lang) + used, size=12.5, color=theme.SUCCESS),
                    ft.TextButton(key=f"pick_btn_{entry.id}", content=t("ai.local.btn_use", lang),
                                  on_click=lambda e, en=entry: self.select(en, download=False)),
                    ft.TextButton(key=f"verify_btn_{entry.id}", content=t("ai.local.verify_btn", lang),
                                  on_click=lambda e, en=entry: self.verify(en)),
                    ft.TextButton(
                        key=f"del_btn_{entry.id}",
                        content=t("ai.local.sure_delete", lang) if self._armed.get(entry.id) else t("ai_setup.local.delete_model", lang),
                        icon=ft.Icons.DELETE_OUTLINE_ROUNDED, icon_color=theme.DANGER,
                        on_click=lambda e, en=entry: self.delete(en)),
                ])
            )
            prior = self._verify_results.get(entry.id)
            if prior is not None:
                holder.content = prior
            body.append(holder)
        elif status == "invalid":
            body.append(ft.Text(t("ai.local.invalid_note", lang), size=12, color=theme.DANGER))
            body.append(ft.Row(spacing=8, wrap=True, controls=[
                ft.TextButton(
                    key=f"del_btn_{entry.id}",
                    content=t("ai.local.sure_delete", lang) if self._armed.get(entry.id) else t("ai_setup.local.delete_model", lang),
                    icon=ft.Icons.DELETE_OUTLINE_ROUNDED, icon_color=theme.DANGER,
                    on_click=lambda e, en=entry: self.delete(en)),
                ft.TextButton(key=f"dl_btn_{entry.id}", content=t("ai.local.btn_redownload", lang),
                              icon=ft.Icons.DOWNLOAD_ROUNDED,
                              on_click=lambda e, en=entry: self.start_download(en)),
            ]))
        elif status == "partial":
            done_mb = downloader.partial_bytes(dest) / MB
            body.append(ft.Text(t("ai.local.partial_note", lang, mb=f"{done_mb:.0f}"), size=12, color=theme.ACCENT_DARK))
            label = t("ai.local.btn_resume", lang) if can_download else t("ai.local.btn_download_disabled", lang)
            resume_btn = common.primary_button(label, lambda e, en=entry: self.start_download(en),
                                               icon=ft.Icons.PLAY_ARROW_ROUNDED, disabled=not can_download)
            resume_btn.key = f"dl_btn_{entry.id}"
            body.append(ft.Row(spacing=8, wrap=True, controls=[resume_btn]))
        else:  # absent
            label = t("ai.local.btn_download", lang, size=f"{entry.size_gb:.1f}") if can_download else t("ai.local.btn_download_disabled", lang)
            dl_btn = common.primary_button(label, lambda e, en=entry: self.start_download(en),
                                           icon=ft.Icons.DOWNLOAD_ROUNDED, disabled=not can_download)
            dl_btn.key = f"dl_btn_{entry.id}"
            body.append(ft.Row(spacing=8, wrap=True, controls=[dl_btn]))

        error = self._errors.get(entry.id)
        if error and status != "downloading":
            body.append(ft.Text(t("ai_setup.local.download_failed", lang) + " " + error, key=f"err_text_{entry.id}",
                                size=12, color=theme.DANGER))

        clickable = selectable and status in ("downloaded", "absent", "partial", "invalid")
        on_click = (lambda e, en=entry: self.select(en, download=False)) if clickable else None
        return ft.Container(
            key=f"model_card_{entry.id}",
            padding=16,
            border_radius=14,
            bgcolor=theme.card_bgcolor(self.page),
            border=ft.Border.all(2 if is_rec else 1, theme.SUCCESS if is_rec else theme.border_color(self.page)),
            ink=selectable,
            on_click=on_click,
            content=ft.Column(spacing=6, controls=body),
        )

    # ------------------------------------------------------------ واردکردن فایل

    def _import_card(self) -> ft.Control:
        lang = self.lang
        path_field = ft.TextField(
            key="import_path_field",
            label=t("ai.local.import_enter_label", lang),
            border_radius=10,
            text_size=12.5,
        )
        notice, ok = self._import_notice
        result = ft.Text(notice, key="import_result", size=12,
                         color=theme.SUCCESS if (notice and ok) else theme.DANGER if notice else None)

        def apply(_e=None) -> None:
            self._import_notice = self._accept_import_file((path_field.value or "").strip())
            self.render()
            self._notify()

        async def pick(_e=None) -> None:
            picker = common.get_or_create_file_picker(self.page)
            try:
                picked = await picker.pick_files(
                    dialog_title=t("ai.local.import_pick", lang),
                    file_type=ft.FilePickerFileType.CUSTOM,
                    allowed_extensions=["gguf"],
                    allow_multiple=False,
                )
            except ft.FletUnsupportedPlatformException:
                picked = None  # وب/تست — انتخاب فایل فقط روی دسکتاپ واقعی
            if picked:
                path_field.value = str(picked[0].path)
                self.page.update()

        return common.card(
            self.page,
            ft.Column(
                key="import_card",
                spacing=10,
                controls=[
                    common.section_header(ft.Icons.UPLOAD_FILE_ROUNDED, t("ai.local.import_title", lang)),
                    ft.Text(t("ai.local.import_desc", lang), size=12, color=theme.text_secondary(self.page)),
                    path_field,
                    ft.Row(spacing=8, wrap=True, controls=[
                        ft.TextButton(key="import_pick_btn", content=t("ai.local.import_pick", lang),
                                      icon=ft.Icons.FOLDER_OPEN_ROUNDED, on_click=pick),
                        ft.TextButton(key="import_apply_btn", content=t("ai.local.import_apply", lang),
                                      icon=ft.Icons.CHECK_ROUNDED, on_click=apply),
                    ]),
                    result,
                ],
            ),
            padding=16,
        )

    def _accept_import_file(self, raw: str) -> tuple:
        """اعتبارسنجیِ صادقانه: فایلِ واقعیِ GGUF (سرِ فایل، پسوند، حجم) — نه پوشه، نه لینک، نه نصفه."""
        lang = self.lang
        if not raw:
            return t("ai.local.import_need_path", lang), False
        try:
            candidate = Path(raw).expanduser()
            if candidate.is_symlink() or not candidate.is_file():
                return t("ai.local.import_not_gguf", lang), False
            if candidate.suffix.lower() != ".gguf" or candidate.stat().st_size < 1_000_000:
                return t("ai.local.import_not_gguf", lang), False
            with open(candidate, "rb") as handle:
                if handle.read(4) != downloader.GGUF_MAGIC:
                    return t("ai.local.import_not_gguf", lang), False
        except OSError:
            return t("ai.local.import_not_gguf", lang), False
        self.settings.model_file_path = str(candidate)
        self.settings.model_id = None
        self.save()
        return t("ai.local.import_done", lang), True

    def _imported_card(self, path: Path) -> ft.Control:
        lang = self.lang
        ready, reason_key = ai_engine.engine_readiness(self.settings)
        return common.card(
            self.page,
            ft.Column(
                key="imported_card",
                spacing=10,
                controls=[
                    common.section_header(ft.Icons.DESCRIPTION_ROUNDED, t("ai.local.imported_title", lang)),
                    ft.Text(str(path), size=12.5, weight=ft.FontWeight.W_500, selectable=True),
                    ft.Text(t(reason_key, lang), size=12, color=theme.SUCCESS if ready else theme.ACCENT_DARK),
                    ft.Row(spacing=8, wrap=True, controls=[
                        ft.TextButton(key="catalog_back_btn", content=t("ai.local.imported_back", lang),
                                      icon=ft.Icons.ARROW_BACK_ROUNDED, icon_color=theme.PRIMARY,
                                      on_click=lambda e: self.drop_import()),
                    ]),
                ],
            ),
            padding=16,
        )

    def drop_import(self) -> None:
        self.settings.model_file_path = ""
        self._import_notice = ("", False)
        self.save()
        self.render()
        self._notify()

    # ------------------------------------------------------------ تیکر

    def tick(self) -> None:
        """پیشرفتِ دانلودها را از رکوردِ تردِ دانلود می‌خواند (بدونِ لمسِ شبکه در UI).

        پایانِ کار (موفق/لغو/خطا) را خودِ تردِ دانلود با `_finish` هندل می‌کند؛
        این‌جا فقط متن/نوارِ پیشرفت تازه می‌شه."""
        lang = self.lang
        for _entry_id, (bar, text, job) in list(self._prog.items()):
            done, total, base = job.get("done", 0), job.get("total", 0), job.get("base", 0)
            if total:
                bar.value = min(1.0, max(0.0, done / total))
            speed = (done - base) / max(time.time() - job.get("started", time.time()), 0.001)
            if total and speed > 0:
                left = _fmt_left((total - done) / speed)
            else:
                left = t("ai.local.left_unknown", lang)
            text.value = t("ai.local.downloading", lang, percent=int(done / total * 100) if total else 0,
                           speed=_fmt_speed(speed) if speed > 0 else "—", left=left)

    def _notify(self) -> None:
        if self.on_change:
            self.on_change()
        try:
            self.page.update()
        except Exception:  # noqa: BLE001 — صفحه‌ی بسته‌شده؛ رسمِ بعدی جبران می‌کنه
            pass


def build(
    page: ft.Page,
    lang: str,
    settings,
    save_callback,
    on_next,
    on_back,
    on_skip=None,
) -> ft.Control:
    """گامِ سومِ آنبوردینگ: انتخابِ مدلِ محلی (بدونِ هیچ سوالِ API)."""

    def refresh_next() -> None:
        next_btn.disabled = not bool(settings.model_id or (settings.model_file_path or "").strip())

    hub = ModelHub(page, lang, settings, save_callback, on_change=refresh_next)
    hw = hub.hw()
    hw_card = build_hardware_card(page, lang, hw, free_gb=hub.path_free_gb(), storage_dir=hub.settings.get_model_storage_dir())

    def go_next(_e=None) -> None:
        on_next()

    next_btn = common.primary_button(
        t("common.next", lang), go_next, width=220,
        disabled=not bool(settings.model_id or (settings.model_file_path or "").strip()),
    )
    next_btn.key = "next_button"
    skip_btn = ft.TextButton(key="skip_button", content=t("ai.local.skip", lang), on_click=lambda e: (on_skip or on_next)())
    back_btn = ft.TextButton(key="back_button", content=t("common.back", lang), on_click=lambda e: on_back())

    header = ft.Column(
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=6,
        controls=[
            ft.Text(t("ai.title", lang), size=22, weight=ft.FontWeight.W_700),
            ft.Container(
                width=560,
                content=ft.Text(t("ai.subtitle", lang), size=13, color=theme.text_secondary(page), text_align=ft.TextAlign.CENTER),
            ),
        ],
    )
    footer = ft.Row(
        alignment=ft.MainAxisAlignment.CENTER,
        spacing=12,
        controls=[back_btn, skip_btn, next_btn],
    )
    root = common.onboarding_frame(page, 2, 3, [header, hw_card, hub.control, footer])
    hub.control.data = {"tick": hub.tick, "hub": hub}
    common.start_ticker(page, hub.control, hub.tick, seconds=2)
    return root
