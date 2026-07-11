import os
from datetime import date
from typing import Literal
from zoneinfo import ZoneInfo
from datetime import datetime
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import ValidationError
from passfit.models import CommuteInput, RideSegment, to_pattern, INCOME_LEVEL_ALIASES
from passfit.engine import (compare_all, collect_notices, calc_modu_best,
                            determine_category, calc_modu_rebate, calc_modu_flat,
                            calc_climate_legacy, Pattern, Segment)
from passfit.normalize import resolve_region
from passfit.dates import resolve_reference_date
from passfit.data_loader import load_passes
from passfit.render import render_comparison, render_pass_details

mcp = FastMCP("PassFit")
RO = {"readOnlyHint": True, "destructiveHint": False,
      "openWorldHint": False, "idempotentHint": True}


def _today() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def _region_note(residence: str) -> str:
    r = resolve_region(residence)
    if not residence.strip():
        return "거주지가 입력되지 않아 전국 기준(모두의카드)으로만 계산했습니다."
    if r.confidence == "unknown":
        return f"'{residence}' 지역을 해석하지 못해 전국 기준(모두의카드)으로만 계산했습니다."
    return f"거주지는 '{r.sido}'({r.region_class})으로 해석했습니다."


CAT_KO = {"general": "일반", "youth": "청년", "senior": "어르신",
          "multi_child_2": "2자녀", "multi_child_3": "3자녀+", "low_income": "저소득"}

TYPE_KO = {"hybrid": "정률·정액 환급형", "flat_pass": "정액 무제한권",
           "threshold_rebate": "초과분 환급형", "prepaid_capped": "선불 정액형"}


def _category_note(age: int, sido: str | None, income_level: str, children_count: int) -> str:
    modu = next(p for p in load_passes()["passes"] if p["id"] == "modu-card")
    cat, rate = determine_category(modu, age, sido, income_level, children_count)
    return f"모두의카드 기준 '{CAT_KO[cat]}' 유형(환급률 {rate:.1%})으로 계산했습니다."


def _build_commute_input(
    monthly_rides: int | None,
    fare_per_ride: int | None,
    monthly_spend: int | None,
    rides: list[RideSegment] | None,
    offpeak_rides: int,
    age: int,
    residence: str,
    income_level: Literal["general", "low_income"],
    children_count: int,
    is_first_month: bool,
    free_ride_status: Literal["none", "eligible", "uses_free_ride_card"],
    has_postpaid_climate_card: bool,
    usage_month: str | None,
    as_of_date: str | None,
    detail: Literal["concise", "detailed"],
) -> CommuteInput:
    try:
        return CommuteInput(
            monthly_rides=monthly_rides, fare_per_ride=fare_per_ride,
            monthly_spend=monthly_spend, rides=rides, offpeak_rides=offpeak_rides,
            age=age, residence=residence, income_level=income_level,
            children_count=children_count, is_first_month=is_first_month,
            free_ride_status=free_ride_status,
            has_postpaid_climate_card=has_postpaid_climate_card,
            usage_month=usage_month, as_of_date=as_of_date, detail=detail,
        )
    except ValidationError as e:
        raise ToolError("; ".join(err["msg"].removeprefix("Value error, ")
                                  for err in e.errors()))


