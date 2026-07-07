"""Deep E2E — 3-axis (창의성/편의성/안정성) rubric probes for PlayMCP eval.

Assumes server at http://127.0.0.1:${PORT:-18000}/mcp (stateless streamable HTTP).
Not part of pytest; run explicitly:
    .venv/bin/python tests/e2e_deep.py
"""
from __future__ import annotations
import json, os, re, sys, textwrap, urllib.request
from dataclasses import dataclass, field

URL = f"http://127.0.0.1:{os.environ.get('PORT', '18000')}/mcp"
H = {"Content-Type": "application/json",
     "Accept": "application/json, text/event-stream",
     "MCP-Protocol-Version": "2025-06-18"}

RID = [1000]

def rpc(method, params=None):
    RID[0] += 1
    body = {"jsonrpc": "2.0", "id": RID[0], "method": method}
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers=H, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
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
    c = res.get("content", [])
    return c[0]["text"] if c else "__EMPTY__"


@dataclass
class Finding:
    group: str
    scenario: str
    passed: bool
    detail: str = ""
    excerpt: str = ""

findings: list[Finding] = []

def rec(group, scenario, passed, detail="", excerpt=""):
    findings.append(Finding(group, scenario, passed, detail, excerpt))
    mark = "✓" if passed else "✗"
    color = "\033[32m" if passed else "\033[31m"
    print(f"  {color}{mark}\033[0m [{group}] {scenario}")
    if not passed and detail:
        print(f"      └ {detail}")
    if excerpt:
        for line in excerpt.strip().splitlines()[:3]:
            print(f"        │ {line}")

def money(text, pattern) -> int | None:
    m = re.search(pattern, text)
    return int(m.group(1).replace(",", "")) if m else None


# ═════════ G1 — 도메인 정확성 심화
print("\n━━ G1 · 도메인 정확성 심화 (창의성·안정성)")

# 1-1) 3자녀 다자녀 부모 30세 서울 — 유형 겹침에서 multi_child_3(50%) 선택
r = call("check_pass_eligibility",
         {"age": 30, "residence": "서울", "income_level": "general", "children_count": 3})
rec("G1", "3자녀 30세: multi_child_3(50%) 선택되어야",
    "50.0%" in r, "유형 겹침에서 max rate 선택 실패", r)

# 1-2) 저소득 + 3자녀 겹침 — 저소득 53.3% vs 다자녀 50% → 저소득 우선
r = call("check_pass_eligibility",
         {"age": 30, "residence": "서울", "income_level": "low_income", "children_count": 3})
rec("G1", "저소득+3자녀: 최고 rate(53.3%) 우선",
    "53.3%" in r, "유형 겹침 max 선택 실패", r)

# 1-3) 광주 저소득 — regional override로 64%
r = call("check_pass_eligibility",
         {"age": 40, "residence": "광주", "income_level": "low_income"})
rec("G1", "광주 저소득: regional override 64%",
    "64.0%" in r, "광주 override 미반영", r)

# 1-4) 울산 저소득 — 100% override
r = call("check_pass_eligibility",
         {"age": 40, "residence": "울산", "income_level": "low_income"})
rec("G1", "울산 저소득: 100% override",
    "100.0%" in r, "울산 100% 미반영", r)

# 1-5) 경남 78세 — 75+ 지역특례 caveat (compare에서만 발동)
r = call("compare_passes_for_commute",
         {"monthly_rides": 30, "fare_per_ride": 1400, "age": 78,
          "residence": "경남 창원시", "as_of_date": "2026-07-07"})
rec("G1", "경남 78세: 75+ 100% 환급 caveat 부착",
    "75세 이상" in r and ("100%" in r or "korea-pass.kr" in r),
    "75+ tier caveat 누락 — 오답 위험", r)

# 1-6) 경기 38세 — youth_age_max=39 override로 청년 유지
r = call("check_pass_eligibility",
         {"age": 38, "residence": "경기 성남시"})
rec("G1", "경기 38세: youth_age_max=39 override → 청년",
    "청년" in r and "30.0%" in r, "경기 39세 확대 미반영", r)

# 1-7) 서울 38세 — override 없음 → 일반(20%)
r = call("check_pass_eligibility",
         {"age": 38, "residence": "서울"})
