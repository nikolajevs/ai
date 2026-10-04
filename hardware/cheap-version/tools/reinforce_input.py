"""Reinforce cheap-1 input/PTC copper without discarding the signal routing.

KiCad Python: reinforce_input.py board.kicad_pcb [--write]
Requires matching project/rules. Repeated runs replace this stage's copper.
This is only the input/PTC stage; LED feeds and converters remain to be reviewed.
"""
import sys
from pathlib import Path
import route_power as rp

p = rp.p
INPUT_TOP = [(52,51),(84,51),(84,76),(75,76),(75,65),(70.5,65),(70.5,61),(52,61)]
LOADS = [(86.5,53),(93,53),(93,64),(77.7,79.3),(51.5,79.3),(51.5,72.8),(75,72.8),(86.5,61.3)]
HEATER = [(51.5,80),(55.5,80),(59.5,84),(62.0,84),(63.5,80),(65.4,80),
          (66.4,83),(66.4,87.8),(58,87.8),(51.5,82)]
POURS = [('input top','+24V','F.Cu',INPUT_TOP),
         ('input bottom','+24V','B.Cu',rp.R(52,51,84,61.5)),
         ('loads bottom','+24V_LOADS','B.Cu',LOADS),
         ('heater top','HEATER_DRAIN','F.Cu',HEATER),
         ('heater bottom','HEATER_DRAIN','B.Cu',HEATER)]
SOURCE_VIAS = [(60.5,80.5),(60.5,81.5),(60.5,82.5),(61.5,82.5)]


def reinforce(board):
    # These polygons belong to the reviewed placement, not an arbitrary board.
    expected = [('J901','2',56.3,57),('J601','1',54.1,78),('J601','2',54.1,81.5),
                ('Q601','2',64.46,80.9),('Q601','3',61.92,80.9),('C901','1',79.7,70.6)]
    for ref,number,x,y in expected:
        fp=board.FindFootprintByReference(ref)
        assert fp is not None,ref
        pads=[q for q in fp.Pads() if q.GetNumber()==number]
        assert len(pads)==1,(ref,number)
        pos=pads[0].GetPosition()
        assert abs(pos.x-rp.MM(x))<=rp.MM(.001) and abs(pos.y-rp.MM(y))<=rp.MM(.001), (ref,'placement changed')
    assert any(isinstance(t,p.PCB_VIA) and t.GetNetname()=='+24V_LOADS' and
               t.GetPosition()==p.VECTOR2I(rp.MM(67.2),rp.MM(84)) for t in board.GetTracks()), 'Pump branch via missing'
    for z in list(board.Zones()):
        if z.GetZoneName().startswith('auto:input-stage:'):
            rp.discard(board,z)
    for t in list(board.GetTracks()):
        if not isinstance(t,p.PCB_VIA) and t.GetNetname()=='+24V_LOADS' and t.GetLayer() in (p.In2_Cu,p.B_Cu):
            rp.discard(board,t)
    for name,net,layer,outline in POURS:
        rp.add_zone(board,'input-stage:'+name,net,layer,outline,solid=True)
    # Reconnect the <=0.5 A pump branch around, not across, the PTC drain pour.
    rp.add_track(board,'+24V_LOADS','B.Cu',1.0,[(69.5,77),(69.5,81.7),(67.2,84)])
    for ref,number in [('F902','1'),('F902','2'),('J601','1'),('J601','2'),
                       ('Q601','2'),('Q601','3'),('C901','1')]:
        for pad in board.FindFootprintByReference(ref).Pads():
            if pad.GetNumber()==number:
                pad.SetLocalZoneConnection(p.ZONE_CONNECTION_FULL)
    for x,y in SOURCE_VIAS:
        if not any(isinstance(t,p.PCB_VIA) and t.GetNetname()=='GND' and
                   t.GetPosition()==p.VECTOR2I(rp.MM(x),rp.MM(y)) for t in board.GetTracks()):
            rp.add_via(board,'GND','M',x,y)
    p.ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()
    for x,y in SOURCE_VIAS:
        found=[t for t in board.GetTracks() if isinstance(t,p.PCB_VIA) and
               t.GetPosition()==p.VECTOR2I(rp.MM(x),rp.MM(y))]
        assert len(found)==1 and found[0].GetNetname()=='GND', 'Source via changed net during fill'


if __name__=='__main__':
    board=rp.load_board(sys.argv[1])
    reinforce(board)
    print('unrouted',board.GetConnectivity().GetUnconnectedCount(False))
    if '--write' in sys.argv:
        p.SaveBoard(sys.argv[1],board)
        path=Path(sys.argv[1])
        path.write_text(path.read_text(encoding='utf-8'),encoding='utf-8',newline='\n')
