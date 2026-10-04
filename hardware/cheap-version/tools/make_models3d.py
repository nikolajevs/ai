#!/usr/bin/env python3
"""Simplified 3D models for the cheap-1 footprints (CadQuery); SPDX-License-Identifier: MIT.

Usage: python hardware/cheap-version/tools/make_models3d.py        (needs cadquery, see hardware/enclosure/README.md)

STEP frame as for the PCB_V1 models: X, Y = footprint X, -Y; Z = 0 on the board surface, up.
* L_Feryster_DTMSS-27_V: Feryster DTMSS-27/0.047/15-V from the manufacturer sheet (version V, +-10 %): sendust
  toroid on edge, outer diameter A = 32.5 mm, width C = 16.0 mm, window B = 5.0 mm, wire D = 1.9 mm, leads
  E = 17.5 mm apart, body at most 2 mm above the board. No third-party CAD geometry is used.
* Diodes_PowerDI5: Diodes Inc. PowerDI5 (DS36524): body 3.97 x 5.37 x 1.1 mm, two anode leads and one cathode
  tab 6.50 mm over all.
"""
from pathlib import Path

import cadquery as cq

OUT = Path(__file__).resolve().parents[1] / "libraries" / "GrowBox.3dshapes"
COPPER_WIRE = cq.Color(0.80, 0.40, 0.15)
WINDING = cq.Color(0.55, 0.20, 0.08)
TIN = cq.Color(0.75, 0.76, 0.78)
BLACK = cq.Color(0.10, 0.10, 0.11)


def dtmss27():
    a, b, c, d, e, lift = 32.5, 5.0, 16.0, 1.9, 17.5, 1.5
    ring = (cq.Workplane("YZ").workplane(offset=-c / 2).circle(a / 2).circle(b / 2).extrude(c)
            .edges().fillet(c / 2 - 0.2)).translate((0, 0, lift + a / 2))
    assy = cq.Assembly(name="DTMSS-27_0.047_15-V")
    assy.add(ring, name="winding", color=WINDING)
    for i, sx in enumerate((-1, 1)):
        lead = cq.Workplane("XY").workplane(offset=-3.0).center(sx * e / 2, 0).circle(d / 2).extrude(lift + 3.0 + 4.0)
        assy.add(lead, name=f"lead{i + 1}", color=COPPER_WIRE)
    return assy


def powerdi5():
    # STEP Y = -footprint Y: the cathode pad of the footprint (negative footprint Y) is at +Y here
    d, e1, e, h, lead_t = 3.966, 5.37, 6.504, 1.10, 0.38
    assy = cq.Assembly(name="PowerDI5")
    body = cq.Workplane("XY").box(d, e1, h - 0.1, centered=(True, True, False)).translate((0, 0, 0.1))
    assy.add(body, name="body", color=BLACK)
    heat = cq.Workplane("XY").box(3.05, 3.55, 0.1, centered=(True, True, False)).translate((0, 1.0, 0))
    assy.add(heat, name="heat_sink", color=TIN)
    reach = (e - e1) / 2 + 0.3                       # lead length outside the body plus a stub under it
    tab = cq.Workplane("XY").box(1.78, reach, lead_t, centered=(True, False, False)).translate((0, e / 2 - reach, 0))
    assy.add(tab, name="cathode_tab", color=TIN)
    for i, sx in enumerate((-0.92, 0.92)):
        lead = cq.Workplane("XY").box(0.89, reach, lead_t, centered=(True, False, False)).translate((sx, -e / 2, 0))
        assy.add(lead, name=f"anode{i + 1}", color=TIN)
    return assy


def main():
    OUT.mkdir(exist_ok=True)
    for name, model in (("L_Feryster_DTMSS-27_V", dtmss27()), ("Diodes_PowerDI5", powerdi5())):
        model.save(str(OUT / f"{name}.step"))
        print("wrote", OUT / f"{name}.step")


if __name__ == "__main__":
    main()
