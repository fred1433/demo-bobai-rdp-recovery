# Interrupted save, recovered without resubmitting

A small attended executor that completes one prepared transaction in an application it can only
see as the pixels of a remote desktop window, and that knows what to do when it is killed right
after clicking **Save**.

> Recorded test. FreeRDP client on macOS, Linux xrdp host. Synthetic application and data.
> Windows client not tested.

Page with the two films: https://theaipipe.com/demos/rdp-recovery/

## The promise, and its limit

After an interruption, it verifies the result before any new submission; if it cannot conclude,
it stops.

It does not promise "never a duplicate": with only pixels and no help from the remote application,
nobody can. What it does: write the intent to submit to a durable journal *before* the click; after
a restart, treat the result as unknown; search the application, reopen the record, compare every
value; and stop with "assistance required" when the screen does not prove anything. An empty search
is not taken as proof that nothing was saved (see the `ambiguous` scenario: the record exists on the
host but is not listed yet, and the executor does not submit again).

## What ran

| Part | What it is |
|---|---|
| Client side (the "workstation") | macOS 27.2, Apple M1 Max. FreeRDP 3.32.2 (`xfreerdp`, Homebrew), drawing into a virtual X screen so the real desktop is never captured or typed into |
| Virtual screen | Xvfb in a Docker container (`screen/`), published on 127.0.0.1 only. macOS cannot run Xvfb without root, hence the container |
| Remote host (the "vendor machine") | Debian 12 container (`host/`), xrdp 0.9.21.1 + xorgxrdp 0.9.19, Python 3.11 / Tk. Nothing from the executor is installed there |
| Synthetic app | `host/app/caseapp.py`: search a household, two-tab form, Save, saved-record list, read-only record view. It ACCEPTS duplicate saves on purpose |
| Executor | `executor/`, Python 3, runs on macOS. Sees only the client window's pixels; sends only local keyboard and mouse events |
| Reading the screen | Tesseract 5.5.2 (local OCR). Field values are read by four OCR variants that must agree 3 of 4; otherwise "unreadable", never a guess |
| Model | Qwen2.5-VL 7B Instruct (Q4_K_M, Apache-2.0) via Ollama 0.40.13 on 127.0.0.1, called only when the screen matches no known state. It returns one label from a fixed list; it never clicks and its words are never shown as facts |
| Cost | No remote model API was called. 0 $ |

Docker runs in colima 0.10.3 (Docker 29.5.2).

## Where things are (for the engineers taking it over)

| Question | Answer |
|---|---|
| Where do the prepared data enter? | `data/DEMO-HH-014_2026-11.json`, passed on the command line. In production: produced by your platform |
| Where are capture and input? | `executor/screen.py`. Capture = the client window's rectangle, read fresh before every action (the window can move). Input = XTest events on the local display. Every single key or click goes through `Runner.gate()` |
| Where is submission allowed? | Only in `Runner.submit_save()`: after a full read-back of both tabs, after a pre-check search found no record for the period, and only if the journal holds no unconcluded submission. Recovery never calls it |
| How does state survive a crash? | `executor/journal.py`: one JSON line per event, `fsync` before the next action. `SUBMIT_INTENT` (with the expected values) is written before the Save click, `SAVE_CLICK_SENT` right after |
| What happens on restart? | `Runner.recover()`: result unknown; a confirmation box on screen is a hint, not proof; search (3 tries, bounded); reopen every record of the period; compare household, period and the 4 values; conclude `RECOVERED_VERIFIED`, or stop with `ASSISTANCE_REQUIRED` |
| Pause, stop, takeover | `python -m executor.control pause|resume|stop`. Checked before every input event. On resume: fresh capture, every value read again; a value changed by the operator is detected, logged and kept, never overwritten |
| Focus | If keyboard focus leaves the client window, the executor suspends itself and never takes focus back. It waits for the operator to resume |
| Unexpected screen | Unknown words on screen -> one call to the local model -> label -> assistance required. The executor does not answer dialogs on the operator's behalf |
| How is success checked in the tests? | `scripts/host_check.sh` counts records in the host's storage. It is a test oracle only; the executor never reads it |

## Reproduce

Requirements: macOS with Homebrew, colima (or any Docker), `brew install freerdp tesseract ollama`.

```sh
docker build -t rdp-demo-host host
docker build -t rdp-demo-screen screen
python3 -m venv venv && venv/bin/pip install python-xlib pillow numpy
ollama serve &              # listens on 127.0.0.1:11434
ollama pull qwen2.5vl:7b
scripts/up.sh               # host + virtual screen + FreeRDP client
venv/bin/python scripts/scenario.py recovery     # pause, operator edit, Save, kill -9, restart
venv/bin/python scripts/scenario.py ambiguous    # saved but not listed: assistance, no resubmission
venv/bin/python scripts/scenario.py popup        # unexpected notice: model call, assistance, operator resolves
venv/bin/python scripts/scenario.py focus        # another local window takes focus
venv/bin/python scripts/scenario.py move         # the client window is moved mid-run
venv/bin/python scripts/results_table.py         # trials/RESULTS.md
scripts/down.sh
```

Add `--record` to a scenario to record the virtual screen; `video/compose.py` turns a recording
into the captioned film.

The scenarios play the operator and the faults from a separate process: pause and resume through
the control file, edits typed into the same window, `SIGKILL` of the executor process right after
`SAVE_CLICK_SENT` is journaled. The executor is never told what will happen.

## Results

See [`trials/RESULTS.md`](trials/RESULTS.md): one row per replay, with the final status, Save clicks
in the journal, records found on the host by the independent check, and model calls. Each run's
journal, executor output and events are next to it in `trials/`.

## Not covered

- Your application, your platform, your data, your remote desktop client and policies.
- A Windows client: capture through `BitBlt`/DXGI, input through `SendInput`, UIPI integrity
  levels, DPI scaling, screen-capture protection. The executor's `screen.py` is the one file to
  port; the journal, gate and recovery logic do not depend on the platform.
- Scaling the display (125 %), scrolling, long lists, multi-record transactions.

Author: Frederic de Lavenne de Choulot, The AI Pipe. https://cal.theaipipe.com (15 minutes).
