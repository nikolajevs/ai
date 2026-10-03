"""Dump the copper of the cheap-1 board to JSON for tools/view.py (KiCad Python).

  "C:/Program Files/KiCad/10.0/bin/python.exe" pcb/cheap-version/tools/export_view.py out.json [board.kicad_pcb] [--no-zones]

Pads (outline polygons per layer), tracks, vias, filled zone polygons and footprint courtyards, in board millimetres.
"""
import json
import sys
from pathlib import Path

import pcbnew as p

HERE = Path(__file__).resolve().parents[1]
args = [a for a in sys.argv[1:] if not a.startswith("--")]
out = Path(args[0])
board = p.LoadBoard(str(Path(args[1]) if len(args) > 1 else HERE / "cheap-version.kicad_pcb"))
mm = p.ToMM
LAYERS = {"F": p.F_Cu, "I1": p.In1_Cu, "I2": p.In2_Cu, "B": p.B_Cu}


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


data = dict(pads=[], tracks=[], vias=[], zones=[], courtyards=[], texts=[])
for fp in board.GetFootprints():
    ref = fp.GetReference()
    for pad in fp.Pads():
        entry = dict(ref=ref, n=pad.GetNumber(), net=pad.GetNetname(), x=mm(pad.GetPosition().x), y=mm(pad.GetPosition().y),
                     drill=mm(pad.GetDrillSizeX()), layers={})
        for key, layer in LAYERS.items():
            if pad.IsOnLayer(layer):
                entry["layers"][key] = polys(pad.GetEffectivePolygon(layer))
        data["pads"].append(entry)
    layer = p.B_CrtYd if fp.IsFlipped() else p.F_CrtYd
    cy = fp.GetCourtyard(layer)
    if cy.OutlineCount():
        data["courtyards"].append(dict(ref=ref, side="B" if fp.IsFlipped() else "F", polys=polys(cy),
                                       x=mm(fp.GetPosition().x), y=mm(fp.GetPosition().y)))
for t in board.GetTracks():
    if isinstance(t, p.PCB_VIA):
        data["vias"].append(dict(x=mm(t.GetPosition().x), y=mm(t.GetPosition().y), d=mm(t.GetWidth(p.F_Cu)), drill=mm(t.GetDrillValue()),
                                 net=t.GetNetname()))
    else:
        data["tracks"].append(dict(layer=board.GetLayerName(t.GetLayer()), x0=mm(t.GetStart().x), y0=mm(t.GetStart().y),
                                   x1=mm(t.GetEnd().x), y1=mm(t.GetEnd().y), w=mm(t.GetWidth()), net=t.GetNetname()))
if "--no-zones" not in sys.argv:
    for z in board.Zones():
        for key, layer in LAYERS.items():
            if z.IsOnLayer(layer) and not z.GetIsRuleArea():
                data["zones"].append(dict(name=z.GetZoneName(), net=z.GetNetname(), layer=key, polys=polys(z.GetFilledPolysList(layer))))
json.dump(data, open(out, "w"))
print("wrote", out, len(data["pads"]), "pads", len(data["tracks"]), "tracks", len(data["vias"]), "vias", len(data["zones"]), "zone layers")
