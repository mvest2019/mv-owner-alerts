# -*- coding: utf-8 -*-
"""Dates and cycles, the way this data actually stores them.

TWO SPELLINGS OF A MONTH, AND ONE BOOBY TRAP

  MonthlyProductionVolumes   cycle_year "2026" (str) + cycle_month "07" (str)
                             cycle_year_month "202607"          <- no dash
  Activity_Test              cycle_year 2026 (int) + cycle_month 7 (int)
                             submit_date / approved_date / completion_date as MM/DD/YYYY strings

  "202607" >= "2026-05" is TRUE - '0' sorts above '-'. A range filter written for one format
  silently matches everything in the other, returns plausible rows, and raises nothing. Every
  cycle is normalised to the six-digit "YYYYMM" form at the point it is read, and every free
  date string is parsed HERE rather than sliced in an aggregation pipeline.

  The slicing trap is not hypothetical. Activity date strings in this cluster carry leading and
  trailing spaces; {"$substr": ["$submit_date", 6, 4]} on a leading-space value slices "/202"
  instead of "2026" and those rows land in a junk bucket that raises nothing and looks fine.
"""
import datetime
import re

_MDY = re.compile(r"^\s*(\d{1,2})[/-](\d{1,2})[/-](\d{4})(?:[\sT].*)?$")
# The trailing (?:[\sT].*)? matters: LeaseRadiusData stores its rebuild stamp as
# "2026-07-15 15:09:40". Anchoring the pattern to end-of-string rejected it, parse_date returned
# None, and the nearby-permit alert shipped with no event date at all - caught by the
# eight-field check in selftest.py rather than by anyone looking at the page.
_YMD = re.compile(r"^\s*(\d{4})[-/](\d{1,2})(?:[-/](\d{1,2}))?(?:[\sT].*)?$")
_CYC = re.compile(r"^\s*(\d{4})(\d{2})\s*$")
MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def parse_date(value):
    """Any of this data's date spellings -> datetime.date, or None. Never raises."""
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    s = str(value).strip()
    if not s or s.lower() in ("none", "null", "nan", "-", ""):
        return None
    m = _MDY.match(s)
    if m:
        mm, dd, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime.date(yy, mm, dd)
        except ValueError:
            return None
    m = _YMD.match(s)
    if m:
        yy, mm = int(m.group(1)), int(m.group(2))
        dd = int(m.group(3) or 1)
        try:
            return datetime.date(yy, mm, dd)
        except ValueError:
            return None
    m = _CYC.match(s)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            return None
    return None


def cycle(year, month):
    """(2026, '07') or ('2026', 7) -> '202607'. None when it cannot be trusted."""
    if year in (None, "") or month in (None, ""):
        return None
    try:
        y = int(str(year).strip())
        m = int(str(month).strip())
    except (TypeError, ValueError):
        return None
    if not (1 <= m <= 12) or not (1900 <= y <= 2200):
        return None
    return "%04d%02d" % (y, m)


def cycle_of(date_obj):
    return None if date_obj is None else "%04d%02d" % (date_obj.year, date_obj.month)


def cycle_shift(cyc, months):
    """'202605' shifted by a signed number of months."""
    y, m = int(cyc[:4]), int(cyc[4:6])
    total = y * 12 + (m - 1) + months
    return "%04d%02d" % (total // 12, total % 12 + 1)


def cycle_range(end_cycle, count):
    """The `count` cycles ending at end_cycle, inclusive, oldest first."""
    return [cycle_shift(end_cycle, -i) for i in range(count - 1, -1, -1)]


def cycle_pretty(cyc):
    if not cyc or len(cyc) < 6:
        return "-"
    return "%s %s" % (MONTHS[int(cyc[4:6])], cyc[:4])


def cycle_short(cyc):
    if not cyc or len(cyc) < 6:
        return "-"
    return "%s %s" % (MONTHS[int(cyc[4:6])], cyc[2:4])


def date_pretty(d):
    if d is None:
        return "-"
    return "%s %d, %d" % (MONTHS[d.month], d.day, d.year)


def date_short(d):
    if d is None:
        return "-"
    return "%s %d" % (MONTHS[d.month], d.day)


def ago(d, today=None):
    """'3 days ago' / 'today'. The UI prints this next to a real date, never instead of one."""
    if d is None:
        return ""
    today = today or datetime.date.today()
    n = (today - d).days
    if n < 0:
        return "scheduled"
    if n == 0:
        return "today"
    if n == 1:
        return "yesterday"
    if n < 30:
        return "%d days ago" % n
    if n < 365:
        return "%d months ago" % max(1, round(n / 30.0))
    return "%.1f years ago" % (n / 365.0)
