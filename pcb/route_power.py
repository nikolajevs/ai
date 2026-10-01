"""Scripted power routing for PCB_V1 (KiCad Python): planes, power pours, tracks, vias, ground ties.

  python route_power.py PCB_V1/PCB_V1.kicad_pcb [--write]            power stage, before the autorouter
  python route_power.py PCB_V1/PCB_V1.kicad_pcb --finish [--write]   finish stage, after route_complete.py

Routing pipeline (PCB_V1/ROUTING.md): route_power.py -> route_signals.py (Freerouting) -> route_complete.py
-> route_power.py --finish -> check_all.py.

The power stage starts from a board without copper: it deletes every track, via and script zone and
rebuilds them from the tables below, so power geometry is edited here and not by hand. It lays out
what carries real current or belongs to a switching loop: the +24 V pours on both outer layers, the
fused loads, the LED boost loops, the 12 V buck, ground copper islands around the power parts, hand
tracks and layer-change vias. Every other GND pad gets a ground tie (a stub and a via to the In1
plane, tie_ground). All of it is locked, so the router receives it as fixed wiring and copper areas.

The finish stage keeps the routing, removes the ground islands (their pads stay solid), adds the
full-board GND pours on F.Cu and B.Cu and the +3V3 fill on In2.Cu, unlocks the tracks and refills.

Coordinates are board millimetres. Rules behind the geometry: PCB_V1/ROUTING_PREP.md and ROUTING.md.
"""
import math
import sys

import pcbnew as p

MM = p.FromMM
TAG = 'auto:'           # zone-name prefix of script-generated zones
VIA = {'S': (0.65, 0.3), 'M': (0.8, 0.4)}   # diameter, drill
BOARD = [(50.0, 50.0), (150.0, 50.0), (150.0, 150.0), (50.0, 150.0)]


