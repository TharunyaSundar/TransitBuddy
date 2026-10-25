# Schedule Upload Skill

## Name
Schedule Upload

## Description
Helps interpret uploaded class schedule screenshots and prepare a student schedule ready for manual confirmation.

## Activation conditions
- A student uploads an image or screenshot.
- The image appears to contain class timetable content.
- The user is asking to save or review their schedule.

## Required inputs
- Student identity and guild context.
- Screenshot or image data.
- Optional user description of the schedule.

## Expected outputs
- Extracted course records.
- Meeting patterns with weekday, start time, and end time.
- Validation warnings for ambiguous scheduling information.
- A response that asks for confirmation before persisting the schedule.

## Tools needed
- Multimodal extraction workflow.
- Student context lookup.
- Validation and parsing utilities.

## Rules and constraints
- Never persist unconfirmed schedules.
- Do not infer exact residential address information.
- Keep timezone handling explicit.
- Use consistent weekday naming.

## Example user requests
- "@Transit Buddy, here is my schedule."
- "Can you extract this timetable?"
- "I uploaded my class schedule screenshot."
