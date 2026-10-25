"""Commute setup form and its post-schedule button, tested with fake Discord interactions, a fake trip planner
and the agent's in-memory demo database."""
import asyncio
from types import SimpleNamespace

from test_schedule_commands import FakeVision

from src.agent import AgentService
from src.agent.dev_database import DEMO_GUILD, demo_database
from src.agent.travel import TravelService
from src.discord_bot.commands.commute import build_commute_group
from src.discord_bot.commands.schedule import NOT_READY, build_schedule_group
from src.discord_bot.commands.setup import CommuteSetupModal, SetupPromptView

ADDRESS = "2000 E Rio Salado Pkwy, Tempe, AZ 85288"


async def fake_planner(body):
    return 200, {"ok": True, "journeys": [{"mode": body["modes"][0], "total_min": 15}]}


class FakeResponse:
    def __init__(self):
        self.modal, self.sent, self.deferred = None, [], None

    async def send_modal(self, modal):
        self.modal = modal

    async def send_message(self, content, ephemeral=False):
        self.sent.append({"content": content, "ephemeral": ephemeral})

    async def edit_message(self, **kw):
        self.edited = kw

    async def defer(self, ephemeral=False, thinking=False):
        self.deferred = {"ephemeral": ephemeral, "thinking": thinking}


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, content, ephemeral=False, **kw):
        self.sent.append({"content": content, "ephemeral": ephemeral, "view": kw.get("view")})


def interaction(user="1001", name="Alex"):
    return SimpleNamespace(user=SimpleNamespace(id=int(user), display_name=name), guild_id=DEMO_GUILD,
                           response=FakeResponse(), followup=FakeFollowup())


def make_agent(db=None):
    return AgentService(db or demo_database(), model=FakeVision(reply="unused"),
                        travel=TravelService(caller=fake_planner))


def fill(modal: CommuteSetupModal, area="Tempe", window="8:00-8:30 AM", modes="bus", opt_in="yes", address=ADDRESS):
    for box, value in ((modal.area, area), (modal.window, window), (modal.modes, modes), (modal.opt_in, opt_in),
                       (modal.address, address)):
        box._value = value


def open_form(agent, user="1001", name="Alex"):
    inter = interaction(user, name)
    asyncio.run(SetupPromptView(agent, user).children[0].callback(inter))
    return inter.response.modal


def submit(modal, user="1001", name="Alex"):
    inter = interaction(user, name)
    asyncio.run(modal.on_submit(inter))
    return inter


def test_form_is_prefilled_and_saves_on_the_student_record():
    db = demo_database()
    agent = make_agent(db)
    modal = open_form(agent)
    assert isinstance(modal, CommuteSetupModal)
    assert modal.address.required and modal.children[0].text == "Home address (required)"
    assert (modal.address.default, modal.area.default, modal.window.default, modal.opt_in.default) == \
        ("1 E Main St, Mesa, AZ 85201", "Mesa", "8:00 AM-8:30 AM", "yes")

    fill(modal)
    done = submit(modal)
    assert done.response.deferred == {"ephemeral": True, "thinking": True}
    reply = done.followup.sent[0]
    assert reply["ephemeral"] and reply["content"].startswith("Saved your commute setup:")
    assert ADDRESS not in reply["content"]
    s = asyncio.run(db.get_student(DEMO_GUILD, "1001"))
    assert (s.home_address, s.general_origin_area, s.commute_match_opt_in) == (ADDRESS, "Tempe", True)


def test_new_student_gets_a_record_with_their_discord_name():
    db = demo_database()
    agent = make_agent(db)
    modal = open_form(agent, user="5005", name="Riya")
    assert modal.address.default is None  # nothing saved yet
    fill(modal, area="", opt_in="no")
    submit(modal, user="5005", name="Riya")
    s = asyncio.run(db.get_student(DEMO_GUILD, "5005"))
    assert (s.display_name, s.home_address, s.general_origin_area, s.commute_match_opt_in) == \
        ("Riya", ADDRESS, None, False)


def test_bad_form_input_is_explained_not_saved():
    db = demo_database()
    agent = make_agent(db)
    for kwargs, words in [({"address": ""}, "Not saved: Add your home address"),
                          ({"area": "742 Evergreen Terrace"}, "Not saved: The area should be general"),
                          ({"area": "", "opt_in": "yes"}, "Not saved: Add your general area")]:
        modal = open_form(agent)
        fill(modal, **kwargs)
        assert submit(modal).followup.sent[0]["content"].startswith(words)
    assert asyncio.run(db.get_student(DEMO_GUILD, "1001")).general_origin_area == "Mesa"  # unchanged


def test_schedule_view_offers_setup_and_delete():
    db = demo_database()
    agent = make_agent(db)
    view_cmd = build_schedule_group(lambda: agent).get_command("view")
    inter = interaction()
    asyncio.run(view_cmd.callback(inter))
    msg = inter.followup.sent[0]
    assert "Commute profile: saved (home address private)." in msg["content"]
    assert ADDRESS not in msg["content"] and "1 E Main St" not in msg["content"]
    assert [c.label for c in msg["view"].children] == ["Set up your commute", "Delete my commute profile"]

    press = interaction()
    asyncio.run(msg["view"].children[1].callback(press))  # Delete
    assert "Deleted your commute profile" in press.followup.sent[0]["content"]
    assert asyncio.run(db.get_student(DEMO_GUILD, "1001")) is None
    assert asyncio.run(db.get_student_schedule(DEMO_GUILD, "1001")) is not None  # schedule kept

    inter = interaction()
    asyncio.run(view_cmd.callback(inter))
    msg = inter.followup.sent[0]
    assert "No commute profile yet" in msg["content"]
    assert [c.label for c in msg["view"].children] == ["Set up your commute"]


def test_unregistered_commute_commands_still_work_and_not_ready():
    db = demo_database()
    agent = make_agent(db)
    inter = interaction()
    asyncio.run(build_commute_group(lambda: agent).get_command("setup").callback(inter))
    assert isinstance(inter.response.modal, CommuteSetupModal)
    inter = interaction()
    asyncio.run(build_commute_group(lambda: agent).get_command("forget-address").callback(inter))
    assert "Deleted your commute profile" in inter.followup.sent[0]["content"]
    inter = interaction()
    asyncio.run(build_commute_group(lambda: None).get_command("setup").callback(inter))
    assert inter.response.sent[0] == {"content": NOT_READY, "ephemeral": True}


def test_buttons_only_for_the_student():
    agent = make_agent()
    view = SetupPromptView(agent, "1001", can_delete=True)
    assert asyncio.run(view.interaction_check(interaction(user="2002"))) is False
    assert asyncio.run(view.interaction_check(interaction())) is True
