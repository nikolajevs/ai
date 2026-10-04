"""Legalise and tidy the cheap-1 placement by simulated annealing (KiCad Python for I/O, plain Python search).

  "C:/Program Files/KiCad/10.0/bin/python.exe" hardware/cheap-version/tools/auto_place.py [--seed N] [--steps N] [--write]

The board comes from make_board.py: the PCB_V1 placement with the cheap-1 footprints. Courtyards are treated as boxes
(all parts sit at multiples of 90 degrees). Energy = half-perimeter wire length of the signal nets (GND excluded)
+ a penalty for moving away from the start position / turning the part + a large penalty for courtyard overlap and for
leaving the 100 x 100 outline. PINNED parts never move; FIXED_AT parts are first put at the given place and then pinned.
Without --write the result is only reported.
"""
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

import pcbnew as p

HERE = Path(__file__).resolve().parents[1]
BOARD_PATH = HERE / "cheap-version.kicad_pcb"
mm = p.ToMM
MARGIN = 0.15            # extra clearance between courtyards
EDGE = 50.35             # courtyards of ordinary parts stay inside [EDGE, 150 - (EDGE - 50)]

# (x, y, rotation) - decided by hand, then pinned
FIXED_AT = {
    "L711": (70.9, 120.0, 0),          # DTMSS-27 standing, pads 62.15 / 79.65
    "J901": (56.3, 57.0, -90),          # KF301 flush with the left edge
    "R716": (71.0, 143.8, 90),         # LED1 return shunt between the terminals J711 and J721 (Kelvin tie follows)
}
NET_TIES = {"NT711": "R715", "NT712": "R716", "NT721": "R725", "NT722": "R726"}   # copper-only Kelvin ties follow their shunt
PINNED = {"U201", "BT301", "TP301", "TP101", "TP102", "TP103", "TP901", "TP902"}
CONNECTOR_PREFIX = "J"   # connectors keep their edge position (J901 is placed above)
FREE_BIG = {"C901"}      # big parts allowed to move but with a small leash
WEIGHT_DISP = 0.35       # mm of wire length per mm of displacement
WEIGHT_ROT = 3.0
OVERLAP_PENALTY = 400.0  # per mm2 of overlap
EDGE_PENALTY = 400.0     # per mm outside


def load(path):
    board = p.LoadBoard(str(path))
    parts = {}
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        layer = p.B_CrtYd if fp.IsFlipped() else p.F_CrtYd
        poly = fp.GetCourtyard(layer)
        if poly.OutlineCount() == 0:
            continue
        pos = fp.GetPosition()
        rot = int(round(fp.GetOrientationDegrees())) % 360
        assert rot % 90 == 0, (ref, rot)
        # local frame: undo position and rotation; a rectilinear courtyard becomes a union of boxes
        outline = poly.Outline(0)
        pts = [unrot((mm(outline.CPoint(k).x) - mm(pos.x), mm(outline.CPoint(k).y) - mm(pos.y)), rot)
               for k in range(outline.PointCount())]
        boxes = slabs(pts)
        pads = []
        for pad in fp.Pads():
            pp = pad.GetPosition()
            net = pad.GetNetname()
            pads.append((unrot((mm(pp.x) - mm(pos.x), mm(pp.y) - mm(pos.y)), rot), net))
        parts[ref] = dict(ref=ref, side=fp.IsFlipped(), x=mm(pos.x), y=mm(pos.y), rot=rot,
                          boxes=boxes, pads=pads)
    return board, parts


def slabs(pts):
    """rectangles covering a polygon: exact for rectilinear outlines, the bounding box otherwise"""
    xs = [q[0] for q in pts]
    ys = [q[1] for q in pts]
    bbox = (min(xs), min(ys), max(xs), max(ys))
    n = len(pts)
    rectilinear = all(abs(pts[i][0] - pts[(i + 1) % n][0]) < 1e-3 or abs(pts[i][1] - pts[(i + 1) % n][1]) < 1e-3 for i in range(n))
    if not rectilinear or n <= 4:
        return [bbox]
    levels = sorted({round(y, 3) for y in ys})
    out = []
    for y0, y1 in zip(levels, levels[1:]):
        ym = (y0 + y1) / 2
        cuts = sorted(round(pts[i][0], 3) for i in range(n)
                      if abs(pts[i][0] - pts[(i + 1) % n][0]) < 1e-3 and min(pts[i][1], pts[(i + 1) % n][1]) < ym < max(pts[i][1], pts[(i + 1) % n][1]))
        for xa, xb in zip(cuts[0::2], cuts[1::2]):
            out.append((xa, y0, xb, y1))
    return out or [bbox]


