#!/usr/bin/env python3
"""Check an UNROUTED placement against the real schematic netlist and geometry.

Requires KiCad pcbnew; native DRC remains a separate mandatory check. Mechanical
checks cover 2D courtyards and solder-joint access, not height or physical fit.
SPDX-License-Identifier: MIT
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import pcbnew as p

HERE = Path(__file__).resolve().parents[1]


def polygon(fp):
    poly = fp.GetCourtyard(p.B_CrtYd if fp.IsFlipped() else p.F_CrtYd)
    if poly.OutlineCount() != 1:
        raise RuntimeError(f'{fp.GetReference()}: expected one courtyard outline')
    outline = poly.Outline(0)
    return [(p.ToMM(outline.CPoint(i).x), p.ToMM(outline.CPoint(i).y)) for i in range(outline.PointCount())]


def rect(b):
    return [(b[0], b[1]), (b[2], b[1]), (b[2], b[3]), (b[0], b[3])]


def inside(pt, poly):
    x, y = pt
    found = False
    for a, b in zip(poly, poly[1:] + poly[:1]):
        if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]:
            found = not found
    return found


def segment_distance(a, b, c, d):
    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    def distance(pt, v, w):
        vx, vy = w[0] - v[0], w[1] - v[1]
        t = max(0, min(1, ((pt[0] - v[0]) * vx + (pt[1] - v[1]) * vy) / (vx * vx + vy * vy))) if vx or vy else 0
        return ((pt[0] - v[0] - t * vx) ** 2 + (pt[1] - v[1] - t * vy) ** 2) ** .5
    if cross(a, b, c) * cross(a, b, d) < -1e-12 and cross(c, d, a) * cross(c, d, b) < -1e-12:
        return 0
    return min(distance(a, c, d), distance(b, c, d), distance(c, a, b), distance(d, a, b))


def polygon_distance(a, b):
    if any(inside(pt, b) for pt in a) or any(inside(pt, a) for pt in b):
        return 0
    return min(segment_distance(v, w, x, y) for v, w in zip(a, a[1:] + a[:1]) for x, y in zip(b, b[1:] + b[:1]))


def near(a, b, distance):
    # Cheap bounding-box rejection before exact polygon-edge distances.
    if (max(x for x, y in a) + distance < min(x for x, y in b) or
        max(x for x, y in b) + distance < min(x for x, y in a) or
        max(y for x, y in a) + distance < min(y for x, y in b) or
        max(y for x, y in b) + distance < min(y for x, y in a)):
        return False
    return polygon_distance(a, b) < distance - 1e-5


def check(board_path, output=None):
    board = p.LoadBoard(str(board_path))
    layout = json.loads((HERE / 'placement.json').read_text())
    xml = ET.parse(HERE / 'review/netlist.xml').getroot()
    comps = {c.get('ref'): c for c in xml.findall('./components/comp')}
    fps = {f.GetReference(): f for f in board.GetFootprints()}
    holes = {h['ref']: h for h in layout['mounting_holes']}
    errors = []
    checks = 0

    def require(ok, reason):
        nonlocal checks
        checks += 1
        if not ok:
            errors.append(reason)

    require(len(fps) == len(board.GetFootprints()), 'Duplicate references')
    require(set(fps) == set(comps) | set(holes), 'PCB/netlist/board-only reference sets differ')
    require(set(layout['placements']) == set(comps), 'Placement/netlist reference sets differ')
    require(board.GetCopperLayerCount() == layout['copper_layers'] == 4, 'Expected four copper layers')
    require(abs(p.ToMM(board.GetDesignSettings().GetBoardThickness()) - 1.6) < 1e-5, 'Expected 1.6 mm PCB')
    require(not list(board.GetTracks()), 'Placement check expects no tracks or vias')
    require(all(z.GetIsRuleArea() for z in board.Zones()), 'Placement check expects no copper zones')
    require(layout['courtyard_gap_mm'] >= .15, 'Assembly courtyard clearance must be at least 0.15 mm')
    require(layout['opposite_side_tht_joint_guard_mm'] >= .5, 'Opposite-face solder-joint guard must be at least 0.5 mm')
    require(len(board.Zones()) == len(layout['heatsink_reserves']), 'Expected one native rule area per heatsink reserve')
    edge = [d for d in board.GetDrawings() if d.GetLayer() == p.Edge_Cuts]
    expected_edges = {frozenset(pair) for pair in [((0, 0), (100, 0)), ((100, 0), (100, 100)), ((100, 100), (0, 100)), ((0, 100), (0, 0))]}
    actual_edges = {frozenset((tuple(round(p.ToMM(v), 6) for v in (d.GetStart().x, d.GetStart().y)), tuple(round(p.ToMM(v), 6) for v in (d.GetEnd().x, d.GetEnd().y)))) for d in edge}
    require(len(edge) == 4 and actual_edges == expected_edges, 'Outline is not a closed 100 x 100 mm square')
    nets = {(node.get('ref'), node.get('pin')): n.get('name') for n in xml.findall('./nets/net') for node in n.findall('node')}
    root_uuid = re.search(r'\(uuid "([^"]+)"', (HERE / 'PCB_EU.kicad_sch').read_text()).group(1)
    connected_pads = 0
    courts, joints = {}, {}
    for ref, comp in comps.items():
        if ref not in fps:
            continue
        fp = fps[ref]
        spec = layout['placements'][ref]
        require(fp.GetFPID().GetUniStringLibId() == comp.findtext('footprint'), f'{ref}: footprint ID mismatch')
        require(fp.GetValue() == comp.findtext('value'), f'{ref}: value mismatch')
        path = '/' + '/'.join([root_uuid] + [s for s in comp.find('sheetpath').get('tstamps').split('/') if s] + [comp.findtext('tstamps')])
        require(fp.GetPath().AsString() == path, f'{ref}: schematic path mismatch')
        require(fp.IsFlipped() == (spec['side'] == 'B'), f'{ref}: wrong board face')
        require(abs(p.ToMM(fp.GetPosition().x) - spec['x']) < 1e-5 and abs(p.ToMM(fp.GetPosition().y) - spec['y']) < 1e-5 and abs((fp.GetOrientationDegrees() - spec['rotation']) % 360) < 1e-5, f'{ref}: position mismatch')
        numbers = {pad.GetNumber() for pad in fp.Pads()}
        for (nref, pin), net in nets.items():
            if nref == ref:
                require(pin in numbers, f'{ref}.{pin}: missing pad')
        joints[ref] = []
        for pad in fp.Pads():
            number = pad.GetNumber()
            expected_net = nets.get((ref, number), '') if number else ''
            require(pad.GetNetname() == expected_net, f'{ref}.{number}: expected {expected_net!r}, got {pad.GetNetname()!r}')
            connected_pads += bool(expected_net) and not expected_net.startswith('unconnected-')
            if pad.GetAttribute() == p.PAD_ATTRIB_PTH:
                require(pad.IsOnLayer(p.F_Mask) and pad.IsOnLayer(p.B_Mask), f'{ref}.{number}: lost through-hole solder-mask openings')
                bb = pad.GetBoundingBox()
                guard = layout['opposite_side_tht_joint_guard_mm']
                joints[ref].append(rect([p.ToMM(bb.GetLeft()) - guard, p.ToMM(bb.GetTop()) - guard, p.ToMM(bb.GetRight()) + guard, p.ToMM(bb.GetBottom()) + guard]))
        courts[ref] = polygon(fp)
        if ref != 'U202':
            require(all(.3 - 1e-5 <= x <= 99.7 + 1e-5 and .3 - 1e-5 <= y <= 99.7 + 1e-5 for x, y in courts[ref]), f'{ref}: courtyard outside board margin')
        else:
            # Actual ESP body is 18 x 25.5; the RF courtyard extends off-board by design.
            x, y = spec['x'], spec['y']
            require(spec['rotation'] == 0 and spec['side'] == 'F' and x - 9 >= .3 and x + 9 <= 99.7 and y - 12.75 >= .3 and y + 12.75 <= 99.7, 'ESP physical body outside board')
    refs = sorted(courts)
    for i, ref in enumerate(refs):
        for other in refs[i + 1:]:
            if fps[ref].IsFlipped() == fps[other].IsFlipped():
                require(not near(courts[ref], courts[other], layout['courtyard_gap_mm']), f'{ref}/{other}: same-face courtyard clearance < 0.15 mm')
            else:
                require(not any(near(j, courts[other], 1e-4) for j in joints[ref]) and not any(near(j, courts[ref], 1e-4) for j in joints[other]), f'{ref}/{other}: opposite-face part obstructs THT solder-joint guard')
    for reserve in layout['heatsink_reserves']:
        region = rect(reserve['box'])
        matching_zones = []
        for zone in board.Zones():
            outline = zone.Outline().Outline(0)
            points = [(p.ToMM(outline.CPoint(i).x), p.ToMM(outline.CPoint(i).y)) for i in range(outline.PointCount())]
            if set(points) == set(region):
                matching_zones.append(zone)
        require(len(matching_zones) == 1, f'{reserve["name"]}: missing or duplicate native rule area')
        if len(matching_zones) == 1:
            zone = matching_zones[0]
            require(set(zone.GetLayerSet().Seq()) == {p.F_Cu} and zone.GetIsRuleArea() and zone.GetDoNotAllowTracks() and zone.GetDoNotAllowVias() and zone.GetDoNotAllowPads() and zone.GetDoNotAllowZoneFills() and not zone.GetDoNotAllowFootprints(), f'{reserve["name"]}: incorrect native keepout layers/flags')
        for ref in refs:
            if ref != reserve['associated_ref'] and not fps[ref].IsFlipped():
                require(not near(region, courts[ref], .15), f'{ref}: intrudes {reserve["name"]} body reserve')
            if fps[ref].IsFlipped():
                require(not any(near(region, j, 1e-4) for j in joints[ref]), f'{ref}: front solder joints intrude {reserve["name"]}')
    for ref, spec in holes.items():
        if ref not in fps:
            continue
        fp = fps[ref]
        require(bool(fp.GetAttributes() & p.FP_BOARD_ONLY), f'{ref}: mounting hole is not board-only')
        pads = list(fp.Pads())
        require(len(pads) == 1 and pads[0].GetAttribute() == p.PAD_ATTRIB_NPTH and abs(p.ToMM(pads[0].GetDrillSize().x) - 3.2) < 1e-5, f'{ref}: expected one 3.2 mm NPTH')
        region = rect([spec['x'] - 3.2, spec['y'] - 3.2, spec['x'] + 3.2, spec['y'] + 3.2])
        for item in refs:
            require(not near(region, courts[item], .15), f'{item}: proposed mounting hardware clearance obstructed by {ref}')
    # RF keepout is an all-face constraint, including the rear battery and capacitors.
    esp = layout['placements']['U202']
    rf = rect([esp['x'] - 24, esp['y'] - 27.75, esp['x'] + 24, esp['y'] - 6.56])
    for ref in refs:
        if ref != 'U202':
            require(not near(rf, courts[ref], 1e-4), f'{ref}: intrudes ESP RF keepout')
    if errors:
        raise RuntimeError('\n'.join(errors))
    def pad_position(ref, number):
        pad = next(pad for pad in fps[ref].Pads() if pad.GetNumber() == number)
        pos = pad.GetPosition()
        return p.ToMM(pos.x), p.ToMM(pos.y)
    driver_distances = {}
    for name, pin, resistor in [('LED1', '7', 'R803'), ('LED2', '5', 'R807')]:
        a, b = pad_position('U801', pin), pad_position(resistor, '1')
        driver_distances[name] = round(((a[0]-b[0])**2 + (a[1]-b[1])**2)**.5, 2)
    result = dict(stage='unrouted two-sided placement candidate; not fabrication release', date='2026-10-21', pcbnew_build=p.GetBuildVersion(),
                  checks_passed=checks, netlisted_references=len(comps), board_only_mounting_holes=len(holes), copper_layers=4, board_mm=[100, 100],
                  face_counts=dict(Counter('B' if fps[r].IsFlipped() else 'F' for r in comps)), back_side_references=sorted(r for r in comps if fps[r].IsFlipped()),
                  connected_physical_pads=connected_pads, connected_netlist_pins=sum(not n.startswith('unconnected-') for n in nets.values()), mapped_netlist_pins_including_nc=len(nets), pad_net_parity=True, routed_tracks=0, routed_vias=0, copper_zones=0,
                  geometry_scope='2D same-face courtyards >= 0.15 mm; opposite-face THT joint guards +0.5 mm; mounting reserves; ESP body and RF reserve; heatsink body reserves',
                  gate_driver_output_to_series_resistor_straight_line_mm=driver_distances,
                  gate_driver_note='Straight-line pin distances, not routed lengths; dedicated return paths, ringing and further placement optimisation remain unqualified.',
                  mechanical_fit_verified=False, heatsink_mounting_pin_coordinates_verified=False, routing_feasibility_verified=False, thermal_verified=False,
                  source_sha256={f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in [board_path, HERE / 'placement.json', HERE / 'review/netlist.xml']})
    if output:
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(f'PASS | placement | {checks} checks; {len(comps)} netlisted references, {len(holes)} proposed NPTH; {len(nets)} pin-net mappings')
    return result


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--board', type=Path, default=HERE / 'PCB_EU.kicad_pcb')
    ap.add_argument('--output', type=Path, default=HERE / 'review/placement.json')
    args = ap.parse_args()
    check(args.board, args.output)
