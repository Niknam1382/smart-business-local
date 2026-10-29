"""صفحه‌ی «راهنما» (N10): جستجو، دسته‌ها، مقاله‌ها، سؤالاتِ متداول و عیب‌یابِ «ربات جواب نمی‌ده؟»."""

from __future__ import annotations

from typing import Callable, Optional

import flet as ft

from app import theme
from app.core import guide, troubleshoot
from app.screens import common

_S = {
    "title": ("راهنما", "Guide"), "subtitle": ("آموزش‌ها، سؤالاتِ متداول و عیب‌یابی — همه آفلاین.", "Tutorials, FAQ and troubleshooting — all offline."),
    "en_note": ("(راهنما فعلاً فارسی است)", "(the guide is in Persian for now)"),
    "search": ("جستجو در راهنما…", "Search the guide…"), "tab_articles": ("مقاله‌ها", "Articles"), "tab_faq": ("سؤالاتِ متداول", "FAQ"), "tab_fix": ("عیب‌یاب", "Troubleshooter"),
    "none": ("چیزی پیدا نشد؛ واژه‌ی دیگری امتحان کن یا عیب‌یاب را اجرا کن.", "Nothing found; try another word or run the troubleshooter."),
    "back": ("بازگشت", "Back"), "related": ("بیشتر بخوان:", "Read more:"), "results": ("{n} نتیجه", "{n} results"),
    "fix_intro": ("«ربات جواب نمی‌ده؟» — چند بررسیِ خودکار انجام می‌شه و برای هر مشکل راه‌حلِ ساده می‌گه. (به سرورِ پیام‌رسان‌ها وصل می‌شه؛ توکن‌ها جایی نمی‌رن.)", "“The bot isn't answering?” — runs a few automatic checks and gives a simple fix for each. (It contacts the messengers' servers; tokens are never shown.)"),
    "run": ("اجرای عیب‌یاب", "Run the troubleshooter"), "running": ("در حال بررسی…", "Checking…"), "more": ("راهنمای این مورد", "Read about this"),
    "st_ok": ("✅", "✅"), "st_warn": ("⚠️", "⚠️"), "st_fail": ("❌", "❌"), "st_skip": ("➖", "➖"),
}


def S(key: str, lang: str, **kw) -> str:
    fa, en = _S[key]
    text = en if lang == "en" else fa
    return text.format(**kw) if kw else text


