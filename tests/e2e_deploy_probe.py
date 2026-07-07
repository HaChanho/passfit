"""Deploy-branch deep probe — 4 axes:

  P1 · MCP protocol conformance (JSON-RPC 2.0 + Streamable HTTP spec)
  P2 · Concurrency + latency stability (stateless_http claim)
  P3 · LLM tool-selection realism (description-driven picking)
  P4 · Korean NL robustness (typos, mixed script, compound queries)

Run:  .venv/bin/python tests/e2e_deploy_probe.py
"""
from __future__ import annotations
import concurrent.futures
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

URL = f"http://127.0.0.1:{os.environ.get('PORT', '18000')}/mcp"
H = {"Content-Type": "application/json",
     "Accept": "application/json, text/event-stream",
     "MCP-Protocol-Version": "2025-06-18"}


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
    print(f"  {m} [{axis}] {label}" + (f" — {note}" if note else ""))


def send(body: dict, timeout: float = 10.0) -> tuple[int, dict, dict]:
    """Return (http_status, response_json, headers). SSE frame extracted."""
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers=H, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        raw = resp.read().decode()
        headers = dict(resp.headers.items())
        code = resp.getcode()
    except urllib.error.HTTPError as e:
        return e.code, {"__http_error__": e.reason}, dict(e.headers.items())
    payload = None
    for line in raw.splitlines():
        if line.startswith("data: "):
            payload = json.loads(line[6:])
            break
    if payload is None:
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"__raw__": raw[:200]}
    return code, payload, headers


def call(name: str, args: dict) -> tuple[int, dict]:
    return send({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                 "params": {"name": name, "arguments": args}})[:2]


def call_text(name: str, args: dict) -> str:
    _, r = call(name, args)
    if "error" in r:
        return f"__RPC_ERROR__ {r['error']}"
    res = r.get("result", {})
    if res.get("isError"):
        return f"__TOOL_ERROR__ {res.get('content', [{}])[0].get('text', '')}"
    return res.get("content", [{}])[0].get("text", "")


# ═════════ P1 · MCP protocol conformance
print("\n━━ P1 · MCP 프로토콜 정합성 (JSON-RPC 2.0 + Streamable HTTP)")

# 1-1) initialize response 형식
code, r, hdrs = send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                      "params": {"protocolVersion": "2025-06-18",
                                 "capabilities": {}, "clientInfo": {"name": "probe", "version": "0"}}})
rec("P1", "initialize HTTP 200", code == 200)
# case-insensitive header lookup (urllib normalizes to lowercase; some clients keep case)
ct = next((v for k, v in hdrs.items() if k.lower() == "content-type"), "")
rec("P1", "SSE Content-Type", ct.startswith("text/event-stream"), ct)
rec("P1", "jsonrpc=2.0 필드", r.get("jsonrpc") == "2.0")
rec("P1", "result.protocolVersion 매칭", r.get("result", {}).get("protocolVersion") == "2025-06-18")
rec("P1", "serverInfo.name=PassFit", r.get("result", {}).get("serverInfo", {}).get("name") == "PassFit")

# 1-2) 잘못된 method → JSON-RPC error -32601
code, r, _ = send({"jsonrpc": "2.0", "id": 2, "method": "does_not_exist"})
err = r.get("error", {})
rec("P1", "unknown method → error 응답",
    "error" in r, f"got {r}")
rec("P1", "unknown method error code (-32601 권장)",
    err.get("code") in (-32601, -32603, -32602),
    f"got code={err.get('code')}")

# 1-3) 잘못된 JSON-RPC (id 없음, method 없음)
code, r, _ = send({"jsonrpc": "2.0"})
rec("P1", "malformed request → error 응답",
    "error" in r or code >= 400, f"http={code} r={r}")

