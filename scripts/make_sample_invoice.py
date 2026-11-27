#!/usr/bin/env python3
"""ساختِ چند فاکتورِ نمونه (A4، A5، انگلیسی) برایِ دیدنِ ظاهرِ PDF — بدونِ دیتابیس و بدونِ ربات (۱٫۲٫۲).

    python scripts/make_sample_invoice.py            # فایل‌ها در پوشه‌یِ جاری
    python scripts/make_sample_invoice.py --out D:\\samples

اگر فاکتور خوب درنیامد، همین فایل‌ها را برایِ من بفرست تا طراحی را اصلاح کنیم.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="فاکتورهایِ نمونه")
    parser.add_argument("--out", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    from dataclasses import replace

    from app.core import invoice_pdf
    from app.core.invoice_service import preview_invoice
    from app.core.settings import AppSettings

    written = []
    variants = [
        ("sample-A4-fa.pdf", {"invoice_paper": "A4"}, "fa", False),
        ("sample-A5-fa.pdf", {"invoice_paper": "A5"}, "fa", False),
        ("sample-A4-en.pdf", {"invoice_paper": "A4", "language": "en"}, "en", False),
        ("sample-credit-fa.pdf", {"invoice_paper": "A4"}, "fa", True),
    ]
    for name, overrides, lang, credit in variants:
        settings = AppSettings(**overrides) if overrides else AppSettings()
        invoice = preview_invoice(settings, lang=lang)
        if credit:
            invoice = replace(invoice, kind="credit", number="CN-SAMPLE-0001")
        try:
            data = invoice_pdf.render(invoice)
        except invoice_pdf.InvoicePdfError as exc:
            print(f"❌ {name}: {exc}")
            continue
        path = args.out / name
        path.write_bytes(data)
        written.append(path)
        print(f"✅ {path}")
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
