"""Reinforce cheap-1 LED/+24V distribution copper without discarding the signal routing.

KiCad Python: reinforce_led.py board.kicad_pcb [--write]
Requires matching project/rules. Repeated runs replace this stage's copper ('auto:led-stage:*' zones and the tracks/vias
marked below). Replaces the 150 mm 0.5 oz In2 +24V loop and the 0.5 oz In2 LED2_OUT run by outer-layer copper:

  input F.Cu pour -> vias beside the B.Cu +24V_LOADS band -> B.Cu trunk -> vias -> F.Cu feeds of F711 / F721

and widens the LED channel VIN / SW nodes. Run after reinforce_input.py (its LOADS band shapes the crossing).
"""
import sys
from pathlib import Path
import route_power as rp

p = rp.p
R = rp.R
LED = '/LEDDrivers/'

# (name, net, layer, outline) ----------------------------------------------------------------------------------
POURS = [
    # +24V crosses the B.Cu +24V_LOADS band on F.Cu (band edge: y = 157 - x), then continues on B.Cu
    ('cross top', '+24V', 'F.Cu', R(76, 75, 85.7, 78.9)),
    ('trunk', '+24V', 'B.Cu', [(85.9, 72.0), (86.3, 72.0), (86.3, 78.9), (83.6, 79.4), (83.6, 86.0), (81.6, 86.0),
                               (81.6, 110.0), (71.0, 110.0), (71.0, 79.9), (77.9, 79.9)]),
    ('ch2 branch', '+24V', 'B.Cu', R(79.0, 100.2, 99.8, 105.6)),
    ('ch2 end', '+24V', 'B.Cu', R(99.0, 103.0, 105.9, 108.4)),
    ('ch1 feed', '+24V', 'F.Cu', R(57.3, 103.28, 82.0, 109.5)),
    ('ch2 feed', '+24V', 'F.Cu', R(99.2, 103.9, 105.7, 108.5)),
    # channel inputs and switching nodes
    ('led1 vin a', LED + 'LED1_VIN', 'F.Cu', R(56.23, 110.4, 59.38, 117.9)),
    ('led1 vin b', LED + 'LED1_VIN', 'F.Cu', R(55.3, 117.0, 57.4, 119.4)),
    ('led1 vin c', LED + 'LED1_VIN', 'F.Cu', [(58.3, 114.0), (62.6, 114.0), (62.6, 119.0), (60.2, 119.0),
                                              (60.2, 118.2), (58.3, 118.2)]),
    ('led1 sw a', LED + 'LED1_SW', 'F.Cu', R(79.0, 112.0, 84.6, 119.1)),
    ('led1 sw b', LED + 'LED1_SW', 'F.Cu', R(82.8, 111.9, 86.6, 114.8)),
    ('led1 sw c', LED + 'LED1_SW', 'F.Cu', R(78.0, 117.0, 82.4, 122.4)),
    ('led2 vin a', LED + 'LED2_VIN', 'F.Cu', R(106.12, 104.7, 109.0, 112.0)),
    ('led2 vin b', LED + 'LED2_VIN', 'F.Cu', R(106.12, 111.0, 110.1, 114.0)),
    ('led2 sw a', LED + 'LED2_SW', 'F.Cu', R(119.6, 112.4, 122.7, 117.3)),
    ('led2 sw b', LED + 'LED2_SW', 'F.Cu', R(122.3, 110.4, 125.9, 113.5)),
]
# (net, size, [(x, y), ...])
VIAS = [
    # beside the band edge, kept 0.2 mm off the C901 pad (JLCDFM: via to pad) and off the pads at y >= 79.5
    ('+24V', 'M', [(80.0, 78.4), (80.9, 77.5), (81.7, 76.7), (82.5, 76.0), (83.6, 76.0), (84.4, 75.3),
                   (81.3, 78.5), (82.1, 77.7), (82.9, 77.0), (84.0, 77.0), (84.8, 76.3), (83.1, 78.1)]),
    ('+24V', 'M', [(x, y) for y in (106.4, 108.0) for x in (72.0, 73.3, 74.6, 75.9, 77.2, 78.5)]),  # CH1 feed
    ('+24V', 'M', [(100.0, 104.8), (100.0, 106.0), (100.0, 107.2), (104.6, 104.8), (104.6, 107.6)]),  # CH2 feed
]
# LED2_OUT leaves the 0.5 oz In2 layer: 1.2 mm on B.Cu from the via at (109.95, 109.76) to J731 pin 1
TRACKS = [
    (LED + 'LED2_OUT', 'B.Cu', 1.2, [(109.95, 109.76), (103.8, 109.8), (100.1, 113.9), (100.1, 119.9), (101.3, 121.8),
                                     (101.3, 123.7), (100.2, 125.5), (100.2, 134.9), (99.4, 137.7), (95.5, 141.6),
                                     (94.0, 144.1)]),
]
EXPECTED = [('F711', '1', 57.8, 106.3), ('F711', '2', 57.8, 111.2), ('F721', '1', 102.19, 106.25),
            ('F721', '2', 107.11, 106.25), ('L711', '1', 62.15, 120.0), ('L711', '2', 79.65, 120.0),
            ('Q711', '5', 85.8, 116.85), ('L721', '1', 108.55, 114.85), ('L721', '2', 119.65, 114.85),
            ('Q721', '5', 124.45, 115.2), ('J731', '1', 94.0, 144.1), ('F902', '1', 79.85, 56.35)]


