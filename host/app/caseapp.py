#!/usr/bin/env python3
"""Synthetic 'legacy' case application, served inside the xrdp session.

It is deliberately plain and deliberately permissive:
- every Save creates a NEW record, even for the same household and period
  (no unique constraint, so the executor cannot rely on the app to refuse a duplicate);
- Save is slow (configurable latency) and the confirmation is a modal box;
- search can lag behind saves (index delay), to make "search is empty" an ambiguous answer.

Faults are read from /srv/data/faults.json at each action. Records live in
/srv/data/records.jsonl. The executor on the client side never reads either file.
"""
import json, os, time, tkinter as tk

DATA = os.environ.get("CASEAPP_DATA", "/srv/data")
REC = os.path.join(DATA, "records.jsonl")
FAULTS = os.path.join(DATA, "faults.json")

HOUSEHOLDS = {  # synthetic
    "DEMO-HH-014": {"name": "Synthetic household 014", "unit": "Unit 4B, Demo Court"},
    "DEMO-HH-015": {"name": "Synthetic household 015", "unit": "Unit 2A, Demo Court"},
}

GRAY, DARK, WHITE, NAVY = "#d4d0c8", "#808080", "#ffffff", "#0a246a"
F = ("DejaVu Sans", 11)
FB = ("DejaVu Sans", 11, "bold")
FT = ("DejaVu Sans", 13, "bold")


def faults():
    try:
        with open(FAULTS) as f:
            return json.load(f)
    except Exception:
        return {}


def load_records():
    out = []
    try:
        with open(REC) as f:
            for line in f:
                if line.strip():
                    out.append(json.loads(line))
    except FileNotFoundError:
        pass
    return out


def next_number():
    return "R-%05d" % (10480 + len(load_records()) + 1)


