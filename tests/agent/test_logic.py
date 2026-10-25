import unittest

from src.agent.dev_database import DEMO_GUILD, demo_database
from src.agent.logic.availability import day_availability, departure_window
from src.agent.logic.matching import find_matches, same_area
from src.agent.logic.negotiation import negotiate
from src.agent.logic.schedule import (classes_on, format_schedule, is_valid_course, missing_for_save,
                                      normalize_schedule)
from src.agent.logic.timeutil import display, normalize_days, normalize_time, parse_window, resolve_day, to_minutes

from agent_helpers import MONDAY_7AM, get


class Time(unittest.TestCase):
    def test_times_and_days(self):
        self.assertEqual(normalize_time("2:00 PM"), "14:00")
        self.assertEqual(normalize_time("9:30am"), "09:30")
        self.assertEqual(normalize_time("12:15 am"), "00:15")
        self.assertIsNone(normalize_time("25:00"))
        self.assertEqual(normalize_days("MWF"), ["Monday", "Wednesday", "Friday"])
        self.assertEqual(normalize_days("TTh"), ["Tuesday", "Thursday"])
        self.assertEqual(normalize_days("Tue/Thu"), ["Tuesday", "Thursday"])
        self.assertEqual(normalize_days(["Mon", "Wednesday"]), ["Monday", "Wednesday"])
        self.assertEqual(parse_window("8am - 9am"), (480, 540))
        self.assertIsNone(parse_window("09:00-08:00"))
        self.assertEqual(display("14:05"), "2:05 PM")

    def test_resolve_day(self):
        self.assertEqual(resolve_day("today", MONDAY_7AM), "Monday")
        self.assertEqual(resolve_day("tomorrow", MONDAY_7AM), "Tuesday")
        self.assertEqual(resolve_day("fri", MONDAY_7AM), "Friday")
        self.assertEqual(resolve_day("2026-10-28", MONDAY_7AM), "Wednesday")
        with self.assertRaises(ValueError):
            resolve_day("someday", MONDAY_7AM)


class Schedule(unittest.TestCase):
    def test_normalize_and_warnings(self):
        raw = {"semester": "Fall 2026", "courses": [
            {"course_code": "cse110", "course_name": "Principles of Programming", "section": "",
             "meeting_patterns": [{"days": "Mon/Wed/Fri", "start_time": "9:00 AM", "end_time": "9:50 AM"}],
             "location": "Tempe - ISTB4 101"},
            {"course_code": "MAT 265", "meeting_patterns": [{"days": "MWF", "start_time": "9:30 AM", "end_time": "10:20 AM"}],
             "location": "COOR 170"},
            {"course_code": "HST 109", "location": "iCourse"},
            {"course_code": "ENG 101", "meeting_patterns": [{"days": "TTh", "start_time": "1:30", "end_time": "2:45"}],
             "location": "LL 104"}]}
        sched, warnings = normalize_schedule(raw)
        self.assertEqual(sched["courses"][0]["course_code"], "CSE 110")
        self.assertEqual(len(sched["courses"][0]["meeting_patterns"]), 3)
        self.assertTrue(any("overlap" in w for w in warnings))  # CSE 110 and MAT 265 on Monday
        self.assertFalse(any("HST 109" in w and "time" in w for w in warnings))  # online: no times needed
        self.assertTrue(any("ENG 101" in w and "unusual" in w for w in warnings))  # 1:30 read as 01:30
        # course name and section are optional (shared is_valid_course): no warning, still valid
        self.assertTrue(is_valid_course(sched["courses"][0]))
        self.assertEqual(missing_for_save(sched["courses"][0]), [])
        self.assertFalse(any("section" in w or "course name" in w for w in warnings))
        bad = {**sched["courses"][0], "location": "", "meeting_patterns": [
            {"day_of_week": "Monday", "start_time": "9am", "end_time": "09:50"}]}
        self.assertEqual(missing_for_save(bad), ["location", "valid meeting times"])
        self.assertIn("Mon/Wed/Fri 9:00 AM-9:50 AM", format_schedule(sched))

    def test_classes_on_skips_online(self):
        sched, _ = normalize_schedule({"courses": [
            {"course_code": "A 100", "meeting_patterns": [{"days": "M", "start_time": "10:00", "end_time": "11:00"}],
             "location": "Online"},
            {"course_code": "B 200", "meeting_patterns": [{"days": "M", "start_time": "12:00", "end_time": "13:00"}],
             "location": "COOR 170"}]})
        self.assertEqual([c["course_code"] for c in classes_on(sched, "Monday")], ["B 200"])