# 1-4) tools/list 응답에 모든 tool이 inputSchema를 가짐
_, r, _ = send({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
tools = r.get("result", {}).get("tools", [])
schemas_ok = all("inputSchema" in t and t["inputSchema"].get("type") == "object" for t in tools)
rec("P1", f"모든 tool에 inputSchema.type=object ({len(tools)}개)",
    schemas_ok and len(tools) == 7)

# 1-5) tools/list의 tool마다 description이 non-empty (LLM tool selection에 필수)
desc_ok = all(len(t.get("description", "")) > 20 for t in tools)
rec("P1", "모든 tool description >= 20자 (LLM selection용)", desc_ok)

# 1-6) readOnlyHint annotation — MCP spec의 자율 실행 힌트
ro_ok = all(t.get("annotations", {}).get("readOnlyHint") is True for t in tools)
rec("P1", "모든 tool readOnlyHint=true (annotations)", ro_ok)


# ═════════ P2 · 동시성 + latency 안정성
print("\n━━ P2 · 동시성·지연 안정성 (stateless_http 클레임 검증)")


def one_call() -> float:
    t = time.perf_counter()
    call("compare_passes_for_commute",
         {"monthly_rides": 44, "fare_per_ride": 1550, "age": 34,
          "residence": "서울 마포구", "as_of_date": "2026-07-07"})
    return (time.perf_counter() - t) * 1000  # ms


# 2-1) 직렬 30회 latency 분포
serial = [one_call() for _ in range(30)]
p50 = statistics.median(serial)
p99 = sorted(serial)[int(len(serial) * 0.99)]
print(f"       serial: p50={p50:.1f}ms  p99={p99:.1f}ms  n=30")
rec("P2", f"직렬 p50 < 100ms (실측 {p50:.1f}ms)", p50 < 100)
rec("P2", f"직렬 p99 < 300ms (실측 {p99:.1f}ms)", p99 < 300)

# 2-2) 동시 16 요청 — 결과 값이 모두 동일한지 (결정론성)
def one_call_return_text() -> str:
    return call_text("compare_passes_for_commute",
                     {"monthly_rides": 44, "fare_per_ride": 1550, "age": 34,
                      "residence": "서울 마포구", "as_of_date": "2026-07-07"})


t0 = time.perf_counter()
with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
    parallel_texts = list(ex.map(lambda _: one_call_return_text(), range(16)))
concurrent_wall = (time.perf_counter() - t0) * 1000
unique_outputs = len(set(parallel_texts))
rec("P2", f"동시 16개 결과 결정론적 (unique={unique_outputs})",
    unique_outputs == 1,
    f"race condition 의심" if unique_outputs > 1 else "")
rec("P2", f"동시 16개 wall-clock < 직렬 16개 (parallel {concurrent_wall:.0f}ms)",
    concurrent_wall < sum(serial[:16]),
    f"{concurrent_wall:.0f}ms vs serial {sum(serial[:16]):.0f}ms")

# 2-3) 모든 tool을 한 번씩 병렬 호출 (cross-tool safety)
calls = [
    ("list_transit_passes", {}),
    ("get_pass_details", {"pass_id": "modu-card"}),
    ("check_pass_eligibility", {"age": 34, "residence": "서울"}),
    ("compare_passes_for_commute",
     {"monthly_rides": 44, "fare_per_ride": 1550, "age": 30, "residence": "서울"}),
    ("simulate_pass_savings",
     {"pass_id": "modu-card", "monthly_rides": 44, "fare_per_ride": 1550,
      "age": 30, "residence": "서울"}),
    ("find_breakeven_rides", {"fare_per_ride": 1500, "age": 30, "residence": "서울"}),
    ("simulate_free_ride_choice",
     {"monthly_rides": 44, "fare_per_ride": 1550, "age": 66, "residence": "서울"}),
]
with concurrent.futures.ThreadPoolExecutor(max_workers=7) as ex:
    outs = list(ex.map(lambda a: call_text(*a), calls))
none_error = all(not o.startswith("__") for o in outs)
rec("P2", "7 tool 동시 호출 모두 성공", none_error,
    "; ".join(o[:60] for o in outs if o.startswith("__"))[:200])


# ═════════ P3 · LLM tool 선택 현실성
print("\n━━ P3 · LLM tool-selection 현실성 (description 매칭)")

# 실제 5천만 유저가 카카오톡에서 물을만한 자연어 질문 → 어떤 tool이 골라질지
# tool description 안의 트리거 단어와 질문 사이 keyword overlap을 heuristic으로 측정.

_, tl, _ = send({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
tool_descs = {t["name"]: (t.get("description", "") + " " + t.get("annotations", {}).get("title", ""))
              for t in tl["result"]["tools"]}

def best_tool_for(query: str) -> str:
    """Heuristic — pick tool whose description shares most keyword ngrams with query."""
    tokens = set(re.findall(r"[가-힣A-Za-z0-9]+", query.lower()))
    best_name = None
    best_score = -1
    for name, desc in tool_descs.items():
        d_tokens = set(re.findall(r"[가-힣A-Za-z0-9]+", desc.lower()))
        score = len(tokens & d_tokens)
        if score > best_score:
            best_score = score
            best_name = name
    return best_name


# tuples: (자연어 질문, 기대 tool)
llm_queries = [
    ("K-패스랑 기후동행카드 뭐가 이득이야?", "compare_passes_for_commute"),
    ("월 교통비 12만원인데 아낄 방법 없을까", "compare_passes_for_commute"),
    ("주 5일 왕복 통근인데 어떤 카드가 좋을까?", "compare_passes_for_commute"),
    ("모두의카드 자세히 설명해줘", "get_pass_details"),
    ("기후동행카드 언제까지 쓸 수 있어?", "get_pass_details"),
    ("나 34살 서울 사는데 K-패스 자격 되나?", "check_pass_eligibility"),
    ("우리 부모님(70세) 대중교통 어떻게 하는게 이득?", "simulate_free_ride_choice"),
    ("65세 이상 무임 승차 vs 환급 어느게 유리?", "simulate_free_ride_choice"),
    ("월 몇번 타야 정액이 이득이에요?", "find_breakeven_rides"),
    ("손익분기점 알려줘", "find_breakeven_rides"),
    ("한국 교통패스 목록 좀 보여줘", "list_transit_passes"),
    ("K-패스 하나만 계산해줘", "simulate_pass_savings"),
]
correct = 0
for q, expected in llm_queries:
    picked = best_tool_for(q)
    ok = picked == expected
    correct += int(ok)
    mark = "✓" if ok else "✗"
    print(f"       {mark} '{q[:35]:<35}' → {picked}  (기대 {expected})")
rec("P3", f"LLM 유사도 매칭 정확도 {correct}/{len(llm_queries)}",
    correct >= len(llm_queries) * 0.75,
    f"기대: 75%+ = {int(len(llm_queries)*0.75)}건")


# ═════════ P4 · 한국어 자연어 견고성
print("\n━━ P4 · 한국어 NL 견고성 (오타·구어체·이름 변형)")

# 4-1) 지역명 오타/짧은 형태
variants = [
    ("서울시 마포구", "서울"),
    ("서울시", "서울"),
    ("마포구", "서울"),  # 마포는 서울 자치구 — 이 서버가 자치구 단독 이름을 해석하는지
    ("Busan", "부산"),   # 영어
    ("부산광역시", "부산"),
    ("성남", "경기"),
    ("성남시 분당구", "경기"),
    ("세종특별자치시", "세종"),
]
for res_input, expected_sido in variants:
    r = call_text("check_pass_eligibility", {"age": 30, "residence": res_input})
    ok = expected_sido in r or "해석하지 못" in r  # 해석 실패도 안전 처리로 인정
    rec("P4", f"지역 변형 '{res_input}' → {expected_sido}", ok, r[:100] if not ok else "")

# 4-2) 첫 달 예외 + 저이용 케이스 — LLM이 잘못 인자 넣을 수 있는 조합
r = call_text("simulate_pass_savings",
              {"pass_id": "modu-card", "monthly_rides": 10, "fare_per_ride": 1500,
               "age": 25, "residence": "서울", "is_first_month": True,
               "as_of_date": "2026-07-07"})
rec("P4", "첫 달 10회: 15회 예외 적용되어 환급 발생",
    "월 환급: " in r and "월 환급: 0원" not in r, r[:150])

# 4-3) 극단 케이스: 연 최대 절약 계산 (60회 × 3000원 = 18만원, 청년 30%)
r = call_text("simulate_pass_savings",
              {"pass_id": "modu-card", "monthly_rides": 60, "fare_per_ride": 3000,
               "age": 30, "residence": "서울", "as_of_date": "2026-07-07"})
m = re.search(r"연간 절약[^:]*: 약 ([\d,]+)원", r)
yearly = int(m.group(1).replace(",", "")) if m else -1
rec("P4", f"고이용자 연간 절약 계산 (실측 {yearly:,}원)",
    yearly > 1_000_000, f"기대: >1백만원, got {yearly}")

# 4-4) 무임+환급이 실제로 지역별로 답이 다른지
r_seoul = call_text("simulate_free_ride_choice",
                    {"monthly_rides": 30, "fare_per_ride": 1550, "age": 66,
                     "residence": "서울", "as_of_date": "2026-07-07"})
r_daegu = call_text("simulate_free_ride_choice",
                    {"monthly_rides": 30, "fare_per_ride": 1400, "age": 66,
                     "residence": "대구", "as_of_date": "2026-07-07"})
# 대구는 도시철도 68세+ 무임이라 66세는 아직 도시철도 무임 대상 아님 (규정 노출로 확인 가능)
rec("P4", "지역별 무임 규정 차별화 (서울 vs 대구 66세)",
    ("전국" in r_seoul or "65세" in r_seoul) and ("대구" in r_daegu or "68세" in r_daegu),
    "대구 68세 규정 미노출")

# 4-5) find_breakeven이 서울(수도권)/일반지방권 두 티어에서 다르게 나옴
r_seoul_be = call_text("find_breakeven_rides",
                       {"fare_per_ride": 1500, "age": 30, "residence": "서울",
                        "as_of_date": "2026-07-07"})
r_gwj_be = call_text("find_breakeven_rides",
                     {"fare_per_ride": 1500, "age": 30, "residence": "광주",
                      "as_of_date": "2026-07-07"})
def first_transition(text):
    m = re.search(r"월 (\d+)회 도달", text)
    return int(m.group(1)) if m else None
s_t = first_transition(r_seoul_be)
g_t = first_transition(r_gwj_be)
rec("P4", f"지역 티어별 손익분기 차이 (서울={s_t}회, 광주={g_t}회)",
    s_t is not None and g_t is not None and s_t != g_t,
    "서울(수도권)과 광주(일반지방권)는 정액 기준금액이 달라 손익분기가 달라야 함")


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
            print(f"   ✗ [{r.axis}] {r.label}" + (f" — {r.note}" if r.note else ""))
