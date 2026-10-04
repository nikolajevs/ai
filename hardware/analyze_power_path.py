"""v0.22 sizing from the netlist, not fault/surge/thermal qualification.
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
    expected = {'U902':'LMR16020PDDAR','R904':'150k 0.1%','R905':'10k 0.1%','R906':'47k 1%',
                'R907':'560k 1%','R908':'47k 1%','L902':'22u PSPMAA0604-220M','D902':'SS36-E3/57T',
                'D901':'SMBJ26CA-E3/52','D601':'SMBJ26CA-E3/52','Q601':'NTMFS5C628NLT1G',
                'U601':'UCC27524ADR','C901':'220u / 50V','F902':'10A mini blade (ATM)',
                'Q521':'AO3422','D521':'SS36-E3/57T','C602':'10u / 25V X5R',
                'C909':'100u 25V polymer','C910':'22u 25V X7R','C101':'22u 25V X7R',
                'R101':'100k 1%','R102':'22k 1%','L101':'10u FXL0630-100-M',
                'R205':'1k 1%','R206':'1k 1%'}
    for ref,value in expected.items():
        assert comps[ref].findtext('value') == value,(ref,'sizing does not match schematic')
    rtc_fields = {f.get('name'):f.text for f in comps['D303'].findall('fields/field')}
    assert comps['D303'].findtext('value') == 'BAV170' and rtc_fields.get('MPN') == 'BAV170'
    assert rtc_fields.get('Manufacturer') == 'JSCJ' and rtc_fields.get('LCSC') == 'C68970', 'RTC diode model is manufacturer-specific'
    assert comps['R307'].findtext('value').split()[0] == '1k', 'RTC battery series resistor changed'
    fuses = {'F501':(1,'0451001.MRL'),'F511':(1,'0451001.MRL'),'F521':(1,'0451001.MRL'),
             'F711':(6.3,'045106.3MRL'),'F721':(3,'0451003.MRL'),'F904':(3,'0451003.MRL')}
    for ref,(amps,mpn) in fuses.items():
        assert comps[ref].findtext('value') == f'{amps}A / {mpn}',ref
        fields = {f.get('name'):f.text for f in comps[ref].findall('fields/field')}
        assert fields.get('MPN') == mpn,(ref,'fuse MPN differs')
    vmin,vnom,vmax = VIN_CASES
    vo, vlo, vhi = 12., .735*(1+15*.999/1.001), .765*(1+15*1.001/.999)
    assert 11.4 < vlo < vhi < 12.6
    # TPS54202 Rev C: full-temperature VFB .581..611 V, R tolerance 1%.
    vlogic = .596*(1+100/22)
    logic_lo, logic_hi = .581*(1+100*.99/(22*1.01)), .611*(1+100*1.01/(22*.99))
    assert 3.0 < logic_lo < logic_hi < 3.6, 'ESP32/SD static supply range'
    # Initial load 1 A, L -20% tolerance and an additional -20% bias scenario;
    # minimum IC frequency 390 kHz. v0.20 cjiang FXL0630-100-M table at 25 C: Isat 4.9 A, Irms 3.8 A, DCR 68 mOhm max.
    logic_di = max((vi-v)*v/(vi*10e-6*.8*.8*390e3)
                   for vi,v in itertools.product((vlo,vhi),(logic_lo,logic_hi)))
    logic_peak = 1+logic_di/2
    logic_rms = math.sqrt(1+logic_di**2/12)
    assert logic_peak < 2.5 and logic_rms < 3.8 and 4.3 < 4.9
    # TI LMR16020 equation 4: RT[kOhm] = 42904 * f[kHz]**-1.088.
    fs_nom = (42904/47)**(1/1.088)*1000
    ptc,pump = 100/24,6/24
    cold = ptc*1.15
    # Lower-voltage constant-power screen is an assumption, not a PTC resistance model.
    ptc_screen = 100/vmin*1.15
    pump_budget = .5  # 2x nominal allowance; real stall/inrush still unknown
    fans,logic,bias = 8/vlo,logic_hi*1.0/.85/vlo,.03
    aux_budget = 1.2
    assert fans+logic+bias < aux_budget
    # v0.20 L902 PROD PSPMAA0604-220M-ANP: Isat 5 A (L -30%), Irms 3.2 A (dT 40 C), DCR 130 mOhm max.
    # Initial L -20%, extra bias -20%, conservative 450 kHz screen retained.
    # Not a guaranteed frequency tolerance at RT=47k (about 526 kHz nominal).
    lmin,lmax,fsmin = 22e-6*.8*.8,22e-6*1.2,450e3
    buck = []
    for vi,v in itertools.product(VIN_CASES,(vlo,vo,vhi)):
        di = (vi-v)*v/(vi*lmin*fsmin)
        # In CCM the winding carries output current throughout the cycle.
        # The input/switch current carries it only during D=Vout/Vin.
        # Keep the existing /eta input-screen allowance for F904, not L902.
        il_rms = math.sqrt(aux_budget**2+di**2/12)
        buck.append(dict(ripple=di,peak=aux_budget+di/2,
                         il_rms=il_rms,input_rms=math.sqrt(v/vi)*il_rms/.85,
                         diode=aux_budget*(1-v/vi)))
    peak = max(c['peak'] for c in buck)
    assert peak < 2.5,'aux peak exceeds specified 25 C limit minimum'
    aux_in,aux_rms = vhi*aux_budget/.85/vmin,max(c['input_rms'] for c in buck)
    inductor_rms = max(c['il_rms'] for c in buck)
    assert all(aux_budget <= c['il_rms'] <= c['peak'] for c in buck), 'CCM winding RMS must lie between mean and peak'
    assert inductor_rms < 3.2 and 3.8 < 5, 'L902 RMS rating or LMR16020 current limit vs Isat'
    cases = [[estimate(ch,*p) for p in itertools.product(VIN_CASES,(40,44,48),(110e3,130e3),(.85,.90),(False,True))] for ch in CHANNELS]
    led_mean = [max(c['average'] for c in cc) for cc in cases]
    led_rms = [max(c['il_rms'] for c in cc) for cc in cases]
    out = ['GrowBox v0.22 power path (24 V)',
           'Conditional datasheet calculations, NOT fault/surge/thermal qualification.',
           '24.0 V set point; power stages 21.6..25 V; AL8853 VIN pins use 12 V aux.', '',
           f'PTC 24 V/100 W: {ptc:.3f} A nominal; +15% cold at 24 V: {cold:.3f} A.',
           f'Pump confirmed 24 V/6 W: {pump:.3f} A; design allowance {pump_budget:.3f} A (not a measured stall limit).',
           f'Aux budget: fans {fans:.3f} + 3.3V/1A logic input {logic:.3f} + gate/controller bias {bias:.3f} = {fans+logic+bias:.3f} A.',
           f'Aux ceiling {aux_budget:.1f} A; input mean {aux_in:.3f} A; input RMS screen {aux_rms:.3f} A.',
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
            'D601 SMBJ26CA (shared with D901): standoff 26 V > 25 V drain off-state; clamp 42.1 V vs Q601 60 V.',
            'Q521 AO3422: 55 V, SS36 cathode after F521.',
            'Pump VDS screen 42.1+0.75=42.85 V, 12.15 V margin before wiring overshoot.',
            'No electronic reverse protection; verify the assembled XT60 cable polarity.', '',
            'LMR16020 12 V auxiliary buck:',
            f'Divider 150k/10k 0.1%: {vo:.3f} V nominal, {vlo:.3f}..{vhi:.3f} V including FB temperature limits.',
            f'RT 47k (shared with R703/R908): {fs_nom/1000:.1f} kHz nominal by TI eq.4; 450 kHz screening floor, not a guaranteed tolerance.',
            f'L22uH/tolerance/bias/frequency scenario: ripple <= {max(c["ripple"] for c in buck):.3f} App; peak {peak:.3f} A.',
            '2.5 A minimum current limit is specified at 25 C; 3.8 A maximum < 5 A Isat of PSPMAA0604-220M-ANP (L -30%).',
            f'L902 winding RMS screen {inductor_rms:.3f} A < 3.2 A (dT 40 C); DCR 130mOhm max: <= {inductor_rms**2*.13:.3f} W at 25C, '
            f'hot x1.4 scenario {inductor_rms**2*.13*1.4:.3f} W; core loss excluded.',
            'CCM winding RMS = sqrt(Iout^2 + ripple^2/12); input RMS is a separate F904 loading screen.',
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
    loose_lo,loose_hi=.735*(1+15*.99/1.01),.765*(1+15*1.01/.99)
    out += [f'0.1% divider retained: with 1% resistors the same step/ripple screen would span '
            f'{loose_lo-undershoot-ripple/2:.3f}..{loose_hi+undershoot+ripple/2:.3f} V, outside the 11.4..12.6 V fan budget.']
    out += [f'Full 0..1.2 A step, dynamic target 0.25 V: Ceff >= {cu*1e6:.1f} uF undershoot / {co*1e6:.1f} uF overshoot.',
            f'C909 25SVPF100M: 100uF/25V polymer; screening Ceff {c_eff*1e6:.1f}uF, ESR {esr*1000:.0f}mOhm; C910 22u ceramic retained.',
            f'No credit for ceramic capacitance: load-step drop screen {undershoot:.3f}V; ripple bound {ripple:.3f}Vpp.',
            'This clears the capacitance sizing screen, not the closed-loop/startup/thermal qualification.',
            'EN 560k/47k retained: start ~14.9 V; threshold-only envelope ~13.0..17.3 V. Current-source spread unqualified.',
            'Startup interaction, ESR, loop stability and thermal behavior require measurements.', '',
            'TPS54202 3.3 V logic buck (1 A budget):',
            f'Divider 100k/22k 1%: {vlogic:.3f} V nominal; {logic_lo:.3f}..{logic_hi:.3f} V static over FB limits.',
            'The static range excludes resistor temperature drift and load-step/ripple excursions; verify those on the prototype.',
            f'At L_eff 6.4uH / 390kHz: ripple <= {logic_di:.3f} App; peak {logic_peak:.3f} A; RMS {logic_rms:.3f} A.',
            'L101 FXL0630-100-M: Isat 4.9A at 25C exceeds TPS54202 HS/LS limits 3.9/4.3A (margin 0.6A); Irms 3.8A.',
            f'DCR 68mOhm max at 25C: <= {logic_rms**2*.068:.3f} W winding loss; hot x1.4 scenario {logic_rms**2*.068*1.4:.3f} W; core loss excluded.',
            'C101 and C910 share CL32B226KAJNNNE, 22uF/25V X7R 1210 on the regulated 12V rail.',
            'UART R205/R206 1k: RC 10..90% rise 0.220us at an assumed 100pF; 921600-baud bit 1.085us.',
            'Short programming cable only; actual cable capacitance/edges and flashing speed need validation.', '',
            'Switch conduction; hot x1.7 is a scenario, not a guaranteed bound:',
            f'Q601 2.4mOhm at VGS>=10 V: {ptc**2*.0024:.4f} W nominal; {cold**2*.0024:.4f} W cold; {cold**2*.0024*1.7:.4f} W hot scenario.',
            f'Q521 200mOhm at VGS=2.5 V: {pump**2*.2:.4f} W at 0.25 A; {pump_budget**2*.2*1.7:.4f} W at allowance/hot scenario.',
            'C602 CL21A106KAYNNNE (shared with C201): 10uF/25V X5R 0805; Samsung curve -81.7 % at 12.26 V = 1.83uF typ.;',
            'with -10 % tolerance and -14.6 % at 85 C ~1.41uF before aging, above the >=1uF target at the UCC27524A.',
            'AL8853 gate drive at 12 V bias: verify VGS/fronts and MOSFET losses hot and at startup.',
            'Q711/Q721 AOD66923: Qg 25nC typ at 10V, Qgd 3.5nC; gate charge power ~25nC x 12V x 130kHz = 0.039 W per AL8853.',
            'Independent PTC thermal cutoff, fuse clearing, connector/PCB ampacity and hot TVS remain unqualified.']
    # JSCJ/JCET BAV170, B Oct 2014: VF <=0.9 V at 1 mA, IR <=5 nA at 75 V, both at 25 C.
    # Use that forward drop as a conservative lower-current screen, not a full-temperature bound.
    # PCF8563: active IDD <=800uA at 400kHz; standby <=500nA at 3V/25C,
    # or <=1000nA before the first firmware boot disables the default CLKOUT.
    # Reserve 1uA for each SDA/SCL input, plus 5nA for the disabled supply diode.
    rtc_active,rtc_standby_reset,rtc_input_leak,diode_reverse = 800e-6,1000e-9,2e-6,5e-9
    assert rtc_active + rtc_input_leak + diode_reverse < 1e-3
    rtc_primary_min = logic_lo - .9
    battery_floor = 2.2  # engineering replacement floor at 25 C, not the CR2032 nominal voltage
    backup_current = rtc_standby_reset + rtc_input_leak + diode_reverse
    rtc_backup_min = battery_floor - .9 - backup_current*1000*1.01
    assert rtc_primary_min > 1.8 and rtc_backup_min > 1.0, 'RTC room-temperature supply screen'
    out += ['', 'PCF8563 backup supply, v0.21:',
            'D303 JSCJ BAV170 C68970: silicon common cathode A1/A2/K3, same SOT-23 footprint.',
            'JSCJ IR <=5nA at 75V/25C; no guaranteed hot leakage bound in the selected datasheet.',
            'VF 0.9V at 1mA used as a lower-current 25C screening drop; verify cold/hot and startup.',
            f'3.3V lower static corner {logic_lo:.3f}V -> RTC_VDD >= {rtc_primary_min:.3f}V in the screen; I2C minimum 1.8V.',
            f'Backup screening current {backup_current*1e6:.3f}uA (includes default CLKOUT before first boot and both input leakage reserves).',
            f'Assumed CR2032 replacement floor {battery_floor:.1f}V, R307 1k+1% -> RTC_VDD >= {rtc_backup_min:.3f}V; timekeeping minimum 1.0V at 25C.',
            'No forced supply priority; fresh battery can contribute while the board is powered.',
            'Not a cell charging/lifetime qualification: verify both battery current polarities and supply transitions.']
    return '\n'.join(out)+'\n'


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('netlist',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    result=report(args.netlist)
    if args.output:args.output.write_text(result,encoding='utf-8')
    print(result,end='')
