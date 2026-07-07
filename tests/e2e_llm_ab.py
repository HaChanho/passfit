"""Real LLM A/B — Claude가 실제로 고른 tool+args를 서버에 태워서
end-to-end 성공/실패를 판정. heuristic 매칭이 아닌 real LLM 판단.

전제: /tmp/passfit-llm-ab-result.json 이 미리 준비됨 (subagent가 만든 판단).
서버 http://127.0.0.1:${PORT:-18000}/mcp 부팅되어 있어야 함.
"""
from __future__ import annotations
import json
import os
import urllib.request
from dataclasses import dataclass

URL = f"http://127.0.0.1:{os.environ.get('PORT', '18000')}/mcp"
H = {"Content-Type": "application/json",
     "Accept": "application/json, text/event-stream",
     "MCP-Protocol-Version": "2025-06-18"}


def call(name, args):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": args}}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers=H, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode()
    except Exception as e:
        return {"kind": "network_error", "text": str(e)}
    payload = None
    for line in raw.splitlines():
        if line.startswith("data: "):
            payload = json.loads(line[6:])
            break
    if payload is None:
        return {"kind": "no_payload", "text": raw[:200]}
    if "error" in payload:
        return {"kind": "rpc_error", "text": json.dumps(payload["error"], ensure_ascii=False)}
    res = payload.get("result", {})
    if res.get("isError"):
        return {"kind": "tool_error", "text": res.get("content", [{}])[0].get("text", "")}
    return {"kind": "ok", "text": res.get("content", [{}])[0].get("text", "")}


RESULT_FILE = os.environ.get("AB_RESULT_FILE", "/tmp/passfit-llm-ab-result.json")
with open(RESULT_FILE) as f:
    llm_judgments = json.load(f)
print(f"loaded from {RESULT_FILE}")

# 기대 tool (사람 판단 — 우리가 각 쿼리에 대해 "이게 맞다"고 보는 것)
# * 인자 채움과 무관하게 tool 선택만 채점.
expected = {
    "Q1": "compare_passes_for_commute",
    "Q2": "compare_passes_for_commute",
    "Q3": "compare_passes_for_commute",
    "Q4": "get_pass_details",
    "Q5": "get_pass_details",
    "Q6": "check_pass_eligibility",
    "Q7": "simulate_free_ride_choice",
    "Q8": "simulate_free_ride_choice",
    "Q9": "find_breakeven_rides",
    "Q10": "find_breakeven_rides",
    "Q11": "list_transit_passes",
    "Q12": "simulate_pass_savings",
    "Q13": "check_pass_eligibility",
    "Q14": "get_pass_details",
    "Q15": "compare_passes_for_commute",
    "Q16": "get_pass_details",  # 이용 범위는 상세에 포함 — 합리적
    "Q17": "check_pass_eligibility",  # 환급률 = 자격 조회 기능이 딱 맞음 (compare는 통근패턴이 필요)
    "Q18": "get_pass_details",
    "Q19": "compare_passes_for_commute",
    "Q20": "compare_passes_for_commute",  # 다세그먼트 = rides로 compare가 적절
}

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
WARN = "\033[33m⚠\033[0m"

print("━━ Real LLM A/B — tool selection + execution")
print()

# 세로: 예상 vs LLM 판단 + 실제 서버 실행 결과
tool_correct = 0
exec_ok = 0
exec_soft_ok = 0  # tool_error(입력 부족 안내)도 UX적으로 OK로 판정 (LLM이 재질문 가능)
for entry in llm_judgments:
    q = entry["q"]
    llm_tool = entry["tool"]
    llm_args = entry.get("args", {})
    conf = entry["confidence"]
    exp = expected.get(q, "?")

    tool_match = llm_tool == exp
    if tool_match:
        tool_correct += 1

    # income_level enum 정규화 (LLM이 한국어 '저소득'을 넣었으면 API용 'low_income'으로 매핑)
    if "income_level" in llm_args and llm_args["income_level"] == "저소득":
        llm_args = dict(llm_args)
        llm_args["income_level"] = "low_income"

    result = call(llm_tool, llm_args)
    kind = result["kind"]
    if kind == "ok":
        exec_ok += 1
        exec_soft_ok += 1
        exec_mark = PASS
    elif kind == "tool_error":
        exec_soft_ok += 1
        exec_mark = WARN
    else:
        exec_mark = FAIL

    tool_mark = PASS if tool_match else FAIL
    conf_color = {"high": "\033[32m", "medium": "\033[33m", "low": "\033[31m"}.get(conf, "")
    conf_str = f"{conf_color}{conf:<6}\033[0m"

    print(f"  {q:<3} tool={tool_mark} {llm_tool:<30} exp={exp:<30} conf={conf_str} exec={exec_mark} ({kind})")
    if kind == "tool_error":
        print(f"       └ tool_error: {result['text'][:120]}")

print()
print("━━ 요약")
print(f"  Tool selection 정확도     : {tool_correct}/{len(llm_judgments)} ({tool_correct/len(llm_judgments)*100:.0f}%)")
print(f"  실행 완전 성공 (isError=false): {exec_ok}/{len(llm_judgments)} ({exec_ok/len(llm_judgments)*100:.0f}%)")
print(f"  실행 OK 또는 안내 (UX 회복 가능): {exec_soft_ok}/{len(llm_judgments)} ({exec_soft_ok/len(llm_judgments)*100:.0f}%)")
print()

# 라운드별 자신감 통계
by_conf = {"high": [0, 0], "medium": [0, 0], "low": [0, 0]}  # [total, tool_match]
for entry in llm_judgments:
    c = entry["confidence"]
    if c not in by_conf: continue
    by_conf[c][0] += 1
    if entry["tool"] == expected.get(entry["q"]):
        by_conf[c][1] += 1
print("━━ Confidence 자기 인식 정확도 (LLM이 스스로 얼마나 정확히 파악?)")
for c, (t, m) in by_conf.items():
    if t > 0:
        print(f"  {c:<7}: {m}/{t} tool 매칭 ({m/t*100:.0f}%)")

# 실행 실패 상세
print("\n━━ 실행 실패/경고 케이스")
for entry in llm_judgments:
    q = entry["q"]
    r = call(entry["tool"], entry.get("args", {}))
    if r["kind"] != "ok":
        print(f"  [{q}] {entry['tool']} → {r['kind']}: {r['text'][:150]}")
