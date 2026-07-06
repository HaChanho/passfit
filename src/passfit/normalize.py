from dataclasses import dataclass

from passfit.data_loader import load_regions


@dataclass(frozen=True)
class RegionInfo:
    raw: str
    sido: str | None          # None = 미해석
    region_class: str         # 수도권/일반지방권/우대지원지역/특별지원지역
    confidence: str           # exact | alias | unknown


def resolve_region(text: str) -> RegionInfo:
    regions = load_regions()
    t = text.replace(" ", "")
    # 1) special zone 우선 (가평군이 '경기' alias보다 구체적)
    for z in regions["special_zones"]:
        if z["name"].rstrip("군시") in t:
            return RegionInfo(text, z["sido"], z["class"], "exact")
    # 2) 시도명 직접 포함
    for sido, cls in regions["sido_class"].items():
        if sido in t:
            return RegionInfo(text, sido, cls, "exact")
    # 3) alias 부분일치 (긴 alias 우선 — '강화'가 '경기'보다 먼저 걸리게 정렬)
    for alias, sido in sorted(regions["aliases"].items(), key=lambda kv: -len(kv[0])):
        if alias in t:
            cls = regions["sido_class"].get(sido, regions["region_class_default"])
            return RegionInfo(text, sido, cls, "alias")
    return RegionInfo(text, None, regions["region_class_default"], "unknown")
