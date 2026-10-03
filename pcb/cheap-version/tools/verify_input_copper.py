"""Geometric regression screen for the input/PTC reinforcement (KiCad Python).

Checks FILLED polygons, not just their nominal outlines. These body corridors
exclude connector necks, plated holes and thermal modelling; CLI DRC and final
whole-board power-path review remain necessary. No credit for inner copper.
"""
import math
import sys
import route_power as rp
from reinforce_input import SOURCE_VIAS

p=rp.p
CORRIDORS = [
    ('input top',5.5,[(59,54),(80,54)]),
    ('input bottom',5.5,[(59,54),(80,54)]),
    ('loads bottom',5.0,[(89.65,62),(75.8,75.85),(55,75.85)]),
    ('heater top',1.5,[(55,82),(59.3,86.7),(61.85,86.7),(61.85,85.5548),
                      (64.4313,82.9735),(64.46,80.9)]),
    ('heater bottom',1.5,[(55,82),(59,85.5),(64.3,85.5),(64.46,80.9)]),
]


def rings(zone):
    shape=zone.GetFilledPolysList(zone.GetLayer())
    def points(ring):
        return [(p.ToMM(ring.CPoint(i).x),p.ToMM(ring.CPoint(i).y)) for i in range(ring.PointCount())]
    return [(points(shape.Outline(i)),[points(shape.Hole(i,h)) for h in range(shape.HoleCount(i))])
            for i in range(shape.OutlineCount())]


def corridor_width(polygons,path):
    result=1e9
    step=.05
    for a,b in zip(path,path[1:]):
        count=max(1,math.ceil(math.dist(a,b)/step))
        for i in range(count+1):
            pt=tuple(a[k]+(b[k]-a[k])*i/count for k in (0,1))
            containing=[(o,h) for o,h in polygons if rp.inside(pt,o) and not any(rp.inside(pt,q) for q in h)]
            if not containing:
                return 0.0
            o,h=containing[0]
            result=min(result,2*min(rp.edge_distance(pt,q) for q in [o]+h))
    # Distance to a boundary is 1-Lipschitz; subtract one sample pitch to
    # conservatively cover both sides between samples, not only the sample points.
    return max(0,result-step)


def verify(board):
    zones={z.GetZoneName():z for z in board.Zones()}
    for name,minimum,path in CORRIDORS:
        z=zones['auto:input-stage:'+name]
        width=corridor_width(rings(z),path)
        print(f'{name}: continuous body corridor >= {width:.3f} mm (required {minimum:.1f})')
        assert width>=minimum,(name,width,minimum)
    assert not any(not isinstance(t,p.PCB_VIA) and t.GetNetname()=='+24V_LOADS' and
                   t.GetLayer()==p.In2_Cu for t in board.GetTracks()), 'Heater feed still uses inner tracks'
    for x,y in SOURCE_VIAS:
        vias=[t for t in board.GetTracks() if isinstance(t,p.PCB_VIA) and
              t.GetPosition()==p.VECTOR2I(rp.MM(x),rp.MM(y))]
        assert len(vias)==1 and vias[0].GetNetname()=='GND'
        assert vias[0].GetDrillValue()>=rp.MM(.4)
    for ref,number in [('F902','1'),('F902','2'),('J601','1'),('J601','2'),('Q601','2'),('Q601','3')]:
        pads=[q for q in board.FindFootprintByReference(ref).Pads() if q.GetNumber()==number]
        assert pads and all(q.GetLocalZoneConnection()==p.ZONE_CONNECTION_FULL for q in pads)
    print('PASS: reviewed input/PTC corridors, solid power pads and source vias')


if __name__=='__main__':
    verify(rp.load_board(sys.argv[1]))