def same(a, b):
    return abs(a - b) <= 0.01


def pos_mm(item):
    pos = item.GetPosition()
    return p.ToMM(pos.x), p.ToMM(pos.y)


def reinforce(board):
    for ref, number, x, y in EXPECTED:
        fp = board.FindFootprintByReference(ref)
        assert fp is not None, ref
        pads = [q for q in fp.Pads() if q.GetNumber() == number]
        assert pads, (ref, number)
        px, py = pos_mm(pads[0])
        assert same(px, x) and same(py, y), (ref, number, 'placement changed', px, py)
    for z in list(board.Zones()):
        if z.GetZoneName().startswith('auto:led-stage:'):
            rp.discard(board, z)
    for t in list(board.GetTracks()):
        net = t.GetNetname().split('/')[-1]
        is_via = isinstance(t, p.PCB_VIA)
        if not is_via and net == '+24V' and t.GetLayer() == p.In2_Cu:
            rp.discard(board, t)
        elif not is_via and net == 'LED2_OUT' and (t.GetLayer() == p.In2_Cu or
                                                    (t.GetLayer() == p.B_Cu and p.ToMM(t.GetWidth()) >= 1.0)):
            rp.discard(board, t)        # the 0.8 mm In2 run, and this stage's own B.Cu track on a repeated run
        elif not is_via and net == '+24V' and t.GetLayer() == p.F_Cu and same(p.ToMM(t.GetStart().y), 104.28) \
                and same(p.ToMM(t.GetEnd().y), 104.28) and p.ToMM(t.GetEnd().x) > 80:
            rp.discard(board, t)        # the 2 mm band is now the 'ch1 feed' pour
        elif is_via and net == '+24V' and same(pos_mm(t)[0], 87.3):
            rp.discard(board, t)
        elif is_via and net == '+24V' and 79.4 <= pos_mm(t)[0] <= 86.6 and 72.8 <= pos_mm(t)[1] <= 79.4:
            rp.discard(board, t)        # the crossing array (earlier runs used other positions)
        elif is_via and net in ('+24V', 'LED2_OUT'):
            # drop vias of this stage that earlier runs created at the same places
            if any(same(pos_mm(t)[0], x) and same(pos_mm(t)[1], y)
                   for n, _s, pts in VIAS if n == net for x, y in pts):
                rp.discard(board, t)
    for k, (name, net, layer, outline) in enumerate(POURS):
        # overlapping outlines (same net) need distinct priorities; the input stage's zones use 10
        rp.add_zone(board, 'led-stage:' + name, net, layer, outline, solid=True).SetAssignedPriority(11 + k)
    for net, size, pts in VIAS:
        for x, y in pts:
            rp.add_via(board, net, size, x, y)
    for net, layer, width, pts in TRACKS:
        rp.add_track(board, net, layer, width, pts)
    # solid pad connections of the fused inputs and the switching parts
    for ref, number in [('F711', '1'), ('F721', '1'), ('F711', '2'), ('F721', '2'), ('L711', '1'), ('L711', '2'),
                        ('L721', '1'), ('L721', '2'), ('Q711', '5'), ('Q721', '5')]:
        for pad in board.FindFootprintByReference(ref).Pads():
            if pad.GetNumber() == number:
                pad.SetLocalZoneConnection(p.ZONE_CONNECTION_FULL)
    p.ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()


if __name__ == '__main__':
    board = rp.load_board(sys.argv[1])
    reinforce(board)
    print('unrouted', board.GetConnectivity().GetUnconnectedCount(False))
    if '--write' in sys.argv:
        p.SaveBoard(sys.argv[1], board)
        path = Path(sys.argv[1])
        path.write_text(path.read_text(encoding='utf-8'), encoding='utf-8', newline='\n')
