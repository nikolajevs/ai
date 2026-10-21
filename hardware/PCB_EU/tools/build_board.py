#!/usr/bin/env python3
"""Build the UNROUTED EU placement candidate from the exported netlist.

Requires the Python interpreter providing KiCad's pcbnew module. Placement is
specified in millimetres at library origins, viewed from the front. Back-side
footprints are flipped first, then given the specified front-view rotation.
Refuses to overwrite any board containing routed copper or filled zones.
SPDX-License-Identifier: MIT
"""
import argparse
import json
from pathlib import Path
import re
import uuid
import xml.etree.ElementTree as ET

import pcbnew as p

HERE = Path(__file__).resolve().parents[1]
BOARD = HERE / 'PCB_EU.kicad_pcb'
NAMESPACE = uuid.UUID('ba9a6b93-12d3-43ea-89a9-584c087740ac')


def point(x, y):
    return p.VECTOR2I(p.FromMM(x), p.FromMM(y))


def identity(item, name):
    value = p.KIID(str(uuid.uuid5(NAMESPACE, name)))
    if hasattr(item, 'SetUuidDirect'):
        item.SetUuidDirect(value)
    else:
        item.m_Uuid.Clone(value)


def load_electrical():
    """Fresh footprints with exact schematic paths and all duplicate pads mapped."""
    root = ET.parse(HERE / 'review/netlist.xml').getroot()
    board = p.BOARD()
    identity(board, 'board')
    board.SetCopperLayerCount(4)
    board.GetDesignSettings().SetBoardThickness(p.FromMM(1.6))
    root_uuid = re.search(r'\(uuid "([^"]+)"', (HERE / 'PCB_EU.kicad_sch').read_text()).group(1)
    fps = {}
    for comp in root.findall('./components/comp'):
        ref = comp.get('ref')
        lib, name = comp.findtext('footprint').split(':', 1)
        fp = p.FootprintLoad(str(HERE / 'libraries' / (lib + '.pretty')), name)
        if fp is None:
            raise RuntimeError(f'{ref}: cannot load {lib}:{name}')
        fp.SetFPID(p.LIB_ID(lib, name))
        fp.SetReference(ref)
        fp.SetValue(comp.findtext('value'))
        for field in comp.findall('./fields/field'):
            if field.get('name') == 'Footprint':
                continue  # The library ID above is the native PCB footprint field.
            fp.SetField(field.get('name'), field.text or '')
            fp.GetField(field.get('name')).SetVisible(False)
        path = p.KIID_PATH()
        for u in [root_uuid] + [u for u in comp.find('sheetpath').get('tstamps').split('/') if u] + [comp.findtext('tstamps')]:
            path.push_back(p.KIID(u))
        fp.SetPath(path)
        identity(fp, ref)
        for i, item in enumerate([*fp.Pads(), *fp.GraphicalItems(), *fp.Zones(), *fp.GetFields()]):
            identity(item, f'{ref}/item/{i}')
        board.Add(fp)
        fps[ref] = fp
    for item in root.findall('./nets/net'):
        net = p.NETINFO_ITEM(board, item.get('name'))
        board.Add(net)
        for node in item.findall('node'):
            pads = [pad for pad in fps[node.get('ref')].Pads() if pad.GetNumber() == node.get('pin')]
            if not pads:
                raise RuntimeError(f'No pad: {node.attrib}')
            for pad in pads:
                pad.SetNet(net)
    return board, fps


def line(board, name, a, b, layer, width=.05):
    item = p.PCB_SHAPE()
    item.SetShape(p.SHAPE_T_SEGMENT)
    item.SetStart(point(*a))
    item.SetEnd(point(*b))
    item.SetLayer(layer)
    item.SetWidth(p.FromMM(width))
    identity(item, name)
    board.Add(item)


def rectangle(board, name, box, layer):
    x0, y0, x1, y1 = box
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    for i in range(4):
        line(board, f'{name}/{i}', pts[i], pts[(i + 1) % 4], layer, .1)


def label(board, name, text, x, y, size=1):
    item = p.PCB_TEXT(board)
    item.SetText(text)
    item.SetPosition(point(x, y))
    item.SetLayer(p.Dwgs_User)
    item.SetTextSize(point(size, size))
    item.SetTextThickness(p.FromMM(.15))
    identity(item, name)
    board.Add(item)


