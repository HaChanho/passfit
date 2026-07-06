from dataclasses import dataclass
from datetime import date
from passfit.dates import in_window

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