@mcp.tool(annotations={"title": "교통패스 비교", **RO})
def compare_passes_for_commute(
    monthly_rides: int | None = None,
    fare_per_ride: int | None = None,
    monthly_spend: int | None = None,
    rides: list[RideSegment] | None = None,
    offpeak_rides: int = 0,
    age: int = 30,
    residence: str = "",
    income_level: Literal["general", "low_income"] = "general",
    children_count: int = 0,
    is_first_month: bool = False,
    free_ride_status: Literal["none", "eligible", "uses_free_ride_card"] = "none",
    has_postpaid_climate_card: bool = False,
    usage_month: str | None = None,
    as_of_date: str | None = None,
    detail: Literal["concise", "detailed"] = "concise",
) -> str:
    """패스핏 – 교통패스 비교. 통근 패턴(승차 횟수·요금·거주지·나이)으로 2026년 모두의카드·
    기후동행카드·지자체 패스를 교차 계산해 월 실질 부담 순위와 절약액을 정리합니다.
    주 5일 왕복이면 monthly_rides는 약 44, 여러 수단을 섞으면 rides 리스트를 씁니다.
    income_level은 'general'/'low_income'이며 '저소득' 등은 low_income으로 넣습니다."""
    inp = _build_commute_input(
        monthly_rides, fare_per_ride, monthly_spend, rides, offpeak_rides,
        age, residence, income_level, children_count, is_first_month,
        free_ride_status, has_postpaid_climate_card, usage_month, as_of_date, detail,
    )
    pattern = to_pattern(inp)
    ref = resolve_reference_date(inp.usage_month, inp.as_of_date, _today())
    region = resolve_region(inp.residence)
    opts = compare_all(pattern, ref, inp.age, inp.residence, inp.income_level,
                       inp.children_count, inp.is_first_month,
                       inp.has_postpaid_climate_card)   # free_ride_status는 caveat에서만 사용 (T7 리뷰)
    caveats = []
    if inp.age < 19:      # 모두의카드는 19세 이상만 가입 — 미성년자에게 최적 추천이 오도되지 않도록
        caveats.append("모두의카드는 만 19세 이상만 가입 가능합니다 — 미성년자는 지자체 즉시할인·"
                       "경기 어린이청소년 교통비 지원·기후동행카드 등을 확인하세요.")
    if pattern.spend_only:
        caveats.append("총액만 입력되어 수단 구성·15회 요건 확인이 제한적입니다. "
                       "탑승 횟수와 수단을 알려주시면 더 정확해집니다.")
    if inp.income_level == "general" and inp.children_count == 0 and not inp.is_first_month:
        caveats.append("저소득·다자녀·가입 첫 달이면 결과가 달라질 수 있습니다.")
    if inp.free_ride_status in ("eligible", "uses_free_ride_card"):
        caveats.append("무임 대상은 무임카드(환급 없음)와 유임+환급 중 유리한 쪽을 선택하세요.")
    if inp.age >= 75 and region.sido in ("경남", "울산"):   # 데이터 모델 밖 티어 — 오답 방지 caveat
        caveats.append("75세 이상은 경남·울산에서 대중교통비 100% 환급 대상일 수 있습니다. "
                       "이 계산은 일반 어르신(30%) 기준이니 korea-pass.kr에서 확인하세요.")
    notices = collect_notices(ref, region.sido)
    region_note = (_region_note(inp.residence) + " " +
                  _category_note(inp.age, region.sido, inp.income_level, inp.children_count))
    return render_comparison(opts, region_note, notices, caveats,
                             inp.detail, load_passes()["last_verified"])


@mcp.tool(annotations={"title": "패스 목록", **RO})
def list_transit_passes(region: str | None = None) -> str:
    """패스핏 – 교통패스 비교. 지원하는 2026년 교통패스 목록을 지역별로 정리해 보여줍니다."""
    data = load_passes()
    sido = resolve_region(region).sido if region else None
    lines = ["| 패스 | 유형 | 대상 | 상태 |", "|---|---|---|---|"]
    for p in data["passes"]:
        if p.get("status") == "display_only":
            name = f"{p['name']} (모두의카드 기반·서울)"          # show_as_alias
        else:
            name = p["name"]
        res = p.get("eligibility", {}).get("residency", "전국")
        if sido and res not in ("전국", sido, "서울이용자"):
            continue
        status = {"ending": "8월 종료 예정", "display_only": "운영 중"}.get(p.get("status"), "운영 중")
        ptype = TYPE_KO.get(p.get("type"), "정률·정액 환급형(모두의카드 기반)")
        lines.append(f"| {name} | {ptype} | {res} | {status} |")
    return "\n".join(lines)


@mcp.tool(annotations={"title": "패스 상세", **RO})
def get_pass_details(pass_id: Literal["modu-card", "climate-card-legacy",
                                      "climate-card-plus", "dongbaek-pass",
                                      "eung-pass"]) -> str:
    """패스핏 – 교통패스 비교. 패스 하나의 자격·환급률·기준금액·신청 방법·유효기간을
    서술형으로 설명합니다. pass_id는 modu-card(모두의카드)·climate-card-legacy(기후동행카드)·
    climate-card-plus(기후동행카드 플러스)·dongbaek-pass(부산 동백패스)·eung-pass(세종 이응패스)."""
    data = load_passes()
    p = next(x for x in data["passes"] if x["id"] == pass_id)
    base = None
    if p.get("details_policy") == "show_alias_plus_base":
        base = next(x for x in data["passes"] if x["id"] == p["calculation_alias_of"])
    return render_pass_details(p, base)


