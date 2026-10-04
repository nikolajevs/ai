#!/usr/bin/env python3
"""Own, simplified GrowBox mechanical models; SPDX-License-Identifier: MIT.

Rebuild: python -m pip install cadquery==2.6.1
         python hardware/models3d/mechanical.py
Check:   python hardware/models3d/mechanical.py --check

Dimensions in mm. STEP X = footprint X, STEP Y = -footprint Y, STEP Z points
away from the component-side PCB surface (Z=0). KiCad applies the backside
transform to BT301; do not mirror its model. See SOURCES_mechanical.md for
drawings, limitations and the licence. No third-party CAD geometry is used.
"""
from __future__ import annotations

import argparse
import math
import re
from dataclasses import dataclass
from pathlib import Path

import cadquery as cq
from OCP.Interface import Interface_Static

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "hardware/PCB_V1/libraries"
OUT = LIB / "GrowBox.3dshapes"
GREEN = cq.Color(0.08, 0.40, 0.20)
BLACK = cq.Color(0.09, 0.09, 0.10)
YELLOW = cq.Color(0.95, 0.72, 0.08)
METAL = cq.Color(0.72, 0.73, 0.75)
GOLD = cq.Color(0.82, 0.63, 0.21)
RED = cq.Color(0.90, 0.08, 0.05)


@dataclass
class Model:
    name: str
    assembly: cq.Assembly
    height: float
    # Physical metal at the PCB plane, grouped by footprint pad number.
    pins: list[tuple[str, cq.Workplane]]
    envelope: tuple[float, float, float, float]  # Xmin, Xmax, Ymin, Ymax


def box(x, y, z, dx, dy, dz):
    return cq.Workplane("XY").box(dx, dy, dz, centered=False).translate((x, y, z))


def cylinder(x, y, z, radius, height):
    return cq.Workplane("XY").circle(radius).extrude(height).translate((x, y, z))


def add(assembly, shape, name, color):
    assembly.add(shape, name=name, color=color)


def terminal(name, poles, pitch, back, front, height, pin_width, pin_depth,
             tail, screw_radius, screw_y, lock=0.0):
    """Extruded side outline, front wire windows, recessed slotted screws."""
    assy = cq.Assembly(name=name)
    # Local YZ extrusion: mounting-face datum, pins at X = i*pitch.
    outline = [(-front, 0), (back, 0), (back, height * .64),
               (back - .75, height * .64), (back - 1.6, height),
               (-front + 1.3, height), (-front + .45, height * .60),
               (-front, height * .56)]
    body = cq.Workplane("YZ").polyline(outline).close().extrude(poles * pitch)
    body = body.translate((-pitch / 2, 0, 0))
    pins = []
    for i in range(poles):
        x = i * pitch
        # Undimensioned window/screw details are illustrative, inside the envelope.
        window = box(x - pitch * .31, -front - .1, height * .15,
                     pitch * .62, 2.0, height * .36)
        recess = cylinder(x, screw_y, height - 1.15, screw_radius + .12, 1.3)
        body = body.cut(window).cut(recess)
        screw = cylinder(x, screw_y, height - 1.15, screw_radius, .75)
        screw = screw.cut(box(x - screw_radius - .1, screw_y - .18, height - .7,
                             2 * screw_radius + .2, .36, .45))
        add(assy, screw, f"screw_{i + 1}", METAL)
        # 0.85x0.50 / 0.90x0.80 tails, as dimensioned in front/side views.
        pin = box(x - pin_width / 2, -pin_depth / 2, -tail,
                  pin_width, pin_depth, tail + .7)
        add(assy, pin, f"pin_{i + 1}", METAL)
        pins.append((str(i + 1), pin))
        cage = box(x - pitch * .24, -front + 1.7, height * .19,
                   pitch * .48, .2, height * .24)
        add(assy, cage, f"cage_{i + 1}", METAL)
    # Moulded side interlock protrusions: included in the physical envelope.
    if lock:
        end = (-pitch / 2 - lock) if pitch == 3.5 else (poles - .5) * pitch
        for y in (-front + .5, back - .8):
            body = body.union(box(end, y, height * .4, lock, .5, height * .3))
    add(assy, body, "housing", GREEN)
    xmin = -pitch / 2 - (lock if pitch == 3.5 else 0)
    xmax = (poles - .5) * pitch + (lock if pitch != 3.5 else 0)
    return Model(name, assy, height, pins, (xmin, xmax, -front, back))


