"""Redeploy-round deep probe — 4 axes not covered before:

  R1 · Tool orchestration chain (multi-tool workflow)
  R2 · Cross-tool numeric consistency (3-way rebate match)
  R3 · Edge domain combinations (category × region × time)
  R4 · Judge persona simulation (실심사관이 물을만한 15 질문)

Run:  .venv/bin/python tests/e2e_redeploy_probe.py
"""
from __future__ import annotations
import json
import os
import re
import urllib.request
from dataclasses import dataclass

URL = f"http://127.0.0.1:{os.environ.get('PORT', '18000')}/mcp"
H = {"Content-Type": "application/json",
     "Accept": "application/json, text/event-stream",
     "MCP-Protocol-Version": "2025-06-18"}


def rpc(method, params=None, rid=1):
    body = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers=H, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read().decode()
    for line in raw.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise RuntimeError(raw)


def call(name, args):
    r = rpc("tools/call", {"name": name, "arguments": args})
    if "error" in r:
        return f"__RPC_ERROR__ {r['error']}"
    res = r.get("result", {})
    if res.get("isError"):
        return f"__TOOL_ERROR__ {res.get('content', [{}])[0].get('text', '')}"
    return res.get("content", [{}])[0].get("text", "")


def money(text, pat):
    m = re.search(pat, text)
    return int(m.group(1).replace(",", "")) if m else None


@dataclass
class Result:
    axis: str
    label: str
    ok: bool
    note: str = ""


results: list[Result] = []


def rec(axis, label, ok, note=""):
    results.append(Result(axis, label, ok, note))
    m = "\033[32m✓\033[0m" if ok else "\033[31m✗\033[0m"
    print(f"  {m} [{axis}] {label}" + (f" — {note[:120]}" if note else ""))


# ═════════ R1 · Tool 오케스트레이션 체인
print("\n━━ R1 · Tool 오케스트레이션 (multi-tool workflow)")

# 시나리오: "부산 사는 68세 어르신 부모님, 통근용 아니라 시장 왕복 정도. 어떤 카드가 이득?"
# LLM 예상 체인:
#   1) check_pass_eligibility → 어떤 pass가 자격 되는지 좁힘
#   2) compare_passes_for_commute → 후보들 비교
#   3) simulate_free_ride_choice → 무임 vs 유임+환급 판정
#   4) get_pass_details → 최종 선택 pass 자세히

age, residence = 68, "부산 해운대구"
t1 = call("check_pass_eligibility", {"age": age, "residence": residence})
rec("R1", "체인1: eligibility 응답 안에 dongbaek-pass 자격 결과 포함",
    "동백" in t1, t1[:120])

t2 = call("compare_passes_for_commute",
          {"monthly_rides": 20, "fare_per_ride": 1450, "age": age,
           "residence": residence, "as_of_date": "2026-07-07"})
rec("R1", "체인2: compare 응답에 동백/모두의카드 후보 노출",
    "동백" in t2 and "모두의카드" in t2, "")

t3 = call("simulate_free_ride_choice",
          {"monthly_rides": 20, "fare_per_ride": 1450, "age": age,
           "residence": residence, "as_of_date": "2026-07-07"})
rec("R1", "체인3: free_ride 시나리오 응답 정상",
    "A(무임카드)" in t3 or "B(유임" in t3, t3[:200])

t4 = call("get_pass_details", {"pass_id": "dongbaek-pass"})
rec("R1", "체인4: get_pass_details 응답 서술형 문장 유지",
    "자격" in t4 and "작동 방식" in t4, t4[:150])

# 체인 내 데이터 흐름 확인: t2의 부산 티어와 t3의 부산 지역이 일관
rec("R1", "체인 통일성: 모든 응답이 '부산' 지역 컨텍스트 유지",
    "부산" in t1 and "부산" in t2 and "부산" in t3, "")

# ═════════ R2 · Cross-tool 숫자 정합성
print("\n━━ R2 · Cross-tool 숫자 정합성 (3-way rebate match)")

