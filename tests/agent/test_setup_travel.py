"""Commute setup (the private form) and home -> class travel times, with a fake trip planner."""
import asyncio
import json
import unittest

from agent_helpers import MONDAY_7AM, ScriptedModel, get, tool_results
from src.agent import AgentService
from src.agent.commute import parse_setup
from src.agent.dev_database import DEMO_GUILD, demo_database
from src.agent.travel import TravelService, find_building

ADDRESS = "2000 E Rio Salado Pkwy, Tempe, AZ 85288"  # a public place (Tempe Marketplace)


def run(coro):
    return asyncio.run(coro)


def planner(minutes=None, fail=None, record=None, origin=(33.4316, -111.9031)):
    """Fake Never Late planner: {mode: minutes}; fail = 'not_found' | 'down'; origin = where the address resolved."""
    minutes = minutes or {"DRIVE": 12, "TRANSIT": 25, "WALK": 50, "BICYCLE": 20}

    async def call(body):
        if record is not None:
            record.append(body)
        if fail == "down":
            raise TimeoutError("planner down")
        if fail == "not_found":
            return 200, {"ok": False, "error": {"code": "ADDRESS_NOT_FOUND", "field": "origin"}}
        mode = body["modes"][0]
        return 200, {"ok": True, "resolved": {"origin": {"lat": origin[0], "lng": origin[1]}},
                     "journeys": [{"mode": mode, "total_min": minutes[mode]},
                                  {"mode": mode, "total_min": minutes[mode] + 9}]}
    return call


def agent(db=None, travel=None, script=None):
    return AgentService(db or demo_database(), model=ScriptedModel(script=script or [], seen=[]),
                        clock=lambda: MONDAY_7AM, travel=travel or TravelService(caller=planner()))


class ParseSetup(unittest.TestCase):
    def test_valid_form(self):
        s = parse_setup(" Mesa ", "3-3:30 PM", "carpool, bus and bike", "Yes", f" {ADDRESS} ")
        self.assertEqual(s, {"general_origin_area": "Mesa", "usual_departure_window": "15:00-15:30",
                             "preferred_transport_modes": ["carpool", "bus", "bike"], "ride_sharing_opt_in": True,
                             "home_address": ADDRESS})
        self.assertIsNone(parse_setup("Mesa", "", "", "no", "")["home_address"])  # empty address: none saved

    def test_rejections(self):
        for args, words in [(("", "", "", "no", ""), "general area"),
                            (("123 E Main St", "", "", "no", ""), "should be general"),
                            (("Mesa", "sometime", "", "no", ""), "range"),
                            (("Mesa", "9:00-8:00 AM", "", "no", ""), "range"),
                            (("Mesa", "", "", "maybe", ""), "yes or no"),
                            (("Mesa", "", "", "no", "my house"), "street address")]:
            with self.assertRaisesRegex(ValueError, words):
                parse_setup(*args)