def xt60():
    name = "AMASS_XT60PW-M_1x02_P7.20mm_Horizontal"
    assy = cq.Assembly(name=name)
    # Footprint mating face Y=-16.35 -> STEP Y=+16.35. Width 15.50,
    # depth 18.20, height 8.40 per Amass 2025V0. Pin 1 at (0,0).
    section = [(-4.15, 2.0), (-2.15, 0), (9.35, 0), (11.35, 2.0),
               (11.35, 8.4), (-4.15, 8.4)]
    # XZ plane extrudes toward -Y; start at the mating face.
    body = cq.Workplane("XZ").polyline(section).close().extrude(18.2)
    body = body.translate((0, 16.35, 0))
    pins = []
    for i, x in enumerate((0, 7.2), 1):
        cavity = cq.Solid.makeCylinder(3.0, 8.5, cq.Vector(x, 8, 4.2), cq.Vector(0, 1, 0))
        body = body.cut(cq.Workplane(obj=cavity))
        vertical = cylinder(x, 0, -3.0, 1.35, 7.2)
        horizontal = cq.Workplane(obj=cq.Solid.makeCylinder(
            1.75, 15.0, cq.Vector(x, 0, 4.2), cq.Vector(0, 1, 0)))
        contact = vertical.union(horizontal)
        add(assy, contact, f"contact_{i}", GOLD)
        pins.append((str(i), vertical))
    for i, x in enumerate((-3.15, 10.35), 1):
        tab = box(x - .35, 6 - .9, -3.5, .7, 1.8, 3.9)
        add(assy, tab, f"mounting_tab_{i}", METAL)
        pins.append(("", tab))
    add(assy, body, "housing", YELLOW)
    return Model(name, assy, 8.4, pins, (-4.15, 11.35, -1.85, 16.35))


def fuseholder():
    name = "Fuseholder_Blade_Mini_XFCN_XF-508P"
    assy = cq.Assembly(name=name)
    # XFCN A1 2023-11-25 variant: 9.80 x 3.40, NOT the later 9.92 variant.
    body = box(-3.1, -5.05, 0, 16.0, 6.7, 7.35).edges("|Z").fillet(.35)
    pins = []
    for number, x in (("1", 0), ("2", 9.8)):
        body = body.cut(box(x - 2.0, -4.0, .85, 4.0, 4.6, 6.6))
        for row, y in enumerate((0, -3.4)):
            pin = box(x - .8, y - .2, -2.85, 1.6, .4, 3.9)
            add(assy, pin, f"pin_{number}_{row}", METAL)
            pins.append((number, pin))
        for side, y in enumerate((-2.3, -.9)):
            clip = box(x - 1.7, y - .2, 1.05, 3.4, .4, 5.7)
            add(assy, clip, f"clip_{number}_{side}", METAL)
    add(assy, body, "holder", BLACK)
    # MINI 297: 10.9 wide, 3.8 thick, body 8.8 high, blades 7.5 long,
    # 2.8 wide / .825 thick. Insertion depth is NOT specified by XFCN.
    # Assembly assumption: blade tips rest at the illustrated well floor Z=.85,
    # so the shoulder is .85+7.50=8.35, 1 mm above the holder top. Neither
    # manufacturer specifies insertion depth: this is NOT a qualified height.
    shoulder = .85 + 7.5
    fuse_x = 4.9 - 10.9 / 2
    add(assy, box(fuse_x, -1.7 - 1.9, shoulder, 10.9, 3.8, 8.8), "mini_10A_body", RED)
    for i, x in enumerate((4.9 - 8.1 / 2, 4.9 + 8.1 / 2), 1):
        blade = box(x - 1.4, -1.7 - .825 / 2, shoulder - 7.5, 2.8, .825, 7.5)
        add(assy, blade, f"mini_blade_{i}", METAL)
    return Model(name, assy, 17.15, pins, (-3.1, 12.9, -5.05, 1.65))


