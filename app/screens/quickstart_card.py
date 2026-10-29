"""کارتِ «شروعِ سریع» بالای صفحه‌ی خانه (N10): گام‌ها از وضعیتِ واقعی حساب می‌شن؛ با «برو» و «؟» به صفحه/مقاله می‌ره."""

from __future__ import annotations

from typing import Callable, Optional

import flet as ft

from app import theme
from app.core import quickstart
from app.screens import common

_S = {
    "title": ("شروعِ سریع", "Quick start"), "progress": ("{done} از {total} گام انجام شد", "{done} of {total} steps done"),
    "go": ("برو", "Go"), "help": ("راهنما", "Guide"), "dismiss": ("بعداً، پنهان کن", "Hide for now"),
    "all_done": ("🎉 همه‌ی گام‌ها انجام شد؛ ربات آماده است.", "🎉 All steps are done; your bot is ready."),
}


def S(key: str, lang: str, **kw) -> str:
    fa, en = _S[key]
    text = en if lang == "en" else fa
    return text.format(**kw) if kw else text


def build(page: ft.Page, lang: str, settings, product_count: Optional[int], bots_running: bool,
          go: Callable[[str], None], open_article: Callable[[str], None], on_dismiss: Callable[[], None]) -> Optional[ft.Control]:
    items = quickstart.steps(settings, product_count, bots_running)
    done, total = quickstart.progress(items)
    secondary = theme.text_secondary(page)
    rows = []
    for step in items:
        title = step.title_en if lang == "en" else step.title_fa
        actions = [] if step.done else [
            ft.TextButton(key=f"qs_go_{step.key}", content=S("go", lang), on_click=lambda _e, t=step.target: go(t)),
            ft.IconButton(key=f"qs_help_{step.key}", icon=ft.Icons.HELP_OUTLINE_ROUNDED, tooltip=S("help", lang), on_click=lambda _e, a=step.article: open_article(a)),
        ]
        rows.append(ft.Row(key=f"qs_step_{step.key}", spacing=6, controls=[
            ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED if step.done else ft.Icons.RADIO_BUTTON_UNCHECKED_ROUNDED, size=18, color=theme.SUCCESS if step.done else secondary),
            ft.Text(title, size=13, expand=True, color=secondary if step.done else None), *actions]))
    head = ft.Row(controls=[ft.Text(S("title", lang), size=15, weight=ft.FontWeight.W_700, expand=True), ft.Text(S("progress", lang, done=done, total=total), key="qs_progress", size=12, color=secondary),
                            ft.TextButton(key="qs_dismiss", content=S("dismiss", lang), on_click=lambda _e: on_dismiss())])
    foot = [ft.Text(S("all_done", lang), key="qs_done", size=13, color=theme.SUCCESS)] if done == total else []
    return ft.Container(key="quickstart_card", margin=ft.Margin.symmetric(horizontal=32, vertical=8), content=common.card(page, ft.Column(spacing=6, controls=[head, *rows, *foot]), padding=14))
