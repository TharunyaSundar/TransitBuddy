"""LLM setup. Provider and model come from the environment (.env.example):

LLM_PROVIDER   ollama (default; the only provider wired up so far)
LLM_MODEL      default glm-5.3-flash:cloud (tool calling and vision, low token use)
VISION_MODEL   model for screenshot extraction (default: LLM_MODEL)
LLM_REASONING  thinking effort: low (default), high, false
OLLAMA_BASE_URL, OLLAMA_API_KEY  only to call ollama.com directly instead of the local Ollama app
"""
import os

from langchain_core.language_models import BaseChatModel

DEFAULT_MODEL = "glm-5.3-flash:cloud"


def _reasoning():
    r = os.environ.get("LLM_REASONING", "low").strip().lower()
    return {"false": False, "true": True, "none": None}.get(r, r)


def create_chat_model(model: str | None = None, max_tokens: int = 800) -> BaseChatModel:
    provider = (os.environ.get("LLM_PROVIDER") or "ollama").strip().lower()
    name = model or os.environ.get("LLM_MODEL") or DEFAULT_MODEL
    if provider != "ollama":
        raise ValueError(f"LLM_PROVIDER={provider!r} isn't supported yet; use 'ollama'")
    from langchain_ollama import ChatOllama
    kwargs = {}
    base = os.environ.get("OLLAMA_BASE_URL")
    if base:
        kwargs["base_url"] = base
        key = os.environ.get("OLLAMA_API_KEY")
        if key and base.startswith("https://"):
            kwargs["client_kwargs"] = {"headers": {"Authorization": f"Bearer {key}"}}
    return ChatOllama(model=name, temperature=0, reasoning=_reasoning(), num_predict=max_tokens, **kwargs)


def create_vision_model() -> BaseChatModel:
    return create_chat_model(os.environ.get("VISION_MODEL") or None, max_tokens=2000)
