"""Group departure negotiation: find a departure time that works for everyone, or the best compromise.

Each participant has a departure window (earliest, latest) in minutes. The ideal time is the start of the
common window. When there's no common window, the compromise is the time that suits the most people, and
the reply says who would have to move and by how many minutes; nothing is forced.
"""
from .timeutil import display, from_minutes


def negotiate(windows: dict[str, tuple[int, int, list[str]]]) -> dict:
    """windows: {user_id: (earliest, latest, reasons)}. Returns a decision dict (times as HH:mm)."""
    if not windows:
        return {"status": "no_participants"}
    bad = {u: w for u, w in windows.items() if w[0] > w[1]}
    if bad:
        return {"status": "impossible_for_some",
                "participants": {u: f"earliest {from_minutes(w[0])} is after latest {from_minutes(w[1])}"
                                 for u, w in bad.items()}}
    lo = max(w[0] for w in windows.values())
    hi = min(w[1] for w in windows.values())
    if lo <= hi:
        return {"status": "agreed", "proposedDeparture": from_minutes(lo),
                "commonWindow": f"{from_minutes(lo)}-{from_minutes(hi)}",
                "slackMinutes": hi - lo}
    # no common window: try each window edge, keep the time that fits the most people, then the least movement
    candidates = sorted({w[0] for w in windows.values()} | {w[1] for w in windows.values()})
    best = None
    for t in candidates:
        fits = [u for u, w in windows.items() if w[0] <= t <= w[1]]
        moves = {u: (w[0] - t if t < w[0] else t - w[1]) for u, w in windows.items() if u not in fits}
        key = (len(fits), -sum(moves.values()), -t)
        if best is None or key > best[0]:
            best = (key, t, fits, moves)
    _, t, fits, moves = best
    conflicts = []
    for u, mins in moves.items():
        w = windows[u]
        side = "leave earlier than" if t < w[0] else "leave later than"
        conflicts.append({"discord_user_id": u, "minutesToMove": mins,
                          "detail": f"would have to {side} they said ({display(from_minutes(w[0]))}-"
                                    f"{display(from_minutes(w[1]))}) by {mins} min",
                          "reasons": w[2]})
    return {"status": "conflict", "compromiseDeparture": from_minutes(t), "fitsEveryoneExcept": conflicts,
            "fits": fits}
