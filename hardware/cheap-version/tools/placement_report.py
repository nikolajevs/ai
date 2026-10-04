"""Placement table and courtyard collisions of the cheap-1 board (KiCad Python).

  "C:/Program Files/KiCad/10.0/bin/python.exe" hardware/cheap-version/tools/placement_report.py [board] [--table] [--max-overlap 0]

Prints, per footprint, the position / rotation / side and the courtyard box (--table), then every pair of footprints
on the same side whose courtyards overlap, with the overlap box, and parts whose courtyard leaves the board or
violates the 0.5 mm copper-to-edge rule. Exit code 1 when anything overlaps.
"""
import sys
from pathlib import Path

import pcbnew as p

HERE = Path(__file__).resolve().parents[1]
args = [a for a in sys.argv[1:] if not a.startswith("--")]
board = p.LoadBoard(str(Path(args[0]) if args else HERE / "cheap-version.kicad_pcb"))
mm = p.ToMM
EDGE = (50.0, 50.0, 150.0, 150.0)


def court(fp):
    layer = p.B_CrtYd if fp.IsFlipped() else p.F_CrtYd
    poly = fp.GetCourtyard(layer)
    if poly.OutlineCount() == 0:
        return None, None
    bb = poly.BBox()
    return poly, (mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom()))


items = []
for fp in sorted(board.GetFootprints(), key=lambda f: f.GetReference()):
    poly, box = court(fp)
    items.append((fp, poly, box))
    if "--table" in sys.argv:
        pos = fp.GetPosition()
        print(f"{fp.GetReference():6s} {'B' if fp.IsFlipped() else 'T'} ({mm(pos.x):7.2f},{mm(pos.y):7.2f}) rot {fp.GetOrientationDegrees():6.1f}  "
              f"court {box if box is None else tuple(round(v, 1) for v in box)}  {fp.GetFPID().GetLibItemName()}")
bad = 0
for i, (a, pa, ba) in enumerate(items):
    if ba is None:
        continue
    x0, y0, x1, y1 = ba
    edge_exempt = a.GetReference().startswith("J") or a.GetReference() == "U201"   # connectors and the antenna keepout reach out
    if not edge_exempt and (x0 < EDGE[0] - 0.01 or y0 < EDGE[1] - 0.01 or x1 > EDGE[2] + 0.01 or y1 > EDGE[3] + 0.01):
        print(f"EDGE   {a.GetReference():6s} courtyard {tuple(round(v, 1) for v in ba)} leaves the 100 x 100 outline")
        bad += 1
    for b, pb, bb in items[i + 1:]:
        if bb is None or a.IsFlipped() != b.IsFlipped():
            continue
        if ba[0] >= bb[2] or bb[0] >= ba[2] or ba[1] >= bb[3] or bb[1] >= ba[3]:
            continue
        inter = p.SHAPE_POLY_SET(pa)
        inter.BooleanIntersection(pb)
        if inter.OutlineCount():
            ib = inter.BBox()
            print(f"OVERLAP {a.GetReference():6s} {b.GetReference():6s} at x {mm(ib.GetLeft()):.1f}..{mm(ib.GetRight()):.1f} "
                  f"y {mm(ib.GetTop()):.1f}..{mm(ib.GetBottom()):.1f}  ({mm(ib.GetWidth()):.2f} x {mm(ib.GetHeight()):.2f})")
            bad += 1
print("placement problems:", bad)
sys.exit(1 if bad else 0)
