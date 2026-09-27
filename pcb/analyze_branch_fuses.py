"""Screen v0.14 fuse loading against the existing LED sizing cases.

This is not a fault-clearing, wire-ampacity or selectivity calculation.
Usage: python analyze_branch_fuses.py netlist.xml --output report.txt
"""
import argparse
import itertools
from pathlib import Path
import xml.etree.ElementTree as ET
from analyze_led_power import CHANNELS, check_schematic, estimate

# Littelfuse 451/453, revised 12/01/25. Nominal cold R, not hot/max R.
PARTS = {1: ('0451001.MRL', .0780, .6029),
         2: ('0451002.MRL', .0367, .530),
         3: ('0451003.MRL', .0227, 1.650),
         10: ('0451010.MRL', .0056, 26.46),
         15: ('0451015.MRL', .0037, 97.82)}
RATINGS = {'F501': 1, 'F511': 1, 'F521': 2,
           'F711': 10, 'F721': 3, 'F731': 3, 'F903': 15}
CONTINUOUS_FACTOR = .75  # manufacturer's continuous-current derating
TEMPERATURE_ALLOWANCE = .90  # deliberately below graph near 60 C; not a guarantee
HOT_R_ALLOWANCE = 2.0  # voltage-drop budget only, must be measured


def report(path):
    check_schematic(path)
    comps = {c.get('ref'): c for c in ET.parse(path).findall('.//components/comp')}
    for ref, rating in RATINGS.items():
        fields = {f.get('name'): f.text for f in comps[ref].findall('fields/field')}
        assert fields['MPN'] == PARTS[rating][0], (ref, 'recalculate for changed fuse')
        assert comps[ref].findtext('value').startswith(f'{rating}A / ')
    by_channel = {}
    for ch in CHANNELS:
        by_channel[ch['n']] = [estimate(ch, *p) for p in itertools.product(
            (10.8, 12, 13.2), (40, 44, 48), (110e3, 130e3), (.85, .90), (False, True))]
    rms = {n: max(c['il_rms'] for c in cases) for n, cases in by_channel.items()}
    mean = {n: max(c['average'] for c in cases) for n, cases in by_channel.items()}
    # Sum of individual maxima is conservative; input capacitor filtering is
    # not credited. AL8853 quiescent/gate-drive consumption is included in the
    # existing deliberately pessimistic efficiency allowance, not added twice.
    loads = {'F501': 4/12, 'F511': 4/12, 'F521': .5,
             'F711': rms[1], 'F721': rms[2], 'F731': rms[3], 'F903': sum(rms.values())}
    out = ['PCB_V1 v0.14 branch-fuse screening',
           'PROTOTYPE ONLY: no guaranteed short-circuit clearing or selectivity.',
           '12 V fan/pump nameplate currents; starting/stall currents are not known.',
           'LED input voltage >=10.8 V AT THE CONTROLLER after all input losses.',
           'Continuous allowance: rated A * 0.75 * 0.90; target fuse ambient <=60 C.',
           'The 0.90 temperature factor is a design allowance, not a measured limit.', '',
           'Ref   Rated  RMS allowance  Working RMS  Margin   Cold-R loss (nominal)']
    total_loss = 0
    for ref, rating in RATINGS.items():
        capacity = rating * CONTINUOUS_FACTOR * TEMPERATURE_ALLOWANCE
        current = loads[ref]
        loss = current**2 * PARTS[rating][1]
        total_loss += loss
        assert current < capacity, (ref, 'continuous-load screen failed')
        out.append(f'{ref:5} {rating:5.1f}A {capacity:10.3f}A {current:11.3f}A '
                   f'{capacity-current:7.3f}A {loss:10.4f}W')
    big_drop = mean[1] * PARTS[10][1] + sum(mean.values()) * PARTS[15][1]
    old_common_capacity = 10 * CONTINUOUS_FACTOR * TEMPERATURE_ALLOWANCE
    out += ['', f'Total nominal cold-R fuse loss: {total_loss:.4f} W; hot loss is higher.',
            f'Old 10 A common LED fuse allowance {old_common_capacity:.3f} A '
            f'< conservative combined RMS {sum(rms.values()):.3f} A.',
            f'F711+F903 mean-current voltage drop: {big_drop:.4f} V cold-nominal;',
            f'with 2x resistance budget: {big_drop*HOT_R_ALLOWANCE:.4f} V.',
            'Add F901, Q901, connector, copper and cable drops separately.', '',
            'FAULT LIMITS:',
            'At 2x rating, 1/2/3/10 A fuses may take up to 5 s; 15 A up to 20 s.',
            'These maxima apply at the specified test conditions, not every PSU fault.',
            'A current-limited/hiccup PSU may never open the fuse. Verify actual source.',
            'Nominal melting I2t is not maximum total-clearing I2t or a pulse-life limit.',
            'No semiconductor survival or upstream/downstream discrimination is claimed.',
            'Output-capacitor discharge into an LED short is downstream of input fuses.',
            'F901/F902 MPN, wiring ampacity and prospective fault current remain open.']
    return '\n'.join(out)+'\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('netlist', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = report(args.netlist)
    if args.output:
        args.output.write_text(result, encoding='utf-8')
    print(result, end='')
