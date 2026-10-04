#!/usr/bin/env python3
"""Make an experimental FDM solder-paste stencil for cheap-version.

The stencil is deliberately generated from the committed top-paste Gerber.  That
keeps it in sync with the board without attempting to reconstruct KiCad pad
shapes.  OpenSCAD performs the final 2-D difference and STL tessellation.

Examples (from hardware/cheap-version)::

    python tools/make_stencil.py --scad stencil/cheap_full.scad
    openscad -o stencil/cheap_full.stl stencil/cheap_full.scad
    python tools/make_stencil.py --test-scad stencil/cheap_test.scad

The script does not change the board or the fabrication archive.  The supplied
STLs are experiments for 0.4 mm and 0.2 mm nozzles with PLA; inspect the sliced
preview before printing.
"""

from __future__ import annotations

import argparse
import math
import re
import subprocess
import zipfile
from pathlib import Path

from gerbonara import GerberFile
from gerbonara.graphic_primitives import ArcPoly, Circle, Rectangle
from gerbonara.utils import MM


HERE = Path(__file__).resolve().parents[1]
FAB_ZIP = HERE / "fab" / "cheap-version_cheap1_jlcpcb.zip"
BOARD_X0 = 49.975
BOARD_Y0 = 49.975
BOARD_W = 100.05
BOARD_H = 100.05


def paste_gerber() -> GerberFile:
    with zipfile.ZipFile(FAB_ZIP) as archive:
        names = [n for n in archive.namelist() if n.endswith("-F_Paste.gtp")]
        if len(names) != 1:
            raise RuntimeError(f"expected one top-paste Gerber, found {names!r}")
        return GerberFile.from_string(archive.read(names[0]).decode("utf-8"))


def xy(x: float, y: float, ox: float, oy: float) -> tuple[float, float]:
    """Gerber (KiCad X, negative Y) to board-local OpenSCAD coordinates."""
    return x - BOARD_X0 - ox, -y - BOARD_Y0 - oy


def primitive_scad(primitive, ox: float, oy: float, expand: float,
                   hole_height: float) -> str:
    # The paste layer is positive polarity.  Aperture macros are already
    # decomposed by Gerbonara into their outline/corner primitives.
    if isinstance(primitive, Circle):
        x, y = xy(primitive.x, primitive.y, ox, oy)
        return (
            f"translate([{x:.5f},{y:.5f},-0.02]) "
            f"cylinder(h={hole_height:.5f},r={primitive.r + expand:.5f},$fn=24);"
        )
    if isinstance(primitive, Rectangle):
        x, y = xy(primitive.x, primitive.y, ox, oy)
        angle = math.degrees(primitive.rotation)
        return (
            f"translate([{x:.5f},{y:.5f},-0.02]) rotate([0,0,{angle:.5f}]) "
            f"cube([{primitive.w + 2*expand:.5f},{primitive.h + 2*expand:.5f},{hole_height:.5f}],center=true);"
        )
    if isinstance(primitive, ArcPoly):
        approx = primitive.approximate_arcs(max_error=0.01)
        points = [xy(x, y, ox, oy) for x, y in approx.outline]
        point_text = ",".join(f"[{x:.5f},{y:.5f}]" for x, y in points)
        # ArcPoly from a rounded-rectangle macro is accompanied by its corner
        # circles/rectangles.  It is an outline helper and is intentionally
        # emitted as-is; the accompanying primitives make the union rounded.
        return (
            f"linear_extrude(height={hole_height:.5f}) "
            f"polygon(points=[{point_text}]);"
        )
    raise TypeError(type(primitive).__name__)


def flash_bbox_scad(obj, ox: float, oy: float, expand: float,
                    hole_height: float) -> str:
    """Emit one inexpensive polygon for one Gerber flash.

    Gerber rounded-rectangle macros expand into several CSG primitives.  Keeping
    every macro primitive makes OpenSCAD consume nearly a gigabyte for this
    board.  A bounding polygon is intentionally used for the FDM experiment:
    it is slightly more open than the paste aperture and therefore safer to
    print with a 0.4 mm nozzle.  The production stencil should still use the
    original Gerber/laser-cut file.
    """
    (x1, y1), (x2, y2) = obj.bounding_box()
    x1, y1 = xy(x1, y1, ox, oy)
    x2, y2 = xy(x2, y2, ox, oy)
    points = (
        (x1 - expand, y1 - expand),
        (x2 + expand, y1 - expand),
        (x2 + expand, y2 + expand),
        (x1 - expand, y2 + expand),
    )
    return f"linear_extrude(height={hole_height:.5f}) polygon(points=[{{}}]);".format(
        ",".join(f"[{x:.5f},{y:.5f}]" for x, y in points)
    )


def hole_union(gbr: GerberFile, ox: float, oy: float, expand: float,
               hole_height: float) -> str:
    lines = ["union() {"]
    count = 0
    for obj in gbr.objects:
        if obj.polarity_dark:
            lines.append("  " + flash_bbox_scad(obj, ox, oy, expand, hole_height))
            count += 1
    lines.append("}")
    if count == 0:
        raise RuntimeError("top-paste layer contains no positive primitives")
    return "\n".join(lines)


def write_scad(path: Path, gbr: GerberFile, *, ox: float, oy: float,
               width: float, height: float, expand: float, thickness: float,
               label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    holes = hole_union(gbr, ox, oy, expand, thickness + 0.08)
    # A tiny bevel is intentionally not added: a flat 0.20 mm plate is easier
    # to print on an A1 mini and lets the paste wipe across both faces.
    content = f"""// Generated by tools/make_stencil.py
// {label}
// Board-local coordinates; top paste openings are subtracted from this plate.
plate_w = {width:.5f};
plate_h = {height:.5f};
plate_t = {thickness:.5f};

difference() {{
  cube([plate_w, plate_h, plate_t]);
  translate([0,0,-0.02]) {{
    {holes}
  }}
}}
"""
    path.write_text(content, encoding="utf-8", newline="\n")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--scad", type=Path, help="write a full-board SCAD")
    p.add_argument("--test-scad", type=Path, help="write a 40 x 40 mm dense-area test coupon")
    p.add_argument("--expand", type=float, default=0.0,
                   help="expand each opening in mm (default: exact paste geometry)")
    p.add_argument("--thickness", type=float, default=0.20,
                   help="plate thickness in mm (default: one 0.20 mm layer)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if not args.scad and not args.test_scad:
        raise SystemExit("choose --scad and/or --test-scad")
    if args.expand < 0 or args.thickness <= 0:
        raise SystemExit("expand must be >= 0 and thickness must be > 0")
    gbr = paste_gerber()
    if args.scad:
        write_scad(args.scad, gbr, ox=0, oy=0, width=BOARD_W, height=BOARD_H,
                   expand=args.expand, thickness=args.thickness,
                   label="cheap-version full-board stencil")
        print(f"wrote {args.scad}")
    if args.test_scad:
        # U601/UCC27524 and the nearby 0603/0805 parts: a dense, useful first
        # coupon.  It is board-local x=20..60, y=25..65.
        write_scad(args.test_scad, gbr, ox=20, oy=25, width=40, height=40,
                   expand=args.expand, thickness=args.thickness,
                   label="cheap-version dense-area stencil coupon (board x20..60 y25..65)")
        print(f"wrote {args.test_scad}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
