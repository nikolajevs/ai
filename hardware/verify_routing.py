"""Check the routing rules of PCB_V1 (KiCad Python): python verify_routing.py PCB_V1/PCB_V1.kicad_pcb

DRC remains responsible for clearances, widths against net classes and connectivity. These checks
cover what DRC cannot see: the layer strategy and the copper that the power paths depend on.
Rules: PCB_V1/ROUTING_PREP.md (section 4) and PCB_V1/ROUTING.md.
"""
import sys
from collections import Counter
from pathlib import Path

import pcbnew as p

board = p.LoadBoard(str(Path(sys.argv[1])))
mm = p.ToMM
short = lambda name: name.split('/')[-1]
tracks = [t for t in board.GetTracks() if not isinstance(t, p.PCB_VIA)]
vias = [t for t in board.GetTracks() if isinstance(t, p.PCB_VIA)]
zones = [z for z in board.Zones() if not z.GetIsRuleArea()]
assert tracks and vias and zones, 'the board is not routed'

# 1. Inner layers: In1 is the solid GND plane, In2 carries signals and the +3V3 fill, never power loops.
by_layer = Counter(board.GetLayerName(t.GetLayer()) for t in tracks)
assert not by_layer['In1.Cu'], ('copper tracks on the GND plane In1.Cu', by_layer['In1.Cu'])
plane = [z for z in zones if z.IsOnLayer(p.In1_Cu)]
assert len(plane) == 1 and plane[0].GetNetname() == 'GND' and plane[0].IsFilled(), 'In1.Cu must be one filled GND zone'
power_inner = {'+24V', '+24V_LOADS', 'HEATER_DRAIN', 'AUX_VIN', 'PUMP_24V', 'PUMP_DRAIN', 'BUCK12_SW', 'BUCK_SW',
               'LED1_VIN', 'LED2_VIN', 'LED1_SW', 'LED2_SW', 'LED1_OUT', 'LED2_OUT', 'LED1_SOURCE', 'LED2_SOURCE',
               'LED1_RETURN', 'LED2_RETURN'}
inner = {short(t.GetNetname()) for t in tracks if t.GetLayer() == p.In2_Cu} & power_inner
assert not inner, ('power nets routed on In2.Cu', sorted(inner))
for z in zones:
    if z.IsOnLayer(p.In2_Cu):
        assert short(z.GetNetname()) in ('+3V3', ''), ('In2.Cu fill must be +3V3', z.GetNetname())
print(f'PASS: In1.Cu is a single filled GND plane without tracks; In2.Cu carries no power-loop nets '
      f'(tracks F {by_layer["F.Cu"]}, In2 {by_layer["In2.Cu"]}, B {by_layer["B.Cu"]}, vias {len(vias)})')

# 2. No vias on switching nodes (radiation). Sense lines stay thin and change layer at most twice.
switching = {'BUCK12_SW', 'BUCK_SW', 'LED1_SW', 'LED2_SW'}
bad = sorted({short(v.GetNetname()) for v in vias} & switching)
assert not bad, ('vias on switching nodes', bad)
sense = ('LED1_CS_K', 'LED1_FB_K', 'LED2_CS_K', 'LED2_FB_K')
for name in sense:
    wide = [mm(t.GetWidth()) for t in tracks if short(t.GetNetname()) == name and mm(t.GetWidth()) > 0.3]
    assert not wide, (name, 'sense line wider than 0.3 mm', wide)
    n = sum(1 for v in vias if short(v.GetNetname()) == name)
    assert n <= 2, (name, 'sense line with more than two vias', n)
# The 32.768 kHz crystal: short, one layer, no vias.
for name in ('RTC_OSCI', 'RTC_OSCO'):
    mine = [t for t in tracks if short(t.GetNetname()) == name]
    length = sum(mm(t.GetLength()) for t in mine)
    assert length <= 12.0, (name, 'crystal track longer than 12 mm', round(length, 1))
    assert all(t.GetLayer() == p.F_Cu for t in mine), (name, 'crystal track off F.Cu')
    assert not any(short(v.GetNetname()) == name for v in vias), (name, 'via in the crystal net')
print('PASS: no vias on BUCK12_SW, BUCK_SW, LED1_SW, LED2_SW; Kelvin sense lines thin with at most two vias each; '
      'RTC crystal nets short on F.Cu without vias')


# 3. Layer-change counts for the main current paths (IPC-2221 figures in ROUTING_PREP.md section 3).
def count(net, min_drill):
    return sum(1 for v in vias if short(v.GetNetname()) == net and mm(v.GetDrill()) >= min_drill - 1e-6)


main24 = count('+24V', 0.4)
loads = count('+24V_LOADS', 0.4)
assert main24 >= 14, ('main +24 V path needs at least 14 vias of 0.4 mm', main24)
assert loads >= 8, ('fused heater supply needs at least 8 vias of 0.4 mm', loads)
print(f'PASS: +24V has {main24} vias of at least 0.4 mm (limit 14), +24V_LOADS {loads} (limit 8)')

# 4. Copper area of the power nets, from the filled zones, per outer layer.
area = Counter()
for z in zones:
    if not (z.IsOnLayer(p.F_Cu) or z.IsOnLayer(p.B_Cu)):
        continue
    layer = 'F' if z.IsOnLayer(p.F_Cu) else 'B'
    area[(short(z.GetNetname()), layer)] += mm(mm(z.GetFilledArea()))
for net, floor in (('+24V', 120.0), ('+24V_LOADS', 60.0)):
    total = sum(v for (n, _), v in area.items() if n == net)
    assert total >= floor, (net, 'copper area below', floor, round(total, 1))
print('PASS: copper areas ' + ', '.join(f'{n} {sum(v for (m, _), v in area.items() if m == n):.0f} mm2'
                                          for n in ('+24V', '+24V_LOADS', 'HEATER_DRAIN', 'LED1_OUT', 'LED2_OUT')))
