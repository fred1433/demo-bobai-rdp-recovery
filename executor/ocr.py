"""Local OCR (Tesseract) and pixel geometry on a captured window image. No network."""
import subprocess, tempfile, os, re
from dataclasses import dataclass
from PIL import Image, ImageOps

SCALE = 2


@dataclass
class Word:
    text: str
    x: int
    y: int
    w: int
    h: int
    line: tuple

    @property
    def cx(self):
        return self.x + self.w // 2

    @property
    def cy(self):
        return self.y + self.h // 2


def _tess(img, psm, extra=()):
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        img.save(f.name)
        path = f.name
    try:
        out = subprocess.run(["tesseract", path, "stdout", "--psm", str(psm), *extra],
                             capture_output=True, text=True, timeout=30).stdout
    finally:
        os.unlink(path)
    return out


def words(img):
    """All words on the window with their boxes, in window pixel coordinates."""
    big = ImageOps.grayscale(img).resize((img.width * SCALE, img.height * SCALE), Image.LANCZOS)
    big = big.point(lambda v: 255 if v > 150 else 0)  # drops the 3D bevels around buttons and tabs
    tsv = _tess(big, 3, ["tsv"])
    out = []
    for row in tsv.splitlines()[1:]:
        p = row.split("\t")
        if len(p) < 12 or not p[11].strip():
            continue
        try:
            if float(p[10]) < 30:
                continue
        except ValueError:
            continue
        x, y, w, h = (int(v) // SCALE for v in p[6:10])
        out.append(Word(p[11].strip(), x, y, w, h, (p[2], p[3], p[4])))
    return out


def text_of(ws):
    return " ".join(w.text for w in ws)


def lines(ws, tol=7):
    """Group words into visual rows (by vertical centre), each row sorted left to right."""
    rows = []
    for w in sorted(ws, key=lambda w: w.cy):
        if rows and abs(rows[-1][-1].cy - w.cy) < tol:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [sorted(r, key=lambda w: w.x) for r in rows]


def find_phrase(ws, phrase, below=0, case=True):
    """First sequence of words on one row matching `phrase` (top to bottom). (x, y, w, h) or None."""
    found = find_all(ws, phrase, below, case)
    return found[0] if found else None


def find_all(ws, phrase, below=0, case=True):
    """Every match of `phrase`, top to bottom."""
    hits = []
    target = phrase.split()
    norm = (lambda s: s) if case else (lambda s: s.lower())
    n = len(target)
    for row in lines(ws):
        for i in range(len(row) - n + 1):
            seq = row[i:i + n]
            if all(norm(a.text.strip(":")) == norm(b) for a, b in zip(seq, target)) and seq[0].y >= below:
                x0 = min(s.x for s in seq); y0 = min(s.y for s in seq)
                x1 = max(s.x + s.w for s in seq); y1 = max(s.y + s.h for s in seq)
                hits.append((x0, y0, x1 - x0, y1 - y0))
    return hits


def white_box_right_of(img, label_box, max_dx=400):
    """The white input box that sits to the right of a label, found by scanning pixels."""
    px = img.load()
    x0 = label_box[0] + label_box[2] + 4
    cy = label_box[1] + label_box[3] // 2
    W, H = img.size

    def white(x, y):
        r, g, b = px[x, y]
        return r > 245 and g > 245 and b > 245

    x = x0
    while x < min(W - 1, x0 + max_dx) and not white(x, cy):
        x += 1
    if x >= min(W - 1, x0 + max_dx):
        return None
    left = x
    inside = lambda yy: white(left, yy) or white(left + 1, yy)
    top = cy
    while top > 0 and inside(top - 1):
        top -= 1
    bottom = cy
    while bottom < H - 1 and inside(bottom + 1):
        bottom += 1
    # width: scan the first inner row (padding above the text), not the text line
    y = top + 1
    right = left
    while right < W - 1 and white(right, y):
        right += 1
    if right - left < 30 or bottom - top < 10:
        return None
    return (left, top, right - left, bottom - top)


def _read_once(img, box, whitelist, scale, binarize):
    x, y, w, h = box
    crop = ImageOps.grayscale(img.crop((x + 2, y + 2, x + w - 2, y + h - 2)))
    crop = remove_caret(crop)
    crop = crop.resize((crop.width * scale, crop.height * scale), Image.LANCZOS)
    if binarize:
        crop = crop.point(lambda v: 255 if v > 140 else 0)
    crop = ImageOps.expand(crop, border=20, fill=255)
    extra = ["-c", f"tessedit_char_whitelist={whitelist}"] if whitelist else []
    return re.sub(r"\s+", "", _tess(crop, 7, extra)).strip()


def remove_caret(g):
    """Whiten the blinking text caret: a 1-2 px column that is dark over most of the box height.
    Digit strokes are shorter than the caret, so they are left alone."""
    px = g.load()
    W, H = g.size
    for x in range(W):
        dark = sum(1 for y in range(H) if px[x, y] < 110)
        if dark >= 0.75 * H:
            for y in range(H):
                px[x, y] = 255
    return g


def read_box(img, box, whitelist="0123456789./-"):
    """Read one input box. Four OCR variants vote; without a clear majority (3 of 4) the
    result is None (unreadable), never a guess."""
    votes = [_read_once(img, box, whitelist, sc, bz) for sc in (3, 4) for bz in (False, True)]
    best = max(set(votes), key=votes.count)
    return best if votes.count(best) >= 3 else None
