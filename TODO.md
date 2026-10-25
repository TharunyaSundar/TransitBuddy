# TODO: align agent and Discord with the new database model

Branch `feature/students-home-address` changed the database layer. **Delete this file when every box is ticked.**

## What changed (database layer, already done)

- MongoDB now has **only two collections: `students` and `schedules`**.
  - `commute_preferences` and `ride_requests` collections, repositories and `DatabaseService` methods are **gone**.
- `Student.home_address: str` is **mandatory** (`src/shared/contracts.py`). A blank, whitespace-only or missing value
  is rejected with a `ValueError`. It is private: never show it to other students.
- `upsert_student` now writes only the fields the caller set. Because `home_address` is required, every upsert
  must carry the address.
- Removed from `DatabaseService`: `save_commute_preferences`, `get_commute_preferences`,
  `get_opted_in_commute_preferences`, `create_ride_request`, `get_open_ride_requests`, `update_ride_request_status`.
- `scripts/seed_demo_data.py` now seeds students (with addresses) and schedules only.

## Decisions for you (not made yet)

- [ ] Where do the old commute fields live now: `general_origin_area`, `general_destination_area`,
      `preferred_transport_modes`, `usual_departure_window`, `ride_sharing_opt_in`?
      Options: add them to `Student`, derive them (area from `home_address`, window from the schedule), or drop them.
      Whatever you pick must be agreed with Developer 2 so `Student` and the docs match.
- [ ] How does `/commute match` find partners without an opt-in flag? (Matching in `src/agent/logic/matching.py`
      filters on `ride_sharing_opt_in`.)

## Agent (`src/agent/`)

- [ ] `db.py`: remove `save_commute_preferences` / `create_ride_request` from the model map.
- [ ] `dev_database.py`: remove preferences and rides, and give every demo `Student` a `home_address`
      (this one missing argument is why most tests fail right now).
- [ ] `agent.py`: `save_commute_setup`, the `home_address` read/forget logic and the `get_commute_preferences` calls must use
      the student record. Note `forget_home_address` can no longer set it to `None`; the field is required.
- [ ] `commute.py` and `logic/matching.py`: stop depending on `CommutePreferences` and `get_opted_in_commute_preferences`.
- [ ] `tools/agent_tools.py`: remove or rewrite `get_my_commute_preferences`, `save_commute_preferences`,
      `list_open_ride_requests`, `create_ride_request`, `update_my_ride_request`.
- [ ] Ride-sharing is being removed: delete `src/skills/ride-sharing/SKILL.md`, and update
      `commute-matching/SKILL.md` and `src/agent/README.md` where they mention preferences or ride requests.

## Discord (`src/discord_bot/`)

- [ ] `commands/setup.py` (`/commute setup`): the form must collect a required home address and save it on the student.
- [ ] Decide what happens to a student who has no address yet (they cannot be saved without one).

## Tests

- [ ] Fix `tests/agent/*` and `tests/discord/*` (48 failing at the time of writing).
- [ ] `tests/agent/test_with_database.py` builds `Student(...)` without `home_address` and calls the removed
      `save_commute_preferences` / ride-request methods.
- [ ] `tests/agent/test_setup_travel.py`, `test_logic.py`, `test_service.py` and `tests/discord/test_commute_commands.py`,
      `test_setup_commands.py` reference the removed methods.
- [ ] Run the database-backed tests too: `TEST_MONGODB_URI=<uri> pytest`.

## Cleanup once nothing imports them

- [ ] Delete `CommutePreferences` and `RideRequest` from `src/shared/contracts.py`, plus `RIDE_REQUEST_STATUSES` /
      `RideRequestStatus` and `is_valid_ride_request_status` (`src/shared/validators.py`).
- [ ] Drop the old Atlas collections `commute_preferences` and `ride_requests` (ask Developer 2; they still hold demo data).
- [ ] Old `students` documents without `home_address` fail validation when read: re-run `python -m scripts.seed_demo_data`
      or delete them.
- [ ] Update `docs/integration-contracts.md` and the root `README.md` if they still mention commute or ride data.
- [ ] **Delete this `TODO.md`.**
