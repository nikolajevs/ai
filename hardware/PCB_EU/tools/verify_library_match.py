#!/usr/bin/env python3
"""Check that every board footprint is its library footprint, apart from the silkscreen.

silkscreen.py cuts library outlines back from pads (silk_clean.py), so native DRC reports
lib_footprint_mismatch for those footprints. The project forbids silencing DRC categories, so
run_checks.py tolerates exactly the references this check lists as silk-only: a footprint
counts as silk-only when KiCad's own comparison finds it equal to the library footprint once
the graphics on F.SilkS and B.SilkS are removed from both. Any other difference (pads, other
layers, models, fields) stays a DRC failure. Footprints without a library link (mounting
holes, the heatsink legs HS1) are not compared.

SPDX-License-Identifier: MIT
"""
import argparse
import json
from pathlib import Path

import pcbnew as p

from build_board import HERE

SILK = (p.F_SilkS, p.B_SilkS)
graveyard = []      # removed items stay referenced, or pcbnew frees them under the footprint


def without_silk(fp):
    for g in list(fp.GraphicalItems()):
        if g.GetLayer() in SILK:
            fp.Remove(g)
            graveyard.append(g)
    return fp


def check(board_path, output=None):
    board = p.LoadBoard(str(board_path))
    identical, silk_only, other, unlinked = [], [], [], []
    for fp in board.GetFootprints():
        ref, lib, name = fp.GetReference(), str(fp.GetFPID().GetLibNickname()), str(fp.GetFPID().GetLibItemName())
        if not lib:
            unlinked.append(ref)
            continue
        source = p.FootprintLoad(str(HERE / 'libraries' / (lib + '.pretty')), name)
        if source is None:
            raise RuntimeError(f'{ref}: cannot load {lib}:{name}')
        if not fp.FootprintNeedsUpdate(source):
            identical.append(ref)
            continue
        copy = p.FOOTPRINT(fp)
        graveyard.extend([copy, source])
        (other if without_silk(copy).FootprintNeedsUpdate(without_silk(source)) else silk_only).append(ref)
    if other:
        raise RuntimeError(f'Footprints differ from their library beyond the silkscreen: {sorted(other)}')
    result = dict(pcbnew_version=p.Version(), compared=len(identical) + len(silk_only), identical=len(identical),
                  silk_only=sorted(silk_only), without_library_link=sorted(unlinked),
                  scope='KiCad FootprintNeedsUpdate on the board footprint and the library footprint, silkscreen graphics removed from both')
    if output:
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(f'PASS | library match | {len(identical)} footprints identical to the library, {len(silk_only)} differ in the silkscreen only, '
          f'{len(unlinked)} without library link')
    return result


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--board', type=Path, default=HERE / 'PCB_EU.kicad_pcb')
    ap.add_argument('--output', type=Path, default=HERE / 'review/library_match.json')
    args = ap.parse_args()
    check(args.board, args.output)
