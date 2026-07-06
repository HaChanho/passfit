from datetime import date

from passfit.dates import in_window, month_of, resolve_reference_date


def test_usage_month_uses_last_day():
    assert resolve_reference_date(usage_month="2026-08", as_of_date=None, today=date(2026, 7, 6)) == date(2026, 8, 31)


def test_as_of_date_wins():
    assert resolve_reference_date("2026-08", "2026-08-15", date(2026, 7, 6)) == date(2026, 8, 15)


def test_default_is_current_month_last_day():
    assert resolve_reference_date(None, None, date(2026, 7, 6)) == date(2026, 7, 31)


def test_month_of():
    assert month_of(date(2026, 8, 31)) == "2026-08"


def test_in_window_before_valid_from_is_false():
    assert in_window(date(2026, 7, 31), "2026-08-01", None) is False


def test_in_window_within_range_is_true():
    assert in_window(date(2026, 8, 15), "2026-08-01", "2026-08-31") is True


def test_in_window_after_valid_until_is_false():
    assert in_window(date(2026, 9, 1), None, "2026-08-31") is False


def test_in_window_none_bounds_are_open():
    assert in_window(date(2000, 1, 1), None, None) is True
