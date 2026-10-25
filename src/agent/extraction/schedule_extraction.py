"""Multimodal schedule extraction: screenshot -> vision model -> JSON -> normalized Course list + warnings.

The result is always returned for confirmation; nothing is saved here.
"""
import asyncio
import base64
import json
import logging
import re
import time

import httpx

from langchain_core.messages import HumanMessage

from ..llm import vision_timeout_s
from ..logic.schedule import normalize_schedule

log = logging.getLogger(__name__)

PROMPT = """Read this class schedule screenshot. Return ONLY JSON, no prose, in this shape:
{"semester": "Fall 2026 or empty if not shown",
 "courses": [{"course_code": "CSE 110", "course_name": "Principles of Programming", "section": "12345 or empty",
              "meeting_patterns": [{"days": "Mon/Wed/Fri", "start_time": "9:00 AM", "end_time": "9:50 AM"}],
              "location": "Tempe - ISTB4 101"}]}
Rules:
- Copy text exactly as shown. Read each block's own time text; don't infer it from where the block sits.
- start_time and end_time each hold ONE time with AM/PM. "10:00 - 10:50 AM" becomes "start_time": "10:00 AM",
  "end_time": "10:50 AM".
- One entry per course. A lab, recitation or discussion is its own entry with the same course_code and
  "Lab" (etc.) in course_name, e.g. {"course_code": "CSE 110", "course_name": "Introduction to Programming Lab"}.
- Group days into one pattern only when the times are identical. If Tuesday is 2:00-2:15 PM and Thursday is
  1:00-2:15 PM, write two patterns: {"days": "Tue", ...} and {"days": "Thu", ...}.
- Only classes. Skip study time, meals, meetings, clubs, work shifts, gym, events and review sessions.
- Online classes: location "Online" and no meeting_patterns if no times are shown.
- Never guess a value you can't read: leave it empty. If the image is not a class schedule, return
  {"semester": "", "courses": []}."""


def image_data_url(image_input: bytes | str, mime_type: str) -> str:
    if isinstance(image_input, (bytes, bytearray)):
        return f"data:{mime_type};base64,{base64.b64encode(image_input).decode()}"
    s = str(image_input)
    if s.startswith(("data:", "http://", "https://")):
        return s
    return f"data:{mime_type};base64,{s}"  # already base64


def parse_json(text: str) -> dict:
    """Pull the JSON object out of a model reply (handles ```json fences and stray prose)."""
    s = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
    if fence:
        s = fence.group(1)
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the model reply")
    return json.loads(s[start:end + 1])


def _content_text(content) -> str:
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content or ""


def _failed(message: str) -> dict:
    return {"extracted_schedule": {"semester": "", "courses": []}, "validation_warnings": [message],
            "confirmation_required": True}


async def extract_schedule(model, image_input: bytes | str, mime_type: str, timeout: float | None = None) -> dict:
    """Returns a ScheduleExtractionResult. Gives up after `timeout` seconds instead of waiting forever."""
    msg = HumanMessage(content=[{"type": "text", "text": PROMPT},
                                {"type": "image_url", "image_url": image_data_url(image_input, mime_type)}])
    limit = timeout or vision_timeout_s()
    started = time.monotonic()
    try:
        reply = await asyncio.wait_for(model.ainvoke([msg]), timeout=limit + 1)  # backstop for the client timeout
    except (asyncio.TimeoutError, httpx.TimeoutException):
        log.warning("schedule extraction timed out after %.0fs (model %s)", time.monotonic() - started,
                    getattr(model, "model", "?"))
        return _failed(f"Reading the screenshot took too long (over {limit:.0f} seconds). Please try again in a "
                       "minute, or send a smaller screenshot.")
    except Exception as e:  # model or connection error: say so, never guess
        log.warning("schedule extraction failed after %.1fs (model %s): %s: %s", time.monotonic() - started,
                    getattr(model, "model", "?"), type(e).__name__, e)
        return _failed(f"I couldn't read that screenshot right now ({type(e).__name__}). Please try again in a "
                       "minute, or type your classes.")
    log.info("schedule extraction took %.1fs (model %s)", time.monotonic() - started, getattr(model, "model", "?"))
    try:
        raw = parse_json(_content_text(reply.content))
    except Exception as e:  # unreadable output: ask for a clearer image
        return _failed(f"I couldn't read that screenshot ({type(e).__name__}). Please send a clearer one, or "
                       "type your classes.")
    schedule, warnings = normalize_schedule(raw)
    return {"extracted_schedule": schedule, "validation_warnings": warnings, "confirmation_required": True}
