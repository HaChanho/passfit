# PassFit (패스핏)

2026년 한국 대중교통 패스 내비게이터 MCP 서버.

통근 패턴(승차 횟수, 요금, 거주지, 연령 등)을 알려주면 모두의카드(구 K-패스)·기후동행카드·지자체 패스를 교차 계산해 최적 선택과 월/연 절약액을 알려줍니다. 손익분기(몇 회부터 정액형이 유리한지)와 어르신 무임 vs 유임+환급 비교까지 지원합니다.

## 특징

- 데이터 출처: korea-pass.kr, korea.kr 정책브리핑, 서울시·각 지자체 공식 자료 (2026-07-06 검증)
- 외부 API 호출 없음 — 정적 검증 데이터 + 결정론적 계산 (지연/실패 변동 없음)
- Streamable HTTP 전송, stateless

## 도구 (7)

- `compare_passes_for_commute` — 통근 패턴을 입력하면 모든 패스를 비교·랭킹
- `simulate_pass_savings` — 특정 패스의 월/연 절약액 시뮬레이션
- `list_transit_passes` — 지원하는 패스 목록 조회
- `get_pass_details` — 패스 상세 정보(자격 요건·환급률·신청 방법·유효기간)
- `check_pass_eligibility` — 특정 패스의 자격 충족 여부 확인
- `find_breakeven_rides` — 월 몇 회부터 이득인지·정률↔정액 손익분기 분석
- `simulate_free_ride_choice` — 어르신 무임카드 vs 유임 결제+환급 비교

## 로컬 실행

```bash
pip install .
python -m passfit.server   # http://0.0.0.0:8080/mcp
```

## 개발

```bash
pip install -e '.[dev]'
pytest
```
