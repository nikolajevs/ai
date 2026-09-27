"""Power-path sizing from the v0.13 netlist; not a fault/thermal simulation.

Usage: python analyze_power_path.py netlist.xml [--output report.txt]
Datasheet conditions and unresolved qualification: PCB_V1/INPUT_PROTECTION.md.
"""
import argparse
from pathlib import Path
import xml.etree.ElementTree as ET


def report(netlist):
    comps = {c.get('ref'): c for c in ET.parse(netlist).findall('.//components/comp')}
    expected = {'Q901': 'NTMFS5C628NLT1G', 'Q601': 'NTMFS5C628NLT1G',
                'U901': 'LM74700QDBVRQ1', 'U602': 'TPS70950DBVR',
                'U601': 'UCC27524ADR', 'D901': 'SMBJ14CA-E3/52',
                'C901': '220u / 35V low ESR', 'C902': '1u / 50V X7R',
                'C904': '220n / 50V X7R', 'C602': '2.2u / 25V X7R',
                'C603': '2.2u / 50V X7R', 'C604': '10u / 16V X7R'}
    for ref, value in expected.items():
        assert comps[ref].findtext('value') == value, (ref, 'sizing data no longer matches schematic')

    lines = ['GrowBox v0.13 input / heater supply sizing',
             'CONDITIONAL ESTIMATES, not approval of 25 A PCB operation or fault protection.',
             'RDS hot multiplier 1.7 is a design allowance, not a guaranteed production limit.',
             '', 'Q901 conduction with VGS >=10 V (2.4 mOhm max at 25 C):',
             'I_A  drop_25C_mV  loss_25C_W  loss_Rx1.7_W']
    for current in (18, 20, 25):
        r = .0024
        lines.append(f'{current:>3} {current*r*1000:>13.3f} {current**2*r:>12.3f} {current**2*r*1.7:>13.3f}')
    # This target assumes all Q901 heat sees the stated ambient, without sharing
    # a hot copper region with the boost converters. Real PCB coupling is absent.
    theta_target = (125 - 60) / (25**2 * .0024 * 1.7)
    lines += [f'At 25 A, TA=60 C and target TJ=125 C: required RthetaJA <= {theta_target:.2f} C/W.',
              'This is a cooling target, not a measured board thermal resistance.',
              'At low current LM74700 regulates forward drop (13..29 mV); I^2R alone is incomplete.',
              '', 'Q601 conduction with measured VGS >=4.5 V (3.3 mOhm max at 25 C):',
              'condition  I_A  loss_25C_W  loss_Rx1.7_W']
    for name, current in [('steady', 100/12), ('cold_+15%', 100/12*1.15)]:
        lines.append(f'{name:>9} {current:>6.3f} {current**2*.0033:>11.3f} {current**2*.0033*1.7:>13.3f}')

    # Conservatively add the table's whole line/load errors to the initial
    # accuracy. The TPS709 accuracy table is for TA=-40..85 C, not all TJ=125 C.
    vmin = 5*.99 - .010 - .050
    vmax = 5*1.01 + .010 + .050
    startup_threshold = 4.65  # UCC27524A package D max; DGN has different limits.
    gate_charge_allowance = 2*52e-9  # allowance; 52 nC itself is typical at 10 V.
    local_cap_min = 1e-6  # requirement for C602; MPN/DC-bias not yet selected.
    droop = gate_charge_allowance/local_cap_min
    lines += ['', '5 V rail screening at TPS709 specified accuracy conditions:',
              f'Static rail envelope: {vmin:.3f}..{vmax:.3f} V (line/load errors added conservatively).',
              f'UCC27524A SOIC-D startup threshold max: {startup_threshold:.3f} V; static margin {vmin-startup_threshold:.3f} V.',
              f'Gate-charge allowance {gate_charge_allowance*1e9:.1f} nC / C602 effective >=1 uF: droop <= {droop:.3f} V.',
              f'Screened local rail after that charge step: {vmin-droop:.3f} V; startup margin {vmin-droop-startup_threshold:.3f} V.',
              'ESR/ESL, regulator transients and driver output drop are NOT included in the charge-step estimate.',
              'Bench targets: gate rail >=4.75 V after startup and Q601 VGS >=4.5 V while commanded on.',
              '5 mA rail load is a design budget to verify, not a guaranteed SOIC-D bias-current maximum.',
              f'LDO dissipation at VIN=13.2 V / VOUT={vmin:.2f} V / IOUT=5 mA: {(13.2-vmin)*.005:.4f} W plus Iq.',
              '', 'TVS screening at 25 C / 10-1000 us only:',
              'SMBJ14CA: standoff 14 V; clamp 23.2 V at 25.9 A; nominal input upper design value 13.2 V.',
              f'Clamp margin to TPS54202 recommended VIN max 28 V: {28-23.2:.1f} V.',
              f'Clamp margin to TPS709 VIN max 30 V: {30-23.2:.1f} V.',
              'No hot clamp extrapolation: VBR tempco is not a guaranteed VC temperature model.',
              'Not rated for a sustained 24 V source; no series OVP or current limit.',
              'Unresolved: PSU fault current, cable/fuses I^2t, inrush/SOA, terminal rating, effective capacitors, thermal layout.',
              'Existing LED sizing uses voltage at AL8853 VIN; allow for Q901/fuse/cable drops when setting the PSU.']
    return '\n'.join(lines)+'\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('netlist', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    text = report(args.netlist)
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    print(text, end='')
