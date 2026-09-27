"""Power-path sizing from the v0.14 netlist (24 V input); not a fault/thermal simulation.

Usage: python analyze_power_path.py netlist.xml [--output report.txt]
Datasheet conditions and open qualification items: PCB_V1/REDESIGN_24V.md.
"""
import argparse
from pathlib import Path
import xml.etree.ElementTree as ET

# External supply: 24.0 V set point, never above 25 V (TVS standoff 26 V).
VIN_MIN, VIN_NOM, VIN_MAX = 21.6, 24.0, 25.0
PTC_W = 100.0
PUMP_A = 1.0          # design budget for a 24 V pump; measure the real inrush/stall current
FANS_A_12V = 2 * 0.5  # two 4-wire PC fans, budget per fan
LOGIC_A_3V3 = 0.6     # ESP32 Wi-Fi peaks + SD + RTC, averaged budget
LED_IIN_NOM_W = 76.75 / 0.90  # LED power / assumed boost efficiency
LED_IIN_WORST = 3.055 + 1.391  # CH1 + CH2 maxima from review/LED_power_v14.txt


def report(netlist):
    comps = {c.get('ref'): c for c in ET.parse(netlist).findall('.//components/comp')}
    expected = {'U902': 'LMR16020PDDAR', 'R904': '100k 1%', 'R905': '6.65k 1%', 'R906': '49.9k 1%',
                'R907': '560k 1%', 'R908': '47k 1%', 'L902': '22u SRP1265A-220M', 'D902': 'SS36-E3/57T',
                'D901': 'SMBJ26CA-E3/52', 'D601': 'SMBJ30A-E3/52', 'Q601': 'NTMFS5C628NLT1G',
                'U601': 'UCC27524ADR', 'C901': '220u / 50V', 'F902': '10A mini blade (ATM)',
                'F903': '7.5A mini blade (ATM)', 'Q521': 'AO3422', 'D521': 'SS36-E3/57T'}
    for ref, value in expected.items():
        assert comps[ref].findtext('value') == value, (ref, 'sizing data no longer matches schematic')

    out = ['GrowBox v0.14 power path (24 V input) sizing',
           'CONDITIONAL ESTIMATES from datasheet limits; not a fault, surge or thermal qualification.', '']

    # ---------------------------------------------------------------- branch currents
    ptc = PTC_W / VIN_NOM
    ptc_cold = ptc * 1.15
    loads = ptc_cold + PUMP_A
    led_nom = LED_IIN_NOM_W / VIN_NOM
    tps_in_12 = 3.3 * LOGIC_A_3V3 / 0.85 / 12.0
    aux12 = FANS_A_12V + tps_in_12 + 0.01
    aux_in = 12.03 * aux12 / 0.85 / VIN_MIN
    total_worst = loads + LED_IIN_WORST + aux_in
    total_nom = ptc + PUMP_A + led_nom + 12.03 * (0.4 + tps_in_12) / 0.85 / VIN_NOM
    out += ['Branch currents (A):',
            f'  F902 +24V_LOADS: PTC {ptc:.2f} (cold +15% {ptc_cold:.2f}) + pump budget {PUMP_A:.2f} = {loads:.2f}'
            f' -> {loads/10*100:.0f}% of 10 A ATM',
            f'  F903 +24V_LED: nominal {led_nom:.2f}; worst-case estimate {LED_IIN_WORST:.2f}'
            f' -> {LED_IIN_WORST/7.5*100:.0f}% of 7.5 A ATM',
            f'  12 V aux: fans {FANS_A_12V:.2f} + TPS54202 input {tps_in_12:.2f} + driver 0.01 = {aux12:.2f} A at 12 V;'
            f' {aux_in:.2f} A from 24 V at {VIN_MIN} V (unfused branch, PSU OCP only)',
            f'  Input total: nominal ~{total_nom:.1f} A, worst-case estimate {total_worst:.1f} A;'
            f' 300 W PSU = {300/VIN_NOM:.1f} A; XT60 rated 30 A continuous class.', '']

    # ---------------------------------------------------------------- TVS / voltage margins
    clamp_in, clamp_drain = 42.1, 48.4
    out += ['TVS screening (datasheet 10/1000 us, 25 C):',
            f'  D901 SMBJ26CA: VWM 26 V > PSU max {VIN_MAX} V; VBR min 28.9 V; VC {clamp_in} V at 14.3 A',
            f'    margin to AL8853 VIN abs max 43 V: {43 - clamp_in:.1f} V (thin; typical surges clamp lower)',
            f'    margin to LMR16020 VIN abs max 65 V: {65 - clamp_in:.1f} V',
            f'  D601 SMBJ30A: VWM 30 V > {VIN_MAX} V; VC {clamp_drain} V vs Q601 VDS 60 V: margin {60 - clamp_drain:.1f} V',
            f'  Q521 AO3422 55 V: flyback D521 to +24V_LOADS, VDS <= {VIN_MAX + 0.75:.1f} V + input clamp; '
            f'worst {clamp_in + 0.75:.1f} V -> margin {55 - clamp_in - 0.75:.1f} V',
            '  No electronic reverse protection: keyed XT60 only. A reversed PSU cable destroys the board.', '']

    # ---------------------------------------------------------------- 12 V aux buck
    vfb_min, vfb_nom, vfb_max = .735, .750, .765
    rt, rb = 100e3, 6.65e3
    vo_nom = vfb_nom * (1 + rt / rb)
    vo_min = vfb_min * (1 + rt * .99 / (rb * 1.01))
    vo_max = vfb_max * (1 + rt * 1.01 / (rb * .99))
    L, fsw = 22e-6, 500e3
    ripple = lambda vin: (vin - vo_nom) * vo_nom / (vin * L * fsw)
    ent, enb = 560e3, 47e3
    ien, ihys = 1e-6, 3.6e-6
    start = lambda ven: ven + ent * (ven / enb - ien)
    stop = lambda ven: ven + ent * (ven / enb - ien - ihys)
    d_diode = 1 - vo_nom / VIN_MIN
    out += ['12 V aux buck LMR16020 (datasheet SNVSAH8A):',
            f'  Vout nominal {vo_nom:.2f} V; envelope {vo_min:.2f}..{vo_max:.2f} V (FB 0.735..0.765 V, 1 % resistors)',
            f'    UCC27524A VDD 4.5..18 V ok; TPS54202 VIN <= 28 V ok; PC fan 12 V +/-5 % = 11.4..12.6 V ok',
            f'  fsw 500 kHz (RT 49.9k, table 1); L 22 uH ripple {ripple(VIN_MAX):.3f} A p-p at {VIN_MAX} V,'
            f' {ripple(VIN_MIN):.3f} A at {VIN_MIN} V',
            f'  Peak at {aux12:.2f} A load: {aux12 + ripple(VIN_MAX)/2:.2f} A < current limit min 2.5 A;'
            f' SRP1265A-220M Isat 9 A > limit max 3.8 A',
            f'  EN UVLO 560k/47k: start {start(1.2):.1f} V typ ({start(1.05):.1f}..{start(1.38):.1f} V over EN threshold),'
            f' stop {stop(1.2):.1f} V typ',
            f'  D902 SS36 average {aux12 * d_diode:.2f} A at {VIN_MIN} V; conduction ~{aux12 * d_diode * .5:.2f} W at Vf 0.5 V', '']

    # ---------------------------------------------------------------- heater switch
    out += ['Q601 NTMFS5C628NL with ~12 V gate (UCC27524A VDD = 12 V aux), 2.4 mOhm max at VGS 10 V, 25 C:',
            'condition   I_A  loss_25C_W  loss_Rx1.7_W']
    for name, current in [('steady', ptc), ('cold_+15%', ptc_cold)]:
        out.append(f'{name:>9} {current:>6.3f} {current**2*.0024:>11.3f} {current**2*.0024*1.7:>13.3f}')
    out += ['', 'Unresolved: real pump current, fuse interrupt rating and I2t with the actual PSU, cable gauge,',
            'surge energy of D901, buck loop stability/thermal on the real layout, LED boost startup and OVP events.']
    return '\n'.join(out) + '\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('netlist', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    text = report(args.netlist)
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    print(text, end='')
