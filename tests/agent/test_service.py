import asyncio
import json
import unittest

import helpers  # noqa: F401  (sets the path)
from agent import AgentService
from agent.dev_database import DEMO_GUILD, demo_database
from agent.extraction.schedule_extraction import extract_schedule, parse_json
from agent.skill_loader import load_skills, select_skills

from helpers import MONDAY_7AM, ScriptedModel, tool_results


def run(coro):
    return asyncio.run(coro)


def service(script, db=None, vision=None):
    model = ScriptedModel(script=script, seen=[])
    return AgentService(db if db is not None else demo_database(), model=model, vision_model=vision,
                        clock=lambda: MONDAY_7AM), model


def ctx(message, user="1001", mentioned=None):
    return {"message": message, "discordUserId": user, "discordGuildId": DEMO_GUILD, "channelId": "c1",
            "mentionedUserIds": mentioned or []}


class ProcessMessage(unittest.TestCase):
    def test_commute_partners_only_opted_in(self):
        svc, model = service([[("find_commute_partners", {"day": "today"})], "Priya is heading in around then."])
        resp = run(svc.process_message(ctx("Anyone heading to ASU around 9 AM?")))
        self.assertEqual(resp["responseText"], "Priya is heading in around then.")
        self.assertEqual(resp["metadata"]["toolsCalled"], ["find_commute_partners"])
        self.assertIn("commute-matching", resp["metadata"]["skillsUsed"])
        result = json.loads(tool_results(model)[0])
        self.assertEqual([m["who"] for m in result["matches"]], ["Priya"])  # Sam (not opted in) excluded
        self.assertNotIn("discordUserId", result["matches"][0])

    def test_group_departure_agreed(self):
        svc, model = service([[("propose_group_departure", {"day": "today", "travel_minutes": 25})], "ok"])
        run(svc.process_message(ctx("Can we share an Uber to campus? <@1002>", mentioned=["1002"])))
        r = json.loads(tool_results(model)[0])
        # Alex: 8:00 to 8:25 (arrive 8:50 - 25). Priya: 8:00 to 8:30 (arrive 8:55 - 25).
        self.assertEqual((r["status"], r["proposedDeparture"]), ("agreed", "8:00 AM"))
        self.assertEqual(r["travelMinutesAssumed"], 25)

    def test_group_departure_conflict_from_chat_constraints(self):
        svc, model = service([[("propose_group_departure", {
            "day": "today", "travel_minutes": 25,
            "stated_constraints": ["Priya can't leave before 8:28 AM"]})], "ok"])
        run(svc.process_message(ctx("<@1002> can't leave before 8:28", mentioned=["1002"])))
        r = json.loads(tool_results(model)[0])
        # Alex must leave by 8:25 (arrive 8:50 - 25 min); Priya can leave 8:28 to 8:30
        self.assertEqual(r["status"], "conflict")
        self.assertEqual(r["fitsEveryoneExcept"][0]["minutesToMove"], 3)
        self.assertEqual(r["constraintsUsed"], {"Priya": {"earliest": "08:28"}})

    def test_group_departure_impossible_for_one(self):
        svc, model = service([[("propose_group_departure", {
            "day": "today", "travel_minutes": 25,
            "stated_constraints": "Priya not before 8:40"})], "ok"])
        run(svc.process_message(ctx("<@1002> can't leave before 8:40", mentioned=["1002"])))
        r = json.loads(tool_results(model)[0])
        self.assertEqual(r["status"], "impossible_for_some")  # 8:40 + 25 min misses her 8:55 arrival

    def test_group_departure_without_classes_asks_instead_of_guessing(self):
        svc, model = service([[("propose_group_departure", {"day": "saturday"})], "What time do you need to be there?"])
        run(svc.process_message(ctx("share a ride saturday?", mentioned=["1002"])))
        r = json.loads(tool_results(model)[0])
        self.assertFalse(r["ok"])
        self.assertIn("Don't suggest a time", r["error"])

    def test_group_departure_with_arrival_time(self):
        svc, model = service([[("propose_group_departure", {"day": "saturday", "arrive_by": "10:00 AM",
                                                             "travel_minutes": 25})], "ok"])
        run(svc.process_message(ctx("share a ride saturday, need to be there at 10", mentioned=["1002"])))
        r = json.loads(tool_results(model)[0])
        # both usually leave from 8:00; latest 9:35 (10:00 - 25)
        self.assertEqual((r["status"], r["proposedDeparture"], r["commonWindow"]), ("agreed", "8:00 AM", "08:00-09:35"))

    def test_typed_schedule_is_prepared_not_saved(self):
        db = demo_database()
        db.delete_student_schedule(DEMO_GUILD, "1001")
        svc, _ = service([[("prepare_schedule_from_text", {"semester": "Fall 2026", "classes": [
            {"courseCode": "CSE 110", "days": "MWF", "startTime": "9:00 AM", "endTime": "9:50 AM",
             "location": "Tempe - ISTB4 101"}]})], "Here's what I got. Press Confirm to save."], db=db)
        resp = run(svc.process_message(ctx("My classes: CSE 110 MWF 9-9:50 ISTB4 101")))
        pend = resp["metadata"]["pendingSchedule"]
        self.assertTrue(pend["confirmationRequired"])
        self.assertEqual(pend["extractedSchedule"]["courses"][0]["meetingPatterns"][0]["startTime"], "09:00")
        self.assertIsNone(db.get_student_schedule(DEMO_GUILD, "1001"))  # nothing persisted
        saved = run(svc.save_confirmed_schedule("1001", DEMO_GUILD))
        self.assertEqual(saved["confirmationStatus"], "confirmed")
        self.assertEqual(db.get_student_schedule(DEMO_GUILD, "1001")["courses"][0]["courseCode"], "CSE 110")
        with self.assertRaises(ValueError):
            run(svc.save_confirmed_schedule("1001", DEMO_GUILD))  # pending was cleared

    def test_save_preferences_rejects_addresses(self):
        svc, model = service([[("save_commute_preferences", {"general_origin_area": "1234 E Main St"})], "ok"])
        run(svc.process_message(ctx("I live at 1234 E Main St")))
        self.assertIn("street address", json.loads(tool_results(model)[0])["error"])

    def test_cannot_close_someone_elses_ride(self):
        svc, model = service([[("update_my_ride_request", {"request_id": "r-demo1", "status": "cancelled"})], "no"])
        run(svc.process_message(ctx("cancel ride r-demo1", user="1001")))
        self.assertFalse(json.loads(tool_results(model)[0])["ok"])

    def test_no_database_is_explained(self):
        model = ScriptedModel(script=[[("get_my_schedule", {})], "The database isn't connected."], seen=[])
        svc = AgentService(None, model=model, clock=lambda: MONDAY_7AM)
        resp = run(svc.process_message(ctx("what's my schedule?")))
        self.assertIn("isn't connected", json.loads(tool_results(model)[0])["error"])
        self.assertEqual(resp["responseText"], "The database isn't connected.")

    def test_empty_message_and_history(self):
        svc, model = service(["first", "second"])
        self.assertEqual(run(svc.process_message(ctx("  ")))["metadata"]["error"], "empty_message")
        run(svc.process_message(ctx("hello")))
        run(svc.process_message(ctx("again")))
        self.assertIn("first", [m.content for m in model.seen[-1]])  # previous answer kept as history

    def test_model_failure_gives_fallback(self):
        class Broken(ScriptedModel):
            def _generate(self, *a, **k):
                raise RuntimeError("boom")
        svc = AgentService(demo_database(), model=Broken(script=[], seen=[]), clock=lambda: MONDAY_7AM)
        self.assertIn("try again", run(svc.process_message(ctx("hi")))["responseText"])


