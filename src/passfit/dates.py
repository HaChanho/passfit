import calendar
from datetime import date


def last_day(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def resolve_reference_date(usage_month: str | None, as_of_date: str | None, today: date) -> date:
    if as_of_date:
        return date.fromisoformat(as_of_date)
    ym = usage_month or today.strftime("%Y-%m")
    y, m = map(int, ym.split("-"))
    return last_day(y, m)


def month_of(d: date) -> str:
    return d.strftime("%Y-%m")


def in_window(d: date, valid_from: str | None, valid_until: str | None) -> bool:
    if valid_from and d < date.fromisoformat(valid_from):
        return False
    if valid_until and d > date.fromisoformat(valid_until):
        return False
    return True
