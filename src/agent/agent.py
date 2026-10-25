"""AgentService: the API Developer 1's Discord layer calls (docs/integration-contracts.md).

    service = AgentService(database_service)          # Developer 2's DatabaseService
    resp = await service.process_message(ProcessMessageContext(message=..., discord_user_id=...,
                                                               discord_guild_id=..., channel_id=...,
                                                               mentioned_user_ids=[...]))
    resp.response_text   -> send to Discord
    resp.metadata        -> skills_used, tools_called, and pending_schedule when a typed schedule needs
                            the Confirm button
    result = await service.extract_schedule_from_image(image_bytes, "image/png", user_id, guild_id)
    -> show service.format_schedule(result.extracted_schedule) + result.validation_warnings with
       Confirm / Edit buttons, then on Confirm:
    await service.save_confirmed_schedule(user_id, guild_id)   # the only path that persists a schedule
"""
import logging
from collections import defaultdict, deque
from datetime import datetime, timezone

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ..shared.contracts import AgentResponse, ProcessMessageContext, ScheduleExtractionResult, StudentSchedule
from . import db as dbcall
from .extraction.schedule_extraction import extract_schedule
from .llm import create_chat_model, create_vision_model
from .logic.schedule import format_schedule, is_valid_course, missing_for_save
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
        """database_service: Developer 2's DatabaseService (async methods returning the shared models).
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

    async def process_message(self, context: ProcessMessageContext | dict) -> AgentResponse:
        if isinstance(context, dict):
            context = ProcessMessageContext.model_validate(context)
        message = context.message.strip()
        user_id, guild_id = context.discord_user_id, context.discord_guild_id or "dm"
        if not message or not user_id:
            return AgentResponse(response_text="Say what you need, for example: when can I leave campus today?",
                                 metadata={"error": "empty_message" if user_id else "missing_user"})
        mentioned = [u for u in context.mentioned_user_ids if u != user_id]
        selected = select_skills(self.skills, message)
        name = None
        if self.db is not None:
            try:
                name = ((await dbcall.call(self.db, "get_student", guild_id, user_id)) or {}).get("display_name")
            except Exception:
                name = None
        now = self.clock()
        ctx = AgentContext(discord_user_id=user_id, discord_guild_id=guild_id, db=self.db,
                           channel_id=context.channel_id, mentioned_user_ids=mentioned, now=now,
                           pending=self.pending)
        key = (guild_id, context.channel_id, user_id)
        group = {}
        for uid in mentioned:
            try:
                group[uid] = ((await dbcall.call(self.db, "get_student", guild_id, uid)) or {}).get("display_name") \
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
        meta = {"skills_used": [s.id for s in selected], "tools_called": tools_called, **ctx.events}
        return AgentResponse(response_text=text, metadata=meta)

    async def extract_schedule_from_image(self, image_input, mime_type: str, discord_user_id: str,
                                          discord_guild_id: str) -> ScheduleExtractionResult:
        """Read a schedule screenshot. Nothing is saved; the schedule waits for save_confirmed_schedule."""
        result = ScheduleExtractionResult.model_validate(
            await extract_schedule(self.vision, image_input, mime_type or "image/png"))
        if result.extracted_schedule["courses"]:
            # the same dict the caller gets, so the caller can tell whether it is still the pending one
            self.pending[discord_user_id] = result.extracted_schedule
        return result

    @staticmethod
    def format_schedule(extracted_schedule: dict) -> str:
        """The extracted schedule as a short Discord list, for the confirmation message."""
        return format_schedule(extracted_schedule)

    def pending_schedule(self, discord_user_id: str) -> dict | None:
        return self.pending.get(discord_user_id)

    async def save_confirmed_schedule(self, discord_user_id: str, discord_guild_id: str,
                                      schedule: dict | None = None) -> StudentSchedule:
        """Call after the student presses Confirm. Saves the pending (or given, edited) schedule as confirmed."""
        sched = schedule or self.pending.get(discord_user_id)
        if not sched or not sched.get("courses"):
            raise ValueError("no schedule waiting for confirmation")
        bad = [f"{c.get('course_code') or '?'} ({', '.join(missing_for_save(c))})"
               for c in sched["courses"] if not is_valid_course(c)]
        if bad:
            raise ValueError(f"fix these classes before saving: {'; '.join(bad)}")
        doc = {"discord_user_id": discord_user_id, "discord_guild_id": discord_guild_id or "dm",
               "semester": sched.get("semester") or "", "courses": sched["courses"],
               "confirmation_status": "confirmed",
               "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
        saved = await dbcall.call(self.db, "save_schedule", doc)
        self.pending.pop(discord_user_id, None)
        return StudentSchedule.model_validate(saved or doc)

    async def view_schedule(self, discord_user_id: str, discord_guild_id: str) -> str:
        """The student's saved schedule, and any schedule still waiting for Confirm, as Discord text."""
        saved = await dbcall.call(self.db, "get_student_schedule", discord_guild_id or "dm", discord_user_id)
        parts = []
        if saved and saved.get("courses"):
            status = "saved" if saved.get("confirmation_status") == "confirmed" else "not confirmed yet"
            parts.append(f"Your schedule ({status}):\n{format_schedule(saved)}")
        pending = self.pending.get(discord_user_id)
        if pending and pending.get("courses"):
            parts.append(f"Waiting for you to confirm:\n{format_schedule(pending)}")
        if not parts:
            return "You haven't saved a schedule yet. Use /schedule upload with a screenshot of your class schedule."
        return "\n\n".join(parts)[:MAX_RESPONSE_CHARS]

    def discard_pending_schedule(self, discord_user_id: str) -> None:
        self.pending.pop(discord_user_id, None)

    def forget_conversation(self, discord_user_id: str) -> None:
        for k in [k for k in self.history if k[2] == discord_user_id]:
            del self.history[k]


def _text(content) -> str:
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict)).strip()
    return (content or "").strip()