class Travel(unittest.TestCase):
    def test_buildings_and_fallback(self):
        self.assertEqual(find_building("Tempe, ISTB4 101")["code"], "ISTB4")
        self.assertEqual(find_building("Tempe - Lattie F. Coor 4403")["code"], "COOR")
        self.assertIsNone(find_building("Tempe, PSF 201"))  # not in the verified list

    def test_minutes_cache_and_fallback(self):
        calls = []
        t = TravelService(caller=planner(record=calls))
        est = run(t.minutes(ADDRESS, "Tempe, ISTB4 101", "TRANSIT", MONDAY_7AM.replace(hour=9, minute=20)))
        self.assertEqual((est.minutes, est.destination, est.describe()),
                         (25, "Interdisciplinary Science and Technology IV", "25 min by bus or train"))
        self.assertEqual(calls[0]["destination"]["address"], "781 E. Terrace Mall, Tempe, AZ 85281")
        self.assertEqual(calls[0]["arrive_by"], "2026-10-26T09:20:00-07:00")
        run(t.minutes(ADDRESS, "Tempe, ISTB4 101", "TRANSIT", MONDAY_7AM.replace(hour=9, minute=20)))
        self.assertEqual(len(calls), 1)  # cached
        far = run(t.minutes(ADDRESS, "Tempe, PSF 201", "DRIVE", MONDAY_7AM.replace(hour=9)))
        self.assertEqual((far.minutes, far.destination, far.exact_building), (12, "campus (Memorial Union)", False))

    def test_failures_are_not_cached(self):
        state = {"limited": True}
        good = planner()

        async def call(body):
            if state["limited"]:
                return 429, {"ok": False, "error": {"code": "RATE_LIMITED"}}
            return await good(body)
        t = TravelService(caller=call)
        when = MONDAY_7AM.replace(hour=9)
        self.assertIsNone(run(t.minutes(ADDRESS, "ISTB4", "DRIVE", when)))  # rate limited: estimate this time
        state["limited"] = False
        self.assertEqual(run(t.minutes(ADDRESS, "ISTB4", "DRIVE", when)).minutes, 12)  # retried, not stuck

    def test_never_raises_and_off_without_token(self):
        down = TravelService(caller=planner(fail="down"))
        self.assertIsNone(run(down.minutes(ADDRESS, "ISTB4", "DRIVE", MONDAY_7AM.replace(hour=9))))
        self.assertEqual(run(down.check_address(ADDRESS, MONDAY_7AM)), "unavailable")
        off = TravelService(token="")
        self.assertFalse(off.enabled)
        self.assertIsNone(run(off.minutes(ADDRESS, "ISTB4", "DRIVE", MONDAY_7AM)))
        self.assertEqual(run(TravelService(caller=planner(fail="not_found")).check_address(ADDRESS, MONDAY_7AM)),
                         "not_found")


class SetupAndPrivacy(unittest.TestCase):
    def test_save_defaults_forget(self):
        db = demo_database()
        a = agent(db)
        text = run(a.save_commute_setup("5005", DEMO_GUILD, "Tempe", "8-8:30 AM", "bus", "yes", ADDRESS))
        self.assertIn("Home address: saved privately", text)
        self.assertNotIn("Rio Salado", text)  # the summary never echoes the address
        saved = get(db, "get_commute_preferences", DEMO_GUILD, "5005")
        self.assertEqual((saved["home_address"], saved["usual_departure_window"], saved["ride_sharing_opt_in"]),
                         (ADDRESS, "08:00-08:30", True))
        self.assertEqual(run(a.commute_setup_defaults("5005", DEMO_GUILD)),
                         {"area": "Tempe", "window": "8:00 AM-8:30 AM", "modes": "bus", "opt_in": "yes",
                          "address": ADDRESS})
        self.assertIn("Deleted your home address", run(a.forget_home_address("5005", DEMO_GUILD)))
        self.assertIsNone(get(db, "get_commute_preferences", DEMO_GUILD, "5005")["home_address"])
        self.assertIn("don't have a home address", run(a.forget_home_address("5005", DEMO_GUILD)))

    def test_unknown_address_is_not_saved(self):
        db = demo_database()
        a = agent(db, travel=TravelService(caller=planner(fail="not_found")))
        with self.assertRaisesRegex(ValueError, "couldn't find that home address"):
            run(a.save_commute_setup("5005", DEMO_GUILD, "Tempe", "", "", "no", "1 Nowhere Rd, Atlantis"))
        self.assertIsNone(get(db, "get_commute_preferences", DEMO_GUILD, "5005"))

    def test_address_matched_far_away_is_rejected(self):
        # what Google did with "99999 Zzyzx Qwerty Blvd, Nowhereville": matched Zzyzx Rd, California
        db = demo_database()
        a = agent(db, travel=TravelService(caller=planner(origin=(35.143, -116.1038))))
        self.assertEqual(run(a.travel.check_address("99999 Zzyzx Qwerty Blvd, Nowhereville, ZZ", MONDAY_7AM)), "too_far")
        with self.assertRaisesRegex(ValueError, "far from ASU Tempe"):
            run(a.save_commute_setup("5005", DEMO_GUILD, "Tempe", "", "", "no", "99999 Zzyzx Qwerty Blvd"))
        self.assertIsNone(get(db, "get_commute_preferences", DEMO_GUILD, "5005"))
        self.assertEqual(run(TravelService(caller=planner()).check_address(ADDRESS, MONDAY_7AM)), "ok")  # Tempe

    def test_model_never_sees_the_address_and_chat_keeps_it(self):
        db = demo_database()
        a = agent(db, script=[[("get_my_commute_preferences", {})], "ok",
                              [("save_commute_preferences", {"general_origin_area": "Chandler"})], "ok"])
        run(a.save_commute_setup("1001", DEMO_GUILD, "Mesa", "", "", "yes", ADDRESS))
        model = a.model
        run(a.process_message({"message": "what are my settings?", "discord_user_id": "1001",
                               "discord_guild_id": DEMO_GUILD, "channel_id": "c"}))
        seen = tool_results(model)[0]
        self.assertNotIn("Rio Salado", seen)
        self.assertEqual(json.loads(seen)["preferences"]["home_address"], "saved (private)")
        run(a.process_message({"message": "I moved to Chandler", "discord_user_id": "1001",
                               "discord_guild_id": DEMO_GUILD, "channel_id": "c"}))
        self.assertNotIn("Rio Salado", tool_results(model)[0])
        saved = get(db, "get_commute_preferences", DEMO_GUILD, "1001")
        self.assertEqual((saved["general_origin_area"], saved["home_address"]), ("Chandler", ADDRESS))


