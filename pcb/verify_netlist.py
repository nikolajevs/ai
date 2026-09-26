"""Check critical schematic connectivity, not analog performance.

Usage:
  kicad-cli sch export netlist --format kicadxml -o netlist.xml PCB_V1/PCB_V1.kicad_sch
  python verify_netlist.py netlist.xml
"""
import sys
import xml.etree.ElementTree as ET

root = ET.parse(sys.argv[1])
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
    [('U201', 33), ('U301', 15), ('R301', 2), ('R303', 1)],
    [('U201', 36), ('U301', 16), ('R302', 2), ('R304', 1)],
    [('U301', 14), ('BT301', 1)],
    [('U301', 2), ('C301', 1), ('U201', 2)],
    [('U301', 13), ('BT301', 2)] + [('U301', pin) for pin in range(5, 13)],
    [('J301', 1), ('F301', 2), ('C302', 1)],
    [('J301', 2), ('J302', 2), ('U201', 1)],
    [('J301', 3), ('R303', 2), ('D301', 1)],
    [('J301', 4), ('R304', 2), ('D301', 2)],
    [('U201', 9), ('R305', 1), ('R306', 2), ('C303', 1)],
    [('J302', 1), ('R305', 2), ('D302', 1)],
    [('U201', 30), ('R401', 1)], [('R401', 2), ('J401', 5), ('D401', 1)],
    [('U201', 37), ('R402', 1)], [('R402', 2), ('J401', 3), ('D401', 2), ('R410', 2)],
    [('U201', 16), ('R403', 1)], [('R403', 2), ('J401', 2), ('D402', 1), ('R408', 2)],
    [('U201', 31), ('R404', 1)], [('R404', 2), ('J401', 7), ('D402', 2), ('R405', 2)],
    [('J401', 8), ('R406', 2), ('D403', 1)],
    [('J401', 1), ('R407', 2), ('D403', 2)],
    [('J401', 4), ('R409', 2), ('C401', 1), ('C402', 1)] + [(r, 1) for r in ['R405', 'R406', 'R407', 'R408', 'R410']],
    [('J401', 6), ('J401', 'SH'), ('U201', 1)] + [(r, 3) for r in ['D301', 'D302', 'D401', 'D402', 'D403']],
]
for group in groups:
    name, actual = net_of(*group[0])
    expected = {(ref, str(pin)) for ref, pin in group}
    assert expected <= actual, (name, expected - actual)

# Battery must never share a power net with the 3.3 V rail or peripheral supply.
assert net_of('BT301', 1)[1] == {('BT301', '1'), ('U301', '14')}
assert net_of('J201', 2)[0] != net_of('U201', 2)[0]
assert net_of('U101', 2)[0] != net_of('U201', 2)[0]

gpio = {'6':'FAN1_TACH', '7':'FAN2_TACH', '8':'LIGHT_PWM', '9':'WATER_LEVEL',
        '10':'FAN1_PWM', '11':'FAN2_PWM', '12':'PUMP_EN', '13':'HEATER_EN',
        '16':'SD_CS', '27':'LIGHT_ENABLE', '30':'SD_SCK', '31':'SD_MISO',
        '33':'I2C_SDA', '36':'I2C_SCL', '37':'SD_MOSI'}
for pin, name in gpio.items():
    assert net_of('U201', pin)[0].split('/')[-1] == name, (pin, name)

assert len(root.findall('.//components/comp')) == 64
print(f'PASS: {len(groups)} connectivity groups, 15 GPIO mappings, battery isolation, UART reference separation, 64 components.')
