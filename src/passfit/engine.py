from dataclasses import dataclass
from datetime import date
from passfit.dates import in_window
from passfit.data_loader import load_fares

@dataclass(frozen=True)
class Segment:
    mode: str
    fare_per_ride: int
    monthly_rides: int
    offpeak_rides: int = 0

    def __post_init__(self):
        # offpeak는 전체 승차의 부분집합 — [0, monthly_rides]로 클램프
        clamped = max(0, min(self.offpeak_rides, self.monthly_rides))
        if clamped != self.offpeak_rides:
            object.__setattr__(self, "offpeak_rides", clamped)

@dataclass(frozen=True)
class Pattern:
    segments: tuple[Segment, ...]
    spend_only: bool = False
    spend_hint: int = 0            # spend_only일 때 총액

    @property
    def total_spend(self) -> int:
        if self.spend_only:
            return self.spend_hint
        return sum(s.fare_per_ride * s.monthly_rides for s in self.segments)

    @property
    def total_rides(self) -> int | None:
        return None if self.spend_only else sum(s.monthly_rides for s in self.segments)

    @property
    def offpeak_spend(self) -> int:
        if self.spend_only:
            return 0
        return sum(s.fare_per_ride * s.offpeak_rides for s in self.segments)

@dataclass(frozen=True)
class CalcResult:
    label: str            # 예: "모두의카드 기본형(정률)"
    rebate: int           # 월 환급액
    net_cost: int         # 월 실질 부담 = spend - rebate (정액권은 price + 미커버 부담)
    note: str = ""
    warnings: tuple[str, ...] = ()

def _rates_for(pass_def: dict, sido: str | None) -> tuple[dict, int]:
    rates = dict(pass_def["rebate_rates"])
    youth_max = pass_def["youth_age"]["max"]
    ov = (pass_def.get("regional_overrides") or {}).get(sido or "", {})
    youth_max = ov.get("youth_age_max", youth_max)
    rates.update(ov.get("rate_overrides", {}))
    return rates, youth_max

def determine_category(pass_def: dict, age: int, sido: str | None,
                       income_level: str, children_count: int) -> tuple[str, float]:
    rates, youth_max = _rates_for(pass_def, sido)
    candidates = ["general"]
    if income_level == "low_income":
        candidates.append("low_income")
    if children_count >= 3:
        candidates.append("multi_child_3")
    elif children_count == 2:
        candidates.append("multi_child_2")
    if pass_def["youth_age"]["min"] <= age <= youth_max:
        candidates.append("youth")
    if age >= pass_def["senior_age_min"]:
        candidates.append("senior")
    # 복수 유형 해당 시 최고 환급률 선택. 동률이면 candidates 추가 순서상 앞선 것(rate 동일하므로 rebate엔 영향 없음)
    best = max(candidates, key=lambda c: rates[c])
    return best, rates[best]

def _active_benefit(pass_def: dict, benefit_id: str, ref: date) -> dict | None:
    for b in pass_def.get("temporary_benefits", []):
        if b["id"] == benefit_id and in_window(ref, b.get("valid_from"), b.get("valid_until")):
            return b
    return None

def calc_modu_rebate(pass_def: dict, pattern: Pattern, category: str, rate: float,
                     ref: date, is_first_month: bool) -> CalcResult:
    label = "모두의카드 기본형(정률)"
    spend = pattern.total_spend
    rides = pattern.total_rides
    cond = pass_def["conditions"]
    if (rides is not None and rides < cond["min_rides_month"]
            and not (is_first_month and cond["first_month_min_rides_exempt"])):
        return CalcResult(label, 0, spend,
                          note=f"월 {cond['min_rides_month']}회 미만이라 환급 없음 (가입 첫 달은 예외)")
    bonus = _active_benefit(pass_def, "offpeak-bonus", ref)
    offpeak_spend = pattern.offpeak_spend if bonus else 0
    normal_spend = spend - offpeak_spend
    rebate = normal_spend * rate + offpeak_spend * (rate + (bonus["bonus_rate"] if bonus else 0))
    rebate = round(rebate)
    note = "시차시간 승차분 +30%p 적용 (9월 이용분까지)" if bonus and offpeak_spend else ""
    warnings = ("탑승 횟수를 알 수 없어 15회 요건을 확인하지 못했습니다 (월 15회 이상 이용 가정 추정치)",) if rides is None else ()
    return CalcResult(label, rebate, spend - rebate, note, warnings)

def _flat_eligible_spend(pattern: Pattern, variant: str) -> tuple[int, int]:
    """(커버 대상 spend, 제외 spend). plus는 전 수단, standard는 3,000원 미만 수단만."""
    if pattern.spend_only:
        return pattern.total_spend, 0
    if variant == "plus":
        return pattern.total_spend, 0
    fares = load_fares()
    covered = excluded = 0
    for s in pattern.segments:
        if s.mode in fares["flat_standard_excluded_modes"] or s.fare_per_ride >= fares["flat_standard_fare_limit"]:
            excluded += s.fare_per_ride * s.monthly_rides
        else:
            covered += s.fare_per_ride * s.monthly_rides
    return covered, excluded

def calc_modu_flat(pass_def: dict, pattern: Pattern, category: str, region_class: str,
                   ref: date, variant: str) -> CalcResult:
    idx = 0 if variant == "standard" else 1
    half = _active_benefit(pass_def, "half-price", ref)
    table = half["thresholds"] if half else pass_def["flat_thresholds"]
    threshold = table[region_class][category][idx]
    covered, excluded = _flat_eligible_spend(pattern, variant)
    rebate = max(0, covered - threshold)
    name = "일반형" if variant == "standard" else "플러스형"
    note = f"기준금액 {threshold:,}원" + (" (한시 반값, 9월 이용분까지)" if half else "")
    warnings: list[str] = []
    if variant == "standard" and excluded:
        warnings.append(f"광역버스·GTX·신분당선 등 {excluded:,}원은 일반형 미적용 (플러스형 필요)")
    if pattern.spend_only:
        warnings.append("수단 구성을 알 수 없어 일반형/플러스형 분기가 정확하지 않을 수 있습니다")
    return CalcResult(f"모두의카드 정액형({name})", rebate,
                      pattern.total_spend - rebate, note, tuple(warnings))

def calc_modu_best(pass_def: dict, pattern: Pattern, age: int, sido: str | None,
                   income_level: str, children_count: int, ref: date,
                   is_first_month: bool, region_class: str) -> CalcResult:
    category, rate = determine_category(pass_def, age, sido, income_level, children_count)
    options = [
        calc_modu_rebate(pass_def, pattern, category, rate, ref, is_first_month),
        calc_modu_flat(pass_def, pattern, category, region_class, ref, "standard"),
        calc_modu_flat(pass_def, pattern, category, region_class, ref, "plus"),
    ]
    return max(options, key=lambda r: r.rebate)   # 제도 자체가 최대 환급 자동 적용
