"""Footprint-level dump of the board for the assembly drawings (KiCad Python):

  "C:/Program Files/KiCad/10.0/bin/python.exe" export_assembly.py out.json [board.kicad_pcb]

For every footprint: reference, value, part fields, library name, side, mounting type (SMD / THT), position, rotation,
courtyard, silkscreen and fab outlines (as filled polygons of the strokes), and its pads (number, net, outline per copper
layer, drill). Board outline included. Used by make_assembly_doc.py; coordinates are board millimetres.
"""
import json
import sys
from pathlib import Path

import pcbnew as p

HERE = Path(__file__).resolve().parents[1]
out = Path(sys.argv[1])
board = p.LoadBoard(str(Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / 'cheap-version.kicad_pcb'))
mm = p.ToMM


def polys(pset):
    res = []
    for i in range(pset.OutlineCount()):
        o = pset.Outline(i)
        outline = [(mm(o.CPoint(k).x), mm(o.CPoint(k).y)) for k in range(o.PointCount())]
        holes = []
        for h in range(pset.HoleCount(i)):
            hole = pset.Hole(i, h)
            holes.append([(mm(hole.CPoint(k).x), mm(hole.CPoint(k).y)) for k in range(hole.PointCount())])
        res.append(dict(o=outline, h=holes))
    return res


def shape_polys(g, layer):
    pset = p.SHAPE_POLY_SET()
    g.TransformShapeToPolygon(pset, layer, 0, p.FromMM(0.02), p.ERROR_INSIDE)
    pset.Simplify() if hasattr(pset, 'Simplify') else None
    return polys(pset)


def fields(fp):
    return {f.GetName(): f.GetText() for f in fp.GetFields()}


data = dict(board=[], fps=[])
for d in board.GetDrawings():
    if d.GetLayer() == p.Edge_Cuts:
        bb = d.GetBoundingBox()
        data['board'].append((mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())))
for fp in board.GetFootprints():
    flipped = fp.IsFlipped()
    silk, fab, cu = (p.B_SilkS, p.B_Fab, p.B_Cu) if flipped else (p.F_SilkS, p.F_Fab, p.F_Cu)
    attrs = fp.GetAttributes()
    entry = dict(ref=fp.GetReference(), value=fp.GetValue(), fields=fields(fp), lib=str(fp.GetFPID().GetLibItemName()),
                 side='B' if flipped else 'F', kind='THT' if attrs & p.FP_THROUGH_HOLE else ('SMD' if attrs & p.FP_SMD else 'OTHER'),
                 x=mm(fp.GetPosition().x), y=mm(fp.GetPosition().y), rot=fp.GetOrientationDegrees(),
                 no_bom=bool(attrs & p.FP_EXCLUDE_FROM_BOM), dnp=bool(attrs & p.FP_DNP), silk=[], fab=[], court=[], pads=[])
    for g in fp.GraphicalItems():
        if hasattr(g, 'GetText'):
            continue
        if g.GetLayer() == silk:
            entry['silk'] += shape_polys(g, silk)
        elif g.GetLayer() == fab:
            entry['fab'] += shape_polys(g, fab)
    cy = fp.GetCourtyard(p.B_CrtYd if flipped else p.F_CrtYd)
    if cy.OutlineCount():
        entry['court'] = polys(cy)
    for pad in fp.Pads():
        if pad.IsOnLayer(cu) or pad.GetDrillSizeX() > 0:
            entry['pads'].append(dict(n=pad.GetNumber(), net=pad.GetNetname(), x=mm(pad.GetPosition().x), y=mm(pad.GetPosition().y),
                                      drill=mm(pad.GetDrillSizeX()), tht=pad.GetAttribute() == p.PAD_ATTRIB_PTH,
                                      npth=pad.GetAttribute() == p.PAD_ATTRIB_NPTH,
                                      poly=polys(pad.GetEffectivePolygon(cu if pad.IsOnLayer(cu) else p.F_Cu))))
    data['fps'].append(entry)
out.write_text(json.dumps(data), encoding='utf-8')
print('wrote', out, len(data['fps']), 'footprints')
