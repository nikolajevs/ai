"""v0.17 sizing from the netlist, not fault/surge/thermal qualification.
Usage: python analyze_power_path.py netlist.xml [--output report.txt]
Sources/assumptions: PCB_V1/DESIGN.md.
"""
import argparse, itertools, math
from pathlib import Path
import xml.etree.ElementTree as ET
from analyze_led_power import CHANNELS, VIN_CASES, estimate, check_schematic


def report(netlist):
    check_schematic(netlist)
    comps = {c.get('ref'):c for c in ET.parse(netlist).findall('.//components/comp')}
    expected = {'U902':'LMR16020PDDAR','R904':'150k 0.1%','R905':'10k 0.1%','R906':'49.9k 1%',
                'R907':'560k 1%','R908':'47k 1%','L902':'22u SRP1265A-220M','D902':'SS36-E3/57T',
                'D901':'SMBJ26CA-E3/52','D601':'SMBJ30A-E3/52','Q601':'NTMFS5C628NLT1G',
                'U601':'UCC27524ADR','C901':'220u / 50V','F902':'10A mini blade (ATM)',
                'Q521':'AO3422','D521':'SS36-E3/57T','C602':'4.7u / 25V X7R',
                'C909':'100u 25V polymer','C910':'22u 25V X7R'}
    for ref,value in expected.items():
        assert comps[ref].findtext('value') == value,(ref,'sizing does not match schematic')
    fuses = {'F501':(1,'0451001.MRL'),'F511':(1,'0451001.MRL'),'F521':(1,'0451001.MRL'),
             'F711':(6.3,'045106.3MRL'),'F721':(3,'0451003.MRL'),'F904':(2,'0451002.MRL')}
    for ref,(amps,mpn) in fuses.items():
        assert comps[ref].findtext('value') == f'{amps}A / {mpn}',ref
        fields = {f.get('name'):f.text for f in comps[ref].findall('fields/field')}
        assert fields.get('MPN') == mpn,(ref,'fuse MPN differs')
    vmin,vnom,vmax = VIN_CASES
    vo, vlo, vhi = 12., .735*(1+15*.999/1.001), .765*(1+15*1.001/.999)
    assert 11.4 < vlo < vhi < 12.6
    ptc,pump = 100/24,6/24
    cold = ptc*1.15
    # Lower-voltage constant-power screen is an assumption, not a PTC resistance model.
    ptc_screen = 100/vmin*1.15
    pump_budget = .5  # 2x nominal allowance; real stall/inrush still unknown
    fans,logic,bias = 8/vlo,3.3*1.0/.85/vlo,.03
    aux_budget = 1.2
    assert fans+logic+bias < aux_budget
    # Initial L -20%, extra bias -20%, frequency -10% engineering scenario.
    # Not a guaranteed frequency tolerance at RT=49.9k.
    lmin,lmax,fsmin = 22e-6*.8*.8,22e-6*1.2,450e3
    buck = []
    for vi,v in itertools.product(VIN_CASES,(vlo,vo,vhi)):
        di = (vi-v)*v/(vi*lmin*fsmin)
        buck.append(dict(ripple=di,peak=aux_budget+di/2,
                         irms=math.sqrt(v/vi*(aux_budget**2+di**2/12))/.85,
                         diode=aux_budget*(1-v/vi)))
    peak = max(c['peak'] for c in buck)
    assert peak < 2.5,'aux peak exceeds specified 25 C limit minimum'
    aux_in,aux_rms = vhi*aux_budget/.85/vmin,max(c['irms'] for c in buck)
    cases = [[estimate(ch,*p) for p in itertools.product(VIN_CASES,(40,44,48),(110e3,130e3),(.85,.90),(False,True))] for ch in CHANNELS]
    led_mean = [max(c['average'] for c in cc) for cc in cases]
    led_rms = [max(c['il_rms'] for c in cc) for cc in cases]
    out = ['GrowBox v0.17 power path (24 V)',
           'Conditional datasheet calculations, NOT fault/surge/thermal qualification.',
           '24.0 V set point; power stages 21.6..25 V; AL8853 VIN pins use 12 V aux.', '',
           f'PTC 24 V/100 W: {ptc:.3f} A nominal; +15% cold at 24 V: {cold:.3f} A.',
           f'Pump confirmed 24 V/6 W: {pump:.3f} A; design allowance {pump_budget:.3f} A (not a measured stall limit).',
           f'Aux budget: fans {fans:.3f} + 3.3V/1A logic input {logic:.3f} + gate/controller bias {bias:.3f} = {fans+logic+bias:.3f} A.',
           f'Aux ceiling {aux_budget:.1f} A; input mean {aux_in:.3f} A; RMS screen {aux_rms:.3f} A.',
           f'LED input mean bound {sum(led_mean):.3f} A; sum of RMS bounds {sum(led_rms):.3f} A.',
           f'Whole-board mean screen {ptc_screen+pump_budget+sum(led_mean)+aux_in:.3f} A; conservative RMS sum {ptc_screen+pump_budget+sum(led_rms)+aux_rms:.3f} A.',
           'Includes a constant-power PTC lower-voltage scenario, not a predicted PTC temperature/resistance.',
           '24 V/300 W PSU nominal current is 12.5 A; actual OCP/hiccup behavior unspecified.', '',
           'Fuse loading: 0.75 continuous x 0.90 engineering hot-board allowance.',
           'ref     rating_A  load_bound_A  derated_A  spare_A']
    loading = {'F501':fans/2,'F511':fans/2,'F521':pump_budget,'F711':led_rms[0],'F721':led_rms[1],
               'F904':aux_rms,'F902':ptc_screen+pump_budget}
    ratings = {r:a for r,(a,_) in fuses.items()} | {'F902':10}
    for r in sorted(loading):
        allowed=ratings[r]*.75*.9
        assert loading[r] < allowed,(r,'continuous-loading screen failed')
        out.append(f'{r:6} {ratings[r]:9.2f} {loading[r]:13.3f} {allowed:10.3f} {allowed-loading[r]:8.3f}')
    out += ['F902 holder uses separately purchased Littelfuse 0297010.WXNV MINI 10 A / 32 V DC insert (curated BOM).',
            'SMT fuse ratings here are >=125 V; loading does not prove I2t, interruption or selective clearing.',
            'v0.16: former F903 (7.5 A, redundant with F711+F721, smallest margin) removed; LED channels are fused individually.',
            'XT60-to-TVS/bulk segment has no onboard fuse; upstream PSU/cable protection must be qualified.', '',
            'TVS screen: 25 C, 10/1000 us; no wire overshoot included.',
            'D901 SMBJ26CA: standoff 26 V >25 V; clamp 42.1 V at 14.3 A.',
            'Margin to LMR16020 input abs max 65 V: 22.9 V; to 50 V input capacitors: only 7.9 V.',
            f'AL8853 VIN static {vlo:.3f}..{vhi:.3f} V, no longer directly exposed to the input TVS clamp.',
            'D601 SMBJ30A: 48.4 V clamp vs Q601 60 V. Q521 AO3422: 55 V, SS36 cathode after F521.',
            'Pump VDS screen 42.1+0.75=42.85 V, 12.15 V margin before wiring overshoot.',
            'No electronic reverse protection; verify the assembled XT60 cable polarity.', '',
            'LMR16020 12 V auxiliary buck:',
            f'Divider 150k/10k 0.1%: {vo:.3f} V nominal, {vlo:.3f}..{vhi:.3f} V including FB temperature limits.',
            f'500 kHz nominal; L22uH/tolerance/bias/frequency scenario: ripple <= {max(c["ripple"] for c in buck):.3f} App; peak {peak:.3f} A.',
            '2.5 A minimum current limit is specified at 25 C; 3.8 A maximum <9 A stated inductor saturation point.',
            f'SS36 average <= {max(c["diode"] for c in buck):.3f} A; conduction screen <= {max(c["diode"] for c in buck)*.75:.3f} W.']
    # TI equations 12/13. Keep static divider tolerance in the fan +/-5% budget.
    delta=.25
    cu=3*aux_budget/fsmin/delta
    co=lmax*aux_budget**2/((vlo+delta)**2-vlo**2)
    cf={f.get('name'):f.text for f in comps['C909'].findall('fields/field')}
    assert cf.get('MPN')=='25SVPF100M','bulk capacitor model changed'
    # Initial -20% and an additional -20% endurance/model reserve; no credit for C910.
    # ESR x2 is a screening assumption, not a full temperature/endurance guarantee.
    c_eff,esr=100e-6*.8*.8,.024*2
    undershoot=3*aux_budget/fsmin/c_eff+aux_budget*esr
    ripple=max(c['ripple'] for c in buck)*(esr+1/(8*fsmin*c_eff))
    assert c_eff>max(cu,co) and vlo-undershoot-ripple/2>11.4 and vhi+undershoot+ripple/2<12.6
    out += [f'Full 0..1.2 A step, dynamic target 0.25 V: Ceff >= {cu*1e6:.1f} uF undershoot / {co*1e6:.1f} uF overshoot.',
            f'C909 25SVPF100M: 100uF/25V polymer; screening Ceff {c_eff*1e6:.1f}uF, ESR {esr*1000:.0f}mOhm; C910 22u ceramic retained.',
            f'No credit for ceramic capacitance: load-step drop screen {undershoot:.3f}V; ripple bound {ripple:.3f}Vpp.',
            'This clears the capacitance sizing screen, not the closed-loop/startup/thermal qualification.',
            'EN 560k/47k retained: start ~14.9 V; threshold-only envelope ~13.0..17.3 V. Current-source spread unqualified.',
            'Startup interaction, ESR, loop stability and thermal behavior require measurements.', '',
            'Switch conduction; hot x1.7 is a scenario, not a guaranteed bound:',
            f'Q601 2.4mOhm at VGS>=10 V: {ptc**2*.0024:.4f} W nominal; {cold**2*.0024:.4f} W cold; {cold**2*.0024*1.7:.4f} W hot scenario.',
            f'Q521 200mOhm at VGS=2.5 V: {pump**2*.2:.4f} W at 0.25 A; {pump_budget**2*.2*1.7:.4f} W at allowance/hot scenario.',
            'C602 CL21B475KAFNNNE: 4.7uF/25V, >=1uF effective target at 12.26 V; reviewed bias/tolerance/temperature screen ~1.29uF before aging.',
            'AL8853 gate drive at 12 V bias: verify VGS/fronts and MOSFET losses hot and at startup.',
            'Independent PTC thermal cutoff, fuse clearing, connector/PCB ampacity and hot TVS remain unqualified.']
    return '\n'.join(out)+'\n'


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('netlist',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    result=report(args.netlist)
    if args.output:args.output.write_text(result,encoding='utf-8')
    print(result,end='')
