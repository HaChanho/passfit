from typing import Literal
from pydantic import BaseModel, Field, model_validator
from passfit.engine import Pattern, Segment

Mode = Literal["subway", "city_bus", "village_bus", "metropolitan_bus",
               "gtx", "shinbundang", "other"]

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
    residence: str
    income_level: Literal["general", "low_income"] = "general"
    children_count: int = Field(0, ge=0)
    is_first_month: bool = False
    free_ride_status: Literal["none", "eligible", "uses_free_ride_card"] = "none"
    has_postpaid_climate_card: bool = False
    usage_month: str | None = Field(None, pattern=r"^\d{4}-\d{2}$")
    as_of_date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    detail: Literal["concise", "detailed"] = "concise"

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
