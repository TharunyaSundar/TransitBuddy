# Commute Matching Skill

## Name
Commute Matching

## Description
Matches nearby students who share compatible schedules and commute preferences while honoring opt-in expectations.

## Activation conditions
- A user asks if anyone is traveling to campus around a specific time.
- A user requests potential commute partners.
- There are multiple students with compatible departure windows.

## Required inputs
- Student's origin and destination areas.
- Commute preferences and departure windows.
- Student schedule data and class times.
- Guild-scoped peer information.

## Expected outputs
- A list of compatible students.
- A brief explanation of why the match is plausible.
- An invitation to ask whether they are interested.

## Tools needed
- Database queries for schedules and preferences.
- Matching logic for schedule compatibility.
- Response formatting for Discord.

## Rules and constraints
- Only consider students who explicitly opted into commute matching.
- Distinguish between class availability and commute availability.
- Do not assume students are leaving campus immediately after a class ends.
- Keep results general and privacy-conscious.

## Example user requests
- "Anyone heading to ASU around 9 AM tomorrow?"
- "Who is going to campus around the same time as me?"
- "Find commute partners in my area."
