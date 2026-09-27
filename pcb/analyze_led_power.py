"""Reproducible electrical sizing estimates for PCB_V1, not a SPICE/thermal model.

Run after exporting the schematic as KiCad XML:
  python analyze_led_power.py netlist.xml
Requires only the Python standard library. See PCB_V1/DESIGN.md for
sources, modelling assumptions and the measurements still required.
"""
import argparse
import itertools
import math
from pathlib import Path
import xml.etree.ElementTree as ET


CHANNELS = [
    # v0.16: back to the 16.9 mm SRP1770TA-470M; restores OCP headroom and lowers copper loss.
    dict(n=1, led_r=.182, cs_r=.027, slope_r=1000, l_mpn='SRP1770TA-470M',
         l_bias=.70, dcr=.055, irms=8.7, isat=16, caps=4,
         diode='STPS5H100B-TR', diode_vf=.85, diode_a=.51, diode_b=.02),
    # CH2 has one CURRENT REGULATOR for J721 || J731, no guaranteed sharing.
    # Even if one bar is open, the other stays below 0.5 A at the FB/R corner.
    dict(n=2, led_r=.43, cs_r=.047, slope_r=2700, l_mpn='SRP1265A-470M',
         l_bias=.80, dcr=.090, irms=6.5, isat=9.5, caps=3,
         diode='STPS2H100AFY', diode_vf=.88, diode_a=.56, diode_b=.045),
]
# POWER-stage input voltage, NOT the AL8853 VIN pins (now 12 V aux bias):
# 24 V PSU set point, 25 V ceiling,
# -10 % allowance for PSU tolerance, cable, fuse and connector drops.
VIN_CASES = (21.6, 24.0, 25.0)
CAP_MPN = 'CL32Y106KCV6PNE'
# Samsung typical curve, 25 C, 1 kHz/1 Vrms; rounded DOWN at 49 V.
# 49 V covers 48 V LED + FB voltage. These are design allowances, not
# guaranteed simultaneous production minima for DC bias/temperature/aging.
CAP_BIASED_UF = 2.575
CAP_ALLOWANCE = .90 * .78 * .90  # initial tolerance, X7S, extra aging/model reserve


def check_schematic(path):
    comps = {c.get('ref'): c for c in ET.parse(path).findall('.//components/comp')}
    for ch in CHANNELS:
        n = ch['n']
        expected = {f'L7{n}1': '47u', f'R7{n}5': str(ch['cs_r']),
                    f'R7{n}6': '0.182' if n == 1 else '0.43',
                    f'R7{n}2': '1k' if n == 1 else '2.7k'}
        for ref, value in expected.items():
            assert comps[ref].findtext('value').split()[0] == value, (ref, value)
        assert comps[f'D7{n}1'].findtext('value') == ch['diode']
        fields = {f.get('name'): f.text for f in comps[f'L7{n}1'].findall('fields/field')}
        assert fields.get('MPN') == ch['l_mpn'], (n, 'inductor MPN')
        cap_refs = [f'C7{n}6', f'C7{n}7'] + (['C718', 'C719'] if n == 1 else ['C728'])
        for ref in cap_refs:
            assert comps[ref].findtext('value') == '10u 100V X7S'
            fields = {f.get('name'): f.text for f in comps[ref].findall('fields/field')}
            assert fields.get('MPN') == CAP_MPN, (ref, 'MLCC MPN')


def estimate(ch, vin, vled, fs, eta, tolerance):
    fb = .206 if tolerance else .200
    io = fb / (ch['led_r'] * (.99 if tolerance else 1))
    inductance = 47e-6 * .8 * ch['l_bias']
    # Size an ideal stage for an extra output load Io/eta and the diode drop.
    # This deliberately overestimates electrical stress; it does not predict
    # actual duty, efficiency or where the circuit dissipates its losses.
    vo = vled + fb + ch['diode_vf']
    load = io / eta
    d_ccm = 1 - vin / vo
    ripple = vin * d_ccm / (inductance * fs)
    average = vo * load / vin
    if average >= ripple / 2:
        mode, duty, diode_duty = 'CCM', d_ccm, 1 - d_ccm
        peak, valley = average + ripple / 2, average - ripple / 2
        mean_square = average**2 + ripple**2 / 12
        il_rms = math.sqrt(mean_square)
        iq_rms = math.sqrt(duty * mean_square)
        id_rms = math.sqrt(diode_duty * mean_square)
    else:
        mode = 'DCM'
        duty = math.sqrt(2 * inductance * fs * load * (vo - vin) / vin**2)
        diode_duty = vin * duty / (vo - vin)
        peak, valley = vin * duty / (inductance * fs), 0
        il_rms = peak * math.sqrt((duty + diode_duty) / 3)
        iq_rms = peak * math.sqrt(duty / 3)
        id_rms = peak * math.sqrt(diode_duty / 3)
    # Datasheet equations 2..6. Only the CCM subharmonic test applies here;
    # this is not the outer feedback-loop stability test.
    rs_high = ch['cs_r'] * 1.01
    sn, sf = rs_high * vin / inductance, rs_high * (vo - vin) / inductance
    se = (.1 + 50e-6 * ch['slope_r'] * .99) * fs
    ratio = abs((sf - se) / (sn + se)) if mode == 'CCM' else None
    # OCP is specified at 90% duty. Subtract the external ramp at the
    # estimated duty, without taking credit for the lower internal ramp.
    # IS/VSL and OCP outside its stated test condition have no full min/max
    # envelope: these are screening estimates and MUST be bench-verified.
    ocp_low = (.255 - 50e-6 * ch['slope_r'] * 1.01 * duty) / rs_high
    ocp_high = (.345 + .1 * (.9 - duty)
                - 50e-6 * ch['slope_r'] * .99 * duty) / (ch['cs_r'] * .99)
    c_eff = ch['caps'] * CAP_BIASED_UF * CAP_ALLOWANCE * 1e-6
    # Whole-cycle discharge bound, intentionally more conservative than
    # Io*D/(fs*C). Does not include ESR/ESL, pulse skipping or cable ringing.
    ripple_v = io / (fs * c_eff)
    return dict(mode=mode, duty=duty, vin=vin, vled=vled, fs=fs,
                io=io, average=average, peak=peak, valley=valley,
                il_rms=il_rms, iq_rms=iq_rms, id_rms=id_rms, ratio=ratio,
                ocp_low=ocp_low, ocp_high=ocp_high, headroom=ocp_low - peak,
                p_copper_100c=il_rms**2 * ch['dcr'] * (1 + .00393 * 75),
                p_shunt=iq_rms**2 * rs_high,
                p_diode=ch['diode_a'] * load + ch['diode_b'] * id_rms**2,
                cap_rms=math.sqrt(max(0, id_rms**2 - load**2)),
                c_eff_uf=c_eff * 1e6, ripple_v=ripple_v)


