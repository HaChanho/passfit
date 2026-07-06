import re
from dataclasses import dataclass

from passfit.data_loader import load_regions


@dataclass(frozen=True)
class RegionInfo:
    raw: str
    sido: str | None          # None = 미해석
    region_class: str         # 수도권/일반지방권/우대지원지역 (특별지원지역은 현재 지역 데이터엔 없음, 계산용 값)
    confidence: str           # exact | alias | unknown


def resolve_region(text: str) -> RegionInfo:
    regions = load_regions()
    t = text.replace(" ", "")
    # 1) special zone 우선 (가평군이 '경기' alias보다 구체적)
    for z in regions["special_zones"]:
        base = re.sub(r"[군시구]$", "", z["name"])
        if base in t:
            return RegionInfo(text, z["sido"], z["class"], "exact")
    # 2) 시도명(exact) + alias(alias)를 함께: t에서 가장 앞, 동률이면 더 긴 매칭 우선
    #    (예: "해운대구"는 alias '해운대'(부산, index 0)가 sido '대구'(index 2)보다 앞서 이김)
    candidates = []  # (index, -len, sido, region_class, confidence)
    for sido, cls in regions["sido_class"].items():
        i = t.find(sido)
        if i != -1:
            candidates.append((i, -len(sido), sido, cls, "exact"))
    for alias, sido in regions["aliases"].items():
        i = t.find(alias)
        if i != -1:
            cls = regions["sido_class"].get(sido, regions["region_class_default"])
            candidates.append((i, -len(alias), sido, cls, "alias"))
    if candidates:
        candidates.sort(key=lambda c: (c[0], c[1]))   # index 오름차순, 그 다음 -len 오름차순(긴 매칭 우선)
        _, _, sido, cls, conf = candidates[0]
        return RegionInfo(text, sido, cls, conf)
    return RegionInfo(text, None, regions["region_class_default"], "unknown")
