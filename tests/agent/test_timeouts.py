"""Model calls must never leave Discord stuck on "thinking": each one has a time limit."""
import asyncio
import json
import logging

import httpx

from agent_helpers import MONDAY_7AM, ScriptedModel
from src.agent import AgentService, agent as agent_module
from src.agent.dev_database import demo_database
from src.agent.extraction.schedule_extraction import extract_schedule
from src.agent.llm import create_chat_model, create_vision_model


class SlowModel(ScriptedModel):
    delay: float = 5.0

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        await asyncio.sleep(self.delay)
        return self._generate(messages, stop, run_manager, **kwargs)


class TimingOutModel(ScriptedModel):
    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        raise httpx.ReadTimeout("timed out")


def test_models_get_a_client_timeout(monkeypatch):
    monkeypatch.delenv("LLM_TIMEOUT_S", raising=False)
    monkeypatch.delenv("VISION_TIMEOUT_S", raising=False)
    assert create_chat_model().client_kwargs["timeout"] == 60
    assert create_vision_model().client_kwargs["timeout"] == 90
    monkeypatch.setenv("VISION_TIMEOUT_S", "45")
    assert create_vision_model().client_kwargs["timeout"] == 45


def test_api_key_header_kept_with_timeout(monkeypatch, caplog):
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://ollama.com")
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key-not-real")
    with caplog.at_level(logging.WARNING):
        m = create_chat_model("gemma4:cloud")
    assert m.client_kwargs["headers"] == {"Authorization": "Bearer test-key-not-real"}
    assert m.client_kwargs["timeout"] == 60
    assert "only work through the local Ollama app" in caplog.text  # wrong name for the direct API
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        create_chat_model("gemma4:31b")
    assert caplog.text == ""


def test_slow_screenshot_reading_gives_up():
    r = asyncio.run(extract_schedule(SlowModel(script=[json.dumps({"courses": []})], seen=[], delay=5),
                                     b"x", "image/png", timeout=0.2))
    assert r["extracted_schedule"]["courses"] == []
    assert "took too long" in r["validation_warnings"][0]


def test_client_timeout_is_reported_as_too_long():
    r = asyncio.run(extract_schedule(TimingOutModel(script=[], seen=[]), b"x", "image/png", timeout=30))
    assert "took too long (over 30 seconds)" in r["validation_warnings"][0]


def test_slow_agent_turn_gives_up(monkeypatch):
    monkeypatch.setattr(agent_module, "TURN_TIMEOUT_S", 0.2)
    svc = AgentService(demo_database(), model=SlowModel(script=["hi"], seen=[], delay=5), clock=lambda: MONDAY_7AM)
    resp = asyncio.run(svc.process_message({"message": "hello", "discord_user_id": "1001",
                                            "discord_guild_id": "demo-guild", "channel_id": "c"}))
    assert resp.response_text == "Sorry, that took too long. Please try again in a minute."
