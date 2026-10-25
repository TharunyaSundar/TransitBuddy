from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def require(**fields: Any) -> None:
    """Raise ValueError if any keyword value is None or a blank string."""
    for name, value in fields.items():
        if value is None or (isinstance(value, str) and value.strip() == ""):
            raise ValueError(f"{name} is required.")


def strip_id(doc: dict | None) -> dict | None:
    """Drop Mongo's _id so documents match the shared contracts."""
    if doc is None:
        return None
    doc = dict(doc)
    doc.pop("_id", None)
    return doc
