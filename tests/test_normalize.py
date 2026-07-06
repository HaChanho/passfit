from passfit.normalize import resolve_region


def test_alias_variants_resolve_to_same_sido():
    for text in ["성남", "분당", "경기도 성남시", "경기 성남"]:
        r = resolve_region(text)
        assert r.sido == "경기", text
        assert r.region_class == "수도권"


def test_special_zone_overrides_class():
    r = resolve_region("경기도 가평군")
    assert r.sido == "경기" and r.region_class == "우대지원지역"


def test_unknown_region_falls_back():
    r = resolve_region("제주도 서귀포")
    assert r.sido is None and r.region_class == "일반지방권" and r.confidence == "unknown"


def test_confidence_reported():
    assert resolve_region("판교").confidence == "alias"
    assert resolve_region("서울").confidence == "exact"


def test_compound_city_name_disambiguation():
    # 경기도 광주시(경기) vs 광주광역시(광주) — 앞선 위치 매칭이 이김. YAML 순서 바뀌어도 유지되어야 함
    assert resolve_region("경기도 광주시").sido == "경기"
    assert resolve_region("광주광역시").sido == "광주"
    assert resolve_region("광주").sido == "광주"
