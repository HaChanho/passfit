from datetime import date
from passfit.engine import Pattern, Segment, calc_modu_flat, calc_modu_best
from passfit.data_loader import load_passes

MODU = next(p for p in load_passes()["passes"] if p["id"] == "modu-card")

def seg(mode, fare, rides): return Segment(mode, fare, rides)

def test_flat_standard_excludes_expensive_modes():
    # 지하철 40회 + GTX 20회: 일반형은 지하철분만 커버
    p = Pattern((seg("subway", 1550, 40), seg("gtx", 4450, 20)))
    r = calc_modu_flat(MODU, p, "general", "수도권", date(2026, 10, 31), variant="standard")
    assert r.rebate == max(0, 1550 * 40 - 62000)          # GTX분 제외
    r_plus = calc_modu_flat(MODU, p, "general", "수도권", date(2026, 10, 31), variant="plus")
    assert r_plus.rebate == max(0, p.total_spend - 100000)  # 전 수단

def test_half_price_applies_only_before_october():
    p = Pattern((seg("subway", 1550, 44),))                 # 68,200원
    sep = calc_modu_flat(MODU, p, "general", "수도권", date(2026, 9, 30), "standard")
    oct_ = calc_modu_flat(MODU, p, "general", "수도권", date(2026, 10, 31), "standard")
    assert sep.rebate == 68200 - 30000                      # 반값 기준금액
    assert oct_.rebate == 68200 - 62000                     # 원복

def test_best_of_three_crossover():
    # 저사용(월 20회): 정률 우세 / 고사용(월 90회, 2026-09 반값): 정액 우세
    low = calc_modu_best(MODU, Pattern((seg("subway", 1550, 20),)), 30, "서울",
                         "general", 0, date(2026, 10, 31), False, "수도권")
    assert low.label.endswith("(정률)")
    high = calc_modu_best(MODU, Pattern((seg("subway", 1550, 90),)), 30, "서울",
                          "general", 0, date(2026, 9, 30), False, "수도권")
    assert "정액" in high.label

def test_flat_path_respects_min_rides_via_best():
    # 14회 고액(GTX): 15회 미만이라 정액형도 환급 0 이어야 함
    p = Pattern((Segment("gtx", 8000, 14),))
    r = calc_modu_best(MODU, p, 30, "서울", "general", 0, date(2026, 10, 31), False, "수도권")
    assert r.rebate == 0 and "15회" in r.note

def test_flat_path_first_month_exempt_via_best():
    # 14회지만 가입 첫 달 → 계산 진행(환급 > 0)
    p = Pattern((Segment("gtx", 8000, 14),))
    r = calc_modu_best(MODU, p, 30, "서울", "general", 0, date(2026, 10, 31), True, "수도권")
    assert r.rebate > 0
