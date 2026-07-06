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

def _meets_min_rides(pass_def: dict, pattern: Pattern, is_first_month: bool) -> bool:
    """월 최소 이용 요건 충족 여부 (정률·정액 공통). 총액만 알면 확인 불가 → 통과(경고 별도)."""
    rides = pattern.total_rides
    if rides is None:
        return True
    cond = pass_def["conditions"]
    return rides >= cond["min_rides_month"] or (is_first_month and cond["first_month_min_rides_exempt"])

def calc_modu_rebate(pass_def: dict, pattern: Pattern, category: str, rate: float,
                     ref: date, is_first_month: bool) -> CalcResult:
    label = "모두의카드 기본형(정률)"
    spend = pattern.total_spend
    rides = pattern.total_rides
    cond = pass_def["conditions"]
    if not _meets_min_rides(pass_def, pattern, is_first_month):
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
        # '1회 총요금 3,000원 미만 수단' 규칙 — 장거리 고액 승차는 모드 무관 제외
        if s.mode in fares["flat_standard_excluded_modes"] or s.fare_per_ride >= fares["flat_standard_fare_limit"]:
            excluded += s.fare_per_ride * s.monthly_rides
        else:
            covered += s.fare_per_ride * s.monthly_rides
    return covered, excluded

def calc_modu_flat(pass_def: dict, pattern: Pattern, category: str, region_class: str,
                   ref: date, variant: str) -> CalcResult:
    # 순수 정액 환급 계산 (15회 요건은 calc_modu_best에서 공통 적용). _flat_eligible_spend가 수단별 자격 판정.
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
    # 15회 최소 이용 요건은 정률·정액 공통 (정본 §2). 미달 시 세 방식 모두 환급 0.
    if not _meets_min_rides(pass_def, pattern, is_first_month):
        cond = pass_def["conditions"]
        return CalcResult("모두의카드", 0, pattern.total_spend,
                          note=f"월 {cond['min_rides_month']}회 미만이라 환급 없음 (가입 첫 달은 예외)")
    options = [
        calc_modu_rebate(pass_def, pattern, category, rate, ref, is_first_month),
        calc_modu_flat(pass_def, pattern, category, region_class, ref, "standard"),
        calc_modu_flat(pass_def, pattern, category, region_class, ref, "plus"),
    ]
    return max(options, key=lambda r: r.rebate)   # 제도 자체가 최대 환급 자동 적용


@dataclass(frozen=True)
class PassOption:
    pass_id: str
    name: str
    label: str
    rebate: int
    net_cost: int
    note: str = ""
    warnings: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()

def _srcs(p: dict) -> tuple[str, ...]:
    return tuple(s["url"] for s in p.get("sources", []))

def calc_climate_legacy(p: dict, pattern: Pattern, ref: date,
                        has_postpaid: bool) -> PassOption | None:
    prepaid_ok = ref <= date.fromisoformat(p["prepaid_valid_until"])
    postpaid_ok = has_postpaid and ref <= date.fromisoformat(p["postpaid"]["valid_until"])
    if not (prepaid_ok or postpaid_ok):
        return None
    price = p["variants"][0]["price"]                     # transit-only 기준
    if pattern.spend_only:
        uncovered = 0
        warns = ["수단 구성을 알 수 없어 서울권 커버 여부를 확인하지 못했습니다"]
    else:
        uncovered = sum(s.fare_per_ride * s.monthly_rides for s in pattern.segments
                        if s.mode in p["excluded_modes"])
        warns = []
    net = price + uncovered
    rebate = pattern.total_spend - net                    # '패스 없음' 대비 절감액 개념
    warns_t = tuple(warns)
    note = "후불형 (기존 보유자, 8/31까지)" if (not prepaid_ok and postpaid_ok) else ""
    if ref.strftime("%Y-%m") == "2026-08":
        warns_t += ("월 전체 사용 불가 — 선불 8/29·후불 8/31까지. 9월부터 모두의카드 전환 필요",)
    if uncovered:
        warns_t += (f"신분당선·GTX·광역버스 {uncovered:,}원은 별도 부담 (기동카 미적용)",)
    # rebate 음수 = 이용량이 적어 정액권이 종량제보다 손해라는 뜻 (그대로 노출, 랭킹은 net_cost 기준)
    return PassOption(p["id"], p["name"], "기후동행카드 30일권", rebate,
                      net, note, warns_t, _srcs(p))

def calc_dongbaek(p: dict, pattern: Pattern) -> PassOption:
    rebate = max(0, pattern.total_spend - p["threshold"])
    return PassOption(p["id"], p["name"], "동백패스(4.5만 초과 환급)", rebate,
                      pattern.total_spend - rebate,
                      note="K-패스 동시 가입 시 유리한 금액 자동 적용",
                      warnings=("부산 수단·실물 동백전 카드 결제만 인정",), sources=_srcs(p))

def calc_eung(p: dict, pattern: Pattern) -> PassOption:
    covered = min(pattern.total_spend, p["monthly_cap"])
    net = p["monthly_price"] + max(0, pattern.total_spend - p["monthly_cap"])
    return PassOption(p["id"], p["name"], "이응패스(월 2만원)", covered - p["monthly_price"], net,
                      note="월 5만원 한도, 세종권 6개 시 적용", sources=_srcs(p))

def compare_all(pattern: Pattern, ref: date, age: int, residence: str,
                income_level: str, children_count: int, is_first_month: bool,
                free_ride_status: str, has_postpaid_climate_card: bool) -> list[PassOption]:
    from passfit.normalize import resolve_region
    from passfit.data_loader import load_passes
    data = load_passes()
    passes = {p["id"]: p for p in data["passes"]}
    region = resolve_region(residence)
    opts: list[PassOption] = []

    modu = passes["modu-card"]
    best = calc_modu_best(modu, pattern, age, region.sido, income_level,
                          children_count, ref, is_first_month, region.region_class)
    note = best.note
    if region.sido == "서울":                              # plus merge_with_alias
        note = (note + " · 서울에서는 '기후동행카드 플러스'로 이용").strip(" ·")
    opts.append(PassOption("modu-card", modu["name"], best.label, best.rebate,
                           best.net_cost, note, best.warnings, _srcs(modu)))

    if region.sido in (None, "서울", "경기", "인천"):       # 수도권/미상만 기동카 후보
        legacy = calc_climate_legacy(passes["climate-card-legacy"], pattern, ref,
                                     has_postpaid_climate_card)
        if legacy:
            opts.append(legacy)
    if region.sido == "부산":
        opts.append(calc_dongbaek(passes["dongbaek-pass"], pattern))
    if region.sido == "세종":
        opts.append(calc_eung(passes["eung-pass"], pattern))
    return sorted(opts, key=lambda o: o.net_cost)

def collect_notices(ref: date, sido: str | None) -> list[str]:
    from passfit.data_loader import load_passes
    data = load_passes()
    notices = []
    legacy = next(p for p in data["passes"] if p["id"] == "climate-card-legacy")
    if ref > date.fromisoformat(legacy["prepaid_valid_until"]) and sido in (None, "서울", "경기", "인천"):
        notices.append(f"기후동행카드는 종료되었습니다. {legacy['transition_note']}")
    if ref <= date(2026, 9, 30):
        notices.append("한시 혜택(반값 기준금액·시차시간 +30%p)은 9월 이용분까지 — 10월부터 표준 원복 예정")
    for fr in data["free_ride_info"]:
        if fr["region"] in (sido, "전국"):
            notices.append(f"[무임 안내] {fr['rule']}")
    return notices