rec("G1", "서울 38세: override 없음 → 일반 20%",
    "일반" in r and "20.0%" in r, "서울 base rate 오류", r)

# 1-8) 첫 달 8회만 탑승 — 15회 미달이지만 first_month_exempt
r = call("simulate_pass_savings",
         {"pass_id": "modu-card", "monthly_rides": 8, "fare_per_ride": 1500,
          "age": 30, "residence": "서울", "is_first_month": True,
          "as_of_date": "2026-07-07"})
first_month_rebate = money(r, r"월 환급: ([\d,]+)원")
rec("G1", "첫 달 8회: 15회 미달이지만 환급 발생",
    first_month_rebate is not None and first_month_rebate > 0,
    f"first_month 예외 미작동 (rebate={first_month_rebate})", r)

# 1-9) 첫 달 아닌 8회 — 환급 0
r = call("simulate_pass_savings",
         {"pass_id": "modu-card", "monthly_rides": 8, "fare_per_ride": 1500,
          "age": 30, "residence": "서울", "is_first_month": False,
          "as_of_date": "2026-07-07"})
zero_rebate = money(r, r"월 환급: ([\d,]+)원")
rec("G1", "일반 달 8회: 15회 미달 → 환급 0",
    zero_rebate == 0, f"15회 게이트 실패 (rebate={zero_rebate})", r)

# 1-10) 무임 대상 free_ride_status='eligible' — 무임+환급 caveat
r = call("compare_passes_for_commute",
         {"monthly_rides": 30, "fare_per_ride": 1400, "age": 70,
          "residence": "서울", "free_ride_status": "eligible",
          "as_of_date": "2026-07-07"})
rec("G1", "무임 대상: '무임 vs 유임+환급 비교' caveat",
    "무임" in r and "환급" in r, "무임 딜레마 안내 누락", r)

# 1-11) 세종 이응패스 노인 무료 (70+) — caveat/note 확인
r = call("get_pass_details", {"pass_id": "eung-pass"})
rec("G1", "이응패스 상세: 노인 무료 규정 노출",
    "70세" in r or "면제" in r, "이응패스 노인 면제 미노출", r)

# 1-12) climate-card 후불 미보유 + 2026-08 → 종료 임박 표시
r = call("compare_passes_for_commute",
         {"monthly_rides": 44, "fare_per_ride": 1450, "age": 30,
          "residence": "서울", "has_postpaid_climate_card": False,
          "as_of_date": "2026-08-15"})
rec("G1", "2026-08 서울: 기동카 종료 임박·전환 안내",
    "8월" in r or "종료" in r or "전환" in r, "종료 안내 누락", r)


# ═════════ G2 — 입력 견고성
print("\n━━ G2 · 입력 견고성 (안정성)")

# 2-1) 다중 세그먼트 rides — 지하철 + 광역버스 (standard 제외 대상)
r = call("compare_passes_for_commute",
         {"rides": [
             {"mode": "metro", "fare_per_ride": 1550, "monthly_rides": 40},
             {"mode": "metropolitan_bus", "fare_per_ride": 3000, "monthly_rides": 20},
          ],
          "age": 30, "residence": "서울", "as_of_date": "2026-07-07"})
rec("G2", "다세그먼트 rides: 광역버스 excluded 반영",
    "광역버스" in r or "플러스형" in r or "미적용" in r, "flat_standard 제외 안내 누락", r)

# 2-2) offpeak_rides > monthly_rides — 클램프
r = call("simulate_pass_savings",
         {"pass_id": "modu-card", "monthly_rides": 20, "offpeak_rides": 100,
          "fare_per_ride": 1200, "age": 30, "residence": "서울",
          "as_of_date": "2026-07-07"})
rec("G2", "offpeak > monthly: 클램프되어도 계산 성공",
    "__" not in r and "월 환급" in r, "클램프 실패", r)

# 2-3) monthly_rides=0 — 15회 미달 게이트
r = call("simulate_pass_savings",
         {"pass_id": "modu-card", "monthly_rides": 0, "fare_per_ride": 1500,
          "age": 30, "residence": "서울", "as_of_date": "2026-07-07"})
rec("G2", "monthly_rides=0: 15회 미달로 환급 0",
    "환급 없음" in r or "환급: 0원" in r or money(r, r"월 환급: ([\d,]+)원") == 0,
    "0회 케이스 처리 불명", r)

