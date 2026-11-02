#!/usr/bin/env python3
"""Turn one recorded scenario into the captioned video shown on the page.

    venv/bin/python video/compose.py runs/scenarios/recovery-<stamp> out.mp4 [--teaser 8] [--from-event SAVE]

Left: the pixels of the FreeRDP client window, cropped from the virtual screen recording.
Right: the executor's own log lines and the scenario's operator/bench events, at the second
they were written. Nothing is re-enacted; captions are chosen from the logged events.
No sound. Real time unless the caption bar says otherwise.
"""
import glob, json, os, subprocess, sys, textwrap
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FONTS = os.path.join(ROOT, "video", "fonts")
W, H, FPS = 1600, 900, 10
WIN = (0, 0, 1024, 720)  # client window rectangle on the virtual screen during the films

INK, MUTED, BG, PANEL, LINE = "#1d2433", "#5b6472", "#e6e9ed", "#ffffff", "#c9ced6"
KIND = {"check": "#1f6f43", "ok": "#1f6f43", "action": "#0a246a", "info": "#5b6472", "warn": "#9a5b00",
        "alert": "#b3261e", "model": "#00696b", "operator": "#6b3fa0", "bench": "#1d2433"}


def font(size, weight=400, mono=False):
    if mono:
        return ImageFont.truetype(os.path.join(FONTS, "PlexMono-Medium.ttf" if weight > 450 else "PlexMono-Regular.ttf"), size)
    f = ImageFont.truetype(os.path.join(FONTS, "PublicSans.ttf"), size)
    try:
        f.set_variation_by_axes([weight])
    except Exception:
        pass
    return f


F_CAP = font(30, 650)
F_SUB = font(17, 450)
F_MSG = font(17, 430)
F_MSGB = font(17, 620)
F_TIME = font(14, 400, mono=True)
F_SMALL = font(15, 450)
F_END = font(40, 650)
F_END2 = font(24, 450)


def load(base):
    ev = [json.loads(l) for l in open(base + ".events.jsonl")]
    res = json.load(open(base + ".json"))
    t_start, t_end = ev[0]["t"] - 1, ev[-1]["t"] + 1
    lines = []
    for p in glob.glob(os.path.join(ROOT, "runs", "*", "log.jsonl")):
        recs = [json.loads(l) for l in open(p)]
        if recs and t_start <= recs[0]["t"] <= t_end:
            lines += [{"t": r["t"], "kind": r["kind"], "msg": r["msg"]} for r in recs]
    for e in ev:
        m = e["msg"]
        if e["who"] == "operator":
            m = m[len("operator "):] if m.startswith("operator ") else m[0].lower() + m[1:]
            lines.append({"t": e["t"], "kind": "operator", "msg": "Operator: " + m})
        elif "killed" in m:
            lines.append({"t": e["t"], "kind": "bench", "msg": "Test bench: executor process killed (SIGKILL) right after the Save click."})
        elif "executor started (restart)" in m:
            lines.append({"t": e["t"], "kind": "bench", "msg": "Test bench: executor started again as a new process."})
    lines.sort(key=lambda r: r["t"])
    t0 = float(open(os.path.join(ROOT, "runs", "raw", os.path.splitext(res["video"])[0] + ".t0")).read())
    return res, ev, lines, t0


