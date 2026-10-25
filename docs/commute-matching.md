# Meet on Your Way matching (Stage 7A)

Matching is a deterministic Python service in `src/agent/logic/commute_matching.py`.
It is not connected to `/commute plan`, Discord invitations, or background jobs.

The existing `students.commute_match_opt_in` field is explicit consent and defaults to
`false`; no MongoDB collection or schema change is needed. Call
`CommuteMatchService.record_plan(student, plan)` only after a student has an
address-free, successful commute plan with an estimated departure and duration.
Class schedules alone never create commute intentions.

The service compares students only when both opted in and have current intentions
in the same Discord guild, general origin area, travel date, direction, and campus
destination. Their estimated departures must be within the configured tolerance
(15 minutes by default), and their saved preferred modes and plan modes must be
compatible. This compares declared preferences and estimates only; it does not
infer shared routes, stops, or transit services.

Active intentions and pending match records live only in the bot process. They
expire after two hours by default (configurable when constructing the service),
and all temporary matching state is lost on process restart. Call
`remove_student(guild_id, user_id)` when consent is revoked. Stage 7B must
re-check persisted consent before sending invitations and must not reveal names or
other participant identity until both participants accept.

Returned candidates contain an opaque match ID and non-identifying compatibility
details only. Participant IDs, addresses, and class schedules are not included in
the result.