class ConstraintParsing(unittest.TestCase):
    NAMES = {"1001": "you", "1002": "Priya", "1003": "Jordan Lee"}

    def parse(self, text):
        from agent.tools.agent_tools import parse_constraint
        return parse_constraint(text, "1001", self.NAMES)

    def test_sentences(self):
        self.assertEqual(self.parse("Priya can't leave before 8:28 AM"), ("1002", {"earliest": "08:28"}))
        self.assertEqual(self.parse("I must leave by 8:20am"), ("1001", {"latest": "08:20"}))
        self.assertEqual(self.parse("Jordan is free after 5 pm, has to leave by 6:30 pm"),
                         ("1003", {"earliest": "17:00", "latest": "18:30"}))
        self.assertEqual(self.parse("Sam can leave after 9"), (None, {"earliest": "09:00"}))  # not in the group
        self.assertEqual(self.parse("I must be on campus by 8:50 AM"), ("1001", {"arriveBy": "08:50"}))
        self.assertEqual(self.parse("Priya needs to arrive by 9"), ("1002", {"arriveBy": "09:00"}))


class Extraction(unittest.TestCase):
    def test_parse_json_with_fence(self):
        self.assertEqual(parse_json('Sure!\n```json\n{"a": 1}\n```'), {"a": 1})

    def test_image_extraction_normalizes_and_holds(self):
        reply = json.dumps({"semester": "Fall 2026", "courses": [
            {"courseCode": "CSE 110", "courseName": "Principles of Programming", "section": "",
             "meetingPatterns": [{"days": "Mon Wed Fri", "startTime": "9:00 AM", "endTime": "9:50 AM"}],
             "location": "Tempe - ISTB4 101"}]})
        db = demo_database()
        svc, _ = service([], db=db, vision=ScriptedModel(script=[f"```json\n{reply}\n```"], seen=[]))
        r = run(svc.extract_schedule_from_image(b"\x89PNG fake", "image/png", "1001", DEMO_GUILD))
        self.assertTrue(r["confirmationRequired"])
        self.assertEqual(len(r["extractedSchedule"]["courses"][0]["meetingPatterns"]), 3)
        self.assertIn("CSE 110", r["formatted"])
        self.assertEqual(svc.pending_schedule("1001")["semester"], "Fall 2026")

    def test_unreadable_image(self):
        r = run(extract_schedule(ScriptedModel(script=["I can't see a schedule"], seen=[]), b"x", "image/png"))
        self.assertEqual(r["extractedSchedule"]["courses"], [])
        self.assertIn("clearer", r["validationWarnings"][0])


class Skills(unittest.TestCase):
    def test_all_skills_load_with_tools(self):
        skills = load_skills()
        self.assertEqual(len(skills), 4)
        self.assertTrue(all("Tools needed" in s.sections and s.keywords for s in skills))
        self.assertEqual([s.id for s in select_skills(skills, "here is my class schedule screenshot")][0],
                         "schedule-upload")


if __name__ == "__main__":
    unittest.main()
