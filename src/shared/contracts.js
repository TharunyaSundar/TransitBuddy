/**
 * @typedef {Object} Student
 * @property {string} discordUserId - Discord snowflake for the student.
 * @property {string} discordGuildId - Discord guild where the student belongs.
 * @property {string} displayName - The student display name in Discord.
 * @property {string} university - University name, such as Arizona State University.
 * @property {string} campus - Campus location for the student, such as Tempe.
 * @property {string} timezone - IANA timezone name, such as America/Phoenix.
 * @property {string} createdAt - ISO timestamp when the student record was created.
 * @property {string} updatedAt - ISO timestamp when the student record was last updated.
 */

/**
 * @typedef {Object} MeetingPattern
 * @property {'Monday'|'Tuesday'|'Wednesday'|'Thursday'|'Friday'|'Saturday'|'Sunday'} dayOfWeek - Day of the week.
 * @property {string} startTime - Start time in 24-hour HH:mm format.
 * @property {string} endTime - End time in 24-hour HH:mm format.
 */

/**
 * @typedef {Object} Course
 * @property {string} courseCode - Course code, such as CSE 565.
 * @property {string} courseName - Human-readable course title.
 * @property {string} section - Section or lab identifier when applicable.
 * @property {MeetingPattern[]} meetingPatterns - All scheduled meeting times for the course.
 * @property {string} location - Campus room or building location.
 */

/**
 * @typedef {Object} StudentSchedule
 * @property {string} discordUserId - Discord user ID for the student.
 * @property {string} discordGuildId - Discord guild ID for the guild where the schedule belongs.
 * @property {string} semester - Semester or term label, such as Fall 2026.
 * @property {Course[]} courses - Courses saved in the student's schedule.
 * @property {'pending_confirmation'|'confirmed'} confirmationStatus - Whether the schedule is awaiting confirmation.
 * @property {string} updatedAt - Last updated timestamp in ISO format.
 */

/**
 * @typedef {Object} CommutePreferences
 * @property {string} discordUserId - Discord user ID for the student.
 * @property {string} discordGuildId - Discord guild ID for the guild where the commute preferences belong.
 * @property {string} generalOriginArea - General origin area such as Downtown Phoenix or Tempe Village.
 * @property {string} generalDestinationArea - General destination area such as ASU Tempe campus or Engineering District.
 * @property {string[]} preferredTransportModes - Candidate transport modes such as carpool, rideshare, bus, bike.
 * @property {string} usualDepartureWindow - Typical departure window, such as 08:00-09:00.
 * @property {boolean} rideSharingOptIn - Whether the student explicitly opts in to ride-sharing matching.
 */

/**
 * @typedef {Object} RideRequest
 * @property {string} requestId - Unique ride request identifier.
 * @property {string} discordUserId - Discord user who submitted the request.
 * @property {string} discordGuildId - Discord guild ID for the request scope.
 * @property {string} originArea - General starting area for the ride request.
 * @property {string} destinationArea - Destination area for the ride request.
 * @property {string} desiredDepartureTime - Desired departure time in ISO or human-readable format.
 * @property {'open'|'matched'|'cancelled'|'completed'} status - Current ride request status.
 * @property {string} createdAt - ISO timestamp when the request was created.
 */

export const COURSE_WEEKDAYS = [
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
  'Sunday',
];

export const CONFIRMATION_STATUSES = ['pending_confirmation', 'confirmed'];

export const RIDE_REQUEST_STATUSES = ['open', 'matched', 'cancelled', 'completed'];

export const STUDENT_CONTRACT = {
  type: 'object',
  required: [
    'discordUserId',
    'discordGuildId',
    'displayName',
    'university',
    'campus',
    'timezone',
    'createdAt',
    'updatedAt',
  ],
};

export const SCHEDULE_CONTRACT = {
  type: 'object',
  required: ['discordUserId', 'discordGuildId', 'semester', 'courses', 'confirmationStatus', 'updatedAt'],
};

export const COMMUTE_PREFERENCES_CONTRACT = {
  type: 'object',
  required: [
    'discordUserId',
    'discordGuildId',
    'generalOriginArea',
    'generalDestinationArea',
    'preferredTransportModes',
    'usualDepartureWindow',
    'rideSharingOptIn',
  ],
};

export const RIDE_REQUEST_CONTRACT = {
  type: 'object',
  required: [
    'requestId',
    'discordUserId',
    'discordGuildId',
    'originArea',
    'destinationArea',
    'desiredDepartureTime',
    'status',
    'createdAt',
  ],
};
