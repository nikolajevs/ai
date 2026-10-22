#!/usr/bin/env python3
"""Native KiCad assembly views, rasterised with PyMuPDF/Pillow for review.

No invented copper, component geometry, routing or 3D qualification is shown.
These annotated images are not production drawings.
SPDX-License-Identifier: MIT
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import tempfile

import fitz
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kicad-cli', required=True)
    ap.add_argument('--silkscreen-only', action='store_true', help='Plot readable manufacturing silk views, without Fab or copper')
    args = ap.parse_args()
    layout = json.loads((HERE / 'placement.json').read_text())
    counts = Counter(v['side'] for v in layout['placements'].values())
    drc = json.loads((HERE / 'review/pcb_drc.json').read_text())
    status = json.loads((HERE / 'review/placement.json').read_text())
    stage = ('ROUTED, NOT RELEASED' if not drc.get('unconnected_items') else 'PARTIAL ROUTING') if status['routed_tracks'] else 'UNROUTED PLACEMENT'
    try:
        title = ImageFont.truetype('DejaVuSans.ttf', 20)
        small = ImageFont.truetype('DejaVuSans.ttf', 15)
    except OSError:
        title = small = ImageFont.load_default()
    with tempfile.TemporaryDirectory(prefix='eu-placement-plot-') as temp:
        for side, name, layers, mirror in [
                ('F', 'front', 'F.Cu,F.Fab,F.Silkscreen,Edge.Cuts,Dwgs.User', False),
                ('B', 'back', 'B.Cu,B.Fab,B.Silkscreen,Edge.Cuts', True)]:
            if args.silkscreen_only:
                layers = f'{side}.Silkscreen,{side}.Mask,Edge.Cuts'
            svg = Path(temp) / (name + '.svg')
            command = [args.kicad_cli, 'pcb', 'export', 'svg', '--mode-single', '--page-size-mode', '2', '--exclude-drawing-sheet', '--layers', layers, '--sketch-pads-on-fab-layers', '-o', str(svg)]
            if mirror:
                command.append('--mirror')
            if args.silkscreen_only:
                command.append('--black-and-white')
            subprocess.run(command + [str(HERE / 'PCB_EU.kicad_pcb')], check=True)
            with fitz.open(svg) as doc:
                pix = doc[0].get_pixmap(matrix=fitz.Matrix(4, 4), alpha=False)
                cad = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
            canvas = Image.new('RGB', (cad.width + 40, cad.height + 150), 'white')
            canvas.paste(cad, (20, 65))
            draw = ImageDraw.Draw(canvas)
            kind = 'SILK / MASK' if args.silkscreen_only else stage
            draw.text((20, 12), f'EU-0.1 | {kind} | {name.upper()}' + (' (mirrored)' if mirror else ''), font=title, fill='#17202a')
            draw.text((20, 39), f'100 x 100 mm / 4 Cu / {counts[side]} netlisted references on this face / {layout["date"]}', font=small, fill='#444444')
            draw.text((20, cad.height + 80), f'{status["routed_tracks"]} tracks / {status["routed_vias"]} vias / {status["copper_zones"]} plane; {len(drc["unconnected_items"])} unrouted. Not a fabrication release.', font=small, fill='#8b1a1a')
            draw.text((20, cad.height + 105), 'HS1: two soldered GND pins, M3 screw; physical fit, 30 mm height and thermal behaviour require prototype checks.', font=small, fill='#444444')
            dest = HERE / 'review' / f'PCB_{"silkscreen" if args.silkscreen_only else "placement"}_{name}.png'
            canvas.save(dest)
            print(dest)


if __name__ == '__main__':
    main()
