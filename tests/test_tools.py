import pytest
from fastmcp import Client
from passfit.server import mcp


async def test_list_tools_has_seven_with_annotations():
    async with Client(mcp) as c:
        tools = {t.name: t for t in await c.list_tools()}
        assert set(tools) == {"list_transit_passes", "get_pass_details",
                              "compare_passes_for_commute", "simulate_pass_savings",
                              "check_pass_eligibility", "find_breakeven_rides",
                              "simulate_free_ride_choice"}
        for t in tools.values():
            assert t.annotations.readOnlyHint is True


async def test_compare_happy_path():
    async with Client(mcp) as c:
        r = await c.call_tool("compare_passes_for_commute", {
            "monthly_rides": 44, "fare_per_ride": 1550, "age": 35,
            "residence": "성남", "usage_month": "2026-07"})
        text = r.content[0].text
        assert "청년" in text
        assert "경기도" in text or "경기" in text
        assert "korea-pass.kr" in text


async def test_compare_missing_pattern_returns_guidance():
    async with Client(mcp) as c:
        r = await c.call_tool("compare_passes_for_commute",
                              {"age": 30, "residence": "서울"}, raise_on_error=False)
        assert r.is_error
        assert "월 교통비 총액" in str(r.content)


async def test_simulate_alias_to_base():
    async with Client(mcp) as c:
        r = await c.call_tool("simulate_pass_savings", {
            "pass_id": "climate-card-plus", "monthly_rides": 44,
            "fare_per_ride": 1550, "age": 30, "residence": "서울"})
        assert "모두의카드" in r.content[0].text


async def test_details_and_list_policies():
    async with Client(mcp) as c:
        d = await c.call_tool("get_pass_details", {"pass_id": "climate-card-plus"})
        assert "모두의카드" in d.content[0].text and "따릉이" in d.content[0].text
        l = await c.call_tool("list_transit_passes", {"region": "서울"})
        assert "기후동행카드 플러스" in l.content[0].text


async def test_eligibility_enforces_age_min():
    async with Client(mcp) as c:
        r = await c.call_tool("check_pass_eligibility",
                              {"age": 15, "residence": "부산"})
        assert "❌" in r.content[0].text and "동백" in r.content[0].text
        r2 = await c.call_tool("check_pass_eligibility",
                               {"age": 40, "residence": "부산"})
        assert "부산 동백패스: ✅" in r2.content[0].text


async def test_breakeven_finds_transitions():
    async with Client(mcp) as c:
        # 청년 서울, 1500원 — 15회 게이트 + 정률→정액 전환이 관측되어야
        r = await c.call_tool("find_breakeven_rides", {
            "fare_per_ride": 1500, "age": 30, "residence": "서울",
            "as_of_date": "2026-07-07"})
        text = r.content[0].text
        assert "가입 임계" in text and "15회" in text
        assert "정률형" in text and "정액형" in text
        assert "청년" in text and "30.0%" in text
        # 참고 표에 여러 지점의 최적 상품이 나열되어야
        assert "44회" in text


async def test_breakeven_rejects_zero_fare():
    async with Client(mcp) as c:
        r = await c.call_tool("find_breakeven_rides",
                              {"fare_per_ride": 0, "residence": "서울"},
                              raise_on_error=False)
        assert r.is_error


async def test_free_ride_choice_shows_both_scenarios():
    async with Client(mcp) as c:
        # 66세 서울 통근자 — 무임(0원) vs 유임+환급 두 시나리오 병기
        r = await c.call_tool("simulate_free_ride_choice", {
            "monthly_rides": 44, "fare_per_ride": 1550, "age": 66,
            "residence": "서울", "as_of_date": "2026-07-07"})
        text = r.content[0].text
        assert "A. 무임카드" in text and "B. 유임" in text
        assert "결론:" in text
        # 서울권 무임 규정(65+ 도시철도)도 노출되어야
        assert "65세" in text or "무임" in text


async def test_free_ride_choice_rejects_bad_input():
    async with Client(mcp) as c:
        r = await c.call_tool("simulate_free_ride_choice",
                              {"monthly_rides": 0, "fare_per_ride": 1500,
                               "age": 70, "residence": "대전"},
                              raise_on_error=False)
        assert r.is_error