class Availability(unittest.TestCase):
    def setUp(self):
        self.db = demo_database()

    def av(self, uid, day="Monday"):
        return day_availability(uid, get(self.db, "get_student_schedule", DEMO_GUILD, uid),
                                get(self.db, "get_commute_preferences", DEMO_GUILD, uid), day)

    def test_class_vs_commute_availability(self):
        a = self.av("1001")
        self.assertEqual((a.first_class_start, a.arrive_by, a.last_class_end, a.earliest_leave_campus),
                         ("09:00", "08:50", "09:50", "10:00"))
        self.assertTrue(any("not a confirmed departure" in n for n in a.notes))

    def test_departure_windows(self):
        a = self.av("1001")
        lo, hi, why = departure_window(a, "to_campus", 30)
        self.assertEqual((lo, hi), (to_minutes("08:00"), to_minutes("08:20")))  # usual 8:00, arrive by 8:50 - 30
        lo, hi, _ = departure_window(a, "to_campus", 30, {"earliest": "08:10"})
        self.assertEqual(lo, to_minutes("08:10"))
        self.assertIsNone(departure_window(self.av("1003", "Friday"), "to_campus", 30))  # no classes Friday

    def test_unconfirmed_schedule_noted(self):
        s = get(self.db, "get_student_schedule", DEMO_GUILD, "1001")
        s["confirmation_status"] = "pending_confirmation"
        self.assertIn("schedule not confirmed yet", day_availability("1001", s, None, "Monday").notes)


class Matching(unittest.TestCase):
    def test_only_opted_in_same_area_close_times(self):
        db = demo_database()
        me = get(db, "get_commute_preferences", DEMO_GUILD, "1001")

        def av(uid):
            return day_availability(uid, get(db, "get_student_schedule", DEMO_GUILD, uid),
                                    get(db, "get_commute_preferences", DEMO_GUILD, uid), "Monday")
        others = [(get(db, "get_commute_preferences", DEMO_GUILD, u), av(u)) for u in ("1002", "1003", "1004")]
        matches = find_matches(me, av("1001"), others)
        # Priya: Mesa, opted in, on campus by 8:55 vs 8:50. Jordan: other area. Sam: not opted in.
        self.assertEqual([m["discord_user_id"] for m in matches], ["1002"])
        self.assertEqual(matches[0]["minutesApart"], 5)
        self.assertIn("carpool", matches[0]["sharedModes"])

    def test_area_normalization(self):
        self.assertTrue(same_area("Mesa", "mesa area"))
        self.assertTrue(same_area("Downtown Phoenix", "downtown phoenix"))
        self.assertFalse(same_area("Mesa", "Chandler"))
        self.assertFalse(same_area("", "Mesa"))


class Negotiation(unittest.TestCase):
    def test_agreed(self):
        r = negotiate({"a": (480, 500, []), "b": (490, 520, [])})
        self.assertEqual((r["status"], r["proposedDeparture"], r["commonWindow"]), ("agreed", "08:10", "08:10-08:20"))

    def test_conflict_names_who_moves(self):
        r = negotiate({"a": (480, 495, []), "b": (480, 500, []), "c": (510, 530, [])})
        self.assertEqual(r["status"], "conflict")
        self.assertEqual(sorted(r["fits"]), ["a", "b"])
        self.assertEqual(r["fitsEveryoneExcept"][0]["discord_user_id"], "c")
        self.assertEqual(r["fitsEveryoneExcept"][0]["minutesToMove"], 15)  # 8:30 -> 8:15

    def test_impossible_window(self):
        self.assertEqual(negotiate({"a": (500, 480, [])})["status"], "impossible_for_some")


if __name__ == "__main__":
    unittest.main()