@mcp.tool(annotations={"title": "절약 시뮬레이션", **RO})
def simulate_pass_savings(
    pass_id: Literal["modu-card", "climate-card-legacy", "climate-card-plus",
                     "dongbaek-pass", "eung-pass"],
    monthly_rides: int | None = None,
    fare_per_ride: int | None = None,
    monthly_spend: int | None = None,
    rides: list[RideSegment] | None = None,
    offpeak_rides: int = 0,
    age: int = 30,
    residence: str = "",
    income_level: Literal["general", "low_income"] = "general",
    children_count: int = 0,
    is_first_month: bool = False,
    free_ride_status: Literal["none", "eligible", "uses_free_ride_card"] = "none",
    has_postpaid_climate_card: bool = False,
    usage_month: str | None = None,
    as_of_date: str | None = None,
    detail: Literal["concise", "detailed"] = "concise",
) -> str:
    """패스핏 – 교통패스 비교. 지정한 패스 하나의 월·연 절약액을 통근 패턴 기준으로 계산합니다.
    여러 패스를 한 번에 비교하려면 compare_passes_for_commute를 사용하세요.
    pass_id는 modu-card·climate-card-legacy·climate-card-plus·dongbaek-pass·eung-pass."""
    data = load_passes()
    p = next(x for x in data["passes"] if x["id"] == pass_id)
    if p.get("simulate_policy") == "alias_to_base":            # plus → modu-card
        note = f"'{p['name']}'는 모두의카드 기반이라 모두의카드로 계산합니다.\n\n"
        p = next(x for x in data["passes"] if x["id"] == p["calculation_alias_of"])
    else:
        note = ""
    inp = _build_commute_input(
        monthly_rides, fare_per_ride, monthly_spend, rides, offpeak_rides,
        age, residence, income_level, children_count, is_first_month,
        free_ride_status, has_postpaid_climate_card, usage_month, as_of_date, detail,
    )
    pattern = to_pattern(inp)
    ref = resolve_reference_date(inp.usage_month, inp.as_of_date, _today())
    region = resolve_region(inp.residence)
    if p["id"] == "modu-card":
        r = calc_modu_best(p, pattern, inp.age, region.sido, inp.income_level,
                           inp.children_count, ref, inp.is_first_month, region.region_class)
        yearly = r.rebate * 12
        return (f"{note}**{p['name']} — {r.label}**\n"
                f"- 월 환급: {r.rebate:,}원 / 월 실질 부담: {r.net_cost:,}원\n"
                f"- 연간 절약(현 조건 유지 가정): 약 {yearly:,}원\n"
                + (f"- {r.note}\n" if r.note else "")
                + "".join(f"- ⚠️ {w}\n" for w in r.warnings))
    if p["id"] == "climate-card-legacy":
        # 기후동행카드는 거주지 무관(서울권 이용 전제)이라 거주지 게이트 없이 직접 계산.
        m = calc_climate_legacy(p, pattern, ref, inp.has_postpaid_climate_card)
        if m is None:
            return (f"{note}기후동행카드는 {ref} 기준 이미 종료되었습니다 "
                    f"(선불 8/29·후불 8/31까지). 모두의카드 계열로 전환하세요.")
    else:
        # 동백(부산)·이응(세종)은 진짜 거주지 전용 → compare_all 재사용(거주지 게이트 유지).
        opts = compare_all(pattern, ref, inp.age, inp.residence, inp.income_level,
                           inp.children_count, inp.is_first_month,
                           inp.has_postpaid_climate_card)   # free_ride_status는 caveat에서만 사용 (T7 리뷰)
        m = next((o for o in opts if o.pass_id == p["id"]), None)
        if m is None:
            resid = {"dongbaek-pass": "부산", "eung-pass": "세종"}.get(p["id"], "")
            return (f"{note}{p['name']}는 {resid} 거주자 전용입니다. "
                    f"거주지에 '{resid}' 입력 후 다시 시도하거나 "
                    f"compare_passes_for_commute로 대안을 확인하세요.")
    return (f"{note}**{m.name} — {m.label}**\n- 월 환급: {m.rebate:,}원 / "
            f"월 실질 부담: {m.net_cost:,}원\n"
            + "".join(f"- ⚠️ {w}\n" for w in m.warnings))