BASE = {"monthly_rides": 44, "fare_per_ride": 1550, "age": 34,
        "residence": "서울 마포구", "as_of_date": "2026-07-07"}

# 서울 청년 44회×1550원 시나리오에서 modu-card 환급이 3개 tool에서 정확히 일치해야 함
r_cmp = call("compare_passes_for_commute", BASE)
r_sim = call("simulate_pass_savings", {"pass_id": "modu-card", **BASE})
r_be = call("find_breakeven_rides",
            {"fare_per_ride": BASE["fare_per_ride"], "age": BASE["age"],
             "residence": BASE["residence"], "as_of_date": BASE["as_of_date"]})

# compare에서 modu-card 행 rebate
m_cmp = re.search(r"모두의카드[^|]*\|\s*([\d,]+)원", r_cmp)
cmp_rebate = int(m_cmp.group(1).replace(",", "")) if m_cmp else -1
# simulate에서 rebate
sim_rebate = money(r_sim, r"월 환급: ([\d,]+)원") or -2
# breakeven 표에서 44회 행
be_row = re.search(r"\|\s*44회\s*\|[^|]*\|\s*([\d,]+)원", r_be)
be_rebate = int(be_row.group(1).replace(",", "")) if be_row else -3

rec("R2", f"compare({cmp_rebate:,}) == simulate({sim_rebate:,})",
    cmp_rebate == sim_rebate and cmp_rebate > 0,
    f"cmp={cmp_rebate}, sim={sim_rebate}")

rec("R2", f"simulate({sim_rebate:,}) == breakeven 표 44회 행({be_rebate:,})",
    sim_rebate == be_rebate and sim_rebate > 0,
    f"sim={sim_rebate}, be={be_rebate}")

# 결정론성 재확인: 같은 인자 3번 호출 결과 동일
outs = [call("compare_passes_for_commute", BASE) for _ in range(3)]
rec("R2", "동일 인자 3회 호출 → 결정론적 응답",
    len(set(outs)) == 1, f"{len(set(outs))} distinct")

# 시점 파라미터 결정: as_of_date=None (오늘) vs as_of_date="2026-07-07"
# 오늘도 2026-07-07이라 같아야 함
r_today = call("compare_passes_for_commute", {k: v for k, v in BASE.items() if k != "as_of_date"})
r_fixed = call("compare_passes_for_commute", BASE)
today_rebate = int(re.search(r"모두의카드[^|]*\|\s*([\d,]+)원", r_today).group(1).replace(",", ""))
fixed_rebate = int(re.search(r"모두의카드[^|]*\|\s*([\d,]+)원", r_fixed).group(1).replace(",", ""))
rec("R2", f"현재 시각(오늘) 호출과 as_of_date=2026-07-07 결과 일치",
    today_rebate == fixed_rebate,
    f"today={today_rebate}, fixed={fixed_rebate}")


# ═════════ R3 · 엣지 도메인 조합
print("\n━━ R3 · 엣지 도메인 조합 (category × region × time)")

# 3-1) 저소득 다자녀 어르신 겹침 60세 광주 — 저소득 64% > 다자녀 30% > 어르신 50% (광주 override)
r = call("check_pass_eligibility",
         {"age": 60, "residence": "광주", "income_level": "low_income", "children_count": 3})
rec("R3", "60세 광주 저소득+3자녀: 최고 rate(64% 저소득) 선택",
    "64.0%" in r, r[:200])

# 3-2) 3자녀지만 저소득 아님, 65세 광주 — multi_child_3(50%) vs senior_광주(50%) 동률
r = call("check_pass_eligibility",
         {"age": 65, "residence": "광주", "children_count": 3})
rec("R3", "65세 광주 3자녀: 50% 유형 (동률 → 안정 선택)",
    "50.0%" in r, r[:200])

