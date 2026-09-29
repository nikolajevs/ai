"""Check critical schematic connectivity, not analog performance.

Usage:
  kicad-cli sch export netlist --format kicadxml -o netlist.xml PCB_V1/PCB_V1.kicad_sch
  python verify_netlist.py netlist.xml
"""
import sys
import xml.etree.ElementTree as ET

root = ET.parse(sys.argv[1])
refs = [c.get('ref') for c in root.findall('.//components/comp')]
assert len(refs) == len(set(refs)), 'Duplicate component references: PCB import is unsafe'
assert all(ref and '?' not in ref for ref in refs), 'Unannotated components'
nets = {n.get('name'): {(p.get('ref'), p.get('pin')) for p in n}
        for n in root.findall('.//nets/net')}

def net_of(ref, pin):
    matches = [(name, pins) for name, pins in nets.items() if (ref, str(pin)) in pins]
    assert len(matches) == 1, (ref, pin, matches)
    return matches[0]

groups = [
    [('U101', 3), ('C101', 1), ('C102', 1), ('TP101', 1)],
    [('U101', 6), ('C103', 1)],
    [('U101', 2), ('C103', 2), ('L101', 1)],
    [('L101', 2), ('C104', 1), ('C105', 1), ('R101', 1), ('U201', 2)],
    [('U101', 4), ('R101', 2), ('R102', 1), ('C106', 2)],
    [('U101', 1), ('U201', 1), ('U201', 15), ('U201', 38), ('U201', 39), ('J201', 1)],
    [('U201', 3), ('R201', 2), ('C203', 1), ('SW201', 1), ('J201', 5)],
    [('U201', 25), ('R202', 2), ('SW202', 1), ('J201', 6)],
    [('U201', 14), ('R203', 1)],
    [('U201', 35), ('R205', 1)], [('R205', 2), ('J201', 3)],
    [('U201', 34), ('R206', 2)], [('R206', 1), ('J201', 4)],
    [('R204', 2), ('J201', 2)], [('R204', 1), ('U201', 2)],
    [('U201', 33), ('U301', 7), ('R301', 2), ('R303', 1)],
    [('U201', 36), ('U301', 8), ('R302', 2), ('R304', 1)],
    [('U301', 6), ('BT301', 1)],
    [('U301', 2), ('C301', 1), ('U201', 2)],
    [('U301', 5), ('BT301', 2)],
    [('J301', 1), ('F301', 2), ('C302', 1)],
    [('J301', 2), ('J302', 2), ('U201', 1)],
    [('J301', 3), ('R303', 2), ('D301', 1)],
    [('J301', 4), ('R304', 2), ('D301', 2)],
    [('U201', 9), ('R305', 1), ('R306', 2), ('C303', 1)],
    [('J302', 1), ('R305', 2), ('D302', 1)],
    [('U201', 30), ('R401', 1)], [('R401', 2), ('J401', 5)],
    [('U201', 37), ('R402', 1)], [('R402', 2), ('J401', 3), ('R410', 2)],
    [('U201', 16), ('R403', 1)], [('R403', 2), ('J401', 2), ('R408', 2)],
    [('U201', 31), ('R404', 1)], [('R404', 2), ('J401', 7), ('R405', 2)],
    [('J401', 8), ('R406', 2)],
    [('J401', 1), ('R407', 2)],
    [('J401', 4), ('U201', 2), ('C401', 1), ('C402', 1)] + [(r, 1) for r in ['R405', 'R406', 'R407', 'R408', 'R410']],
    [('J401', 6), ('J401', 'SH'), ('U201', 1), ('D301', 3), ('D302', 3)],
]
# Output polarity, gate drive and connector pinout.
groups += [
    [('U201', 12), ('R209', 1), ('R521', 1)],
    [('R521', 2), ('R522', 1), ('Q521', 1)],
    [('Q521', 3), ('J521', 2), ('D521', 2)],
    [('F902', 2), ('F521', 1), ('J601', 1), ('TP902', 1)],
    [('F521', 2), ('J521', 1), ('D521', 1), ('C521', 1)],
    [('U201', 13), ('R210', 1), ('U601', 2)],
    [('U601', 7), ('R601', 1)],
    [('R601', 2), ('R602', 1), ('Q601', 4)],
    [('Q601', 5), ('J601', 2), ('D601', 1)],
    [('U201', 2), ('U601', 1)],
    [('U201', 1), ('Q601', 1), ('Q601', 2), ('Q601', 3), ('R602', 2),
     ('D601', 2), ('U601', 3), ('U601', 4), ('U601', 8), ('Q521', 2)],
    # UCC27524A VDD comes from the regulated 12 V aux rail, never from the 24 V input.
    [('L902', 2), ('U601', 6), ('C601', 1), ('C602', 1)],
    [('C601', 2), ('C602', 2), ('U201', 1)],
]
for suffix, pwm_pin, tach_pin, pull in [(501, 10, 6, 'R207'), (511, 11, 7, 'R208')]:
    j,q,r,d = f'J{suffix}', f'Q{suffix}', f'R{suffix}', f'D{suffix}'
    groups += [
        [('U201', pwm_pin), (r, 1)],
        [(r, 2), (q, 1), (f'R{suffix+1}', 1)],
        [(q, 3), (j, 4), (d, 1)],
        [('U201', tach_pin), (pull, 2), (f'R{suffix+2}', 1)],
        [(f'R{suffix+2}', 2), (j, 3), (d, 2)],
        [('U201', 1), (q, 2), (j, 1), (d, 3)],
        [('L902', 2), (f'F{suffix}', 1)],
        [(f'F{suffix}', 2), (j, 2)],
    ]

