"""کارتِ «شتابِ گرافیکی» (قلم ۲ از باگ‌هایِ گزارش‌شدهٔ مالک).

یک نصبِ واحد، دو سرنوشت: رویِ ماشینِ بدونِ کارتِ NVIDIA همان CPU می‌ماند و هیچ چیزی دانلود
نمی‌شود؛ رویِ ماشینِ دارایِ کارت، برنامه خودش «بستهٔ شتاب» را از انتشارِ رسمیِ llama.cpp دانلود،
با SHA-256 راستی‌آزمایی، جای‌گذاری و فعال می‌کند — و اگر خودِ بیلد بعد ازِ نصب هم GPU را نشناخت،
همان‌جا rollback می‌شود تا موتورِ خراب انتخاب‌شده نماند.

کلِ منطق در ``app/core/gpu_pack.py`` است؛ این صفحه هیچ عددی را محاسبه نمی‌کند و هیچ ادعایی
نمی‌سازد: وضعیت، اندازه‌ها و نتیجهٔ کار را از همان ماژول می‌خواند. ``pack`` فقط برایِ تست
تزریق می‌شود (جایگزینِ ماژول با همان API).
"""

from __future__ import annotations

import flet as ft

from app import theme
from app.core import gpu_pack
from app.screens import common

_S = {
    "title": ("شتابِ گرافیکی (اختیاری)", "GPU acceleration (optional)"),
    "intro": (
        "برنامه یک نسخه دارد. اگر کارتِ NVIDIA داشته باشی، بستهٔ شتاب را خودش دانلود و فعال می‌کند "
        "تا پاسخ سریع‌تر و با فشارِ کمترِ CPU بیاید؛ اگر نداشته باشی، همان CPU می‌ماند و چیزی "
        "دانلود نمی‌شود.",
        "One build. With an NVIDIA card the app downloads and activates an acceleration pack so answers "
        "come faster with less CPU load; without one it stays on CPU and downloads nothing.",
    ),
    "cuda": ("نسخهٔ CUDA", "CUDA version"),
    "enabled": ("اگر گرافیک بود، خودکار فعال شود", "Activate automatically when a GPU exists"),
    "install": ("نصب و فعال‌سازی", "Install and enable"),
    "resume": ("ادامهٔ نصب", "Resume install"),
    "cancel": ("لغو", "Cancel"),
    "uninstall": ("برداشتنِ بسته", "Remove the pack"),
    "check": ("بررسیِ دوباره", "Check again"),
    "gpu_none": ("کارتِ NVIDIA پیدا نشد؛ این ماشین CPU است و بستهٔ شتاب لازم ندارد.",
                 "No NVIDIA card found — this machine is CPU-only and needs no pack."),
    "gpu_yes": ("کارت: {model}{vram}", "Card: {model}{vram}"),
    "sizes": ("حجمِ دانلود: {total} مگابایت — {parts}", "Download size: {total} MB — {parts}"),
    "absent": ("بستهٔ شتاب نصب نشده؛ پاسخ‌ها روی CPU ساخته می‌شوند.", "No acceleration pack; answers are built on CPU."),
    "partial": ("نصبِ نصفه: {files} فایل آماده است. «ادامهٔ نصب» از همان‌جا ادامه می‌دهد.",
                "Partial install: {files} file(s) ready. “Resume install” continues from where it stopped."),
    "active": ("✅ فعال است: پاسخ‌ها روی {gpu} محاسبه می‌شوند.", "✅ Active: answers are computed on {gpu}."),
    "cpu_fallback": ("⚠️ بسته نصب است ولی خودِ موتور گرافیک را نشناخت؛ برنامه به CPU برگشت.",
                     "⚠️ The pack is installed but the engine rejected a GPU; the app fell back to CPU."),
    "restart": ("بسته فعال شد؛ برایِ دیدنِ اثرش برنامه را یک‌بار ببند و دوباره باز کن.",
                "The pack is active — close and reopen the app once for it to take effect."),
    "busy": ("در حالِ دانلود/بررسی… اگر خواهی «لغو» را بزن.", "Downloading/checking… press “Cancel” to stop."),
    "cancelled": ("لغو شد؛ هرچه دانلود شده پاک نمی‌شود و بعداً ادامه می‌دهد.",
                  "Cancelled — what was downloaded is kept and will resume later."),
    "removed": ("بسته برداشته شد؛ محاسبه دوباره روی CPU است.", "Pack removed; computing is back on CPU."),
    "saved": ("ذخیره شد.", "Saved."),
    "failed": ("⚠️ {detail}", "⚠️ {detail}"),
    "not_supported": ("بستهٔ شتاب فقط روی ویندوزِ دارایِ کارتِ NVIDIA معنا دارد.",
                      "The acceleration pack only makes sense on Windows with an NVIDIA card."),
}


