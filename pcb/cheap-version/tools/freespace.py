"""Widest-corridor finder on the cheap-1 copper export (design aid for the power pours; not part of the build).

  python freespace.py board.json LAYER NET x0,y0 x1,y1 [--clear 0.4] [--region 50,50,150,150] [--png out.png] [--width 4]

LAYER is F|B|I1|I2, NET is the net the corridor belongs to (its own pads/tracks/vias/zones are not obstacles; GND zone
fills are ignored because power pours replace them). Prints the widest centre-line corridor between the two points that
keeps `--clear` to every foreign pad/track/via/zone and 0.5 mm to the board edge, then (with --width) the centre line of a
path of that width. Needs numpy, scipy and Pillow (any Python, not the KiCad one).
"""
import argparse
import json
import math

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

ap = argparse.ArgumentParser()
ap.add_argument("json")
ap.add_argument("layer")
ap.add_argument("net")
ap.add_argument("a")
ap.add_argument("b")
ap.add_argument("--clear", type=float, default=0.4)
ap.add_argument("--region", default="50,50,150,150")
ap.add_argument("--res", type=float, default=0.1)
ap.add_argument("--png")
ap.add_argument("--width", type=float)
ap.add_argument("--ignore-zones", action="store_true", help="treat every zone fill as removable (floods such as +3V3 on In2 give way to new copper)")
args = ap.parse_args()

X0, Y0, X1, Y1 = map(float, args.region.split(","))
RES = args.res
W, H = int(round((X1 - X0) / RES)), int(round((Y1 - Y0) / RES))
data = json.load(open(args.json))
layer = args.layer
LNAME = {"F": "F.Cu", "B": "B.Cu", "I1": "In1.Cu", "I2": "In2.Cu"}[layer]


def to_px(pt):
    return ((pt[0] - X0) / RES, (pt[1] - Y0) / RES)


img = Image.new("L", (W, H), 0)
d = ImageDraw.Draw(img)
# board edge: 0.1 mm inside the outline, the clearance below adds up to the 0.5 mm copper-to-edge rule
for box in [(X0, Y0, X1, 50.1), (X0, 149.9, X1, Y1), (X0, Y0, 50.1, Y1), (149.9, Y0, X1, Y1)]:
    if box[2] > box[0] and box[3] > box[1]:
        d.rectangle([(box[0] - X0) / RES, (box[1] - Y0) / RES, (box[2] - X0) / RES, (box[3] - Y0) / RES], fill=255)
net = args.net
for pad in data["pads"]:
    if pad["net"] == net:
        continue
    for poly in pad["layers"].get(layer, []):
        d.polygon([to_px(q) for q in poly["o"]], fill=255)
    if pad["drill"] > 0 and layer not in pad["layers"]:
        cx, cy = to_px((pad["x"], pad["y"]))
        r = pad["drill"] / 2 / RES
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
for t in data["tracks"]:
    if t["net"] == net or t["layer"] != LNAME:
        continue
    d.line([to_px((t["x0"], t["y0"])), to_px((t["x1"], t["y1"]))], fill=255, width=max(1, int(round(t["w"] / RES))))
    for q in ((t["x0"], t["y0"]), (t["x1"], t["y1"])):
        cx, cy = to_px(q)
        r = t["w"] / 2 / RES
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
for v in data["vias"]:
    if v["net"] == net:
        continue
    cx, cy = to_px((v["x"], v["y"]))
    r = v["d"] / 2 / RES
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
for z in data["zones"]:
    if args.ignore_zones or z["layer"] != layer or z["net"] in (net, "GND"):
        continue
    for poly in z["polys"]:
        d.polygon([to_px(q) for q in poly["o"]], fill=255)
        for hole in poly["h"]:
            d.polygon([to_px(q) for q in hole], fill=0)
obst = np.array(img) > 0
# distance from every pixel centre to the nearest obstacle pixel, in mm
dist = ndimage.distance_transform_edt(~obst) * RES
A = tuple(int(round(v)) for v in to_px(tuple(map(float, args.a.split(",")))))
B = tuple(int(round(v)) for v in to_px(tuple(map(float, args.b.split(",")))))