def chapters(lines, scenario):
    """(t, caption) list, picked from logged events."""
    caps = []

    def first(pred):
        return next((l["t"] for l in lines if pred(l)), None)

    if scenario == "recovery":
        caps.append((lines[0]["t"], "Prepared values typed into the remote app, each one read back from the pixels"))
        t = first(lambda l: l["msg"].startswith("Operator: pause"))
        if t: caps.append((t, "Operator presses Pause: no further input. They correct a value by hand"))
        t = first(lambda l: l["msg"].startswith("Resume requested"))
        if t: caps.append((t, "Resume: fresh capture. The operator's value is kept, not overwritten"))
        t = first(lambda l: l["msg"].startswith("Submit intent"))
        if t: caps.append((t, "Intent written to the journal, then Save is clicked"))
        t = first(lambda l: "SIGKILL" in l["msg"])
        if t: caps.append((t, "The executor is killed before it reads the result"))
        t = first(lambda l: l["msg"].startswith("Save sent. Result unknown"))
        if t: caps.append((t, "Restart: result unknown. Search, reopen, compare. Save is disabled"))
        t = first(lambda l: l["msg"].startswith("Status:"))
        if t: caps.append((t, "Verified on screen. No second Save"))
    else:
        caps.append((lines[0]["t"], "Save is clicked. The app returns to the list with no confirmation"))
        t = first(lambda l: l["msg"].startswith("Search 1/"))
        if t: caps.append((t, "The record is not listed yet. The executor searches again, with a time limit"))
        t = first(lambda l: l["msg"].startswith("Assistance required"))
        if t: caps.append((t, "It stops and asks for help. It does not submit again"))
    return caps


def wrap(draw, text, f, width):
    words, out, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=f) <= width:
            cur = test
        else:
            out.append(cur)
            cur = w
    if cur:
        out.append(cur)
    return out


def hms(t):
    import time
    return time.strftime("%H:%M:%S", time.localtime(t))


def frame(rdp, t, lines, caps, footer, tag, highlight_cap=None):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    cap = highlight_cap or next((c for tt, c in reversed(caps) if tt <= t), caps[0][1])
    d.text((32, 30), cap, font=F_CAP, fill=INK)
    tw = d.textlength(tag, font=F_SMALL)
    d.text((W - 32 - tw, 40), tag, font=F_SMALL, fill=MUTED)
    # client window, with a thin frame
    x0, y0 = 32, 96
    d.rectangle((x0 - 1, y0 - 1, x0 + 1024, y0 + 720), outline="#8a919b")
    im.paste(rdp, (x0, y0))
    d.text((x0, y0 + 732), footer, font=F_SMALL, fill=MUTED)
    # log panel
    px, py, pw, ph = 1080, 96, 488, 720
    d.rectangle((px, py, px + pw, py + ph), fill=PANEL, outline=LINE)
    d.text((px + 18, py + 14), "Executor log and test events", font=F_SUB, fill=MUTED)
    d.line((px + 18, py + 44, px + pw - 18, py + 44), fill=LINE)
    shown = [l for l in lines if l["t"] <= t]
    blocks, total = [], 0
    for l in reversed(shown):
        f = F_MSGB if l["kind"] in ("alert", "ok", "operator", "bench") else F_MSG
        rows = wrap(d, l["msg"], f, pw - 120)
        hgt = 10 + 23 * len(rows)
        if total + hgt > ph - 64:
            break
        blocks.append((l, rows, f, hgt))
        total += hgt
    y = py + 56
    for l, rows, f, hgt in reversed(blocks):
        new = t - l["t"] < 1.2
        if new:
            d.rectangle((px + 6, y - 3, px + pw - 6, y + hgt - 8), fill="#f1f4f8")
        d.rectangle((px + 12, y, px + 15, y + hgt - 12), fill=KIND.get(l["kind"], MUTED))
        d.text((px + 24, y + 2), hms(l["t"]), font=F_TIME, fill=MUTED)
        for i, r in enumerate(rows):
            d.text((px + 100, y + i * 23), r, font=f, fill=INK)
        y += hgt
    return im


def card(lines_big, lines_small):
    im = Image.new("RGB", (W, H), "#ffffff")
    d = ImageDraw.Draw(im)
    y = 300
    for s in lines_big:
        d.text((120, y), s, font=F_END, fill=INK)
        y += 58
    y += 20
    for s in lines_small:
        d.text((120, y), s, font=F_END2, fill=MUTED)
        y += 38
    return im


