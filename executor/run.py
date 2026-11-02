"""Attended executor: one prepared transaction, driven through the pixels of the RDP client window.

    python -m executor.run data/DEMO-HH-014_2026-11.json [--no-model]

Where things happen (for the engineers taking this over):
- input data ............ the JSON file given on the command line (prepared upstream)
- capture / input ....... executor/screen.py (local display only), every input goes through gate()
- reading the screen .... executor/ocr.py (Tesseract, local), executor/vision.py (local model, exceptions only)
- submission ............ ONLY in submit_save(): allowed once, after a full read-back, never in recovery
- crash survival ........ executor/journal.py: SUBMIT_INTENT is fsync'd BEFORE the click
- recovery .............. Runner.recover(): result unknown -> search, reopen, compare -> conclude or stop
"""
import json, os, re, sys, time
from . import ocr, control
from .journal import Journal
from .screen import Screen, WindowGone
from .vision import LocalVision, NoVision

FIELDS = [  # (key, tab, label on screen)
    ("members", "Household", "Members in household"),
    ("effective_date", "Household", "Effective date"),
    ("monthly_wages", "Income", "Monthly wages"),
    ("monthly_benefits", "Income", "Monthly benefits"),
]
LABEL = {k: l for k, _, l in FIELDS}

KNOWN_WORDS = set("""file edit view records help find household id search ready synthetic unit demo court new
recertification saved recertifications no for this listed period members in effective date monthly wages
benefits save cancel editing saving viewing close income record confirmation ok housing case manager
application listed record(s) 4b, 2a, 014 015""".split())

RUNS = os.path.join(os.path.dirname(__file__), "..", "runs")


class Paused(Exception):
    pass


class Stopped(Exception):
    pass


class FocusLost(Exception):
    pass


class Assistance(Exception):
    def __init__(self, code, msg, final=False):
        super().__init__(msg)
        self.code, self.msg, self.final = code, msg, final