def build(page: ft.Page, lang: str, settings, manager=None, open_article: Optional[str] = None,
          probe: Optional[Callable[[], list]] = None) -> ft.Control:
    """``probe``: جایگزینِ عیب‌یاب در تست‌ها (بدونِ شبکه)."""
    secondary = theme.text_secondary(page)
    st = {"tab": "articles", "article": open_article if guide.by_id(open_article or "") else None, "query": "", "cat": None}
    header = common.page_header(page, ft.Icons.MENU_BOOK_ROUNDED, S("title", lang), S("subtitle", lang) + (" " + S("en_note", lang) if lang == "en" else ""))
    body = ft.Column(spacing=14, key="gd_body")
    search_tf = ft.TextField(key="gd_search", hint_text=S("search", lang), prefix_icon=ft.Icons.SEARCH_ROUNDED, border_radius=12, width=420, autofocus=False,
                             on_change=lambda e: set_query(e.control.value or ""))

    def set_query(q: str) -> None:
        st["query"], st["article"] = q, None
        render()

    def go(article_id: str) -> None:
        if guide.by_id(article_id):
            st["article"], st["query"] = article_id, ""
            search_tf.value = ""
            render()

    def on_link(e) -> None:
        url = str(getattr(e, "data", "") or "")
        if url.startswith("guide:"):
            go(url[6:])
        elif url.startswith("https://"):
            page.launch_url(url)

    def article_line(a) -> ft.Control:
        return ft.ListTile(key=f"gd_open_{a.id}", title=ft.Text(a.title, size=14, weight=ft.FontWeight.W_600), subtitle=ft.Text(a.category_title, size=12, color=secondary),
                           dense=True, on_click=lambda _e, i=a.id: go(i))

    def article_view(a) -> list:
        related = [guide.by_id(i) for i in dict.fromkeys(a.links) if guide.by_id(i)]
        out = [
            ft.TextButton(key="gd_back", content=S("back", lang), icon=ft.Icons.ARROW_BACK_ROUNDED, on_click=lambda _e: (st.update(article=None), render())),
            ft.Text(a.category_title, size=12, color=secondary),
            ft.Text(a.title, key="gd_title", size=20, weight=ft.FontWeight.W_700),
            common.card(page, ft.Markdown(a.body, key="gd_md", selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB, on_tap_link=on_link), padding=16),
        ]
        if related:
            out.append(ft.Text(S("related", lang), size=13, color=secondary))
            out.append(ft.Row(spacing=6, wrap=True, controls=[ft.OutlinedButton(key=f"gd_rel_{r.id}", content=r.title, on_click=lambda _e, i=r.id: go(i)) for r in related]))
        return out

    def articles_tab() -> list:
        if st["query"].strip():
            found = guide.search(st["query"])
            return [ft.Text(S("results", lang, n=len(found)), size=12, color=secondary), *(map(article_line, found) if found else [ft.Text(S("none", lang), key="gd_none", size=13, color=secondary)])]
        rows: list = []
        for cat, title in guide.CATEGORIES:
            if cat in ("faq",):
                continue
            items = guide.in_category(cat)
            rows.append(ft.ExpansionTile(key=f"gd_cat_{cat}", title=ft.Text(title, size=14, weight=ft.FontWeight.W_600), subtitle=ft.Text(f"{len(items)}", size=12, color=secondary),
                                         controls=[article_line(a) for a in items], expanded=st["cat"] == cat))
        return rows

    def faq_tab() -> list:
        rows: list = []
        for group, items in guide.faq_groups():
            rows.append(ft.ExpansionTile(key=f"gd_faq_{group}", title=ft.Text(group, size=14, weight=ft.FontWeight.W_600), subtitle=ft.Text(f"{len(items)}", size=12, color=secondary),
                                         controls=[article_line(a) for a in items]))
        return rows

    fix_out = ft.Column(key="gd_fix_out", spacing=8)

    def run_fix(_e=None) -> None:
        fix_out.controls = [ft.Text(S("running", lang), size=13, color=secondary)]
        page.update()

        def work() -> None:
            try:
                findings = probe() if probe else troubleshoot.run_sync(settings, bots_running=bool(manager and manager.is_running()))
            except Exception as exc:  # noqa: BLE001
                findings = [troubleshoot.Finding("error", troubleshoot.FAIL, "عیب‌یاب", f"اجرا نشد: {type(exc).__name__}")]
            fix_out.controls = [fix_row(f) for f in findings]
            page.update()

        if probe:
            work()
        else:
            page.run_thread(work)

    def fix_row(f) -> ft.Control:
        icon = S(f"st_{f.status}", lang)
        controls = [ft.Text(f"{icon} {f.title}", size=14, weight=ft.FontWeight.W_600), ft.Text(f.detail, size=13, color=secondary)]
        if f.article and guide.by_id(f.article) and f.status != troubleshoot.OK:
            controls.append(ft.TextButton(key=f"gd_fix_more_{f.key}", content=S("more", lang), on_click=lambda _e, i=f.article: (st.update(tab="articles"), go(i))))
        return common.card(page, ft.Column(spacing=2, controls=controls), padding=12)

    def fix_tab() -> list:
        return [ft.Text(S("fix_intro", lang), size=13, color=secondary), ft.FilledButton(key="gd_fix_run", content=S("run", lang), icon=ft.Icons.PLAY_ARROW_ROUNDED, on_click=run_fix), fix_out]

    def render(update: bool = True) -> None:
        tabs = ft.Row(spacing=8, wrap=True, controls=[(ft.FilledButton if st["tab"] == k else ft.OutlinedButton)(
            key=f"gd_tab_{k}", content=S(f"tab_{k}", lang), on_click=lambda _e, kk=k: (st.update(tab=kk, article=None, query=""), setattr(search_tf, "value", ""), render())) for k in ("articles", "faq", "fix")])
        article = guide.by_id(st["article"]) if st["article"] else None
        if article:
            body.controls = [search_tf, *article_view(article)]
        else:
            body.controls = [search_tf, tabs, *(articles_tab() if st["query"].strip() else {"articles": articles_tab, "faq": faq_tab, "fix": fix_tab}[st["tab"]]())]
        if update:
            page.update()

    render(update=False)
    return ft.Container(expand=True, padding=ft.Padding.symmetric(horizontal=32, vertical=24), content=ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=14, controls=[header, body]))