@mcp.tool(annotations={"title": "자격 확인", **RO})
def check_pass_eligibility(age: int, residence: str = "",
                           income_level: Literal["general", "low_income"] = "general",
                           children_count: int = 0, is_first_month: bool = False,
                           free_ride_status: Literal["none", "eligible",
                                                     "uses_free_ride_card"] = "none") -> str:
    """패스핏 – 교통패스 비교. 나이·거주지·소득으로 모두의카드·부산 동백패스·세종 이응패스의
    가입 자격과 환급률을 확인합니다 (기후동행카드는 이용 가능 여부라 compare에서 다룸).
    income_level은 'general'/'low_income'이며 '저소득' 등은 low_income으로 넣습니다."""
    # income_level 한국어 alias → enum 매핑 (LLM이 '저소득'을 그대로 넘기는 케이스)
    income_level = INCOME_LEVEL_ALIASES.get(income_level, income_level)
    if income_level not in ("general", "low_income"):
        raise ToolError(f"income_level은 'general' 또는 'low_income'이어야 합니다 (받음: '{income_level}').")
    data = load_passes()
    region = resolve_region(residence)
    modu = next(p for p in data["passes"] if p["id"] == "modu-card")
    lines = [_region_note(residence), ""]
    if age < modu["eligibility"]["age_min"]:
        lines.append(f"- 모두의카드: ❌ 만 19세 이상만 가입 가능 (현재 {age}세). "
                     "어린이·청소년은 지자체 즉시할인(광주 등)·경기 어린이청소년 교통비 지원을 확인하세요.")
    else:
        cat, rate = determine_category(modu, age, region.sido, income_level, children_count)
        lines.append(f"- 모두의카드: ✅ '{CAT_KO[cat]}' 유형, 환급률 {rate:.1%}"
                     + (f" (거주지 {region.sido} 상위 혜택 반영)" if region.sido else ""))
    for pid, name, sido in [("dongbaek-pass", "부산 동백패스", "부산"),
                            ("eung-pass", "세종 이응패스", "세종")]:
        p = next(x for x in data["passes"] if x["id"] == pid)
        amin = p.get("eligibility", {}).get("age_min", 0)
        if region.sido != sido:
            lines.append(f"- {name}: ❌ {sido} 거주자 전용")
        elif age < amin:
            lines.append(f"- {name}: ❌ 만 {amin}세 이상 대상 (현재 {age}세)")
        else:
            lines.append(f"- {name}: ✅")
    if free_ride_status != "none":
        for fr in data["free_ride_info"]:
            if fr["region"] in (region.sido, "전국"):
                lines.append(f"- [무임] {fr['rule']}")
        lines.append("- 무임카드 이용분은 환급 대상이 아니므로, 무임 vs 유임+환급을 비교해 선택하세요.")
    return "\n".join(lines)


