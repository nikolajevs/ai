"""Drawing helpers of the assembly document (system Python with Pillow): board tiles, overviews and polarity cards.

Data comes from export_assembly.py (assembly.json). Everything is drawn in board millimetres and scaled to pixels; the
bottom side is drawn mirrored (as the operator sees the board turned over).
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path(r'C:\Windows\Fonts')
BOARD = (50.0, 50.0, 150.0, 150.0)
STEP_COLORS = {1: (150, 70, 200), 2: (225, 50, 50), 3: (240, 135, 20), 4: (30, 100, 220), 5: (20, 160, 80),
               6: (0, 160, 180), 7: (140, 100, 40), 8: (200, 30, 140), 9: (70, 70, 70), 10: (110, 50, 150)}
FAINT_PAD, FAINT_SILK = (214, 214, 214), (190, 190, 190)
GOLD = (233, 196, 90)


def font(size, bold=False):
    for name in (('arialbd.ttf' if bold else 'arial.ttf'), 'DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(str(FONT_DIR / name), int(size))
        except OSError:
            continue
    return ImageFont.load_default()


class View:
    """a rectangle of the board mapped to pixels; mirror for the bottom side"""

    def __init__(self, region, scale, mirror=False):
        self.x0, self.y0, self.x1, self.y1 = region
        self.s = scale
        self.mirror = mirror
        self.w = int(round((self.x1 - self.x0) * scale))
        self.h = int(round((self.y1 - self.y0) * scale))

    def px(self, x, y):
        u = (x - self.x0) * self.s
        if self.mirror:
            u = self.w - u
        return (u, (y - self.y0) * self.s)

    def inside(self, bbox, margin=0.0):
        return not (bbox[2] < self.x0 - margin or bbox[0] > self.x1 + margin or bbox[3] < self.y0 - margin or bbox[1] > self.y1 + margin)


def poly_bbox(polys):
    xs = [q[0] for p in polys for q in p['o']]
    ys = [q[1] for p in polys for q in p['o']]
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def fp_bbox(fp):
    """bounding box of the pads of a footprint (the part body for the label placement)"""
    boxes = [poly_bbox(p['poly']) for p in fp['pads'] if p['poly']]
    boxes = [b for b in boxes if b]
    if fp['court']:
        boxes.append(poly_bbox(fp['court']))
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def pads_bbox(fp):
    boxes = [poly_bbox(p['poly']) for p in fp['pads'] if p['poly']]
    boxes = [b for b in boxes if b]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def fill_polys(d, view, polys, color):
    for poly in polys:
        pts = [view.px(*q) for q in poly['o']]
        if len(pts) >= 3:
            d.polygon(pts, fill=color)
        for hole in poly['h']:
            pts = [view.px(*q) for q in hole]
            if len(pts) >= 3:
                d.polygon(pts, fill=(255, 255, 255))


def draw_fp(d, view, fp, color=None, faint=False, step_color=None):
    """pads (coloured by the assembly step), silkscreen and fab outline of one footprint"""
    padc = FAINT_PAD if faint else (step_color or GOLD)
    for poly in fp['fab']:
        fill_polys(d, view, [poly], (225, 225, 225) if faint else (160, 160, 160))
    for pad in fp['pads']:
        fill_polys(d, view, pad['poly'], padc)
        if pad['drill'] > 0:
            cx, cy = view.px(pad['x'], pad['y'])
            r = pad['drill'] / 2 * view.s
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255), outline=(90, 90, 90) if not faint else (200, 200, 200))
    for poly in fp['silk']:
        fill_polys(d, view, [poly], FAINT_SILK if faint else (0, 0, 0))


def overlaps(a, b, pad=0):
    return not (a[2] + pad < b[0] or b[2] + pad < a[0] or a[3] + pad < b[1] or b[3] + pad < a[1])


class Labeler:
    """greedy label placement: the label goes next to its part where it covers no pad and no other label"""

    def __init__(self, view, obstacles):
        self.view = view
        self.boxes = []                      # pixel boxes of placed labels
        self.obstacles = obstacles           # pixel boxes of pads of every part in view
        self.gaps = (4, 10, 18, 28, 40, 56, 76, 100)

    def place(self, d, bbox_mm, lines, color, fonts, anchor_pad_boxes=()):
        v = self.view
        (ux0, uy0), (ux1, uy1) = v.px(bbox_mm[0], bbox_mm[1]), v.px(bbox_mm[2], bbox_mm[3])
        ux0, ux1 = sorted((ux0, ux1))
        uy0, uy1 = sorted((uy0, uy1))
        cx, cy = (ux0 + ux1) / 2, (uy0 + uy1) / 2
        sizes = [d.textbbox((0, 0), t, font=f) for t, f in zip(lines, fonts)]
        w = max(s[2] - s[0] for s in sizes) + 6
        h = sum(s[3] - s[1] + 4 for s in sizes) + 2
        cands = [(cx, cy)]
        for gap in self.gaps:
            cands += [(cx, uy0 - gap - h / 2), (cx, uy1 + gap + h / 2), (ux0 - gap - w / 2, cy), (ux1 + gap + w / 2, cy),
                      (ux0 - gap - w / 2, uy0 - gap - h / 2), (ux1 + gap + w / 2, uy0 - gap - h / 2),
                      (ux0 - gap - w / 2, uy1 + gap + h / 2), (ux1 + gap + w / 2, uy1 + gap + h / 2)]
        best, best_cost = None, None
        for x, y in cands:
            box = (x - w / 2, y - h / 2, x + w / 2, y + h / 2)
            if box[0] < 2 or box[1] < 2 or box[2] > v.w - 2 or box[3] > v.h - 2:
                continue
            cost = sum(overlaps(box, b) for b in self.boxes) * 1000 + sum(overlaps(box, b) for b in self.obstacles) * 3
            if best_cost is None or cost < best_cost:
                best, best_cost = (x, y, box), cost
            if cost == 0:
                break
        if best is None:
            best = (cx, cy, (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))
        x, y, box = best[:3]
        # white halo plate, coloured text
        d.rounded_rectangle([box[0], box[1], box[2], box[3]], radius=3, fill=(255, 255, 255, 235), outline=color, width=1)
        ty = box[1] + 2
        for t, f, s in zip(lines, fonts, sizes):
            d.text((x - (s[2] - s[0]) / 2 - s[0], ty - s[1]), t, font=f, fill=color if f is fonts[0] else (60, 60, 60))
            ty += s[3] - s[1] + 4
        self.boxes.append(box)
        if not (box[0] <= cx <= box[2] and box[1] <= cy <= box[3]):
            ex = min(max(cx, box[0]), box[2])
            ey = min(max(cy, box[1]), box[3])
            d.line([(ex, ey), (cx, cy)], fill=color, width=2)
        return box


def badge(d, view, x, y, text, color=(210, 0, 0), r_mm=0.42, f=None):
    """round marker with 1-3 characters, centred at board position (x, y)"""
    cx, cy = view.px(x, y)
    r = r_mm * view.s
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255), outline=color, width=max(2, int(view.s * 0.06)))
    f = f or font(max(10, r * (1.25 if len(text) == 1 else 0.95)), True)
    bb = d.textbbox((0, 0), text, font=f)
    d.text((cx - (bb[2] - bb[0]) / 2 - bb[0], cy - (bb[3] - bb[1]) / 2 - bb[1]), text, font=f, fill=color)


def pad_center(fp, number):
    sel = [p for p in fp['pads'] if p['n'] == str(number)]
    if not sel:
        return None
    # big tab pads: the centre of the bounding box of all pads with the number
    boxes = [poly_bbox(p['poly']) for p in sel if p['poly']]
    return ((min(b[0] for b in boxes) + max(b[2] for b in boxes)) / 2, (min(b[1] for b in boxes) + max(b[3] for b in boxes)) / 2)


def marker_position(fp, number, outward=True, size_mm=0.42):
    """where to put the badge for a pad: beside the pad, away from the part centre (on the pad itself when it is a tab)"""
    c = pad_center(fp, number)
    pb = poly_bbox([p['poly'][0] for p in fp['pads'] if p['n'] == str(number) and p['poly']])
    bb = pads_bbox(fp)
    mx, my = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
    pw, ph = pb[2] - pb[0], pb[3] - pb[1]
    if pw > 2.0 and ph > 2.0:                       # a tab or a large pad: the badge sits on it
        return c
    dx, dy = c[0] - mx, c[1] - my
    n = math.hypot(dx, dy)
    if n < 0.2:
        dx, dy, n = 0.0, -1.0, 1.0
    # step out of the pad along the dominant axis
    if abs(dx) >= abs(dy):
        return (c[0] + math.copysign(pw / 2 + size_mm + 0.15, dx), c[1])
    return (c[0], c[1] + math.copysign(ph / 2 + size_mm + 0.15, dy))