# 24 V input, branch fuses and 12 V auxiliary buck (LMR16020).
groups += [
    [('J901', 2), ('D901', 1), ('C901', 1), ('C902', 1), ('F902', 1), ('F904', 1), ('TP901', 1),
     ('F711', 1), ('F721', 1), ('C710', 1)],
    [('F904', 2), ('U902', 2), ('C905', 1), ('C906', 1), ('C907', 1), ('R907', 1)],
    [('J901', 1), ('D901', 2), ('C901', 2), ('C902', 2), ('C905', 2), ('C906', 2), ('C907', 2),
     ('R908', 2), ('R906', 2), ('R905', 2), ('D902', 2), ('C909', 2), ('C910', 2),
     ('U902', 7), ('U902', 9), ('U201', 1)],
    [('U902', 1), ('C908', 1)],
    [('U902', 8), ('C908', 2), ('D902', 1), ('L902', 1)],
    [('U902', 3), ('R907', 2), ('R908', 1)],
    [('U902', 4), ('R906', 1)],
    [('U902', 5), ('R904', 2), ('R905', 1)],
    [('L902', 2), ('R904', 1), ('C909', 1), ('C910', 1), ('U101', 3), ('C101', 1), ('C102', 1), ('TP101', 1),
     ('U710', 1), ('U720', 1), ('C711', 1), ('C721', 1)],
]

# AL8853 low-side LED current sensing. CH1 = panel; CH2 = two identical bars (J721 || J731).
groups += [
    [('U700', 1), ('U201', 8), ('R211', 1)],
    [('U700', 2), ('U201', 27), ('R212', 1)],
    [('U700', 4), ('R703', 1), ('U710', 8), ('U720', 8)],
    [('U700', 5), ('C700', 1), ('U201', 2)],
    [('U700', 3), ('C700', 2), ('R211', 2), ('R212', 2), ('R703', 2), ('U201', 1)],
]
returns = []
for idx in (1, 2):
    r = lambda kind, n: f'{kind}7{idx}{n}'
    u, q, l, d, j = (r(k, n) for k, n in [('U',0),('Q',1),('L',1),('D',1),('J',1)])
    # PowerPAK and the NexFET footprints aggregate drain contacts as pad 5.
    gate, drain, sources = 4, 5, [1, 2, 3]
    # STPS5H100B DPAK: NC1, cathode/tab2, anode3. SOD128: K1/A2.
    cathode, anode = (2, 3) if idx == 1 else (1, 2)
    bars = [j] + (['J731'] if idx == 2 else [])
    out_caps = [r('C',6), r('C',7)] + (['C718', 'C719'] if idx == 1 else ['C728'])
    groups += [
        [(u, 1), (r('C',1), 1), ('L902', 2)],
        [(r('F',1), 2), (r('C',5), 1), (l, 1)],
        [(u, 2), (r('R',1), 1)],
        [(r('R',1), 2), (q, gate), (r('R',3), 1)],
        [(q, drain), (l, 2), (d, anode)],
        [(q, pin) for pin in sources] + [(r('R',5), 1), (r('R',2), 1), (r('R',3), 2)],
        [(u, 4), (r('R',2), 2), (r('C',3), 1)],
        [(d, cathode), (r('R',7), 1)] + [(b, 1) for b in bars] + [(c, 1) for c in out_caps],
        [(u, 7), (r('R',7), 2), (r('R',8), 1)],
        [(u, 5), (r('R',6), 1)] + [(b, 2) for b in bars],
        [(u, 3), (r('R',5), 2), (r('R',6), 2), (r('R',8), 2), (r('C',1), 2),
         (r('C',2), 2), (r('C',3), 2), (r('C',4), 2), (r('C',5), 2), ('U201', 1)] + [(c, 2) for c in out_caps],
        [(u, 6), (r('R',4), 1), (r('C',2), 1)],
        [(r('R',4), 2), (r('C',4), 1)],
    ]
    name, nodes = net_of(j, 2)
    assert nodes == {(b, '2') for b in bars} | {(u, '5'), (r('R',6), '1')}, (j, 'LED return bypassed')
    returns.append(name)
assert len(set(returns + [net_of('U201',1)[0]])) == 3, 'LED returns shorted together or to ground'
groups += [[('U201', 1), ('C710', 2)]]
assert net_of('D711', 1)[1] == {('D711', '1')}, 'DPAK NC lead connected'

for group in groups:
    name, actual = net_of(*group[0])
    expected = {(ref, str(pin)) for ref, pin in group}
    assert expected <= actual, (name, expected - actual)