# 2-4) 음수 rides — validation 거부
r = call("compare_passes_for_commute", {"monthly_rides": -5, "fare_per_ride": 1500, "age": 30})
rec("G2", "음수 monthly_rides: 검증 실패",
    "__TOOL_ERROR__" in r or "__RPC_ERROR__" in r, "음수 허용됨", r[:200])

# 2-5) 음수 age — validation
r = call("check_pass_eligibility", {"age": -3, "residence": "서울"})
rec("G2", "음수 age: 검증 실패 또는 안전 처리",
    "__TOOL_ERROR__" in r or "__RPC_ERROR__" in r or "❌" in r,
    "음수 age 무방비", r[:200])

# 2-6) 잘못된 as_of_date 포맷
r = call("compare_passes_for_commute",
         {"monthly_rides": 44, "fare_per_ride": 1550, "age": 30,
          "residence": "서울", "as_of_date": "2026/07/07"})
rec("G2", "잘못된 date 포맷: 검증 실패 메시지",
    "__TOOL_ERROR__" in r or "__RPC_ERROR__" in r,
    "date 포맷 검증 통과 (should fail)", r[:200])

# 2-7) usage_month + as_of_date 동시 (충돌?)
r = call("compare_passes_for_commute",
         {"monthly_rides": 44, "fare_per_ride": 1550, "age": 30,
          "residence": "서울", "usage_month": "2026-08", "as_of_date": "2026-07-07"})
rec("G2", "usage_month+as_of_date 동시: 정상 처리",
    "__" not in r, "동시 지정 시 실패", r[:200])

# 2-8) 극단적 fare_per_ride (KTX급 만원)
r = call("simulate_pass_savings",
         {"pass_id": "modu-card", "monthly_rides": 20, "fare_per_ride": 10000,
          "age": 30, "residence": "서울", "as_of_date": "2026-07-07"})
rec("G2", "고액 fare: 계산 안정성",
    "__" not in r and "월 환급" in r, "고액 케이스 실패", r[:200])

# 2-9) residence="" (미해석) — 전국 기준으로 fallback
r = call("compare_passes_for_commute",
         {"monthly_rides": 44, "fare_per_ride": 1550, "age": 30,
          "residence": "", "as_of_date": "2026-07-07"})
rec("G2", "빈 residence: '전국 기준' fallback 메시지",
    "전국 기준" in r or "해석하지 못" in r or "모두의카드" in r,
    "빈 지역 fallback 실패", r[:200])

# 2-10) 미지 지역 — unknown confidence fallback
r = call("compare_passes_for_commute",
         {"monthly_rides": 44, "fare_per_ride": 1550, "age": 30,
          "residence": "화성 크레이터", "as_of_date": "2026-07-07"})
rec("G2", "미지 지역 '화성 크레이터': 우아하게 fallback",
    "__" not in r and ("전국" in r or "해석" in r or "모두의카드" in r),
    "미지 지역 crash", r[:300])


# ═════════ G3 — KakaoTalk UX 적합성 (편의성)
print("\n━━ G3 · KakaoTalk UX 적합성 (편의성)")

# 3-1) 응답 길이: KT 챗봇은 ~1200자 이내가 편함 (concise)
r = call("compare_passes_for_commute",
         {"monthly_rides": 44, "fare_per_ride": 1550, "age": 30,
          "residence": "서울", "as_of_date": "2026-07-07", "detail": "concise"})
rec("G3", f"concise 길이 KT 적합 ({len(r)} chars, target <1500)",
    len(r) < 1500, f"concise 응답이 {len(r)}자로 김", r[:200])

# 3-2) detailed 응답도 3000자 넘지 않도록
r = call("compare_passes_for_commute",
         {"monthly_rides": 44, "fare_per_ride": 1550, "age": 30,
          "residence": "서울", "as_of_date": "2026-07-07", "detail": "detailed"})
rec("G3", f"detailed 길이 상한 ({len(r)} chars, target <3000)",
    len(r) < 3000, f"detailed 응답 {len(r)}자 초과", r[-300:])

# 3-3) 결론 첫 줄 — LLM이 최상단만 뽑아도 답이 되는지
r = call("compare_passes_for_commute",
         {"monthly_rides": 44, "fare_per_ride": 1550, "age": 30,
          "residence": "서울", "as_of_date": "2026-07-07"})
