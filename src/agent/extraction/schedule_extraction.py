"""Multimodal schedule extraction: screenshot -> vision model -> JSON -> normalized Course list + warnings.

The result is always returned for confirmation; nothing is saved here.
"""
import base64
import json
import re

from langchain_core.messages import HumanMessage

from ..logic.schedule import normalize_schedule

PROMPT = """Read this class schedule screenshot. Return ONLY JSON, no prose, in this shape:
{"semester": "Fall 2026 or empty if not shown",
 "courses": [{"courseCode": "CSE 110", "courseName": "Principles of Programming", "section": "12345 or empty",
              "meetingPatterns": [{"days": "Mon/Wed/Fri", "startTime": "9:00 AM", "endTime": "9:50 AM"}],
              "location": "Tempe - ISTB4 101"}]}
Copy text exactly as shown. One entry per course; add a pattern per distinct meeting time. Online classes:
location "Online" and no meetingPatterns if no times are shown. Never guess a value you can't read: leave it
empty. If the image is not a class schedule, return {"semester": "", "courses": []}."""


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


async def extract_schedule(model, image_input: bytes | str, mime_type: str) -> dict:
    """Returns a ScheduleExtractionResult."""
    msg = HumanMessage(content=[{"type": "text", "text": PROMPT},
                                {"type": "image_url", "image_url": image_data_url(image_input, mime_type)}])
    try:
        reply = await model.ainvoke([msg])
        raw = parse_json(_content_text(reply.content))
    except Exception as e:  # model error or unreadable output: ask for a clearer image, never guess
        return {"extractedSchedule": {"semester": "", "courses": []},
                "validationWarnings": [f"I couldn't read that screenshot ({type(e).__name__}). Please send a "
                                       "clearer one, or type your classes."],
                "confirmationRequired": True}
    schedule, warnings = normalize_schedule(raw)
    return {"extractedSchedule": schedule, "validationWarnings": warnings, "confirmationRequired": True}
