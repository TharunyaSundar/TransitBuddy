"""Deterministic schedule-context resolution for commute planning."""
import asyncio
import json
import unittest
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from agent_helpers import MONDAY_7AM, ScriptedModel
from src.agent import AgentService
from src.agent.commute_intent import TravelIntent
from src.agent.dev_database import DEMO_GUILD, demo_database
from src.agent.schedule_planner import arrival_buffer_minutes, plan_from_schedule
from src.agent.travel import TravelService


def intent(direction="to_campus", destination="first_class", kind="inferred_from_schedule", time_value=None):
    return TravelIntent.model_validate({
        "travel_date": "2026-10-26",
        "direction": direction,
        "time_constraint": {"type": kind, "time": time_value},
        "destination": destination,
        "needs_clarification": False,
        "clarification_question": None,
    })


def schedule(courses=None, status="confirmed"):
    return {
        "semester": "Fall 2026",
        "confirmation_status": status,
        "courses": courses if courses is not None else [
            {"course_code": "CSE 565", "course_name": "Software Verification", "location": "BYENG 210",
             "meeting_patterns": [{"day_of_week": "Monday", "start_time": "09:00", "end_time": "10:15"}]},
            {"course_code": "CSE 572", "course_name": "Data Mining", "location": "GWC 487",
             "meeting_patterns": [{"day_of_week": "Monday", "start_time": "13:30", "end_time": "14:45"}]},
        ],
    }


