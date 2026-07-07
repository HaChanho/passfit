import os
from datetime import date
from typing import Literal
from zoneinfo import ZoneInfo
from datetime import datetime
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import ValidationError
from passfit.models import CommuteInput, RideSegment, to_pattern
from passfit.engine import compare_all, collect_notices, calc_modu_best, determine_category
from passfit.normalize import resolve_region
from passfit.dates import resolve_reference_date
from passfit.data_loader import load_passes
from passfit.render import render_comparison

mcp = FastMCP("PassFit")
RO = {"readOnlyHint": True, "destructiveHint": False,
      "openWorldHint": False, "idempotentHint": True}


def _today() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def _region_note(residence: str) -> str:
    r = resolve_region(residence)
    if r.confidence == "unknown":
        return f"거주지 '{residence}'를 해석하지 못해 전국 기준(모두의카드)으로만 계산했습니다."
    return f"거주지는 '{r.sido}'({r.region_class})으로 해석했습니다."


CAT_KO = {"general": "일반", "youth": "청년", "senior": "어르신",
          "multi_child_2": "2자녀", "multi_child_3": "3자녀+", "low_income": "저소득"}


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
    """Compare all 2026 Korean transit passes for a commute pattern and rank by
    real monthly cost, from PassFit(패스핏). Use when the user asks which transit
    pass/card saves money — e.g. '교통비 아끼는 법', 'K-패스랑 기후동행카드 뭐가 이득?',
    '월 교통비 12만원인데 아낄 방법?'. If the user only knows weekly commute days,
    convert: 주 5일 왕복 ≈ monthly_rides 44. offpeak_rides = 출퇴근 시차시간
    (05:30~06:30/09~10/16~17/19~20시) 승차 횟수 — 한시 환급 할증 대상."""
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
    """List available Korean transit passes(교통패스 목록) from PassFit(패스핏),
    optionally filtered by region (e.g. '서울', '부산')."""
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
        ptype = p.get("type", "hybrid(모두의카드 기반)")
        lines.append(f"| {name} | {ptype} | {res} | {status} |")
    return "\n".join(lines)


def _fmt(v):
    if isinstance(v, bool):
        return "예" if v else "아니오"
    if isinstance(v, dict):
        return ", ".join(f"{k}: {_fmt(x)}" for k, x in v.items())
    if isinstance(v, list):
        return ", ".join(_fmt(x) for x in v)
    return str(v)


@mcp.tool(annotations={"title": "패스 상세", **RO})
def get_pass_details(pass_id: Literal["modu-card", "climate-card-legacy",
                                      "climate-card-plus", "dongbaek-pass",
                                      "eung-pass"]) -> str:
    """Get details(자격·환급률·기준금액·신청 방법) of one Korean transit pass
    from PassFit(패스핏). Valid pass_id: modu-card(모두의카드),
    climate-card-legacy(기후동행카드), climate-card-plus(기후동행카드 플러스),
    dongbaek-pass(부산 동백패스), eung-pass(세종 이응패스). Discover ids via
    list_transit_passes."""
    data = load_passes()
    p = next(x for x in data["passes"] if x["id"] == pass_id)
    lines = [f"## {p['name']}"]
    if p.get("details_policy") == "show_alias_plus_base":     # plus 정책
        base = next(x for x in data["passes"] if x["id"] == p["calculation_alias_of"])
        lines.append(f"모두의카드 기반 서울 전환 상품 — 계산·혜택은 '{base['name']}'과 동일.")
        lines.append("예정 혜택(미확정, 계산 미반영): " + ", ".join(p["pending_benefits"]))
        p = base
        lines.append(f"\n### 기반 제도: {p['name']}")
    for key in ("eligibility", "rebate_rates", "conditions", "threshold",
                "monthly_price", "monthly_cap", "scope_note", "note",
                "transition_note", "included_scope"):
        if key in p:
            lines.append(f"- **{key}**: {_fmt(p[key])}")
    lines.append("- **출처**: " + ", ".join(s["url"] for s in p["sources"]))
    return "\n".join(lines)


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
    """Simulate monthly/yearly savings(월·연 절약액과 손익분기) for ONE specific
    pass from PassFit(패스핏). Valid pass_id: modu-card(모두의카드),
    climate-card-legacy(기후동행카드), climate-card-plus(기후동행카드 플러스),
    dongbaek-pass(부산 동백패스), eung-pass(세종 이응패스). Discover ids via
    list_transit_passes. offpeak_rides = 출퇴근 시차시간(05:30~06:30/09~10/16~17/
    19~20시) 승차 횟수 — 한시 환급 할증 대상."""
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
    # legacy/dongbaek/eung은 compare_all 재사용 후 해당 항목만 발췌
    opts = compare_all(pattern, ref, inp.age, inp.residence, inp.income_level,
                       inp.children_count, inp.is_first_month,
                       inp.has_postpaid_climate_card)   # free_ride_status는 caveat에서만 사용 (T7 리뷰)
    m = next((o for o in opts if o.pass_id == p["id"]), None)
    if m is None:
        return (f"{note}{p['name']}는 현재 조건(거주지 {inp.residence}, 기준일 {ref})"
                f"에서는 선택지가 아닙니다. compare_passes_for_commute로 대안을 확인하세요.")
    return (f"{note}**{m.name} — {m.label}**\n- 월 환급: {m.rebate:,}원 / "
            f"월 실질 부담: {m.net_cost:,}원\n"
            + "".join(f"- ⚠️ {w}\n" for w in m.warnings))


@mcp.tool(annotations={"title": "자격 확인", **RO})
def check_pass_eligibility(age: int, residence: str,
                           income_level: Literal["general", "low_income"] = "general",
                           children_count: int = 0, is_first_month: bool = False,
                           free_ride_status: Literal["none", "eligible",
                                                     "uses_free_ride_card"] = "none") -> str:
    """Check which Korean transit passes the user qualifies for(자격 확인),
    with reasons, from PassFit(패스핏). 모두의카드·부산 동백패스·세종 이응패스의
    자격을 확인합니다(기후동행카드는 이용 가능 여부라 compare에서 다룸)."""
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


if __name__ == "__main__":
    # allowed_hosts=["*"]: 프록시 뒤 배포에서 upstream Host 헤더가 rewrite/변형되어도
    # FastMCP의 host 검증이 421을 반환하지 않도록 허용. 게이트웨이(카카오 클라우드
    # Envoy)가 도메인 인증·라우팅을 담당하므로 백엔드 host 검증은 중복 방어.
    mcp.run(transport="http", host="0.0.0.0",
            port=int(os.environ.get("PORT", "8000")),
            stateless_http=True, allowed_hosts=["*"])
