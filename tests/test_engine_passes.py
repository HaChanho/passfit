from datetime import date
from passfit.engine import Pattern, Segment, compare_all

def commuter(rides=44, fare=1550, mode="subway"):
    return Pattern((Segment(mode, fare, rides),))

def base_user(**kw):
    d = dict(age=30, residence="서울", income_level="general", children_count=0,
             is_first_month=False, free_ride_status="none", has_postpaid_climate_card=False)
    d.update(kw); return d

def test_august_includes_legacy_with_forced_warning():
    # 8/29 = 선불 마지막 유효일(폐구간). 8월이라 종료 예고 경고가 강제로 붙는다
    opts = compare_all(commuter(rides=90), ref=date(2026, 8, 29), **base_user())
    legacy = [o for o in opts if o.pass_id == "climate-card-legacy"]
    assert legacy and any("8/29" in w for w in legacy[0].warnings)

def test_aug30_excludes_prepaid_and_postpaid_by_default():
    opts = compare_all(commuter(), ref=date(2026, 8, 30), **base_user())
    assert not [o for o in opts if o.pass_id == "climate-card-legacy"]

def test_aug30_postpaid_flag_includes_it():
    opts = compare_all(commuter(), ref=date(2026, 8, 30), **base_user(has_postpaid_climate_card=True))
    legacy = [o for o in opts if o.pass_id == "climate-card-legacy"]
    assert legacy and "후불" in legacy[0].note

def test_september_shows_transition_only():
    opts = compare_all(commuter(), ref=date(2026, 9, 30), **base_user())
    assert not [o for o in opts if o.pass_id == "climate-card-legacy"]
    from passfit.engine import collect_notices
    notices = collect_notices(ref=date(2026, 9, 30), sido="서울")
    assert any("전환" in n for n in notices)

def test_plus_never_ranked_separately():
    opts = compare_all(commuter(), ref=date(2026, 7, 31), **base_user())
    assert not [o for o in opts if o.pass_id == "climate-card-plus"]
    modu = next(o for o in opts if o.pass_id == "modu-card")
    assert "기후동행카드 플러스" in modu.note

def test_legacy_excluded_mode_cost_added():
    p = commuter(rides=44, fare=2550, mode="shinbundang")
    opts = compare_all(p, ref=date(2026, 7, 31), **base_user())
    legacy = next(o for o in opts if o.pass_id == "climate-card-legacy")
    assert legacy.net_cost == 62000 + 2550 * 44

def test_dongbaek_for_busan_resident():
    opts = compare_all(commuter(rides=60, fare=1550), ref=date(2026, 7, 31), **base_user(residence="부산"))
    ids = {o.pass_id for o in opts}
    assert "dongbaek-pass" in ids and "climate-card-legacy" not in ids