def S(key: str, lang: str, **kw) -> str:
    fa, en = _S[key]
    text = en if lang == "en" else fa
    return text.format(**kw) if kw else text


def _status(st, lang: str, labels) -> None:
    """سطرِ وضعیت + در دسترس‌بودنِ دکمه‌ها — فقط از دادهٔ ``gpu_pack``، بدونِ حدس."""
    secondary = labels["secondary"]
    if not st.windows or not st.supported:
        st_line, color = S("not_supported", lang), secondary
    elif not st.has_nvidia:
        st_line, color = S("gpu_none", lang), secondary
    elif st.active:
        st_line, color = S("active", lang, gpu=st.gpu_model or "GPU"), theme.SUCCESS
    elif st.verified == "cpu":
        st_line, color = S("cpu_fallback", lang), theme.WARNING
    elif st.state == gpu_pack.STATE_PARTIAL:
        st_line, color = S("partial", lang, files=len(st.files)), theme.WARNING
    elif st.state == gpu_pack.STATE_INSTALLED:
        st_line, color = S("restart", lang), theme.INFO
    else:
        st_line, color = S("absent", lang), secondary
    labels["state"].value, labels["state"].color = st_line, color
    labels["gpu"].value = (
        S("gpu_yes", lang, model=st.gpu_model or "NVIDIA",
          vram=f" — {st.gpu_vram_gb:g} گیگابایت" if st.gpu_vram_gb else "") if st.has_nvidia else ""
    )
    labels["gpu"].visible = bool(st.has_nvidia)
    can_work = bool(st.windows and st.supported and st.has_nvidia)
    labels["sizes"].value = ""
    labels["sizes"].visible = False
    if can_work:
        parts = labels["sizes_data"]
        labels["sizes"].value = S("sizes", lang, total=round(sum(mb for _n, mb in parts), 1),
                                 parts=" + ".join(f"{n} ({mb})" for n, mb in parts))
        labels["sizes"].visible = True
    labels["install"].visible = can_work and not st.active
    labels["install"].content = S("resume" if st.state == gpu_pack.STATE_PARTIAL else "install", lang)
    labels["uninstall"].visible = can_work and st.installed


