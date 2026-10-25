# Ride Sharing Skill

## Name
Ride Sharing

## Description
Helps students coordinate group ride requests while balancing personal departure constraints and campus arrival needs.

## Activation conditions
- A user asks to share an Uber or Lyft.
- A group conversation includes ride-sharing constraints.
- Multiple students have open or compatible ride requests.

## Required inputs
- Participant origin and destination areas.
- Desired departure windows.
- Student arrival constraints and preferences.
- Ride request status and time needs.

## Expected outputs
- A suggested departure time or ride plan.
- A summary of key constraints from each participant.
- An offer to propose a group departure time.

## Tools needed
- list_open_ride_requests, create_ride_request (only when asked), update_my_ride_request.
- propose_group_departure (schedules + saved windows + what people said in the chat).

## Keywords
ride, rides, uber, lyft, share, sharing, carpool, split, group, pick, pickup, request, driver

## Rules and constraints
- Respect explicit opt-in behavior.
- Keep suggestions general and not based on exact addresses. A saved home address only sets that
  student's own trip time; it is never shown to other students or used for matching.
- Prefer negotiation rather than forcing a departure time.
- Distinguish between ideal and realistic departure times.

## Example user requests
- "Can we share an Uber tomorrow morning?"
- "Is there a ride available for campus?"
- "Can we coordinate a ride around 8:45 AM?"
