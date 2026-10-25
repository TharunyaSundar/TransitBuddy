"""Group departure negotiation: find a departure time that works for everyone, or the best compromise.

Each participant has a departure window (earliest, latest) in minutes. The ideal time is the start of the
common window. When there's no common window, the compromise is the time that suits the most people, and
the reply says who would have to move and by how many minutes; nothing is forced.
"""
from .availability import END_OF_DAY
from .timeutil import display, from_minutes


def window_text(earliest: int | None, latest: int) -> str:
    """A departure window for replies: '8:00 AM-8:25 AM', 'by 7:30 AM' or 'from 3:10 PM'."""
    if earliest is None:
        return f"by {display(from_minutes(latest))}"
    if latest >= END_OF_DAY:
        return f"from {display(from_minutes(earliest))}"
    return f"{display(from_minutes(earliest))}-{display(from_minutes(latest))}"


def negotiate(windows: dict[str, tuple[int | None, int, list[str]]]) -> dict:
    """windows: {user_id: (earliest or None, latest, reasons)}. Returns a decision dict (times as HH:mm).

    An unknown earliest time means "whenever"; it never becomes midnight. If nobody's earliest time is
    known, the proposal is the latest departure that still works for everyone ("leave by").
    """
    if not windows:
        return {"status": "no_participants"}
    bad = {u: w for u, w in windows.items() if w[0] is not None and w[0] > w[1]}
    if bad:
        return {"status": "impossible_for_some",
                "participants": {u: f"can't leave until {display(from_minutes(w[0]))} but would have to leave by "
                                    f"{display(from_minutes(w[1]))}" for u, w in bad.items()}}
    known = [w[0] for w in windows.values() if w[0] is not None]
    hi = min(w[1] for w in windows.values())
    if not known:
        return {"status": "agreed", "proposedDeparture": from_minutes(hi), "leaveBy": True,
                "commonWindow": None, "slackMinutes": None}
    lo = max(known)
    if lo <= hi:
        return {"status": "agreed", "proposedDeparture": from_minutes(lo),
                "commonWindow": f"{from_minutes(lo)}-{from_minutes(hi)}",
                "slackMinutes": hi - lo}
    # no common window: try each window edge, keep the time that fits the most people, then the least movement
    candidates = sorted(set(known) | {w[1] for w in windows.values()})

    def fits(w, t):
        return (w[0] is None or w[0] <= t) and t <= w[1]

    best = None
    for t in candidates:
        ok = [u for u, w in windows.items() if fits(w, t)]
        moves = {u: (w[0] - t if w[0] is not None and t < w[0] else t - w[1])
                 for u, w in windows.items() if u not in ok}
        key = (len(ok), -sum(moves.values()), -t)
        if best is None or key > best[0]:
            best = (key, t, ok, moves)
    _, t, ok, moves = best
    conflicts = []
    for u, mins in moves.items():
        w = windows[u]
        side = "leave earlier than" if w[0] is not None and t < w[0] else "leave later than"
        conflicts.append({"discord_user_id": u, "minutesToMove": mins,
                          "detail": f"would have to {side} they said ({window_text(w[0], w[1])}) by {mins} min",
                          "reasons": w[2]})
    return {"status": "conflict", "compromiseDeparture": from_minutes(t), "fitsEveryoneExcept": conflicts,
            "fits": ok}
