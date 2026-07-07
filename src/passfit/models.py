from datetime import date as _date
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator
from passfit.engine import Pattern, Segment

Mode = Literal["subway", "city_bus", "village_bus", "metropolitan_bus",
               "gtx", "shinbundang", "other"]

# LLM이 자연어로 넘길 가능성이 있는 한국어 alias → 서버 enum 매핑.
# check_pass_eligibility·compare 등 여러 tool에서 공용 사용.
INCOME_LEVEL_ALIASES = {
    "저소득": "low_income", "저소득자": "low_income", "저소득층": "low_income",
    "기초생활수급자": "low_income", "차상위": "low_income",
    "일반": "general", "일반인": "general",
}

class RideSegment(BaseModel):
    mode: Mode = "subway"
    fare_per_ride: int = Field(gt=0)
    monthly_rides: int = Field(gt=0)
    offpeak_rides: int = Field(0, ge=0)

MISSING_PATTERN_MSG = ("월 교통비 총액 또는 월 탑승 횟수와 1회 요금을 알려주시면 "
                       "계산할 수 있어요. 주 5일 왕복이면 월 약 44회입니다.")

class CommuteInput(BaseModel):
    monthly_rides: int | None = Field(None, gt=0)
    fare_per_ride: int | None = Field(None, gt=0)
    monthly_spend: int | None = Field(None, gt=0)
    rides: list[RideSegment] | None = None
    offpeak_rides: int = Field(0, ge=0)
    age: int = Field(ge=6, le=120)
    # residence는 미상이면 "" → "전국" 취급 (resolve_region이 unknown fallback 처리).
    # LLM이 거주지 없이 호출하는 흔한 UX 케이스 회복.
    residence: str = ""
    income_level: Literal["general", "low_income"] = "general"
    children_count: int = Field(0, ge=0, le=10)
    is_first_month: bool = False
    free_ride_status: Literal["none", "eligible", "uses_free_ride_card"] = "none"
    has_postpaid_climate_card: bool = False
    usage_month: str | None = Field(None, pattern=r"^\d{4}-\d{2}$")
    as_of_date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    detail: Literal["concise", "detailed"] = "concise"

    @field_validator("income_level", mode="before")
    @classmethod
    def _income_level_alias(cls, v):
        # LLM이 한글 '저소득' 등을 그대로 넘기면 enum 값으로 변환.
        if isinstance(v, str) and v in INCOME_LEVEL_ALIASES:
            return INCOME_LEVEL_ALIASES[v]
        return v

    @field_validator("as_of_date")
    @classmethod
    def _valid_as_of_date(cls, v):
        if v is not None:
            try:
                _date.fromisoformat(v)
            except ValueError:
                raise ValueError(f"as_of_date '{v}'는 실제 날짜가 아닙니다 (YYYY-MM-DD)")
        return v

    @field_validator("usage_month")
    @classmethod
    def _valid_usage_month(cls, v):
        if v is not None:
            try:
                y, m = v.split("-")
                _date(int(y), int(m), 1)
            except ValueError:
                raise ValueError(f"usage_month '{v}'는 실제 연월이 아닙니다 (YYYY-MM)")
        return v

    @model_validator(mode="after")
    def _require_pattern(self):
        if self.rides or self.monthly_spend is not None \
           or (self.monthly_rides is not None and self.fare_per_ride is not None):
            return self
        raise ValueError(MISSING_PATTERN_MSG)

def to_pattern(inp: CommuteInput) -> Pattern:
    if inp.rides:
        return Pattern(tuple(Segment(r.mode, r.fare_per_ride, r.monthly_rides,
                                     r.offpeak_rides) for r in inp.rides))
    if inp.monthly_spend is not None:
        return Pattern((), spend_only=True, spend_hint=inp.monthly_spend)
    return Pattern((Segment("subway", inp.fare_per_ride, inp.monthly_rides,
                            inp.offpeak_rides),))
