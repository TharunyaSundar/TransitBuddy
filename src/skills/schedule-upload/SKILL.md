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
- Screenshots: AgentService.extract_schedule_from_image (called by the Discord layer before the agent sees the message).
- Typed classes: prepare_schedule_from_text (checks and prepares; never saves).
- get_my_schedule to show what is already saved.
- Saving happens only through AgentService.save_confirmed_schedule after the student presses Confirm.

## Keywords
schedule, timetable, screenshot, upload, classes, class, courses, course, semester, extract, save, my schedule

## Rules and constraints
- Never persist unconfirmed schedules.
- Do not infer, ask for or store a home address here. Students can save one privately with /commute setup;
  it's used only for their own trip times.
- Keep timezone handling explicit.
- Use consistent weekday naming.

## Example user requests
- "@Transit Buddy, here is my schedule."
- "Can you extract this timetable?"
- "I uploaded my class schedule screenshot."
