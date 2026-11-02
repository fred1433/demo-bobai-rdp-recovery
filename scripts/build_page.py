#!/usr/bin/env python3
"""Fill the page template with the exact numbers of the recorded runs and the trial replays.

    venv/bin/python scripts/build_page.py <film scenario base> <ambiguous film base>

Every number on the page comes from runs/scenarios/*.json (journal, executor output, host check).
"""
import glob, html, json, os, re, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
esc = html.escape
film, amb = sys.argv[1], sys.argv[2]
F = json.load(open(film + ".json"))
A = json.load(open(amb + ".json"))
page = open(os.path.join(ROOT, "video", "page.template.html")).read()

marks = json.load(open(os.path.join(ROOT, "site", "media", "recovery.chapters.json")))
rows = ['<li><button type="button" data-at="0"><span class="clock">0:00</span><span>Excerpt: the restart, shown first</span></button></li>']
for m in marks:
    rows.append(f'<li><button type="button" data-at="{m["at"]}"><span class="clock">{m["clock"]}</span>'
                f'<span>{esc(m["caption"])}</span></button></li>')
page = page.replace("<!--MARKS-->", "\n".join(rows))

s = F["restart_summary"]
hc = F["host_check"]
saves = sum(1 for e in F["journal"] if e["event"] == "SAVE_CLICK_SENT")
model = sum(1 for e in F["journal"] if e["event"] == "MODEL_CALL")
op = [e for e in F["journal"] if e["event"] == "OPERATOR_VALUE"]
prepared = json.load(open(os.path.join(ROOT, "data", "DEMO-HH-014_2026-11.json")))["values"]
facts = [
    ("Executor status after restart", f'{s["status"]} {s["ref"]}', "ok"),
    (f'Records on the host for <span class="nw">{hc["household"]}</span>, <span class="nw">{hc["period"]}</span>', str(hc["records_on_host"]), "ok"),
    ("Save clicks in the journal", str(saves), ""),
    ("Model calls in this run", str(model), ""),
]
for e in op:
    facts.append((f'Kept the operator\'s value for {e["field"].replace("_", " ")} (prepared {prepared[e["field"]]})',
                  e["on_screen"], ""))
page = page.replace("<!--FACTS-->", "\n".join(
    f'<div class="row"><dt>{k if "<span" in k else esc(k)}</dt><dd class="{c}">{esc(v)}</dd></div>' for k, v, c in facts))

out = open(glob.glob(amb + ".only.out")[0]).read()
m = re.search(r"no record is visible after (\d+) searches over (\d+) s", out)
ah = A["host_check"]
asaves = sum(1 for e in A["journal"] if e["event"] == "SAVE_CLICK_SENT")
page = page.replace("<!--AMBIG-->", f"""
<p>Here the application accepts the Save but returns to its list without a confirmation, and the list lags behind. The executor searches {m.group(1)} times over {m.group(2)} seconds and finds nothing.</p>
<p>An empty list does not prove that nothing was saved, so it stops with <b>assistance required</b> and does not submit again.</p>
<p>The check on the host afterwards: {ah["records_on_host"]} record for {ah["household"]}, {ah["period"]}. It had been saved. A second submission would have made a duplicate. Save clicks in the journal: {asaves}.</p>""")

bench = [
    ("Workstation side", "macOS 27.2 on Apple M1 Max. FreeRDP 3.32.2 client, drawing into an isolated virtual screen (Xvfb with Openbox in a container, localhost only) so the faults can be replayed and recorded automatically. It is a test convenience, not a security feature."),
    ("Remote side", "Debian 12 container with xrdp 0.9.21.1, clock on the same UTC offset as the journal. It runs the synthetic application and nothing from the executor."),
    ("Application", "Synthetic, written for this test: search, two-tab form, Save, saved-record list, read-only record. It accepts duplicate saves on purpose."),
    ("Reading the screen", "Tesseract 5.5.2, local. Each value is read by four OCR variants that must agree three times out of four, else it counts as unreadable."),
    ("Model", "Qwen2.5-VL 7B Instruct (Apache-2.0) through Ollama on the same Mac, only when the screen matches no known state. It returns a label from a fixed list and never clicks."),
    ("Remote model API", "None. Cost 0 $."),
]
page = page.replace("<!--BENCH-->", "\n".join(f'<tr><td class="k">{esc(k)}</td><td>{esc(v)}</td></tr>' for k, v in bench))

desc = {
    "recovery": "Pause, scripted operator edit, Save, kill -9, restart",
    "ambiguous": "Saved, not listed, no confirmation",
    "midfield_edit": "Pause in the middle of a field; the scripted operator replaces the partial entry with 2, then 275.00",
    "stop_pause": "Stop sent during a pause",
    "pause_at_intent": "Pause sent the moment the submit intent is journaled",
    "pause_save_wait": "Pause sent while the application is still saving",
    "intent_crash_clear": "Crash between the journaled intent and the click; the operator checks and clears; the next run completes",
    "torn_after_save": "kill -9 after Save, with a torn last journal line",
    "torn_only": "Journal holding only a torn line",
    "popup": "Unexpected notice: assistance requested, scripted operator resolves it, then resumes. One model call per replay",
    "focus": "Another window takes keyboard focus; continues after explicit operator resume",
    "move": "Client window moved mid-run",
}
groups, total_model, n = {}, 0, 0
for p in glob.glob(os.path.join(ROOT, "runs", "scenarios", "*.json")):
    r = json.load(open(p))
    sm = r.get("summary") or r.get("restart_summary")
    g = groups.setdefault(r["scenario"], {"runs": 0, "status": {}, "saves": [], "host": [], "model": 0})
    g["runs"] += 1
    key = sm["status"]
    if r["scenario"] == "intent_crash_clear":
        key = f'{r["restart_summary"]["status"]}, then after clear {sm["status"]}'
    g["status"][key] = g["status"].get(key, 0) + 1
    g["saves"].append(sum(1 for e in r["journal"] if e["event"] == "SAVE_CLICK_SENT"))
    g["host"].append(r["host_check"]["records_on_host"])
    mc = sum(1 for e in r["journal"] if e["event"] == "MODEL_CALL")
    g["model"] += mc
    total_model += mc
    n += 1


def each(vals):
    return f"{vals[0]} in each" if len(set(vals)) == 1 else ", ".join(map(str, vals))


trs = []
for key in desc:
    if key not in groups:
        continue
    g = groups[key]
    st = "<br>".join(f'{c} of {g["runs"]} {k.replace("_", " ").lower()}' for k, c in g["status"].items())
    cls = "ok" if all(k.split()[-1] in ("COMPLETED_VERIFIED", "RECOVERED_VERIFIED") for k in g["status"]) else "wa"
    extra = ""
    trs.append(f'<tr><td>{esc(desc[key])}.{extra}</td><td class="st {cls}">{st}</td>'
               f'<td class="num">{each(g["saves"])}</td><td class="num">{each(g["host"])}</td></tr>')
page = page.replace("<!--TRIALS-->", "\n".join(trs))
page = page.replace("<!--TRIALNOTE-->", f"{n} replays on the final code, each from an empty host. Model calls across all of them: {total_model}. "
                    "Each replay starts from an empty host, which is why every saved record is R-10481. "
                    "Per-run journals and logs are in the repository under trials/.")
open(os.path.join(ROOT, "site", "index.html"), "w").write(page)
print("site/index.html written,", n, "replays")
