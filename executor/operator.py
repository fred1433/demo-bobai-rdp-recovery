"""Scripted stand-in for the human operator, used to make the recorded runs reproducible.

It acts on the SAME client window the way a person would (mouse and keyboard on the local
display). It is not part of the executor and the executor does not know when it acts.

    python -m executor.operator focus                 # click into the RDP window
    python -m executor.operator set "Monthly wages" 1865.00
    python -m executor.operator click "Continue"
    python -m executor.operator steal-focus           # open a local window that takes focus
"""
import sys, time
from Xlib import X
from . import ocr
from .screen import Screen


def main():
    s = Screen()
    cmd = sys.argv[1]
    if cmd == "focus":
        w = s.client_window()
        x, y, ww, hh = s.geometry()
        s.move(ww // 2, hh - 4)
        s.d.set_input_focus(w, X.RevertToPointerRoot, X.CurrentTime)
        s.d.sync()
        print("focus on client window:", s.has_focus())
    elif cmd == "set":
        label, value = sys.argv[2], sys.argv[3]
        img = s.capture()
        lb = ocr.find_phrase(ocr.words(img), label)
        box = ocr.white_box_right_of(img, lb)
        s.click(box[0] + box[2] - 8, box[1] + box[3] // 2)
        time.sleep(0.3)
        s.key("a", ("Control_L",))
        for ch in value:
            s.char(ch)
            time.sleep(0.12)
        print("operator typed", value, "into", label)
    elif cmd == "click":
        img = s.capture()
        b = ocr.find_all(ocr.words(img), sys.argv[2])[-1]  # the button, below any text using the same word
        s.click(b[0] + b[2] // 2, b[1] + b[3] // 2)
        print("operator clicked", sys.argv[2])
    elif cmd == "steal-focus":
        win = s.root.create_window(1060, 40, 200, 120, 0, s.d.screen().root_depth,
                                   background_pixel=s.d.screen().white_pixel)
        win.set_wm_name("Local notepad")
        win.map()
        s.d.sync()
        time.sleep(0.3)
        s.d.set_input_focus(win, X.RevertToPointerRoot, X.CurrentTime)
        s.d.sync()
        print("focus moved to a local window; holding it", sys.argv[2] if len(sys.argv) > 2 else "8", "s")
        time.sleep(float(sys.argv[2]) if len(sys.argv) > 2 else 8)
        win.destroy()
        s.d.sync()


if __name__ == "__main__":
    main()