first_line = r.split("\n", 1)[0]
rec("G3", "첫 줄이 자체 완결된 결론",
    "결론" in first_line and ("원" in first_line or "패스" in first_line),
    "결론 문장이 상단에 없음", first_line)

# 3-4) 마크다운 헤더/테이블 구조 — MCP 클라이언트에서 렌더 가능해야
rec("G3", "마크다운 테이블 사용 (| ... |)",
    r.count("|") >= 4, "테이블 구조 부재", r[:300])

# 3-5) 존댓말/친절함 — 한국어 톤
r = call("check_pass_eligibility", {"age": 20, "residence": "서울"})
rec("G3", "한국어 톤: 존댓말·안내",
    "합니다" in r or "요" in r or "확인" in r, "톤이 어색", r[:200])

# 3-6) 이모지·시각 표식 — 자격 O/X 즉시 식별
rec("G3", "자격 O/X 시각 표식 (✅/❌)",
    "✅" in r or "❌" in r, "자격 표식 부재", r[:200])

# 3-7) 출처 명시 — 신뢰성 (안정성 축과도 겹침)
r = call("compare_passes_for_commute",
         {"monthly_rides": 44, "fare_per_ride": 1550, "age": 30,
          "residence": "서울", "as_of_date": "2026-07-07"})
rec("G3", "출처/검증일자 노출",
    "출처" in r or "확인 기준" in r or "korea-pass.kr" in r or "2026" in r,
    "출처 미표기", r[-300:])

# 3-8) 다국어 지명 저항 — 영어/한자
r = call("check_pass_eligibility", {"age": 30, "residence": "Seoul"})
rec("G3", "영어 지명 'Seoul': fallback 또는 해석",
    "__" not in r, "영어 지명 crash", r[:200])


# ═════════ G4 — 정률↔정액 크로스오버 & 이사 시나리오 (창의성)
print("\n━━ G4 · 크로스오버·손익분기 (창의성)")

# 4-1) 정률형이 정액형을 이기는 저이용자 시나리오
r_low = call("simulate_pass_savings",
             {"pass_id": "modu-card", "monthly_rides": 18, "fare_per_ride": 1200,
              "age": 30, "residence": "서울", "as_of_date": "2026-07-07",
              "detail": "detailed"})
rec("G4", "저이용자(18회×1200): 정률형이 이김",
    "기본형(정률)" in r_low, "정률 선택 실패", r_low)

# 4-2) 고이용자 — 정액형(플러스형) 이김
r_high = call("simulate_pass_savings",
              {"pass_id": "modu-card", "monthly_rides": 60, "fare_per_ride": 2500,
               "age": 30, "residence": "서울", "as_of_date": "2026-07-07"})
rec("G4", "고이용자(60회×2500): 정액형 선택",
    "정액형" in r_high, "고이용 → 정액 선택 실패", r_high)

# 4-3) 크로스오버 스윕 — 승차횟수에 따라 최적 상품이 바뀌는가?
sweeps = []
for rides in [10, 20, 30, 40, 50, 60]:
    r = call("simulate_pass_savings",
             {"pass_id": "modu-card", "monthly_rides": rides, "fare_per_ride": 1500,
              "age": 30, "residence": "서울", "as_of_date": "2026-07-07"})
    reb = money(r, r"월 환급: ([\d,]+)원") or 0
    label = "정률" if "정률" in r else ("일반형" if "일반형" in r else ("플러스" if "플러스" in r else "?"))
    sweeps.append((rides, label, reb))
print("       ┌ 승차횟수별 최적 상품 스윕:")
for rides, label, reb in sweeps:
    print(f"       │ {rides:>2}회 × 1500원 → {label:<6} 환급 {reb:>7,}원")
labels = [s[1] for s in sweeps]
rec("G4", "승차횟수 스윕: 최적 상품이 실제로 변함",
    len(set(labels)) >= 2, "모든 구간 동일 상품 → 크로스오버 없음", "")

# 4-4) 이사 시나리오 — 부산→서울 이사 전후 최적 패스 다름
r_busan = call("compare_passes_for_commute",
               {"monthly_rides": 44, "fare_per_ride": 1450, "age": 30,
                "residence": "부산", "as_of_date": "2026-07-07"})
