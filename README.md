# Interrupted save, recovered without resubmitting

A small attended executor that completes one prepared transaction in an application it can only
see as the pixels of a remote desktop window, and that knows what to do when it is killed right
after clicking **Save**.

> Recorded test. FreeRDP client on macOS, Linux xrdp host. Synthetic application and data.
> Windows client not tested. Operator actions and faults are scripted; the executor runs independently.

Page with the films: https://theaipipe.com/demos/rdp-recovery/

## The promise, and its limit

After an interruption, it verifies the result before any new submission; if it cannot conclude,
it stops.

It does not promise "never a duplicate": with only pixels and no help from the remote application,
nobody can. What it does: check pause and stop for the last time, then write the intent to submit to
a durable journal *before* the click; after a restart, treat the result as unknown; let a slow save
finish (bounded wait); search the application, reopen the record, compare every value; and stop with
"assistance required" when the screen does not prove anything. An empty search is not taken as proof
that nothing was saved (`ambiguous` scenario: the record exists on the host but is not listed yet,
and the executor does not submit again).

## What ran

| Part | What it is |
|---|---|
| Client side (the "workstation") | macOS 27.2, Apple M1 Max. FreeRDP 3.32.2 (`xfreerdp`, Homebrew) |
| Virtual screen | Xvfb + Openbox in a Docker container (`screen/`), published on 127.0.0.1 only. The FreeRDP client draws into it. It exists so the faults can be replayed and recorded automatically without touching the real desktop (and because macOS cannot run Xvfb without root); it is not a security feature of a workstation |
| Remote host (the "vendor machine") | Debian 12 container (`host/`), xrdp 0.9.21.1 + xorgxrdp 0.9.19, Python 3.11 / Tk, clock set to the client's UTC offset. Nothing from the executor is installed there |
| Synthetic app | `host/app/caseapp.py`: search a household, two-tab form, Save, saved-record list, read-only record view. It ACCEPTS duplicate saves on purpose |
| Executor | `executor/`, Python 3, runs on macOS. Sees only the client window's pixels; sends only local keyboard and mouse events |
| Reading the screen | Tesseract 5.5.2 (local OCR). Field values are read by four OCR variants that must agree 3 of 4; otherwise "unreadable", never a guess. The text caret is removed before reading |
| Model | Qwen2.5-VL 7B Instruct (Q4_K_M, Apache-2.0) via Ollama 0.40.13 on 127.0.0.1, called only when the screen matches no known state. It returns one label from a fixed list; the executor then pauses for the operator. The model never clicks and its words are never shown as facts |
| Cost | No remote model API was called. 0 $ |

Docker runs in colima 0.10.3 (Docker 29.5.2).

The known path is deterministic on purpose (OCR and fixed steps): a transaction should not hang on a
model's guess. The model is for screens the workflow does not know; the adapter in `vision.py` can
hand pointing to a computer-use model if an application needs it.

## Where things are (for the engineers taking it over)

| Question | Answer |
|---|---|
| Where do the prepared data enter? | `data/DEMO-HH-014_2026-11.json`, passed on the command line. In production: produced by your platform |
| Where are capture and input? | `executor/screen.py`. Capture = the client window's rectangle, read fresh before every action (the window can move). Input = XTest events on the local display. Every key or click goes through `Runner.gate()` (pause, stop, focus) |
| Where is submission allowed? | Only in `Runner.submit_save()`: after a full read-back of both tabs, after a pre-check search found no record for the period, and only if the journal holds no unconcluded submission. `gate()` is checked once more, then the intent is journaled and the click is sent with no pause check in between (a pause there would leave an intent with no click). Recovery never calls it |
| How does state survive a crash? | `executor/journal.py`: one JSON line per event, `fsync` before the next action. `SUBMIT_INTENT` (with the expected values) before the Save click, `SAVE_CLICK_SENT` right after. A torn (unreadable) line is ignored with a warning; if the readable journal then shows no open submission, the state is uncertain and the case goes to assistance |
| What happens on restart, or on resume after a pause? | The journal is read again on every pass of the main loop. With an open submission, `Runner.recover()` runs: result unknown; a form still saving is given up to 20 s; a confirmation box is a hint, not proof; search (3 tries, bounded); reopen every record of the period; compare household, period and the 4 values; conclude `RECOVERED_VERIFIED`, or stop with `ASSISTANCE_REQUIRED` |
| Pause, stop, takeover | `python -m executor.control pause|resume|stop`. Checked before every input event, and stop works while paused. On resume: fresh capture, every value read again. A field is only typed over when it holds exactly what the executor itself typed (or nothing). A value changed by a person is never overwritten: a finished field keeps the operator's value (logged); a field interrupted mid-entry, or touched before the executor reached it, triggers "assistance required", and on the operator's resume the value on screen is kept (logged) |
| Unblocking a case | After "assistance required" on an unknown result, the operator checks the application, then `python -m executor.control clear data/<transaction>.json` writes `OPERATOR_CLEARED`. The next run starts with the pre-check search, so a record that does exist is found, not submitted again |
| Focus | If keyboard focus leaves the client window, the executor suspends itself and never takes focus back. It continues only after an explicit resume |
| Unexpected screen | Unknown words on screen -> one call to the local model -> label -> assistance required. The executor does not answer dialogs on the operator's behalf |
| How is success checked in the tests? | `scripts/host_check.sh` counts records in the host's storage. It is a test oracle only; the executor never reads it |

