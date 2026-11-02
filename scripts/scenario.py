#!/usr/bin/env python3
"""Replay one test scenario end to end and write its exact result.

    venv/bin/python scripts/scenario.py recovery [--record]
    venv/bin/python scripts/scenario.py ambiguous|popup|focus|move [--record]

The scenario plays the OPERATOR and the FAULTS (pause, edits, kill -9, slow index, popup, focus
loss, window move). The executor is started as a separate process and is never told what will
happen. Results: runs/scenarios/<scenario>-<time>.json (+ .events.jsonl, + raw video if --record).
"""
import json, os, signal, subprocess, sys, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PY = os.path.join(ROOT, "venv", "bin", "python")
TX = os.path.join(ROOT, "data", "DEMO-HH-014_2026-11.json")
JOURNAL = os.path.join(ROOT, "runs", "journal", "DEMO-HH-014_2026-11.jsonl")
OUT = os.path.join(ROOT, "runs", "scenarios")

FAULTS = {
    "stop_pause": {"save_latency": 2.5, "index_delay": 0},
    "pause_at_intent": {"save_latency": 2.5, "index_delay": 0},
    "pause_save_wait": {"save_latency": 6.0, "index_delay": 0},
    "intent_crash_clear": {"save_latency": 2.5, "index_delay": 0},
    "torn_after_save": {"save_latency": 2.5, "index_delay": 0},
    "torn_only": {"save_latency": 2.5, "index_delay": 0},
    "midfield_edit": {"save_latency": 2.5, "index_delay": 0},
    "recovery": {"save_latency": 2.5, "index_delay": 0},
    "ambiguous": {"save_latency": 2.5, "index_delay": 600, "quiet_save": True},
    "popup": {"save_latency": 2.5, "index_delay": 0, "popup_on_income_tab": True},
    "focus": {"save_latency": 2.5, "index_delay": 0},
    "move": {"save_latency": 2.5, "index_delay": 0},
}