class App:
    def __init__(self, root):
        self.root = root
        root.configure(bg=GRAY)
        w, h = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{w}x{h}+0+0")
        self.title = tk.Frame(root, bg=NAVY, height=30)
        self.title.pack(fill="x")
        tk.Label(self.title, text="  Housing Case Manager 4.2  [synthetic demo application]",
                 bg=NAVY, fg=WHITE, font=FB, anchor="w").pack(side="left", pady=4)
        menu = tk.Frame(root, bg=GRAY)
        menu.pack(fill="x")
        for m in ("File", "Edit", "View", "Records", "Help"):
            tk.Label(menu, text=m, bg=GRAY, font=F, padx=10).pack(side="left", pady=2)
        tk.Frame(root, bg=DARK, height=1).pack(fill="x")
        self.body = tk.Frame(root, bg=GRAY)
        self.body.pack(fill="both", expand=True, padx=14, pady=10)
        self.status = tk.Label(root, text="Ready", bg=GRAY, font=F, anchor="w", relief="sunken", bd=1)
        self.status.pack(fill="x", side="bottom")
        root.bind_class("Entry", "<Control-a>", lambda e: (e.widget.select_range(0, "end"), e.widget.icursor("end"), "break")[-1])
        self.modal = None
        self.show_search()

    # ---------- helpers
    def clear(self):
        for c in self.body.winfo_children():
            c.destroy()

    def heading(self, text):
        tk.Label(self.body, text=text, bg=GRAY, font=FT, anchor="w").pack(fill="x", pady=(0, 10))

    def button(self, parent, text, cmd, **kw):
        return tk.Button(parent, text=text, command=cmd, font=F, bg=GRAY, activebackground=GRAY,
                         relief="raised", bd=2, padx=14, pady=3, highlightthickness=0, **kw)

    def field(self, parent, row, label, value="", readonly=False):
        tk.Label(parent, text=label, bg=GRAY, font=F, anchor="w", width=22).grid(row=row, column=0, sticky="w", pady=7)
        if readonly:
            e = tk.Label(parent, text=value, bg=WHITE, font=F, anchor="w", width=18, relief="sunken", bd=2, padx=4)
        else:
            e = tk.Entry(parent, font=F, width=18, relief="sunken", bd=2, bg=WHITE,
                         highlightthickness=0, insertwidth=1)
            e.insert(0, value)
        e.grid(row=row, column=1, sticky="w", pady=7, ipady=2)
        return e

    def dialog(self, title, lines, buttons):
        if self.modal:
            self.modal.destroy()
        d = tk.Frame(self.root, bg=GRAY, relief="raised", bd=3)
        tb = tk.Frame(d, bg=NAVY)
        tb.pack(fill="x")
        tk.Label(tb, text="  " + title, bg=NAVY, fg=WHITE, font=FB, anchor="w").pack(side="left", pady=3)
        for ln in lines:
            tk.Label(d, text=ln, bg=GRAY, font=F, anchor="w", padx=18).pack(fill="x", pady=(10, 0))
        row = tk.Frame(d, bg=GRAY)
        row.pack(pady=16)
        for text, cmd in buttons:
            self.button(row, text, cmd, width=8).pack(side="left", padx=8)
        d.place(relx=0.5, rely=0.42, anchor="center", width=430)
        d.lift()
        self.modal = d

    def close_dialog(self, then=None):
        if self.modal:
            self.modal.destroy()
            self.modal = None
        if then:
            then()

    # ---------- screen 1: search
    def show_search(self, hhid=""):
        self.clear()
        self.heading("Find household")
        top = tk.Frame(self.body, bg=GRAY)
        top.pack(fill="x")
        tk.Label(top, text="Household ID", bg=GRAY, font=F).pack(side="left")
        self.q = tk.Entry(top, font=F, width=18, relief="sunken", bd=2, highlightthickness=0, insertwidth=1)
        self.q.pack(side="left", padx=10, ipady=2)
        self.q.insert(0, hhid)
        self.q.bind("<Return>", lambda e: self.do_search())
        self.button(top, "Search", self.do_search).pack(side="left")
        self.results = tk.Frame(self.body, bg=GRAY)
        self.results.pack(fill="both", expand=True, pady=14)
        self.status.config(text="Ready")
        if hhid:
            self.do_search()

    def do_search(self):
        hhid = self.q.get().strip().upper()
        for c in self.results.winfo_children():
            c.destroy()
        hh = HOUSEHOLDS.get(hhid)
        if not hh:
            tk.Label(self.results, text="No household found.", bg=GRAY, font=F, anchor="w").pack(fill="x")
            return
        tk.Label(self.results, text=f"{hhid}   {hh['name']}   {hh['unit']}", bg=GRAY, font=FB,
                 anchor="w").pack(fill="x")
        self.button(self.results, "New recertification", lambda: self.show_form(hhid)).pack(anchor="w", pady=10)
        tk.Label(self.results, text="Saved recertifications", bg=GRAY, font=FB, anchor="w").pack(fill="x", pady=(8, 4))
        box = tk.Frame(self.results, bg=WHITE, relief="sunken", bd=2)
        box.pack(fill="x")
        delay = float(faults().get("index_delay", 0))
        now = time.time()
        rows = [r for r in load_records() if r["household_id"] == hhid and now - r["saved_epoch"] >= delay]
        if not rows:
            tk.Label(box, text="No saved records for this household.", bg=WHITE, font=F, anchor="w",
                     padx=6, pady=6).pack(fill="x")
        for r in rows:
            line = tk.Frame(box, bg=WHITE)
            line.pack(fill="x", padx=4, pady=2)
            tk.Label(line, text=f"{r['number']}    Period {r['period']}    Saved {r['saved_at']}",
                     bg=WHITE, font=F, anchor="w").pack(side="left", padx=4)
            self.button(line, "View", lambda r=r: self.show_record(r)).pack(side="right", padx=4)
        self.status.config(text=f"{len(rows)} saved record(s) listed")

    # ---------- screen 2: form with two tabs
    def show_form(self, hhid):
        self.clear()
        self.form_hh = hhid
        self.popup_done = False
        self.heading(f"Recertification   {hhid}   Period 2026-11")
        tabs = tk.Frame(self.body, bg=GRAY)
        tabs.pack(fill="x")
        self.pages, self.tabbtn = {}, {}
        holder = tk.Frame(self.body, bg=GRAY, relief="raised", bd=2)
        holder.pack(fill="x", pady=(0, 10))
        for name in ("Household", "Income"):
            b = tk.Button(tabs, text=name, font=F, bg=GRAY, relief="raised", bd=2, padx=16,
                          highlightthickness=0, command=lambda n=name: self.tab(n))
            b.pack(side="left")
            self.tabbtn[name] = b
            p = tk.Frame(holder, bg=GRAY)
            self.pages[name] = p
        p = self.pages["Household"]
        self.e_members = self.field(p, 0, "Members in household")
        self.e_eff = self.field(p, 1, "Effective date")
        p = self.pages["Income"]
        self.e_wages = self.field(p, 0, "Monthly wages")
        self.e_benef = self.field(p, 1, "Monthly benefits")
        bar = tk.Frame(self.body, bg=GRAY)
        bar.pack(fill="x")
        self.button(bar, "Save", self.save).pack(side="left")
        self.button(bar, "Cancel", lambda: self.show_search(hhid)).pack(side="left", padx=10)
        self.tab("Household")
        self.status.config(text="Editing")

    def tab(self, name):
        for n, p in self.pages.items():
            p.pack_forget()
            self.tabbtn[n].config(relief="raised", font=F)
        self.pages[name].pack(fill="x", padx=12, pady=12)
        self.tabbtn[name].config(relief="sunken", font=FB)
        fl = faults()
        if name == "Income" and fl.get("popup_on_income_tab") and not getattr(self, "popup_done", False):
            self.popup_done = True
            self.dialog("Notice", ["Income source verification is pending", "for this case. Continue anyway?"],
                        [("Continue", self.close_dialog), ("Cancel", self.close_dialog)])

    def save(self):
        vals = {"members": self.e_members.get().strip(), "effective_date": self.e_eff.get().strip(),
                "monthly_wages": self.e_wages.get().strip(), "monthly_benefits": self.e_benef.get().strip()}
        self.status.config(text="Saving...")
        self.root.config(cursor="watch")
        lat = float(faults().get("save_latency", 2.5))
        self.root.after(int(lat * 1000), lambda: self.finish_save(vals))

    def finish_save(self, vals):
        rec = {"number": next_number(), "household_id": self.form_hh, "period": "2026-11",
               "saved_at": time.strftime("%H:%M:%S"), "saved_epoch": time.time(), **vals}
        os.makedirs(DATA, exist_ok=True)
        with open(REC, "a") as f:
            f.write(json.dumps(rec) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self.root.config(cursor="")
        self.status.config(text="Saved")
        hh = self.form_hh
        if faults().get("quiet_save"):  # some screens return to the list without any confirmation
            self.show_search(hh)
            return
        self.dialog("Housing Case Manager", ["Record saved.", f"Confirmation {rec['number']}"],
                    [("OK", lambda: self.close_dialog(lambda: self.show_search(hh)))])

    # ---------- screen 3: saved record, read only
    def show_record(self, r):
        self.clear()
        self.heading(f"Saved recertification   {r['number']}")
        g = tk.Frame(self.body, bg=GRAY)
        g.pack(fill="x", padx=12)
        self.field(g, 0, "Household ID", r["household_id"], readonly=True)
        self.field(g, 1, "Period", r["period"], readonly=True)
        self.field(g, 2, "Members in household", r["members"], readonly=True)
        self.field(g, 3, "Effective date", r["effective_date"], readonly=True)
        self.field(g, 4, "Monthly wages", r["monthly_wages"], readonly=True)
        self.field(g, 5, "Monthly benefits", r["monthly_benefits"], readonly=True)
        self.button(self.body, "Close", lambda: self.show_search(r["household_id"])).pack(anchor="w", pady=14)
        self.status.config(text=f"Viewing {r['number']}")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
