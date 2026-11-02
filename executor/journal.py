"""Durable transaction journal: one JSON line per event, fsync'd before the next action.

Key = household id + period. The journal is what survives a crash. It never replaces
reading the screen: after a restart it only says what the executor INTENDED and SENT.
"""
import json, os, time

ROOT = os.environ.get("RDP_JOURNAL_DIR", os.path.join(os.path.dirname(__file__), "..", "runs", "journal"))


class Journal:
    def __init__(self, household_id, period):
        os.makedirs(ROOT, exist_ok=True)
        self.path = os.path.join(ROOT, f"{household_id}_{period}.jsonl")

    def events(self):
        if not os.path.exists(self.path):
            return []
        with open(self.path) as f:
            return [json.loads(l) for l in f if l.strip()]

    def write(self, event, **data):
        rec = {"t": round(time.time(), 3), "event": event, **data}
        with open(self.path, "a") as f:
            f.write(json.dumps(rec) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return rec

    def open_submission(self):
        """The last SUBMIT_INTENT that has no conclusion after it, or None."""
        pending = None
        for e in self.events():
            if e["event"] == "SUBMIT_INTENT":
                pending = e
            elif e["event"] in ("CONFIRMED_AND_VERIFIED", "RECOVERED_VERIFIED", "OPERATOR_CLEARED"):
                pending = None
        return pending

    def last(self):
        ev = self.events()
        return ev[-1] if ev else None
