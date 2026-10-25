# Integration Contracts

This document defines the service boundaries for the project. These interfaces are intentionally simple and designed for independent development on separate branches. The data models live in `transit_buddy/shared/contracts.py` (Pydantic, snake_case fields; timestamps are ISO-8601 strings).

## DatabaseService

The DatabaseService contract is owned by the MongoDB developer and consumed by the agent developer. The service must manage student, schedule, commute, and ride request data scoped to a Discord guild.

Models: `Student`, `StudentSchedule` (`courses` -> `meeting_patterns`, `confirmation_status` is `pending_confirmation` or `confirmed`), `CommutePreferences`, `RideRequest` (`status` is `open`, `matched`, `cancelled`, or `completed`). See `contracts.py` for every field.

### Required methods

All methods are `async`.

```python
class DatabaseService(Protocol):
    async def upsert_student(self, student: Student) -> Student:
        """Insert or update a student by Discord guild and user identity.
        Raises ValueError if identifiers are missing; persistence errors propagate."""

    async def get_student(self, discord_guild_id: str, discord_user_id: str) -> Student | None: ...

    async def save_schedule(self, schedule: StudentSchedule) -> StudentSchedule:
        """Save or replace a student's schedule."""

    async def get_student_schedule(self, discord_guild_id: str, discord_user_id: str) -> StudentSchedule | None: ...

    async def get_schedules_for_users(
        self, discord_guild_id: str, discord_user_ids: list[str]
    ) -> list[StudentSchedule]: ...

    async def delete_student_schedule(self, discord_guild_id: str, discord_user_id: str) -> bool: ...

    async def save_commute_preferences(self, preferences: CommutePreferences) -> CommutePreferences: ...

    async def get_commute_preferences(
        self, discord_guild_id: str, discord_user_id: str
    ) -> CommutePreferences | None: ...

    async def create_ride_request(self, request: RideRequest) -> RideRequest: ...

    async def get_open_ride_requests(self, discord_guild_id: str) -> list[RideRequest]:
        """Return all active ride requests in a guild."""

    async def update_ride_request_status(
        self, request_id: str, status: RideRequestStatus
    ) -> RideRequest | None: ...
```

### Error behavior

- All methods should raise an exception (`ValueError`) when required data is missing.
- Guild-scoped queries must never cross Discord guild boundaries.
- When a record is not found, methods return `None` or an empty list depending on the API contract.
- Unexpected persistence errors should be surfaced to the caller without leaking secrets.

## AgentService

The AgentService contract is implemented by the LangChain developer and used by the Discord developer. The service is responsible for interpreting user messages, multi-modal schedule extraction, and generating Discord-friendly outputs.

Models: `ProcessMessageContext`, `AgentResponse`, `ScheduleExtractionResult` (see `contracts.py`).

### Required methods

```python
class AgentService(Protocol):
    async def process_message(self, context: ProcessMessageContext) -> AgentResponse:
        """Process a Discord message and determine the best response."""

    async def extract_schedule_from_image(
        self,
        image_input: bytes | str,
        mime_type: str,
        discord_user_id: str,
        discord_guild_id: str,
    ) -> ScheduleExtractionResult:
        """Extract a schedule from an uploaded image."""
```

### Contract requirements

- `process_message` receives a message string and metadata from Discord.
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
