#!/usr/bin/env python3
"""Check planned copper and actual KiCad connectivity of the partial power routes.

Named groups are checked through KiCad's physical copper connectivity, not merely
matching net names. Native DRC and placement checks remain mandatory separately.
SPDX-License-Identifier: MIT
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import pcbnew as p

from build_board import HERE
from route_power import plan_items, signature


def check_connected_groups(board, specified_groups):
    """Return group evidence from actual filled copper, including duplicate pads."""
    board.BuildConnectivity()
    fps = {f.GetReference(): f for f in board.GetFootprints()}
    connectivity = board.GetConnectivity()
    groups = []
    for group in specified_groups:
        pads = []
        for name in group['pads']:
            ref, pin = name.split('.')
            matches = [a for a in fps[ref].Pads() if a.GetNumber() == pin]
            if not matches or any(a.GetNetname() != group['net'] for a in matches):
                raise RuntimeError(f'{name}: missing pad or incorrect group net')
            pads.extend(matches)  # Include every duplicate-number diode land.
        reached = {pads[0].m_Uuid.AsString()} | {i.m_Uuid.AsString() for i in connectivity.GetConnectedItems(pads[0])}
        if any(a.m_Uuid.AsString() not in reached for a in pads):
            raise RuntimeError(f'Physically disconnected copper group: {group}')
        groups.append(dict(net=group['net'], pads=group['pads'], physical_pad_count=len(pads), copper_connected=True))
    return groups


def check(board_path, output=None):
    board = p.LoadBoard(str(board_path))
    plan = json.loads((HERE / 'routing.json').read_text())
    actual = {v.m_Uuid.AsString(): v for v in [*board.GetTracks(), *board.Zones()]}
    expected = plan_items(board, plan)
    if len({i.m_Uuid.AsString() for i in expected}) != len(expected):
        raise RuntimeError('Routing plan contains duplicate object UUIDs')
    for item in expected:
        uid = item.m_Uuid.AsString()
        if uid not in actual or signature(actual[uid]) != signature(item):
            raise RuntimeError(f'Missing or changed planned copper: {uid}')
    groups = check_connected_groups(board, plan['connected_groups'])
    zones = [z for z in board.Zones() if not z.GetIsRuleArea()]
    for zone in zones:
        if not zone.IsFilled() or not zone.HasFilledPolysForLayer(zone.GetLayer()) or zone.GetFilledArea() <= 0:
            raise RuntimeError('Copper zone has no saved fill; refill and rerun DRC')
    board.BuildConnectivity()
    unrouted = board.GetConnectivity().GetUnconnectedCount(False)
    sessions = sorted((HERE / 'routing').glob('*.ses'))
    tracks = [t for t in board.GetTracks() if not isinstance(t, p.PCB_VIA)]
    vias = [t for t in board.GetTracks() if isinstance(t, p.PCB_VIA)]
    # Each entry is a physical routed segment, not a completed schematic net.
    result = dict(stage='autorouted board with open connections' if unrouted else 'fully routed board', date=plan['date'], pcbnew_build=p.GetBuildVersion(),
                  planned_copper_objects_checked=len(expected), tracks=len(tracks), vias=len(vias),
                  tracks_by_layer=dict(Counter(board.GetLayerName(t.GetLayer()) for t in tracks)),
                  copper_zones=[dict(net=z.GetNetname(), layer=board.GetLayerName(z.GetLayer()),
                                     filled_area_mm2=round(z.GetFilledArea()/1e12, 2)) for z in zones],
                  actual_copper_connected_groups=groups, scope=plan['scope'], limits=plan['limits'],
                  unrouted_connections=unrouted, complete_board_routing=unrouted == 0,
                  router='LED1 plan (routing.json) + tools/route_board.py: Freerouting 2.4.1 sessions in routing/, grid completion, GND ties and pours',
                  min_track_width_mm={cls: round(min((p.ToMM(t.GetWidth()) for t in tracks if t.GetNetClassName() == cls), default=0), 3)
                                      for cls in ('HEAVY24', 'LOAD', 'PWR', 'Default')},
                  ampacity_verified=False, thermal_verified=False,
                  source_sha256={str(f.relative_to(HERE)) if f.is_relative_to(HERE) else f.name: hashlib.sha256(f.read_bytes()).hexdigest()
                                 for f in [board_path, HERE/'routing.json', *sessions]})
    if output:
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(f'PASS | {result["stage"]} | {unrouted} unrouted | {len(expected)} planned objects; {len(groups)} physically connected groups; {len(tracks)} tracks / {len(vias)} vias')
    return result


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--board', type=Path, default=HERE/'PCB_EU.kicad_pcb')
    ap.add_argument('--output', type=Path, default=HERE/'review/routing.json')
    args = ap.parse_args()
    check(args.board, args.output)
