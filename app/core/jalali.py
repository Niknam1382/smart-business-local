"""
تقویمِ جلالی (شمسی) — پایتونِ خالص، بدونِ وابستگی (N19).

الگوریتمِ ``jalaali-js`` (بازه‌ی معتبر ۱۷۸ تا ۱۶۳۳ جلالی؛ همه‌ی سال‌های کبیسه‌ی ۱۳۰۰–۱۵۰۰ در تست‌ها
با مرجع سنجیده شدن). زمان‌ها در دیتابیس *همیشه UTC* ذخیره می‌شن؛ فقط نمایش جلالی است.
ایران از ۱۴۰۱ ساعتِ تابستانی ندارد ⇒ جابه‌جاییِ ثابتِ ‎+۰۳:۳۰ (بدونِ نیاز به tzdata در ویندوز).
"""

from __future__ import annotations

import datetime as _dt
from typing import Optional

TEHRAN_OFFSET_SECONDS = 3 * 3600 + 30 * 60
_TEHRAN = _dt.timezone(_dt.timedelta(seconds=TEHRAN_OFFSET_SECONDS))

MONTHS_FA = ("فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند")
MONTHS_EN = ("Farvardin", "Ordibehesht", "Khordad", "Tir", "Mordad", "Shahrivar", "Mehr", "Aban", "Azar", "Dey", "Bahman", "Esfand")

_BREAKS = (-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210, 1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178)


class JalaliError(ValueError):
    pass


def _div(a: int, b: int) -> int:
    """تقسیمِ صحیح با گردکردن به سمتِ صفر (مثلِ مرجعِ jalaali-js؛ ``//`` پایتون برای منفی‌ها فرق دارد)."""
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def _jal_cal(jy: int):
    """(leap, gy, march) — ``leap`` = سالهای از آخرین کبیسه (۰ = کبیسه)، ``march`` = روزِ ۱ فروردین در مارس."""
    if jy < _BREAKS[0] or jy >= _BREAKS[-1]:
        raise JalaliError(f"سالِ جلالیِ {jy} خارج از بازه‌ی پشتیبانی‌شده است.")
    gy = jy + 621
    leap_j = -14
    jp = _BREAKS[0]
    jump = 0
    for jm in _BREAKS[1:]:
        jump = jm - jp
        if jy < jm:
            break
        leap_j += _div(jump, 33) * 8 + _div(jump % 33, 4)
        jp = jm
    n = jy - jp
    leap_j += _div(n, 33) * 8 + _div(n % 33 + 3, 4)
    if jump % 33 == 4 and jump - n == 4:
        leap_j += 1
    leap_g = _div(gy, 4) - _div((_div(gy, 100) + 1) * 3, 4) - 150
    march = 20 + leap_j - leap_g
    if jump - n < 6:
        n = n - jump + _div(jump + 4, 33) * 33
    leap = ((n + 1) % 33 - 1) % 4
    if leap == -1:
        leap = 4
    return leap, gy, march


def is_leap(jy: int) -> bool:
    return _jal_cal(jy)[0] == 0


def month_length(jy: int, jm: int) -> int:
    if not 1 <= jm <= 12:
        raise JalaliError("ماهِ نامعتبر.")
    if jm <= 6:
        return 31
    if jm <= 11:
        return 30
    return 30 if is_leap(jy) else 29


def _g2d(gy: int, gm: int, gd: int) -> int:
    d = _div((gy + _div(gm - 8, 6) + 100100) * 1461, 4) + _div(153 * ((gm + 9) % 12) + 2, 5) + gd - 34840408
    return d - _div(_div(gy + 100100 + _div(gm - 8, 6), 100) * 3, 4) + 752


