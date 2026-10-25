# Availability Skill

## Name
Availability

## Description
Determines when students are realistically available to leave campus based on their class schedules, stated departure windows, and ride-sharing coordination needs.

## Activation conditions
- A user asks when a student can leave campus.
- A user wants to negotiate departure times.
- A ride-sharing scenario requires balancing multiple constraints.

## Required inputs
- Class schedule and meeting patterns.
- Student commute preferences.
- Stated time preferences or constraints.
- Guild context and participant list.

## Expected outputs
- Availability windows for leaving campus.
- Suggested departure windows that honor class timing and preferences.
- Conflict notes where constraints are not aligned.

## Tools needed
- Schedule analysis.
- Commute preference lookup.
- Time-window comparison utilities.

## Rules and constraints
- A class ending at a given time does not automatically imply an immediate departure.
- Actual commute availability is a separate concept from class availability.
- Do not assume a student wants to share a ride without consent.
- Keep the model conservative when the input is ambiguous.

## Example user requests
- "When can we leave campus after class?"
- "I can leave after 8:30 AM."
- "Can we agree on a departure window that works for everyone?"
