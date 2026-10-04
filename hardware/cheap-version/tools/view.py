"""Zoomable copper view of the cheap-1 board with a millimetre grid (PIL; run with any Python that has Pillow).

  python view.py board.json out.png --region 50,50,100,100 [--layer F|B|I1|I2] [--scale 24] [--no-zones] [--nets]

Pads, tracks, vias and zone fills are coloured by net (power nets have fixed colours, GND grey); courtyards are thin
outlines; reference designators are written at the footprint origins; the grid has a line every mm (light) and every
5 mm (labelled). Used to design the power pours and to inspect routing.
"""
import argparse
import json
import zlib

from PIL import Image, ImageDraw, ImageFont

ap = argparse.ArgumentParser()
ap.add_argument("json")
ap.add_argument("out")
ap.add_argument("--region", default="50,50,150,150")
ap.add_argument("--layer", default="F")
ap.add_argument("--scale", type=float, default=12.0)
ap.add_argument("--no-zones", action="store_true")
ap.add_argument("--no-tracks", action="store_true")
ap.add_argument("--no-courtyards", action="store_true")
args = ap.parse_args()
x0, y0, x1, y1 = map(float, args.region.split(","))
S = args.scale
W, H = int((x1 - x0) * S), int((y1 - y0) * S)
data = json.load(open(args.json))

NETCOL = {"GND": (150, 150, 150), "+24V": (220, 30, 30), "+24V_LOADS": (235, 120, 20), "+12V": (30, 150, 60), "+3V3": (30, 90, 220)}


def color(net):
    if net in NETCOL:
        return NETCOL[net]
    if not net:
        return (120, 120, 120)
    h = zlib.crc32(net.encode())
    return (60 + h % 150, 60 + (h >> 8) % 150, 60 + (h >> 16) % 150)


def px(pt):
    return ((pt[0] - x0) * S, (pt[1] - y0) * S)


base = Image.new("RGB", (W, H), (255, 255, 255))
d = ImageDraw.Draw(base, "RGBA")
# grid
for i in range(int(x0), int(x1) + 1):
    gx = (i - x0) * S
    d.line([(gx, 0), (gx, H)], fill=(0, 0, 0, 70 if i % 5 == 0 else 18), width=1)
for j in range(int(y0), int(y1) + 1):
    gy = (j - y0) * S
    d.line([(0, gy), (W, gy)], fill=(0, 0, 0, 70 if j % 5 == 0 else 18), width=1)
font = ImageFont.load_default()
layer = args.layer
if not args.no_zones:
    for z in data["zones"]:
        if z["layer"] != layer:
            continue
        c = color(z["net"])
        for poly in z["polys"]:
            if max(q[0] for q in poly["o"]) < x0 or min(q[0] for q in poly["o"]) > x1 or max(q[1] for q in poly["o"]) < y0 or min(q[1] for q in poly["o"]) > y1:
                continue
            d.polygon([px(q) for q in poly["o"]], fill=c + (70,))
            for hole in poly["h"]:
                d.polygon([px(q) for q in hole], fill=(255, 255, 255, 255))
if not args.no_tracks:
    for t in data["tracks"]:
        if t["layer"].split(".")[0].replace("In", "I").replace("Cu", "") not in (layer, layer + "Cu"):
            name = {"F.Cu": "F", "B.Cu": "B", "In1.Cu": "I1", "In2.Cu": "I2"}[t["layer"]]
            if name != layer:
                continue
        d.line([px((t["x0"], t["y0"])), px((t["x1"], t["y1"]))], fill=color(t["net"]) + (230,), width=max(1, int(t["w"] * S)))
    for v in data["vias"]:
        c = px((v["x"], v["y"]))
        r = v["d"] / 2 * S
        d.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], fill=color(v["net"]) + (255,), outline=(0, 0, 0, 255))
        r = v["drill"] / 2 * S
        d.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], fill=(255, 255, 255, 255))
for pad in data["pads"]:
    polys = pad["layers"].get(layer)
    if not polys:
        continue
    c = color(pad["net"])
    for poly in polys:
        d.polygon([px(q) for q in poly["o"]], fill=c + (200,), outline=(0, 0, 0, 255))
    if pad["drill"] > 0:
        r = pad["drill"] / 2 * S
        cx, cy = px((pad["x"], pad["y"]))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 255), outline=(0, 0, 0, 255))
if not args.no_courtyards:
    side = "B" if layer == "B" else "F"
    for cy in data["courtyards"]:
        if cy["side"] != side:
            continue
        for poly in cy["polys"]:
            pts = [px(q) for q in poly["o"]]
            d.line(pts + [pts[0]], fill=(200, 0, 200, 170), width=1)
        cx, cyy = px((cy["x"], cy["y"]))
        d.text((cx + 2, cyy + 2), cy["ref"], fill=(0, 0, 160, 255), font=font)
for i in range(int(x0), int(x1) + 1, 5):
    d.text(((i - x0) * S + 2, 2), str(i), fill=(0, 0, 0, 255), font=font)
for j in range(int(y0), int(y1) + 1, 5):
    d.text((2, (j - y0) * S + 2), str(j), fill=(0, 0, 0, 255), font=font)
base.save(args.out)
print("wrote", args.out, W, "x", H)