def unrot(pt, rot):
    """world offset -> footprint-local offset for a footprint rotated by rot degrees (KiCad: CCW on screen, Y down)"""
    x, y = pt
    t = math.radians(rot)
    # world = R(rot) * local with R acting on screen-CCW => in a Y-down frame x' = x cos + y sin, y' = -x sin + y cos
    return (x * math.cos(t) - y * math.sin(t), x * math.sin(t) + y * math.cos(t))


def rotate(pt, rot):
    x, y = pt
    t = math.radians(rot)
    return (x * math.cos(t) + y * math.sin(t), -x * math.sin(t) + y * math.cos(t))


def world_box(part, x, y, rot):
    out = []
    for x0, y0, x1, y1 in part["boxes"]:
        pts = [rotate((px, py), rot) for px, py in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        xs = [q[0] for q in pts]
        ys = [q[1] for q in pts]
        out.append((x + min(xs), y + min(ys), x + max(xs), y + max(ys)))
    return out


def hull(boxes):
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def pad_world(part, x, y, rot):
    return [(x + rotate(q, rot)[0], y + rotate(q, rot)[1], net) for q, net in part["pads"]]


def overlap(a_list, b_list):
    total = 0.0
    for a in a_list:
        for b in b_list:
            w = min(a[2], b[2]) - max(a[0], b[0]) + MARGIN
            h = min(a[3], b[3]) - max(a[1], b[1]) + MARGIN
            if w > 0 and h > 0:
                total += w * h
    return total


def main():
    seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 1
    steps = int(sys.argv[sys.argv.index("--steps") + 1]) if "--steps" in sys.argv else 150000
    random.seed(seed)
    board, parts = load(BOARD_PATH)
    start = {r: (q["x"], q["y"], q["rot"]) for r, q in parts.items()}
    for ref, (x, y, rot) in FIXED_AT.items():
        parts[ref]["x"], parts[ref]["y"], parts[ref]["rot"] = x, y, rot
    pinned = set(PINNED) | set(FIXED_AT) | {r for r in parts if r.startswith(CONNECTOR_PREFIX)}
    pinned &= set(parts)
    movable = [r for r in parts if r not in pinned]
    state = {r: [q["x"], q["y"], q["rot"]] for r, q in parts.items()}
    home = {r: (state[r][0], state[r][1], state[r][2]) for r in parts}
    for ref in FIXED_AT:
        home[ref] = tuple(state[ref])

    nets = defaultdict(list)          # net -> [(ref, pad index)]
    for ref, q in parts.items():
        for i, (_, net) in enumerate(q["pads"]):
            if net and net != "GND":
                nets[net].append((ref, i))
    part_nets = defaultdict(set)
    for net, items in nets.items():
        for ref, _ in items:
            part_nets[ref].add(net)

    def net_len(net):
        xs, ys = [], []
        for ref, i in nets[net]:
            x, y, rot = state[ref]
            rx, ry = rotate(parts[ref]["pads"][i][0], rot)
            xs.append(x + rx)
            ys.append(y + ry)
        return (max(xs) - min(xs)) + (max(ys) - min(ys)) if len(xs) > 1 else 0.0

    boxes = {r: world_box(parts[r], *state[r]) for r in parts}
    hulls = {r: hull(boxes[r]) for r in parts}

    def penalty_part(ref, box):
        pen = 0.0
        side = parts[ref]["side"]
        bh = hull(box)
        for other, ob in boxes.items():
            if other == ref or parts[other]["side"] != side:
                continue
            oh = hulls[other]
            if bh[0] >= oh[2] + MARGIN or oh[0] >= bh[2] + MARGIN or bh[1] >= oh[3] + MARGIN or oh[1] >= bh[3] + MARGIN:
                continue
            pen += overlap(box, ob)
        out = 0.0
        if ref not in pinned:
            out = (max(0.0, EDGE - bh[0]) + max(0.0, EDGE - bh[1]) + max(0.0, bh[2] - (200 - EDGE))
                   + max(0.0, bh[3] - (200 - EDGE)))
        return OVERLAP_PENALTY * pen + EDGE_PENALTY * out

    def disp_energy(ref, x, y, rot):
        hx, hy, hr = home[ref]
        scale = 0.25 if ref in FREE_BIG else 1.0
        return scale * WEIGHT_DISP * (abs(x - hx) + abs(y - hy)) + (WEIGHT_ROT if rot != hr else 0.0)

    def energy_of(ref, x, y, rot):
        e = disp_energy(ref, x, y, rot)
        old = state[ref][:]
        state[ref][:] = [x, y, rot]
        e += sum(net_len(n) for n in part_nets[ref])
        state[ref][:] = old
        return e

    def total_penalty():
        return sum(penalty_part(r, boxes[r]) for r in parts) / 2

    t0, t1 = 2.0, 0.02
    best_pen = total_penalty()
    print(f"start: overlap/edge penalty {best_pen:.1f}")
    for step in range(steps):
        T = t0 * (t1 / t0) ** (step / steps)
        ref = random.choice(movable)
        x, y, rot = state[ref]
        sigma = max(0.3, 6.0 * (1 - step / steps)) if random.random() < 0.7 else 0.4
        nx, ny, nrot = x + random.gauss(0, sigma), y + random.gauss(0, sigma), rot
        if random.random() < 0.08:
            nrot = (rot + random.choice((90, 180, 270))) % 360
        nx, ny = round(nx * 20) / 20, round(ny * 20) / 20
        nbox = world_box(parts[ref], nx, ny, nrot)
        old_e = energy_of(ref, x, y, rot) + penalty_part(ref, boxes[ref])
        new_e = energy_of(ref, nx, ny, nrot) + penalty_part(ref, nbox)
        d = new_e - old_e
        if d <= 0 or random.random() < math.exp(-d / T):
            state[ref] = [nx, ny, nrot]
            boxes[ref] = nbox
            hulls[ref] = hull(nbox)
        if step % 30000 == 0:
            print(f"step {step}: penalty {total_penalty():.1f}")
    final_pen = total_penalty()
    wl = sum(net_len(n) for n in nets)
    moved = sorted(((abs(state[r][0] - start[r][0]) + abs(state[r][1] - start[r][1]), r) for r in movable), reverse=True)
    print(f"final: penalty {final_pen:.2f}, signal HPWL {wl:.0f} mm; farthest moves:",
          ", ".join(f"{r} {d:.1f}" for d, r in moved[:12]))
    if "--write" in sys.argv:
        for nt, parent in NET_TIES.items():                  # keep each tie at the same place on its shunt pad
            ftie, fpar = board.FindFootprintByReference(nt), board.FindFootprintByReference(parent)
            ox, oy = mm(ftie.GetPosition().x) - start[parent][0], mm(ftie.GetPosition().y) - start[parent][1]
            lx, ly = unrot((ox, oy), start[parent][2])
            px, py, prot = state[parent]
            rx, ry = rotate((lx, ly), prot)
            ftie.SetPosition(p.VECTOR2I(p.FromMM(px + rx), p.FromMM(py + ry)))
            ftie.SetOrientationDegrees((ftie.GetOrientationDegrees() + prot - start[parent][2]) % 360)
        for ref, (x, y, rot) in state.items():
            fp = board.FindFootprintByReference(ref)
            fp.SetPosition(p.VECTOR2I(p.FromMM(x), p.FromMM(y)))
            fp.SetOrientationDegrees(rot)
        p.SaveBoard(str(BOARD_PATH), board)
        print("written", BOARD_PATH)


if __name__ == "__main__":
    main()
