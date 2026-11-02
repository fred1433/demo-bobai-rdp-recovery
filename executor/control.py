"""Operator control: pause / resume / stop, checked before EVERY single input event.

    python -m executor.control pause|resume|stop|status

The signal is a local file, so it works from any terminal, hotkey tool or button on the
customer's workstation. A pause takes effect before the next key or click; it cannot undo a
click that was already sent.
"""
import os, sys, time

PATH = os.environ.get("RDP_CONTROL", os.path.join(os.path.dirname(__file__), "..", ".run", "control"))


def get():
    try:
        with open(PATH) as f:
            return f.read().strip() or "run"
    except FileNotFoundError:
        return "run"


def put(v):
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    with open(PATH, "w") as f:
        f.write(v)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        print(get())
    elif cmd in ("pause", "stop"):
        put(cmd)
        print(cmd)
    elif cmd == "resume":
        put("run")
        print("run")
    else:
        sys.exit("usage: pause|resume|stop|status")
