"""Widen the +12V fan line on In2 (KiCad Python): reinforce_12v.py board.kicad_pcb [--write]

The two fans (0.68 A) are fed over In2, 0.5 mm of 0.5 oz copper for about 45 mm: about +28 K by IPC-2221 (open question
since PCB_V1). The segments below become 0.8 mm (the PWR12 class width, about +11 K at 0.68 A); the outer layers around
them are too crowded for a wider track, and a 6.5 mm neck between two vias and an ESP_IO0 track stays 0.5 mm.
Repeatable.
"""
import sys
from pathlib import Path
import route_power as rp

p = rp.p
WIDTH = 0.8
NECK = 129.0            # y of the split below the congested neck (vias LED2_DRV, GND and the ESP_IO0 track nearby)
# segments widened to 0.8 mm; the neck (123.7,122.5)..(124.4,129.0) stays 0.5 mm, 6.5 mm long, heat flows into the wide copper
LINE = [((122.6, 96.1), (122.6, 113.8)), ((122.6, 113.8), (127.8, 119.0)), ((124.4, 127.3), (124.4, 139.4)),
        ((124.4, 139.4), (125.0, 140.0))]


def key(t):
    return (round(p.ToMM(t.GetStart().x), 1), round(p.ToMM(t.GetStart().y), 1),
            round(p.ToMM(t.GetEnd().x), 1), round(p.ToMM(t.GetEnd().y), 1))


def apply(board):
    want = {(a[0], a[1], b[0], b[1]) for a, b in LINE}
    found = set()
    for t in list(board.GetTracks()):
        if isinstance(t, p.PCB_VIA) or t.GetLayer() != p.In2_Cu or t.GetNetname() != '+12V':
            continue
        k = key(t)
        if k == (124.4, 127.3, 124.4, 139.4):       # split: 0.5 mm neck above NECK, 0.8 mm below
            t.SetStart(p.VECTOR2I(rp.MM(124.4), rp.MM(NECK)))
            rp.add_track(board, '+12V', 'In2.Cu', 0.5, [(124.4, 127.3), (124.4, NECK)])
        elif k == (124.4, NECK, 124.4, 139.4):      # already split on an earlier run
            pass
        elif k not in want:
            continue
        t.SetWidth(rp.MM(WIDTH))
        found.add(k)
    assert len(found) == len(want), ('fan line segments not found', sorted(want - found))
    p.ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()


if __name__ == '__main__':
    board = rp.load_board(sys.argv[1])
    apply(board)
    print('unrouted', board.GetConnectivity().GetUnconnectedCount(False))
    if '--write' in sys.argv:
        p.SaveBoard(sys.argv[1], board)
        path = Path(sys.argv[1])
        path.write_text(path.read_text(encoding='utf-8'), encoding='utf-8', newline='\n')
