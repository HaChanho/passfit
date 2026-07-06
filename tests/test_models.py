import pytest
from pydantic import ValidationError
from passfit.models import CommuteInput, to_pattern

def test_requires_one_usage_pattern():
    with pytest.raises(ValidationError, match="월 교통비 총액 또는 월 탑승 횟수"):
        CommuteInput(age=30, residence="서울")

def test_accepts_each_pattern_form():
    CommuteInput(age=30, residence="서울", monthly_spend=120000)
    CommuteInput(age=30, residence="서울", monthly_rides=44, fare_per_ride=1550)
    CommuteInput(age=30, residence="서울",
                 rides=[{"mode": "subway", "fare_per_ride": 1550, "monthly_rides": 44}])

def test_priority_rides_over_spend():
    inp = CommuteInput(age=30, residence="서울", monthly_spend=999999,
                       rides=[{"mode": "subway", "fare_per_ride": 1550, "monthly_rides": 44}])
    p = to_pattern(inp)
    assert p.total_spend == 1550 * 44 and not p.spend_only

def test_spend_only_pattern():
    p = to_pattern(CommuteInput(age=30, residence="서울", monthly_spend=120000))
    assert p.spend_only and p.total_spend == 120000 and p.total_rides is None

def test_rejects_invalid_dates():
    for bad in ["2026-13-01", "2026-02-30"]:
        with pytest.raises(ValidationError):
            CommuteInput(age=30, residence="서울", monthly_spend=50000, as_of_date=bad)
    with pytest.raises(ValidationError):
        CommuteInput(age=30, residence="서울", monthly_spend=50000, usage_month="2026-13")

def test_accepts_valid_dates():
    CommuteInput(age=30, residence="서울", monthly_spend=50000,
                 as_of_date="2026-08-30", usage_month="2026-08")

def test_rejects_empty_residence():
    with pytest.raises(ValidationError):
        CommuteInput(age=30, residence="", monthly_spend=50000)
