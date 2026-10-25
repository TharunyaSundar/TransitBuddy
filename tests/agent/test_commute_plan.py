"""/commute plan: request understanding, picking the class from the timetable, and the bus route reply.
Uses real recorded trip planner answers (fixtures/never_late_*.json, Tempe Marketplace -> Helmick Center for
Monday Oct 26 9:00 AM), a scripted model and the in-memory demo database. The clock is Monday 7:00 AM."""
import asyncio
import json
import unittest
from datetime import datetime
from pathlib import Path

from agent_helpers import MONDAY_7AM, PHX, ScriptedModel, get
from src.agent import AgentService, route
from src.agent.commute_plan import resolve_trip, understand_request
from src.agent.dev_database import DEMO_GUILD, demo_database
from src.agent.travel import TravelService

FIX = Path(__file__).resolve().parent / "fixtures"
HOME = "1 E Main St, Mesa, AZ 85201"  # Alex's (1001) saved home in the demo database


def fixture(name):
    return json.loads((FIX / f"never_late_{name}.json").read_text())


def run(coro):
    return asyncio.run(coro)


def planner(name="ok", status=200, record=None):
    async def call(body):
        if record is not None:
            record.append(body)
        if name is None:
            raise TimeoutError("planner down")
        return status, fixture(name)
    return call


def agent(understood: dict | str, db=None, travel=None):
    reply = understood if isinstance(understood, str) else json.dumps(understood)
    return AgentService(db or demo_database(), model=ScriptedModel(script=[reply], seen=[]),
                        clock=lambda: MONDAY_7AM, travel=travel or TravelService(caller=planner()))


class Understanding(unittest.TestCase):
    def test_parses_json_and_ignores_extras(self):
        model = ScriptedModel(script=['Sure!\n```json\n{"course": "CSE 110", "day": "Monday", "from": null, '
                                      '"to": "null", "arrive_by": "", "mood": "happy"}\n```'], seen=[])
        out = run(understand_request(model, "how do I get to CSE 110 on Monday", None, MONDAY_7AM))
        self.assertEqual(out, {"course": "CSE 110", "day": "Monday", "from": None, "to": None, "arrive_by": None})

    def test_model_failure_means_next_class_from_home(self):
        self.assertEqual(run(understand_request(ScriptedModel(script=["no idea"], seen=[]), "hi", None, MONDAY_7AM)), {})

    def test_model_never_sees_the_home_address(self):
        a = agent({})
        run(a.plan_commute("1001", DEMO_GUILD, "how do I get to class"))
        prompt = a.model.seen[0][0].content
        self.assertIn("CSE 110 (Mon/Wed/Fri 9:00 AM)", prompt)  # the class list, yes
        self.assertNotIn("Main St", prompt)  # the address, never


class WhichTrip(unittest.TestCase):
    def setUp(self):
        self.sched = get(demo_database(), "get_student_schedule", DEMO_GUILD, "1001")

    def test_next_class_course_and_day(self):
        t = resolve_trip({}, self.sched, MONDAY_7AM)
        self.assertEqual((t["title"], t["location"], t["start"]),
                         ("**CSE 110**, today at 9:00 AM", "Tempe - ISTB4 101", datetime(2026, 10, 26, 9, 0, tzinfo=PHX)))
        t = resolve_trip({"course": "mat265", "day": None}, self.sched, MONDAY_7AM)
        self.assertEqual((t["title"], t["location"]), ("**MAT 265**, tomorrow at 10:30 AM", "Tempe - COOR 170"))
        t = resolve_trip({"day": "Wednesday"}, self.sched, MONDAY_7AM)
        self.assertEqual(t["title"], "**CSE 110**, Wednesday, Oct 28 at 9:00 AM")

    def test_started_class_moves_to_its_next_meeting(self):
        t = resolve_trip({"course": "CSE 110"}, self.sched, MONDAY_7AM.replace(hour=9, minute=30))
        self.assertEqual(t["title"], "**CSE 110**, Wednesday, Oct 28 at 9:00 AM")

    def test_other_destination_needs_a_time(self):
        t = resolve_trip({"to": "Hayden Library", "arrive_by": "2pm", "day": "tomorrow"}, self.sched, MONDAY_7AM)
        self.assertEqual((t["title"], t["is_class"]), ("**Hayden Library**, tomorrow at 2:00 PM", False))
        self.assertIn("What time do you need to be at Hayden Library", resolve_trip({"to": "Hayden Library"}, self.sched,
                                                                                 MONDAY_7AM)["error"])

    def test_explained_failures(self):
        self.assertIn("/schedule upload", resolve_trip({}, None, MONDAY_7AM)["error"])
        self.assertIn("isn't in your saved schedule", resolve_trip({"course": "BIO 100"}, self.sched, MONDAY_7AM)["error"])
        self.assertIn("on Saturday", resolve_trip({"day": "Saturday"}, self.sched, MONDAY_7AM)["error"])
        self.assertIn("couldn't tell which day", resolve_trip({"day": "someday"}, self.sched, MONDAY_7AM)["error"])


