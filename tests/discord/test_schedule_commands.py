"""/schedule upload and /schedule view with fake Discord interactions, a fake vision model and the agent's
in-memory demo database (no Discord, Ollama or MongoDB needed)."""
import asyncio
import json
from types import SimpleNamespace

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from src.agent import AgentService
from src.agent.dev_database import DEMO_GUILD, demo_database
from src.discord_bot.client import create_discord_client
from src.discord_bot.commands.schedule import NOT_READY, ConfirmScheduleView, build_schedule_group

USER = "1001"
SCREENSHOT = {"semester": "Spring 2027", "courses": [
    {"course_code": "CSE 340", "course_name": "Principles of Programming Languages", "section": "",
     "meeting_patterns": [{"days": "Tue/Thu", "start_time": "1:30 PM", "end_time": "2:45 PM"}],
     "location": "Tempe - BYENG 210"}]}


class FakeVision(BaseChatModel):
    reply: str

    @property
    def _llm_type(self) -> str:
        return "fake-vision"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.reply))])


class FakeResponse:
    def __init__(self):
        self.sent, self.edited, self.deferred = [], [], None

    async def send_message(self, content, ephemeral=False, view=None):
        self.sent.append({"content": content, "ephemeral": ephemeral, "view": view})

    async def defer(self, ephemeral=False, thinking=False):
        self.deferred = {"ephemeral": ephemeral, "thinking": thinking}

    async def edit_message(self, content=None, view="unchanged"):
        self.edited.append({"content": content, "view": view})


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, content, view=None, ephemeral=False):
        self.sent.append({"content": content, "view": view, "ephemeral": ephemeral})


def interaction(user=USER):
    return SimpleNamespace(user=SimpleNamespace(id=int(user)), guild_id=DEMO_GUILD, response=FakeResponse(),
                           followup=FakeFollowup())


def attachment(content_type="image/png", size=1000):
    async def read():
        return b"\x89PNG fake"
    return SimpleNamespace(content_type=content_type, size=size, read=read)


def make_agent(reply=json.dumps(SCREENSHOT)):
    db = demo_database()
    asyncio.run(db.delete_student_schedule(DEMO_GUILD, USER))
    return AgentService(db, model=FakeVision(reply="unused"), vision_model=FakeVision(reply=reply)), db


def commands(agent):
    group = build_schedule_group(lambda: agent)
    return group.get_command("upload"), group.get_command("view")


def upload(agent, inter=None, image=None, semester=None):
    inter = inter or interaction()
    asyncio.run(commands(agent)[0].callback(inter, image or attachment(), semester))
    return inter


def test_bot_registers_schedule_group():
    bot = create_discord_client()
    group = bot.tree.get_command("schedule")
    assert sorted(c.name for c in group.commands) == ["upload", "view"]
    assert group.guild_only
    assert bot.agent is None  # created in setup_hook only when MongoDB is configured


def test_upload_rejects_non_images_and_reports_not_ready():
    agent, _ = make_agent()
    inter = upload(agent, image=attachment(content_type="application/pdf"))
    assert inter.response.sent[0]["ephemeral"] and "image" in inter.response.sent[0]["content"]
    inter = upload(agent, image=attachment(size=9 * 1024 * 1024))
    assert "too large" in inter.response.sent[0]["content"]
    inter = interaction()
    asyncio.run(build_schedule_group(lambda: None).get_command("upload").callback(inter, attachment(), None))
    assert inter.response.sent[0]["content"] == NOT_READY


def test_upload_shows_private_review_and_saves_nothing():
    agent, db = make_agent()
    inter = upload(agent)
    assert inter.response.deferred == {"ephemeral": True, "thinking": True}
    msg = inter.followup.sent[0]
    assert msg["ephemeral"]
    assert "CSE 340 (Principles of Programming Languages): Tue/Thu 1:30 PM-2:45 PM" in msg["content"]
    assert [c.label for c in msg["view"].children] == ["Confirm", "Cancel"]
    assert asyncio.run(db.get_student_schedule(DEMO_GUILD, USER)) is None  # not saved before Confirm
    assert agent.pending_schedule(USER)["semester"] == "Spring 2027"


