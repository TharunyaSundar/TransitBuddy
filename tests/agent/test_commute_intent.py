"""Natural-language commute intent extraction and safe failure handling."""
import asyncio
import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from agent_helpers import MONDAY_7AM, ScriptedModel
from src.agent import AgentService
from src.agent.commute_intent import IntentExtractionError, extract_travel_intent
from src.agent.dev_database import DEMO_GUILD, demo_database

PHOENIX = ZoneInfo("America/Phoenix")


def run(coro):
    return asyncio.run(coro)


def model_for(intent):
    return ScriptedModel(script=[json.dumps(intent)], seen=[])


def intent(date_value="2026-10-26", direction="to_campus", constraint_type="inferred_from_schedule",
           time_value=None, destination="first_class", needs_clarification=False, question=None):
    return {
        "travel_date": date_value,
        "direction": direction,
        "time_constraint": {"type": constraint_type, "time": time_value},
        "destination": destination,
        "needs_clarification": needs_clarification,
        "clarification_question": question,
    }


class IntentExtraction(unittest.TestCase):
    def test_extracts_direction_arrival_time_destination_and_next_weekday(self):
        model = model_for(intent(date_value="2026-11-02", constraint_type="arrive_by", time_value="9:00 AM",
                                 destination="campus"))
        result = run(extract_travel_intent(model, "Get me to campus by 9 AM next Monday.",
                                           MONDAY_7AM, "America/Phoenix"))

        self.assertEqual(result.travel_date.isoformat(), "2026-11-02")
        self.assertEqual(result.direction, "to_campus")
        self.assertEqual(result.time_constraint.type, "arrive_by")
        self.assertEqual(result.time_constraint.time, "09:00")
        self.assertEqual(result.destination, "campus")

    def test_converts_now_using_student_timezone(self):
        utc_now = datetime(2026, 10, 26, 0, 30, tzinfo=ZoneInfo("UTC"))
        model = model_for(intent(date_value="2026-10-25", constraint_type="inferred_from_schedule",
                                 time_value=None, destination="home", direction="from_campus"))
        result = run(extract_travel_intent(model, "How do I get home today?", utc_now, "America/Phoenix"))

        self.assertEqual(result.travel_date.isoformat(), "2026-10-25")
        self.assertEqual(model.seen[0][1].content.split("Local current date and time: ", 1)[1].splitlines()[0],
                         "2026-10-25T17:30:00-07:00 (Sunday).")

    def test_resolves_weekday_and_leave_after_constraint(self):
        model = model_for(intent(date_value="2026-10-26", constraint_type="leave_after", time_value="15:30",
                                 destination="home", direction="from_campus"))
        result = run(extract_travel_intent(model, "I want to leave after 3:30 PM on Monday.",
                                           MONDAY_7AM, "America/Phoenix"))

        self.assertEqual(result.travel_date.isoformat(), "2026-10-26")
        self.assertEqual(result.time_constraint.type, "leave_after")
        self.assertEqual(result.time_constraint.time, "15:30")
        self.assertEqual(result.direction, "from_campus")

    def test_resolves_now_to_local_leave_time(self):
        model = model_for(intent(date_value="2026-10-26", constraint_type="inferred_from_schedule",
                                 time_value=None, destination="home", direction="from_campus"))
        result = run(extract_travel_intent(model, "I need to go home now.", MONDAY_7AM, "America/Phoenix"))

        self.assertEqual(result.time_constraint.type, "leave_at")
        self.assertEqual(result.time_constraint.time, "07:00")

    def test_returns_model_clarification_as_validated_intent(self):
        clarification = {
            "travel_date": None,
            "direction": None,
            "time_constraint": None,
            "destination": None,
            "needs_clarification": True,
            "clarification_question": "Are you traveling to campus or home?",
        }
        result = run(extract_travel_intent(model_for(clarification), "Plan my trip.",
                                           MONDAY_7AM, "America/Phoenix"))

        self.assertTrue(result.needs_clarification)
        self.assertEqual(result.clarification_question, "Are you traveling to campus or home?")

    def test_allows_clarification_for_ambiguous_relative_dates(self):
        clarification = {
            "travel_date": None,
            "direction": "to_campus",
            "time_constraint": {"type": "arrive_by", "time": "09:00"},
            "destination": "campus",
            "needs_clarification": True,
            "clarification_question": "Do you mean today or tomorrow?",
        }
        result = run(extract_travel_intent(model_for(clarification), "Get me there today or tomorrow.",
                                           MONDAY_7AM, "America/Phoenix"))

        self.assertTrue(result.needs_clarification)
        self.assertEqual(result.clarification_question, "Do you mean today or tomorrow?")

    def test_rejects_invalid_time_or_relative_date_from_model(self):
        invalid_time = intent(constraint_type="arrive_by", time_value="25:99")
        with self.assertRaises(IntentExtractionError):
            run(extract_travel_intent(model_for(invalid_time), "Get me to campus tomorrow.",
                                      MONDAY_7AM, "America/Phoenix"))

        wrong_date = intent(date_value="2026-10-28")
        with self.assertRaisesRegex(IntentExtractionError, "relative date"):
            run(extract_travel_intent(model_for(wrong_date), "Get me to campus tomorrow.",
                                      MONDAY_7AM, "America/Phoenix"))

    def test_rejects_invalid_json(self):
        with self.assertRaises(IntentExtractionError):
            run(extract_travel_intent(ScriptedModel(script=["not JSON"], seen=[]),
                                      "Get me to campus tomorrow.", MONDAY_7AM, "America/Phoenix"))

    def test_rejects_address_in_model_destination_and_redacts_user_address(self):
        raw = intent(destination="1 E Main St, Mesa, AZ 85201")
        model = model_for(raw)
        with self.assertRaises(IntentExtractionError):
            run(extract_travel_intent(model, "From 1 E Main St, Mesa, AZ 85201 to campus tomorrow.",
                                      MONDAY_7AM, "America/Phoenix"))
        prompt = model.seen[0][1].content
        self.assertNotIn("1 E Main St", prompt)
        self.assertIn("[private address]", prompt)


