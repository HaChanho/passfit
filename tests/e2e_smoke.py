"""E2E smoke over live HTTP transport (stateless streamable HTTP).

Boots against http://127.0.0.1:${PORT:-18000}/mcp. Not part of pytest — run:
    .venv/bin/python tests/e2e_smoke.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

URL = f"http://127.0.0.1:{os.environ.get('PORT', '18000')}/mcp"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2025-06-18",
}


def rpc(method: str, params: dict | None = None, rpc_id: int = 1) -> dict:
    body = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(
        URL, data=json.dumps(body).encode(), headers=HEADERS, method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode()
    # streamable HTTP: single SSE event → `data: {json}`
    for line in raw.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise RuntimeError(f"no data frame: {raw!r}")


def call(name: str, args: dict, rpc_id: int = 1) -> str:
    r = rpc("tools/call", {"name": name, "arguments": args}, rpc_id=rpc_id)
    if "error" in r:
        return f"__ERROR__: {r['error']}"
    return r["result"]["content"][0]["text"]


def call_raw(name: str, args: dict, rpc_id: int = 1) -> dict:
    return rpc("tools/call", {"name": name, "arguments": args}, rpc_id=rpc_id)


PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
results: list[tuple[str, bool, str]] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    results.append((label, cond, detail))
    mark = PASS if cond else FAIL
    print(f"  {mark} {label}" + (f" — {detail}" if detail and not cond else ""))


def section(title: str) -> None:
    print(f"\n━━ {title}")


# ═════════ Preflight
section("preflight — initialize + tools/list")
init = rpc(
    "initialize",
    {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "e2e", "version": "0"},
    },
)
check("initialize returns serverInfo=PassFit",
      init.get("result", {}).get("serverInfo", {}).get("name") == "PassFit",
      f"got {init}")

tools = rpc("tools/list", rpc_id=2)["result"]["tools"]
tool_names = {t["name"] for t in tools}
expected = {"compare_passes_for_commute", "list_transit_passes",
            "get_pass_details", "simulate_pass_savings", "check_pass_eligibility",
            "find_breakeven_rides", "simulate_free_ride_choice"}
check("all 7 tools exposed", tool_names == expected,
      f"got {tool_names}, missing {expected - tool_names}")

# ═════════ Scenario 1 — 서울 청년 통근자 크로스-tool 일관성
section("S1 — 서울 청년 34세, 44회/1550원: eligibility → compare → simulate 일관성")
elig = call("check_pass_eligibility",
            {"age": 34, "residence": "서울 마포구", "income_level": "general",
             "children_count": 0}, rpc_id=10)
check("서울 → '수도권' + 청년 30%로 해석", "'청년' 유형, 환급률 30.0%" in elig, elig[:200])
check("부산·세종은 거주 미달로 ❌", "부산 동백패스: ❌" in elig and "세종 이응패스: ❌" in elig)

cmp_ = call("compare_passes_for_commute",
            {"monthly_rides": 44, "fare_per_ride": 1550, "age": 34,
             "residence": "서울 마포구", "as_of_date": "2026-07-07",
             "detail": "concise"}, rpc_id=11)
# 44 * 1550 = 68,200원. 청년 30% → 20,460원. 단, 한시 반값 정액형(25,000원) 존재 시
# 정액형 환급이 더 커질 수 있음. 검증: 모두의카드가 1위, 서울 alias 문구, 한시 반값 언급.
check("모두의카드가 결론 1위", "결론: 모두의카드" in cmp_)
check("서울 → 기후동행카드 플러스 alias 힌트 노출",
      "기후동행카드 플러스" in cmp_ or "플러스" in cmp_)
check("한시 반값 caveat 부착", "반값" in cmp_ or "9월" in cmp_)

sim = call("simulate_pass_savings",
           {"pass_id": "modu-card", "monthly_rides": 44, "fare_per_ride": 1550,
            "age": 34, "residence": "서울 마포구", "as_of_date": "2026-07-07"},
           rpc_id=12)
check("simulate가 modu-card 결과 반환", "모두의카드" in sim)
# 크로스-tool: compare 표에서 뽑은 modu 환급액 == simulate 환급액
m = re.search(r"월 환급: ([\d,]+)원", sim)
sim_rebate = int(m.group(1).replace(",", "")) if m else -1
m2 = re.search(r"모두의카드[^|]*\| ([\d,]+)원", cmp_)
cmp_rebate = int(m2.group(1).replace(",", "")) if m2 else -2
check(f"compare↔simulate 환급액 일치 ({cmp_rebate:,} vs {sim_rebate:,})",
      sim_rebate == cmp_rebate and sim_rebate > 0)

# ═════════ Scenario 2 — 부산 저소득 어르신, 지역 패스 승부
section("S2 — 부산 해운대구 68세 저소득, 30회/1450원: 동백패스 vs 모두의카드")
elig2 = call("check_pass_eligibility",
             {"age": 68, "residence": "부산 해운대구", "income_level": "low_income",
              "children_count": 0}, rpc_id=20)
check("해운대구 alias → 부산 해석", "부산" in elig2, elig2[:200])
check("모두의카드 저소득 53.3% 반영",
      "53.3%" in elig2 or "저소득" in elig2, elig2)
check("부산 동백패스: ✅", "부산 동백패스: ✅" in elig2)

cmp2 = call("compare_passes_for_commute",
            {"monthly_rides": 30, "fare_per_ride": 1450, "age": 68,
             "residence": "부산 해운대구", "income_level": "low_income",
             "as_of_date": "2026-07-07", "detail": "detailed"}, rpc_id=21)
check("부산 동백패스가 옵션에 등장", "동백" in cmp2)
check("기후동행카드는 부산에선 제외", "기후동행카드 " not in cmp2 or "서울이용자" not in cmp2)

# ═════════ Scenario 3 — 세종 이응패스, 자격 좁히기
section("S3 — 세종 이응패스: 자격/비자격 대칭 검증")
elig_sejong = call("check_pass_eligibility",
                   {"age": 45, "residence": "세종", "income_level": "general",
                    "children_count": 0}, rpc_id=30)
check("세종 거주자 → 이응패스 ✅", "세종 이응패스: ✅" in elig_sejong)
elig_daejeon = call("check_pass_eligibility",
                    {"age": 45, "residence": "대전 유성구", "income_level": "general",
                     "children_count": 0}, rpc_id=31)
check("대전 거주자 → 이응패스 ❌ (세종 전용)",
      "세종 이응패스: ❌" in elig_daejeon)

# ═════════ Scenario 4 — 미성년 사용자, 연령 게이트
section("S4 — 만 16세: 모두의카드 age_min(19) 컷")
elig_teen = call("check_pass_eligibility",
                 {"age": 16, "residence": "서울"}, rpc_id=40)
check("16세 → 모두의카드 ❌ + 대안 안내",
      "모두의카드: ❌" in elig_teen and "만 19세" in elig_teen)

# ═════════ Scenario 5 — 미승차자 (spend_only 경로)
section("S5 — spend_only 경로: monthly_spend만 입력")
cmp_spend = call("compare_passes_for_commute",
                 {"monthly_spend": 120000, "age": 30, "residence": "서울",
                  "as_of_date": "2026-07-07"}, rpc_id=50)
check("총액만 입력 caveat 나타남", "총액만 입력" in cmp_spend or "탑승 횟수" in cmp_spend,
      cmp_spend[:300])

# ═════════ Scenario 6 — 오프피크 할증 (한시 +30%p)
section("S6 — offpeak_rides: 시차시간 +30%p 반영")
cmp_off = call("compare_passes_for_commute",
               {"monthly_rides": 44, "offpeak_rides": 20, "fare_per_ride": 1550,
                "age": 34, "residence": "서울 마포구", "as_of_date": "2026-07-07"},
               rpc_id=60)
# offpeak=0 대비 offpeak=20 → 환급액이 더 커야 함
m_off = re.search(r"모두의카드[^|]*\| ([\d,]+)원", cmp_off)
off_rebate = int(m_off.group(1).replace(",", "")) if m_off else -3
check(f"offpeak 20회 환급({off_rebate:,}) ≥ offpeak 0회 환급({cmp_rebate:,})",
      off_rebate >= cmp_rebate)

# ═════════ Scenario 7 — 시점 정책 (10월 이후 원복)
section("S7 — as_of_date=2026-11-01: 한시 혜택 원복 반영")
cmp_nov = call("compare_passes_for_commute",
               {"monthly_rides": 44, "fare_per_ride": 1550, "age": 34,
                "residence": "서울 마포구", "as_of_date": "2026-11-01"},
               rpc_id=70)
m_nov = re.search(r"모두의카드[^|]*\| ([\d,]+)원", cmp_nov)
nov_rebate = int(m_nov.group(1).replace(",", "")) if m_nov else -4
check(f"11월 환급({nov_rebate:,}) ≤ 7월 환급({cmp_rebate:,}) — 한시 반값 종료",
      nov_rebate <= cmp_rebate)

# ═════════ Scenario 8 — 잘못된 pass_id (schema 방어)
section("S8 — 잘못된 pass_id: MCP schema/enum 거부")
bad = call_raw("get_pass_details", {"pass_id": "nonexistent-pass"}, rpc_id=80)
has_err = ("error" in bad or
           (bad.get("result", {}).get("isError") is True) or
           ("__ERROR__" in json.dumps(bad, ensure_ascii=False)))
check("존재하지 않는 pass_id → 에러 or 툴 오류로 거부", has_err,
      json.dumps(bad, ensure_ascii=False)[:300])

# ═════════ Scenario 9 — 입력 없이 호출 (anyOf 검증)
section("S9 — 인자 없이 compare 호출: anyOf 검증 오류")
empty = call_raw("compare_passes_for_commute", {}, rpc_id=90)
has_err2 = ("error" in empty or
            (empty.get("result", {}).get("isError") is True))
check("monthly_rides/fare/spend/rides 모두 비면 실패", has_err2,
      json.dumps(empty, ensure_ascii=False)[:300])

# ═════════ Scenario 10 — 미확정 혜택은 계산에 반영되지 않음
section("S10 — climate-card-plus: 예정 혜택은 상세 표시만, 계산은 base로 위임")
det = call("get_pass_details", {"pass_id": "climate-card-plus"}, rpc_id=100)
check("plus는 base(모두의카드)로 alias",
      "모두의카드" in det and ("기반" in det or "동일" in det or "재포장" in det))
check("예정 혜택은 '미확정' 라벨로 표시",
      "미확정" in det or "예정" in det)
sim_plus = call("simulate_pass_savings",
                {"pass_id": "climate-card-plus", "monthly_rides": 44,
                 "fare_per_ride": 1550, "age": 34, "residence": "서울",
                 "as_of_date": "2026-07-07"}, rpc_id=101)
check("plus로 simulate 호출 시 base로 위임됨",
      "모두의카드 기반" in sim_plus or "모두의카드로 계산" in sim_plus,
      sim_plus[:200])

# ═════════ 최종 리포트
section("Summary")
total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
print(f"\n{passed}/{total} assertions passed")
if passed != total:
    print("\nFailures:")
    for label, ok, detail in results:
        if not ok:
            print(f"  {FAIL} {label}")
            if detail:
                for line in detail.splitlines()[:6]:
                    print(f"      {line}")
    sys.exit(1)
