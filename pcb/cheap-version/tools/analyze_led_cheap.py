"""LED boost sizing for cheap-1: the PCB_V1 estimates re-run with the stock parts; SPDX-License-Identifier: MIT.

Usage: python pcb/cheap-version/tools/analyze_led_cheap.py [--output pcb/cheap-version/review/LED_power_cheap1.txt]

Imports pcb/analyze_led_power.py (the PCB_V1 model, unchanged) and overrides the parameters that differ:
  CH1 inductor  Feryster DTMSS-27/0.047/15-V: L = 45.5 uH at 1 A and about 42 uH at 5 A (graph in the
                datasheet, page 4), 26.1 uH at 15 A, RDC 10 mOhm, 33 K rise at 15 A. L is taken as 47 uH -20 %
                (as for the other inductors) and a further 12 % drop at the peak current.
  diodes        Diodes SBRT15U100SP5: VF typ. 0.44 V at 5 A, 0.59 V at 12 A (25 C) -> 0.333 V + 0.021 ohm,
                rounded up to 0.35 V + 0.025 ohm, 0.60 V assumed for the output-voltage estimate.
  output MLCCs  Samsung CL32B475KCI6PJE 4.7 uF/100 V X7R: 2.6 uF at 48 V (lower end of the 2.6..3.3 uF
                estimate supplied by the user, NOT a Samsung curve), X7R +/-15 % over temperature.
  switches      Infineon BSC146N10LS5 (RDS(on) 14.6 mOhm max at 10 V; only the name is used by the model).
CH2 keeps the PCB_V1 inductor (SRP1265A-470M).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import analyze_led_power as m  # noqa: E402

SBRT = dict(diode='SBRT15U100SP5', diode_vf=.60, diode_a=.35, diode_b=.025)
m.SWITCH = 'BSC146N10LS5'
m.CHANNELS = [
    dict(n=1, led_r=.18, cs_r=.027, slope_r=1000, l_mpn='DTMSS-27/0.047/15-V',
         l_bias=.88, dcr=.011, irms=15, isat=15, caps=4, **SBRT),
    dict(n=2, led_r=.43, cs_r=.047, slope_r=2700, l_mpn='SRP1265A-470M',
         l_bias=.80, dcr=.090, irms=6.5, isat=9.5, caps=3, **SBRT),
]
m.CAP_BIASED_UF = 2.6
m.CAP_ALLOWANCE = .90 * .85 * .90      # initial tolerance, X7R +/-15 %, extra aging/model reserve

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    text = m.report().replace('PCB_V1 v0.22', 'cheap-1 (PCB_V1 0.22 schematic with stock parts)').replace(
        '10u/100V', '4.7u/100V X7R')
    if args.output:
        args.output.parent.mkdir(exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
    print(text, end='')