class BusRoute(unittest.TestCase):
    def test_route_from_home_with_backup_rules(self):
        calls = []
        a = agent({}, travel=TravelService(caller=planner(record=calls)))
        text = run(a.plan_commute("1001", DEMO_GUILD, "how do I get to class"))
        self.assertTrue(text.startswith("**CSE 110**, today at 9:00 AM"))
        self.assertIn("**Leave at 8:28 AM** from home: walk 3 min to Tempe Marketplace, take **48th St** toward "
                      "Priest+Baseline at 8:32 AM", text)
        self.assertIn("I didn't find a later bus that still gets you there in time", text)  # none boards later
        self.assertIn("posted schedules, not live", text)
        body = calls[0]
        self.assertEqual((body["origin"], body["modes"], body["buffer_min"], body["arrive_by"]),
                         ({"label": "Home", "address": HOME}, ["TRANSIT", "WALK", "BICYCLE"], 10,
                          "2026-10-26T09:00:00-07:00"))
        self.assertEqual(body["destination"]["address"], "781 E. Terrace Mall, Tempe, AZ 85281")  # ISTB4, verified

    def test_backup_boards_later_and_still_arrives(self):
        d = fixture("ok")
        start = datetime(2026, 10, 26, 9, 10, tzinfo=PHX)  # a later class: University Dr becomes a usable backup?
        js = route.usable(d["journeys"], datetime(2026, 10, 26, 8, 0, tzinfo=PHX))
        ch = route.choose(js, start, 10)
        self.assertEqual(ch["primary"]["id"], "journey_1")
        self.assertIsNone(ch["backup"])  # same 8:32 boarding is not "later": no fake backup
        early = route.choose(js, datetime(2026, 10, 26, 9, 0, tzinfo=PHX), 10)
        self.assertEqual(early["primary"]["route"], "48th St")  # fewest transfers beats the transfer trip

    def test_from_a_named_place(self):
        calls = []
        a = agent({"from": "Memorial Union"}, travel=TravelService(caller=planner(record=calls)))
        text = run(a.plan_commute("1001", DEMO_GUILD, "I'm at the MU, how do I get to class?"))
        self.assertIn("from Memorial Union", text)
        self.assertEqual(calls[0]["origin"], {"label": "Memorial Union", "address": "1290 S. Normal Ave., Tempe, AZ 85287"})

    def test_buses_gone_walkable_and_late(self):
        late = AgentService(demo_database(), model=ScriptedModel(script=["{}"], seen=[]),
                            clock=lambda: MONDAY_7AM.replace(hour=8, minute=31), travel=TravelService(caller=planner()))
        text = run(late.plan_commute("1001", DEMO_GUILD, "class"))
        self.assertIn("The buses that would get you there in time have already left.", text)
        self.assertIn("bike (13 min)", text)
        short = run(agent({}, travel=TravelService(caller=planner("short_trip"))).plan_commute("1001", DEMO_GUILD, "x"))
        self.assertIn("**Leave at 8:40 AM** from home and walk (9 min)", short)
        self.assertNotIn("posted schedules", short)  # no bus in this answer

    def test_failures_are_explained(self):
        def run_with(travel, db=None, understood=None):
            return run(agent(understood or {}, db=db, travel=travel).plan_commute("1001", DEMO_GUILD, "class"))
        self.assertIn("busy", run_with(TravelService(caller=planner(status=429))))
        self.assertIn("isn't working", run_with(TravelService(caller=planner(None))))
        async def origin_not_found(body):
            return 200, {**fixture("error"), "error": {"code": "ADDRESS_NOT_FOUND", "field": "origin"}}
        self.assertIn("couldn't find your saved home address", run_with(TravelService(caller=origin_not_found)))
        self.assertIn("isn't set up", run_with(TravelService(token="")))
        db = demo_database()
        run(db.delete_student(DEMO_GUILD, "1001"))  # no home address saved
        text = run_with(TravelService(caller=planner()), db=db)
        self.assertIn('I need your home address to plan from home: use the "Set up your commute" button', text)

    def test_destination_error_names_the_place(self):
        d = fixture("error")  # the recorded error is for the destination field
        self.assertEqual(d["error"]["field"], "destination")
        text = run(agent({}, travel=TravelService(caller=planner("error"))).plan_commute("1001", DEMO_GUILD, "x"))
        self.assertIn("couldn't find Tempe - ISTB4 101", text)


if __name__ == "__main__":
    unittest.main()
