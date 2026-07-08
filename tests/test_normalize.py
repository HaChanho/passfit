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


def test_busan_district_not_misread_as_daegu():
    r = resolve_region("해운대구")
    assert r.sido == "부산"          # '해운대' alias가 '대구' 부분일치를 이김
    r2 = resolve_region("부산 해운대구")
    assert r2.sido == "부산"


def test_gyeongnam_province_and_cities_resolve():
    # 경남은 regional_overrides(저소득 100%)를 가지지만, 광역 지명·창원/김해/양산/진주
    # 외 도시는 미해석되어 전국(53.3%)으로 오계산되던 버그 회귀.
    for text in ["경남", "경상남도", "경남 통영시", "경상남도 거제시", "통영", "밀양"]:
        assert resolve_region(text).sido == "경남", text
    assert resolve_region("경남").region_class == "일반지방권"
