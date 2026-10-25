# Integration Contracts

This document defines the service boundaries for the project. These interfaces are intentionally simple and designed for independent development on separate branches.

## DatabaseService

The DatabaseService contract is owned by the MongoDB developer and consumed by the agent developer. The service must manage student, schedule, commute, and ride request data scoped to a Discord guild.

```js
/**
 * @typedef {Object} Student
 * @property {string} discordUserId
 * @property {string} discordGuildId
 * @property {string} displayName
 * @property {string} university
 * @property {string} campus
 * @property {string} timezone
 * @property {string} createdAt
 * @property {string} updatedAt
 */

/**
 * @typedef {Object} StudentSchedule
 * @property {string} discordUserId
 * @property {string} discordGuildId
 * @property {string} semester
 * @property {Array<Object>} courses
 * @property {'pending_confirmation'|'confirmed'} confirmationStatus
 * @property {string} updatedAt
 */

/**
 * @typedef {Object} CommutePreferences
 * @property {string} discordUserId
 * @property {string} discordGuildId
 * @property {string} generalOriginArea
 * @property {string} generalDestinationArea
 * @property {string[]} preferredTransportModes
 * @property {string} usualDepartureWindow
 * @property {boolean} rideSharingOptIn
 */

/**
 * @typedef {Object} RideRequest
 * @property {string} requestId
 * @property {string} discordUserId
 * @property {string} discordGuildId
 * @property {string} originArea
 * @property {string} destinationArea
 * @property {string} desiredDepartureTime
 * @property {'open'|'matched'|'cancelled'|'completed'} status
 * @property {string} createdAt
 */
```

### Required methods

```js
/**
 * Insert or update a student document by Discord guild and user identity.
 *
 * @param {Student} student
 * @returns {Promise<Student>}
 * @throws {Error} If required identifiers are missing or persistence fails.
 */
async upsertStudent(student) {}

/**
 * Fetch a student record for a guild and Discord user.
 *
 * @param {string} discordGuildId
 * @param {string} discordUserId
 * @returns {Promise<Student|null>}
 */
async getStudent(discordGuildId, discordUserId) {}

/**
 * Save or replace a student's schedule.
 *
 * @param {StudentSchedule} schedule
 * @returns {Promise<StudentSchedule>}
 */
async saveSchedule(schedule) {}

/**
 * Fetch a student's schedule scoped by guild and Discord user.
 *
 * @param {string} discordGuildId
 * @param {string} discordUserId
 * @returns {Promise<StudentSchedule|null>}
 */
async getStudentSchedule(discordGuildId, discordUserId) {}

/**
 * Fetch schedules for multiple students within a guild.
 *
 * @param {string} discordGuildId
 * @param {string[]} discordUserIds
 * @returns {Promise<StudentSchedule[]>}
 */
async getSchedulesForUsers(discordGuildId, discordUserIds) {}

/**
 * Delete a student's schedule record.
 *
 * @param {string} discordGuildId
 * @param {string} discordUserId
 * @returns {Promise<boolean>}
 */
async deleteStudentSchedule(discordGuildId, discordUserId) {}

/**
 * Save or update a student's commute preferences.
 *
 * @param {CommutePreferences} preferences
 * @returns {Promise<CommutePreferences>}
 */
async saveCommutePreferences(preferences) {}

/**
 * Fetch commute preferences for a student within a guild.
 *
 * @param {string} discordGuildId
 * @param {string} discordUserId
 * @returns {Promise<CommutePreferences|null>}
 */
async getCommutePreferences(discordGuildId, discordUserId) {}

/**
 * Create a ride request.
 *
 * @param {RideRequest} request
 * @returns {Promise<RideRequest>}
 */
async createRideRequest(request) {}

/**
 * Return all active ride requests in a guild.
 *
 * @param {string} discordGuildId
 * @returns {Promise<RideRequest[]>}
 */
async getOpenRideRequests(discordGuildId) {}

/**
 * Update the status of a ride request.
 *
 * @param {string} requestId
 * @param {'open'|'matched'|'cancelled'|'completed'} status
 * @returns {Promise<RideRequest|null>}
 */
async updateRideRequestStatus(requestId, status) {}
```

### Error behavior

- All methods should reject with an Error when required data is missing.
- Guild-scoped queries must never cross Discord guild boundaries.
- When a record is not found, methods should return null or an empty array depending on the API contract.
- Unexpected persistence errors should be surfaced to the caller without leaking secrets.

## AgentService

The AgentService contract is implemented by the LangChain developer and used by the Discord developer. The service is responsible for interpreting user messages, multi-modal schedule extraction, and generating Discord-friendly outputs.

```js
/**
 * @typedef {Object} ProcessMessageContext
 * @property {string} message
 * @property {string} discordUserId
 * @property {string} discordGuildId
 * @property {string} channelId
 * @property {string[]} mentionedUserIds
 */

/**
 * @typedef {Object} AgentResponse
 * @property {string} responseText
 * @property {Object} [metadata]
 */

/**
 * @typedef {Object} ScheduleExtractionResult
 * @property {Object} extractedSchedule
 * @property {string[]} validationWarnings
 * @property {boolean} confirmationRequired
 */
```

### Required methods

```js
/**
 * Process a Discord message and determine the best response.
 *
 * @param {ProcessMessageContext} context
 * @returns {Promise<AgentResponse>}
 */
async processMessage(context) {}

/**
 * Extract a schedule from an uploaded image.
 *
 * @param {Buffer|string} imageInput
 * @param {string} mimeType
 * @param {string} discordUserId
 * @param {string} discordGuildId
 * @returns {Promise<ScheduleExtractionResult>}
 */
async extractScheduleFromImage(imageInput, mimeType, discordUserId, discordGuildId) {}
```

### Contract requirements

- processMessage receives a message string and metadata from Discord.
- The response must contain text suitable for Discord display.
- The agent must not automatically persist unconfirmed schedules.
- Agent logic must not directly access Discord for bot lifecycle tasks.
- The agent may use DatabaseService for schedule and preference lookups.
- Discord-specific actions stay on the Discord side.

## Boundary Notes

- Developer 1 uses AgentService from Discord handlers and presents the agent output in Discord.
- Developer 2 implements DatabaseService for persistence and retrieval.
- Developer 3 implements AgentService and the LangChain reasoning flow.

This keeps each branch isolated while preserving a clean project-level architecture.
