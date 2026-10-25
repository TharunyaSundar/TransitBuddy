"""Test helpers: put src/ on the path and provide a scripted chat model (no Ollama needed)."""
import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from langchain_core.language_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402

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
