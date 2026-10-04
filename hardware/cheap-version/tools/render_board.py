"""PNG preview of the cheap-1 board layers (kicad-cli SVG export rendered with PyMuPDF).

Usage: python hardware/cheap-version/tools/render_board.py out.png [--bottom] [--layers F.Cu,F.Courtyard,...] [--dpi 150]
Default layers (top): F.Cu, F.Courtyard, F.Fab, F.Silkscreen, Edge.Cuts; --bottom mirrors to the back side.
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser()
ap.add_argument("out", type=Path)
ap.add_argument("--bottom", action="store_true")
ap.add_argument("--layers")
ap.add_argument("--dpi", type=int, default=150)
ap.add_argument("--board", type=Path, default=HERE / "cheap-version.kicad_pcb")
args = ap.parse_args()
side = "B" if args.bottom else "F"
layers = args.layers or f"{side}.Cu,{side}.Courtyard,{side}.Fab,{side}.Silkscreen,Edge.Cuts"
cli = os.environ.get("KICAD_CLI", r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")
svg = Path(tempfile.mkdtemp()) / "board.svg"
cmd = [cli, "pcb", "export", "svg", "--layers", layers, "--page-size-mode", "2", "--exclude-drawing-sheet", "-o", str(svg), str(args.board)]
if args.bottom:
    cmd.insert(4, "--mirror")
subprocess.run(cmd, check=True, capture_output=True)
doc = pymupdf.open(str(svg))
doc[0].get_pixmap(dpi=args.dpi).save(str(args.out))
print("wrote", args.out)
