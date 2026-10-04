"""v0.22 copper screen before routing: conductor widths, layer-change vias and drops.

Usage: python analyze_copper.py netlist.xml [--output report.txt]
Currents come from analyze_power_path.py / analyze_led_power.py for the same netlist; copper
thicknesses from the PCB_V1.kicad_pcb stackup; routing widths from the PCB_V1.kicad_pro net classes.
IPC-2221 conductor chart (I = k * dT^0.44 * A^0.725, A in mil^2; k 0.048 outer, 0.024 inner) for
isolated conductors, still air, no neighbouring heat sources. This is a sizing screen for the layout,
NOT a thermal simulation or an IPC-2152 qualification; polygons and parallel layers are credited
only where the report says so.
"""
import argparse
import itertools
import json
import math
import re
from pathlib import Path

from analyze_led_power import CHANNELS, VIN_CASES, estimate
from analyze_power_path import report as power_path_report

HERE = Path(__file__).resolve().parent
BOARD = HERE / 'PCB_V1' / 'PCB_V1.kicad_pcb'
PROJECT = HERE / 'PCB_V1' / 'PCB_V1.kicad_pro'
MIL = 0.0254                 # mm
RHO_CU = 1.724e-5            # ohm*mm at 20 C (annealed copper)
ALPHA_CU = 0.00393
VIA_DRILL = (0.3, 0.4)       # project via presets, mm
VIA_PLATING = 0.018          # mm; assumed finished barrel copper, confirm with the fab option


def ipc2221_width(current, rise, thickness, k):
    """Minimum conductor width in mm for current [A], temperature rise [C] and copper thickness [mm]."""
    area_mil2 = (current / (k * rise ** 0.44)) ** (1 / 0.725)
    return area_mil2 / (thickness / MIL) * MIL


def ipc2221_current(area_mm2, rise, k):
    return k * rise ** 0.44 * (area_mm2 / MIL ** 2) ** 0.725


def stackup():
    text = BOARD.read_text(encoding='utf-8')
    layers = re.findall(r'\(layer "([^"]+)"\s*\(type "copper"\)\s*\(thickness ([\d.]+)\)', text)
    assert [name for name, _ in layers] == ['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu'], layers
    total = float(re.search(r'\(general\s*\(thickness ([\d.]+)\)', text).group(1))
    return {name: float(t) for name, t in layers}, total


def netclasses():
    data = json.loads(PROJECT.read_text(encoding='utf-8'))['net_settings']
    return {c['name']: c for c in data['classes']}


def currents(netlist):
    text = power_path_report(netlist)
    num = lambda pattern: float(re.search(pattern, text).group(1))
    fuses = {m.group(1): float(m.group(2)) for m in re.finditer(r'^(F\d+)\s+[\d.]+\s+([\d.]+)', text, re.M)}
    cases = [[estimate(ch, *p) for p in itertools.product(VIN_CASES, (40, 44, 48), (110e3, 130e3), (.85, .90), (False, True))]
             for ch in CHANNELS]
    hi = lambda n, key: max(c[key] for c in cases[n])
    rows = [
        # (path, net class, RMS/continuous current, basis)
        ('XT60 +24V to TVS/bulk and fuse inputs', 'MAIN24', num(r'conservative RMS sum ([\d.]+) A'), 'whole-board RMS sum'),
        ('GND return XT60 pin 1 to the loads', 'GND', num(r'conservative RMS sum ([\d.]+) A'), 'same current, planes/pours'),
        ('F902 -> +24V_LOADS -> PTC J601 / pump F521', 'HEATER24', fuses['F902'], 'F902 load bound'),
        ('PTC return J601 -> Q601 drain/source -> GND', 'HEATER24', fuses['F902'] - fuses['F521'], 'F902 load minus pump'),
        ('F711 -> L711 (CH1 input)', 'LED_INPUT', fuses['F711'], 'F711 load bound = CH1 inductor RMS'),
        ('CH1 switch node L711/Q711/D711', 'SWITCH', hi(0, 'il_rms'), 'CH1 inductor RMS'),
        ('CH1 source/shunt Q711 -> R715 -> GND', 'SWITCH', hi(0, 'iq_rms'), 'CH1 switch RMS'),
        ('CH1 LED output and return (J711, R716)', 'LED48', hi(0, 'io'), 'CH1 LED current, FB/R corner'),
        ('F721 -> L721 (CH2 input)', 'LED_INPUT', fuses['F721'], 'F721 load bound = CH2 inductor RMS'),
        ('CH2 switch node L721/Q721/D721', 'SWITCH', hi(1, 'il_rms'), 'CH2 inductor RMS'),
        ('CH2 LED output and return (J721/J731, R726)', 'LED48', hi(1, 'io'), 'CH2 LED current'),
        ('F904 -> AUX_VIN (LMR16020 input)', 'AUX24', fuses['F904'], 'F904 input RMS screen'),
        ('Pump F521 -> J521, Q521 drain', 'AUX24', fuses['F521'], 'pump allowance'),
        ('+12V aux rail', 'PWR12', num(r'Aux ceiling ([\d.]+) A'), 'aux ceiling'),
        ('+12V fan branches F501/F511', 'PWR12', fuses['F501'], 'per fan'),
        ('+3V3 logic rail', 'PWR3V3', 1.0, '3.3 V buck budget'),
    ]
    return rows, num(r'conservative RMS sum ([\d.]+) A')


