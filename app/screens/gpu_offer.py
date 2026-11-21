"""پیشنهادِ خودکارِ شتابِ گرافیکی (۱٫۲٫۰).

اگر کارتِ NVIDIA روی ویندوز پیدا شود و «بسته‌ی شتاب» نصب نباشد، یک‌بار (در هر اجرا؛ و تا وقتی کاربر «دیگر نپرس» نزده)
دیالوگی با حجمِ دقیق و علتِ دانلود نشان داده می‌شود. هیچ‌چیز بدونِ اجازه‌ی صریحِ کاربر دانلود نمی‌شود. نصب، راستی‌آزمایی،
فعال‌سازی و rollbackِ خودکار همه در ``gpu_pack`` است؛ اینجا فقط درخواست و نمایشِ پیشرفت است. مسیرِ CPU همیشه سالم می‌ماند.
"""

from __future__ import annotations

import os

import flet as ft

from app import theme
from app.core import gpu_pack
from app.screens.gpu_card import S

_OFFERED = {"done": False}


def should_offer(settings, st) -> bool:
    """فقط وقتی پیشنهاد بده که واقعاً به کاربر کمک می‌کند."""
    if not (st.windows and st.supported and st.has_nvidia):
        return False
    if st.active or st.installed:
        return False
    if not getattr(settings, "gpu_pack_enabled", True) or getattr(settings, "gpu_offer_dismissed", False):
        return False
    return bool(getattr(settings, "model_id", "") or getattr(settings, "model_file_path", ""))


def maybe_offer(page: ft.Page, lang: str, settings, save, pack=None, once: bool = True) -> bool:
    """اگر لازم بود دیالوگ را نشان می‌دهد؛ ``True`` یعنی نشان داده شد. هرگز استثنا نمی‌اندازد."""
    g = pack or gpu_pack
    if os.environ.get("SMART_BUSINESS_NO_GPU_OFFER") == "1":  # تست‌ها/اجرای بی‌سر: هرگز دیالوگ نشان نده
        return False
    if once and _OFFERED["done"]:
        return False
    try:
        st = g.status(settings=settings)
        if not should_offer(settings, st):
            return False
        sizes = list(g.describe_sizes(settings.gpu_pack_cuda or ""))
    except Exception:  # noqa: BLE001 — پیشنهادِ اختیاری نباید برنامه را بشکند
        return False
    _OFFERED["done"] = True
    total_mb = round(sum(mb for _n, mb in sizes), 1)
    ui = {"busy": False, "cancel": False}
    note = ft.Text("", key="gpu_offer_note", size=12.5, selectable=True, visible=False)
    bar = ft.ProgressBar(key="gpu_offer_bar", visible=False, width=360, color=theme.PRIMARY)

    def close(_e=None) -> None:
        pop = getattr(page, "pop_dialog", None)
        if callable(pop):
            try:
                pop()
                return
            except Exception:  # noqa: BLE001
                pass
        dialog.open = False
        page.update()

    def later(_e=None) -> None:
        if ui["busy"]:
            ui["cancel"] = True
        close()

    def never(_e=None) -> None:
        if ui["busy"]:
            ui["cancel"] = True
        settings.gpu_offer_dismissed = True
        save()
        close()

    def tick(done: int, total: int) -> None:
        bar.value = (done / total) if total else 0.0
        bar.visible = True
        page.update()

    def do_install(_e=None) -> None:
        if ui["busy"]:
            return
        ui["busy"], ui["cancel"] = True, False
        note.value, note.color, note.visible = S("busy", lang), theme.INFO, True
        bar.visible, bar.value = True, 0.0
        install_btn.disabled = True
        page.update()

        def worker() -> None:
            try:
                result = g.install(settings=settings, cuda=settings.gpu_pack_cuda or "", progress_cb=tick, cancel_cb=lambda: ui["cancel"])
            except Exception as exc:  # noqa: BLE001 — GpuPackError و هر خطای دیگر: علتِ روشن، بدونِ نیمه‌کاری
                ui["busy"] = False
                bar.visible = False
                install_btn.disabled = False
                note.value, note.color, note.visible = S("failed", lang, detail=str(exc) or "—"), theme.WARNING, True
                page.update()
                return
            ui["busy"] = False
            bar.visible = False
            if result.cancelled:
                note.value, note.color = S("cancelled", lang), theme.INFO
                install_btn.disabled = False
            elif result.ok and result.verified == "gpu":
                note.value, note.color = (S("restart", lang) if result.restart_needed else S("saved", lang)), theme.SUCCESS
            elif result.rolled_back:
                note.value, note.color = S("cpu_fallback", lang) + (f"\n{result.detail}" if result.detail else ""), theme.WARNING
                install_btn.disabled = False
            else:
                note.value, note.color = S("failed", lang, detail=result.detail or "—"), theme.WARNING
                install_btn.disabled = False
            note.visible = True
            page.update()

        page.run_thread(worker)

    install_btn = ft.FilledButton(key="gpu_offer_install", content=S("offer_yes", lang, mb=total_mb), icon=ft.Icons.BOLT_ROUNDED, on_click=do_install)
    dialog = ft.AlertDialog(
        key="gpu_offer_dialog",
        modal=True,
        title=ft.Text(S("offer_title", lang), weight=ft.FontWeight.W_700),
        content=ft.Container(width=440, content=ft.Column(tight=True, spacing=10, controls=[
            ft.Text(S("offer_body", lang, gpu=st.gpu_model or "NVIDIA", mb=total_mb), size=13),
            bar,
            note,
        ])),
        actions=[
            install_btn,
            ft.TextButton(key="gpu_offer_later", content=S("offer_later", lang), on_click=later),
            ft.TextButton(key="gpu_offer_never", content=S("offer_never", lang), on_click=never),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    show = getattr(page, "show_dialog", None)
    try:
        if callable(show):
            show(dialog)
        else:
            overlay = getattr(page, "overlay", None)
            if isinstance(overlay, list):
                overlay.append(dialog)
                page.update()
    except Exception:  # noqa: BLE001
        return False
    return True
