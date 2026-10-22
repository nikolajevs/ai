#!/usr/bin/env python3
"""Reinforce the routed 12 V inner-layer feed, then screen auxiliary copper.

The load allocations below are conservative design cases, not measurements.
The existing DC track/via model excludes pours, GND and component dynamics.
Only widths of existing +12V In2.Cu tracks >= 0.6 mm can change; endpoints,
UUIDs, other copper, placements and library data are preserved byte for byte.
Run after route_board.py, before silkscreen generation and the native DRC.
SPDX-License-Identifier: MIT
"""
import argparse
import hashlib
import json
from pathlib import Path

import pcbnew as p

from ampacity import analyze_net
from models3d import spans
from verify_footprints import parse, child

HERE = Path(__file__).resolve().parents[1]
CASES = {
    '+12V_FANS': ('F401.2', {'J411.2': .45, 'J421.2': .45}),
    '+12V': ('L101.2', {'F401.1': .9, 'U201.2': .27, 'Q702.2': .01, 'U802.8': .002}),
    '+3V3': ('L201.2', {'U202.2': .5, 'J301.4': .25, 'J401.1': .02,
                       'U301.8': .005, 'U102.6': .003, 'U401.5': .002,
                       'U402.5': .002, 'R813.1': .002}),
}


def width_clear(board, track, width):
    """Use native shapes and the existing 0.2 mm net clearance; no rule bypass."""
    saved = track.GetWidth()
    track.SetWidth(p.FromMM(width))
    shape = track.GetEffectiveShape()
    track.SetWidth(saved)
    layer, net = track.GetLayer(), track.GetNetCode()
    gap = p.FromMM(.2) - 1  # permit exact 0.2 mm tangency at native integer resolution
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetCode() != net and pad.IsOnLayer(layer):
                if pad.GetEffectiveShape(layer).Collide(shape, gap):
                    return False
    for other in board.GetTracks():
        if other.GetNetCode() == net or not other.IsOnLayer(layer):
            continue
        other_shape = other.GetEffectiveShape(layer) if isinstance(other, p.PCB_VIA) else other.GetEffectiveShape()
        if other_shape.Collide(shape, gap):
            return False
    for zone in board.Zones():
        if zone.GetIsRuleArea() and zone.IsOnLayer(layer) and zone.GetDoNotAllowTracks():
            if zone.Outline().Collide(shape, 0):
                return False
    edge = board.GetBoardEdgesBoundingBox()
    bounds = shape.BBox()
    margin = p.FromMM(.3)
    return (edge.GetLeft() + margin <= bounds.GetLeft() and bounds.GetRight() <= edge.GetRight() - margin
            and edge.GetTop() + margin <= bounds.GetTop() and bounds.GetBottom() <= edge.GetBottom() - margin)


def reinforce(board):
    result = []
    for track in board.GetTracks():
        if isinstance(track, p.PCB_VIA) or track.GetLayer() != p.In2_Cu or track.GetNetname() != '+12V':
            continue
        original = p.ToMM(track.GetWidth())
        if original < .599:
            continue  # fine-pitch/local low-current branches are not the fan trunk
        target = original
        for width in (.8, .7):
            if width >= original and width_clear(board, track, width):
                target = width
                break
        track.SetWidth(p.FromMM(target))
        result.append(dict(uuid=track.m_Uuid.AsString(), original_mm=original, target_mm=target,
                           start_mm=[p.ToMM(track.GetStart().x), p.ToMM(track.GetStart().y)],
                           end_mm=[p.ToMM(track.GetEnd().x), p.ToMM(track.GetEnd().y)]))
    return result


def update_text(text, selected):
    replacements = {v['uuid']: v['target_mm'] for v in selected if v['original_mm'] != v['target_mm']}
    edits = []
    for a, b in spans(text, 'segment'):
        block = text[a:b]
        node = parse(block)
        uid = child(node, 'uuid')[1]
        if uid in replacements:
            matches = spans(block, 'width')
            if len(matches) != 1:
                raise RuntimeError(f'{uid}: expected a single width')
            x, y = matches[0]
            edits.append((a + x, a + y, f'(width {replacements.pop(uid):g})'))
    if replacements:
        raise RuntimeError(f'Missing routed segments: {sorted(replacements)}')
    for a, b, value in sorted(edits, reverse=True):
        text = text[:a] + value + text[b:]
    return text


def check_cases(board):
    pads = {fp.GetReference() + '.' + pad.GetNumber(): pad
            for fp in board.GetFootprints() for pad in fp.Pads()}
    return [analyze_net(board, pads, net, source, sinks, 35, 17.5)
            for net, (source, sinks) in CASES.items()]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--board', type=Path, default=HERE / 'PCB_EU.kicad_pcb')
    ap.add_argument('--apply', action='store_true', help='Widen clear trunk segments; preserve every other source byte')
    ap.add_argument('--output', type=Path, default=HERE / 'review/aux_power.json')
    args = ap.parse_args()
    if not p.Version().startswith('10.'):
        ap.error('KiCad 10 pcbnew is required')
    original = args.board.read_text()
    board = p.LoadBoard(str(args.board))
    widths = reinforce(board) if args.apply else []
    changed = [v for v in widths if v['original_mm'] != v['target_mm']]
    if args.apply:
        updated = update_text(original, widths)
        if updated != original:
            args.board.write_text(updated)
    cases = check_cases(board)
    errors = [v for v in cases if 'error' in v]
    if errors:
        raise RuntimeError(errors)
    hot = [dict(net=v['net'], **s) for v in cases for s in v['segments'] if s['dt_ipc2221_c'] > 30]
    excessive_vias = [dict(net=v['net'], **via) for v in cases for via in v['vias_over_limit']]
    report = dict(pcbnew_version=p.Version(), outer_um=35, inner_um=17.5,
                  screening_only=True, thermal_qualified=False,
                  assumptions=['12 V fans allocated 0.45 A each (0.9 A total, above documented 10 W steady budget)',
                               '12 V logic input allocated 0.27 A plus 12 mA driver/comparator allowance',
                               '3.3 V ESP32 allocated 0.5 A, SD 0.25 A, sensors/RTC/monitor/ESD/divider 34 mA',
                               'DC copper only; startup pulses, planes/GND, temperature coefficients, tolerances and components not modelled'],
                  feed_widths=widths, widened_segments=len(changed), nets=cases,
                  tracks_over_30c_rise=hot, vias_over_heuristic=excessive_vias,
                  source_sha256=hashlib.sha256(args.board.read_bytes()).hexdigest())
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    if hot or excessive_vias:
        raise RuntimeError('Auxiliary copper screening has unresolved temperature-rise/via flags; see report')
    print(f'PASS | auxiliary copper screening | {len(cases)} design cases; {len(changed)} widths increased; no >30 C model rises or via flags')


if __name__ == '__main__':
    main()