def battery():
    name = "BatteryHolder_MYOUNG_BS-07-A1BJ001_CR2032"
    assy = cq.Assembly(name=name)
    # MY-CP-0292 A/0, pin 1 = + at X=0; circle centre 12.4, pin 2=20.8.
    base = cylinder(12.4, 0, 0, 11.6, 1.0)
    rim = cylinder(12.4, 0, 1.0, 11.6, 3.1).cut(cylinder(12.4, 0, .9, 10.2, 3.3))
    # Finger openings are visual approximations; retain the circular envelope.
    rim = rim.cut(box(7.4, -12, 1.8, 10, 24, 2.5))
    latch = box(-2.6, -2.875, 0, 3.75, 5.75, 4.1)
    body = base.union(rim).union(latch)
    add(assy, body, "housing", BLACK)
    plus = box(-.4, -.25, -3.1, .8, .5, 3.7)
    minus = box(20.4, -.25, -3.1, .8, .5, 3.7)
    add(assy, plus, "positive_tail", METAL)
    add(assy, minus, "negative_tail", METAL)
    # Simplified raised spring and floor contact; CR2032 cell is not included.
    spring = box(0, -1.55, 3.4, 18, 3.1, .5)
    add(assy, spring, "positive_spring", METAL)
    add(assy, box(10.4, -2.5, 1, 11, 5, .3), "negative_contact", METAL)
    return Model(name, assy, 4.1, [("1", plus), ("2", minus)], (-2.6, 24, -11.6, 11.6))


def switch():
    name = "SW_Push_1P1T_XKB_TS-1187A"
    assy = cq.Assembly(name=name)
    # TS-1187A-X-X-X A0: B force, A height=1.50, B brass actuator.
    outline = [(-2.55, -1.25), (-1.25, -2.55), (1.25, -2.55), (2.55, -1.25),
               (2.55, 1.25), (1.25, 2.55), (-1.25, 2.55), (-2.55, 1.25)]
    base = cq.Workplane("XY").polyline(outline).close().extrude(.9)
    cover = cq.Workplane("XY").polyline(outline).close().extrude(.3).translate((0, 0, .9))
    cover = cover.cut(cylinder(0, 0, .85, 1.05, .5))
    add(assy, base, "base", BLACK)
    add(assy, cover, "cover", METAL)
    add(assy, cylinder(0, 0, 1.1, 1.0, .4), "brass_actuator", GOLD)
    pins = []
    # Drawing lead outer span 6.50, lead row pitch 3.70; lands use 3.75.
    # Each 0.50-wide tail overlaps its complete 1.00x0.75 land with margin.
    for num, y in (("1", 1.85), ("2", -1.85)):
        for side, x in (("L", -3.25), ("R", 2.5)):
            pin = box(x, y - .25, 0, .75, .5, .3)
            add(assy, pin, f"terminal_{num}_{side}", METAL)
            pins.append((num, pin))
    return Model(name, assy, 1.5, pins, (-3.25, 3.25, -2.55, 2.55))


def models():
    return [xt60(),
            terminal("TerminalBlock_DORABO_DB125-3.5_1x02_P3.50mm_Horizontal",
                     2, 3.5, 3.9, 3.5, 8.6, .85, .5, 3.4, 1.25, -.1, .42),
            terminal("TerminalBlock_DORABO_DB125-3.5_1x04_P3.50mm_Horizontal",
                     4, 3.5, 3.9, 3.5, 8.6, .85, .5, 3.4, 1.25, -.1, .42),
            terminal("TerminalBlock_KANGNEX_WJ500V-5.08_1x02_P5.08mm_Horizontal",
                     2, 5.08, 4.5, 5.5, 14.07, .90, .80, 4.2, 1.65, .1, .60),
            fuseholder(), battery(), switch()]


