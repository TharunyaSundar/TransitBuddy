"""/commute setup (the private form), /commute forget-address and the setup button after a schedule is saved.
Fake Discord interactions, a fake trip planner and the agent's in-memory demo database."""
import asyncio
from types import SimpleNamespace

from test_schedule_commands import FakeVision

from src.agent import AgentService
from src.agent.dev_database import DEMO_GUILD, demo_database
from src.agent.travel import TravelService
from src.discord_bot.commands.commute import build_commute_group
from src.discord_bot.commands.schedule import NOT_READY
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

    async def defer(self, ephemeral=False, thinking=False):
        self.deferred = {"ephemeral": ephemeral, "thinking": thinking}


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, content, ephemeral=False, **kw):
        self.sent.append({"content": content, "ephemeral": ephemeral})


def interaction(user="1001"):
    return SimpleNamespace(user=SimpleNamespace(id=int(user)), guild_id=DEMO_GUILD, response=FakeResponse(),
                           followup=FakeFollowup())


def make_agent(db=None):
    return AgentService(db or demo_database(), model=FakeVision(reply="unused"),
                        travel=TravelService(caller=fake_planner))


def fill(modal: CommuteSetupModal, area="Tempe", window="8:00-8:30 AM", modes="bus", opt_in="yes", address=ADDRESS):
    for box, value in ((modal.area, area), (modal.window, window), (modal.modes, modes), (modal.opt_in, opt_in),
                       (modal.address, address)):
        box._value = value


def test_setup_opens_prefilled_private_form_and_saves():
    db = demo_database()
    agent = make_agent(db)
    inter = interaction()
    asyncio.run(build_commute_group(lambda: agent).get_command("setup").callback(inter))
    modal = inter.response.modal
    assert isinstance(modal, CommuteSetupModal)
    assert (modal.area.default, modal.window.default, modal.opt_in.default) == ("Mesa", "8:00 AM-8:30 AM", "yes")
    assert modal.address.default is None  # nothing saved yet

    fill(modal)
    submit = interaction()
    asyncio.run(modal.on_submit(submit))
    assert submit.response.deferred == {"ephemeral": True, "thinking": True}
    reply = submit.followup.sent[0]
    assert reply["ephemeral"] and reply["content"].startswith("Saved your commute setup:")
    assert ADDRESS not in reply["content"]
    assert asyncio.run(db.get_commute_preferences(DEMO_GUILD, "1001")).home_address == ADDRESS


def test_bad_form_input_is_explained_not_saved():
    db = demo_database()
    agent = make_agent(db)
    inter = interaction()
    asyncio.run(build_commute_group(lambda: agent).get_command("setup").callback(inter))
    modal = inter.response.modal
    fill(modal, area="742 Evergreen Terrace", address="")
    submit = interaction()
    asyncio.run(modal.on_submit(submit))
    assert submit.followup.sent[0]["content"].startswith("Not saved: The area should be general")
    assert asyncio.run(db.get_commute_preferences(DEMO_GUILD, "1001")).general_origin_area == "Mesa"  # unchanged


def test_forget_address_and_not_ready():
    db = demo_database()
    agent = make_agent(db)
    asyncio.run(agent.save_commute_setup("1001", DEMO_GUILD, "Mesa", "", "", "yes", ADDRESS))
    inter = interaction()
    asyncio.run(build_commute_group(lambda: agent).get_command("forget-address").callback(inter))
    assert "Deleted your home address" in inter.followup.sent[0]["content"]
    assert asyncio.run(db.get_commute_preferences(DEMO_GUILD, "1001")).home_address is None
    inter = interaction()
    asyncio.run(build_commute_group(lambda: None).get_command("setup").callback(inter))
    assert inter.response.sent[0] == {"content": NOT_READY, "ephemeral": True}


def test_button_after_schedule_confirm_opens_the_form():
    agent = make_agent()
    view = SetupPromptView(agent, "1001")
    assert asyncio.run(view.interaction_check(interaction(user="2002"))) is False  # only the student
    inter = interaction()
    asyncio.run(view.children[0].callback(inter))
    assert isinstance(inter.response.modal, CommuteSetupModal)