def frames_of(raw, start, dur):
    cmd = ["ffmpeg", "-loglevel", "error", "-ss", f"{max(0, start):.2f}", "-t", f"{dur:.2f}", "-i", raw,
           "-vf", f"crop={WIN[2]}:{WIN[3]}:{WIN[0]}:{WIN[1]},fps={FPS}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    n = WIN[2] * WIN[3] * 3
    while True:
        b = p.stdout.read(n)
        if len(b) < n:
            break
        yield Image.frombytes("RGB", (WIN[2], WIN[3]), b)


def main():
    base, out = sys.argv[1], sys.argv[2]
    teaser = float(sys.argv[sys.argv.index("--teaser") + 1]) if "--teaser" in sys.argv else 0
    res, ev, lines, t0 = load(base)
    raw = os.path.join(ROOT, "runs", "raw", res["video"])
    scen = res["scenario"]
    if scen == "ambiguous":
        ts = next(l["t"] for l in lines if l["msg"].startswith("Submit intent")) - 1.5
        lines = [l for l in lines if l["t"] >= ts]
    else:
        ts = lines[0]["t"] - 0.5
    te = next(l["t"] for l in lines if l["msg"].startswith("Status:")) + 3.0
    caps = chapters(lines, scen)
    footer = "Recorded test. FreeRDP client on macOS, Linux xrdp host. Synthetic application and data. Windows client not tested."
    enc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                            "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "slow",
                            "-crf", "27", "-tune", "stillimage", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out],
                           stdin=subprocess.PIPE)
    nt = 0
    if teaser:
        tr = next(l["t"] for l in lines if l["msg"].startswith("Save sent. Result unknown")) - 1.0
        for i, rdp in enumerate(frames_of(raw, tr - t0, teaser)):
            enc.stdin.write(frame(rdp, tr + i / FPS, lines, caps, footer, "Excerpt from the run below",
                                  highlight_cap="Save sent. Result unknown. Checking existing record.").tobytes())
            nt += 1
        c = card(["The full run, in real time."], ["Data entry, pause and takeover, Save, kill -9, restart, verification."])
        for _ in range(int(FPS * 2.2)):
            enc.stdin.write(c.tobytes())
            nt += 1
    n_before = nt
    marks, last = [], None
    for i, rdp in enumerate(frames_of(raw, ts - t0, te - ts)):
        t = ts + i / FPS
        cur = next((c for tt, c in reversed(caps) if tt <= t), caps[0][1])
        if cur != last:
            marks.append({"at": round((n_before + i) / FPS, 1), "caption": cur, "clock": hms(t)})
            last = cur
        enc.stdin.write(frame(rdp, t, lines, caps, footer, f"Real time   {int((t - ts) // 60)}:{int((t - ts) % 60):02d}").tobytes())
    hc = res["host_check"]
    summ = res.get("restart_summary") or res.get("summary") or {}
    if scen == "recovery":
        big = [f"Records on the host for {hc['household']} / {hc['period']}: {hc['records_on_host']}.",
               f"Executor status: {summ.get('status')} {summ.get('ref')}."]
    else:
        big = [f"Records on the host for {hc['household']} / {hc['period']}: {hc['records_on_host']}.",
               "Saved, not yet listed. Executor status: ASSISTANCE_REQUIRED."]
    small = ["Independent check read from the host's storage after the run. The executor never reads it.",
             f"Save clicks in the journal: {sum(1 for e in res['journal'] if e['event'] == 'SAVE_CLICK_SENT')}. "
             f"Model calls in this run: {summ.get('model_calls')}."]
    c = card(big, small)
    for _ in range(int(FPS * 5)):
        enc.stdin.write(c.tobytes())
    enc.stdin.close()
    enc.wait()
    with open(os.path.splitext(out)[0] + ".chapters.json", "w") as f:
        json.dump(marks, f, indent=1)
    print("wrote", out)


if __name__ == "__main__":
    main()