class SchedulePlanning(unittest.TestCase):
    def test_selects_first_class_and_applies_default_arrival_buffer(self):
        plan = plan_from_schedule(intent(), schedule(), "Get me to campus before my first class.",
                                  MONDAY_7AM)

        self.assertEqual(plan.relevant_course, "CSE 565")
        self.assertEqual(plan.class_start_time, "09:00")
        self.assertEqual(plan.destination_building, "BYENG 210")
        self.assertEqual(plan.time_constraint.type, "arrive_by")
        self.assertEqual(plan.time_constraint.time, "08:50")
        self.assertEqual(plan.arrival_buffer_minutes, 10)
        self.assertEqual(plan.origin_reference, "saved_home")
        self.assertFalse(plan.needs_clarification)

    def test_selects_last_class_for_trip_home(self):
        plan = plan_from_schedule(intent("from_campus", "last_class"), schedule(),
                                  "How do I get home after my last class today?", MONDAY_7AM)

        self.assertEqual(plan.relevant_course, "CSE 572")
        self.assertEqual(plan.class_end_time, "14:45")
        self.assertEqual(plan.time_constraint.type, "leave_after")
        self.assertEqual(plan.time_constraint.time, "14:45")
        self.assertEqual(plan.destination_reference, "saved_home")

    def test_explicit_times_are_preserved_and_named_course_is_selected(self):
        explicit_arrival = plan_from_schedule(
            intent(destination="CSE 565", kind="arrive_by", time_value="08:30"), schedule(),
            "Get to my CSE 565 class by 8:30 AM.", MONDAY_7AM,
        )
        self.assertEqual(explicit_arrival.relevant_course, "CSE 565")
        self.assertEqual(explicit_arrival.time_constraint.time, "08:30")

        explicit_departure = plan_from_schedule(
            intent("from_campus", "home", "leave_at", "16:00"), schedule(),
            "Leave campus at 4 PM.", MONDAY_7AM,
        )
        self.assertEqual(explicit_departure.time_constraint.type, "leave_at")
        self.assertEqual(explicit_departure.time_constraint.time, "16:00")

    def test_time_mentioned_for_a_class_selects_matching_class(self):
        plan = plan_from_schedule(
            intent(destination="class at 1:30 PM"), schedule(),
            "Can I make my 1:30 PM class if I leave at 12:45?", MONDAY_7AM,
        )
        self.assertEqual(plan.relevant_course, "CSE 572")
        self.assertEqual(plan.class_start_time, "13:30")

    def test_no_class_day_and_missing_schedule_require_time_for_inferred_request(self):
        no_classes = plan_from_schedule(intent(), schedule([]), "Get me to my first class.", MONDAY_7AM)
        self.assertTrue(no_classes.needs_clarification)
        self.assertIn("don't see a class", no_classes.clarification_question)

        missing = plan_from_schedule(intent(), None, "Get me to my first class.", MONDAY_7AM)
        self.assertTrue(missing.needs_clarification)
        self.assertIn("/schedule upload", missing.clarification_question)

    def test_explicitly_timed_trip_can_proceed_without_schedule(self):
        plan = plan_from_schedule(
            intent(destination="campus", kind="arrive_by", time_value="09:00"), None,
            "Get me to campus by 9 AM.", MONDAY_7AM,
        )
        self.assertFalse(plan.needs_clarification)
        self.assertIsNone(plan.relevant_course)
        self.assertEqual(plan.time_constraint.time, "09:00")

    def test_missing_building_is_optional_and_conflicting_departure_is_clarified(self):
        courses = schedule()["courses"]
        courses[0]["location"] = ""
        plan = plan_from_schedule(intent(), schedule(courses), "Get me to my first class.", MONDAY_7AM)
        self.assertEqual(plan.relevant_course, "CSE 565")
        self.assertIsNone(plan.destination_building)

        conflict = plan_from_schedule(
            intent("from_campus", "home", "leave_at", "10:00"), schedule(),
            "Leave campus at 10 AM.", MONDAY_7AM,
        )
        self.assertTrue(conflict.needs_clarification)
        self.assertTrue(conflict.schedule_conflict)
        self.assertIn("after that departure time", conflict.clarification_question)

    def test_started_classes_are_not_selected_as_the_next_class(self):
        now = datetime(2026, 10, 26, 9, 30, tzinfo=ZoneInfo("America/Phoenix"))
        missed_first = plan_from_schedule(intent(), schedule(), "Get me to my first class today.", now)
        self.assertTrue(missed_first.needs_clarification)
        self.assertIn("already started or ended", missed_first.clarification_question)

        next_class = plan_from_schedule(
            intent(destination="campus"), schedule(), "Get me to campus today.", now
        )
        self.assertEqual(next_class.relevant_course, "CSE 572")

        already_started = plan_from_schedule(
            intent(destination="CSE 565"), schedule(), "Get me to CSE 565 today.", now
        )
        self.assertTrue(already_started.needs_clarification)
        self.assertIn("already started or ended", already_started.clarification_question)

    def test_arrival_buffer_can_be_configured(self):
        with patch.dict("os.environ", {"COMMUTE_ARRIVAL_BUFFER_MINUTES": "15"}):
            self.assertEqual(arrival_buffer_minutes(), 15)
            plan = plan_from_schedule(intent(), schedule(), "Get me to my first class.", MONDAY_7AM,
                                      arrival_buffer_minutes())
        self.assertEqual(plan.time_constraint.time, "08:45")

    def test_unconfirmed_schedule_is_not_used(self):
        plan = plan_from_schedule(intent(), schedule(status="pending"),
                                  "Get me to my first class.", MONDAY_7AM)
        self.assertTrue(plan.needs_clarification)
        self.assertIn("confirmed schedule", plan.clarification_question)

    def test_agent_uses_authenticated_user_and_guild_schedule(self):
        class TrackingDatabase:
            def __init__(self, inner):
                self.inner = inner
                self.schedule_lookup = None

            async def get_student(self, guild_id, user_id):
                return await self.inner.get_student(guild_id, user_id)

            async def get_student_schedule(self, guild_id, user_id):
                self.schedule_lookup = (guild_id, user_id)
                return await self.inner.get_student_schedule(guild_id, user_id)

        db = TrackingDatabase(demo_database())
        extraction = {
            "travel_date": "2026-10-26",
            "direction": "to_campus",
            "time_constraint": {"type": "inferred_from_schedule", "time": None},
            "destination": "first_class",
            "needs_clarification": False,
            "clarification_question": None,
        }
        model = ScriptedModel(script=[json.dumps(extraction)], seen=[])
        agent = AgentService(db, model=model, clock=lambda: MONDAY_7AM)

        response = asyncio.run(agent.commute_plan_request("1002", DEMO_GUILD, "Get me to campus before class."))

        self.assertEqual(db.schedule_lookup, (DEMO_GUILD, "1002"))
        self.assertEqual(response.course_code, "EEE 120")
        self.assertNotEqual(response.course_code, "CSE 110")
        self.assertEqual(response.target_arrival_time, "8:55 AM")
        self.assertNotIn("1 E Main St", response.model_dump_json())

        wrong_guild_model = ScriptedModel(script=[json.dumps(extraction)], seen=[])
        wrong_guild_agent = AgentService(db, model=wrong_guild_model, clock=lambda: MONDAY_7AM)
        wrong_guild_response = asyncio.run(
            wrong_guild_agent.commute_plan_request("1002", "other-guild", "Get me to class.")
        )
        self.assertIn("don't have a saved home address", wrong_guild_response.description)
        self.assertEqual(db.schedule_lookup, (DEMO_GUILD, "1002"))

    def test_agent_uses_travel_service_and_estimates_departure_for_arrival_deadline(self):
        calls = []

        async def mocked_planner(body):
            calls.append(body)
            return 200, {"ok": True, "journeys": [
                {"mode": "TRANSIT", "total_min": 25},
                {"mode": "TRANSIT", "total_min": 34},
            ]}

        extraction = {
            "travel_date": "2026-10-26",
            "direction": "to_campus",
            "time_constraint": {"type": "inferred_from_schedule", "time": None},
            "destination": "first_class",
            "needs_clarification": False,
            "clarification_question": None,
        }
        db = demo_database()
        model = ScriptedModel(script=[json.dumps(extraction)], seen=[])
        agent = AgentService(
            db, model=model, clock=lambda: MONDAY_7AM,
            travel=TravelService(caller=mocked_planner),
        )

        response = asyncio.run(
            agent.commute_plan_request("1001", DEMO_GUILD, "Get me to campus before my first class.")
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["modes"], ["TRANSIT"])
        self.assertEqual(calls[0]["arrive_by"], "2026-10-26T08:50:00-07:00")
        self.assertEqual(calls[0]["destination"]["label"], "Interdisciplinary Science and Technology IV (ISTB4)")
        self.assertEqual(response.status, "success")
        self.assertEqual(response.estimated_duration_minutes, 25)
        self.assertEqual(response.target_arrival_time, "8:50 AM")
        self.assertEqual(response.recommended_departure_time, "8:25 AM")
        self.assertEqual(response.transport_mode, "bus or train")
        self.assertEqual(response.direction, "to_campus")
        self.assertEqual(response.campus_destination, "Tempe")
        self.assertNotIn(db.students[(DEMO_GUILD, "1001")].home_address, response.model_dump_json())
        self.assertNotIn(db.students[(DEMO_GUILD, "1001")].home_address, model.seen[0][1].content)

    def test_departure_time_request_is_not_sent_as_an_arrival_request(self):
        calls = []

        async def mocked_planner(body):
            calls.append(body)
            return 200, {"ok": True, "journeys": [{"mode": "TRANSIT", "total_min": 25}]}

        extraction = {
            "travel_date": "2026-10-26",
            "direction": "to_campus",
            "time_constraint": {"type": "leave_at", "time": "08:00"},
            "destination": "campus",
            "needs_clarification": False,
            "clarification_question": None,
        }
        agent = AgentService(
            demo_database(), model=ScriptedModel(script=[json.dumps(extraction)], seen=[]),
            clock=lambda: MONDAY_7AM, travel=TravelService(caller=mocked_planner),
        )

        response = asyncio.run(agent.commute_plan_request("1001", DEMO_GUILD, "Leave for campus at 8 AM."))

        self.assertEqual(calls, [])
        self.assertEqual(response.status, "unsupported")
        self.assertIn("requires an arrival deadline", response.description)
        self.assertIsNone(response.recommended_departure_time)

    def test_return_trip_is_not_misrepresented_as_home_to_campus_route(self):
        calls = []

        async def mocked_planner(body):
            calls.append(body)
            return 200, {"ok": True, "journeys": [{"mode": "TRANSIT", "total_min": 25}]}

        extraction = {
            "travel_date": "2026-10-26",
            "direction": "from_campus",
            "time_constraint": {"type": "inferred_from_schedule", "time": None},
            "destination": "last_class",
            "needs_clarification": False,
            "clarification_question": None,
        }
        agent = AgentService(
            demo_database(), model=ScriptedModel(script=[json.dumps(extraction)], seen=[]),
            clock=lambda: MONDAY_7AM, travel=TravelService(caller=mocked_planner),
        )

        response = asyncio.run(agent.commute_plan_request("1001", DEMO_GUILD, "Go home after my last class."))

        self.assertEqual(calls, [])
        self.assertEqual(response.status, "unsupported")
        self.assertIn("only estimates trips from your saved home to campus", response.description)
        self.assertIsNone(response.recommended_departure_time)

    def test_unavailable_estimate_does_not_fabricate_departure_time(self):
        async def mocked_planner(body):
            return 503, {"ok": False, "error": {"code": "UNAVAILABLE"}}

        extraction = {
            "travel_date": "2026-10-26",
            "direction": "to_campus",
            "time_constraint": {"type": "inferred_from_schedule", "time": None},
            "destination": "first_class",
            "needs_clarification": False,
            "clarification_question": None,
        }
        agent = AgentService(
            demo_database(), model=ScriptedModel(script=[json.dumps(extraction)], seen=[]),
            clock=lambda: MONDAY_7AM, travel=TravelService(caller=mocked_planner),
        )

        response = asyncio.run(
            agent.commute_plan_request("1001", DEMO_GUILD, "Get me to campus before my first class.")
        )

        self.assertEqual(response.status, "error")
        self.assertIn("couldn't get a usable travel-time estimate", response.description)
        self.assertIsNone(response.recommended_departure_time)

    def test_estimate_that_requires_a_past_departure_warns_that_deadline_cannot_be_met(self):
        async def mocked_planner(body):
            return 200, {"ok": True, "journeys": [{"mode": "TRANSIT", "total_min": 60}]}

        extraction = {
            "travel_date": "2026-10-26",
            "direction": "to_campus",
            "time_constraint": {"type": "arrive_by", "time": "07:30"},
            "destination": "campus",
            "needs_clarification": False,
            "clarification_question": None,
        }
        agent = AgentService(
            demo_database(), model=ScriptedModel(script=[json.dumps(extraction)], seen=[]),
            clock=lambda: MONDAY_7AM, travel=TravelService(caller=mocked_planner),
        )

        response = asyncio.run(agent.commute_plan_request("1001", DEMO_GUILD, "Get to campus by 7:30 AM."))

        self.assertIn("estimated departure time has already passed", response.description)
        self.assertEqual(response.recommended_departure_time, "6:30 AM")

    def test_resolves_schedule_on_local_calendar_weekday(self):
        utc_clock = datetime(2026, 10, 26, 0, 30, tzinfo=ZoneInfo("UTC"))
        tuesday = date(2026, 10, 27)
        local_now = utc_clock.astimezone(ZoneInfo("America/Phoenix"))
        self.assertEqual(local_now.date(), date(2026, 10, 25))
        tue_schedule = schedule([{
            "course_code": "MAT 265", "course_name": "Calculus", "location": "COOR 170",
            "meeting_patterns": [{"day_of_week": "Tuesday", "start_time": "10:30", "end_time": "11:45"}],
        }])
        tue_intent = TravelIntent.model_validate({
            **intent().model_dump(),
            "travel_date": tuesday,
        })
        plan = plan_from_schedule(tue_intent, tue_schedule, "Get me to my first class tomorrow.",
                                  local_now)
        self.assertEqual(plan.travel_date, tuesday)
        self.assertEqual(plan.relevant_course, "MAT 265")
        self.assertEqual(plan.time_constraint.time, "10:20")


if __name__ == "__main__":
    unittest.main()