class TravelInReplies(unittest.TestCase):
    def test_availability_leave_home_only_for_yourself(self):
        db = demo_database()
        a = agent(db)
        run(a.save_commute_setup("1001", DEMO_GUILD, "Mesa", "8:00-8:30 AM", "bus", "yes", ADDRESS))
        run(a.save_commute_setup("1002", DEMO_GUILD, "Mesa", "8:00-8:40 AM", "carpool", "yes", ADDRESS))
        text = run(a.commute_availability("1001", DEMO_GUILD, "Monday", ["1002"]))
        mine, theirs = [line for line in text.splitlines() if line.startswith("- ")]
        # first class CSE 110 at ISTB4 9:00 -> on campus by 8:50, 25 min by bus -> leave home by 8:25
        self.assertIn("leave home by 8:25 AM (25 min by bus or train to Interdisciplinary Science and "
                      "Technology IV, from the trip planner)", mine)
        self.assertNotIn("leave home", theirs)  # never a classmate's home trip

    def test_plan_uses_longest_home_trip(self):
        db = demo_database()
        a = agent(db, travel=TravelService(caller=planner({"DRIVE": 20, "TRANSIT": 25, "WALK": 50, "BICYCLE": 20})))
        run(a.save_commute_setup("1001", DEMO_GUILD, "Mesa", "8:00-8:30 AM", "carpool", "yes", ADDRESS))
        text = run(a.commute_plan("1001", DEMO_GUILD, ["1002"], "Monday"))
        self.assertIn("Based on a 20-minute trip: the longest trip from your saved homes, from the trip planner.", text)
        self.assertIn("Everyone can leave between 8:00 AM and 8:30 AM.", text)  # 8:50 - 20 = 8:30
        no_addresses = run(agent(demo_database()).commute_plan("1001", DEMO_GUILD, ["1002"], "Monday"))
        self.assertIn("Assuming a 30-minute trip (an estimate: save a home address with /commute setup", no_addresses)
        given = run(a.commute_plan("1001", DEMO_GUILD, ["1002"], "Monday", travel_minutes=15))
        self.assertIn("Based on a 15-minute trip.", given)


if __name__ == "__main__":
    unittest.main()