r_seoul = call("compare_passes_for_commute",
               {"monthly_rides": 44, "fare_per_ride": 1450, "age": 30,
                "residence": "서울", "as_of_date": "2026-07-07"})
rec("G4", "이사 시나리오: 부산엔 동백, 서울엔 기동카/모두의카드",
    "동백" in r_busan and "동백" not in r_seoul,
    "지역별 옵션 세트 미분화", "")

# 4-5) 시점 시나리오 — 8월(종료 임박) vs 9월(완전 종료)
r_aug = call("compare_passes_for_commute",
             {"monthly_rides": 44, "fare_per_ride": 1550, "age": 30,
              "residence": "서울", "as_of_date": "2026-08-15"})
r_sep = call("compare_passes_for_commute",
             {"monthly_rides": 44, "fare_per_ride": 1550, "age": 30,
              "residence": "서울", "as_of_date": "2026-09-15"})
rec("G4", "8월 vs 9월: 기후동행카드 존재감 변화",
    ("기후동행" in r_aug) and ("종료" in r_sep or "전환" in r_sep or "기후동행" not in r_sep),
    "시점별 옵션 세트 static", f"aug has 기동카: {'기후동행' in r_aug}, sep: {'기후동행' in r_sep}")

# 4-6) 통근 밀도 — 주 3일 vs 5일 (14회 vs 22회 편도 → 왕복 44회) 손익분기
r_part = call("simulate_pass_savings",
              {"pass_id": "modu-card", "monthly_rides": 14, "fare_per_ride": 1500,
               "age": 30, "residence": "서울", "as_of_date": "2026-07-07"})
r_full = call("simulate_pass_savings",
              {"pass_id": "modu-card", "monthly_rides": 44, "fare_per_ride": 1500,
               "age": 30, "residence": "서울", "as_of_date": "2026-07-07"})
part_r = money(r_part, r"월 환급: ([\d,]+)원") or 0
full_r = money(r_full, r"월 환급: ([\d,]+)원") or 0
rec("G4", f"통근 밀도 대비 환급 규모 (14회={part_r:,} vs 44회={full_r:,})",
    full_r > part_r, "밀도 증가에도 환급 동일/역전", "")


# ═════════ G5 — KT 대화 흐름 재현 (전체 rubric)
print("\n━━ G5 · KakaoTalk 대화 흐름 재현 (창의성+편의성)")

def kt_turn(label: str, tool: str, args: dict):
    r = call(tool, args)
    print(f"\n  👤 [{label}]")
    print(textwrap.indent(r, "     🤖 "))
    return r

# Simulated multi-turn conversation from a real user perspective
print("\n  ─── 대화 재현: '서울 살다 부산 이사 예정, 어떻게 준비할까요?' ───")
t1 = kt_turn("서울 34세 청년, 지하철+버스 44회 통근",
             "compare_passes_for_commute",
             {"monthly_rides": 44, "fare_per_ride": 1550, "age": 34,
              "residence": "서울 마포구", "as_of_date": "2026-07-07"})
t2 = kt_turn("부산 이사 후 계산해줘",
             "compare_passes_for_commute",
             {"monthly_rides": 44, "fare_per_ride": 1450, "age": 34,
              "residence": "부산 해운대구", "as_of_date": "2026-07-07"})
t3 = kt_turn("동백패스 자세히 알려줘",
             "get_pass_details", {"pass_id": "dongbaek-pass"})
t4 = kt_turn("나 저소득인데 자격 되나?",
             "check_pass_eligibility",
             {"age": 34, "residence": "부산 해운대구", "income_level": "low_income"})

rec("G5", "T1(서울)→T2(부산) 결과 실제로 다름",
    ("모두의카드" in t1 and "결론" in t1) and ("동백" in t2 or "부산" in t2),
    "이사 전후 결과 동질", "")
rec("G5", "T3 상세 응답이 정보 밀도 확보 (>300자)",
    len(t3) > 300, f"상세 응답 {len(t3)}자로 부실", "")
# 서술형 재작성 확인 — dict raw dump가 아니라 문장형 서술
rec("G5", "T3 서술형 문장(자격·작동 방식·적용 범위 명시)",
    ("자격" in t3 and "작동 방식" in t3 and "적용 범위" in t3),
    "dict raw dump — 서술형 재작성 미반영", t3[:200])