@mcp.tool(annotations={"title": "손익분기 승차 횟수", **RO})
def find_breakeven_rides(
    fare_per_ride: int,
    age: int = 30,
    residence: str = "",
    income_level: Literal["general", "low_income"] = "general",
    children_count: int = 0,
    as_of_date: str | None = None,
) -> str:
    """패스핏 – 교통패스 비교. 모두의카드에서 월 몇 회부터 이득인지(15회 요건)와 정률형→정액형
    전환점을 요금 기준으로 계산하고, 해당 요금대의 최적 정액형(일반형/플러스형)을 함께 알려줍니다.
    fare_per_ride는 1회 요금(원), income_level은 'general'/'low_income'."""
    if fare_per_ride <= 0:
        raise ToolError("fare_per_ride는 양수여야 합니다.")
    income_level = INCOME_LEVEL_ALIASES.get(income_level, income_level)
    if income_level not in ("general", "low_income"):
        raise ToolError(f"income_level은 'general' 또는 'low_income'이어야 합니다 (받음: '{income_level}').")
    modu = next(p for p in load_passes()["passes"] if p["id"] == "modu-card")
    ref = resolve_reference_date(None, as_of_date, _today())
    region = resolve_region(residence)
    category, rate = determine_category(modu, age, region.sido, income_level, children_count)

    def _best_label(rides: int) -> tuple[str, int]:
        pattern = Pattern((Segment("subway", fare_per_ride, rides, 0),))
        r_rebate = calc_modu_rebate(modu, pattern, category, rate, ref, False)
        r_std = calc_modu_flat(modu, pattern, category, region.region_class, ref, "standard")
        r_plus = calc_modu_flat(modu, pattern, category, region.region_class, ref, "plus")
        options = [("정률형", r_rebate.rebate), ("정액형(일반형)", r_std.rebate),
                   ("정액형(플러스형)", r_plus.rebate)]
        best = max(options, key=lambda x: x[1])
        return best

    # 15회 게이트: 정률/정액 모두 15회 미만이면 rebate=0
    entry_line = f"**가입 임계**: 월 15회 미만은 환급 대상이 아닙니다 (가입 첫 달만 예외)."

    # 스윕: 15회부터 120회까지 각 지점의 승자 라벨을 기록
    prev_label = None
    transitions: list[tuple[int, str, int, str, int]] = []  # (rides, from_label, from_rebate, to_label, to_rebate)
    per_rides: list[tuple[int, str, int]] = []
    for rides in range(15, 121):
        label, rebate = _best_label(rides)
        per_rides.append((rides, label, rebate))
        if prev_label is not None and label != prev_label:
            prev_r = per_rides[-2][2]
            transitions.append((rides, prev_label, prev_r, label, rebate))
        prev_label = label

    # 손익분기: 정률형에서 처음으로 환급이 fare_per_ride를 넘는 지점 (한 번 더 타는 값어치)
    # → 이 계산은 심리적 손익분기 (환급 > 1회 요금)
    psychological_be = None
    for rides, label, rebate in per_rides:
        if rebate >= fare_per_ride:
            psychological_be = (rides, label, rebate)
            break

    lines = [
        f"**{fare_per_ride:,}원/회 이용자의 모두의카드 손익분기 분석**",
        "",
        f"거주지: {region.sido or '전국'} ({region.region_class}), "
        f"유형: {CAT_KO[category]} (환급률 {rate:.1%})",
        "",
        entry_line,
    ]
    if psychological_be:
        r, lb, rb = psychological_be
        lines.append(f"**본전 회복**: 월 {r}회부터 월 환급 {rb:,}원이 1회 요금({fare_per_ride:,}원)을 넘습니다 "
                     f"— 이 시점에는 이미 {lb}이 최적입니다.")
    if transitions:
        lines.append("")
        lines.append("**상품 전환 지점**:")
        for r, from_lb, from_r, to_lb, to_r in transitions:
            lines.append(f"  - 월 {r}회 도달 시 **{from_lb}({from_r:,}원)** → **{to_lb}({to_r:,}원)** 전환")
    else:
        lines.append("")
        lines.append(f"이 요금대(1회 {fare_per_ride:,}원)에서는 정률형이 계속 최적입니다.")

    lines += ["", "**참고 표 (주요 지점)**",
              "| 승차 횟수 | 최적 상품 | 월 환급 |", "|---:|---|---:|"]
    for r in [15, 20, 30, 44, 60, 88, 120]:
        entry = next(x for x in per_rides if x[0] == r)
        lines.append(f"| {r}회 | {entry[1]} | {entry[2]:,}원 |")

    if ref <= date(2026, 9, 30):
        lines.append("")
        lines.append("_※ 한시 반값(9월 이용분까지) 기준. 10월 이후에는 정액형 이득이 절반가량 줄어듭니다._")

    return "\n".join(lines)


