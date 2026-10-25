# Commute Matching Skill

## Name
Commute Matching

## Description
Matches nearby students who share compatible schedules and commute profiles, only among students who opted in.

## Activation conditions
- A user asks if anyone is traveling to campus around a specific time.
- A user requests potential commute partners.
- There are multiple students with compatible departure windows.

## Required inputs
- Student's origin and destination areas.
- Commute profiles (general area, transport, usual departure window, opt-in) and class times.
- Student schedule data and class times.
- Guild-scoped peer information.

## Expected outputs
- A list of compatible students.
- A brief explanation of why the match is plausible.
- An invitation to ask whether they are interested.

## Tools needed
- get_my_commute_profile / update_my_commute_profile (general area, transport, usual departure window, opt-in).
- The private "Set up your commute" form (button under /schedule view) creates the profile; it needs the home address.
- find_commute_partners (opted-in students, same general area, arrival or leaving times within 30 minutes).

## Keywords
commute, partner, partners, heading, going, campus, travel, together, nearby, area, match, buddy, bus, carpool

## Rules and constraints
- Only consider students who explicitly opted into commute matching.
- Distinguish between class availability and commute availability.
- Do not assume students are leaving campus immediately after a class ends.
- Keep results general and privacy-conscious: never use or reveal anyone's home address.

## Example user requests
- "Anyone heading to ASU around 9 AM tomorrow?"
- "Who is going to campus around the same time as me?"
- "Find commute partners in my area."
