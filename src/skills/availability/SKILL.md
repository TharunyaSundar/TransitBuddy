# Availability Skill

## Name
Availability

## Description
Determines when students are realistically available to travel based on their class schedules, stated departure windows and trip times, finds free time between classes (for errands, lunch or a break), and proposes one departure time for a group travelling together.

## Activation conditions
- A user asks when a student can leave campus.
- A user wants to negotiate departure times.
- A group travelling together needs one departure time that balances everyone's constraints.
- A user asks when they have free time between classes, for errands, lunch or a break.

## Required inputs
- Class schedule and meeting patterns.
- Student commute profiles (usual departure window; home address only for their own trip time).
- Stated time preferences or constraints.
- Guild context and participant list.

## Expected outputs
- Availability windows for leaving campus.
- Suggested departure windows that honor class timing and preferences.
- Conflict notes where constraints are not aligned.

## Tools needed
- get_availability (on campus by, classes over at, usual window, for the user and anyone @mentioned).
- get_free_time (gaps between the user's classes on a day, when to be back, usable minutes).
- propose_group_departure (common window, or the best compromise and who would need to move).

## Keywords
leave, leaving, available, availability, free, when, depart, departure, window, agree, negotiate, after, before, time, together, group, share, uber, lyft, carpool, errand, errands, between, gap, gaps, break, breaks, lunch, spare

## Rules and constraints
- A class ending at a given time does not automatically imply an immediate departure.
- Actual commute availability is a separate concept from class availability.
- Do not assume a student wants to travel with others without consent; plan only with classmates the user named.
- Keep the model conservative when the input is ambiguous.
- For free time, report only the gaps get_free_time returns, with when to be back; don't add travel time to an errand you don't know.

## Example user requests
- "When can we leave campus after class?"
- "I can leave after 8:30 AM."
- "On Tuesday, when do I have time between classes to run errands?"
- "Can we agree on a departure window that works for everyone?"
