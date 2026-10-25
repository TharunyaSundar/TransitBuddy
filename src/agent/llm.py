"""LLM setup. Provider and model come from src.config.settings; the rest from the environment
(.env.example):

LLM_PROVIDER   ollama (default; the only provider wired up so far)
LLM_MODEL      default glm-5.3-flash:cloud (tool calling and vision, low token use)
VISION_MODEL   model for screenshot extraction (default: LLM_MODEL)
LLM_REASONING  thinking effort: low (default), high, false
OLLAMA_BASE_URL, OLLAMA_API_KEY  only to call ollama.com directly instead of the local Ollama app
LLM_TIMEOUT_S, VISION_TIMEOUT_S  seconds to wait for one model reply (default 60 and 90); the Ollama
               client otherwise waits forever, which leaves Discord stuck on "thinking"

Model names: ":cloud" names (gemma4:cloud) only work through the local Ollama app. On https://ollama.com
use the names from https://ollama.com/api/tags (for example gemma4:31b, glm-5.3-flash).
"""
import logging
import os

from langchain_core.language_models import BaseChatModel

from ..config import settings

DEFAULT_MODEL = "glm-5.3-flash:cloud"
log = logging.getLogger(__name__)


def timeout_s(var: str, default: float) -> float:
    try:
        return max(5.0, float(os.environ.get(var) or default))
    except ValueError:
        return default


def chat_timeout_s() -> float:
    return timeout_s("LLM_TIMEOUT_S", 60)


def vision_timeout_s() -> float:
    return timeout_s("VISION_TIMEOUT_S", 90)


def _reasoning():
    r = os.environ.get("LLM_REASONING", "low").strip().lower()
    return {"false": False, "true": True, "none": None}.get(r, r)


def create_chat_model(model: str | None = None, max_tokens: int = 800, timeout: float | None = None) -> BaseChatModel:
    provider = (settings.llm_provider or "ollama").strip().lower()
    name = model or settings.llm_model or DEFAULT_MODEL
    if provider != "ollama":
        raise ValueError(f"LLM_PROVIDER={provider!r} isn't supported yet; use 'ollama'")
    from langchain_ollama import ChatOllama
    kwargs = {}
    client = {"timeout": timeout or chat_timeout_s()}  # never wait forever for a reply
    base = os.environ.get("OLLAMA_BASE_URL")
    if base:
        kwargs["base_url"] = base
        key = os.environ.get("OLLAMA_API_KEY")
        if key and base.startswith("https://"):
            client["headers"] = {"Authorization": f"Bearer {key}"}
        if "ollama.com" in base and name.endswith(":cloud"):
            log.warning("Model %r won't be found on %s: ':cloud' names only work through the local Ollama app. "
                        "Use a name from https://ollama.com/api/tags, for example gemma4:31b.", name, base)
    return ChatOllama(model=name, temperature=0, reasoning=_reasoning(), num_predict=max_tokens,
                      client_kwargs=client, **kwargs)


def create_vision_model() -> BaseChatModel:
    return create_chat_model(os.environ.get("VISION_MODEL") or None, max_tokens=2000, timeout=vision_timeout_s())