def export(model):
    OUT.mkdir(parents=True, exist_ok=True)
    # AP214IS retains component colours. OCCT's length unit defaults to mm.
    Interface_Static.SetCVal_s("write.step.schema", "AP214IS")
    path = OUT / (model.name + ".step")
    model.assembly.save(str(path), exportType="STEP", mode="default", write_pcurves=False)
    # Remove machine-specific filename and clock from the non-geometric header.
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"FILE_NAME\('.*?',\s*'.*?'", f"FILE_NAME('{path.name}','2026-09-30T00:00:00'", text, count=1)
    path.write_bytes(("\n".join(line.rstrip() for line in text.splitlines()) + "\n").encode("utf-8"))


def check(model, footprints=None):
    path = OUT / (model.name + ".step")
    text = path.read_text(encoding="utf-8")
    assert "AUTOMOTIVE_DESIGN" in text, (model.name, "not AP214")
    assert "SI_UNIT(.MILLI.,.METRE.)" in text, (model.name, "not mm")
    imported = cq.importers.importStep(str(path))
    assert imported.vals() and all(s.isValid() for s in imported.vals()), (model.name, "invalid STEP")
    bb = imported.val().BoundingBox()
    assert abs(bb.zmax - model.height) < 1e-5, (model.name, "height", bb.zmax)
    expected = model.envelope
    actual = (bb.xmin, bb.xmax, bb.ymin, bb.ymax)
    assert all(abs(a-b) < 1e-5 for a,b in zip(actual, expected)), (model.name, "envelope", actual, expected)
    if footprints:
        # Read KiCad pad centres/sizes with a balanced expression scanner; no
        # pcbnew dependency is required in the CadQuery environment.
        footprint = footprints / (model.name + ".kicad_mod")
        src = footprint.read_text(encoding="utf-8")
        pads = []
        for start in re.finditer(r'\(pad "([^"]*)" (\w+) \w+', src):
            depth, end = 0, start.start()
            while end < len(src):
                depth += (src[end] == "(") - (src[end] == ")")
                end += 1
                if depth == 0: break
            part = src[start.start():end]
            pos = re.search(r'\(at ([-\d.]+) ([-\d.]+)', part)
            size = re.search(r'\(size ([-\d.]+) ([-\d.]+)', part)
            hole = re.search(r'\(drill (?:oval )?([-\d.]+)(?: ([-\d.]+))?', part)
            pads.append((start[1], start[2], float(pos[1]), -float(pos[2]),
                         float(size[1]), float(size[2]),
                         float(hole[1]) if hole else None, float(hole[2] or hole[1]) if hole else None))
        for num, pin in model.pins:
            pb = pin.val().BoundingBox()
            px, py = (pb.xmin+pb.xmax)/2, (pb.ymin+pb.ymax)/2
            candidates = [p for p in pads if p[0] == num]
            pad = min(candidates, key=lambda p: math.hypot(p[2]-px, p[3]-py))
            dx, dy = abs(px-pad[2]), abs(py-pad[3])
            if pad[1] == "smd":
                assert dx+pb.xlen/2 <= pad[4]/2+1e-6 and dy+pb.ylen/2 <= pad[5]/2+1e-6, (model.name, num, "tail off land")
            elif pad[6] == pad[7]:
                radius = pad[6]/2
                # Round XT60 pins: use actual circular radius, not bbox diagonal.
                reach = math.hypot(dx,dy)+pb.xlen/2 if model.name.startswith("AMASS") and num else math.hypot(dx+pb.xlen/2,dy+pb.ylen/2)
                assert reach < radius, (model.name, num, "tail outside hole")
            else:
                # Slot minor direction X, straight central part along Y.
                assert dx+pb.xlen/2 < pad[6]/2 and dy+pb.ylen/2 < pad[7]/2, (model.name, num, "tab outside slot")
    terminal_status = ", PCB terminals fit footprint" if footprints else ""
    print(f"PASS {model.name}: AP214/mm, valid solids, H={bb.zmax:.2f}, envelope{terminal_status}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify existing STEP files without writing")
    parser.add_argument("--footprints", type=Path, help="directory containing all seven footprints (including standard KiCad copies)")
    args = parser.parse_args()
    for model in models():
        if not args.check: export(model)
        check(model, args.footprints)


if __name__ == "__main__":
    main()