def report(netlist):
    copper, total = stackup()
    classes = netclasses()
    rows, main = currents(netlist)
    outer, inner = copper['F.Cu'], copper['In1.Cu']
    assert outer == copper['B.Cu'] and inner == copper['In2.Cu']
    out = ['GrowBox v0.22 copper screen before routing',
           f'Stack (board file): {total:.4f} mm; outer F.Cu/B.Cu {outer * 1000:.1f} um (1 oz), '
           f'inner In1/In2 {inner * 1000:.1f} um (0.5 oz finished).',
           'IPC-2221 chart, isolated conductor, still air; k 0.048 outer, 0.024 inner. Screen only, not IPC-2152/thermal simulation.',
           '', 'Minimum width on ONE outer layer, mm (dT above local board temperature):',
           f'{"path":46} {"class":9} {"I, A":>6} {"dT10":>6} {"dT20":>6} {"class":>6}  status']
    for path, cls, current, basis in rows:
        w10 = ipc2221_width(current, 10, outer, .048)
        w20 = ipc2221_width(current, 20, outer, .048)
        width = classes[cls]['track_width'] if cls in classes else None
        if width is None:
            status = 'plane/pour only'
        elif width >= w10:
            status = 'class width OK at dT10'
        elif width >= w20:
            status = 'class width OK only at dT20: widen or pour'
        else:
            status = 'class width too narrow: pour on both outer layers'
        width_txt = f'{width:6.2f}' if width is not None else '     -'
        out.append(f'{path:46} {cls:9} {current:6.3f} {w10:6.2f} {w20:6.2f} {width_txt}  {status}')
        out.append(f'{"":46} basis: {basis}')
    two = ipc2221_width(main / 2, 10, outer, .048)
    one_inner = ipc2221_width(main, 10, inner, .024)
    out += ['', f'Main 24 V path {main:.3f} A: {ipc2221_width(main, 10, outer, .048):.1f} mm on one outer layer (dT10); '
                f'{two:.1f} mm on EACH outer layer when F.Cu and B.Cu pours are stitched in parallel.',
            f'Same current on one 0.5 oz inner layer would need {one_inner:.0f} mm: inner layers carry no power path.',
            'Resistance per 10 mm of 1 oz outer copper at 60 C: '
            + ', '.join(f'{w:g} mm {RHO_CU * (1 + ALPHA_CU * 40) * 10 / (w * outer) * 1000:.2f} mOhm'
                        for w in (0.25, 1, 3, 8)) + '.']
    out += ['', f'Layer-change vias (barrel plating assumed {VIA_PLATING * 1000:.0f} um; IPC-2221 inner k as a conservative barrel screen):']
    for drill in VIA_DRILL:
        area = math.pi * (drill + VIA_PLATING) * VIA_PLATING
        per_via = ipc2221_current(area, 10, .024)
        out.append(f'  drill {drill:.1f} mm: {per_via:.2f} A per via at dT10; '
                   f'main path {math.ceil(main / per_via)} vias, HEATER24 {math.ceil(rows[2][2] / per_via)}, '
                   f'CH1 input {math.ceil(rows[4][2] / per_via)}.')
    out += ['', 'Kelvin taps (net ties, v0.22): NT711 R715->R712 (LED1_CS_K), NT712 R716->U710 FB (LED1_FB_K),',
            'NT721 R725->R722 (LED2_CS_K), NT722 R726->U720 FB (LED2_FB_K). Route the *_K nets as thin traces from the',
            'net-tie pad; never connect them to the source/return pours. Error per 1 mOhm of shared copper:',
            f'  R715 0.027 ohm: {1 / 27 * 100:.1f} % of the CS signal; R716 0.18 ohm: {1 / 180 * 100:.2f} % of LED current.',
            '', 'Not covered: neighbouring hot parts (inductors, diodes, shunts), enclosure air, via fill, current crowding',
            'at pads/fuse holders, transient/fault currents (fuse clearing), plating tolerance.']
    return '\n'.join(out) + '\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('netlist', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = report(args.netlist)
    if args.output:
        args.output.write_text(result, encoding='utf-8')
    print(result, end='')
