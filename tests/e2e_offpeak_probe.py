"""S6 재검증: 정률형이 반드시 이기는 케이스에서 offpeak 반영을 확인.

정액형 기준금액(청년/수도권 half=25,000)보다 spend가 낮으면 정액형 환급≈0 →
정률형이 이길 수밖에 없다. 이 상태에서 offpeak를 0과 20으로 비교하면
정률형 로직의 +30%p가 관측된다.
"""
from __future__ import annotations
import json, os, re, urllib.request

URL = f"http://127.0.0.1:{os.environ.get('PORT', '18000')}/mcp"
H = {"Content-Type": "application/json",
     "Accept": "application/json, text/event-stream",
     "MCP-Protocol-Version": "2025-06-18"}


def call(name, args, rid=1):
    body = {"jsonrpc": "2.0", "id": rid, "method": "tools/call",
            "params": {"name": name, "arguments": args}}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers=H, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read().decode()
    for line in raw.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])["result"]["content"][0]["text"]


# 낮은 spend: 20회 × 1200원 = 24,000원 < 25,000원 기준금액 → 정액형 환급 0
# 청년 30% 정률 → 24,000 × 30% = 7,200원 (offpeak 0회)
# offpeak 15회 × 1200 = 18,000원에 +30%p 얹으면:
#   normal 6,000×30% + offpeak 18,000×60% = 1,800 + 10,800 = 12,600원
BASE = {"monthly_rides": 20, "fare_per_ride": 1200, "age": 34,
        "residence": "서울", "as_of_date": "2026-07-07", "detail": "detailed"}

r0 = call("simulate_pass_savings", {**BASE, "pass_id": "modu-card", "offpeak_rides": 0}, rid=1)
r1 = call("simulate_pass_savings", {**BASE, "pass_id": "modu-card", "offpeak_rides": 15}, rid=2)

print("── offpeak=0 ──")
print(r0)
print("── offpeak=15 ──")
print(r1)

m0 = int(re.search(r"월 환급: ([\d,]+)원", r0).group(1).replace(",", ""))
m1 = int(re.search(r"월 환급: ([\d,]+)원", r1).group(1).replace(",", ""))
print(f"\noffpeak 0회 환급: {m0:,}원")
print(f"offpeak 15회 환급: {m1:,}원")
print(f"delta: +{m1 - m0:,}원  (기대: +5,400원 = 18,000 × 30%p)")
assert m1 > m0, f"offpeak 로직이 살아있어야 함 — got {m0} → {m1}"
assert m1 - m0 == 5400, f"delta 예측 실패 — expected 5400, got {m1 - m0}"
print("\n✓ offpeak +30%p 로직 정상 반영")
