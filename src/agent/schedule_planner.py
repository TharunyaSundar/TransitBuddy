"""Deterministic schedule-aware context resolution for commute requests."""
import os
import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .commute_intent import TimeConstraint, TravelIntent
from .logic.schedule import is_online
from .logic.timeutil import display, normalize_time, to_minutes

_COURSE_TIME = re.compile(
    r"\b(?:(?:class|course)\s+(?:at\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm))|"
    r"(\d{1,2}(?::\d{2})?\s*(?:am|pm))\s+(?:class|course))\b",
    re.IGNORECASE,
)
_ARRIVAL_BUFFER_ENV = "COMMUTE_ARRIVAL_BUFFER_MINUTES"
DEFAULT_ARRIVAL_BUFFER_MINUTES = 10


def arrival_buffer_minutes() -> int:
    """Get a non-negative, bounded class-arrival buffer from the environment."""
    raw = os.environ.get(_ARRIVAL_BUFFER_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_ARRIVAL_BUFFER_MINUTES
    try:
        minutes = int(raw)
    except ValueError as error:
        raise ValueError(f"{_ARRIVAL_BUFFER_ENV} must be an integer") from error
    if not 0 <= minutes <= 180:
        raise ValueError(f"{_ARRIVAL_BUFFER_ENV} must be between 0 and 180")
    return minutes


class ScheduleAwarePlan(BaseModel):
    """Validated schedule context for a later routing stage; contains references, never addresses."""

    model_config = ConfigDict(extra="forbid")

    travel_date: date | None
    direction: Literal["to_campus", "from_campus"] | None
    relevant_course: str | None = None
    relevant_course_name: str | None = None
    class_start_time: str | None = None
    class_end_time: str | None = None
    destination_building: str | None = None
    campus_name: str | None = None
    origin_reference: str | None = None
    destination_reference: str | None = None
    time_constraint: TimeConstraint | None = None
    arrival_buffer_minutes: int = Field(ge=0, le=180)
    needs_clarification: bool
    clarification_question: str | None = None
    schedule_conflict: bool = False

    @field_validator("class_start_time", "class_end_time")
    @classmethod
    def validate_clock_time(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = normalize_time(value)
        if normalized is None:
            raise ValueError("class time must be a valid clock time")
        return normalized

    @model_validator(mode="after")
    def validate_class_fields(self):
        if self.relevant_course is None and any(
            (self.class_start_time, self.class_end_time, self.destination_building)
        ):
            raise ValueError("class details require a relevant course")
        if self.needs_clarification and not (self.clarification_question or "").strip():
            raise ValueError("clarification question is required")
        if not self.needs_clarification and self.clarification_question is not None:
            raise ValueError("clarification question must be empty for a resolved plan")
        return self


def _schedule_classes(schedule: dict, travel_date: date) -> list[dict]:
    weekday = travel_date.strftime("%A")
    classes = []
    for course in schedule.get("courses") or []:
        location = str(course.get("location") or "").strip()
        if is_online(location):
            continue
        for meeting in course.get("meeting_patterns") or []:
            if meeting.get("day_of_week") != weekday:
                continue
            start, end = normalize_time(meeting.get("start_time", "")), normalize_time(meeting.get("end_time", ""))
            if start is None or end is None or to_minutes(end) <= to_minutes(start):
                continue
            classes.append({
                "course": course,
                "course_label": course.get("course_code") or course.get("course_name") or "Class",
                "start": start,
                "end": end,
                "location": location or None,
            })
    return sorted(classes, key=lambda c: (c["start"], c["end"], c["course_label"]))


def _course_mentions(request: str, classes: list[dict]) -> list[dict]:
    normalized = re.sub(r"\s+", " ", request).casefold()
    matches = []
    for item in classes:
        course = item["course"]
        values = [course.get("course_code"), course.get("course_name")]
        if any(value and str(value).casefold() in normalized for value in values):
            matches.append(item)
    return matches


def _course_at_mentioned_time(request: str, classes: list[dict]) -> list[dict]:
    found = _COURSE_TIME.search(request)
    if not found:
        return []
    stated = normalize_time(found.group(1) or found.group(2))
    if stated is None:
        return []
    return [item for item in classes if item["start"] == stated]


def _clarification(intent: TravelIntent, buffer: int, question: str, *,
                   relevant_course: dict | None = None, conflict: bool = False) -> ScheduleAwarePlan:
    return ScheduleAwarePlan(
        travel_date=intent.travel_date,
        direction=intent.direction,
        relevant_course=relevant_course["course_label"] if relevant_course else None,
        relevant_course_name=(relevant_course["course"].get("course_name") if relevant_course else None),
        class_start_time=relevant_course["start"] if relevant_course else None,
        class_end_time=relevant_course["end"] if relevant_course else None,
        destination_building=relevant_course["location"] if relevant_course else None,
        origin_reference="saved_home" if intent.direction == "to_campus" else "campus",
        destination_reference=(
            ("class_building" if relevant_course and relevant_course["location"] else "campus")
            if intent.direction == "to_campus" else "saved_home"
        ),
        time_constraint=intent.time_constraint,
        arrival_buffer_minutes=buffer,
        needs_clarification=True,
        clarification_question=question,
        schedule_conflict=conflict,
    )


def plan_from_schedule(intent: TravelIntent, schedule: dict | None, request: str, local_now: datetime,
                       arrival_buffer: int = DEFAULT_ARRIVAL_BUFFER_MINUTES,
                       campus_name: str | None = None) -> ScheduleAwarePlan:
    """Resolve relevant class and explicit/inferred time constraints without using the LLM."""
    if intent.needs_clarification:
        return _clarification(intent, arrival_buffer,
                              intent.clarification_question or "What date and time should I plan for?")
    if intent.travel_date is None or intent.direction is None or intent.time_constraint is None:
        return _clarification(intent, arrival_buffer, "What date, direction, and time should I plan for?")
    if schedule and schedule.get("confirmation_status") != "confirmed":
        schedule = None

    classes = _schedule_classes(schedule or {}, intent.travel_date)
    named_courses = _course_mentions(request, classes)
    classes_at_time = _course_at_mentioned_time(request, classes)
    destination = (intent.destination or "").strip()
    destination_lower = destination.casefold()
    if named_courses:
        candidates = named_courses
    elif classes_at_time:
        candidates = classes_at_time
    elif destination_lower in ("first_class", "last_class") or intent.time_constraint.type == "inferred_from_schedule":
        candidates = classes
    elif destination and destination_lower not in ("campus", "home"):
        matches = [item for item in classes
                   if destination_lower in item["course_label"].casefold()
                   or destination_lower in str(item["course"].get("course_name") or "").casefold()]
        candidates = matches
    else:
        candidates = []

    relevant = None
    if len(candidates) > 1 and (named_courses or classes_at_time or destination_lower not in ("", "first_class",
                                                                                             "last_class",
                                                                                             "campus", "home")):
        return _clarification(intent, arrival_buffer,
                              "Which class do you mean? I found more than one matching class.",
                              conflict=True)
    if candidates:
        if destination_lower == "last_class" or (
            intent.direction == "from_campus"
            and intent.time_constraint.type == "inferred_from_schedule"
            and not named_courses and not classes_at_time
        ):
            relevant = max(candidates, key=lambda item: (item["end"], item["start"]))
        elif named_courses or classes_at_time or destination_lower == "first_class":
            relevant = candidates[0]
            if (intent.travel_date == local_now.date()
                    and to_minutes(relevant["start"]) <= local_now.hour * 60 + local_now.minute):
                return _clarification(
                    intent, arrival_buffer,
                    f"{relevant['course_label']} has already started or ended today. Which class or time should I plan for?",
                    relevant_course=relevant,
                )
        elif intent.travel_date == local_now.date():
            current_minutes = local_now.hour * 60 + local_now.minute
            upcoming = [item for item in candidates if to_minutes(item["start"]) > current_minutes]
            if upcoming:
                relevant = upcoming[0]
            elif intent.time_constraint.type == "inferred_from_schedule":
                return _clarification(intent, arrival_buffer,
                                      "Your classes today have already started or ended. Which time should I plan for?")
        else:
            relevant = candidates[0]

    if intent.time_constraint.type == "inferred_from_schedule" and relevant is None:
        if schedule is None:
            question = "I can't find a confirmed schedule. Upload one with /schedule upload, or tell me the exact time."
        else:
            question = f"I don't see a class on {intent.travel_date.strftime('%A')} to plan around. What time should I use?"
        return _clarification(intent, arrival_buffer, question)

    if intent.direction == "from_campus" and classes and intent.time_constraint.type in ("leave_at", "leave_after"):
        departure = to_minutes(intent.time_constraint.time or "00:00")
        later = [item for item in classes if to_minutes(item["end"]) > departure]
        if later:
            class_name = later[0]["course_label"]
            return _clarification(
                intent, arrival_buffer,
                f"Your schedule shows {class_name} after that departure time. Do you still need to leave then?",
                relevant_course=later[0], conflict=True,
            )

    if intent.direction == "from_campus" and relevant is not None:
        requested = intent.time_constraint
        if requested.type == "leave_at" and requested.time and to_minutes(requested.time) < to_minutes(relevant["end"]):
            return _clarification(
                intent, arrival_buffer,
                f"Your {relevant['course_label']} ends at {display(relevant['end'])}, after your requested departure. Should I plan for after class?",
                relevant_course=relevant, conflict=True,
            )

    constraint = intent.time_constraint
    if constraint.type == "inferred_from_schedule" and relevant is not None:
        if intent.direction == "to_campus":
            deadline = max(0, to_minutes(relevant["start"]) - arrival_buffer)
            constraint = TimeConstraint(type="arrive_by", time=f"{deadline // 60:02d}:{deadline % 60:02d}")
        else:
            leave_after = relevant["end"]
            if intent.travel_date == local_now.date():
                current_minutes = local_now.hour * 60 + local_now.minute
                leave_after = f"{max(to_minutes(leave_after), current_minutes) // 60:02d}:{max(to_minutes(leave_after), current_minutes) % 60:02d}"
            constraint = TimeConstraint(type="leave_after", time=leave_after)

    origin = "saved_home" if intent.direction == "to_campus" else "campus"
    destination_ref = (
        ("class_building" if relevant and relevant["location"] else "campus")
        if intent.direction == "to_campus" else "saved_home"
    )
    if intent.destination and intent.destination.casefold() not in ("first_class", "last_class", "campus", "home"):
        destination_ref = "class_building" if relevant and relevant["location"] else "explicit_destination"
    return ScheduleAwarePlan(
        travel_date=intent.travel_date,
        direction=intent.direction,
        relevant_course=relevant["course_label"] if relevant else None,
        relevant_course_name=(relevant["course"].get("course_name") if relevant else None),
        class_start_time=relevant["start"] if relevant else None,
        class_end_time=relevant["end"] if relevant else None,
        destination_building=relevant["location"] if relevant else None,
        campus_name=campus_name,
        origin_reference=origin,
        destination_reference=destination_ref,
        time_constraint=constraint,
        arrival_buffer_minutes=arrival_buffer,
        needs_clarification=False,
        clarification_question=None,
    )
