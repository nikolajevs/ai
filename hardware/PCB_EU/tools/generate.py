#!/usr/bin/env python3
"""Generate the EU prototype schematic and its allocated BOM (Python >=3.10).

The schematic is the output of this explicit pin/net specification. No old PCB
or old manufacturer's footprint is reused. Do not rerun after editing in KiCad
without first incorporating the manual changes here. SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import csv
import json
import math
import uuid
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
NS = uuid.UUID('865e0545-a87e-45f2-a7d8-a1903e95df04')
ROOT = 'PCB_EU'
REV = 'EU-0.1-DRAFT'
DATE = '2026-10-20'
parts = []
sheets = {}
symbols = {}
counts = Counter()
MECHANICAL = json.loads((HERE/'footprint_assignments.json').read_text())['assignments']


def uid(*args):
    return str(uuid.uuid5(NS, '/'.join(map(str, args))))


def q(x):
    return json.dumps(str(x), ensure_ascii=False)


def num(x):
    return f'{x:.4f}'.rstrip('0').rstrip('.') if x else '0'


def effects(size=1, extra=''):
    return f'(effects (font (size {size} {size})) {extra})'


def prop(key, val, x=0, y=0, hide=True, size=1):
    return f'(property {q(key)} {q(val)} (at {num(x)} {num(y)} 0) {effects(size, "(hide yes)" if hide else "")})'


def sheet(name, title, notes, chip_area=0):
    sheets[name] = dict(title=title, notes=notes, chip_area=chip_area, parts=[])


def pin(n, name, side='L', typ='passive'):
    return dict(number=str(n), name=name, side=side, typ=typ)


def ic(name, left, right, width=25.4):
    """Each side uses 2.54 mm pitch; explicit physical pin numbers are mandatory."""
    pp = []
    n = max(len(left), len(right))
    height = (n + 1) * 2.54
    for side, seq in [('L', left), ('R', right)]:
        for k, item in enumerate(seq):
            p = pin(*item, side=side) if len(item) == 2 else pin(item[0], item[1], side, item[2])
            p.update(x=-(width/2+5.08) if side == 'L' else width/2+5.08,
                     y=height/2 - 2.54*(k+1), angle=0 if side == 'L' else 180)
            pp.append(p)
    symbols[name] = dict(name=name, pins=pp, width=width, height=height, kind='ic')
    return name


def primitive(name, kind, ps):
    symbols[name] = dict(name=name, kind=kind, width=10.16, height=5.08, pins=[])
    for no, nm, x, y, angle, typ in ps:
        symbols[name]['pins'].append(dict(number=str(no), name=nm, x=x, y=y, angle=angle, typ=typ))


for name, kind in [('R','r'),('C','c'),('CP','cp'),('L','l'),('F','f'),('D','d'),('TVS','tvs'),('SW','sw'),('Y','y'),('BAT','bat')]:
    primitive(name, kind, [(1,'K' if name in ['D','TVS'] else '~',-7.62,0,0,'passive'),
                           (2,'A' if name in ['D','TVS'] else '~',7.62,0,180,'passive')])
primitive('NMOS', 'nmos', [(1,'G',-5.08,0,0,'input'),(2,'D',2.54,5.08,270,'passive'),(3,'S',2.54,-5.08,90,'passive')])
primitive('NMOS_GSD', 'nmos', [(1,'G',-5.08,0,0,'input'),(2,'S',2.54,-5.08,90,'passive'),(3,'D',2.54,5.08,270,'passive')])
primitive('NPN', 'npn', [(1,'B',-7.62,0,0,'input'),(2,'E',5.08,-5.08,90,'passive'),(3,'C',5.08,5.08,270,'passive')])
primitive('PNP', 'pnp', [(1,'B',-7.62,0,0,'input'),(2,'E',5.08,5.08,270,'passive'),(3,'C',5.08,-5.08,90,'passive')])
primitive('FLAG', 'flag', [(1,'PWR',0,0,90,'power_out')])
primitive('TP', 'tp', [(1,'PAD',0,0,90,'passive')])

ic('L7987', [(2,'VIN','power_in'),(3,'VIN','power_in'),(4,'VCC','power_in'),(5,'EN','input'),
             (6,'SS','passive'),(7,'SYNCH','bidirectional'),(8,'COMP','passive'),(9,'FB','input'),(10,'FSW','passive'),(11,'ILIM','passive')],
            [(1,'VBIAS','power_in'),(15,'BOOT','passive'),(13,'LX','output'),(14,'LX','passive'),(12,'PGOOD','open_collector'),(16,'GND','power_in'),(17,'EP_GND','power_in')],30.48)
ic('AP63203',[(3,'VIN','power_in'),(2,'EN','input'),(4,'GND','power_in')],[(6,'BST','passive'),(5,'SW','output'),(1,'FB','input')])
ic('LM3429',[(1,'VIN','power_in'),(2,'COMP','passive'),(3,'CSH','passive'),(4,'RCT','passive'),(5,'AGND','power_in'),(6,'OVP','input'),(7,'nDIM','input')],
            [(14,'HSN','input'),(13,'HSP','input'),(12,'IS','input'),(11,'VCC','power_out'),(10,'GATE','output'),(9,'PGND','power_in'),(8,'NC','no_connect'),(15,'EP_GND','power_in')],30.48)
ic('TC4427A',[(2,'INA','input'),(4,'INB','input'),(1,'NC','no_connect'),(8,'NC','no_connect')],[(7,'OUTA','output'),(5,'OUTB','output'),(6,'VDD','power_in'),(3,'GND','power_in')])
ic('LM2903',[(3,'IN1+','input'),(2,'IN1-','input'),(5,'IN2+','input'),(6,'IN2-','input')],[(1,'OUT1','open_collector'),(7,'OUT2','open_collector'),(8,'VCC','power_in'),(4,'GND','power_in')])
ic('MCP7940N',[(1,'X1','passive'),(2,'X2','passive'),(3,'VBAT','power_in'),(4,'VSS','power_in')],[(8,'VCC','power_in'),(7,'MFP','open_collector'),(6,'SCL','input'),(5,'SDA','bidirectional')])
ic('USBLC6',[(1,'IO1','passive'),(3,'IO2','passive'),(2,'GND','power_in')],[(6,'IO1','passive'),(4,'IO2','passive'),(5,'VREF','power_in')])
ic('ESDAL',[(1,'K1','passive'),(2,'K2','passive')],[(3,'A_COMMON','power_in')])
ic('BAT54',[(1,'A','passive'),(2,'NC','no_connect')],[(3,'K','passive')])
ic('INA226',[(10,'IN+','input'),(9,'IN-','input'),(8,'VBUS','input'),(1,'A1','input'),(2,'A0','input')],
            [(6,'VS','power_in'),(4,'SDA','bidirectional'),(5,'SCL','input'),(3,'ALERT','open_collector'),(7,'GND','power_in')])
ic('SD',[(1,'DAT2','passive'),(2,'DAT3_CS','input'),(3,'CMD_MOSI','input'),(4,'VDD','power_in'),(5,'CLK','input')],
        [(8,'DAT1','passive'),(7,'DAT0_MISO','tri_state'),(6,'VSS','power_in'),('SH','SHELL','passive'),('CD1','CARD_DETECT_1','passive'),('CD2','CARD_DETECT_2','passive')],30.48)
for n in [2,4,6]:
    ic(f'J{n}',[(i,str(i),'passive') for i in range(1,n+1)],[],10.16)
esp = [(1,'GND','power_in'),(2,'3V3','power_in'),(3,'EN','input'),(4,'GPIO36','input'),(5,'GPIO39','input'),
       (6,'GPIO34','input'),(7,'GPIO35','input'),(8,'GPIO32','bidirectional'),(9,'GPIO33','bidirectional'),
       (10,'GPIO25','bidirectional'),(11,'GPIO26','bidirectional'),(12,'GPIO27','bidirectional'),(13,'GPIO14','bidirectional'),
       (14,'GPIO12','bidirectional'),(15,'GND','power_in'),(16,'GPIO13','bidirectional'),(17,'NC','no_connect'),(18,'NC','no_connect'),(19,'NC','no_connect'),(39,'GND_EP','power_in')]
er = [(38,'GND','power_in'),(37,'GPIO23','bidirectional'),(36,'GPIO22','bidirectional'),(35,'GPIO1_TXD0','bidirectional'),(34,'GPIO3_RXD0','bidirectional'),
      (33,'GPIO21','bidirectional'),(32,'NC','no_connect'),(31,'GPIO19','bidirectional'),(30,'GPIO18','bidirectional'),(29,'GPIO5','bidirectional'),
      (28,'GPIO17','bidirectional'),(27,'GPIO16','bidirectional'),(26,'GPIO4','bidirectional'),(25,'GPIO0_BOOT','bidirectional'),(24,'GPIO2','bidirectional'),
      (23,'GPIO15','bidirectional'),(22,'NC','no_connect'),(21,'NC','no_connect'),(20,'NC','no_connect')]
ic('ESP32',esp,er,35.56)

FP_R = 'Resistor_SMD:R_1206_3216Metric'
FP_C = 'Capacitor_SMD:C_1206_3216Metric'
FP_0805 = 'Capacitor_SMD:C_0805_2012Metric'
FP_DIG = 'Resistor_SMD:R_0603_1608Metric'
FP_SHT = 'Connector_JST:JST_XH_S4B-XH-A_1x04_P2.50mm_Horizontal'
FP_FAN = 'Connector_Molex:Molex_KK-254_AE-6410-04A_1x04_P2.54mm_Vertical'
P = 'power_in'


def add(sh, ref, sym, value, mpn, nets, fp='', note='', pos=None, bom=True):
    if not fp and mpn in MECHANICAL: fp = MECHANICAL[mpn]['footprint']
    pd = {str(k):v for k,v in (nets.items() if isinstance(nets,dict) else enumerate(nets,1))}
    expected = {x['number'] for x in symbols[sym]['pins']}
    if set(pd) != expected:
        raise ValueError((ref, 'pin map differs',set(pd)^expected))
    assert ref not in {c['ref'] for c in parts}, ref
    c=dict(sheet=sh, ref=ref, symbol=sym, value=value, mpn=mpn, nets=pd, footprint=fp,
           note=note, position=pos, in_bom=bom)
    parts.append(c);sheets[sh]['parts'].append(c)
    if mpn and bom:counts[mpn]+=1
    return c


def r(sh,ref,val,mpn,a,b,note='',pos=None):
    fp=FP_DIG if '0603' in mpn else ('Resistor_SMD:R_2512_6332Metric' if '2512' in mpn else FP_R)
    return add(sh,ref,'R',val,mpn,[a,b],fp,note,pos)


def c(sh,ref,val,mpn,a,b='GND',pos=None):
    if mpn=='UPW1H221MPD':fp='Capacitor_THT:CP_Radial_D10.0mm_P5.00mm'
    elif mpn=='EEUFR1E102':fp='Capacitor_THT:CP_Radial_D10.0mm_P5.00mm'
    elif mpn=='EEUFR1J101LB':fp='Capacitor_THT:CP_Radial_D8.0mm_P5.00mm'
    else:fp=FP_0805 if mpn.startswith(('CL21','C0805')) else FP_C
    return add(sh,ref,'CP' if mpn.startswith(('UPW','EEU')) else 'C',val,mpn,[a,b],fp,pos=pos)


R1='SMD1206-1K-1%';R10='SMD1206-10K-1%';R100='SMD1206-100R-1%'
D1='SMD0603-1K';D10='SMD0603-10K';D100='SMD0603-100K'
C100='CL21B104KBCNNNC';C1='CL21B105KBFNNNG';C22='CL31A226KQHNNNE';C10='CL31A106KAHNNNE'
GND='GND';V3='+3V3';V12='+12V';V24='+24V_FUSED'

sheet('InputPower','01 | 24 V input and 12 V auxiliary supply',[
 'External PSU 24.0 V, max 25 V, at least 240 W / 10 A. J101: 1 = +24 V, 2 = PSU return.',
 'Reverse polarity: Q102 IRF1010ES in the return path; drain = J101.2, source = RTN_SHUNT.',
 'Power monitor: R111||R112 = 5 mOhm from board GND to Q102 source; INA226 U102 at I2C 0x40 (A0=A1=GND).',
 'U102 IN+ (pin 10) is a Kelvin tap on the GND pad of R111 and has no own ground via or pour connection.',
 'U102 VBUS: R113 1k + D103 33 V zener, because the SMBJ26A clamp (42 V) exceeds the INA226 40 V rating.',
 'Q102 gate divider 5k6+5k6 / 10k from +24V_FUSED: Vgs 10.2 V at 21.6 V, 19.8 V at 42 V TVS clamp.',
 'Programmer/USB ground must never become the power return. Fuse coordination NOT qualified.',
 'L7987 is the 3 A part. VCC is on 24 V; VBIAS is on the regulated 12 V rail.',
 'RF + CF series from COMP to FB; CP across the complete RF/CF network.',
 'C112 has 0.1 ohm in series to GND. This is deliberate compensation damping.'
],95)
add('InputPower','J101','J2','24 V IN','DG301R-5.0-2P12',['+24V_RAW','PSU_RTN'],note='DG301R-C02 T1 drawing; UL 15 A / IEC 17.5 A; confirm ordered suffix matches drawing')
fuses=[('F101','15 A slow','3413.0330.11','+24V_RAW',V24),('F102','8 A slow','3413.0327.11',V24,'+24V_PTC'),
       ('F103','6.3 A slow','3413.0224.11',V24,'+24V_LED1'),('F104','2 A slow','3403.0169.11',V24,'+24V_LED2'),
       ('F105','2 A slow','3403.0169.11',V24,'+24V_AUX'),('F106','1 A slow','3403.0166.11',V24,'+24V_PUMP')]
for ref,val,mpn,a,b in fuses:add('InputPower',ref,'F',val,mpn,[a,b],note='SCHURTER reflow lands checked; fuse clearing I2t/coordination remain unqualified')
add('InputPower','D101','TVS','SMBJ26A','SMBJ26A-E3/52',[V24,GND],'Diode_SMD:D_SMB')
add('InputPower','Q102','NMOS','IRF1010ESPBF','IRF1010ESPBF',{1:'REVP_GATE',2:'PSU_RTN',3:'RTN_SHUNT'},'Package_TO_SOT_SMD:TO-263-2',note='Reverse-polarity switch in the 24 V return. Tab = DRAIN = PSU_RTN; body diode conducts until the gate is enhanced',pos=(265,200))
r('InputPower','R108','5k6 1%','SMD1206 5K6 1%',V24,'REVP_MID')
r('InputPower','R109','5k6 1%','SMD1206 5K6 1%','REVP_MID','REVP_GATE')
r('InputPower','R110','10k 1%',R10,'REVP_GATE',GND)
c('InputPower','C101','220u 50V','UPW1H221MPD',V24)
add('InputPower','U101','L7987','L7987 3A','L7987',{1:V12,2:'+24V_AUX',3:'+24V_AUX',4:'+24V_AUX',5:'+24V_AUX',6:'AUX_SS',7:None,8:'AUX_COMP',9:'AUX_FB',10:'AUX_FSW',11:'AUX_ILIM',12:'BLOCK_OC',13:'AUX_SW',14:'AUX_SW',15:'AUX_BOOT',16:GND,17:GND},note='ST HTSSOP16 EP17=GND; 3x3 EP and 0.65 pitch; assembly and thermal vias pending',pos=(90,60))
add('InputPower','L101','L','33u','JNRH1207-330M-A',['AUX_SW',V12],note='Jantek SP-N251224012 rev A lands checked; hot Isat remains prototype check')
add('InputPower','D102','D','SS510 100V','SS510-YAN',['AUX_SW',GND],'Diode_SMD:D_SMC')
c('InputPower','C102','220u 50V','UPW1H221MPD','+24V_AUX')
for n in range(103,107):c('InputPower',f'C{n}','1u 50V',C1,'+24V_AUX')
c('InputPower','C107','100n 50V',C100,'+24V_AUX')
c('InputPower','C108','100n BOOT',C100,'AUX_BOOT','AUX_SW')
c('InputPower','C109','1u 50V',C1,V12)
c('InputPower','C110','1u 50V',C1,V12)
c('InputPower','C111','1u SS',C1,'AUX_SS')
c('InputPower','C112','1000u 25V','EEUFR1E102',V12,'AUX_COUT_RETURN')
r('InputPower','R101','0R1 5%','SMD1206-0R1','AUX_COUT_RETURN',GND)
r('InputPower','R102','10k 1%',R10,V12,'AUX_FB_MID')
r('InputPower','R103','3k9 1%','SMD1206-3K9-1%','AUX_FB_MID','AUX_FB')
r('InputPower','R104','1k 1%',R1,'AUX_FB',GND)
r('InputPower','R105','3k9 RF','SMD1206-3K9-1%','AUX_COMP','AUX_COMP_MID')
c('InputPower','C113','1u CF',C1,'AUX_COMP_MID','AUX_FB')
c('InputPower','C114','330p C0G','CC1206JRNPO9331','AUX_COMP','AUX_FB')
r('InputPower','R106','27k 1%','SMD1206-27K-1%','AUX_ILIM',GND)
r('InputPower','R107','68k 5%','SMD1206-68K','AUX_FSW',GND)
# Low-side power monitor: all board return current flows GND -> R111||R112 -> Q102 source.
r('InputPower','R111','0R01 3W 1%','SMD2512-0R01-1%-3W',GND,'RTN_SHUNT','Shunt for U102; pad 1 = board GND side (Kelvin IN+), pad 2 = Q102 source side (IN-)',pos=(165,95))
r('InputPower','R112','0R01 3W 1%','SMD2512-0R01-1%-3W',GND,'RTN_SHUNT','Parallel with R111: 5 mOhm, 81.92 mV full scale = 16.4 A',pos=(165,112))
add('InputPower','U102','INA226','INA226','INA226AIDGSR',{1:GND,2:GND,3:None,4:'I2C_SDA',5:'I2C_SCL',6:V3,7:GND,8:'INA_VBUS',9:'RTN_SHUNT',10:GND},'Package_SO:VSSOP-10_3x3mm_P0.5mm',note='I2C 0x40. IN+ Kelvin to R111.1, IN- Kelvin to R111.2; bus = +24V_FUSED through R113',pos=(240,75))
r('InputPower','R113','1k VBUS',D1,V24,'INA_VBUS','Limits current into VBUS above 40 V; 0.12% gain error with the 830k VBUS input',pos=(310,75))
c('InputPower','C115','100n VS',C100,V3,pos=(310,95))
add('InputPower','D103','TVS','33V zener','BZV55-C33',['INA_VBUS',GND],'Diode_SMD:D_MiniMELF',note='Keeps VBUS below its 40 V absolute maximum when D101 clamps up to 42 V; R113 limits the current. 31-35 V, no conduction at 25 V',pos=(310,112))

sheet('MCU','02 | 3.3 V supply and ESP32',[
 'AP63203 is supplied from +12V only. Raw 24 V / TVS-clamped input is prohibited.',
 '6.8 uH in AP63203 output is a cost selection requiring transient/stability verification.',
 'GPIO34/35 are input-only. Boot strapping pins 2, 5, 12, 15 have no external loads.',
 'ESP32 pins 17-22 and 32 are NC on this module; do not expose flash signals.',
 'J201 UART is 3.3 V logic: 1 GND, 2 3V3_REF, 3 TX, 4 RX, 5 EN, 6 BOOT.',
 'Programmer power is not a board supply. Keep its VCC disconnected while PSU powers the board.'
],110)
add('MCU','U201','AP63203','AP63203WU-7','AP63203WU-7',{1:V3,2:V12,3:V12,4:GND,5:'LOGIC_SW',6:'LOGIC_BOOT'},'Package_TO_SOT_SMD:TSOT-23-6',pos=(80,45))
add('MCU','L201','L','6u8','SRN6045-6R8Y',['LOGIC_SW',V3],note='Bourns SRN6045 lands checked; not the TA variant; stability remains prototype check')
c('MCU','C201','10u 25V',C10,V12)
c('MCU','C202','10u 25V',C10,V12)
c('MCU','C203','100n BOOT',C100,'LOGIC_BOOT','LOGIC_SW')
c('MCU','C204','22u 6.3V',C22,V3)
c('MCU','C205','22u 6.3V',C22,V3)
en={str(i):None for i in range(1,40)}
en.update({'1':GND,'2':V3,'3':'ESP_EN','6':'FAN1_TACH','7':'FAN2_TACH','8':'PTC_GPIO','9':'PUMP_GPIO','10':'LED_PWM_GPIO','11':'FAN1_GPIO','12':'FAN2_GPIO','13':'FLOAT_GPIO','15':GND,'16':'SD_CS','25':'ESP_BOOT','30':'SD_SCK_GPIO','31':'SD_MISO','33':'I2C_SDA','34':'UART_RX','35':'UART_TX','36':'I2C_SCL','37':'SD_MOSI_GPIO','38':GND,'39':GND})
add('MCU','U202','ESP32','ESP32-WROOM-32E-N4','ESP32-WROOM-32E-N4',en,'EU_Parts:ESP32-WROOM-32E_NoVias',note='Antenna keepout and GND pad 39 mandatory',pos=(285,69))
c('MCU','C206','22u 6.3V',C22,V3)
c('MCU','C207','100n',C100,V3)
c('MCU','C208','1u RESET',C1,'ESP_EN')
r('MCU','R201','10k',D10,V3,'ESP_EN')
r('MCU','R202','10k',D10,V3,'ESP_BOOT')
add('MCU','SW201','SW','RESET','TACTB-64K-F',['ESP_EN',GND],note='4 physical button leads form two internally common pairs')
add('MCU','SW202','SW','BOOT','TACTB-64K-F',['ESP_BOOT',GND])
add('MCU','J201','J6','UART 3V3','ZL2019-20',[GND,V3,'UART_TX','UART_RX','ESP_EN','ESP_BOOT'],'Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical',note='Cut 6 of purchased 20 header positions; 14 spare')

sheet('Peripherals','03 | RTC, battery and microSD',[
 'MCP7940N: I2C 0x6F; old PCF8563/DS3231 firmware is incompatible.',
 'Firmware must set oscillator ST and backup VBATEN bits and validate time before schedules.',
 'CR2032 is not rechargeable. No path from +3V3 to VBAT; MFP is unused.',
 'SD uses SPI; CMD and DAT0..DAT3 all have 10k pull-ups, including unused DAT1/2.',
 'GCT drawing Rev A1: shell is ground; normally closed detect contact is unused.',
 'CD1/CD2 are separate unused contact pads; both SH ground tabs are grounded. Preserve socket keepout.',
 'Initial SD speed 2-4 MHz with 220R SCK/MOSI; validate with the actual card.'
],85)
add('Peripherals','U301','MCP7940N','MCP7940N-I/SN','MCP7940N-I/SN',{1:'RTC_X1',2:'RTC_X2',3:'VBAT',4:GND,5:'I2C_SDA',6:'I2C_SCL',7:None,8:V3},'Package_SO:SOIC-8_3.9x4.9mm_P1.27mm',pos=(75,60))
add('Peripherals','Y301','Y','32.768k CL7p','ABS07-32.768KHZ-7-T',['RTC_X1','RTC_X2'],note='Crystal ESR/load/drive to verify on prototype')
c('Peripherals','C301','10p C0G','C1206C100J5GAC','RTC_X1')
c('Peripherals','C302','10p C0G','C1206C100J5GAC','RTC_X2')
c('Peripherals','C303','100n',C100,V3)
add('Peripherals','BT301','BAT','CR2032 + BC-2001','BC-2001',['VBAT',GND],note='COMF BC-2001: side pads 1 positive; centre pad 2 negative, no paste; durable plated finish and physical fit required')
add('Peripherals','J301','SD','MEM2061 SPI','MEM2061-01-188-00-A',{1:'SD_DAT2',2:'SD_CS',3:'SD_MOSI',4:V3,5:'SD_SCK',6:GND,7:'SD_MISO',8:'SD_DAT1','SH':GND,'CD1':None,'CD2':None},note='GCT MEM2061 A1: without pegs; separate CD1/CD2 pads unused; both SH tabs GND; preserve contact keepout and card access',pos=(280,60))
c('Peripherals','C304','22u 6.3V',C22,V3)
c('Peripherals','C305','100n',C100,V3)
r('Peripherals','R301','220R','SMD1206-220R-1%','SD_SCK_GPIO','SD_SCK')
r('Peripherals','R302','220R','SMD1206-220R-1%','SD_MOSI_GPIO','SD_MOSI')
for n,net in enumerate(['SD_CS','SD_MOSI','SD_MISO','SD_DAT1','SD_DAT2'],303):r('Peripherals',f'R{n}','10k',D10,V3,net)
r('Peripherals','R308','4k7 1%','SMD1206 4K7 1%',V3,'I2C_SDA')
r('Peripherals','R309','4k7 1%','SMD1206 4K7 1%',V3,'I2C_SCL')

sheet('Interfaces','04 | SHT4x, float and two 4-wire fans',[
 'Both fans combined <=10 W at 12 V; combined fuse 2 A. Start currents not measured.',
 'Fan PWM = open drain, 25 kHz. MCU HIGH pulls fan PWM LOW: invert firmware duty.',
 'Reset / Hi-Z opens PWM MOSFETs: fans run at full speed while +12V is present.',
 'Tach outputs must be open collector/open drain. GPIO34/35 have external 10k pull-ups.',
 'ESDA6V1L: pins 1/2 are protected cathodes, pin 3 is common anode -> GND.',
 'USBLC6: 1=6 IO1; 3=4 IO2; 2 GND; 5 +3V3. Place at connector, before series resistors.',
 'Float J403 closed -> GPIO14 LOW. Firmware water-present polarity must follow wiring.',
 'J411/J421 fan headers: 1 GND, 2 +12 V, 3 tach, 4 PWM (standard 4-pin PC fan order).',
 'J401 SHT4x header XH2.54-4P-90: 1 +3V3, 2 GND, 3 SDA, 4 SCL. Confirm the wire order of the sensor cable.',
 'SHT4x module is external. No 5 V sensor or push-pull tach on these 3.3 V inputs.'
],110)
# External SHT4x on one right-angle XH 4-pin header since 2026-10-22 (was two screw terminals J401/J402).
add('Interfaces','J401','J4','SHT4x XH2.54-4P-90','XH2.54-4P-90',[V3,GND,'SHT_SDA','SHT_SCL'],FP_SHT,
    note='1 +3V3, 2 GND, 3 SDA, 4 SCL. XH clone, right angle; real pitch is the JST XH 2.50 mm; check pitch and wire order of the purchased part and the sensor cable')
add('Interfaces','J403','J2','FLOAT / GND','DG306-5.0-2P12',['FLOAT_EXT',GND])
r('Interfaces','R401','100R',R100,'I2C_SDA','SHT_SDA')
r('Interfaces','R402','100R',R100,'I2C_SCL','SHT_SCL')
add('Interfaces','U401','USBLC6','USBLC6-2SC6','USBLC6-2SC6',{1:'SHT_SDA',6:'SHT_SDA',3:'SHT_SCL',4:'SHT_SCL',2:GND,5:V3},'Package_TO_SOT_SMD:SOT-23-6',pos=(65,45))
c('Interfaces','C401','100n',C100,V3)
add('Interfaces','U402','USBLC6','USBLC6-2SC6','USBLC6-2SC6',{1:'FLOAT_EXT',6:'FLOAT_EXT',3:None,4:None,2:GND,5:V3},'Package_TO_SOT_SMD:SOT-23-6',pos=(195,45))
c('Interfaces','C402','100n',C100,V3)
r('Interfaces','R403','1k',D1,'FLOAT_EXT','FLOAT_GPIO')
r('Interfaces','R404','10k',D10,V3,'FLOAT_GPIO')
c('Interfaces','C403','100n FILTER',C100,'FLOAT_GPIO')
add('Interfaces','F401','F','2 A slow','3403.0169.11',[V12,'+12V_FANS'])
for k in (1,2):
    i=410 if k==1 else 420
    sh='Interfaces';prefix=f'FAN{k}'
    # 4-pin PC fan header (KF2510 / Molex KK-254 style, 2.54 mm): the fans come with this plug.
    add(sh,f'J{i+1}','J4',f'FAN{k} 2510-4P','KF2510-4A',[GND,'+12V_FANS',prefix+'_TACH_EXT',prefix+'_PWM'],FP_FAN,
        note='4-pin PC fan pinout: 1 GND, 2 +12 V, 3 tach, 4 PWM. KF2510 header matches Molex KK-254; confirm against the purchased part')
    add(sh,f'Q{i+1}','NMOS_GSD',f'FAN{k} AO3422','AO3422',{1:prefix+'_GATE',2:GND,3:prefix+'_PWM'},'Package_TO_SOT_SMD:SOT-23',pos=(65 if k==1 else 195,100))
    r(sh,f'R{i+1}','1k GATE',D1,prefix+'_GPIO',prefix+'_GATE','Uses spare from purchased pack; 25 kHz edge timing must be checked')
    r(sh,f'R{i+2}','100k',D100,prefix+'_GATE',GND)
    r(sh,f'R{i+3}','1k TACH',D1,prefix+'_TACH_EXT',prefix+'_TACH')
    r(sh,f'R{i+4}','10k',D10,V3,prefix+'_TACH')
    add(sh,f'D{i+1}','ESDAL','ESDA6V1L','ESDA6V1L',{1:prefix+'_PWM',2:prefix+'_TACH_EXT',3:GND},'Package_TO_SOT_SMD:SOT-23',pos=(315,45 if k==1 else 100))

for k in (1,2):
    sh=f'LED{k}';base=500 if k==1 else 600;pre=f'LED{k}_';vin=f'+24V_LED{k}'
    sheet(sh,f'0{k+4} | LED boost channel {k}',[
      f'CH{k}: '+('panel ~1.117 A nominal, screening 1.25 A.' if k==1 else 'two parallel bars ~0.464 A total, screening 0.52 A.'),
      'LM3429 VIN senses the actual 24 V input. Both RCT resistors start at SW, not VIN.',
      'HSP/HSN use equal 1k filters and Kelvin traces. Output bank is BEFORE the LED shunt.',
      'MOS source -> IS shunt -> power GND. Keep IS sense and signal ground away from switched current.',
      'LED negative is GND in this high-side-sense redesign. Do not reuse the old low-side return rule.',
      'OVP nominal 54.56 V. 63 V capacitors require measured overshoot qualification.',
      'Boost output has a DC path from VIN even while disabled. Fuse is not semiconductor short-circuit proof.',
      '22u COMP intentionally slow; DCM / PWM response / cold-hot transitions remain unqualified.'
    ],85)
    def ref(letter,n):return f'{letter}{base+n}'
    nn={1:vin,2:pre+'COMP',3:pre+'CSH',4:pre+'RCT',5:GND,6:pre+'OVP',7:'LED_NDIM',8:None,9:GND,10:pre+'GATE_RAW',11:pre+'VCC',12:pre+'IS',13:pre+'HSP',14:pre+'HSN',15:GND}
    add(sh,ref('U',1),'LM3429','LM3429MH/NOPB','LM3429MH/NOPB',nn,note='TI PWP0014A: EP15=GND; copper 3.4x5, mask 3.155x3.255; thermal vias and assembly pending',pos=(85,60))
    if k==1:
        add(sh,ref('L',1),'L','10u','JNRH1207-100N-A',[vin,pre+'L_MID'])
        add(sh,ref('L',2),'L','10u','JNRH1207-100N-A',[pre+'L_MID',pre+'SW'])
    else:add(sh,ref('L',1),'L','22u','JNRH1207-220M-A',[vin,pre+'SW'])
    add(sh,ref('D',1),'D','SS5P10 100V','SS5P10-M3/86A',[pre+'OUT',pre+'SW'],'EU_Parts:Vishay_TO-277A_D_K1_A2')
    add(sh,ref('Q',1),'NMOS','TK22E10N1','TK22E10N1',{1:pre+'GATE',2:pre+'SW',3:pre+'IS'},'Package_TO_SOT_THT:TO-220-3_Vertical',note=('Drain tab live. Separate insulated heatsink; exact assembly placement pending' if k==1 else 'Drain tab live (switch node). No heatsink: ~0.65 W, Rth(ch-a) 83.3 K/W free air; measure on the prototype'),pos=(300,60))
    r(sh,ref('R',1),'0R040 3W' if k==1 else '0R068 2W','LRP2512-R040-1%' if k==1 else 'CS2512-0R068-1%-HP',pre+'IS',GND)
    r(sh,ref('R',2),'0R15 2W' if k==1 else '0R47 2W','CS2512-0R15-1%-HP' if k==1 else 'CS2512-0R47-1%-HP',pre+'OUT',pre+'LED_POS','High side LED current shunt, separate Kelvin sense pair')
    r(sh,ref('R',3),'1k 1%',R1,pre+'OUT',pre+'HSP')
    r(sh,ref('R',4),'1k 1%',R1,pre+'LED_POS',pre+'HSN')
    r(sh,ref('R',5),'6k2' if k==1 else '5k6','SMD1206-6K2-1%' if k==1 else 'SMD1206 5K6 1%',pre+'CSH',pre+'CSH_MID')
    r(sh,ref('R',6),'1k2' if k==1 else '82R','CRCW12061K20FKTABC' if k==1 else 'SMD1206-82R',pre+'CSH_MID',GND)
    r(sh,ref('R',7),'56k 1%','SMD1206 56K 1%',pre+'SW',pre+'RT_MID')
    r(sh,ref('R',8),'6k2 1%','SMD1206-6K2-1%',pre+'RT_MID',pre+'RCT')
    r(sh,ref('R',9),'33k 1%','SMD1206-33K-1%',pre+'OUT',pre+'OVP_MID')
    r(sh,ref('R',10),'10k 1%',R10,pre+'OVP_MID',pre+'OVP')
    r(sh,ref('R',11),'1k 1%',R1,pre+'OVP',GND)
    for n in [1,2]:c(sh,ref('C',n),'220u 50V','UPW1H221MPD',vin)
    c(sh,ref('C',3),'100n VIN',C100,vin)
    c(sh,ref('C',4),'3u3 16V','CL31B335KOHNNNE',pre+'VCC')
    c(sh,ref('C',5),'22u COMP',C22,pre+'COMP')
    c(sh,ref('C',6),'1n C0G','C1206C102JCGACTU',pre+'RCT')
    c(sh,ref('C',7),'100p C0G','CL31C101JBCNNNC',pre+'OVP')
    for n in range(8,11 if k==1 else 10):c(sh,ref('C',n),'100u 63V','EEUFR1J101LB',pre+'OUT')
    c(sh,ref('C',11),'100n 100V','C0805C104K1RACTU',pre+'OUT')
    add(sh,ref('J',1),'J2',f'LED{k} + / GND','DG306-5.0-2P12',[pre+'LED_POS',GND])
    if k==2:add(sh,ref('J',2),'J2','BAR2 + / GND','DG306-5.0-2P12',[pre+'LED_POS',GND])

sheet('Loads','07 | PTC heater and 24 V pump',[
 'PTC is ON/OFF only, no fast PWM. External independent thermal cut-out is required in series with heater.',
 'GPIO32 HIGH turns on Q701 NPN, Q702 PNP, then Q703 power MOSFET; LOW / Hi-Z turns it off.',
 'Q703 IRF1010ES pin 2 and metal tab = DRAIN, pin 3 = SOURCE, pin 1 = GATE.',
 'Pump GPIO33 HIGH turns on Q704. 1k series gate uses the purchased spare resistor pack.',
 'D701 pump flyback cathode to fused +24V_PUMP, anode to PUMP_DRAIN.',
 'R702 4k7 keeps Q701 off (<0.4 V) even with the ESP32 internal pull-up on GPIO32; HIGH still gives ~0.13 mA base.',
 '100k GPIO/gate pulls stay active during reset. Pump stall current and fuse coordination still unmeasured.'
],70)
add('Loads','J701','J2','PTC + / RETURN','DG306-5.0-2P12',['+24V_PTC','PTC_DRAIN'],note='Bottom-edge DG306 since 2026-10-22: 15 A / 1.5 mm2 rating covers the 4.5 A heater')
add('Loads','Q701','NPN','BC847B-DIO','BC847B-DIO',{1:'PTC_NPN_B',2:GND,3:'PTC_NPN_C'},'Package_TO_SOT_SMD:SOT-23',pos=(65,55))
add('Loads','Q702','PNP','BC857B','BC857B',{1:'PTC_PNP_B',2:V12,3:'PTC_DRV'},'Package_TO_SOT_SMD:SOT-23',pos=(165,55))
add('Loads','Q703','NMOS','IRF1010ESPBF','IRF1010ESPBF',{1:'PTC_GATE',2:'PTC_DRAIN',3:GND},'Package_TO_SOT_SMD:TO-263-2',pos=(265,55))
r('Loads','R701','10k',D10,'PTC_GPIO','PTC_NPN_B')
r('Loads','R702','4k7 1%','SMD1206 4K7 1%','PTC_NPN_B',GND)
r('Loads','R703','2k2 1%','SMD1206-2K2-1%','PTC_NPN_C','PTC_PNP_B')
r('Loads','R704','10k',D10,V12,'PTC_PNP_B')
r('Loads','R705','220R','SMD1206-220R-1%','PTC_DRV','PTC_GATE')
r('Loads','R706','2k2 0.25W','SMD1206-2K2-1%','PTC_GATE',GND)
add('Loads','J702','J2','PUMP + / RETURN','DG306-5.0-2P12',['+24V_PUMP','PUMP_DRAIN'])
add('Loads','Q704','NMOS_GSD','AO3422','AO3422',{1:'PUMP_GATE',2:GND,3:'PUMP_DRAIN'},'Package_TO_SOT_SMD:SOT-23',pos=(365,55))
r('Loads','R707','1k GATE',D1,'PUMP_GPIO','PUMP_GATE')
r('Loads','R708','100k',D100,'PUMP_GATE',GND)
add('Loads','D701','D','SS510 100V','SS510-YAN',['+24V_PUMP','PUMP_DRAIN'],'Diode_SMD:D_SMC')

sheet('Control','08 | LED gate drive and hardware inhibit',[
 'BLOCK_OC is wired OR: L7987 PGOOD + LM2903 output, pulled up only to +3V3.',
 'BAT54 anode -> nDIM; cathode -> BLOCK_OC. Do not reverse this diode.',
 'One shared 10k pull-down on nDIM defeats BOTH internal LM3429 hysteresis sources after MCU reset.',
 'Do NOT add a 100n capacitor to nDIM. GPIO25 HIGH is enabled only after software checks.',
 'UVLO nominal release 19.90 V / fall 19.70 V depends on +3V3 reference and comparator tolerances.',
 'No external gate driver: each LM3429 GATE drives its own TK22E10N1 (Qg 28 nC) through 4R7; 100k gate pull-down.',
 'BAT54 cold Vf / hot leakage and nDIM reset levels remain hardware tests.',
 'Unused comparator inputs tied to valid DC levels; its unused open-collector output is NC.'
],85)
for k in (1,2):
    pre=f'LED{k}_';b=800+(k-1)*4
    r('Control',f'R{b+3}','4R7 1W','SMD2512-4R7',pre+'GATE_RAW',pre+'GATE')
    r('Control',f'R{b+4}','100k',D100,pre+'GATE',GND)
add('Control','U802','LM2903','LM2903D-ST','LM2903D-ST',{1:'BLOCK_OC',2:'UVLO_REF',3:'UVLO_SENSE',4:GND,5:GND,6:'UVLO_REF',7:None,8:V12},'Package_SO:SOIC-8_3.9x4.9mm_P1.27mm',pos=(280,55))
c('Control','C803','100n',C100,V12)
r('Control','R809','56k 1%','SMD1206 56K 1%',V24,'UVLO_TOP_MID')
r('Control','R810','5k6 1%','SMD1206 5K6 1%','UVLO_TOP_MID','UVLO_SENSE')
r('Control','R811','5k6 1%','SMD1206 5K6 1%','UVLO_SENSE',GND)
r('Control','R812','1M 1%','SMD1206-1M-1%','BLOCK_OC','UVLO_SENSE')
r('Control','R813','10k 1%',R10,V3,'UVLO_REF')
r('Control','R814','10k 1%',R10,'UVLO_REF',GND)
r('Control','R815','10k',D10,V3,'BLOCK_OC')
r('Control','R816','5k6 1%','SMD1206 5K6 1%','LED_PWM_GPIO','LED_NDIM')
r('Control','R817','10k SHARED',D10,'LED_NDIM',GND)
add('Control','D801','BAT54','BAT54-DIO','BAT54-DIO',{1:'LED_NDIM',2:None,3:'BLOCK_OC'},'Package_TO_SOT_SMD:SOT-23')

# A power flag documents the external/regulator source on each independently
# fused power net. It is not a purchased component and not a protection device.
for k,net in enumerate([GND,'+24V_RAW',V24,'+24V_PTC','+24V_PUMP','+24V_LED1','+24V_LED2','+24V_AUX',V12,V3,'VBAT'],1):
    add('InputPower',f'#FLG{k:02}','FLAG','PWR_FLAG','',{1:net},bom=False,pos=(20+33*((k-1)%11),240))

# Free PCB probe pads, deliberately not purchased or included in the parts count.
for n,(sh,net) in enumerate([('MCU',V3),('InputPower',V12),('Control','LED_NDIM'),('Control','BLOCK_OC'),('Control','UVLO_SENSE'),('Control','UVLO_REF'),('LED1','LED1_IS'),('LED2','LED2_IS')],1):
    add(sh,f'TP{n:02}','TP',net,'',{1:net},'TestPoint:TestPoint_Pad_D1.0mm',bom=False)

# One heatsink set: Q501 (LED1). Q601 (LED2, ~0.65 W) runs without a heatsink since 2026-10-22.
accessories = {'BAT-CR2032/P':1,'RAD-DY-GF/3':1,'TO220-SET':1,'SMICA-TO220-2':1}


def geometry(s):
    kind=s['kind'];line=lambda pts:f'(polyline (pts {" ".join(f"(xy {num(x)} {num(y)})" for x,y in pts)}) (stroke (width 0.254) (type default)) (fill (type none)))'
    rect=lambda x1,y1,x2,y2:f'(rectangle (start {num(x1)} {num(y1)}) (end {num(x2)} {num(y2)}) (stroke (width 0.254) (type default)) (fill (type background)))'
    if kind=='ic':return rect(-s['width']/2,s['height']/2,s['width']/2,-s['height']/2)
    if kind in ['r','f']:return rect(-2.54,1.27,2.54,-1.27)+(line([(-2.54,0),(2.54,0)]) if kind=='f' else '')
    if kind in ['c','cp']:
        out=line([(-.635,2.54),(-.635,-2.54)])+line([(.635,2.54),(.635,-2.54)])
        if kind=='cp':out+=line([(-3.5,3.3),(-2,3.3)])+line([(-2.75,2.55),(-2.75,4.05)])
        return out
    if kind=='l':return line([(-2.54,0),(-1.9,1.27),(-1.27,0),(-.635,1.27),(0,0),(.635,1.27),(1.27,0),(1.9,1.27),(2.54,0)])
    if kind in ['d','tvs']:
        out=line([(-1.27,2.54),(-1.27,-2.54)])+line([(-1.27,0),(1.27,2.54),(1.27,-2.54),(-1.27,0)])
        if kind=='tvs':out+=line([(-1.9,3.17),(-1.27,2.54)])+line([(-1.27,-2.54),(-.635,-3.17)])
        return out
    if kind=='sw':return line([(-2.54,0),(2.54,2.54)])
    if kind=='y':return rect(-1.27,2.54,1.27,-2.54)+line([(-2.54,2.54),(-2.54,-2.54)])+line([(2.54,2.54),(2.54,-2.54)])
    if kind=='bat':return line([(-.635,2.54),(-.635,-2.54)])+line([(.635,1.27),(.635,-1.27)])+line([(-3,3),(-1.5,3)])+line([(-2.25,2.25),(-2.25,3.75)])
    if kind=='nmos':return (HERE/'libraries/NMOS_graphics.sexpr').read_text()
    if kind in ['npn','pnp']:
        body=line([(-2.54,2.54),(-2.54,-2.54)])+line([(-2.54,1.27),(5.08,3.81),(5.08,5.08)])+line([(-2.54,-1.27),(5.08,-3.81),(5.08,-5.08)])
        arrow=[(3.81,-3.386),(2.05,-3.45),(2.75,-1.78),(3.81,-3.386)] if kind=='npn' else [(0.635,2.328),(2.8,2.07),(2.1,3.74),(0.635,2.328)]
        return body+line(arrow)
    if kind in ['tp','flag']:return f'(circle (center 0 1.27) (radius 0.635) (stroke (width 0.254) (type default)) (fill (type none)))'
    raise ValueError(kind)


def pin_length(s,p):
    if s['kind']=='ic':return 5.08
    if s['kind'] in ['tp','flag']:return 0
    if s['kind'] in ['c','cp','bat']:return 6.985
    if s['kind'] in ['d','tvs']:return 6.35
    if s['kind']=='y':return 5.08
    if s['kind']=='nmos':return 2.54
    if s['kind'] in ['npn','pnp']:return 5.08 if p['number']=='1' else 1.27
    return 5.08


def libsymbol(name, qualified=False):
    s=symbols[name];shown=s['kind']=='ic';ref='U' if shown else name
    n=f'EU:{name}' if qualified else name
    a=[f'(symbol {q(n)} (pin_names (offset 0.762){"" if shown else " (hide yes)"})',
       '(in_bom yes) (on_board yes)',prop('Reference',ref,0,5,False),prop('Value',name,0,-5,False),prop('Footprint',''),prop('Datasheet',''),
       f'(symbol {q(name+"_0_1")} {geometry(s)})',f'(symbol {q(name+"_1_1")}']
    for p in s['pins']:
        a.append(f'(pin {p["typ"]} line (at {num(p["x"])} {num(p["y"])} {p["angle"]}) (length {num(pin_length(s,p))}) (name {q(p["name"])} {effects(.95)}) (number {q(p["number"])} {effects(.95)}))')
    return '\n'.join(a)+'))'


def header(name,title):
    stage = ('SCHEMATIC DRAFT | PARTIAL LED1 PCB ROUTING | no manufacturing release' if (HERE/'routing.json').exists()
             else 'SCHEMATIC DRAFT | UNROUTED PCB | no manufacturing release' if (HERE/'placement.json').exists()
             else 'SCHEMATIC DRAFT | no PCB / manufacturing release')
    return f'(kicad_sch (version 20260306) (generator "eeschema") (generator_version "10.0") (uuid {q(uid(name))}) (paper "A3") (title_block (title {q(title)}) (date {q(DATE)}) (rev "EU-0.1") (company "GrowBox | EU prototype") (comment 1 {q(stage)}))'


def textblk(name,key,t,x,y,size=1.1):
    return f'(text {q(t)} (at {num(x)} {num(y)} 0) {effects(size,"(justify left top)")} (uuid {q(uid(name,key))}))'


def schematic(sh,meta):
    used=sorted({p['symbol'] for p in meta['parts']})
    a=[header(sh,meta['title']), '(lib_symbols '+ '\n'.join(libsymbol(n,True) for n in used)+')']
    root=uid(ROOT);su=uid('sheet',sh)
    a.append(textblk(sh,'heading',meta['title'],12.7,12.7,2))
    a.append(textblk(sh,'note','\n'.join(meta['notes']),12.7,251,1.02))
    # Five columns, 80 mm pitch. ICs get a distinct top row if chip_area != 0.
    grid=[]
    for y in range((45 if meta['chip_area']==0 else 35+meta['chip_area']),236,20):
        for x in [46,107,174,241,308,375]:grid.append((x,y))
    g=iter(grid)
    for p in meta['parts']:
        p['position']=p['position'] or next(g)
        x,y=p['position'];x=round(x/1.27)*1.27;y=round(y/1.27)*1.27
        p['position']=(round(x,4),round(y,4));s=symbols[p['symbol']];h=s['height']/2
        pi=uid('component',p['ref'])
        val=p['value']
        a.append(f'(symbol (lib_id {q("EU:"+p["symbol"])}) (at {num(x)} {num(y)} 0) (unit 1) (in_bom {"yes" if p["in_bom"] else "no"}) (on_board {"no" if p["symbol"]=="FLAG" else "yes"}) (dnp no) (uuid {q(pi)})')
        tx=x-7.62 if s['kind'] in ['nmos','npn','pnp'] else x
        if s['kind']=='tp':tx=x-8.89
        a.extend([prop('Reference',p['ref'],tx,y-h-3.1,s['kind']=='flag',1.15),prop('Value',val,tx,y+h+3.1,s['kind'] in ['flag','tp'],.98),prop('Footprint',p['footprint'],x,y),prop('Datasheet',source_urls.get(p['mpn'],''),x,y),prop('MPN',p['mpn'],x,y),prop('Design_note',p['note'],x,y),prop('FootprintStatus','DRAWING CHECKED - physical fit and PCB validation pending' if p['mpn'] in MECHANICAL else ('PACKAGE ONLY - verify before PCB' if p['footprint'] else 'PENDING - no approved footprint'),x,y)])
        for pin_ in s['pins']:a.append(f'(pin {q(pin_["number"])} (uuid {q(uid(pi,pin_["number"]))}))')
        a.append(f'(instances (project {q(ROOT)} (path {q("/"+root+"/"+su)} (reference {q(p["ref"])}) (unit 1)))) )')
        for pin_ in s['pins']:
            pn=pin_['number'];xx=x+pin_['x'];yy=y-pin_['y'];net=p['nets'][pn]
            if net is None:
                a.append(f'(no_connect (at {num(xx)} {num(yy)}) (uuid {q(uid(pi,pn,"NC"))}))');continue
            # Stubs follow the outward pin direction.
            th=math.radians(pin_['angle']);dx=-math.cos(th)*5.08;dy=math.sin(th)*5.08
            if s['kind'] in ['flag','tp']:dx=-5.08;dy=0
            ex=round(xx+dx,4);ey=round(yy+dy,4)
            a.append(f'(wire (pts (xy {num(xx)} {num(yy)}) (xy {num(ex)} {num(ey)})) (stroke (width 0) (type default)) (uuid {q(uid(pi,pn,"wire"))}))')
            # Global labels connect separate sheets. Text is outside the component.
            la=(pin_['angle']+180)%360
            if s['kind'] in ['flag','tp']:la=180
            just='left' if la in [0,90] else 'right'
            a.append(f'(global_label {q(net)} (shape bidirectional) (at {num(ex)} {num(ey)} {la}) {effects(.9,f"(justify {just})")} (uuid {q(uid(pi,pn,"label"))}) {prop("Intersheetrefs","${INTERSHEET_REFS}",ex,ey)})')
    a.append(f'(sheet_instances (path "/" (page {q(str(list(sheets).index(sh)+2))})))')
    a.append('(embedded_fonts no))')
    return '\n'.join(a)+'\n'


source_urls={
 'LM3429MH/NOPB':'https://www.ti.com/lit/ds/symlink/lm3429.pdf',
 'L7987':'https://www.st.com/resource/en/datasheet/l7987.pdf',
 'AP63203WU-7':'https://www.diodes.com/datasheet/download/AP63200-AP63201-AP63203-AP63205.pdf',
 'LM2903D-ST':'https://www.st.com/resource/en/datasheet/lm2903.pdf',
 'USBLC6-2SC6':'https://www.st.com/resource/en/datasheet/usblc6-2.pdf',
 'ESDA6V1L':'https://www.st.com/resource/en/datasheet/esdal.pdf',
 'BAT54-DIO':'https://www.diodes.com/datasheet/download/BAT54.pdf',
 'MEM2061-01-188-00-A':'https://gct.co/Files/Drawings/MEM2061.pdf',
 'ESP32-WROOM-32E-N4':'https://www.espressif.com/sites/default/files/documentation/esp32-wroom-32e_esp32-wroom-32ue_datasheet_en.pdf',
 'AO3422':'https://www.aosmd.com/sites/default/files/res/datasheets/AO3422.pdf',
 'TK22E10N1':'https://docs.rs-online.com/8d7e/0900766b81294f79.pdf',
 'INA226AIDGSR':'https://www.ti.com/lit/ds/symlink/ina226.pdf',
 'BZV55-C33':'https://assets.nexperia.com/documents/data-sheet/BZV55_SER.pdf',
 'MCP7940N-I/SN':'https://ww1.microchip.com/downloads/aemDocuments/documents/MPD/ProductDocuments/DataSheets/MCP7940N-Battery-Backed-I2C-RTCC-with-SRAM-20005010J.pdf',
}


# Review fixes of 2026-10-21 change these per-piece quantities against the
# dated 2026-10-20 price snapshot (prices unchanged, stock was sufficient then).
REVIEW_BUY={'SMD1206 4K7 1%':3,'IRF1010ESPBF':2,'SMD1206 5K6 1%':6,'SMD1206-10K-1%':6,'CL31A106KAHNNNE':2}
REVIEW_USAGE={
 'SMD1206 4K7 1%':'1%: I2C pull-ups ×2, R702 база Q701 (держит PTC выключенным при внутренней подтяжке ESP32)',
 'IRF1010ESPBF':'60 В, D2PAK: Q703 ключ PTC (затвор от 12 В) и Q102 защита от переполюсовки в минусе входа',
 'SMD1206 5K6 1%':'1%: RCSH CH2, два плеча UVLO, series-R GPIO25 → nDIM, делитель затвора Q102 ×2',
 'SMD1206-10K-1%':'1%: верх OVP ×2, верх FB L7987 ×1, опорный делитель UVLO ×2, gate–source Q102 ×1',
 'CL31A106KAHNNNE':'10 мкФ / 25 В: 2 на входе AP63203',
 'CL21B104KBCNNNC':'13 байпасных/фильтрующих конденсаторов в схеме (вкл. VS INA226), покупка 20, остаток 7',
 'CL21B105KBFNNNG':'1 мкФ / 50 В X7R 0805: 4 VCC/VIN, 2 VBIAS, 1 CF, 1 SS, 1 EN ESP32; купить пачку 10',
 'SMD0603-100K':'0603 / 5%: gate TK22E10N1 ×2, gate помпы ×1, gate fan PWM ×2',
 'DG306-5.0-2P12':'PTC, помпа, LED×3, float (6 шт.). С 22.10.2026 вентиляторы на хидерах KF2510, SHT4x на разъёме XH, PTC на DG306 у нижнего края: 5 шт. в покупке лишние, количество не менялось до проверки BOM',
 'DG301R-5.0-2P12':'Вход 24 В J101 (1 шт., 2,5 мм², 16 А). С 22.10.2026 клемма PTC J701 на DG306: 1 шт. в покупке лишняя, количество не менялось до проверки BOM',
 'RAD-DY-GF/3':'STONECOLD RAD-DY-GF/3, 30×30×15 мм, 8,8 К/Вт по каталогу; радиатор Q501 (LED1). У Q601 (LED2) радиатора нет с 22.10.2026: второй в покупке лишний',
 'TO220-SET':'TO220-SET: винт, гайка, шайба, втулка, слюда для Q501; второй комплект лишний с 22.10.2026',
 'SMICA-TO220-2':'NINIGI, силиконовая прокладка со втулкой, 15×20×0,3 мм, для Q501; вторая лишняя с 22.10.2026',
}


# Rows added after the 2026-10-20 snapshot, inserted after the named row.
# TK22E10N1 replaced IRF540ZPBF on 2026-10-21: lower gate charge for the 7 V,
# 1 A LM3429 driver at 400 kHz. INA226 and its shunt added 2026-10-21 for the
# board power display.
REVIEW_ROWS={
 'IRF540ZPBF':[dict(shop='Salvats',mpn='TK22E10N1',needed=2,buy=2,unit='шт.',price_unit=1.38,line=2.76,stock=22,
  url='https://www.salvats.lv/lv/100v-n-fet-tht/22e10n-tranzistors-n-fet-100v-20v-22a-72w-0r0115-to-220',block='LED',
  usage='Toshiba, 100 В, 13,8 мОм, Qg 28 нКл, TO-220 G-D-S; Q501/Q601 от GATE LM3429 через 4,7 Ом',price_date='2026-10-21')],
 'DG306-5.0-2P12':[dict(shop='не выбран',mpn='KF2510-4A',needed=2,buy=2,unit='шт.',price_unit=0.0,line=0.0,stock='',
  url='',block='Вентиляторы',
  usage='Прямой хидер 4 контакта 2,54 мм (серия KF2510 / «2510-4P», посадка Molex KK-254) для J411/J421. Магазин и цена не выбраны: ждут проверки BOM',price_date='2026-10-22'),
  dict(shop='не выбран',mpn='XH2.54-4P-90',needed=1,buy=1,unit='шт.',price_unit=0.0,line=0.0,stock='',
  url='',block='Интерфейсы',
  usage='Угловой хидер XH 4 контакта (посадка JST XH S4B-XH-A, шаг 2,50 мм) для внешнего SHT4x, J401. Магазин и цена не выбраны: ждут проверки BOM; сверить шаг и порядок проводов',price_date='2026-10-22')],
 'IRF1010ESPBF':[dict(shop='Electrobase',mpn='INA226AIDGSR',needed=1,buy=1,unit='шт.',price_unit=3.94,line=3.94,stock='',
  url='https://electrobase.lv/katalogs/operacijas-pastiprinataji-smd/ic-instrumentation-amplifier-2755vdc-vssop10-reeltape-0',block='Вход 24 В',
  usage='TI INA226, VSSOP-10: ток, напряжение и мощность всей платы по I2C (0x40). Цена от Igors 21.10.2026; наличие и продажа поштучно с катушки не подтверждены',price_date='2026-10-21'),
  dict(shop='Salvats',mpn='SMD2512-0R01-1%-3W',needed=2,buy=2,unit='шт.',price_unit=0.24,line=0.48,stock=369,
  url='https://www.salvats.lv/lv/rezistori-smd-2512-1w3w/0r01-2512635x32mm-3w-1-smd-55170c-rezistors-thick-film-2512',block='Вход 24 В',
  usage='0R01 2512 3 Вт 1%: R111||R112 = 5 мОм, шунт INA226 в обратном проводе',price_date='2026-10-21'),
  dict(shop='Salvats',mpn='BZV55-C33',needed=1,buy=1,unit='шт.',price_unit=0.13,line=0.13,stock=94,
  url='https://www.salvats.lv/lv/stabilitroni-smd-bzv55/33v-stabilitrons-smd-bzv55-5-05w-minimelf-1',block='Вход 24 В',
  usage='Стабилитрон 33 В 0,5 Вт MiniMELF: D103 защищает вход VBUS INA226 (предел 40 В) при срабатывании D101',price_date='2026-10-21')]}


def main():
    for d in ['libraries','review']: (HERE/d).mkdir(exist_ok=True)
    lib='(kicad_symbol_lib (version 20241209) (generator "kicad_symbol_editor")\n'+'\n'.join(libsymbol(n) for n in sorted(symbols))+')\n'
    (HERE/'libraries/EU.kicad_sym').write_text(lib)
    (HERE/'sym-lib-table').write_text('(sym_lib_table (version 7) (lib (name "EU") (type "KiCad") (uri "${KIPRJMOD}/libraries/EU.kicad_sym") (options "") (descr "Project pin-verified symbols")))\n')
    libs=sorted(x.name[:-7] for x in (HERE/'libraries').glob('*.pretty'))
    (HERE/'fp-lib-table').write_text('(fp_lib_table (version 7)\n'+'\n'.join(f'(lib (name {q(n)}) (type "KiCad") (uri "${{KIPRJMOD}}/libraries/{n}.pretty") (options "") (descr "Project-local footprints; see SOURCES.md for qualification status"))' for n in libs)+')\n')
    for sh,meta in sheets.items(): (HERE/f'{sh}.kicad_sch').write_text(schematic(sh,meta))
    root=[header(ROOT,'GrowBox | EU redesign | schematic review'),'(lib_symbols)']
    root.append(textblk(ROOT,'title','GrowBox controller\nEuropean sourcing / 24 V PSU / one prototype',20,17,2.5))
    placement_stage = (HERE/'placement.json').exists()
    routing_stage = (HERE/'routing.json').exists()
    scope = ('Connection/BOM draft; partial LED1 PCB routing. No manufacturing release.' if routing_stage
             else 'Connection/BOM draft; unrouted PCB placement candidate. No manufacturing release.' if placement_stage
             else 'Full connection/BOM draft. No PCB placement, routing or manufacturing release.')
    root.append(textblk(ROOT,'scope','SCHEMATIC DRAFT EU-0.1 | 20 October 2026\n'+scope+'\nSeparate project; original PCB_V1 rev 0.22 remains the functional reference.',20,40,1.6))
    for k,(sh,meta) in enumerate(sheets.items()):
        x=25+185*(k%2);y=75+42*(k//2);sid=uid('sheet',sh)
        root.append(f'(sheet (at {x} {y}) (size 155 28) (stroke (width 0.254) (type default)) (fill (color 0 0 0 0)) (uuid {q(sid)}) {prop("Sheetname",meta["title"],x+77.5,y-2,False,1.4)} {prop("Sheetfile",sh+".kicad_sch",x+77.5,y+30,False,1)} (instances (project {q(ROOT)} (path {q("/"+uid(ROOT))} (page {q(k+2)})))))')
    root.append('(sheet_instances (path "/" (page "1"))) (embedded_fonts no))')
    (HERE/f'{ROOT}.kicad_sch').write_text('\n'.join(root)+'\n')
    # Preserve PCB rules/stackup added by the board editor. No broad ERC exclusions.
    project_path = HERE/f'{ROOT}.kicad_pro'
    project = json.loads(project_path.read_text()) if project_path.exists() else dict(meta=dict(filename=f'{ROOT}.kicad_pro',version=3),erc=dict(erc_exclusions=[],meta=dict(version=0)),schematic=dict(meta=dict(version=1)))
    project.setdefault('text_variables',{})['DESIGN_STAGE'] = 'PARTIAL_LED1_ROUTING' if routing_stage else 'UNROUTED_PLACEMENT' if placement_stage else 'SCHEMATIC_DRAFT'
    (HERE/f'{ROOT}.kicad_pro').write_text(json.dumps(project,indent=2)+'\n')
    spec=dict(revision=REV,date=DATE,source_commit='1d6b1eaf1273149b32eb1cf5c91fc69ff6a6ca09',parts=parts,accessories=accessories,source_urls=source_urls)
    (HERE/'design.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2)+'\n')
    # Allocate all purchasing rows to actual component references / accessories.
    rows=json.loads((HERE/'procurement_2026-10-20.json').read_text())
    for i in range(len(rows)-1,-1,-1):
        for extra in reversed(REVIEW_ROWS.get(rows[i]['mpn'],[])):rows.insert(i+1,dict(extra))
    for row in rows:
        row['previous_needed']=row['needed'];mpn=row['mpn']
        refs=[p['ref'] for p in parts if p['mpn']==mpn and p['in_bom']]
        need=counts[mpn]+accessories.get(mpn,0)
        row['needed']=need;row['refs']=refs;row['accessory_count']=accessories.get(mpn,0)
        # Digitals are sold in complete packs of ten; all other quantities are
        # retained except the three unused 100-ohm gate resistors.
        if mpn=='SMD0603-10K': row['buy']=10*math.ceil(need/10);row['line']=float(Decimal(str(row['price_unit']))*(row['buy']//10))
        if mpn=='SMD1206-100R-1%': row['buy']=need;row['line']=float(Decimal(str(row['price_unit']))*need)
        if mpn in REVIEW_BUY:
            row['buy']=REVIEW_BUY[mpn];row['line']=float(Decimal(str(row['price_unit']))*row['buy'])
        if mpn in REVIEW_USAGE:row['usage']=REVIEW_USAGE[mpn]
        if mpn=='SMD0603-1K':row['usage']='1k: tach x2, float x1, pump/fan gates x3, INA226 VBUS x1; 7 of 10 purchased'
        assert need<=row['buy'],(mpn,need,row['buy'])
    dropped=[row['mpn'] for row in rows if not row['needed']]
    rows=[row for row in rows if row['needed']]
    unknown=set(counts)|set(accessories)
    unknown-=set(row['mpn'] for row in rows)
    assert not unknown,unknown
    assert not [x['mpn'] for x in rows if not x['needed']], 'Unallocated purchased SKU'
    (HERE/'BOM_allocated.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
    with (HERE/'BOM_allocated.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f,lineterminator="\n");w.writerow(['Shop','MPN_or_shop_SKU','Fitted_or_accessory','Buy_pieces','Sale_unit','Price_per_sale_unit_EUR_VAT','Line_EUR_VAT','References','Accessory_count','URL','Price_date'])
        for row in rows:w.writerow([row['shop'],row['mpn'],row['needed'],row['buy'],row['unit'],row['price_unit'],f'{row["line"]:.2f}',' '.join(row['refs']),row['accessory_count'],row['url'],row.get('price_date',DATE)])
    totals=defaultdict(Decimal)
    for row in rows:totals[row['shop']]+=Decimal(str(row['line']))
    summary=dict(electrical_components=sum(counts.values()),testpads=8,accessories=accessories,rows=len(rows),shop_totals={k:str(v) for k,v in totals.items()},shipping_EUR='5.87',total_EUR=str(sum(totals.values())+Decimal('5.87')),price_basis='Dated sourcing snapshot 2026-10-20; quantities now allocated to actual schematic. No reservation or order.')
    (HERE/'review/BOM_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    print('Dropped SKUs (no fitted reference):',dropped)
    print('Changed quantities:',[(r['mpn'],r['previous_needed'],r['needed']) for r in rows if r['previous_needed']!=r['needed']])


if __name__=='__main__':main()