def _d2g(jdn: int):
    j = 4 * jdn + 139361631
    j += _div(_div(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908
    i = _div(j % 1461, 4) * 5 + 308
    gd = _div(i % 153, 5) + 1
    gm = (_div(i, 153) % 12) + 1
    gy = _div(j, 1461) - 100100 + _div(8 - gm, 6)
    return gy, gm, gd


def _j2d(jy: int, jm: int, jd: int) -> int:
    _leap, gy, march = _jal_cal(jy)
    return _g2d(gy, 3, march) + (jm - 1) * 31 - _div(jm, 7) * (jm - 7) + jd - 1


def to_jalali(gy: int, gm: int, gd: int):
    """میلادی ← ``(jy, jm, jd)``."""
    jdn = _g2d(gy, gm, gd)
    jy = gy - 621
    _leap, _gy, march = _jal_cal(jy)
    k = jdn - _g2d(gy, 3, march)
    if k >= 0:
        if k <= 185:
            return jy, 1 + _div(k, 31), k % 31 + 1
        k -= 186
    else:
        jy -= 1
        k += 179
        if _leap == 1:  # مرجع: ``r.leap`` سالِ جاری (قبلِ کم‌کردن)، نه سالِ قبل
            k += 1
    return jy, 7 + _div(k, 30), k % 30 + 1


def to_gregorian(jy: int, jm: int, jd: int):
    """جلالی ← ``(gy, gm, gd)`` (ورودیِ نامعتبر = ``JalaliError``)."""
    if not (1 <= jm <= 12 and 1 <= jd <= month_length(jy, jm)):
        raise JalaliError(f"تاریخِ جلالیِ نامعتبر: {jy}/{jm}/{jd}")
    return _d2g(_j2d(jy, jm, jd))


def tehran_dt(ts: float) -> _dt.datetime:
    return _dt.datetime.fromtimestamp(float(ts), tz=_dt.timezone.utc).astimezone(_TEHRAN)


def ts_to_jalali(ts: float):
    """زمانِ یونیکس (UTC) ← ``(jy, jm, jd)`` به وقتِ تهران."""
    d = tehran_dt(ts)
    return to_jalali(d.year, d.month, d.day)


def jalali_day_start_ts(jy: int, jm: int, jd: int) -> int:
    """آغازِ روزِ جلالی (۰۰:۰۰ تهران) به‌صورتِ زمانِ یونیکس."""
    gy, gm, gd = to_gregorian(jy, jm, jd)
    local = _dt.datetime(gy, gm, gd, tzinfo=_TEHRAN)
    return int(local.timestamp())


def month_range(jy: int, jm: int):
    """``[start_ts, end_ts)`` ماهِ جلالی."""
    start = jalali_day_start_ts(jy, jm, 1)
    ny, nm = (jy + 1, 1) if jm == 12 else (jy, jm + 1)
    return start, jalali_day_start_ts(ny, nm, 1)


def today_range(now: Optional[float] = None):
    import time as _time

    jy, jm, jd = ts_to_jalali(now if now is not None else _time.time())
    start = jalali_day_start_ts(jy, jm, jd)
    return start, start + 86400


_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_EN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def fa_digits(text) -> str:
    return str(text).translate(_FA_DIGITS)


def en_digits(text) -> str:
    return str(text).translate(_EN_DIGITS)


def format_ts(ts: float, with_time: bool = False, digits: str = "fa", month_names: bool = False) -> str:
    """``۱۴۰۵/۰۲/۱۵`` (و ``۱۴:۳۰``)؛ ``digits='en'`` ارقامِ لاتین."""
    jy, jm, jd = ts_to_jalali(ts)
    if month_names:
        out = f"{jd} {MONTHS_FA[jm - 1]} {jy}"
    else:
        out = f"{jy:04d}/{jm:02d}/{jd:02d}"
    if with_time:
        d = tehran_dt(ts)
        out += f" {d.hour:02d}:{d.minute:02d}"
    return fa_digits(out) if digits == "fa" else out


def parse_jalali(text: str):
    """``۱۴۰۵/۰۲/۱۵`` یا ``1405-2-15`` ← ``(jy, jm, jd)`` یا ``JalaliError``."""
    clean = en_digits(str(text or "")).strip().replace("-", "/").replace(".", "/")
    parts = clean.split("/")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise JalaliError("تاریخ را به‌صورتِ ۱۴۰۵/۰۲/۱۵ بنویس.")
    jy, jm, jd = (int(p) for p in parts)
    if not (1 <= jm <= 12 and 1 <= jd <= month_length(jy, jm)):
        raise JalaliError("این تاریخِ جلالی وجود ندارد.")
    return jy, jm, jd


def parse_date_ts(text: str) -> int:
    """تاریخِ جلالیِ تایپ‌شده ← آغازِ آن روز (UTC یونیکس)."""
    return jalali_day_start_ts(*parse_jalali(text))