# Battery must never share a power net with the 3.3 V rail or peripheral supply.
assert net_of('BT301', 1)[1] == {('BT301', '1'), ('U301', '6')}
assert net_of('J201', 2)[0] != net_of('U201', 2)[0]
assert net_of('U101', 2)[0] != net_of('U201', 2)[0]

gpio = {'6':'FAN1_TACH', '7':'FAN2_TACH', '8':'LIGHT_PWM', '9':'WATER_LEVEL',
        '10':'FAN1_PWM', '11':'FAN2_PWM', '12':'PUMP_EN', '13':'HEATER_EN',
        '16':'SD_CS', '27':'LIGHT_ENABLE', '30':'SD_SCK', '31':'SD_MISO',
        '33':'I2C_SDA', '36':'I2C_SCL', '37':'SD_MOSI'}
for pin, name in gpio.items():
    assert net_of('U201', pin)[0].split('/')[-1] == name, (pin, name)

assert len(root.findall('.//components/comp')) == 161

# Supply-domain mistakes can pass ordinary ERC. Check the non-interchangeable nets.
v24, v24_loads, v12, v33, gnd = (net_of('J901', 2)[0], net_of('F902', 2)[0], net_of('L902', 2)[0],
                                 net_of('U201', 2)[0], net_of('U201', 1)[0])
assert len({v24, v24_loads, net_of('F904', 2)[0], v12, v33, gnd}) == 6, 'supply rails merged'
assert net_of('J901', 1)[0] == gnd, 'XT60 pin 1 must be GND (KiCad AMASS footprint "-")'
assert net_of('U601', 6)[0] == v12, 'UCC27524A VDD must be the 12 V aux rail (18 V max)'
assert net_of('U101', 3)[0] == v12, 'TPS54202 (28 V max) must be fed from the 12 V aux rail'
assert net_of('F501', 1)[0] == net_of('F511', 1)[0] == v12, 'PC fans must be fused from 12 V'
assert net_of('U710', 1)[0] == net_of('U720', 1)[0] == v12, 'AL8853 bias must be isolated from 24 V transients'
assert net_of('U902', 6)[1] == {('U902', '6')}, 'LMR16020 PGOOD is unused'
obsolete = {'U901', 'Q901', 'F901', 'R903', 'C903', 'C904', 'U602', 'C603', 'C604', 'U730', 'Q731', 'L731', 'D731',
            'F903', 'TP903', 'D401', 'D402', 'D403', 'R409', 'R701', 'R702'}
assert not obsolete & set(refs), ('obsolete parts remain', obsolete & set(refs))
for ref, mpn in [('U902', 'LMR16020PDDAR'), ('D901', 'SMBJ26CA-E3/52'), ('D601', 'SMBJ26CA-E3/52'),
                 ('Q711', 'CSD19534Q5A'), ('Q721', 'CSD19538Q3A'), ('Q521', 'AO3422'), ('D521', 'SS36-E3/57T')]:
    comp = next(c for c in root.findall('.//components/comp') if c.get('ref') == ref)
    assert comp.findtext('value') == mpn, (ref, 'unqualified substitute')

for drain in [('Q601', 5), ('Q521', 3)]:
    assert net_of(*drain)[0] not in (gnd, v24, v24_loads, v12)
fused_nodes = {
 'F501': {('F501','2'),('J501','2')},
 'F511': {('F511','2'),('J511','2')},
 'F521': {('F521','2'),('J521','1'),('D521','1'),('C521','1')},
 'F711': {('F711','2'),('L711','1'),('C715','1')},
 'F721': {('F721','2'),('L721','1'),('C725','1')},
 'F904': {('F904','2'),('U902','2'),('C905','1'),('C906','1'),('C907','1'),('R907','1')},
}
for ref, expected in fused_nodes.items():
 assert net_of(ref,2)[1] == expected, (ref,'fuse bypass or unintended branch load')
 assert net_of(ref,1)[0] != net_of(ref,2)[0], (ref,'fuse shorted')
assert len({net_of(ref,2)[0] for ref in fused_nodes}) == 6, 'branch outputs merged'
comps = {c.get('ref'):c for c in root.findall('.//components/comp')}
for ref, value in {'R726':'0.43 1% >=0.25W','R715':'0.027 1% >=1W','L711':'47u SRP1770TA-470M',
                  'R904':'150k 0.1%','R905':'10k 0.1%'}.items():
 assert comps[ref].findtext('value') == value, (ref,'wrong design value')
for ref in ['R211','R212','R405','R406','R407','R408','R410']:
 assert comps[ref].findtext('value') in ('10k','10k 1%'), (ref,'required startup/SD pull resistor')
assert comps['C909'].findtext('value')=='100u 25V polymer'
assert net_of('C909',1)[0]==v12 and net_of('C909',2)[0]==gnd, 'C909 polymer polarity'
print(f'PASS: {len(groups)} connectivity groups, 15 GPIO mappings, battery/LED-return/NC isolation, UART reference separation, {len(refs)} components.')
print('PASS: 24 V input polarity, separate power/bias domains, LMR16020 wiring, CH2 parallel bars, six unbypassed branch fuses')
