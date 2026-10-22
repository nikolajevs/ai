#!/usr/bin/env python3
"""Repeat PCB_EU pre-prototype DC copper screening, never thermal certification."""
import argparse
import hashlib
import json
from pathlib import Path

import pcbnew as p

from ampacity import SCENARIOS, analyze_net
from aux_power import CASES
from stackup import check_text

HERE = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--board', type=Path, default=HERE / 'PCB_EU.kicad_pcb')
    ap.add_argument('--output', type=Path, default=HERE / 'review/power_copper.json')
    args = ap.parse_args()
    stack = check_text(args.board.read_text())
    board = p.LoadBoard(str(args.board))
    board.BuildConnectivity()
    pads = {f.GetReference() + '.' + pad.GetNumber(): pad for f in board.GetFootprints() for pad in f.Pads()}
    cases = []
    flags = []
    for scale in [.5, 1, 2]:
        for net, (source, sinks) in SCENARIOS.items():
            result = analyze_net(board, pads, net, source, sinks, 35, 17.5, scale)
            result['via_resistance_scale'] = scale
            if 'error' in result:
                raise RuntimeError(result)
            cases.append(result)
            flags.extend(dict(net=net, scale=scale, **v) for v in result['vias_over_limit'])
    aux = []
    for net, (source, sinks) in CASES.items():
        result = analyze_net(board, pads, net, source, sinks, 35, 17.5)
        if 'error' in result:
            raise RuntimeError(result)
        aux.append(result)
        flags.extend(dict(net=net, scale=1, **v) for v in result['vias_over_limit'])
        flags.extend(dict(net=net, reason='auxiliary >30 C screening rise', **s)
                     for s in result['segments'] if s['dt_ipc2221_c'] > 30)
    ground = []
    for name in ['R111.1', 'R112.1']:
        pad = pads[name]
        conn = board.GetConnectivity()
        reached = {i.m_Uuid.AsString() for i in conn.GetConnectedItems(pad)}
        local = [v for v in board.GetTracks() if isinstance(v, p.PCB_VIA) and v.GetNetname() == 'GND'
                 and (v.GetPosition() - pad.GetPosition()).EuclideanNorm() <= p.FromMM(5)
                 and v.m_Uuid.AsString() in reached]
        large = [v for v in local if v.GetDrillValue() >= p.FromMM(.5)]
        if len(large) < 2:
            flags.append(dict(anchor=name, reason='need two extra 0.5 mm GND drills within 5 mm'))
        ground.append(dict(anchor=name, connected_vias_within_5mm=len(local),
                           connected_05mm_drill_vias=len(large),
                           actual_current_sharing_qualified=False))
    report = dict(date='2026-10-22', kicad_version=p.Version(),
                  status='DC pre-prototype screening; no fabrication release',
                  stackup=stack, outer_um=35, inner_um=17.5,
                  via_resistance_scales=[.5, 1, 2], input_current_a=9.5,
                  cases=cases, auxiliary_cases=aux, ground_via_banks=ground,
                  unresolved_screening_flags=flags,
                  thermal_qualified=False, transient_and_emc_qualified=False,
                  limitations=[
                      'Resistance network is a 1D approximation with ideal overlapping contacts; not a 2D/3D thermal model.',
                      'GND pours and THT barrel resistance are not solved; GND evidence is native connectivity and via geometry only.',
                      'Via drill-current comparisons are screening heuristics, not guaranteed ampacity ratings.',
                      'Design currents are not measurements; converter switching peaks, startup, real ambient and assembly temperatures require prototype checks.',
                      'Factory dielectric schedule, minimum finished copper and barrel plating must be confirmed before manufacturing release.'
                  ], source_sha256=hashlib.sha256(args.board.read_bytes()).hexdigest())
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    if flags:
        raise RuntimeError(f'{len(flags)} unresolved DC copper screening flags; see {args.output}')
    print('PASS | DC power screening | 24 supply cases + 3 auxiliary cases; via sensitivity 0.5/1/2; no screening flags')


if __name__ == '__main__':
    main()
