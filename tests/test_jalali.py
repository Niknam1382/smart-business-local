"""N19: تقویمِ جلالی — مرجع‌های شناخته‌شده، کبیسه‌ها، رفت‌وبرگشتِ کاملِ ۱۳۰۰–۱۵۰۰ و مرزِ ساعتِ تهران."""

import datetime as dt

import pytest

from app.core import jalali as j

# ۱ فروردین (نوروز) به میلادی — تقویمِ رسمی
NOWRUZ = {1300: (1921, 3, 21), 1348: (1969, 3, 21), 1370: (1991, 3, 21), 1399: (2020, 3, 20),
          1400: (2021, 3, 21), 1403: (2024, 3, 20), 1404: (2025, 3, 21), 1405: (2026, 3, 21), 1408: (2029, 3, 20)}
LEAP_1395_1420 = [1395, 1399, 1403, 1408, 1412, 1416, 1420]


@pytest.mark.parametrize("jy,greg", sorted(NOWRUZ.items()))
def test_nowruz_anchors(jy, greg):
    assert j.to_gregorian(jy, 1, 1) == greg
    assert j.to_jalali(*greg) == (jy, 1, 1)


def test_leap_years_and_month_lengths():
    assert [y for y in range(1395, 1421) if j.is_leap(y)] == LEAP_1395_1420
    assert j.month_length(1403, 12) == 30 and j.month_length(1404, 12) == 29  # اسفندِ کبیسه
    assert [j.month_length(1404, m) for m in range(1, 13)] == [31] * 6 + [30] * 5 + [29]


def test_roundtrip_every_day_1300_to_1500():
    day, last = dt.date(1921, 3, 21), dt.date(2122, 3, 20)
    prev = (1300, 1, 1)
    while day <= last:
        cur = j.to_jalali(day.year, day.month, day.day)
        assert j.to_gregorian(*cur) == (day.year, day.month, day.day)
        if day != dt.date(1921, 3, 21):  # روزها یکی‌یکی جلو می‌روند (بدونِ جهش/تکرار)
            assert cur > prev and (cur[1], cur[2]) in {(prev[1], prev[2] + 1), (prev[1] + 1, 1), (1, 1)}
        prev = cur
        day += dt.timedelta(days=1)


def test_invalid_dates_rejected():
    for bad in [(1404, 13, 1), (1404, 0, 1), (1404, 7, 31), (1404, 12, 30), (1404, 1, 0)]:
        with pytest.raises(j.JalaliError):
            j.to_gregorian(*bad)
    assert j.to_gregorian(1403, 12, 30) == (2025, 3, 20)  # اسفندِ کبیسه ۳۰ روز دارد


def test_tehran_midnight_boundary():
    # ۲۰:۳۰ UTC همان روز = ۰۰:۰۰ تهرانِ روزِ بعد
    before = dt.datetime(2026, 3, 20, 20, 29, tzinfo=dt.timezone.utc).timestamp()
    after = dt.datetime(2026, 3, 20, 20, 30, tzinfo=dt.timezone.utc).timestamp()
    assert j.ts_to_jalali(before) == (1404, 12, 29) and j.ts_to_jalali(after) == (1405, 1, 1)
    assert j.jalali_day_start_ts(1405, 1, 1) == int(after)


def test_format_parse_and_ranges():
    ts = j.jalali_day_start_ts(1405, 2, 15) + 14 * 3600 + 30 * 60
    assert j.format_ts(ts) == "۱۴۰۵/۰۲/۱۵"
    assert j.format_ts(ts, with_time=True, digits="en") == "1405/02/15 14:30"
    assert j.format_ts(ts, month_names=True) == "۱۵ اردیبهشت ۱۴۰۵"
    assert j.parse_jalali("۱۴۰۵/۲/۱۵") == (1405, 2, 15) == j.parse_jalali("1405-02-15")
    assert j.parse_date_ts("1405/02/15") == j.jalali_day_start_ts(1405, 2, 15)
    for bad in ["", "abc", "1405/13/1", "1404/12/30", "1405/2"]:
        with pytest.raises(j.JalaliError):
            j.parse_jalali(bad)
    start, end = j.month_range(1403, 12)
    assert (end - start) // 86400 == 30
    s2, e2 = j.today_range(ts)
    assert s2 <= ts < e2 and e2 - s2 == 86400
    assert j.fa_digits("12:30") == "۱۲:۳۰" and j.en_digits("۱۲٤") == "124"
