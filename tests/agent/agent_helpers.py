"""Agent test helpers: a scripted chat model (no Ollama needed) and a fixed clock."""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

logging.disable(logging.CRITICAL)  # expected failures are logged by the service

PHX = ZoneInfo("America/Phoenix")
MONDAY_7AM = datetime(2026, 10, 26, 7, 0, tzinfo=PHX)


class ScriptedModel(BaseChatModel):
    """Returns the given replies in order. A reply is a str (final answer) or a list of tool calls
    [(name, args), ...]. Records every prompt it saw."""
    script: list
    seen: list = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(messages)
        step = self.script.pop(0) if self.script else "done"
        if isinstance(step, str):
            msg = AIMessage(content=step)
        else:
            msg = AIMessage(content="", tool_calls=[{"name": n, "args": a, "id": f"call{i}"}
                                                    for i, (n, a) in enumerate(step)])
        return ChatResult(generations=[ChatGeneration(message=msg)])


def tool_results(model: ScriptedModel) -> list[str]:
    """Contents of the tool messages the model received on its last call."""
    return [m.content for m in model.seen[-1] if m.type == "tool"]


def get(db, method: str, *args):
    """Call an async DatabaseService method from a sync test and return plain dicts."""
    import asyncio

    from transit_buddy.agent.db import plain
    return plain(asyncio.run(getattr(db, method)(*args)))