def test_confirm_saves_and_view_shows_it():
    agent, db = make_agent()
    view = upload(agent).followup.sent[0]["view"]
    press = interaction()
    asyncio.run(view.children[0].callback(press))  # Confirm
    edited = press.response.edited[0]
    assert edited["content"].startswith("Saved your schedule. Use /schedule view to see it.")
    assert [c.label for c in edited["view"].children] == ["Set up your commute"]  # next step: the setup form
    saved = asyncio.run(db.get_student_schedule(DEMO_GUILD, USER))
    assert saved.confirmation_status == "confirmed" and saved.courses[0].course_code == "CSE 340"
    assert agent.pending_schedule(USER) is None

    look = interaction()
    asyncio.run(commands(agent)[1].callback(look))
    assert look.response.deferred == {"ephemeral": True, "thinking": False}
    assert look.followup.sent[0]["ephemeral"]
    assert "Your schedule (saved):" in look.followup.sent[0]["content"]
    assert "CSE 340" in look.followup.sent[0]["content"]


def test_cancel_discards_and_view_says_nothing_saved():
    agent, db = make_agent()
    view = upload(agent).followup.sent[0]["view"]
    look = interaction()
    asyncio.run(commands(agent)[1].callback(look))
    assert "Waiting for you to confirm" in look.followup.sent[0]["content"]

    press = interaction()
    asyncio.run(view.children[1].callback(press))  # Cancel
    assert press.response.edited[0]["view"] is None and "Not saved" in press.response.edited[0]["content"]
    assert agent.pending_schedule(USER) is None
    assert asyncio.run(db.get_student_schedule(DEMO_GUILD, USER)) is None
    look = interaction()
    asyncio.run(commands(agent)[1].callback(look))
    assert "haven't saved a schedule" in look.followup.sent[0]["content"]


def test_only_the_uploader_can_press_and_bad_schedules_are_not_saved():
    agent, db = make_agent()
    bad = {"semester": "", "courses": [{"course_code": "CSE 340", "location": "",
                                        "meeting_patterns": [{"day_of_week": "Tuesday", "start_time": "13:30",
                                                              "end_time": "14:45"}]}]}
    view = ConfirmScheduleView(agent, USER, DEMO_GUILD, bad)
    assert asyncio.run(view.interaction_check(interaction(user="2002"))) is False
    assert asyncio.run(view.interaction_check(interaction())) is True
    press = interaction()
    asyncio.run(view.children[0].callback(press))
    assert press.response.sent[0]["ephemeral"] and "Not saved: " in press.response.sent[0]["content"]
    assert "location" in press.response.sent[0]["content"]
    assert asyncio.run(db.get_student_schedule(DEMO_GUILD, USER)) is None


def test_timeout_discards_only_its_own_upload():
    agent, _ = make_agent()
    first = upload(agent).followup.sent[0]["view"]
    second = upload(agent).followup.sent[0]["view"]  # a newer upload replaces the pending schedule
    asyncio.run(first.on_timeout())
    assert agent.pending_schedule(USER) is second.schedule
    asyncio.run(second.on_timeout())
    assert agent.pending_schedule(USER) is None


def test_unreadable_screenshot_has_no_buttons():
    agent, _ = make_agent(reply="I can't see a schedule here")
    msg = upload(agent).followup.sent[0]
    assert msg["ephemeral"] and msg["view"] is None
    assert msg["content"].startswith("I couldn't read that screenshot")


def test_semester_option_fills_a_missing_semester():
    no_term = json.dumps({**SCREENSHOT, "semester": ""})
    agent, db = make_agent(reply=no_term)
    msg = upload(agent).followup.sent[0]
    assert "upload again with the semester option" in msg["content"]  # told how to add it
    agent, db = make_agent(reply=no_term)
    msg = upload(agent, semester=" Fall 2026 ").followup.sent[0]
    assert "Please check" not in msg["content"]  # the only warning was the missing semester
    asyncio.run(msg["view"].children[0].callback(interaction()))  # Confirm
    assert asyncio.run(db.get_student_schedule(DEMO_GUILD, USER)).semester == "Fall 2026"