@mcp.tool(annotations={"title": "무임 vs 유임+환급 비교", **RO})
def simulate_free_ride_choice(
    monthly_rides: int,
    fare_per_ride: int,
    age: int,
    residence: str,
    income_level: Literal["general", "low_income"] = "general",
    as_of_date: str | None = None,
) -> str:
    """패스핏 – 교통패스 비교. 65세 이상 무임카드(결제 0원)와 유임 결제+모두의카드 환급 중
    어느 쪽이 유리한지 비교합니다. 도시철도 무임 개시 연령은 지역별로 다릅니다(전국 65세·대구 68세).
    승차 수단은 지하철로 가정합니다."""
    if monthly_rides <= 0 or fare_per_ride <= 0:
        raise ToolError("monthly_rides·fare_per_ride는 양수여야 합니다.")
    income_level = INCOME_LEVEL_ALIASES.get(income_level, income_level)
    if income_level not in ("general", "low_income"):
        raise ToolError(f"income_level은 'general' 또는 'low_income'이어야 합니다 (받음: '{income_level}').")
    modu = next(p for p in load_passes()["passes"] if p["id"] == "modu-card")
    data = load_passes()
    ref = resolve_reference_date(None, as_of_date, _today())
    region = resolve_region(residence)

    total_spend = monthly_rides * fare_per_ride

    # 시나리오 B: 유임 결제 + 모두의카드 환급
    pattern = Pattern((Segment("subway", fare_per_ride, monthly_rides, 0),))
    b = calc_modu_best(modu, pattern, age, region.sido, income_level, 0,
                       ref, False, region.region_class)
    scenario_b_cost = b.net_cost

    # 시나리오 A: 무임카드(결제 0원)는 도시철도 무임 개시 연령을 충족해야 성립.
    # 전국 65세 기본, 지역 상향(예: 대구 도시철도 68세+)은 free_ride_info에서 읽음.
    subway_free_age = 65
    for fr in data["free_ride_info"]:
        if fr["region"] == region.sido and "subway_free_age" in fr:
            subway_free_age = fr["subway_free_age"]

    header = (f"거주지: {region.sido or '전국'}, 월 이용: {monthly_rides}회 × "
              f"{fare_per_ride:,}원 = 총 {total_spend:,}원")
    table_head = ["| 시나리오 | 월 결제 | 월 환급 | 월 실질 부담 |", "|---|---:|---:|---:|"]
    b_row = (f"| B. 유임 결제 + {b.label} | {total_spend:,}원 | {b.rebate:,}원 | "
             f"**{scenario_b_cost:,}원** |")

    if age >= subway_free_age:
        scenario_a_cost = 0
        winner = "A(무임카드)" if scenario_a_cost < scenario_b_cost else "B(유임+환급)"
        delta = abs(scenario_a_cost - scenario_b_cost)
        lines = [
            f"**만 {age}세 무임 대상 사용자 — 두 시나리오 비교**", "", header, "",
            *table_head,
            f"| A. 무임카드 이용 | 0원 | 0원 | **0원** |",
            b_row, "",
            f"**결론: {winner}이 월 {delta:,}원 더 유리합니다.**",
        ]
    else:
        # 국가 65세 이상이라 도구는 호출되나, 이 지역은 무임 개시 연령이 더 높음.
        lines = [
            f"**만 {age}세 — 아직 무임 대상 아님 ({region.sido} 도시철도 {subway_free_age}세+)**",
            "", header, "",
            *table_head,
            f"| A. 무임카드 이용 | — | — | **{subway_free_age}세부터 가능** |",
            b_row, "",
            f"**결론: {region.sido} 도시철도 무임은 {subway_free_age}세부터라 만 {age}세는 "
            f"아직 무임 대상이 아닙니다. 현재는 B(유임+환급, 실질 {scenario_b_cost:,}원)만 가능합니다.**",
        ]

    # 지역별 무임 규정 안내
    free_notes = [fr for fr in data["free_ride_info"]
                  if fr["region"] in (region.sido, "전국")]
    if free_notes:
        lines.append("")
        lines.append("**무임 규정 (지역별)**:")
        for fr in free_notes:
            lines.append(f"  - [{fr['region']}] {fr['rule']}")

    lines.append("")
    lines.append("**주의**: 무임카드는 승차 자체가 결제 0원이라 환급 대상이 아닙니다. "
                 "도시철도만 무임인 지역에서는 버스 승차분은 여전히 유임+환급이 유리할 수 있습니다.")
    return "\n".join(lines)


if __name__ == "__main__":
    # allowed_hosts=["*"]: 프록시 뒤 배포에서 upstream Host 헤더가 rewrite/변형되어도
    # FastMCP의 host 검증이 421을 반환하지 않도록 허용. 게이트웨이(카카오 클라우드
    # Envoy)가 도메인 인증·라우팅을 담당하므로 백엔드 host 검증은 중복 방어.
    mcp.run(transport="http", host="0.0.0.0",
            port=int(os.environ.get("PORT", "8000")),
            stateless_http=True, allowed_hosts=["*"])
