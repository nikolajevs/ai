#!/usr/bin/env python3
"""GrowBox controller enclosure (base + lid), parametric CadQuery; SPDX-License-Identifier: MIT.

Rebuild: python -m pip install cadquery==2.8.0
         python hardware/enclosure/enclosure.py            # STEP (board frame) + STL (print orientation)
Check:   python hardware/enclosure/check_enclosure.py      # interference / clearance against the board STEP

Frame (identical to the KiCad STEP export of PCB_V1): X = KiCad x, Y = -KiCad y, board bottom at Z = 0,
board top at Z = 1.6. KiCad coordinates are used for everything that is placed along a wall; sides are
named after the KiCad drawing: L = x 50 edge, R = x 150, T = y 50 (ESP32 antenna), B = y 150 (terminals).
Dimensions in mm. Design notes: hardware/enclosure/README.md.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import cadquery as cq

OUT = Path(__file__).resolve().parent

# ---------------------------------------------------------------- board and shell parameters
BX0, BX1 = 50.0, 150.0                 # board outline, STEP X
BY0, BY1 = -150.0, -50.0               # board outline, STEP Y
CTR = (100.0, -100.0)
BOARD_TOP = 1.6
GAP = 0.4                              # board edge to inner wall
T = 2.6                                # wall and plate thickness (skin + gap + tongue, 0.4 mm nozzle multiples)
IX0, IX1, IY0, IY1 = BX0 - GAP, BX1 + GAP, BY0 - GAP, BY1 + GAP
OX0, OX1, OY0, OY1 = IX0 - T, IX1 + T, IY0 - T, IY1 + T
R_IN = 0.5
R_OUT = R_IN + T

Z_BOT = -7.6                           # outside of the base floor (against the wall)
Z_FLOOR = -5.2                         # inner floor: BT301 bottom -4.19 + 1.0 mm
Z_LEDGE = 0.0                          # board rests here
Z_SPLIT = BOARD_TOP                    # joint plane between base and lid
Z_CEIL = 21.0                          # inner ceiling: F902 top 18.75 (not measured) + 2.25
Z_TOP = Z_CEIL + T

# lap joint: tongue on the base (inside), skin on the lid (outside), 0.2 mm clearance
TONGUE_T, SKIN_T, JOINT_GAP = 1.2, 1.2, 0.2
TONGUE_H, GROOVE_H = 9.0, 9.4
assert abs(T - (SKIN_T + JOINT_GAP + TONGUE_T)) < 1e-9
Z_TONGUE = Z_SPLIT + TONGUE_H

# ---------------------------------------------------------------- features (KiCad coordinates along a wall)
LEDGE_W, LEDGE_L = 2.0, 8.0            # board support blocks, 1.6 mm under the board edge
RIB_W, RIB_D = 4.0, 1.6                # lid ribs pressing on the board top, 1.2 mm over the board edge
RIBS = [('T', 58.0), ('T', 90.0), ('L', 72.7), ('L', 112.0), ('L', 140.0),
        ('R', 126.0), ('B', 53.4), ('B', 146.0)]
CORNER = 3.5                           # square ledge blocks in the four corners (J201 pin tails end 1.5 mm further)

# wall windows from the connector bodies (STEP bounding boxes, +0.5 mm per side); z top is absolute
NOTCHES = [
    ('L', 52.6, 70.2, 11.2, 'J901 XT60'),
    ('L', 75.3, 83.8, 10.8, 'J601 PTC'),
    ('L', 89.3, 97.8, 10.8, 'J521 PUMP'),
    ('B', 57.0, 68.7, 16.3, 'J711 LED1'),
    ('B', 74.0, 85.7, 16.3, 'J721 LED2'),
    ('B', 91.0, 102.7, 16.3, 'J731 LED3'),
    ('B', 106.3, 121.8, 10.8, 'J501 FAN1'),
    ('B', 126.3, 141.8, 10.8, 'J511 FAN2'),
    ('R', 79.9, 95.7, 4.65, 'J401 microSD'),
    ('R', 114.2, 122.7, 10.8, 'J302 FLOAT'),
]
# vertical connectors reached through the ceiling: x0, x1, y0, y1 in KiCad coordinates
CEIL_WINDOWS = [
    (141.8, 149.3, 96.4, 110.1, 'J301 SHT4x XH'),
    (144.2, 148.8, 129.8, 146.9, 'J201 UART header'),
]
# BOOT / RESET: guide tube from the ceiling down to the tact switch
BUTTONS = [(106.0, 71.0, 'SW201 RESET'), (104.0, 64.0, 'SW202 BOOT')]
TUBE_OD, TUBE_ID, TUBE_BOT = 6.4, 2.8, 4.5

# snap fit: windows in the lid skin (fingers), ridges on the base tongue
SNAPS = [('T', 66.0), ('T', 100.0), ('T', 134.0), ('L', 106.0), ('L', 130.0), ('R', 104.0), ('R', 134.0)]
SNAP_WIN = (3.8, 6.4)                  # window z range above the split
SNAP_HALF_WIN, SNAP_SLIT_IN, SNAP_SLIT_OUT = 3.0, 5.6, 6.4
RIDGE_P, RIDGE_RUN_LOW, RIDGE_RUN_UP = 0.6, 1.4, 1.2
PRY = [('T', 82.0), ('R', 62.0)]       # screwdriver notches at the lid bottom edge

# ventilation
CEIL_VENT_ZONES = [(63, 93, 56, 66), (63, 92, 76, 86), (94, 118, 76.5, 86.5), (84, 116, 90, 104),
                   (62, 138, 108, 124), (110, 137, 130, 139)]
VENT_W, VENT_PITCH, VENT_MAX_L = 2.0, 4.2, 16.0
LID_WALL_SLOTS = {'T': [74, 102, 116, 130, 144], 'L': [105, 118, 131, 144], 'R': [58, 70]}
LID_SLOT_Z, LID_SLOT_L = (13.5, 16.0), 10.0
BASE_WALL_SLOTS = {'L': [62, 92, 126], 'R': [64, 84, 104], 'T': [72, 106, 120, 134], 'B': [72, 88, 104, 124]}
BASE_SLOT_Z, BASE_SLOT_L = (-4.4, -1.0), 10.0

# wall mounting ears, Ø4.5 hole with a 90° countersink for a Ø8.6 head
EAR_R, EAR_T, EAR_HOLE, EAR_HEAD, EAR_DY = 6.0, 3.6, 4.5, 8.6, 46.0
EAR_OFFSET = 7.0


# ---------------------------------------------------------------- helpers
def box(x0, x1, y0, y1, z0, z1):
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0))


def kbox(kx0, kx1, ky0, ky1, z0, z1):
    return box(kx0, kx1, -ky1, -ky0, z0, z1)


def rrect(inset, z0, z1):
    """Rounded rectangle, inset mm inside the outer shell outline."""
    x0, x1, y0, y1 = OX0 + inset, OX1 - inset, OY0 + inset, OY1 - inset
    r = max(R_OUT - inset, 0.0)
    w = (cq.Workplane("XY").workplane(offset=z0).center((x0 + x1) / 2, (y0 + y1) / 2)
         .rect(x1 - x0, y1 - y0).extrude(z1 - z0))
    return w.edges("|Z").fillet(r) if r > 0.01 else w


def ring(inset_out, inset_in, z0, z1):
    return rrect(inset_out, z0, z1).cut(rrect(inset_in, z0 - 1, z1 + 1))


def wall_box(side, a0, a1, d0, d1, z0, z1):
    """Box on a wall: a0..a1 KiCad coordinate along the wall, d0..d1 depth inward from the outer face."""
    if side == 'L':
        return box(OX0 + d0, OX0 + d1, -a1, -a0, z0, z1)
    if side == 'R':
        return box(OX1 - d1, OX1 - d0, -a1, -a0, z0, z1)
    if side == 'T':
        return box(a0, a1, OY1 - d1, OY1 - d0, z0, z1)
    return box(a0, a1, OY0 + d0, OY0 + d1, z0, z1)


ROT = {'B': 0.0, 'R': 90.0, 'T': 180.0, 'L': 270.0}


def wall_point(side, c):
    return {'L': (OX0, -c), 'R': (OX1, -c), 'T': (c, OY1), 'B': (c, OY0)}[side]


def to_side(shape, side, c):
    """Place a feature built on wall B (centred on x = along) onto another wall at KiCad position c."""
    px, py = wall_point(side, c)
    a = math.radians(-ROT[side])
    dx, dy = px - CTR[0], py - CTR[1]
    along = CTR[0] + dx * math.cos(a) - dy * math.sin(a)
    return shape.translate((along, 0, 0)).rotate((CTR[0], CTR[1], 0), (CTR[0], CTR[1], 1), ROT[side])


def cut_all(body, tools):
    shape = body.val().cut(*[t.val() for t in tools])
    return cq.Workplane("XY").newObject([shape])


def fuse_all(body, parts):
    shape = body.val().fuse(*[p.val() for p in parts]).clean()
    return cq.Workplane("XY").newObject([shape])


def overlaps(a0, a1, intervals, margin):
    return any(a0 < b1 + margin and a1 > b0 - margin for b0, b1 in intervals)


# ---------------------------------------------------------------- base
def ridge(c, side):
    """Snap ridge on the outer face of the tongue (built on wall B, then moved)."""
    lo, hi = SNAP_WIN
    p = RIDGE_P
    za = Z_SPLIT + lo + JOINT_GAP - JOINT_GAP * RIDGE_RUN_LOW / p
    zb = za + RIDGE_RUN_LOW
    zd = Z_SPLIT + hi - JOINT_GAP + JOINT_GAP * RIDGE_RUN_UP / p
    zc = zd - RIDGE_RUN_UP
    y_t = OY0 + SKIN_T + JOINT_GAP                # tongue outer face
    pts = [(y_t + 0.2, za), (y_t, za), (y_t - p, zb), (y_t - p, zc), (y_t, zd), (y_t + 0.2, zd)]
    half = SNAP_HALF_WIN - 0.3
    prism = cq.Workplane("YZ").polyline(pts).close().extrude(2 * half).translate((-half, 0, 0))
    return to_side(prism, side, c)


def ear(sx, sy):
    hx = CTR[0] + sx * (OX1 - CTR[0] + EAR_OFFSET)
    hy = CTR[1] + sy * EAR_DY
    wall_x = CTR[0] + sx * (OX1 - CTR[0] - 1.0)
    lug = cq.Workplane("XY").workplane(offset=Z_BOT).center(hx, hy).circle(EAR_R).extrude(EAR_T)
    lug = lug.union(box(min(hx, wall_x), max(hx, wall_x), hy - EAR_R, hy + EAR_R, Z_BOT, Z_BOT + EAR_T))
    return lug, (hx, hy)


def build_base():
    outer = rrect(0, Z_BOT, Z_SPLIT).faces("<Z").chamfer(0.8)
    base = outer.cut(rrect(T, Z_FLOOR, Z_SPLIT + 1))
    parts = [ring(SKIN_T + JOINT_GAP, T, Z_SPLIT, Z_TONGUE)]
    # board supports: under every rib and in the corners
    for side, c in RIBS:
        parts.append(wall_box(side, c - LEDGE_L / 2, c + LEDGE_L / 2, T - 0.1, T + LEDGE_W, Z_FLOOR - 0.1, Z_LEDGE))
    for kx, sx in ((BX0 - GAP, 1), (BX1 + GAP, -1)):
        for ky, sy in ((BX0 - GAP, 1), (BX1 + GAP, -1)):
            parts.append(kbox(min(kx, kx + sx * CORNER), max(kx, kx + sx * CORNER),
                              min(ky, ky + sy * CORNER), max(ky, ky + sy * CORNER), Z_FLOOR - 0.1, Z_LEDGE))
    for side, c in SNAPS:
        parts.append(ridge(c, side))
    ears = [ear(sx, sy) for sx in (-1, 1) for sy in (-1, 1)]
    parts += [e[0] for e in ears]
    base = fuse_all(base, parts)
    tools = []
    for side, a0, a1, ztop, _ in NOTCHES:
        tools.append(wall_box(side, a0, a1, -1.0, T + 0.05, Z_SPLIT, ztop + 1.0))
    ledge_iv = {s: [(c - LEDGE_L / 2, c + LEDGE_L / 2) for sd, c in RIBS if sd == s] + [(50.0, 56.0), (144.0, 150.0)]
                for s in 'LRTB'}
    for side, centers in BASE_WALL_SLOTS.items():
        for c in centers:
            if overlaps(c - BASE_SLOT_L / 2, c + BASE_SLOT_L / 2, ledge_iv[side], 0.5):
                continue
            tools.append(wall_box(side, c - BASE_SLOT_L / 2, c + BASE_SLOT_L / 2, -1.0, T + 0.05, *BASE_SLOT_Z))
    for _, (hx, hy) in ears:
        tools.append(cq.Workplane("XY").workplane(offset=Z_BOT - 1).center(hx, hy).circle(EAR_HOLE / 2).extrude(EAR_T + 2))
        depth = (EAR_HEAD - EAR_HOLE) / 2
        cone = cq.Solid.makeCone(EAR_HOLE / 2, EAR_HEAD / 2 + 0.5, depth + 0.5,
                                 pnt=cq.Vector(hx, hy, Z_BOT + EAR_T - depth), dir=cq.Vector(0, 0, 1))
        tools.append(cq.Workplane("XY").newObject([cone]))
    return cut_all(base, tools)


# ---------------------------------------------------------------- lid
def build_lid():
    lid = rrect(0, Z_SPLIT, Z_TOP).faces(">Z").chamfer(1.0)
    lid = lid.cut(rrect(T, Z_SPLIT - 1, Z_CEIL))
    lid = lid.cut(rrect(SKIN_T, Z_SPLIT - 1, Z_SPLIT + GROOVE_H))
    parts = []
    for side, c in RIBS:                           # L-shaped rib: wall part above the groove, free part down to the board
        parts.append(wall_box(side, c - RIB_W / 2, c + RIB_W / 2, T - 0.3, T + RIB_D, Z_SPLIT + GROOVE_H, Z_CEIL + 0.1))
        parts.append(wall_box(side, c - RIB_W / 2, c + RIB_W / 2, T + JOINT_GAP, T + RIB_D, BOARD_TOP, Z_SPLIT + GROOVE_H + 0.5))
    for bx, by, _ in BUTTONS:
        tube = (cq.Workplane("XY").workplane(offset=TUBE_BOT).center(bx, -by).circle(TUBE_OD / 2)
                .extrude(Z_CEIL + 0.1 - TUBE_BOT))
        parts.append(tube)
    lid = fuse_all(lid, parts)

    tools = []
    for side, a0, a1, ztop, _ in NOTCHES:
        tools.append(wall_box(side, a0, a1, -1.0, T + 0.05, Z_SPLIT - 1, ztop))
    for x0, x1, y0, y1, _ in CEIL_WINDOWS:
        tools.append(kbox(x0, x1, y0, y1, Z_CEIL - 0.1, Z_TOP + 1))
    for bx, by, _ in BUTTONS:
        tools.append(cq.Workplane("XY").workplane(offset=TUBE_BOT - 1).center(bx, -by).circle(TUBE_ID / 2)
                     .extrude(Z_TOP + 2 - TUBE_BOT))
    lo, hi = SNAP_WIN
    for side, c in SNAPS:
        tools.append(wall_box(side, c - SNAP_HALF_WIN, c + SNAP_HALF_WIN, -1.0, SKIN_T + 0.05,
                              Z_SPLIT + lo, Z_SPLIT + hi))
        for sgn in (-1, 1):
            a0, a1 = sorted((c + sgn * SNAP_SLIT_IN, c + sgn * SNAP_SLIT_OUT))
            tools.append(wall_box(side, a0, a1, -1.0, SKIN_T + 0.05, Z_SPLIT - 1, Z_SPLIT + GROOVE_H - 0.6))
    for side, c in PRY:
        tools.append(wall_box(side, c - 4, c + 4, -1.0, SKIN_T + 0.05, Z_SPLIT - 1, Z_SPLIT + 1.2))
    excl = [(x0 - 2, x1 + 2, y0 - 2, y1 + 2) for x0, x1, y0, y1, _ in CEIL_WINDOWS]
    excl += [(bx - TUBE_OD / 2 - 2, bx + TUBE_OD / 2 + 2, by - TUBE_OD / 2 - 2, by + TUBE_OD / 2 + 2) for bx, by, _ in BUTTONS]
    for x0, x1, y0, y1 in CEIL_VENT_ZONES:
        n = int((x1 - x0 - VENT_W) // VENT_PITCH) + 1
        x_start = x0 + VENT_W / 2 + (x1 - x0 - VENT_W - (n - 1) * VENT_PITCH) / 2
        length = min(y1 - y0, VENT_MAX_L)
        yc = (y0 + y1) / 2
        for i in range(n):
            xc = x_start + i * VENT_PITCH
            if any(xc - VENT_W / 2 < ex1 and xc + VENT_W / 2 > ex0 and yc - length / 2 < ey1 and yc + length / 2 > ey0
                   for ex0, ex1, ey0, ey1 in excl):
                continue
            tools.append(cq.Workplane("XY").workplane(offset=Z_CEIL - 0.1).center(xc, -yc)
                         .slot2D(length, VENT_W, 90).extrude(T + 0.2))
    blocked = {s: [(a0, a1) for sd, a0, a1, zt, _ in NOTCHES if sd == s and zt > LID_SLOT_Z[0]]
               + [(c - RIB_W / 2, c + RIB_W / 2) for sd, c in RIBS if sd == s] for s in 'LRTB'}
    for side, centers in LID_WALL_SLOTS.items():
        for c in centers:
            if overlaps(c - LID_SLOT_L / 2, c + LID_SLOT_L / 2, blocked[side], 1.0):
                continue
            tools.append(wall_box(side, c - LID_SLOT_L / 2, c + LID_SLOT_L / 2, -1.0, T + 0.05, *LID_SLOT_Z))
    return cut_all(lid, tools)


# ---------------------------------------------------------------- output
COUPON_X = (93.0, 107.0)               # KiCad x range of the T-wall snap at x = 100, for a quick fit test print


def coupon(wp):
    cutter = box(COUPON_X[0], COUPON_X[1], OY1 - 7.0, OY1 + 1.0, Z_BOT - 1, Z_TOP + 1)
    return cq.Workplane("XY").newObject([wp.val().intersect(cutter.val())])


def print_orientation(wp, flip):
    s = wp.val()
    if flip:
        s = s.rotate(cq.Vector(0, 0, 0), cq.Vector(1, 0, 0), 180)
    bb = s.BoundingBox()
    return s.translate(cq.Vector(-bb.xmin, -bb.ymin, -bb.zmin))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-stl", action="store_true")
    args = ap.parse_args()
    base, lid = build_base(), build_lid()
    for name, wp, flip in (("base", base, False), ("lid", lid, True)):
        shape = wp.val()
        bb = shape.BoundingBox()
        print(f"{name}: {len(shape.Solids())} solid(s), volume {shape.Volume() / 1000:.1f} cm3, "
              f"x {bb.xmin:.1f}..{bb.xmax:.1f} y {bb.ymin:.1f}..{bb.ymax:.1f} z {bb.zmin:.1f}..{bb.zmax:.1f}")
        cq.exporters.export(wp, str(OUT / f"GrowBox_{name}.step"))
        if not args.no_stl:
            cq.exporters.export(cq.Workplane("XY").newObject([print_orientation(wp, flip)]),
                                str(OUT / f"GrowBox_{name}_print.stl"), tolerance=0.03, angularTolerance=0.15)
            cq.exporters.export(cq.Workplane("XY").newObject([print_orientation(coupon(wp), flip)]),
                                str(OUT / f"GrowBox_{name}_coupon_print.stl"), tolerance=0.03, angularTolerance=0.15)


if __name__ == "__main__":
    main()