rec("G5", "T4 저소득 반영해 rate 상향",
    "53.3%" in t4 or "저소득" in t4, "저소득 rate 반영 실패", t4[:200])


# ═════════ G6 — 신설 tool 두 개 (창의성 강화 축)
print("\n━━ G6 · 신설 tool: find_breakeven_rides + simulate_free_ride_choice")

# 6-1) 손익분기: 서울 청년 1500원 — 전환점 최소 1개 관측
r = call("find_breakeven_rides",
         {"fare_per_ride": 1500, "age": 30, "residence": "서울",
          "as_of_date": "2026-07-07"})
rec("G6", "손익분기: 정률→정액 전환점 자동 탐지",
    "전환" in r and ("정률형" in r and "정액형" in r), "전환 탐지 실패", r[:300])
rec("G6", "손익분기: 15회 게이트 명시",
    "15회" in r and "가입 임계" in r, "게이트 안내 누락", r[:200])
rec("G6", "손익분기: 참고 표에 여러 지점",
    r.count("회 |") >= 5, "요약 표 지점 부족", r[-300:])

# 6-2) 손익분기: 고가 fare(3000원, 광역버스) — 전환점이 더 낮은 승차수에서
r_hi = call("find_breakeven_rides",
            {"fare_per_ride": 3000, "age": 30, "residence": "서울",
             "as_of_date": "2026-07-07"})
r_lo = call("find_breakeven_rides",
            {"fare_per_ride": 1200, "age": 30, "residence": "서울",
             "as_of_date": "2026-07-07"})
# 고가 요금은 전환점(정률→정액)이 더 이른 승차수. 원시 텍스트에서 첫 전환 회수 추출.
def first_transition_rides(text: str) -> int | None:
    m = re.search(r"월 (\d+)회 도달 시", text)
    return int(m.group(1)) if m else None
hi_t = first_transition_rides(r_hi)
lo_t = first_transition_rides(r_lo)
rec("G6", f"고가 fare 전환점 더 이름 (3000원: {hi_t}회, 1200원: {lo_t}회)",
    hi_t is not None and lo_t is not None and hi_t < lo_t,
    "요금 스케일링이 반영되지 않음", "")

# 6-3) 손익분기: 15회 미만 요구 → 검증 실패 or 안전 처리 (0 fare)
r = call("find_breakeven_rides", {"fare_per_ride": 0, "residence": "서울"})
rec("G6", "손익분기: fare_per_ride=0 거부",
    "__TOOL_ERROR__" in r or "__RPC_ERROR__" in r, "0원 통과", r[:200])

# 6-4) 무임+환급 딜레마: 서울 66세 — 무임카드 승리
r = call("simulate_free_ride_choice",
         {"monthly_rides": 44, "fare_per_ride": 1550, "age": 66,
          "residence": "서울", "as_of_date": "2026-07-07"})
rec("G6", "무임+환급: 서울 66세는 A(무임) 승리",
    "A(무임카드)" in r and "월 결제" in r,
    "무임 시나리오 승자 오류", r[:300])
rec("G6", "무임+환급: 두 시나리오 실질 부담 표",
    "0원" in r and r.count("| **") >= 2, "시나리오 병기 부재", r[:300])

# 6-5) 무임+환급: 대전 71세 — 대전 70+ 무임 규정 노출
r = call("simulate_free_ride_choice",
         {"monthly_rides": 44, "fare_per_ride": 1400, "age": 71,
          "residence": "대전", "as_of_date": "2026-07-07"})
rec("G6", "무임+환급: 지역별 무임 규정 노출 (대전 70+)",
    "70세" in r or "무임" in r, "지역 규정 미노출", r[:300])


# ═════════ 리포트
print("\n" + "═" * 70)
print(" 요약")
print("═" * 70)
by_group: dict[str, list[Finding]] = {}
for f in findings:
    by_group.setdefault(f.group, []).append(f)
total_pass = 0
total = 0
for g, fs in by_group.items():
    p = sum(1 for f in fs if f.passed)
    total_pass += p; total += len(fs)
    print(f"  {g}: {p}/{len(fs)} passed")
print(f"\n  전체: {total_pass}/{total}")
if total_pass < total:
    print("\n  실패 항목:")
    for f in findings:
        if not f.passed:
            print(f"   ✗ [{f.group}] {f.scenario}")
            if f.detail:
                print(f"       └ {f.detail}")
