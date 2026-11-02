"""Client-side screen access: find the local RDP client window, capture its pixels, send input.

Everything here talks to the LOCAL display only (the X screen the FreeRDP client draws into).
Nothing reaches the remote host except what FreeRDP itself forwards: pixels in, keys/clicks out.
Identifying the local client window by its title is a local operation; the remote
application's own controls are never queried (there is nothing to query: they are pixels).
"""
import os, time
from PIL import Image
from Xlib import X, XK, display as xdisplay
from Xlib.ext import xtest

CLIENT_TITLE = os.environ.get("RDP_CLIENT_TITLE", "Remote Desktop - case-host")


class WindowGone(Exception):
    pass


class Screen:
    def __init__(self, display_name=None):
        self.d = xdisplay.Display(display_name or os.environ.get("RDP_X_DISPLAY", "127.0.0.1:99"))
        self.root = self.d.screen().root

    # ---------- window
    def _walk(self, w):
        try:
            name = w.get_wm_name()
        except Exception:
            name = None
        if name and CLIENT_TITLE in str(name):
            return w
        try:
            for c in w.query_tree().children:
                r = self._walk(c)
                if r:
                    return r
        except Exception:
            pass
        return None

    def client_window(self):
        w = self._walk(self.root)
        if not w:
            raise WindowGone("remote desktop client window not found")
        return w

    def geometry(self):
        """Window rectangle in root coordinates, read fresh every time (the window can move)."""
        w = self.client_window()
        g = w.get_geometry()
        t = w.translate_coords(self.root, 0, 0)
        return (-t.x, -t.y, g.width, g.height)

    def has_focus(self):
        """True when keyboard focus is on the client window (or one of its children)."""
        w = self.client_window()
        f = self.d.get_input_focus().focus
        if f in (X.PointerRoot, X.NONE) or isinstance(f, int):
            return False
        while f:
            if f.id == w.id:
                return True
            try:
                p = f.query_tree().parent
            except Exception:
                return False
            if not p or p.id == self.root.id:
                return False
            f = p
        return False

    def capture(self):
        x, y, w, h = self.geometry()
        raw = self.root.get_image(x, y, w, h, X.ZPixmap, 0xFFFFFFFF)
        return Image.frombytes("RGB", (w, h), raw.data, "raw", "BGRX")

    # ---------- input (window-relative coordinates, converted with the fresh geometry)
    def move(self, wx, wy):
        x, y, _, _ = self.geometry()
        xtest.fake_input(self.d, X.MotionNotify, x=int(x + wx), y=int(y + wy))
        self.d.sync()

    def click(self, wx, wy):
        self.move(wx, wy)
        time.sleep(0.08)
        xtest.fake_input(self.d, X.ButtonPress, 1)
        self.d.sync()
        time.sleep(0.05)
        xtest.fake_input(self.d, X.ButtonRelease, 1)
        self.d.sync()

    def _keycode(self, name):
        ks = XK.string_to_keysym(name)
        return self.d.keysym_to_keycode(ks)

    def key(self, name, mods=()):
        """One key event (press+release), e.g. key('Return'), key('a', ('Control_L',))."""
        mcodes = [self._keycode(m) for m in mods]
        for m in mcodes:
            xtest.fake_input(self.d, X.KeyPress, m)
        kc = self._keycode(name)
        xtest.fake_input(self.d, X.KeyPress, kc)
        xtest.fake_input(self.d, X.KeyRelease, kc)
        for m in reversed(mcodes):
            xtest.fake_input(self.d, X.KeyRelease, m)
        self.d.sync()

    CHARMAP = {".": "period", "/": "slash", "-": "minus", " ": "space", ",": "comma", ":": "colon"}

    def char(self, ch):
        if ch.isalpha() and ch.isupper():
            self.key(ch.lower(), ("Shift_L",))
        elif ch == ":":
            self.key("semicolon", ("Shift_L",))
        else:
            self.key(self.CHARMAP.get(ch, ch))
