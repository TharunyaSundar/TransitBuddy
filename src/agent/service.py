"""AgentService: the API Developer 1's Discord layer calls (docs/integration-contracts.md).

    service = AgentService(database_service)          # Developer 2's DatabaseService
    resp = await service.process_message({"message": "...", "discordUserId": "...", "discordGuildId": "...",
                                          "channelId": "...", "mentionedUserIds": [...]})
    resp["responseText"]          -> send to Discord
    resp["metadata"]              -> skillsUsed, toolsCalled, and pendingSchedule when a typed schedule
                                     needs the Confirm button
    result = await service.extract_schedule_from_image(image_bytes, "image/png", user_id, guild_id)
    -> show result["extractedSchedule"] + warnings with Confirm / Edit buttons, then on Confirm:
    await service.save_confirmed_schedule(user_id, guild_id)   # the only path that persists a schedule
"""
import logging
from collections import defaultdict, deque
from datetime import datetime, timezone

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from . import db as dbcall
from .extraction.schedule_extraction import extract_schedule
from .llm import create_chat_model, create_vision_model
from .logic.schedule import format_schedule, is_valid_course
from .logic.timeutil import now as tz_now
from .prompts.system_prompt import build_system_prompt
from .skill_loader import load_skills, select_skills, skills_prompt
from .tools.agent_tools import ALL_TOOLS, AgentContext

log = logging.getLogger(__name__)

HISTORY_MESSAGES = 10  # per user per channel; tool calls are not kept, to save tokens
MAX_RESPONSE_CHARS = 1900  # Discord's limit is 2000
FALLBACK = "Sorry, I couldn't work that out right now. Please try again in a minute."


class AgentService:
    def __init__(self, database_service=None, model=None, vision_model=None, skills=None, clock=None):
        """database_service: Developer 2's DatabaseService (sync or async methods).
        model / vision_model: LangChain chat models (default: from LLM_* environment variables).
        clock: optional callable returning the current datetime (tests)."""
        self.db = database_service
        self.model = model or create_chat_model()
        self._vision = vision_model
        self.skills = skills if skills is not None else load_skills()
        self.clock = clock or tz_now
        self.graph = create_agent(self.model, ALL_TOOLS, context_schema=AgentContext)
        self.history: dict[tuple, deque] = defaultdict(lambda: deque(maxlen=HISTORY_MESSAGES))
        self.pending: dict[str, dict] = {}  # user id -> schedule waiting for confirmation (never persisted)

    @property
    def vision(self):
        if self._vision is None:
            self._vision = create_vision_model()
        return self._vision

    async def process_message(self, context: dict) -> dict:
        message = (context.get("message") or "").strip()
        user_id, guild_id = context.get("discordUserId"), context.get("discordGuildId") or "dm"
        if not message or not user_id:
            return {"responseText": "Say what you need, for example: when can I leave campus today?",
                    "metadata": {"error": "empty_message" if user_id else "missing_user"}}
        mentioned = [u for u in context.get("mentionedUserIds") or [] if u != user_id]
        selected = select_skills(self.skills, message)
        name = context.get("displayName")
        if not name and self.db is not None:
            try:
                name = ((await dbcall.call(self.db, "get_student", guild_id, user_id)) or {}).get("displayName")
            except Exception:
                name = None
        now = self.clock()
        ctx = AgentContext(discord_user_id=user_id, discord_guild_id=guild_id, db=self.db,
                           channel_id=context.get("channelId", ""), mentioned_user_ids=mentioned, now=now,
                           pending=self.pending)
        key = (guild_id, context.get("channelId", ""), user_id)
        group = {}
        for uid in mentioned:
            try:
                group[uid] = ((await dbcall.call(self.db, "get_student", guild_id, uid)) or {}).get("displayName") \
                    or "a classmate"
            except Exception:
                group[uid] = "a classmate"
        system = build_system_prompt(now, skills_prompt(self.skills, selected), name, group)
        msgs = [SystemMessage(system), *self.history[key], HumanMessage(message)]
        tools_called: list[str] = []
        try:
            out = await self.graph.ainvoke({"messages": msgs}, context=ctx, config={"recursion_limit": 14})
            new = out["messages"][len(msgs):]
            tools_called = [tc["name"] for m in new for tc in (getattr(m, "tool_calls", None) or [])]
            text = _text(out["messages"][-1].content) or FALLBACK
        except Exception:
            log.exception("agent turn failed")
            text = FALLBACK
        if len(text) > MAX_RESPONSE_CHARS:
            text = text[:MAX_RESPONSE_CHARS - 1].rsplit("\n", 1)[0] + "\n…"
        self.history[key].extend([HumanMessage(message), AIMessage(text)])
        meta = {"skillsUsed": [s.id for s in selected], "toolsCalled": tools_called, **ctx.events}
        return {"responseText": text, "metadata": meta}

    async def extract_schedule_from_image(self, image_input, mime_type: str, discord_user_id: str,
                                          discord_guild_id: str) -> dict:
        """Read a schedule screenshot. Returns a ScheduleExtractionResult; nothing is saved."""
        result = await extract_schedule(self.vision, image_input, mime_type or "image/png")
        if result["extractedSchedule"]["courses"]:
            self.pending[discord_user_id] = result["extractedSchedule"]
        result["formatted"] = format_schedule(result["extractedSchedule"])  # ready to show in Discord
        return result

    def pending_schedule(self, discord_user_id: str) -> dict | None:
        return self.pending.get(discord_user_id)

    async def save_confirmed_schedule(self, discord_user_id: str, discord_guild_id: str,
                                      schedule: dict | None = None) -> dict:
        """Call after the student presses Confirm. Saves the pending (or given, edited) schedule as confirmed."""
        sched = schedule or self.pending.get(discord_user_id)
        if not sched or not sched.get("courses"):
            raise ValueError("no schedule waiting for confirmation")
        bad = [c.get("courseCode") or "?" for c in sched["courses"] if not is_valid_course(c)]
        if bad:
            raise ValueError(f"fix these classes before saving: {', '.join(bad)}")
        doc = {"discordUserId": discord_user_id, "discordGuildId": discord_guild_id or "dm",
               "semester": sched.get("semester") or "", "courses": sched["courses"],
               "confirmationStatus": "confirmed",
               "updatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
        saved = await dbcall.call(self.db, "save_schedule", doc)
        self.pending.pop(discord_user_id, None)
        return saved or doc

    def discard_pending_schedule(self, discord_user_id: str) -> None:
        self.pending.pop(discord_user_id, None)

    def forget_conversation(self, discord_user_id: str) -> None:
        for k in [k for k in self.history if k[2] == discord_user_id]:
            del self.history[k]


def _text(content) -> str:
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict)).strip()
    return (content or "").strip()