class Runner:
    def __init__(self, tx_path, use_model=True):
        with open(tx_path) as f:
            tx = json.load(f)
        self.hh, self.period = tx["household_id"], tx["period"]
        self.prepared = dict(tx["values"])
        self.expected = dict(tx["values"])
        self.journal = Journal(self.hh, self.period)
        self.s = Screen()
        self.vision = LocalVision() if use_model else NoVision()
        self.run_id = time.strftime("%Y%m%d-%H%M%S")
        self.dir = os.path.join(RUNS, self.run_id)
        os.makedirs(os.path.join(self.dir, "shots"), exist_ok=True)
        self.logf = open(os.path.join(self.dir, "log.jsonl"), "a")
        self.typed, self.verified_fields = {}, set()
        self.precheck_done = False
        self.shot_n = 0
        self.inputs = 0

    # ------------------------------------------------------------------ log
    def log(self, kind, msg, shot=False, img=None):
        rec = {"t": round(time.time(), 3), "kind": kind, "msg": msg}
        if shot:
            self.shot_n += 1
            name = f"{self.shot_n:03d}.png"
            (img or self.s.capture()).save(os.path.join(self.dir, "shots", name))
            rec["shot"] = name
        self.logf.write(json.dumps(rec) + "\n")
        self.logf.flush()
        print(time.strftime("%H:%M:%S"), f"[{kind}]", msg, flush=True)

    # ------------------------------------------------------------------ the gate
    def gate(self):
        """Checked before EVERY key or click. Pause/stop win over any planned action."""
        c = control.get()
        if c == "stop":
            raise Stopped()
        if c == "pause":
            raise Paused()
        if not self.s.has_focus():
            control.put("pause")
            raise FocusLost()

    def click(self, x, y):
        self.gate()
        self.s.click(x, y)
        self.inputs += 1

    def type_text(self, text):
        for ch in text:
            self.gate()
            self.s.char(ch)
            self.inputs += 1
            time.sleep(0.09)

    def select_all(self):
        self.gate()
        self.s.key("a", ("Control_L",))
        self.inputs += 1

    # ------------------------------------------------------------------ seeing
    def look(self):
        img = self.s.capture()
        return img, ocr.words(img)

    def wait_for(self, cond, timeout, what, every=0.4):
        t0 = time.time()
        while time.time() - t0 < timeout:
            img, ws = self.look()
            if cond(img, ws):
                return img, ws
            self.gate()
            time.sleep(every)
        return None, None

    def has(self, ws, phrase):
        return ocr.find_phrase(ws, phrase) is not None

    def screen_kind(self, img, ws):
        txt = ocr.text_of(ws)
        unknown = [w.text for w in ws if re.search(r"[A-Za-z]{3,}", w.text)
                   and re.sub(r"[^\w()\-,]", "", w.text.lower()) not in KNOWN_WORDS
                   and not re.match(r"^[A-Z]+-[A-Z]+-\d+$|^R-\d{5}$", w.text.strip("|"))]
        if len(unknown) >= 3:
            return "unexpected"
        if "Record saved." in txt or ("Record" in txt and "Confirmation" in txt):
            return "save_confirmation"
        if self.has(ws, "Saved recertification") and self.has(ws, "Close"):
            return "record_view"
        if re.search(r"Recertification\s+\S+\s+Period", txt) and self.has(ws, "Save"):
            return "form"
        if self.has(ws, "Find household"):
            return "search"
        return "unexpected"

    def handle_unexpected(self, img):
        self.log("alert", "Screen does not match any known state. Asking the local vision model to classify it.", shot=True, img=img)
        label, secs, raw = self.vision.classify(img)
        self.journal.write("MODEL_CALL", model=self.vision.name, label=label, seconds=secs)
        self.log("model", f"Model call #{self.vision.calls} ({self.vision.name}, {secs} s): label '{label}'.")
        msgs = {
            "warning_or_notice": "An unexpected notice is open in the application. The agent will not answer it for you.",
            "error_message": "The application shows an error message. The agent will not dismiss it for you.",
            "login_or_session_prompt": "The application asks for a login or session action. That stays with you.",
        }
        raise Assistance("UNEXPECTED_SCREEN", msgs.get(label, "The screen is in a state this workflow does not cover.")
                         + " Resolve it in the window, then resume.")

    # ------------------------------------------------------------------ fields
    def field_box(self, img, ws, key):
        lb = ocr.find_phrase(ws, LABEL[key])
        if not lb:
            return None
        return ocr.white_box_right_of(img, lb)

    def read_field(self, img, ws, key, tries=3):
        """Value in one field, read from pixels. Unreadable -> fresh capture, up to 3 times -> None."""
        for i in range(tries):
            box = self.field_box(img, ws, key)
            val = None if box is None else ocr.read_box(img, box)
            if val is not None:
                return val
            time.sleep(0.3)
            img, ws = self.look()
        return None

    def open_tab(self, tab):
        first = next(l for k, t, l in FIELDS if t == tab)
        img, ws = self.look()
        if self.has(ws, first):
            return img, ws
        b = next((w for w in ws if w.text == tab and w.y > 100), None)
        if not b:
            raise Assistance("TAB_NOT_FOUND", f"Tab '{tab}' is not visible on screen.")
        self.click(b.cx, b.cy)
        img, ws = self.wait_for(lambda i, w: self.has(w, first), 6, f"tab {tab}")
        if img is None:
            img, ws = self.look()
            if self.screen_kind(img, ws) == "unexpected":
                self.handle_unexpected(img)
            raise Assistance("TAB_NOT_OPEN", f"Tab '{tab}' did not open within 6 s.")
        if self.screen_kind(img, ws) == "unexpected":
            self.handle_unexpected(img)
        return img, ws

    def fill_form(self):
        for tab in ("Household", "Income"):
            img, ws = self.open_tab(tab)
            for key, t, label in FIELDS:
                if t != tab:
                    continue
                cur = self.read_field(img, ws, key)
                exp = self.expected[key]
                if cur == exp:
                    if key not in self.verified_fields:
                        self.verified_fields.add(key)
                        self.log("check", f"{label}: screen reads {cur}, matches.")
                    continue
                if cur is None:
                    raise Assistance("UNREADABLE", f"{label} cannot be read reliably from the screen.")
                if key in self.typed and cur != self.typed[key]:
                    time.sleep(0.7)  # confirm on a second, later capture before calling it a change
                    img, ws = self.look()
                    cur = self.read_field(img, ws, key)
                    if cur == self.typed[key]:
                        continue
                if key in self.typed and cur != self.typed[key]:
                    self.log("warn", f"{label} changed on screen by the operator: entered {self.typed[key]}, now {cur}. "
                                     f"Kept, not overwritten.", shot=True, img=img)
                    self.journal.write("OPERATOR_VALUE", field=key, entered=self.typed[key], on_screen=cur)
                    self.expected[key] = cur
                    self.typed[key] = cur
                    self.verified_fields.add(key)
                    continue
                if cur and not exp.startswith(cur):
                    raise Assistance("UNEXPECTED_VALUE", f"{label} already holds a value the agent did not enter.")
                box = self.field_box(img, ws, key)
                self.log("action", f"Entering {label}: {exp}")
                self.click(box[0] + box[2] - 8, box[1] + box[3] // 2)
                time.sleep(0.25)
                self.select_all()
                self.type_text(exp)
                time.sleep(0.4)
                img, ws = self.look()
                got = self.read_field(img, ws, key)
                if got != exp:
                    raise Assistance("READBACK_MISMATCH", f"{label}: typed {exp}, screen reads {got}.")
                self.typed[key] = exp
                self.verified_fields.add(key)
                self.journal.write("FIELD_SET", field=key, value=exp)
                self.log("check", f"{label}: read back {got}, matches.")

    def final_review(self):
        seen = {}
        for tab in ("Household", "Income"):
            img, ws = self.open_tab(tab)
            for key, t, _ in FIELDS:
                if t == tab:
                    seen[key] = self.read_field(img, ws, key)
        bad = {k: v for k, v in seen.items() if v != self.expected[k]}
        if bad:
            raise Assistance("REVIEW_MISMATCH", "Final read-back differs: " + ", ".join(f"{LABEL[k]}={v}" for k, v in bad.items()))
        self.log("check", "Final read-back: all 4 values on screen match the expected values.", shot=True)
        return seen

    # ------------------------------------------------------------------ search & records
    def search(self):
        img, ws = self.look()
        kind = self.screen_kind(img, ws)
        if kind == "unexpected":
            self.handle_unexpected(img)
        if kind != "search":
            raise Assistance("NOT_ON_SEARCH", f"Expected the search screen, found '{kind}'.")
        lb = ocr.find_phrase(ws, "Household ID")
        box = ocr.white_box_right_of(img, lb)
        self.click(box[0] + box[2] - 8, box[1] + box[3] // 2)
        time.sleep(0.2)
        self.select_all()
        self.type_text(self.hh)
        b = ocr.find_phrase(ws, "Search")
        self.click(b[0] + b[2] // 2, b[1] + b[3] // 2)
        img, ws = self.wait_for(lambda i, w: self.has(w, "Saved recertifications") and
                                (self.has(w, "listed") or self.has(w, "No saved records")), 10, "search results")
        if img is None:
            raise Assistance("SEARCH_TIMEOUT", "Search results did not appear within 10 s.")
        if self.hh not in ocr.text_of(ws):
            raise Assistance("WRONG_HOUSEHOLD", f"Result does not show {self.hh}.")
        return img, ws

    def rows_for_period(self, ws):
        rows = []
        for w in ws:
            m = re.match(r"^R-\d{5}$", w.text)
            if not m:
                continue
            same = next(r for r in ocr.lines(ws) if w in r)
            line = " ".join(x.text for x in same)
            if f"Period {self.period}" in line:
                view = next((x for x in same if x.text == "View"), None)
                rows.append((w.text, view))
        return rows

    def open_and_read(self, number, view):
        self.click(view.cx, view.cy)
        img, ws = self.wait_for(lambda i, w: self.has(w, "Saved recertification") and number in ocr.text_of(w), 8, "record view")
        if img is None:
            raise Assistance("RECORD_NOT_OPEN", f"Record {number} did not open.")
        vals = {k: self.read_field(img, ws, k) for k, _, _ in FIELDS}
        idbox = ocr.white_box_right_of(img, ocr.find_phrase(ws, "Household ID"))
        hh_on_screen = ocr.read_box(img, idbox, "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-")
        return img, ws, vals, hh_on_screen

    def close_record(self, ws):
        b = ocr.find_phrase(ws, "Close")
        self.click(b[0] + b[2] // 2, b[1] + b[3] // 2)
        self.wait_for(lambda i, w: self.has(w, "Saved recertifications"), 8, "back to search")

    def matching_records(self, rows):
        """Reopen every record for this household and period; return those whose values match."""
        found = []
        for number, view in rows:
            img, ws = self.look()
            row = [r for r in self.rows_for_period(ws) if r[0] == number]
            if not row:
                continue
            img, ws, vals, hh = self.open_and_read(number, row[0][1])
            diff = {k: v for k, v in vals.items() if v != self.expected[k]}
            if hh == self.hh and not diff:
                self.log("check", f"{number} reopened: household {hh}, period {self.period}, "
                                  f"4 of 4 values match the submitted values.", shot=True, img=img)
                found.append(number)
            else:
                self.log("warn", f"{number} reopened: differs on " + ", ".join(LABEL[k] for k in diff), shot=True, img=img)
            self.close_record(ws)
        return found

    # ------------------------------------------------------------------ submission
    def submit_save(self, review):
        if self.journal.open_submission():
            raise Assistance("SUBMIT_BLOCKED", "Journal holds an unconcluded submission. Refusing to submit again.")
        intent = self.journal.write("SUBMIT_INTENT", run=self.run_id, values=self.expected, read_back=review)
        self.log("action", "Submit intent written to the journal (fsync) before clicking Save.")
        img, ws = self.look()
        b = ocr.find_phrase(ws, "Save")
        self.click(b[0] + b[2] // 2, b[1] + b[3] // 2)
        self.journal.write("SAVE_CLICK_SENT", intent_t=intent["t"])
        self.log("action", "Save clicked. Waiting for the application's answer.")
        return intent

    def after_save(self):
        img, ws = self.wait_for(lambda i, w: self.screen_kind(i, w) != "form", 20, "save answer", every=0.3)
        if img is None:
            self.log("warn", "No answer from the application within 20 s. Result unknown.", shot=True)
            return self.recover(in_run=True)
        kind = self.screen_kind(img, ws)
        if kind != "save_confirmation":
            if kind == "unexpected":
                self.handle_unexpected(img)
            self.log("warn", f"After Save the screen shows '{kind}', not a confirmation. Result unknown.", shot=True, img=img)
            return self.recover(in_run=True)
        m = re.search(r"R-\d{5}", ocr.text_of(ws))
        number = m.group(0) if m else None
        self.log("info", f"Confirmation box shows {number}. Not trusted alone: reopening the record.", shot=True, img=img)
        self.journal.write("CONFIRMATION_SEEN", number=number)
        b = ocr.find_phrase(ws, "OK")
        self.click(b[0] + b[2] // 2, b[1] + b[3] // 2)
        img, ws = self.wait_for(lambda i, w: self.has(w, "Saved recertifications"), 8, "search after OK")
        rows = [r for r in self.rows_for_period(ws) if r[0] == number]
        found = self.matching_records(rows)
        if found:
            self.journal.write("CONFIRMED_AND_VERIFIED", number=found[0])
            return "COMPLETED_VERIFIED", found[0]
        raise Assistance("SAVED_NOT_VERIFIED", f"Confirmation {number} shown but the record could not be verified.", final=True)

    # ------------------------------------------------------------------ recovery
    def recover(self, in_run=False):
        """Result of a Save is unknown. Find out from the screen; never submit again."""
        intent = self.journal.open_submission()
        self.expected = dict(intent["values"])
        self.journal.write("RECOVERY_START", intent_t=intent["t"])
        if not in_run:
            self.log("alert", "Save sent. Result unknown. Checking existing record.", shot=True)
            self.log("info", f"Journal: submit intent at {time.strftime('%H:%M:%S', time.localtime(intent['t']))} "
                             f"by run {intent['run']}, Save click sent, no confirmation read. Submitting is disabled.")
        img, ws = self.look()
        kind = self.screen_kind(img, ws)
        if kind == "save_confirmation":
            m = re.search(r"R-\d{5}", ocr.text_of(ws))
            self.log("info", f"A confirmation box is on screen ({m.group(0) if m else 'no number'}). "
                             "Treated as a hint only; closing it and searching.", shot=True, img=img)
            b = ocr.find_phrase(ws, "OK")
            self.click(b[0] + b[2] // 2, b[1] + b[3] // 2)
            img, ws = self.wait_for(lambda i, w: self.screen_kind(i, w) != "save_confirmation", 6, "box closed")
            kind = self.screen_kind(img, ws)
        elif kind == "form":
            self.log("info", "The form is still on screen. Leaving it with Cancel (nothing is submitted).", shot=True, img=img)
            b = ocr.find_phrase(ws, "Cancel")
            self.click(b[0] + b[2] // 2, b[1] + b[3] // 2)
            img, ws = self.wait_for(lambda i, w: self.has(w, "Find household"), 8, "search")
            kind = "search" if img is not None else "unexpected"
        if kind == "unexpected":
            self.handle_unexpected(img)
        attempts, wait = 3, 5
        t_first = time.time()
        for i in range(1, attempts + 1):
            img, ws = self.search()
            rows = self.rows_for_period(ws)
            self.log("check", f"Search {i}/{attempts}: {len(rows)} record(s) for {self.hh}, period {self.period}.", shot=True, img=img)
            if rows:
                found = self.matching_records(rows)
                if len(found) == 1:
                    self.journal.write("RECOVERED_VERIFIED", number=found[0], searches=i)
                    return "RECOVERED_VERIFIED", found[0]
                if len(found) > 1:
                    raise Assistance("DUPLICATE_ON_SCREEN", f"{len(found)} records match: " + ", ".join(found), final=True)
                raise Assistance("NO_MATCHING_RECORD", "Records exist for the period but none matches the submitted values.", final=True)
            if i < attempts:
                time.sleep(wait)
        raise Assistance("RESULT_UNKNOWN", f"Save was sent, but no record is visible after {attempts} searches over "
                                           f"{round(time.time() - t_first)} s. An empty search does not prove nothing was saved. "
                                           "Not submitting again. Please check the application.", final=True)

    # ------------------------------------------------------------------ main flow
    def normal(self):
        img, ws = self.look()
        kind = self.screen_kind(img, ws)
        if kind == "unexpected":
            self.handle_unexpected(img)
        if kind == "search" or not self.precheck_done:
            if kind != "search":
                raise Assistance("NOT_ON_SEARCH", f"Start from the search screen (found '{kind}').")
            if not self.precheck_done:
                img, ws = self.search()
                rows = self.rows_for_period(ws)
                if rows:
                    found = self.matching_records(rows)
                    if found:
                        self.journal.write("ALREADY_RECORDED", number=found[0])
                        return "ALREADY_RECORDED", found[0]
                    raise Assistance("CONFLICTING_RECORD", "A record for this period exists with other values.", final=True)
                self.log("check", f"Pre-check: no saved record for {self.hh}, period {self.period}.", shot=True, img=img)
                self.journal.write("PRECHECK_NONE")
                self.precheck_done = True
            img, ws = self.look()
            b = ocr.find_phrase(ws, "New recertification")
            self.click(b[0] + b[2] // 2, b[1] + b[3] // 2)
            img, ws = self.wait_for(lambda i, w: self.screen_kind(i, w) in ("form", "unexpected"), 8, "form")
            if img is None:
                raise Assistance("FORM_TIMEOUT", "The form did not open within 8 s.")
        img, ws = self.look()
        if self.screen_kind(img, ws) == "unexpected":
            self.handle_unexpected(img)
        txt = ocr.text_of(ws)
        if self.hh not in txt or self.period not in txt:
            raise Assistance("WRONG_CASE", "The open form is not for this household and period.")
        self.log("check", f"Form open for {self.hh}, period {self.period} (read on screen).", shot=True, img=img)
        self.fill_form()
        review = self.final_review()
        self.submit_save(review)
        return self.after_save()

    def hold(self, why):
        if why == "focus":
            self.log("alert", "Focus left the remote desktop window. Suspended; the agent will not take focus back. "
                              "Resume when ready.")
        elif why == "pause":
            self.log("alert", "Paused by operator. No further input is sent.", shot=True)
        while True:
            c = control.get()
            if c == "stop":
                raise Stopped()
            if c == "run":
                if not self.s.has_focus():
                    time.sleep(0.3)
                    continue
                self.log("info", "Resume requested. Fresh capture; every value is read again before any input.", shot=True)
                return
            time.sleep(0.2)

    def main(self):
        open_sub = self.journal.open_submission()
        self.log("info", f"Transaction {self.hh} / {self.period}: {len(self.prepared)} prepared values. "
                         f"Model on exceptions: {self.vision.name}.")
        while True:
            try:
                if open_sub:
                    status, ref = self.recover()
                else:
                    status, ref = self.normal()
                break
            except Paused:
                self.hold("pause")
            except FocusLost:
                self.hold("focus")
            except Assistance as a:
                self.journal.write("ASSISTANCE_REQUIRED", code=a.code, msg=a.msg)
                self.log("alert", f"Assistance required: {a.msg}", shot=True)
                if a.final:
                    status, ref = "ASSISTANCE_REQUIRED", a.code
                    break
                control.put("pause")
                self.hold("assist")
            except Stopped:
                self.journal.write("STOPPED_BY_OPERATOR")
                self.log("alert", "Stopped by operator.")
                status, ref = "STOPPED", None
                break
        nsub = sum(1 for e in self.journal.events() if e["event"] == "SAVE_CLICK_SENT")
        summary = {"status": status, "ref": ref, "model_calls": self.vision.calls, "inputs_sent": self.inputs,
                   "save_clicks_in_journal": nsub, "operator_values": {k: v for k, v in self.expected.items()
                                                                       if v != self.prepared.get(k)}}
        self.log("ok" if status in ("COMPLETED_VERIFIED", "RECOVERED_VERIFIED", "ALREADY_RECORDED") else "alert",
                 f"Status: {status}{' ' + ref if ref else ''}. Save clicks in journal: {nsub}. "
                 f"Model calls this run: {self.vision.calls}.", shot=True)
        with open(os.path.join(self.dir, "summary.json"), "w") as f:
            json.dump(summary, f, indent=1)
        return summary


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    control.put("run") if control.get() == "stop" else None
    r = Runner(args[0], use_model="--no-model" not in sys.argv)
    out = r.main()
    print(json.dumps(out))
    sys.exit(0 if out["status"] in ("COMPLETED_VERIFIED", "RECOVERED_VERIFIED", "ALREADY_RECORDED") else 3)