def report():
    out = ['PCB_V1 v0.16 LED sizing estimates (24 V power, 12 V IC bias, 2 channels)',
           'Not a manufacturing release or a guaranteed OCP/stability envelope.',
           'VIN 21.6/24/25 V at the LED rail; LED Vf 40/44/48 V;',
           'fs 110/130 kHz; assumed efficiency 85/90%; FB/shunt tolerances;',
           'L -20% initial plus bias allowance; winding resistance at 100 C.', '']
    for ch in CHANNELS:
        cases = [estimate(ch, *p) for p in itertools.product(
            VIN_CASES, (40, 44, 48), (110e3, 130e3), (.85, .90), (False, True))]
        hi = lambda k: max(c[k] for c in cases if c[k] is not None)
        lo = lambda k: min(c[k] for c in cases if c[k] is not None)
        assert hi('peak') < ch['isat'], 'Normal peak exceeds selected Isat point'
        assert hi('il_rms') < ch['irms'], 'Normal RMS exceeds selected thermal rating'
        ratios = [c['ratio'] for c in cases if c['ratio'] is not None]
        assert not ratios or max(ratios) < 1, 'CCM subharmonic screening failed'
        ratio_txt = f'{max(ratios):.3f} (<1; typical ramp only)' if ratios else 'n/a (all cases DCM)'
        assert lo('headroom') > 0, 'Estimated minimum OCP clips normal peak'
        assert hi('ocp_high') < ch['isat'], 'Estimated operating-duty OCP exceeds Isat'
        out += [f"CH{ch['n']}: {ch['l_mpn']}; {len(cases)} cases; "
                f"modes {','.join(sorted({c['mode'] for c in cases}))}",
                f"  ILED max {hi('io'):.4f} A; Iin estimate max {hi('average'):.3f} A",
                f"  L effective allowance {47*.8*ch['l_bias']:.2f} uH; "
                f"Ipeak max {hi('peak'):.3f} A; ILrms max {hi('il_rms'):.3f} A",
                f"  IQrms max {hi('iq_rms'):.3f} A; IDrms max {hi('id_rms'):.3f} A",
                f"  CCM subharmonic ratio max {ratio_txt}",
                f"  OCP estimate {lo('ocp_low'):.3f}..{hi('ocp_high'):.3f} A; "
                f"minimum paired peak headroom {lo('headroom'):.3f} A",
                f"  Winding copper loss at 100 C max {hi('p_copper_100c'):.3f} W "
                '(core loss NOT included)',
                f"  CS shunt loss max {hi('p_shunt'):.3f} W; "
                f"diode conduction estimate max {hi('p_diode'):.3f} W "
                '(reverse/dynamic loss NOT included)',
                f"  Output bank {ch['caps']} x 10u/100V; C effective allowance "
                f"{hi('c_eff_uf'):.3f} uF; whole-cycle discharge bound {hi('ripple_v'):.3f} Vpp",
                f"  Output-cap RMS screening max {hi('cap_rms'):.3f} A total", '']
    nominal = sum(.2 / c['led_r'] * 48 for c in CHANNELS)
    maximum = sum(.206 / (c['led_r'] * .99) * 48 for c in CHANNELS)
    bar_max = .206 / (.43 * .99)
    assert bar_max < .5, 'CH2 can exceed the single-bar rating if the other bar is open'
    out += [f'Combined LED power at 48 V: nominal {nominal:.2f} W; FB/R corner {maximum:.2f} W.',
            f'CH2 sharing is NOT guaranteed. One remaining bar: <= {bar_max:.4f} A steady-state.',
            'Uncovered: faults/startup/OVP, gate delays, ramp tolerances, compensation loop,',
            'hot saturation and core loss, MLCC bias/temperature/aging interaction, layout.',
            'Input branch fuses are fitted; clearing time/I2t with the actual PSU is NOT qualified.']
    return '\n'.join(out) + '\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('netlist', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    check_schematic(args.netlist)
    result = report()
    if args.output:
        args.output.write_text(result, encoding='utf-8')
    print(result, end='')
