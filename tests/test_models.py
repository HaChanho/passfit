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

def test_empty_residence_falls_back_to_nationwide():
    # LLM이 거주지 정보 없을 때 residence를 생략/빈문자로 넘기는 UX 회복 —
    # min_length=1 방어를 걷어내고 resolve_region이 unknown fallback 처리.
    inp = CommuteInput(age=30, residence="", monthly_spend=50000)
    assert inp.residence == ""

def test_income_level_korean_alias():
    # LLM이 한국어로 넘긴 '저소득' → enum 'low_income'으로 자동 매핑.
    inp = CommuteInput(age=30, residence="서울", monthly_spend=50000, income_level="저소득")
    assert inp.income_level == "low_income"
