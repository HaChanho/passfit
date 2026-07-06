from datetime import date
from passfit.engine import Pattern, Segment, determine_category, calc_modu_rebate
from passfit.data_loader import load_passes

MODU = next(p for p in load_passes()["passes"] if p["id"] == "modu-card")
def pat(rides=44, fare=1550, offpeak=0):
    return Pattern(segments=(Segment("subway", fare, rides, offpeak),), spend_only=False)

def test_category_youth_age_boundary_by_region():
    # 35세: 국가 기준 일반(20%), 경기 거주 청년(30%)
    assert determine_category(MODU, age=35, sido="서울", income_level="general", children_count=0)[0] == "general"
    assert determine_category(MODU, age=35, sido="경기", income_level="general", children_count=0)[0] == "youth"

def test_category_picks_highest_rate():
    # 저소득(0.533) > 3자녀(0.50) > 청년(0.30)
    cat, rate = determine_category(MODU, 30, "서울", "low_income", 3)
    assert cat == "low_income" and rate == 0.533

def test_gwangju_overrides():
    cat, rate = determine_category(MODU, 70, "광주", "general", 0)
    assert cat == "senior" and rate == 0.50

def test_rebate_below_15_rides_is_zero():
    r = calc_modu_rebate(MODU, pat(rides=14), "general", 0.20, ref=date(2026, 7, 31), is_first_month=False)
    assert r.rebate == 0 and "15회" in r.note

def test_rebate_first_month_exempt():
    r = calc_modu_rebate(MODU, pat(rides=14), "general", 0.20, ref=date(2026, 7, 31), is_first_month=True)
    assert r.rebate == round(14 * 1550 * 0.20)

def test_offpeak_bonus_applies_only_during_window():
    # 2026-07 (한시 유효): 시차 10회는 +30%p
    r = calc_modu_rebate(MODU, pat(rides=44, offpeak=10), "general", 0.20, date(2026, 7, 31), False)
    expected = round((34 * 1550) * 0.20 + (10 * 1550) * 0.50)
    assert r.rebate == expected
    # 2026-10 (원복): 시차 무시
    r2 = calc_modu_rebate(MODU, pat(rides=44, offpeak=10), "general", 0.20, date(2026, 10, 31), False)
    assert r2.rebate == round(44 * 1550 * 0.20)

def test_no_legacy_caps():  # 폐지 규칙 회귀 테스트
    r = calc_modu_rebate(MODU, pat(rides=120, fare=3000), "general", 0.20, date(2026, 7, 31), False)
    assert r.rebate == round(120 * 3000 * 0.20)   # 60회/20만원 상한 미적용

def test_offpeak_rides_clamped_to_total():
    s = Segment("subway", 1550, 15, 1000)   # offpeak가 total 초과 → 클램프
    assert s.offpeak_rides == 15
    r = calc_modu_rebate(MODU, Pattern((s,)), "low_income", 0.533, date(2026, 7, 31), False)
    assert r.net_cost >= 0                    # 음수 환급 불가
    assert r.rebate <= s.monthly_rides * s.fare_per_ride   # 환급 ≤ 지출

def test_spend_only_warns_about_assumption():
    p = Pattern(segments=(), spend_only=True, spend_hint=100000)
    r = calc_modu_rebate(MODU, p, "general", 0.20, date(2026, 7, 31), False)
    assert any("15회" in w for w in r.warnings)
    assert r.rebate == 20000
