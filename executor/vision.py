"""Model adapter, used ONLY when the screen does not match a known state.

The model never clicks and never writes text that is shown as fact. It picks one identifier
from a fixed list; the executor maps that identifier to its own wording and decision.
Every call is counted and journaled.

Implementation used in the recorded runs: Qwen2.5-VL 7B Instruct (Apache-2.0), served locally
by Ollama on 127.0.0.1. No remote API.
"""
import base64, io, json, os, time, urllib.request

LABELS = {
    "A": "normal_form",
    "B": "save_confirmation",
    "C": "warning_or_notice",
    "D": "error_message",
    "E": "login_or_session_prompt",
    "F": "other",
}

PROMPT = ("This is a screenshot of a remote desktop window showing a business application. "
          "Which ONE option best describes what is in front of the user right now?\n"
          "A) only the normal data-entry form, no dialog box\n"
          "B) a box saying a record was saved\n"
          "C) a warning or notice box asking the user to decide whether to continue\n"
          "D) an error message box\n"
          "E) a login or session prompt\n"
          "F) something else\n"
          "Answer with the letter only.")


class LocalVision:
    name = "qwen2.5vl:7b via Ollama (local)"

    def __init__(self, model="qwen2.5vl:7b", host="http://127.0.0.1:11434"):
        self.model, self.host, self.calls = model, host, 0

    def classify(self, img):
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        body = json.dumps({"model": self.model, "stream": False, "options": {"temperature": 0},
                           "messages": [{"role": "user", "content": PROMPT,
                                         "images": [base64.b64encode(buf.getvalue()).decode()]}]}).encode()
        t0 = time.time()
        req = urllib.request.Request(self.host + "/api/chat", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            ans = json.loads(r.read())["message"]["content"].strip()
        self.calls += 1
        letter = next((c for c in ans.upper() if c in LABELS), "F")
        return LABELS[letter], round(time.time() - t0, 1), ans[:40]


class NoVision:
    name = "none"
    calls = 0

    def classify(self, img):
        return "other", 0.0, ""