class Scenario:
    def __init__(self, name, record):
        self.name, self.record = name, record
        self.stamp = time.strftime("%Y%m%d-%H%M%S")
        os.makedirs(OUT, exist_ok=True)
        self.base = os.path.join(OUT, f"{name}-{self.stamp}")
        self.ev = open(self.base + ".events.jsonl", "w")
        self.procs = []

    def event(self, who, msg):
        rec = {"t": round(time.time(), 3), "who": who, "msg": msg}
        self.ev.write(json.dumps(rec) + "\n")
        self.ev.flush()
        print(time.strftime("%H:%M:%S"), f"<{who}>", msg, flush=True)

    def sh(self, *cmd, **kw):
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)

    def journal_events(self):
        if not os.path.exists(JOURNAL):
            return []
        out = []
        with open(JOURNAL) as f:
            for l in f:
                if l.strip():
                    try:
                        out.append(json.loads(l))
                    except ValueError:
                        out.append({"event": "_UNREADABLE", "raw": l.strip()[:120]})
        return out

    def wait_journal(self, pred, timeout=120):
        t0 = time.time()
        while time.time() - t0 < timeout:
            for e in self.journal_events():
                if pred(e):
                    return e
            time.sleep(0.05)
        raise TimeoutError("journal condition not met")

    def wait_out(self, path, text, timeout=60, start=0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            with open(path) as f:
                if text in f.read()[start:]:
                    return
            time.sleep(0.1)
        raise TimeoutError(f"'{text}' not seen")

    def start_executor(self, label, env=None):
        out = f"{self.base}.{label}.out"
        f = open(out, "w")
        p = subprocess.Popen([PY, "-u", "-m", "executor.run", TX], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
                             env={**os.environ, **(env or {})})
        self.procs.append(p)
        self.event("bench", f"executor started ({label}), pid {p.pid}")
        return p, out

    def ctl(self, cmd):
        self.sh(PY, "-m", "executor.control", cmd)
        self.event("operator", {"pause": "Pause pressed", "resume": "Resume pressed", "stop": "Stop pressed"}[cmd])

    def op(self, *args):
        r = self.sh(PY, "-m", "executor.operator", *args)
        self.event("operator", r.stdout.strip() or r.stderr.strip()[-200:])

    def host_count(self):
        r = self.sh(os.path.join(ROOT, "scripts", "host_check.sh"))
        return json.loads(r.stdout)

    def run(self):
        r = self.sh(os.path.join(ROOT, "scripts", "reset.sh"), json.dumps(FAULTS[self.name]))
        self.event("bench", r.stdout.strip())
        if self.record:
            self.video = f"{self.name}-{self.stamp}.mkv"
            subprocess.Popen(["docker", "exec", "rdp-demo-screen", "sh", "-c",
                              f"date +%s.%N > /rec/{self.video[:-4]}.t0; exec ffmpeg -loglevel error -f x11grab -video_size 1280x860 -framerate 10 -i :0 "
                              f"-c:v libx264 -preset veryfast -crf 18 -pix_fmt yuv420p /rec/{self.video}"])
            time.sleep(1.0)
            self.event("bench", f"recording started: runs/raw/{self.video}")
        sys.path.insert(0, ROOT)
        from executor.screen import Screen
        scr = Screen()
        fr = scr.client_window().query_tree().parent.get_geometry()
        self.frame = [fr.x, fr.y, fr.width, fr.height]  # client window + its title bar, for the film crop
        try:
            result = getattr(self, "s_" + self.name)()
        finally:
            for p in self.procs:
                if p.poll() is None:
                    p.kill()
            if self.record:
                time.sleep(1.5)
                subprocess.run(["docker", "exec", "rdp-demo-screen", "sh", "-c",
                                "for p in /proc/[0-9]*; do grep -q '^ffmpeg' $p/cmdline 2>/dev/null && kill -INT ${p#/proc/}; done"])
                time.sleep(2)
        result["frame"] = self.frame
        if self.record:
            result["video"] = self.video
        result.update({"scenario": self.name, "faults": FAULTS[self.name], "host_check": self.host_count(),
                       "journal": self.journal_events()})
        with open(self.base + ".json", "w") as f:
            json.dump(result, f, indent=1)
        self.event("bench", "independent host check: " + json.dumps(result["host_check"]))
        return result

    def last_summary(self, out):
        with open(out) as f:
            lines = [l for l in f.read().splitlines() if l.startswith("{")]
        return json.loads(lines[-1]) if lines else None

    # ------------------------------------------------------------------ scenarios
    def s_recovery(self):
        """Pause + operator edit + resume, then kill -9 right after Save is sent, then restart."""
        p, out = self.start_executor("first")
        self.wait_journal(lambda e: e["event"] == "FIELD_SET" and e["field"] == "monthly_wages")
        self.ctl("pause")
        self.wait_out(out, "Paused by operator")
        time.sleep(1.0)
        self.op("set", "Monthly wages", "1865.00")
        time.sleep(1.2)
        self.ctl("resume")
        self.wait_journal(lambda e: e["event"] == "SAVE_CLICK_SENT", timeout=90)
        p.send_signal(signal.SIGKILL)
        p.wait()
        self.event("bench", "executor process killed with SIGKILL right after the Save click, before any confirmation was read")
        time.sleep(4)
        p2, out2 = self.start_executor("restart")
        p2.wait(timeout=180)
        return {"first_exit": p.returncode, "restart_exit": p2.returncode, "restart_summary": self.last_summary(out2)}

    def s_ambiguous(self):
        """Save is accepted but the list lags and no confirmation is shown."""
        p, out = self.start_executor("only")
        p.wait(timeout=240)
        return {"exit": p.returncode, "summary": self.last_summary(out)}

    def s_popup(self):
        """An unexpected notice opens on the Income tab; the operator answers it, then resumes."""
        p, out = self.start_executor("only")
        self.wait_out(out, "Assistance required", timeout=240)
        time.sleep(1.5)
        self.op("click", "Continue")
        time.sleep(1.0)
        self.ctl("resume")
        p.wait(timeout=240)
        return {"exit": p.returncode, "summary": self.last_summary(out)}

    def s_focus(self):
        """Another local window takes keyboard focus mid-entry."""
        p, out = self.start_executor("only")
        self.wait_journal(lambda e: e["event"] == "FIELD_SET" and e["field"] == "effective_date")
        h = subprocess.Popen([PY, "-m", "executor.operator", "steal-focus", "6"], cwd=ROOT)
        self.event("operator", "opens another local window, which takes keyboard focus for 6 s")
        self.wait_out(out, "Focus left", timeout=30)
        h.wait()
        self.op("focus")
        time.sleep(1)
        self.ctl("resume")
        p.wait(timeout=240)
        return {"exit": p.returncode, "summary": self.last_summary(out)}

    def s_move(self):
        """The client window is moved on the local screen mid-run."""
        p, out = self.start_executor("only")
        self.wait_journal(lambda e: e["event"] == "FIELD_SET" and e["field"] == "effective_date")
        from Xlib import display as xd
        d = xd.Display(os.environ.get("RDP_X_DISPLAY", "127.0.0.1:99"))
        sys.path.insert(0, ROOT)
        from executor.screen import Screen
        w = Screen().client_window()
        w.configure(x=200, y=100)
        d.sync()
        self.event("operator", "moves the remote desktop window to (200, 100) on the local screen")
        p.wait(timeout=240)
        w.configure(x=self.frame[0], y=self.frame[1])
        d.sync()
        return {"exit": p.returncode, "summary": self.last_summary(out)}

    def s_stop_pause(self):
        """Operator pauses mid-entry, then presses Stop while paused."""
        p, out = self.start_executor("only")
        self.wait_journal(lambda e: e["event"] == "FIELD_SET" and e["field"] == "effective_date")
        self.ctl("pause")
        self.wait_out(out, "Paused by operator")
        time.sleep(1.0)
        self.ctl("stop")
        p.wait(timeout=60)
        self.sh(PY, "-m", "executor.control", "resume")
        return {"exit": p.returncode, "summary": self.last_summary(out)}

    def s_pause_at_intent(self):
        """Pause pressed the moment the submit intent is journaled (the click is already decided)."""
        p, out = self.start_executor("only")
        self.wait_journal(lambda e: e["event"] == "SUBMIT_INTENT", timeout=120)
        self.ctl("pause")
        self.wait_out(out, "Paused by operator")
        time.sleep(1.0)
        self.ctl("resume")
        p.wait(timeout=180)
        return {"exit": p.returncode, "summary": self.last_summary(out)}

    def s_pause_save_wait(self):
        """Pause pressed while the application is still saving (slow save)."""
        p, out = self.start_executor("only")
        self.wait_journal(lambda e: e["event"] == "SAVE_CLICK_SENT", timeout=120)
        time.sleep(1.0)
        self.ctl("pause")
        self.wait_out(out, "Paused by operator")
        time.sleep(7.0)
        self.ctl("resume")
        p.wait(timeout=180)
        return {"exit": p.returncode, "summary": self.last_summary(out)}

    def s_intent_crash_clear(self):
        """Crash between the journaled intent and the click (test hook). Restart cannot conclude;
        the operator checks the application, clears the case, and a third run completes it."""
        p, out = self.start_executor("first", env={"RDP_TEST_FAULT": "exit_before_click"})
        p.wait(timeout=180)
        self.event("bench", "executor exited (test hook) after journaling the intent, before the click")
        p2, out2 = self.start_executor("restart")
        p2.wait(timeout=180)
        hc = self.host_count()
        self.event("operator", f"checks the application by hand: {hc['records_on_host']} record(s); runs control clear")
        self.sh(PY, "-m", "executor.control", "clear", TX, "operator checked: no record saved")
        p3, out3 = self.start_executor("after_clear")
        p3.wait(timeout=180)
        return {"first_exit": p.returncode, "restart_summary": self.last_summary(out2),
                "summary": self.last_summary(out3), "restart_exit": p2.returncode, "after_clear_exit": p3.returncode}

    def _torn(self, text):
        with open(JOURNAL, "a") as f:
            f.write(text)
        self.event("bench", f"appended a torn journal line: {text[:40]!r}")

    def s_torn_after_save(self):
        """kill -9 right after the Save click, and the journal's last line is torn."""
        p, out = self.start_executor("first")
        self.wait_journal(lambda e: e["event"] == "SAVE_CLICK_SENT", timeout=120)
        p.send_signal(signal.SIGKILL)
        p.wait()
        self.event("bench", "executor process killed with SIGKILL right after the Save click")
        self._torn('{"t": 1793630000.1, "event": "CONFIRMATION_SE')
        time.sleep(4)
        p2, out2 = self.start_executor("restart")
        p2.wait(timeout=180)
        return {"first_exit": p.returncode, "restart_exit": p2.returncode, "restart_summary": self.last_summary(out2)}

    def s_torn_only(self):
        """The journal holds only a torn line: whether a Save was sent cannot be known from it."""
        os.makedirs(os.path.dirname(JOURNAL), exist_ok=True)
        self._torn('{"t": 1793630000.1, "event": "SUBMIT_IN')
        p, out = self.start_executor("only")
        p.wait(timeout=60)
        return {"exit": p.returncode, "summary": self.last_summary(out)}

    def s_midfield_edit(self):
        """Pause while Monthly benefits is being typed; the operator replaces the partial entry with 2;
        the executor asks instead of overwriting; the operator finishes with 275.00 and resumes."""
        p, out = self.start_executor("only")
        self.wait_out(out, "Entering Monthly benefits", timeout=120)
        time.sleep(1.0)  # lands after a few characters of 260.00 have been typed
        self.ctl("pause")
        self.wait_out(out, "Paused by operator")
        time.sleep(1.0)
        self.op("set", "Monthly benefits", "2")
        time.sleep(1.0)
        self.ctl("resume")
        self.wait_out(out, "which the agent did not type", timeout=60)
        time.sleep(1.0)
        self.op("set", "Monthly benefits", "275.00")
        time.sleep(1.0)
        self.ctl("resume")
        p.wait(timeout=180)
        return {"exit": p.returncode, "summary": self.last_summary(out)}


if __name__ == "__main__":
    s = Scenario(sys.argv[1], "--record" in sys.argv)
    res = s.run()
    keep = {k: v for k, v in res.items() if k != "journal"}
    print(json.dumps(keep, indent=1))