Test hook: `RDP_TEST_FAULT=exit_before_click` makes the executor exit right after journaling the
intent (used only by the `intent_crash_clear` scenario).

## Reproduce

Requirements: macOS with Homebrew, colima (or any Docker), `brew install freerdp tesseract ollama`.

```sh
docker build -t rdp-demo-host host
docker build -t rdp-demo-screen screen
python3 -m venv venv && venv/bin/pip install python-xlib pillow numpy
ollama serve &              # listens on 127.0.0.1:11434
ollama pull qwen2.5vl:7b
scripts/up.sh               # host + virtual screen + FreeRDP client
scripts/all_trials.sh       # every scenario below, then trials/RESULTS.md
scripts/down.sh
```

Scenarios (`venv/bin/python scripts/scenario.py <name> [--record]`):

| Name | What the harness does |
|---|---|
| `recovery` | pause, operator edits a finished field, resume, Save, `kill -9` right after the click, restart |
| `ambiguous` | the app saves but lists the record late and shows no confirmation |
| `midfield_edit` | pause while Monthly benefits is being typed; operator replaces the partial entry with `2`, resumes; then finishes with `275.00` and resumes |
| `stop_pause` | pause, then stop while paused |
| `pause_at_intent` | pause sent the moment the submit intent is journaled |
| `pause_save_wait` | pause sent while the app is still saving (6 s save) |
| `intent_crash_clear` | executor exits between intent and click; restart cannot conclude; operator checks and clears; third run completes |
| `torn_after_save` | `kill -9` after Save, then a torn line appended to the journal |
| `torn_only` | the journal holds only a torn line |
| `popup` | unexpected notice on the Income tab; the scripted operator answers it and resumes |
| `focus` | another local window takes keyboard focus for 6 s |
| `move` | the client window is moved mid-run |

`--record` records the virtual screen; `video/compose.py` turns a recording into the captioned film
(`--mobile` for the phone version cropped to the client window).

The scenarios play the operator and the faults from a separate process: pause, resume and stop
through the control file, edits typed into the same window, `SIGKILL` of the executor process. The
executor is never told what will happen.

## Results

See [`trials/RESULTS.md`](trials/RESULTS.md): one row per replay, with the final status, Save clicks
in the journal, records found on the host by the independent check, and model calls. Each run's
journal, executor output and events are next to it in `trials/`.

## Not covered

- Your application, your platform, your data, your remote desktop client and policies.
- A pause button or hotkey for the customer: here pause, resume, stop and clear are commands on a
  local control file, and the operator in the recorded runs is a script.
- A Windows client: capture through `BitBlt`/DXGI, input through `SendInput`, UIPI integrity levels,
  DPI scaling, screen-capture protection. `executor/screen.py` isolates capture and input; a Windows
  port replaces it, adds detection of the operator's own mouse and keyboard (takeover), and
  recalibrates the OCR for Windows fonts and scaling. The journal, gate and recovery logic do not
  depend on the platform.
- Display scaling (125 %), scrolling, long lists, multi-record transactions.

Author: Frederic de Lavenne de Choulot, The AI Pipe. https://cal.theaipipe.com (15 minutes).