def mounting_hole(board, spec):
    fp = p.FOOTPRINT(board)
    ref, x, y = spec['ref'], spec['x'], spec['y']
    fp.SetReference(ref)
    fp.SetValue('M3 NPTH 3.2 / proposed')
    fp.SetAttributes(p.FP_BOARD_ONLY | p.FP_EXCLUDE_FROM_BOM | p.FP_EXCLUDE_FROM_POS_FILES)
    identity(fp, ref)
    pad = p.PAD(fp)
    pad.SetAttribute(p.PAD_ATTRIB_NPTH)
    pad.SetShape(p.PAD_SHAPE_CIRCLE)
    pad.SetSize(point(3.2, 3.2))
    pad.SetDrillSize(point(3.2, 3.2))
    # Never mutate the static AllCuMask() object: doing so makes the serializer
    # incorrectly treat solder-mask layers as part of the *.Cu wildcard.
    hole_layers = p.LSET()
    hole_layers.AddLayerSet(p.LSET.AllCuMask())
    hole_layers.AddLayer(p.F_Mask)
    hole_layers.AddLayer(p.B_Mask)
    pad.SetLayerSet(hole_layers)
    identity(pad, ref + '/hole')
    fp.Add(pad)
    for layer in [p.F_CrtYd, p.B_CrtYd]:
        circle = p.PCB_SHAPE(fp)
        circle.SetShape(p.SHAPE_T_CIRCLE)
        circle.SetCenter(point(0, 0))
        circle.SetEnd(point(3.2, 0))
        circle.SetLayer(layer)
        circle.SetWidth(p.FromMM(.05))
        identity(circle, f'{ref}/courtyard/{layer}')
        fp.Add(circle)
    fp.Reference().SetLayer(p.F_Fab)
    fp.Reference().SetPosition(point(0, -4))
    fp.Value().SetVisible(False)
    for i, field in enumerate(fp.GetFields()):
        identity(field, f'{ref}/field/{i}')
    board.Add(fp)
    fp.SetPosition(point(x, y))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, default=BOARD,
                    help='New unrouted base; existing routed copper is never overwritten')
    args = ap.parse_args()
    if args.output.exists():
        old = p.LoadBoard(str(args.output))
        if len(old.GetTracks()) or any(not z.GetIsRuleArea() for z in old.Zones()):
            raise SystemExit('Refusing to overwrite routed tracks, vias or copper zones; preserve manual routing.')
    layout = json.loads((HERE / 'placement.json').read_text())
    board, fps = load_electrical()
    if set(layout['placements']) != set(fps):
        raise RuntimeError('placement.json reference set differs from exported netlist')
    for ref, spec in layout['placements'].items():
        fp = fps[ref]
        if spec['side'] == 'B':
            fp.Flip(point(0, 0), False)
        elif spec['side'] != 'F':
            raise RuntimeError(f'{ref}: invalid side')
        fp.SetOrientationDegrees(spec['rotation'])
        fp.SetPosition(point(spec['x'], spec['y']))
        # Assembly references belong on Fab until silkscreen is designed.
        fp.Reference().SetLayer(p.B_Fab if fp.IsFlipped() else p.F_Fab)
        if any(hasattr(item, 'GetText') and item.GetText() in ('${REFERENCE}', '%R') and item.GetLayer() in (p.F_Fab, p.B_Fab) for item in fp.GraphicalItems()):
            fp.Reference().SetVisible(False)  # The library already has a centred Fab reference.
        fp.Value().SetVisible(False)
    w, h = layout['board_mm']
    rectangle(board, 'outline', [0, 0, w, h], p.Edge_Cuts)
    for hole in layout['mounting_holes']:
        mounting_hole(board, hole)
    for reserve in layout['heatsink_reserves']:
        rectangle(board, reserve['name'], reserve['box'], p.Dwgs_User)
        x0, y0, x1, y1 = reserve['box']
        label(board, reserve['name'] + '/text', reserve['name'] + '\nRESERVE ONLY', (x0 + x1) / 2, (y0 + y1) / 2, 1.3)
        zone = p.ZONE(board)
        identity(zone, reserve['name'] + '/keepout')
        zone.SetIsRuleArea(True)
        layers = p.LSET()
        # Front-side body reserve; rear SMDs are allowed. Guide-pin locations
        # remain unqualified and can require later movement of rear parts.
        for layer in [p.F_Cu]:
            layers.AddLayer(layer)
        zone.SetLayerSet(layers)
        zone.SetDoNotAllowTracks(True)
        zone.SetDoNotAllowVias(True)
        zone.SetDoNotAllowPads(True)
        zone.SetDoNotAllowZoneFills(True)
        # The associated TO-220 body enters this region; its pads remain outside.
        # verify_board.py separately checks every other component against it.
        zone.SetDoNotAllowFootprints(False)
        outline = zone.Outline()
        outline.NewOutline()
        for x, y in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]:
            outline.Append(p.FromMM(x), p.FromMM(y))
        board.Add(zone)
    label(board, 'stage', 'EU-0.1 / UNROUTED PLACEMENT / 100 x 100 mm / 4 Cu', 50, -17, 1.3)
    label(board, 'limits', 'HS guide holes / thermal / routing NOT qualified', 50, -14.5)
    p.SaveBoard(str(args.output), board)
    print(f'Built {len(fps)} netlisted references + {len(layout["mounting_holes"])} proposed mounting holes; 0 tracks/vias/copper pours')


if __name__ == '__main__':
    main()