def mask_for(width):
    return dist >= args.clear + width / 2


def connected(width):
    m = mask_for(width)
    lab, _ = ndimage.label(m, structure=np.ones((3, 3)))
    la, lb = lab[A[1], A[0]], lab[B[1], B[0]]
    return la != 0 and la == lb


# the end points sit on pads of the net itself; allow a 3 mm neighbourhood to attach
lo, hi = 0.0, 14.0
if not connected(0.2):
    print("no connection even for a 0.2 mm track (end points may sit inside the clearance of a foreign item)")
else:
    for _ in range(14):
        mid = (lo + hi) / 2
        if connected(mid):
            lo = mid
        else:
            hi = mid
    print(f"widest corridor {args.a} -> {args.b} on {LNAME}: {lo:.2f} mm (clearance {args.clear})")

target = args.width or lo * 0.98
if lo > 0.2 and args.png or args.width:
    m = mask_for(target)
    ys, xs = np.nonzero(m)
    idx = -np.ones(m.shape, dtype=np.int64)
    idx[ys, xs] = np.arange(len(xs))
    rows, cols, costs = [], [], []
    for dy, dx in [(0, 1), (1, 0), (1, 1), (1, -1)]:
        y2, x2 = ys + dy, xs + dx
        ok = (y2 >= 0) & (y2 < H) & (x2 >= 0) & (x2 < W)
        ok[ok] = m[y2[ok], x2[ok]]
        rows += list(idx[ys[ok], xs[ok]])
        cols += list(idx[y2[ok], x2[ok]])
        costs += [math.hypot(dx, dy)] * int(ok.sum())
    g = csr_matrix((costs, (rows, cols)), shape=(len(xs), len(xs)))
    ia, ib = idx[A[1], A[0]], idx[B[1], B[0]]
    if ia < 0 or ib < 0:
        print("end point outside the free mask at width", round(target, 2))
    else:
        dd, pred = dijkstra(g, directed=False, indices=ia, return_predecessors=True)
        path = []
        k = ib
        while k != ia and k >= 0:
            path.append((xs[k], ys[k]))
            k = pred[k]
        path.append((xs[ia], ys[ia]))
        path.reverse()
        pts = [(X0 + x * RES, Y0 + y * RES) for x, y in path]

        def simplify(points, eps):
            if len(points) < 3:
                return points
            (ax, ay), (bx, by) = points[0], points[-1]
            n = math.hypot(bx - ax, by - ay) or 1e-9
            far, fi = 0, 0
            for i, (px, py) in enumerate(points[1:-1], 1):
                dd_ = abs((bx - ax) * (ay - py) - (ax - px) * (by - ay)) / n
                if dd_ > far:
                    far, fi = dd_, i
            if far > eps:
                return simplify(points[:fi + 1], eps)[:-1] + simplify(points[fi:], eps)
            return [points[0], points[-1]]

        print(f"path at {target:.2f} mm width:", [(round(x, 1), round(y, 1)) for x, y in simplify(pts, 0.4)])
        if args.png:
            rgb = np.zeros((H, W, 3), dtype=np.uint8) + 255
            rgb[mask_for(0.2) & ~m] = (210, 235, 210)
            rgb[m] = (150, 215, 150)
            rgb[dist < args.clear] = (230, 150, 150)
            rgb[obst] = (70, 70, 70)
            out = Image.fromarray(rgb)
            od = ImageDraw.Draw(out)
            od.line([to_px(q) for q in pts], fill=(0, 0, 255), width=2)
            for i in range(int(X0), int(X1) + 1, 5):
                od.line([((i - X0) / RES, 0), ((i - X0) / RES, H)], fill=(0, 0, 0), width=1)
                od.text(((i - X0) / RES + 2, 2), str(i), fill=(0, 0, 0))
            for j in range(int(Y0), int(Y1) + 1, 5):
                od.line([(0, (j - Y0) / RES), (W, (j - Y0) / RES)], fill=(0, 0, 0), width=1)
                od.text((2, (j - Y0) / RES + 2), str(j), fill=(0, 0, 0))
            out.save(args.png)
            print("wrote", args.png)
