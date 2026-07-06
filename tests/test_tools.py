import pytest
from fastmcp import Client
from passfit.server import mcp


async def test_list_tools_has_five_with_annotations():
    async with Client(mcp) as c:
        tools = {t.name: t for t in await c.list_tools()}
        assert set(tools) == {"list_transit_passes", "get_pass_details",
                              "compare_passes_for_commute", "simulate_pass_savings",
                              "check_pass_eligibility"}
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