def R(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


# --- zones: (name, net, layer, outline) -------------------------------------------------------
# Outlines stay clear of foreign pads, so the autorouter (which reads outlines, not fills) sees
# the same copper as the zone filler produces.
PLANES = [
    ('GND plane', 'GND', 'In1.Cu', BOARD),
]
FINISH = [
    ('GND top', 'GND', 'F.Cu', BOARD),
    ('GND bottom', 'GND', 'B.Cu', BOARD),
    ('3V3 fill', '+3V3', 'In2.Cu', BOARD),
]
POURS = [
    # +24 V input: XT60 -> TVS, bulk capacitors, fuse F902, strip down to F904 (F721 continues on B.Cu)
    ('24V in F', '+24V', 'F.Cu', [
        (63.2, 51.0), (87.5, 51.0), (87.5, 87.08), (85.56, 87.08), (85.56, 83.6), (84.9, 83.6), (84.9, 73.0),
        (75.2, 73.0), (75.2, 70.7), (71.0, 70.7), (71.0, 68.0), (75.2, 68.0), (75.2, 65.0), (71.2, 65.0),
        (71.2, 61.8), (75.2, 61.8), (75.2, 57.0), (70.6, 57.0), (70.6, 61.8), (63.2, 61.8)]),
    # same node on the bottom plus the left trunk to F711 / C710 (LED channel 1)
    ('24V in B', '+24V', 'B.Cu', [
        (63.2, 51.0), (84.4, 51.0), (84.4, 72.8), (75.2, 72.8), (75.2, 59.9), (59.2, 59.9), (59.2, 107.6),
        (61.8, 107.6), (61.8, 112.2), (56.0, 112.2), (56.0, 104.3), (54.8, 104.3), (54.8, 97.7), (56.0, 97.7),
        (56.0, 56.0), (63.2, 56.0)]),
    ('24V F711', '+24V', 'F.Cu', R(55.9, 108.3, 61.7, 112.2)),
    ('24V C710', '+24V', 'F.Cu', R(54.9, 97.9, 56.15, 104.1)),
    ('24V F721', '+24V', 'F.Cu', R(102.7, 102.92, 106.53, 106.9)),

    # fused loads: F902 -> heater terminal J601 (bottom layer, top only where it crosses the 24 V trunk)
    ('LOADS F902', '+24V_LOADS', 'F.Cu', R(88.3, 56.6, 98.2, 64.2)),
    ('LOADS B', '+24V_LOADS', 'B.Cu', [
        (85.6, 55.5), (91.9, 55.5), (91.9, 77.4), (60.0, 77.4), (60.0, 73.4), (85.6, 73.4)]),
    ('LOADS J601', '+24V_LOADS', 'F.Cu', [
        (52.5, 73.3), (63.7, 73.3), (63.7, 76.8), (62.9, 76.8), (62.9, 79.2), (52.5, 79.2)]),
    ('LOADS F521', '+24V_LOADS', 'F.Cu', R(77.56, 88.9, 79.53, 93.58)),
    ('HEATER drain', 'HEATER_DRAIN', 'F.Cu', [
        (52.5, 79.8), (63.75, 79.8), (63.75, 77.22), (68.28, 77.22), (68.28, 82.78), (63.1, 82.78),
        (63.1, 88.15), (60.6, 88.15), (60.6, 82.9), (52.5, 82.9)]),

    # 12 V buck LMR16020
    ('AUX VIN', 'AUX_VIN', 'F.Cu', [
        (88.95, 77.15), (90.1, 77.15), (90.1, 79.85), (90.97, 79.85), (90.97, 83.92), (92.44, 83.92),
        (92.44, 87.08), (89.3, 87.08), (89.3, 79.85), (88.95, 79.85)]),
    ('BUCK12 SW', 'BUCK12_SW', 'F.Cu', [
        (102.15, 76.05), (104.65, 76.05), (104.65, 80.8), (109.15, 85.3), (109.15, 87.0), (106.8, 87.0),
        (106.8, 85.6), (102.8, 81.6), (102.15, 81.39), (99.67, 81.39), (99.67, 80.8), (102.15, 80.8)]),
    ('12V out', '+12V', 'F.Cu', [
        (112.85, 88.2), (123.1, 88.2), (123.1, 92.0), (120.1, 92.0), (120.1, 98.85), (118.95, 98.85),
        (118.95, 92.0), (115.2, 92.0), (115.2, 90.25), (112.85, 90.25)]),

    # 3.3 V buck TPS54202
    ('3V3 out', '+3V3', 'F.Cu', [
        (91.85, 97.75), (94.2, 97.75), (94.2, 98.78), (96.55, 98.78), (96.55, 102.72), (95.55, 102.72),
        (95.55, 101.25), (91.85, 101.25)]),

    # LED channel 1 boost
    ('LED1 VIN', 'LED1_VIN', 'F.Cu', [
        (58.42, 103.56), (61.58, 103.56), (61.58, 105.95), (65.4, 105.95), (65.4, 125.25), (63.2, 125.25),
        (63.2, 131.35), (61.95, 131.35), (61.95, 125.6), (62.25, 125.6), (62.25, 107.8), (58.42, 107.8)]),
    ('LED1 SW', 'LED1_SW', 'F.Cu', [
        (77.6, 112.75), (82.1, 112.75), (82.1, 112.54), (83.1, 112.54), (83.1, 110.35), (86.9, 110.35),
        (86.9, 112.54), (87.9, 112.54), (87.9, 118.94), (77.6, 118.94)]),
    ('LED1 SOURCE', 'LED1_SOURCE', 'F.Cu', [
        (86.68, 120.94), (87.88, 120.94), (87.88, 123.6), (88.97, 123.6), (88.97, 125.05), (85.62, 125.05),
        (85.62, 124.6), (84.12, 124.6), (84.12, 124.0), (85.62, 124.0), (85.62, 123.6), (86.68, 123.6)]),
    # quiet cathode node of D711: heat spreader on both layers (about 1 W in the diode)
    ('LED1 OUT F', 'LED1_OUT', 'F.Cu', [
        (66.2, 103.1), (80.0, 103.1), (80.0, 102.0), (93.4, 102.0), (93.4, 103.3), (95.0, 103.3), (95.0, 111.05),
        (93.75, 111.05), (93.75, 104.6), (90.1, 104.6), (90.1, 111.05), (88.95, 111.05), (88.95, 109.62),
        (82.3, 109.62), (82.3, 111.9), (66.2, 111.9)]),
    ('LED1 OUT B', 'LED1_OUT', 'B.Cu', R(66.2, 103.1, 82.3, 111.9)),

    # LED channel 2 boost
    ('LED2 VIN', 'LED2_VIN', 'F.Cu', [
        (109.47, 102.92), (111.44, 102.92), (111.44, 106.3), (111.1, 106.3), (111.1, 115.6), (105.9, 115.6),
        (105.9, 113.4), (109.47, 113.4)]),
    ('LED2 SW', 'LED2_SW', 'F.Cu', [
        (117.0, 114.5), (121.1, 114.5), (121.1, 110.54), (122.1, 110.54), (122.1, 108.35), (125.9, 108.35),
        (125.9, 110.54), (126.9, 110.54), (126.9, 116.94), (117.0, 116.94)]),
    ('LED2 SOURCE', 'LED2_SOURCE', 'F.Cu', [
        (125.68, 118.94), (126.88, 118.94), (126.88, 121.7), (127.97, 121.7), (127.97, 123.15), (124.62, 123.15),
        (124.62, 122.7), (123.12, 122.7), (123.12, 122.1), (124.62, 122.1), (124.62, 121.7), (125.68, 121.7)]),
    ('LED2 OUT F', 'LED2_OUT', 'F.Cu', [
        (117.5, 99.8), (129.1, 99.8), (129.1, 113.25), (127.95, 113.25), (127.95, 107.62), (117.5, 107.62)]),
    ('LED2 OUT B', 'LED2_OUT', 'B.Cu', R(117.5, 99.8, 129.1, 107.62)),

    # ground islands of the power parts: solid pad connection, vias to the In1 plane inside
    ('GND XT60 C902', 'GND', 'F.Cu', R(69.0, 65.95, 74.35, 67.1)),
    ('GND D901', 'GND', 'F.Cu', R(71.85, 57.6, 74.15, 61.5)),
    ('GND C901', 'GND', 'F.Cu', R(88.0, 69.75, 94.6, 72.25)),
    ('GND Q601', 'GND', 'F.Cu', [
        (69.15, 78.9), (70.35, 78.9), (70.35, 83.9), (71.6, 83.9), (71.6, 88.4), (64.7, 88.4), (64.7, 85.6),
        (68.9, 85.6), (68.9, 83.9), (69.15, 83.9)]),
    ('GND U902', 'GND', 'F.Cu', [
        (96.53, 80.55), (99.47, 80.55), (99.47, 82.06), (101.45, 82.06), (101.45, 82.67), (99.47, 82.67),
        (99.47, 85.45), (96.53, 85.45)]),
    ('GND D902', 'GND', 'F.Cu', R(108.4, 74.0, 111.9, 81.4)),
    ('GND C909', 'GND', 'F.Cu', R(125.5, 88.0, 130.5, 91.95)),
    ('GND C910', 'GND', 'F.Cu', R(121.9, 96.15, 124.6, 98.85)),
    ('GND U101', 'GND', 'F.Cu', [
        (96.9, 87.8), (98.7, 87.8), (98.7, 89.15), (98.05, 89.15), (98.05, 92.75), (98.53, 92.75),
        (98.53, 93.35), (96.47, 93.35), (96.47, 94.72), (95.58, 94.72), (95.58, 92.3), (96.9, 92.3)]),
    ('GND 3V3 out', 'GND', 'F.Cu', R(97.45, 98.78, 99.9, 102.72)),
    ('GND C710', 'GND', 'F.Cu', R(57.9, 99.65, 60.7, 102.35)),
    ('GND C715', 'GND', 'F.Cu', R(64.9, 128.65, 67.5, 131.35)),
    ('GND C716', 'GND', 'F.Cu', R(91.9, 104.85, 93.05, 113.5)),
    ('GND C718', 'GND', 'F.Cu', R(96.8, 104.85, 99.4, 111.05)),
    ('GND R715', 'GND', 'F.Cu', R(85.62, 129.75, 88.97, 132.5)),
    ('GND R716', 'GND', 'F.Cu', R(69.35, 134.32, 72.1, 137.68)),
    ('GND C725', 'GND', 'F.Cu', R(112.9, 106.9, 115.6, 109.6)),
    ('GND C726', 'GND', 'F.Cu', R(130.9, 103.55, 133.6, 113.25)),
    ('GND R725', 'GND', 'F.Cu', R(124.62, 127.85, 127.97, 130.6)),
    ('GND R726', 'GND', 'F.Cu', R(100.9, 135.0, 103.5, 137.0)),
]

# --- tracks: (net, layer, width, points) ------------------------------------------------------
TRACKS = [
    # +24 V from the F904 strip to the CH2 fuse F721, bottom layer
    ('+24V', 'B.Cu', 1.5, [(86.2, 80.6), (86.2, 96.9), (92.7, 103.4), (103.4, 103.4)]),
    ('+24V', 'B.Cu', 1.2, [(103.4, 103.4), (103.4, 106.2)]),
    # pump fuse feed
    ('+24V_LOADS', 'B.Cu', 1.5, [(81.0, 76.0), (81.0, 87.6), (79.1, 89.5), (78.0, 89.5)]),
    # LMR16020: VIN pin from the fuse pad, boot capacitor to the switch node
    # reaches pin 2 from above: the corridor left of pin 3 (EN) must stay free for the EN track
    ('AUX_VIN', 'F.Cu', 0.6, [(90.6, 80.9), (93.5, 80.9), (93.5, 82.365), (95.44, 82.365)]),
    ('BUCK12_SW', 'F.Cu', 0.3, [(97.775, 78.7), (102.4, 78.7)]),
    # GND pin 8 of the heater driver: the area above it belongs to the heater supply, so it joins C601's ground pad
    ('GND', 'F.Cu', 0.3, [(80.0, 77.1), (83.275, 77.1), (83.275, 78.2)]),
    # second bulk capacitor C906 and the EN divider sit on the far side of the fuse
    ('AUX_VIN', 'F.Cu', 0.5, [(91.45, 86.6), (91.45, 87.8), (81.275, 87.8), (81.275, 85.6)]),
    ('AUX_VIN', 'F.Cu', 0.5, [(88.18, 87.8), (88.18, 89.0)]),
    # TPS54202: input capacitors to VIN, switch node under the package to L101 and the boot capacitor
    ('+12V', 'F.Cu', 0.6, [(94.5, 91.5), (94.5, 94.25)]),
    ('+12V', 'F.Cu', 0.3, [(94.475, 94.25), (94.475, 95.15), (97.865, 95.15)]),
    ('BUCK_SW', 'F.Cu', 0.3, [(97.865, 94.0), (99.0, 94.0), (99.0, 97.0)]),
    ('BUCK_SW', 'F.Cu', 0.8, [(99.0, 97.0), (87.0, 97.0), (87.0, 98.2)]),
    ('BUCK_SW', 'F.Cu', 0.25, [(99.0, 94.0), (99.0, 90.375), (102.275, 90.375), (102.275, 91.25)]),
    # LED outputs and returns to the terminals
    ('LED1_OUT', 'B.Cu', 1.5, [(69.0, 111.0), (69.0, 131.0), (60.0, 140.0), (60.0, 144.1)]),
    ('LED1_OUT', 'F.Cu', 0.5, [(94.425, 110.5), (94.425, 112.0), (100.68, 112.0), (100.68, 113.0)]),
    ('LED1_RETURN', 'F.Cu', 1.2, [(64.04, 137.0), (64.04, 140.6), (65.08, 141.64), (65.08, 144.1)]),
    ('LED2_OUT', 'B.Cu', 1.2, [(118.5, 107.0), (118.5, 112.0), (106.0, 124.5), (106.0, 137.0), (102.5, 140.5),
                               (77.0, 140.5), (77.0, 144.1)]),
    ('LED2_OUT', 'B.Cu', 1.2, [(94.0, 140.5), (94.0, 144.1)]),
    ('LED2_OUT', 'F.Cu', 0.5, [(128.525, 112.9), (128.525, 114.6), (135.4, 114.6), (135.4, 120.5), (137.675, 120.5),
                               (137.675, 122.0)]),
    ('LED2_RETURN', 'F.Cu', 1.2, [(98.54, 136.5), (98.54, 141.0), (99.08, 141.54), (99.08, 144.1)]),
    ('LED2_RETURN', 'F.Cu', 1.2, [(82.08, 144.1), (82.08, 139.5), (98.54, 139.5)]),
]

# --- vias: (net, size, points) ----------------------------------------------------------------
VIAS = [
    # +24 V input, both layers stitched between XT60 and F902 (IPC: 0.9 A per 0.4 mm via)
    ('+24V', 'M', [(x, y) for y in (52.0, 56.0) for x in (70.6, 72.0, 73.4, 74.8, 76.2, 77.6)]
     + [(76.4, 61.2), (76.4, 64.2), (76.4, 67.2), (77.0, 70.4)]),
    ('+24V', 'M', [(57.2, 109.0), (57.2, 110.4), (58.6, 111.4), (59.9, 111.4), (61.1, 111.4)]),   # F711
    ('+24V', 'M', [(55.5, 98.6), (55.5, 103.4)]),                                               # C710
    ('+24V', 'M', [(86.2, 80.6), (86.2, 81.9), (86.2, 83.2)]),                                  # strip -> B.Cu
    ('+24V', 'M', [(103.4, 103.6), (103.4, 104.9), (103.4, 106.2)]),                            # F721
    # heater current changes to the top layer to cross the +24 V trunk
    ('+24V_LOADS', 'M', [(x, y) for x in (60.7, 61.9, 63.1) for y in (73.95, 75.15, 76.35)]),
    ('+24V_LOADS', 'M', [(78.0, 89.5), (79.1, 89.5)]),                                          # F521
    # output nodes of the LED diodes: heat to the bottom layer and the way to the terminals
    ('LED1_OUT', 'M', [(81.5, 105.8), (81.5, 107.3), (81.5, 108.8)]
     + [(x, y) for x in (69.0, 73.0, 77.0) for y in (105.0, 107.5, 110.0)]),
    ('LED2_OUT', 'M', [(119.0, 101.5), (119.0, 103.5), (119.0, 105.5), (122.0, 101.2), (124.0, 101.2),
                       (126.0, 101.2)]),
    # ground of the power parts
    ('GND', 'M', [(72.4, 60.9), (73.6, 60.9)]),                                                 # D901
    ('GND', 'M', [(93.2, 70.2), (93.2, 71.4)]),                                                 # C901
    ('GND', 'M', [(69.5, 84.75), (70.7, 84.75)] + [(x, y) for x in (68.2, 69.4, 70.6) for y in (86.4, 87.6)]),
    ('GND', 'S', [(x, y) for x in (97.3, 98.7) for y in (81.4, 83.0, 84.6)]),                   # U902 pad
    ('GND', 'M', [(109.6, 75.2), (110.8, 75.2), (109.6, 80.2), (110.8, 80.2)]),                 # D902
    ('GND', 'M', [(126.6, 89.2), (128.0, 89.2), (129.4, 89.2)]),                                # C909
    ('GND', 'M', [(124.0, 96.8), (124.0, 98.2)]),                                               # C910
    ('GND', 'S', [(97.3, 88.45), (98.25, 88.45)]),                                              # C101
    ('GND', 'M', [(99.3, 99.5), (99.3, 101.3)]),                                                # C104, C105
    ('GND', 'M', [(60.1, 101.0)]),                                                              # C710
    ('GND', 'M', [(66.9, 129.3), (66.9, 130.7)]),                                               # C715
    # (no via between C716.2 and C717.2: it would sit 0.075 mm from both pads)
    ('GND', 'M', [(92.475, 111.75), (92.475, 112.95)]),                                         # C716, C717
    ('GND', 'M', [(98.8, 105.5), (98.8, 107.95), (98.8, 110.4)]),                               # C718, C719
    ('GND', 'M', [(86.2, 131.9), (87.3, 131.9), (88.4, 131.9)]),                                # R715
    ('GND', 'M', [(71.5, 135.2), (71.5, 136.8)]),                                               # R716
    ('GND', 'M', [(115.0, 107.6), (115.0, 108.9)]),                                             # C725
    ('GND', 'M', [(133.0, 104.9), (133.0, 108.4), (133.0, 111.9)]),                             # C726-C728
    ('GND', 'M', [(125.2, 130.0), (126.3, 130.0), (127.4, 130.0)]),                             # R725
    ('GND', 'M', [(102.9, 135.4), (102.9, 136.6)]),                                             # R726
]

TIED_BY_TRACK = {('U601', '8')}       # ground pads connected by a hand-placed track in TRACKS

# pads joined solidly to every zone they touch: full input current through one XT60 pin
# (the stock SO-8FL drain pad is drawn with "no zone connection")
# C602.2 and the J401 shield tabs: DRC reports starved thermal spokes on the routed board (not enough free copper)
SOLID_PADS = [('J901', '1'), ('J901', '2'), ('Q601', '5'), ('J301', '2'), ('C602', '2'), ('J401', 'SH')]


NETS = {}


def net(board, name):
    if not NETS:    # read once: the net table proxy is not reliable after zones have been removed
        for n, info in board.GetNetsByName().items():
            NETS[str(n)] = info
    found = [info for n, info in NETS.items() if n == name or n.split('/')[-1] == name]
    if len(found) != 1:
        raise KeyError(name)
    return found[0]


def add_zone(board, name, netname, layer, outline, solid):
    z = p.ZONE(board)
    z.SetZoneName(TAG + name)
    z.SetLayer(board.GetLayerID(layer))
    z.SetNet(net(board, netname))
    z.SetAssignedPriority(10 if solid else 0)
    z.SetMinThickness(MM(0.25))
    z.SetLocalClearance(0)                      # net-class clearance applies
    z.SetPadConnection(p.ZONE_CONNECTION_FULL if solid else p.ZONE_CONNECTION_THERMAL)
    z.SetThermalReliefGap(MM(0.4))
    z.SetThermalReliefSpokeWidth(MM(0.5))
    z.SetIslandRemovalMode(p.ISLAND_REMOVAL_MODE_ALWAYS)
    poly = z.Outline()
    poly.NewOutline()
    for x, y in outline:
        poly.Append(MM(x), MM(y))
    board.Add(z)
    return z


def add_track(board, netname, layer, width, points):
    for a, b in zip(points, points[1:]):
        t = p.PCB_TRACK(board)
        t.SetStart(p.VECTOR2I(MM(a[0]), MM(a[1])))
        t.SetEnd(p.VECTOR2I(MM(b[0]), MM(b[1])))
        t.SetWidth(MM(width))
        t.SetLayer(board.GetLayerID(layer))
        t.SetNet(net(board, netname))
        t.SetLocked(True)                       # exported to the autorouter as fixed wiring
        board.Add(t)


def add_via(board, netname, size, x, y):
    dia, drill = VIA[size]
    v = p.PCB_VIA(board)
    v.SetViaType(p.VIATYPE_THROUGH)
    v.SetLayerPair(p.F_Cu, p.B_Cu)
    v.SetPosition(p.VECTOR2I(MM(x), MM(y)))
    v.SetWidth(p.F_Cu, MM(dia))
    v.SetDrill(MM(drill))
    v.SetNet(net(board, netname))
    v.SetLocked(True)
    board.Add(v)


GRAVEYARD = []      # removed items stay referenced: destroying their Python proxies breaks later pcbnew calls


def discard(board, item):
    board.Remove(item)
    GRAVEYARD.append(item)


def remove_zones(board, names=None):
    for z in list(board.Zones()):
        name = z.GetZoneName()
        if name.startswith(TAG) and (names is None or name[len(TAG):] in names):
            discard(board, z)


def inside(pt, poly):
    """Ray-casting point-in-polygon test, board mm."""
    x, y = pt
    hit = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            hit = not hit
    return hit


def edge_distance(pt, poly):
    best = 1e9
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        dx, dy = x1 - x0, y1 - y0
        s = max(0.0, min(1.0, ((pt[0] - x0) * dx + (pt[1] - y0) * dy) / (dx * dx + dy * dy)))
        best = min(best, ((pt[0] - x0 - s * dx) ** 2 + (pt[1] - y0 - s * dy) ** 2) ** 0.5)
    return best


def islands():
    """GND copper islands of the power stage: they exist only while the autorouter runs."""
    return [(name, layer, outline) for name, netname, layer, outline in POURS if netname == 'GND']


COPPER = [p.F_Cu, p.In1_Cu, p.In2_Cu, p.B_Cu]
TIE_RADII = (0.9, 1.1, 1.35, 1.65, 2.0, 2.5, 3.2)
TIE_ANGLES = (0, 180, 90, 270, 45, 225, 135, 315, 22.5, 202.5, 112.5, 292.5, 67.5, 247.5, 157.5, 337.5)
TIE_MARGIN = 0.3            # clearance of a tie to foreign copper, above the 0.2 mm default class
TIE_WIDTH = 0.3


def obstacles(board):
    """Copper of every net: [net, (x0, y0, x1, y1) in mm, {layer: shape}, clearance mm, uuid, kind]."""
    out = []

    def add(item, layers, kind):
        bb = item.GetBoundingBox()
        box = (p.ToMM(bb.GetLeft()), p.ToMM(bb.GetTop()), p.ToMM(bb.GetRight()), p.ToMM(bb.GetBottom()))
        try:
            clr = p.ToMM(item.GetEffectiveNetClass().GetClearance())
        except Exception:
            clr = 0.5
        out.append([item.GetNetname(), box, {layer: item.GetEffectiveShape(layer) for layer in layers}, max(clr, 0.2),
                    item.m_Uuid.AsString(), kind])

    for fp in board.GetFootprints():
        for pad in fp.Pads():
            add(pad, [layer for layer in COPPER if pad.IsOnLayer(layer)], 'pad')
    for t in board.GetTracks():
        add(t, COPPER if isinstance(t, p.PCB_VIA) else [t.GetLayer()], 'via' if isinstance(t, p.PCB_VIA) else 'track')
    return out


def tie_ground(board, only=None):
    """A via and a short stub for every GND pad outside the copper islands: SMD pads reach In1 locally.

    A tie via keeps clear of every other pad and via, also of its own net (no via touching a neighbouring pad);
    `only` limits the work to a set of (reference, pad number), used when a tie is redone on a finished board."""
    pours = [outline for name, netname, layer, outline in POURS if netname != 'GND']
    keepouts = []
    for fp in board.GetFootprints():
        for z in fp.Zones():
            if z.GetIsRuleArea():
                bb = z.GetBoundingBox()
                keepouts.append((p.ToMM(bb.GetLeft()), p.ToMM(bb.GetTop()), p.ToMM(bb.GetRight()), p.ToMM(bb.GetBottom())))
    edge = board.GetBoardEdgesBoundingBox()
    left, top, right, bottom = (p.ToMM(v) for v in (edge.GetLeft(), edge.GetTop(), edge.GetRight(), edge.GetBottom()))
    obst = obstacles(board)
    gnd = net(board, 'GND')
    dia, drill = VIA['S']
    placed, failed = 0, []

    def clear_of(shape, layer, box, via, own):
        x0, y0, x1, y1 = box
        for netname, (a, b, c, d), shapes, clr, uid, kind in obst:
            if uid == own or layer not in shapes:
                continue
            if netname == 'GND':
                if kind == 'track' or (kind == 'via' and not via):
                    continue
                m = 0.35 if kind == 'via' else 0.15        # same net: hole spacing / no sliver against a neighbouring pad
            else:
                m = max(clr, TIE_MARGIN)
            if c < x0 - m or a > x1 + m or d < y0 - m or b > y1 + m:
                continue
            if shape.Collide(shapes[layer], MM(m)):
                return False
        return True

    for fp in board.GetFootprints():
        if fp.IsNetTie():
            continue
        for pad in fp.Pads():
            if pad.GetNetname() != 'GND' or pad.GetAttribute() == p.PAD_ATTRIB_PTH or (fp.GetReference(), pad.GetNumber()) in TIED_BY_TRACK:
                continue
            if only is not None and (fp.GetReference(), pad.GetNumber()) not in only:
                continue
            cx, cy = p.ToMM(pad.GetPosition().x), p.ToMM(pad.GetPosition().y)
            if any(inside((cx, cy), outline) for _, layer, outline in islands() if layer == 'F.Cu'):
                continue
            pad_layer = p.B_Cu if fp.IsFlipped() else p.F_Cu
            found = None
            for r in TIE_RADII:
                for ang in TIE_ANGLES:
                    vx = cx + r * math.cos(math.radians(ang))
                    vy = cy + r * math.sin(math.radians(ang))
                    if not (left + 0.9 <= vx <= right - 0.9 and top + 0.9 <= vy <= bottom - 0.9):
                        continue
                    if any(a - 0.5 <= vx <= c + 0.5 and b - 0.5 <= vy <= d + 0.5 for a, b, c, d in keepouts):
                        continue
                    if any(inside((vx, vy), outline) or edge_distance((vx, vy), outline) < 0.6 for outline in pours):
                        continue
                    v = p.PCB_VIA(board)
                    v.SetViaType(p.VIATYPE_THROUGH)
                    v.SetLayerPair(p.F_Cu, p.B_Cu)
                    v.SetPosition(p.VECTOR2I(MM(vx), MM(vy)))
                    v.SetWidth(p.F_Cu, MM(dia))
                    v.SetDrill(MM(drill))
                    v.SetNet(gnd)
                    box = (vx - dia / 2, vy - dia / 2, vx + dia / 2, vy + dia / 2)
                    if v.GetEffectiveShape(pad_layer).Collide(pad.GetEffectiveShape(pad_layer), MM(0.15)):
                        continue            # never a via in or against the pad being tied (hand soldering)
                    own = pad.m_Uuid.AsString()
                    if not all(clear_of(v.GetEffectiveShape(layer), layer, box, True, own) for layer in (p.F_Cu, p.In2_Cu, p.B_Cu)):
                        continue
                    stub = p.PCB_TRACK(board)
                    stub.SetStart(pad.GetPosition())
                    stub.SetEnd(p.VECTOR2I(MM(vx), MM(vy)))
                    stub.SetWidth(MM(TIE_WIDTH))
                    stub.SetLayer(pad_layer)
                    sbox = (min(cx, vx) - TIE_WIDTH, min(cy, vy) - TIE_WIDTH, max(cx, vx) + TIE_WIDTH, max(cy, vy) + TIE_WIDTH)
                    if not clear_of(stub.GetEffectiveShape(), pad_layer, sbox, False, own):
                        continue
                    found = (v, stub)
                    break
                if found:
                    break
            if not found:
                failed.append(f'{fp.GetReference()}.{pad.GetNumber()}')
                continue
            for item, layers in ((found[0], COPPER), (found[1], [pad_layer])):
                item.SetNet(gnd)
                item.SetLocked(True)
                board.Add(item)
                bb = item.GetBoundingBox()
                obst.append(['GND', (p.ToMM(bb.GetLeft()), p.ToMM(bb.GetTop()), p.ToMM(bb.GetRight()), p.ToMM(bb.GetBottom())),
                             {layer: item.GetEffectiveShape(layer) for layer in layers}, 0.2, item.m_Uuid.AsString(),
                             'via' if isinstance(item, p.PCB_VIA) else 'track'])
            placed += 1
    print(f'GND ties: {placed} vias with stubs; no room for {failed if failed else "none"}')
    return failed


def apply_solid(board):
    for ref, number in SOLID_PADS:
        for pad in board.FindFootprintByReference(ref).Pads():
            if pad.GetNumber() == number:
                pad.SetLocalZoneConnection(p.ZONE_CONNECTION_FULL)


def power_stage(board):
    for t in list(board.GetTracks()):
        discard(board, t)
    remove_zones(board)
    for name, netname, layer, outline in PLANES:
        add_zone(board, name, netname, layer, outline, solid=False)
    for name, netname, layer, outline in POURS:
        add_zone(board, name, netname, layer, outline, solid=True)
    for netname, layer, width, points in TRACKS:
        add_track(board, netname, layer, width, points)
    for netname, size, points in VIAS:
        for x, y in points:
            add_via(board, netname, size, x, y)
    apply_solid(board)
    tie_ground(board)


def finish_stage(board):
    """After autorouting the GND islands give way to the full-board pours; their pads stay solid."""
    for name, layer, outline in islands():
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                if pad.GetNetname() == 'GND' and inside((p.ToMM(pad.GetPosition().x), p.ToMM(pad.GetPosition().y)), outline):
                    pad.SetLocalZoneConnection(p.ZONE_CONNECTION_FULL)
    apply_solid(board)
    for t in board.GetTracks():
        t.SetLocked(False)          # locked only to hand the power stage to the router as fixed wiring
    remove_zones(board, {name for name, *_ in FINISH} | {name for name, _, _ in islands()})
    for name, netname, layer, outline in FINISH:
        add_zone(board, name, netname, layer, outline, solid=False)


def main():
    path = sys.argv[1]
    board = p.LoadBoard(path)
    net(board, 'GND')
    if '--finish' in sys.argv:
        finish_stage(board)
    else:
        power_stage(board)
    p.ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()
    vias = sum(1 for t in board.GetTracks() if isinstance(t, p.PCB_VIA))
    print('zones', len(list(board.Zones())), 'tracks', len(board.GetTracks()) - vias, 'vias', vias,
          'unrouted', board.GetConnectivity().GetUnconnectedCount(False))
    if '--write' in sys.argv:
        p.SaveBoard(path, board)
        text = open(path, encoding='utf-8').read().replace('\r\n', '\n')
        open(path, 'w', encoding='utf-8', newline='\n').write(text)
        print('saved')


if __name__ == '__main__':
    main()