# 3-3) 우대지원지역 (전주 등) 손익분기 — 서울(수도권)보다 이른 승차수에서 전환
r_gwj = call("find_breakeven_rides",
             {"fare_per_ride": 1500, "age": 30, "residence": "전주",
              "as_of_date": "2026-07-07"})
gwj_t = re.search(r"월 (\d+)회 도달", r_gwj)
rec("R3", f"전주(우대지원지역) 손익분기 관측 ({gwj_t.group(1) if gwj_t else 'N/A'}회)",
    gwj_t is not None, r_gwj[:300])

# 3-4) 세종 vs 이응패스 vs 모두의카드 5만원 초과분 비교
r_sejong = call("compare_passes_for_commute",
                {"monthly_rides": 50, "fare_per_ride": 1400, "age": 30,
                 "residence": "세종", "as_of_date": "2026-07-07"})
rec("R3", "세종 50회×1400원: 이응패스와 모두의카드 둘 다 후보",
    "이응패스" in r_sejong and "모두의카드" in r_sejong, r_sejong[:200])

# 3-5) 기후동행카드 마지막 유효일(2026-08-31) 다음날 → 서울에서도 옵션 사라져야
r_early_sep = call("compare_passes_for_commute",
                   {"monthly_rides": 44, "fare_per_ride": 1550, "age": 30,
                    "residence": "서울", "as_of_date": "2026-09-01",
                    "has_postpaid_climate_card": True})
rec("R3", "2026-09-01 서울: 기동카 옵션 소멸, 종료 안내",
    "종료" in r_early_sep or "전환" in r_early_sep,
    r_early_sep[:200])

# 3-6) 다세그먼트: 지하철+광역버스 조합에서 광역버스 excluded 처리
r_multi = call("compare_passes_for_commute",
               {"rides": [
                   {"mode": "subway", "fare_per_ride": 1550, "monthly_rides": 40},
                   {"mode": "metropolitan_bus", "fare_per_ride": 3000, "monthly_rides": 20},
                ],
                "age": 30, "residence": "서울", "as_of_date": "2026-07-07",
                "detail": "detailed"})
rec("R3", "다세그먼트 광역버스 60,000원 별도 부담 안내",
    "광역버스" in r_multi and ("별도 부담" in r_multi or "60,000원" in r_multi),
    r_multi[:400])

# 3-7) 첫 달 예외가 spend_only에서도 작동
r_first_spend = call("compare_passes_for_commute",
                     {"monthly_spend": 50000, "age": 30, "residence": "서울",
                      "is_first_month": True, "as_of_date": "2026-07-07"})
rec("R3", "첫 달 spend_only 50,000원: 15회 예외 → 환급 정상",
    "환급 없음" not in r_first_spend and "월 환급" in r_first_spend,
    r_first_spend[:200])


# ═════════ R4 · 대회 심사관 페르소나 시뮬
print("\n━━ R4 · 대회 심사관 페르소나 시뮬")

# 현실적으로 5천만 유저가 카카오톡에서 물을만한 15개 질문. 각각 어떤 tool이 응답 가능한지 확인.
# 심사관 관점: (a) 답이 나오나 (b) 답이 유용한가 (c) 카카오톡 UX에 맞나

