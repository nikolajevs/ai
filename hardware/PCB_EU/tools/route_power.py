#!/usr/bin/env python3
"""Add the reviewed, partial LED1 routing plan; preserve all other copper.

Requires KiCad pcbnew. Existing plan UUIDs must match exactly; conflicting
objects are rejected, never silently replaced. This is not a complete router.
SPDX-License-Identifier: MIT
"""
import argparse
import json
from pathlib import Path

import pcbnew as p

from build_board import HERE, identity, point


def plan_items(board, plan):
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    nets = {net.GetNetname(): net for net in board.GetNetInfo().NetsByNetcode().values()}
    vias = {v['id']: v for v in plan['vias']}

    def resolve(anchor, net):
        if isinstance(anchor, list):
            return point(*anchor)
        if 'via' in anchor:
            via = vias[anchor['via']]
            if via['net'] != net:
                raise RuntimeError(f'{anchor}: via net differs from route {net}')
            return point(*via['at'])
        ref, number = anchor['pad'].split('.')
        pads = [v for v in fps[ref].Pads() if v.GetNumber() == number]
        pad = pads[anchor.get('index', 0)]
        if pad.GetNetname() != net:
            raise RuntimeError(f'{anchor}: pad net {pad.GetNetname()} differs from route {net}')
        return pad.GetPosition()

    items = []
    for spec in plan['vias']:
        via = p.PCB_VIA(board)
        via.SetPosition(point(*spec['at']))
        via.SetWidth(p.FromMM(spec['diameter']))
        via.SetDrill(p.FromMM(spec['drill']))
        via.SetViaType(p.VIATYPE_THROUGH)
        via.SetLayerPair(p.F_Cu, p.B_Cu)
        via.SetNet(nets[spec['net']])
        identity(via, 'routing/via/' + spec['id'])
        items.append(via)
    for route in plan['routes']:
        pts = [resolve(a, route['net']) for a in route['points']]
        for i, (a, b) in enumerate(zip(pts, pts[1:])):
            if a == b:
                raise RuntimeError(f'{route["id"]}: zero-length track')
            track = p.PCB_TRACK(board)
            track.SetStart(a)
            track.SetEnd(b)
            track.SetWidth(p.FromMM(route['width']))
            track.SetLayer(board.GetLayerID(route['layer']))
            track.SetNet(nets[route['net']])
            identity(track, f'routing/track/{route["id"]}/{i}')
            items.append(track)
    for spec in plan['zones']:
        zone = p.ZONE(board)
        zone.SetLayer(board.GetLayerID(spec['layer']))
        zone.SetNet(nets[spec['net']])
        zone.SetLocalClearance(p.FromMM(spec['clearance']))
        zone.SetMinThickness(p.FromMM(.2))
        zone.SetPadConnection(p.ZONE_CONNECTION_THERMAL)
        zone.SetThermalReliefGap(p.FromMM(.3))
        zone.SetThermalReliefSpokeWidth(p.FromMM(.5))
        zone.SetIslandRemovalMode(p.ISLAND_REMOVAL_MODE_ALWAYS)
        outline = zone.Outline()
        outline.NewOutline()
        for x, y in spec['outline']:
            outline.Append(p.FromMM(x), p.FromMM(y))
        identity(zone, 'routing/zone/' + spec['id'])
        items.append(zone)
    return items


def signature(item):
    """Geometry/electrical signature; excludes regenerated zone-fill caches."""
    if isinstance(item, p.PCB_VIA):
        return ('via', item.GetNetname(), item.GetPosition().x, item.GetPosition().y,
                tuple(item.GetWidth(layer) for layer in (p.F_Cu, p.In1_Cu, p.In2_Cu, p.B_Cu)),
                item.GetDrillValue(), item.TopLayer(), item.BottomLayer())
    if isinstance(item, p.PCB_TRACK):
        return ('track', item.GetNetname(), item.GetLayer(), item.GetWidth(),
                item.GetStart().x, item.GetStart().y, item.GetEnd().x, item.GetEnd().y)
    poly = item.Outline().Outline(0)
    return ('zone', item.GetNetname(), tuple(item.GetLayerSet().Seq()),
            tuple((poly.CPoint(i).x, poly.CPoint(i).y) for i in range(poly.PointCount())),
            item.GetLocalClearance(), item.GetMinThickness(), item.GetPadConnection(),
            item.GetThermalReliefGap(), item.GetThermalReliefSpokeWidth(), item.GetIslandRemovalMode())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--board', type=Path, default=HERE / 'PCB_EU.kicad_pcb')
    args = ap.parse_args()
    # pcbnew loads rules/text variables from the project beside the PCB. Without
    # it a temporary board silently uses default clearances during zone filling.
    project_path = args.board.with_suffix('.kicad_pro')
    if not project_path.exists():
        raise RuntimeError('Copy PCB_EU.kicad_pro beside the temporary board with the same basename before routing')
    source_project = json.loads((HERE / 'PCB_EU.kicad_pro').read_text())
    project = json.loads(project_path.read_text())
    def includes(actual, reference):
        # KiCad expands sparse project files with defaults after saving. Compare
        # explicitly configured values, permitting that normal expansion.
        if isinstance(reference, dict):
            return isinstance(actual, dict) and all(k in actual and includes(actual[k], v) for k, v in reference.items())
        return actual == reference
    for section in ('board', 'net_settings', 'text_variables'):
        if section in source_project and not includes(project.get(section), source_project[section]):
            raise RuntimeError(f'Temporary project {section} differs from PCB_EU; review rules before filling')
    if 'net_settings' not in source_project:
        net_settings = project.get('net_settings', {})
        if any(c.get('name') != 'Default' or c.get('clearance') != .2 for c in net_settings.get('classes', [])) or any(net_settings.get(k) for k in ('netclass_assignments', 'netclass_patterns')):
            raise RuntimeError('Temporary project introduces net classes absent from PCB_EU')
    plan = json.loads((HERE / 'routing.json').read_text())
    board = p.LoadBoard(str(args.board))
    existing = {v.m_Uuid.AsString(): v for v in [*board.GetTracks(), *board.Zones()]}
    planned = plan_items(board, plan)
    if len({i.m_Uuid.AsString() for i in planned}) != len(planned):
        raise RuntimeError('Routing plan contains duplicate object UUIDs')
    added = 0
    for item in planned:
        uid = item.m_Uuid.AsString()
        if uid in existing:
            if signature(item) != signature(existing[uid]):
                raise RuntimeError(f'Existing routing object differs: {uid}; preserve and review manual edits')
        else:
            board.Add(item)
            added += 1
    for item in board.GetDrawings():
        if isinstance(item, p.PCB_TEXT) and 'UNROUTED PLACEMENT' in item.GetText():
            item.SetText('EU-0.1 / PARTIAL LED1 ROUTING / 100 x 100 mm / 4 Cu')
    board.BuildConnectivity()
    p.ZONE_FILLER(board).Fill(board.Zones())
    p.SaveBoard(str(args.board), board)
    print(f'Added {added} planned copper objects; preserved existing copper; filled zones. Partial routing only.')


if __name__ == '__main__':
    main()