class CommutePlanRequest(unittest.TestCase):
    def test_uses_saved_timezone_and_does_not_send_saved_address_to_model(self):
        db = demo_database()
        student = run(db.get_student(DEMO_GUILD, "1001"))
        run(db.upsert_student(student.model_copy(update={"timezone": "UTC", "home_address": "HOME_SECRET_1001"})))
        model = model_for(intent(date_value="2026-10-27", constraint_type="arrive_by", time_value="09:00",
                                 destination="campus"))
        clock = lambda: datetime(2026, 10, 26, 0, 30, tzinfo=ZoneInfo("UTC"))
        agent = AgentService(db, model=model, clock=clock)

        response = run(agent.commute_plan_request(
            "1001", DEMO_GUILD, "Get me to campus tomorrow by 9 AM from HOME_SECRET_1001."
        ))

        self.assertIn("Tuesday, October 27", response.description)
        self.assertIn("arriving by 9:00 AM", response.description)
        prompt = model.seen[0][1].content
        self.assertIn("timezone UTC", prompt)
        self.assertNotIn("HOME_SECRET_1001", prompt)
        self.assertIn("[private address]", prompt)

    def test_defaults_to_phoenix_timezone_without_a_student_profile(self):
        model = model_for(intent(date_value="2026-10-25", destination="campus"))
        clock = lambda: datetime(2026, 10, 26, 0, 30, tzinfo=ZoneInfo("UTC"))
        agent = AgentService(demo_database(), model=model, clock=clock)

        run(agent.commute_plan_request("unknown-user", DEMO_GUILD, "Get me to campus today."))

        prompt = model.seen[0][1].content
        self.assertIn("timezone America/Phoenix", prompt)
        self.assertIn("Local current date and time: 2026-10-25T17:30:00-07:00", prompt)

    def test_returns_clarification_without_claiming_to_plan(self):
        clarification = {
            "travel_date": None,
            "direction": None,
            "time_constraint": None,
            "destination": None,
            "needs_clarification": True,
            "clarification_question": "Are you going to campus or home?",
        }
        agent = AgentService(demo_database(), model=model_for(clarification), clock=lambda: MONDAY_7AM)

        response = run(agent.commute_plan_request("1001", DEMO_GUILD, "Plan my trip."))

        self.assertEqual(response.status, "clarification")
        self.assertEqual(response.description, "Are you going to campus or home?")

    def test_past_time_and_invalid_model_output_are_handled_gracefully(self):
        past = intent(constraint_type="arrive_by", time_value="06:00", destination="campus")
        agent = AgentService(demo_database(), model=model_for(past), clock=lambda: MONDAY_7AM)
        response = run(agent.commute_plan_request("1001", DEMO_GUILD, "Get to campus by 6 AM today."))
        self.assertIn("time has already passed today", response.description)

        broken = AgentService(demo_database(), model=ScriptedModel(script=["not JSON"], seen=[]),
                              clock=lambda: MONDAY_7AM)
        response = run(broken.commute_plan_request("1001", DEMO_GUILD, "Get me to campus tomorrow."))
        self.assertIn("couldn't confidently understand", response.description)


if __name__ == "__main__":
    unittest.main()
