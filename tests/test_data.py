from passfit.data_loader import load_passes, load_regions, load_fares

def test_passes_load_and_have_required_fields():
    data = load_passes()
    ids = {p["id"] for p in data["passes"]}
    assert {"modu-card", "climate-card-legacy", "climate-card-plus", "dongbaek-pass", "eung-pass"} <= ids
    modu = next(p for p in data["passes"] if p["id"] == "modu-card")
    assert modu["conditions"]["first_month_min_rides_exempt"] is True
    assert modu["flat_thresholds"]["수도권"]["general"] == [62000, 100000]
    tb = {b["id"]: b for b in modu["temporary_benefits"]}
    assert tb["half-price"]["applies_to"] == "flat_only"
    assert tb["offpeak-bonus"]["applies_to"] == "rebate_only"

def test_all_passes_have_sources():
    for p in load_passes()["passes"]:
        assert p.get("sources"), f"{p['id']} missing sources"

def test_regions_and_fares():
    regions = load_regions()
    assert regions["sido_class"]["서울"] == "수도권"
    assert any(z["name"] == "가평군" for z in regions["special_zones"])
    fares = load_fares()
    assert fares["default_fares"]["subway"] == 1550
    assert "gtx" in fares["flat_standard_excluded_modes"]
