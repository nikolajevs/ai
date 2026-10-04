"""JLCDFM-style touch-ups of the cheap-1 routing (KiCad Python): fab_touchups.py board.kicad_pcb [--write]

hardware/check_fab.py reports nine tracks that pass a pad of their own net within 0.03 - 0.085 mm without touching it, so the
solder-mask opening of the pad exposes the track (JLCDFM "solder mask opening exposing trace"). Every case is a router
corner next to the pad; the segments are merged so that the track starts on the pad (or, for the net tie NT722, the
corner moves 0.2 mm onto the pad). Each edit is tied to coordinates of the committed routing and skipped with a message
when its segments are not found, so a repeated run changes nothing. The two silk labels with the PCB_V1 revision are
renamed. Zones are refilled at the end; DRC must stay clean.
"""
import sys
from pathlib import Path

import route_power as rp

p = rp.p
mm, FM = p.ToMM, p.FromMM
LABELS = {'GROWBOX 24V / 0.22': 'GROWBOX 24V / CHEAP-1', 'GROWBOX 0.22 / BOTTOM': 'GROWBOX CHEAP-1 / BOTTOM'}
G = []              # removed items stay referenced


def near(point, x, y, tol=0.006):
    return abs(mm(point.x) - x) < tol and abs(mm(point.y) - y) < tol


def segment(board, a, b, layer='F.Cu'):
    for t in board.GetTracks():
        if isinstance(t, p.PCB_VIA) or board.GetLayerName(t.GetLayer()) != layer:
            continue
        if (near(t.GetStart(), *a) and near(t.GetEnd(), *b)) or (near(t.GetStart(), *b) and near(t.GetEnd(), *a)):
            return t
    return None


def replace(board, old, new, label, layer='F.Cu'):
    """replace the segments `old` by `new` (same net, width, layer and lock as the first of them)"""
    found = [segment(board, a, b, layer) for a, b in old]
    if not all(found):
        print(f'skip {label}: segments not found')
        return
    proto = found[0]
    width, net, lay, locked = proto.GetWidth(), proto.GetNet(), proto.GetLayer(), proto.IsLocked()
    for t in found:
        board.Remove(t)
        G.append(t)
    for a, b in new:
        t = p.PCB_TRACK(board)
        t.SetStart(p.VECTOR2I(FM(a[0]), FM(a[1])))
        t.SetEnd(p.VECTOR2I(FM(b[0]), FM(b[1])))
        t.SetWidth(width)
        t.SetLayer(lay)
        t.SetNet(net)
        t.SetLocked(locked)
        board.Add(t)
    print(f'done {label}')


def apply(board):
    replace(board, [((136.39, 78.0), (135.69, 77.30)), ((135.69, 77.30), (135.69, 76.92))],
            [((136.39, 78.0), (135.69, 76.92))], '+3V3 at R408.1')
    replace(board, [((109.78, 126.10), (110.34, 126.66)), ((110.34, 126.66), (110.34, 127.28))],
            [((109.78, 126.10), (110.34, 127.28))], '+3V3 at C700.1')
    replace(board, [((57.80, 106.30), (57.80, 104.28)), ((57.80, 104.28), (57.80, 103.91))],
            [((57.80, 106.30), (57.80, 103.91))], '+24V at F711.1')
    replace(board, [((93.62, 82.18), (92.97, 82.18)), ((92.97, 82.18), (91.61, 83.55))],
            [((93.62, 82.18), (91.61, 83.55))], 'AUX_VIN at F904.2')
    replace(board, [((123.47, 81.81), (122.31, 81.81)), ((122.31, 81.81), (122.18, 81.95))],
            [((123.47, 81.81), (122.18, 81.95))], 'RTC_OSCO at U301.2')
    replace(board, [((128.72, 125.56), (128.72, 126.05)), ((128.72, 126.05), (129.93, 127.25))],
            [((128.72, 125.56), (129.93, 127.25))], 'LED2_CS at U720.4')
    replace(board, [((109.49, 124.35), (108.99, 124.85)), ((108.99, 124.85), (108.99, 125.01))],
            [((109.49, 124.35), (108.99, 125.01))], 'LED_DIM at U700.4')
    # LED2_RETURN runs under the Kelvin net tie NT722.1 (0.025 mm); the corner at R726.1 moves 0.2 mm up onto the tie pad
    moved = 0
    for t in board.GetTracks():
        if isinstance(t, p.PCB_VIA) or t.GetNetname().split('/')[-1] != 'LED2_RETURN' or board.GetLayerName(t.GetLayer()) != 'F.Cu':
            continue
        for end in ('Start', 'End'):
            pt = getattr(t, 'Get' + end)()
            for x in (89.05, 98.69):
                if near(pt, x, 137.05):
                    getattr(t, 'Set' + end)(p.VECTOR2I(FM(x), FM(136.85)))
                    moved += 1
    print(f'done LED2_RETURN at NT722.1 ({moved} track ends moved)' if moved else 'skip LED2_RETURN at NT722.1: not found')
    # board labels still carry the PCB_V1 revision
    for d in board.GetDrawings():
        if hasattr(d, 'GetText'):
            new = LABELS.get(d.GetText())
            if new:
                d.SetText(new)
                print(f'done label {new!r}')
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
