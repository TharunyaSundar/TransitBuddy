"""Structured, address-free result for the Discord commute-plan response."""
from typing import Literal

from pydantic import BaseModel, ConfigDict

CommuteResponseStatus = Literal["success", "clarification", "unsupported", "error"]


class CommutePlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: CommuteResponseStatus
    description: str
    course_name: str | None = None
    course_code: str | None = None
    class_start_time: str | None = None
    campus_building: str | None = None
    travel_date: str | None = None
    direction: Literal["to_campus", "from_campus"] | None = None
    campus_destination: str | None = None
    target_arrival_time: str | None = None
    estimated_duration_minutes: int | None = None
    recommended_departure_time: str | None = None
    transport_mode: str | None = None
    estimated: bool = False