def build(page: ft.Page, lang: str, settings, save_callback, pack=None) -> ft.Control:
    g = pack or gpu_pack
    secondary = theme.text_secondary(page)
    state = ft.Text("", key="gpu_state", size=13, weight=ft.FontWeight.W_600)
    gpu_line = ft.Text("", key="gpu_info", size=12, color=secondary)
    sizes_line = ft.Text("", key="gpu_sizes", size=12, color=secondary)
    note = ft.Text("", key="gpu_note", size=12.5, visible=False, selectable=True)
    bar = ft.ProgressRing(key="gpu_progress", width=22, height=22, visible=False, stroke_width=3)
    ui = {"busy": False, "cancel": False}

    def show(text: str, ok: bool = True) -> None:
        note.value, note.color, note.visible = text, (theme.SUCCESS if ok else theme.WARNING), bool(text)

    def refresh() -> None:
        st = g.status(settings=settings)
        _status(st, lang, labels)
        page.update()

    def on_install(_e=None) -> None:
        if ui["busy"]:
            return
        ui["busy"], ui["cancel"] = True, False
        settings.gpu_pack_cuda = cuda_dd.value or settings.gpu_pack_cuda
        save_callback()
        bar.visible, bar.value, note.visible = True, 0.0, False
        show(S("busy", lang), True)

        def worker() -> None:
            try:
                result = g.install(settings=settings, cuda=cuda_dd.value or "",
                                   progress_cb=lambda done, total: _tick(done, total),
                                   cancel_cb=lambda: ui["cancel"])
            except g.GpuPackError as exc:  # «نشود» صریح: علت را می‌گوییم، چیزی نیمه‌کاره نمی‌ماند
                ui["busy"] = False
                bar.visible = False
                show(str(exc), False)
                page.update()
                refresh()
                return
            ui["busy"] = False
            bar.visible = False
            if result.cancelled:
                show(S("cancelled", lang), True)
            elif result.ok and result.verified == "gpu":
                show(S("restart", lang) if result.restart_needed else S("saved", lang), True)
            elif result.rolled_back:
                show(S("cpu_fallback", lang) + (f"\n{result.detail}" if result.detail else ""), False)
            else:
                show(S("failed", lang, detail=result.detail or "—"), False)
            page.update()
            refresh()

        page.run_thread(worker)

    def _tick(done: int, total: int) -> None:
        bar.value = (done / total) if total else 0.0
        bar.visible = True
        page.update()

    def on_cancel(_e=None) -> None:
        ui["cancel"] = True
        show(S("busy", lang), True)

    def on_uninstall(_e=None) -> None:
        if ui["busy"]:
            return
        ok, detail = g.uninstall(cuda=cuda_dd.value or "", settings=settings)
        show(detail if not ok else S("removed", lang), ok)
        refresh()

    def on_switch(_e=None) -> None:
        settings.gpu_pack_enabled = bool(enabled.value)
        save_callback()
        show(S("saved", lang), True)

    keys = g.target_keys()
    cuda_dd = ft.Dropdown(
        key="gpu_cuda", label=S("cuda", lang), border_radius=10, width=180,
        value=settings.gpu_pack_cuda if settings.gpu_pack_cuda in keys else (keys[0] if keys else ""),
        options=[ft.DropdownOption(key=k, text=k) for k in keys],
        on_select=lambda _e: refresh(),
    )
    enabled = ft.Switch(key="gpu_enabled", label=S("enabled", lang), value=bool(settings.gpu_pack_enabled), on_change=on_switch)
    install_btn = ft.FilledButton(key="gpu_install", content=S("install", lang), icon=ft.Icons.DOWNLOAD_ROUNDED, on_click=on_install)
    cancel_btn = ft.TextButton(key="gpu_cancel", content=S("cancel", lang), on_click=on_cancel)
    uninstall_btn = ft.TextButton(key="gpu_uninstall", content=S("uninstall", lang), icon=ft.Icons.DELETE_OUTLINE_ROUNDED, on_click=on_uninstall)
    check_btn = ft.OutlinedButton(key="gpu_check", content=S("check", lang), icon=ft.Icons.REFRESH_ROUNDED, on_click=lambda _e: refresh())

    labels = {"state": state, "gpu": gpu_line, "sizes": sizes_line, "install": install_btn,
              "uninstall": uninstall_btn, "secondary": secondary, "sizes_data": []}
    # اندازه‌ها یک‌بار از ماژول خوانده می‌شوند (عددهایِ سنجیده‌شده، نه وعده‌یِ ساختگی)
    try:
        labels["sizes_data"] = list(g.describe_sizes(settings.gpu_pack_cuda or ""))
    except Exception:  # noqa: BLE001 — نبودِ فهرست نباید صفحه را ببندد
        labels["sizes_data"] = []

    refresh()
    return common.card(
        page,
        ft.Column(
            key="gpu_card",
            spacing=10,
            controls=[
                ft.Text(S("title", lang), size=15, weight=ft.FontWeight.W_700),
                ft.Text(S("intro", lang), size=12.5, color=secondary),
                state,
                gpu_line,
                sizes_line,
                ft.Row(spacing=10, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                       controls=[cuda_dd, enabled, bar, install_btn, cancel_btn, uninstall_btn, check_btn]),
                note,
            ],
        ),
        padding=14,
    )