judge_scenarios = [
    ("직장인 프리랜서", "compare_passes_for_commute",
     {"monthly_rides": 30, "fare_per_ride": 1500, "age": 32, "residence": "서울",
      "as_of_date": "2026-07-07"},
     lambda r: "결론" in r and "실질 부담" in r),

    ("취준생·저이용", "compare_passes_for_commute",
     {"monthly_rides": 12, "fare_per_ride": 1550, "age": 26, "residence": "서울",
      "as_of_date": "2026-07-07"},
     lambda r: "15회 미만" in r or "환급 없음" in r),

    ("워킹맘 2자녀", "check_pass_eligibility",
     {"age": 38, "residence": "경기 성남시", "children_count": 2},
     lambda r: "청년" in r or "2자녀" in r),

    ("대학생 신입", "check_pass_eligibility",
     {"age": 20, "residence": "서울"},
     lambda r: "✅" in r and "청년" in r),

    ("고교생 (미성년)", "check_pass_eligibility",
     {"age": 17, "residence": "부산"},
     lambda r: "❌" in r and "만 19세" in r),

    ("부산 대학생", "compare_passes_for_commute",
     {"monthly_rides": 40, "fare_per_ride": 1450, "age": 22, "residence": "부산",
      "as_of_date": "2026-07-07"},
     lambda r: "동백" in r and "모두의카드" in r),

    ("세종 공무원", "compare_passes_for_commute",
     {"monthly_rides": 44, "fare_per_ride": 1500, "age": 35, "residence": "세종",
      "as_of_date": "2026-07-07"},
     lambda r: "이응패스" in r),

    ("무임 대상 어르신", "simulate_free_ride_choice",
     {"monthly_rides": 30, "fare_per_ride": 1550, "age": 67, "residence": "서울",
      "as_of_date": "2026-07-07"},
     lambda r: "A(무임" in r and "결론" in r),

    ("손익분기 궁금", "find_breakeven_rides",
     {"fare_per_ride": 1500, "age": 30, "residence": "서울",
      "as_of_date": "2026-07-07"},
     lambda r: "전환" in r and "가입 임계" in r),

    ("이사 예정 (서울→부산)", "compare_passes_for_commute",
     {"monthly_rides": 44, "fare_per_ride": 1450, "age": 30, "residence": "부산",
      "as_of_date": "2026-07-07"},
     lambda r: "부산" in r and "동백" in r),

    ("저소득 지원 대상", "check_pass_eligibility",
     {"age": 40, "residence": "울산", "income_level": "low_income"},
     lambda r: "100.0%" in r),

    ("광주 저소득", "check_pass_eligibility",
     {"age": 30, "residence": "광주", "income_level": "low_income"},
     lambda r: "64.0%" in r),

    ("경기 39세 청년 확대", "check_pass_eligibility",
     {"age": 39, "residence": "경기 성남시"},
     lambda r: "청년" in r and "30.0%" in r),

    ("한시 혜택 정보", "compare_passes_for_commute",
     {"monthly_rides": 44, "fare_per_ride": 1550, "age": 30, "residence": "서울",
      "as_of_date": "2026-07-07"},
     lambda r: "반값" in r or "9월" in r or "한시" in r),

    ("한시 혜택 종료 후 (2026-10)", "compare_passes_for_commute",
     {"monthly_rides": 44, "fare_per_ride": 1550, "age": 30, "residence": "서울",
      "as_of_date": "2026-10-15"},
     lambda r: "결론" in r),
]

for persona, tool, args, checker in judge_scenarios:
    r = call(tool, args)
    ok = not r.startswith("__") and checker(r)
    rec("R4", f"{persona} → {tool}", ok, r[:150] if not ok else "")

# 심사관 총평용 통계
r4_results = [r for r in results if r.axis == "R4"]
r4_pass = sum(1 for r in r4_results if r.ok)
print(f"\n       ┌ 심사관 페르소나 통과: {r4_pass}/{len(r4_results)}")
print(f"       └ 카카오톡 5천만 대상 실사용 커버리지 관점 신호")


# ═════════ Summary
print("\n" + "═" * 70)
axes: dict[str, list[Result]] = {}
for r in results:
    axes.setdefault(r.axis, []).append(r)
total_pass = sum(1 for r in results if r.ok)
total = len(results)
for axis, rs in axes.items():
    p = sum(1 for r in rs if r.ok)
    print(f"  {axis}: {p}/{len(rs)} passed")
print(f"\n  전체: {total_pass}/{total}")
if total_pass < total:
    print("\n  실패:")
    for r in results:
        if not r.ok:
            print(f"   ✗ [{r.axis}] {r.label}" + (f"\n       {r.note[:200]}" if r.note else ""))
