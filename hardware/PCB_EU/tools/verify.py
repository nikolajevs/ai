#!/usr/bin/env python3
"""Verify the exported KiCad XML against the connection specification and key
functional invariants. This is not a circuit simulation or physical validation.
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('netlist',type=Path)
    ap.add_argument('--output',type=Path,default=HERE/'review/connectivity.txt')
    args = ap.parse_args()
    root = ET.parse(args.netlist).getroot()
    spec = json.loads((HERE/'design.json').read_text())
    bom = json.loads((HERE/'BOM_allocated.json').read_text())
    p = {x['ref']:x for x in spec['parts']}
    actual = {}
    nodes = defaultdict(set)
    for net in root.findall('./nets/net'):
        name = net.attrib['name']
        for n in net.findall('node'):
            key = (n.attrib['ref'],n.attrib['pin'])
            actual[key] = name;nodes[name].add(key)
    comp = {x.attrib['ref']:x for x in root.findall('./components/comp')}
    passed = []

    def check(label, condition):
        if not condition: raise AssertionError(label)
        passed.append(label)

    def n(ref,pin):
        return actual.get((ref,str(pin)))

    def pins(ref, expected):
        return all(n(ref,k)==v for k,v in expected.items())

    def r(ref,mpn,a,b):
        return p[ref]['mpn']==mpn and {n(ref,1),n(ref,2)}=={a,b}

    def val(ref):return p[ref]['value']

    expected = {(x['ref'],k):v for x in spec['parts'] for k,v in x['nets'].items() if v is not None and not x['ref'].startswith('#')}
    mismatches = [(k,v,actual.get(k)) for k,v in expected.items() if actual.get(k)!=v]
    unexpected = [k for k in actual if k[0] in p and not k[0].startswith('#') and p[k[0]]['nets'].get(k[1]) is None and not actual[k].startswith('unconnected-')]
    check('Every specified connected component pin matches the KiCad-exported net',not mismatches)
    check('All intended NC pins remain unconnected',not unexpected)
    check('No purchased component disappears during schematic export',all(x['ref'] in comp for x in spec['parts'] if x['in_bom']))
    nc_or_stub = [name for name,ns in nodes.items() if not name.startswith('unconnected-') and len(ns)<2]
    check('No one-pin orphan nets in exported design',not nc_or_stub)

    check('Input terminal polarity and main fuse precede the TVS',pins('J101',{1:'+24V_RAW',2:'PSU_RTN'}) and pins('F101',{1:'+24V_RAW',2:'+24V_FUSED'}) and pins('D101',{1:'+24V_FUSED',2:'GND'}))
    check('Reverse polarity: Q102 drain on PSU return, source on the shunt, gate divider keeps Vgs <= 20 V at the 42 V TVS clamp',pins('Q102',{1:'REVP_GATE',2:'PSU_RTN',3:'RTN_SHUNT'}) and r('R108','SMD1206 5K6 1%','+24V_FUSED','REVP_MID') and r('R109','SMD1206 5K6 1%','REVP_MID','REVP_GATE') and r('R110','SMD1206-10K-1%','REVP_GATE','GND') and 42*10/(10+5.6+5.6)<=20 and 21.6*10/(10+5.6+5.6)>=10 and {k for k in nodes['PSU_RTN']}=={('J101','2'),('Q102','2')})
    shunt=Decimal('0.01')/2
    check('Power monitor: INA226 U102 at I2C 0x40 (A0=A1=GND), 5 mOhm low-side shunt carries all return current, full scale >= 15 A main fuse',
          pins('U102',{1:'GND',2:'GND',4:'I2C_SDA',5:'I2C_SCL',6:'+3V3',7:'GND',8:'INA_VBUS',9:'RTN_SHUNT',10:'GND'}) and n('U102',3).startswith('unconnected-')
          and all(r(x,'SMD2512-0R01-1%-3W','GND','RTN_SHUNT') for x in ('R111','R112'))
          and {k for k in nodes['RTN_SHUNT']}=={('Q102','3'),('R111','2'),('R112','2'),('U102','9')}
          and Decimal('0.08192')/shunt>=15 and p['U102']['mpn']=='INA226AIDGSR')
    check('INA226 VBUS: 1k from +24V_FUSED, 33 V zener keeps the pin below 40 V at the 42 V TVS clamp; 100n on VS',
          r('R113','SMD0603-1K','+24V_FUSED','INA_VBUS') and pins('D103',{1:'INA_VBUS',2:'GND'}) and p['D103']['mpn']=='BZV55-C33'
          and {k for k in nodes['INA_VBUS']}=={('R113','2'),('U102','8'),('D103','1')} and 33*1.05+(42-33*1.05)*80/(1000+80)<40
          and {n('C115',1),n('C115',2)}=={'+3V3','GND'})
    fuse_expected={'F102':'+24V_PTC','F103':'+24V_LED1','F104':'+24V_LED2','F105':'+24V_AUX','F106':'+24V_PUMP'}
    check('All five 24 V load branches are separately fused',all(pins(ref,{1:'+24V_FUSED',2:net}) for ref,net in fuse_expected.items()))
    check('Fan branch fuse is on the 12 V rail',pins('F401',{1:'+12V',2:'+12V_FANS'}))
    check('AP63203 VIN and EN connect to 12 V; FB senses 3.3 V',pins('U201',{1:'+3V3',2:'+12V',3:'+12V',4:'GND',5:'LOGIC_SW',6:'LOGIC_BOOT'}))
    check('AP63203 bootstrap and LC output topology',pins('C203',{1:'LOGIC_BOOT',2:'LOGIC_SW'}) and pins('L201',{1:'LOGIC_SW',2:'+3V3'}))
    check('L7987 power, duplicated LX pins, EP and open-collector PGOOD',pins('U101',{1:'+12V',2:'+24V_AUX',3:'+24V_AUX',4:'+24V_AUX',5:'+24V_AUX',12:'BLOCK_OC',13:'AUX_SW',14:'AUX_SW',15:'AUX_BOOT',16:'GND',17:'GND'}))
    check('L7987 catch diode and bootstrap polarity/topology',pins('D102',{1:'AUX_SW',2:'GND'}) and pins('C108',{1:'AUX_BOOT',2:'AUX_SW'}))
    check('L7987 RF/CF series + CP across COMP/FB; Cout ESR resistor is retained',r('R105','SMD1206-3K9-1%','AUX_COMP','AUX_COMP_MID') and pins('C113',{1:'AUX_COMP_MID',2:'AUX_FB'}) and pins('C114',{1:'AUX_COMP',2:'AUX_FB'}) and pins('C112',{1:'+12V',2:'AUX_COUT_RETURN'}) and r('R101','SMD1206-0R1','AUX_COUT_RETURN','GND'))

    for k,b in [(1,500),(2,600)]:
        pre=f'LED{k}_';rf=lambda x,off:f'{x}{b+off}'
        check(f'LED{k}: VIN senses its own fused 24 V; nDIM is common',pins(rf('U',1),{1:f'+24V_LED{k}',7:'LED_NDIM',9:'GND',10:pre+'GATE_RAW',11:pre+'VCC',12:pre+'IS',13:pre+'HSP',14:pre+'HSN',15:'GND'}))
        check(f'LED{k}: RCT is fed from switching node through 56k + 6k2',r(rf('R',7),'SMD1206 56K 1%',pre+'SW',pre+'RT_MID') and r(rf('R',8),'SMD1206-6K2-1%',pre+'RT_MID',pre+'RCT'))
        check(f'LED{k}: rectifier, high-side LED shunt, equal Kelvin input filters',pins(rf('D',1),{1:pre+'OUT',2:pre+'SW'}) and pins(rf('R',2),{1:pre+'OUT',2:pre+'LED_POS'}) and r(rf('R',3),'SMD1206-1K-1%',pre+'OUT',pre+'HSP') and r(rf('R',4),'SMD1206-1K-1%',pre+'LED_POS',pre+'HSN'))
        check(f'LED{k}: MOS source is above IS shunt; drain is SW; LED return is GND',pins(rf('Q',1),{1:pre+'GATE',2:pre+'SW',3:pre+'IS'}) and pins(rf('R',1),{1:pre+'IS',2:'GND'}) and pins(rf('J',1),{1:pre+'LED_POS',2:'GND'}))
        check(f'LED{k}: OVP uses 33k+10k / 1k, 100p filter; COMP is separate 22u',r(rf('R',9),'SMD1206-33K-1%',pre+'OUT',pre+'OVP_MID') and r(rf('R',10),'SMD1206-10K-1%',pre+'OVP_MID',pre+'OVP') and r(rf('R',11),'SMD1206-1K-1%',pre+'OVP','GND') and pins(rf('C',7),{1:pre+'OVP',2:'GND'}) and p[rf('C',5)]['mpn']=='CL31A226KQHNNNE')
        check(f'LED{k}: every 63 V bulk capacitor is before the LED current shunt',all(n(ref,1)==pre+'OUT' and n(ref,2)=='GND' for ref,part in p.items() if part['sheet']==f'LED{k}' and part['mpn']=='EEUFR1J101LB'))
    check('LED1 has two series 10u coils; LED2 one 22u coil',pins('L501',{1:'+24V_LED1',2:'LED1_L_MID'}) and pins('L502',{1:'LED1_L_MID',2:'LED1_SW'}) and pins('L601',{1:'+24V_LED2',2:'LED2_SW'}))
    check('Shared nDIM has one 10k pull-down, a 5k6 GPIO series resistor and correct BAT54 polarity',r('R817','SMD0603-10K','LED_NDIM','GND') and r('R816','SMD1206 5K6 1%','LED_PWM_GPIO','LED_NDIM') and pins('D801',{1:'LED_NDIM',3:'BLOCK_OC'}) and len([1 for x in p.values() if x['symbol']=='R' and set(x['nets'].values())=={'LED_NDIM','GND'}])==1)
    check('No capacitor is attached to PWM nDIM',not any('LED_NDIM' in x['nets'].values() and x['symbol'] in ['C','CP'] for x in p.values()))
    check('Each LM3429 GATE drives only its own TK22E10N1 through 4R7; no external driver',all(p[q]['mpn']=='TK22E10N1' for q in ('Q501','Q601')) and r('R803','SMD2512-4R7','LED1_GATE_RAW','LED1_GATE') and r('R807','SMD2512-4R7','LED2_GATE_RAW','LED2_GATE') and 'U801' not in p and len(nodes['LED1_GATE_RAW'])==2 and len(nodes['LED2_GATE_RAW'])==2)
    check('UVLO positive feedback, valid unused comparator inputs, output tied to PGOOD',pins('U802',{1:'BLOCK_OC',2:'UVLO_REF',3:'UVLO_SENSE',4:'GND',5:'GND',6:'UVLO_REF',8:'+12V'}) and r('R812','SMD1206-1M-1%','BLOCK_OC','UVLO_SENSE') and r('R815','SMD0603-10K','+3V3','BLOCK_OC'))
    check('Both LED MOSFET gate pull-downs are 100k',all(r(f'R{no}','SMD0603-100K',net,'GND') for no,net in [(804,'LED1_GATE'),(808,'LED2_GATE')]))

    check('PTC driver defaults off, with separate NPN and PNP stages',pins('Q701',{1:'PTC_NPN_B',2:'GND',3:'PTC_NPN_C'}) and pins('Q702',{1:'PTC_PNP_B',2:'+12V',3:'PTC_DRV'}) and pins('Q703',{1:'PTC_GATE',2:'PTC_DRAIN',3:'GND'}) and r('R702','SMD1206 4K7 1%','PTC_NPN_B','GND') and r('R706','SMD1206-2K2-1%','PTC_GATE','GND'))
    # ESP32 internal pull-up is 45k typ; worst low value taken as 30k. Q701 needs Vbe ~0.6 V to conduct.
    check('PTC stays off with the ESP32 internal pull-up enabled on GPIO32 (R701 10k / R702 4k7)',3.6*4.7/(30+10+4.7)<0.45 and (3.3-0.7)/10-0.7/4.7>0.1)
    check('Pump AO3422: 1 gate / 2 source / 3 drain, reset pull-down and flyback polarity',pins('Q704',{1:'PUMP_GATE',2:'GND',3:'PUMP_DRAIN'}) and pins('D701',{1:'+24V_PUMP',2:'PUMP_DRAIN'}) and r('R708','SMD0603-100K','PUMP_GATE','GND'))
    for k,b in [(1,410),(2,420)]:
        pre=f'FAN{k}'
        check(f'Fan{k}: AO3422 source pin 2 grounded, reset gate pull-down and externally pulled tach',pins(f'Q{b+1}',{1:pre+'_GATE',2:'GND',3:pre+'_PWM'}) and r(f'R{b+2}','SMD0603-100K',pre+'_GATE','GND') and r(f'R{b+4}','SMD0603-10K','+3V3',pre+'_TACH'))
        check(f'Fan{k}: ST ESDA6V1L pin 3 common anode is grounded',pins(f'D{b+1}',{1:pre+'_PWM',2:pre+'_TACH_EXT',3:'GND'}))
        check(f'Fan{k}: one 4-pin PC fan header J{b+1}: 1 GND, 2 +12 V, 3 tach, 4 PWM',pins(f'J{b+1}',{1:'GND',2:'+12V_FANS',3:pre+'_TACH_EXT',4:pre+'_PWM'}) and p[f'J{b+1}']['mpn']=='KF2510-4A' and f'J{b+2}' not in p)
    check('SHT4x: one 4-pin XH header J401 (1 +3V3, 2 GND, 3 SDA, 4 SCL), USBLC6 U401 on SDA/SCL, R401/R402 in series',pins('J401',{1:'+3V3',2:'GND',3:'SHT_SDA',4:'SHT_SCL'}) and p['J401']['mpn']=='XH2.54-4P-90' and 'J402' not in p and pins('U401',{1:'SHT_SDA',6:'SHT_SDA',3:'SHT_SCL',4:'SHT_SCL'}) and r('R401','SMD1206-100R-1%','I2C_SDA','SHT_SDA') and r('R402','SMD1206-100R-1%','I2C_SCL','SHT_SCL'))
    check('USBLC6 reference and ground are correctly wired for both external interfaces',all(pins(ref,{2:'GND',5:'+3V3'}) for ref in ['U401','U402']))
    check('Float has series 1k, external pull-up and local filter',r('R403','SMD0603-1K','FLOAT_EXT','FLOAT_GPIO') and r('R404','SMD0603-10K','+3V3','FLOAT_GPIO') and pins('C403',{1:'FLOAT_GPIO',2:'GND'}))
    check('RTC battery is isolated from 3.3 V; MCP7940N pin 3 VBAT / pin 8 VCC',pins('U301',{1:'RTC_X1',2:'RTC_X2',3:'VBAT',4:'GND',5:'I2C_SDA',6:'I2C_SCL',8:'+3V3'}) and {(ref,pin) for ref,pin in nodes['VBAT'] if not ref.startswith('#')}=={('U301','3'),('BT301','1')})
    sd_lines=['SD_CS','SD_MOSI','SD_MISO','SD_DAT1','SD_DAT2']
    check('All five SD CMD/DAT lines have external 10k pull-ups',all(any(r(x['ref'],'SMD0603-10K','+3V3',net) for x in p.values() if x['symbol']=='R') for net in sd_lines))
    check('SD SPI pin mapping and shell ground follow GCT MEM2061 drawing',pins('J301',{1:'SD_DAT2',2:'SD_CS',3:'SD_MOSI',4:'+3V3',5:'SD_SCK',6:'GND',7:'SD_MISO',8:'SD_DAT1','SH':'GND'}))
    check('SD SCK/MOSI series 220R are present; DAT1/2 have no MCU connection',r('R301','SMD1206-220R-1%','SD_SCK_GPIO','SD_SCK') and r('R302','SMD1206-220R-1%','SD_MOSI_GPIO','SD_MOSI') and not any(n('U202',pin) in ['SD_DAT1','SD_DAT2'] for pin in range(1,40)))

    gpio={6:'FAN1_TACH',7:'FAN2_TACH',8:'PTC_GPIO',9:'PUMP_GPIO',10:'LED_PWM_GPIO',11:'FAN1_GPIO',12:'FAN2_GPIO',13:'FLOAT_GPIO',16:'SD_CS',25:'ESP_BOOT',30:'SD_SCK_GPIO',31:'SD_MISO',33:'I2C_SDA',34:'UART_RX',35:'UART_TX',36:'I2C_SCL',37:'SD_MOSI_GPIO'}
    check('ESP32 GPIO assignment and all four ground contacts are consistent',pins('U202',dict(gpio,**{'1':'GND','15':'GND','38':'GND','39':'GND','2':'+3V3','3':'ESP_EN'})))
    reserved=[14,17,18,19,20,21,22,23,24,29,32]
    check('ESP32 NC / flash pins and unused strapping pins are not externally loaded',all(p['U202']['nets'][str(i)] is None for i in reserved))
    check('UART service connector has explicit 3.3 V-only pin order',pins('J201',{1:'GND',2:'+3V3',3:'UART_TX',4:'UART_RX',5:'ESP_EN',6:'ESP_BOOT'}))
    check('BOOT / EN have external pull-ups and active-low buttons; EN delay 10k / 1u per Espressif',pins('C208',{1:'ESP_EN',2:'GND'}) and p['C208']['mpn']=='CL21B105KBFNNNG' and r('R201','SMD0603-10K','+3V3','ESP_EN') and r('R202','SMD0603-10K','+3V3','ESP_BOOT') and pins('SW201',{1:'ESP_EN',2:'GND'}) and pins('SW202',{1:'ESP_BOOT',2:'GND'}))
    allocated=Counter(x['mpn'] for x in spec['parts'] if x['in_bom'])+Counter(spec['accessories'])
    check('Every purchasing quantity is allocated to fitted references or assembly accessories',all(x['needed']==allocated[x['mpn']] and x['buy']>=x['needed'] for x in bom) and set(allocated)=={x['mpn'] for x in bom})
    check('No passive SMD footprint is smaller than 0603',all(not re.search(r'_(0201|0402)_',x['footprint']) for x in spec['parts'] if x['symbol'] in ['R','C','CP','L']))
    delivered=sum(Decimal(str(x['line'])) for x in bom)+Decimal('5.87')
    check('Purchased quantities + dated VAT and delivery estimate stay under the 100 EUR ceiling (target ~80 EUR)',delivered<=Decimal('100.00'))
    out=['EU-0.1 schematic connectivity review',f'Input: {args.netlist.name}',f'PASS: {len(passed)} checks',f'Exported electrical components: {sum(x["in_bom"] for x in spec["parts"])}',f'Specified connected pins checked: {len(expected)}',f'Procurement snapshot incl. VAT and delivery: {delivered:.2f} EUR','']
    out += [f'PASS {i+1:02d} | {label}' for i,label in enumerate(passed)]
    out += ['', 'Limitations: these checks establish pin/net and BOM consistency, not analog stability,',
            'power sequencing, component temperature, EMC/ESD immunity, or manufacturing readiness.',
            'Footprint qualification, <=100x100 placement, routing/DRC and new firmware remain pending.']
    args.output.write_text('\n'.join(out)+'\n')
    print('\n'.join(out[:6]))


if __name__=='__main__':main()
