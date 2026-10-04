"""Local HF bypass at the ST1S14 VIN pin (KiCad Python): add_c911.py board.kicad_pcb [--write]

U902 (ST1S14) is fed from F904/C905/C906 through about 15 mm of 0.6 mm copper with two vias, half of it on B.Cu where
the nearest plane is the +3V3 flood, not GND (hot-loop estimate 15 nH or more). C911, 100 nF 0603 (a copy of C907), sits
on the bottom side right under pins 6/7: its AUX_VIN pad lies on the existing B.Cu AUX_VIN track, its GND pad has a
via beside it into In1 and a short AUX_VIN via next to pin 7 closes the loop (about 5 nH). Repeatable: the part, its
via and track are replaced.
"""
import re
import sys
from pathlib import Path

import route_power as rp

p = rp.p
HERE = Path(__file__).resolve().parents[1]
CENTRE = (100.1, 85.1)          # between the pads, vertical, bottom side
GND_VIA = (101.1, 85.9)
AUX_VIA = (101.1, 84.67)        # on the F.Cu track pin 7 -> via (102.27, 84.67), above the B.Cu AUX_VIN track
GND_TRACK = [(100.1, 85.875), GND_VIA]
SHEET = '/7c30e6d8-4e60-4647-b4d3-d05e639d6467/13f6ec92-6d25-5cb3-b953-f0854e3d007b'


def symbol_uuid():
    text = (HERE / 'InputPower.kicad_sch').read_text(encoding='utf-8')
    i = text.index('(property "Reference" "C911"')
    j = text.rfind('(symbol', 0, i)
    return re.search(r'\(uuid "?([0-9a-f-]{36})"?\)', text[j:i]).group(1)


def near(pt, x, y, tol=0.01):
    return abs(p.ToMM(pt.x) - x) < tol and abs(p.ToMM(pt.y) - y) < tol


def apply(board):
    old = board.FindFootprintByReference('C911')
    if old is not None:
        board.Remove(old)
        rp.GRAVEYARD.append(old)
    for t in list(board.GetTracks()):
        hit = (near(t.GetPosition(), *GND_VIA) or near(t.GetPosition(), *AUX_VIA)) if isinstance(t, p.PCB_VIA) else \
            (near(t.GetStart(), *GND_TRACK[0]) and near(t.GetEnd(), *GND_VIA))
        if hit:
            rp.discard(board, t)
    src = board.FindFootprintByReference('C907')
    fp = p.FOOTPRINT(src)
    fp.SetReference('C911')
    fp.SetPath(p.KIID_PATH(f'{SHEET}/{symbol_uuid()}'))
    board.Add(fp)
    fp.SetPosition(p.VECTOR2I(rp.MM(CENTRE[0]), rp.MM(CENTRE[1])))
    fp.Flip(fp.GetPosition(), False)            # to B.Cu
    assert fp.IsFlipped()
    # pad 1 (AUX_VIN) above pad 2 (GND): try both quarter turns
    for angle in (90, 270, 0, 180):
        fp.SetOrientationDegrees(angle)
        pads = {pad.GetNumber(): pad.GetPosition() for pad in fp.Pads()}
        if abs(p.ToMM(pads['1'].x) - CENTRE[0]) < 0.01 and p.ToMM(pads['1'].y) < p.ToMM(pads['2'].y):
            break
    else:
        raise AssertionError('no orientation puts pad 1 above pad 2')
    for pad in fp.Pads():
        pad.SetNet(rp.net(board, 'AUX_VIN' if pad.GetNumber() == '1' else 'GND'))
    fp.Reference().SetVisible(False)
    rp.add_track(board, 'GND', 'B.Cu', 0.3, GND_TRACK)
    rp.add_via(board, 'GND', 'S', *GND_VIA)
    rp.add_via(board, 'AUX_VIN', 'M', *AUX_VIA)
    p.ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()


if __name__ == '__main__':
    board = rp.load_board(sys.argv[1])
    apply(board)
    c = board.FindFootprintByReference('C911')
    print('C911 pads', [(pad.GetNumber(), pad.GetNetname(), round(p.ToMM(pad.GetPosition().x), 3), round(p.ToMM(pad.GetPosition().y), 3)) for pad in c.Pads()])
    print('unrouted', board.GetConnectivity().GetUnconnectedCount(False))
    if '--write' in sys.argv:
        p.SaveBoard(sys.argv[1], board)
        path = Path(sys.argv[1])
        path.write_text(path.read_text(encoding='utf-8'), encoding='utf-8', newline='\n')
