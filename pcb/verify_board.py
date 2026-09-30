"""Run with KiCad bundled Python: verify_board.py netlist.xml board.kicad_pcb.
Checks every exported electrical pin and every numbered power MOSFET pad.
"""
import sys
import xml.etree.ElementTree as ET
import pcbnew
root=ET.parse(sys.argv[1]);board=pcbnew.LoadBoard(sys.argv[2])
fps={f.GetReference():f for f in board.GetFootprints()}
refs=[c.get('ref') for c in root.findall('.//components/comp')]
assert set(refs)==set(fps),'Board and schematic component sets differ'
for comp in root.findall('.//components/comp'):
 ref=comp.get('ref');fp=fps[ref];identity=fp.GetFPID()
 assert fp.GetValue()==comp.findtext('value'),(ref,'value differs')
 assert str(identity.GetLibNickname())+':'+str(identity.GetLibItemName())==comp.findtext('footprint'),(ref,'footprint differs')
 fields={f.get('name'):f.text or '' for f in comp.findall('fields/field')}
 for key in ('Manufacturer','MPN','LCSC'):
  assert (fp.GetFieldText(key) if fp.HasField(key) else '')==fields.get(key,''),(ref,key,'metadata differs')
 # XML omits the schematic root UUID; the PCB path includes it. This catches
 # newly added footprints that would otherwise be duplicated on Update PCB.
 suffix=comp.find('sheetpath').get('tstamps').rstrip('/')+'/'+comp.findtext('tstamps').strip()
 assert fp.GetPath().AsString().endswith(suffix),(ref,'schematic instance path differs')
nodes={}
for net in root.findall('.//nets/net'):
 for node in net.findall('node'):
  key=(node.get('ref'),node.get('pin'));nodes[key]=net.get('name')
  pads=[p for p in fps[key[0]].Pads() if p.GetNumber()==key[1]]
  assert pads and all(p.GetNetname()==net.get('name') for p in pads),key
for ref in ['U301','U902','Q711','Q721','Q601']:
 for pad in fps[ref].Pads():
  number=pad.GetNumber()
  if number:assert (ref,number) in nodes and pad.GetNetname()==nodes[(ref,number)],(ref,number)
 if ref in ('U301','U902'):continue
 source_pins, gate, drain = ['1','2','3'], '4', '5'
 source=[nodes[(ref,n)] for n in source_pins]
 assert len(set(source))==1,(ref,'source pads differ')
 assert len({source[0],nodes[(ref,gate)],nodes[(ref,drain)]})==3,(ref,'G/D/S short')
print(f'PASS: {len(fps)} footprints, {len(nodes)} nodes; every numbered power MOSFET pad checked')

def numbered(ref):
 pads={}
 for p in fps[ref].Pads():
  if p.GetNumber():pads.setdefault(p.GetNumber(),[]).append(p)
 return pads
def size(p):
 s=p.GetSize();return (round(pcbnew.ToMM(s.x),4),round(pcbnew.ToMM(s.y),4))

# v0.20 AOS AOD66923 (TO-252/DPAK) on a project footprint that keeps the NexFET numbering:
# source lead = pads 1/2/3 stacked (paste on pad 1 only), gate lead 4, drain tab 5.
for ref in ['Q711','Q721']:
 pads=numbered(ref)
 assert str(fps[ref].GetFPID().GetLibItemName())=='TO-252-2_NMOS_S123_G4_D5',(ref,'DPAK footprint')
 assert fps[ref].GetValue()=='AOD66923'
 assert set(pads)=={'1','2','3','4','5'} and all(len(v)==1 for v in pads.values()),(ref,'DPAK pad numbers')
 rel={n:tuple(round(pcbnew.ToMM(v),3) for v in (ps[0].GetFPRelativePosition().x,ps[0].GetFPRelativePosition().y)) for n,ps in pads.items()}
 assert rel['1']==rel['2']==rel['3']==(-5.04,2.28) and rel['4']==(-5.04,-2.28) and rel['5']==(1.26,0.0),(ref,'DPAK lead positions')
 assert all(size(pads[n][0])==(2.2,1.2) for n in '1234') and size(pads['5'][0])==(6.4,5.8),(ref,'DPAK lands')
 assert [n for n in '123' if pads[n][0].IsOnLayer(pcbnew.F_Paste)]==['1'],(ref,'stacked source pads must print paste once')
assert str(fps['U301'].GetFPID().GetLibItemName())=='SOIC-8_3.9x4.9mm_P1.27mm'
assert fps['U301'].GetValue()=='PCF8563T/5'
assert {p.GetNumber() for p in fps['U301'].Pads()}==set('12345678')
assert nodes[('U301','1')]==nodes[('Y301','1')] and nodes[('U301','2')]==nodes[('Y301','2')],'crystal on OSCI/OSCO'
print('PASS: AOD66923 DPAK S1/2/3 G4 D5 (Q711, Q721) and SOIC-8 PCF8563 package/pin mapping')

# Check selected LED power packages: SS5P10 TO-277A cathode tab 1, two anode leads 2.
for ref in ['D711','D721','L711','L721']:
 for pad in fps[ref].Pads():
  if pad.GetNumber():
   key=(ref,pad.GetNumber())
   assert key in nodes and pad.GetNetname()==nodes[key],key
for n in (1,2):
 d=f'D7{n}1'
 assert nodes[(d,'1')]==nodes[(f'C7{n}6','1')] and nodes[(d,'2')]==nodes[(f'Q7{n}1','5')],(d,'diode polarity')
 assert str(fps[d].GetFPID().GetLibItemName())=='Vishay_TO-277A_D_K1_A2',(d,'TO-277A footprint')
 pads=numbered(d)
 assert set(pads)=={'1','2'} and len(pads['1'])==1 and len(pads['2'])==2,(d,'K tab + two A leads')
 assert size(pads['1'][0])==(4.8,4.72) and all(size(p)==(1.4,1.27) for p in pads['2']),(d,'TO-277A lands')
for ref,sz in [('L711',(3.15,12.5)),('L721',(3.1,5.0))]:
 pads=[p for p in fps[ref].Pads() if p.GetNumber()]
 assert {p.GetNumber() for p in pads}=={'1','2'}
 for pad in pads:
  assert size(pad)==sz,(ref,'land dimensions')
assert str(fps['L721'].GetFPID().GetLibItemName())=='L_Bourns_SRP1265A'
assert str(fps['L711'].GetFPID().GetLibItemName())=='L_Bourns_SRP1770TA_16.9x16.9mm'
assert nodes[('J721','1')]==nodes[('J731','1')] and nodes[('J721','2')]==nodes[('J731','2')],'CH2 bars not paralleled'
print('PASS: all values/footprints agree; SS5P10 polarity and lands, CH2 parallel bars and selected passive lands checked')

# 24 V input and 12 V aux buck.
gnd=nodes[('U201','1')]
assert str(fps['J901'].GetFPID().GetLibItemName())=='AMASS_XT60PW-M_1x02_P7.20mm_Horizontal'
assert str(fps['J901'].GetFPID().GetLibNickname())=='GrowBox','Use reviewed XT60 lands, not older stock footprint'
for pad in fps['J901'].Pads():
 drill=pad.GetDrillSize()
 drill=tuple(round(pcbnew.ToMM(v),3) for v in (drill.x,drill.y))
 assert drill==((3.,3.) if pad.GetNumber() else (.9,2.)),('J901','contact or retaining slot',drill)
assert nodes[('J901','1')]==gnd and nodes[('J901','2')]==nodes[('F904','1')],'XT60 polarity'
assert nodes[('F904','2')]==nodes[('U902','2')],'buck must be after auxiliary fuse'
for ref in ['F902']:
 pads=numbered(ref)
 assert str(fps[ref].GetFPID().GetLibItemName())=='Fuseholder_Blade_Mini_XFCN_XF-508P'
 assert set(pads)=={'1','2'} and all(len(v)==2 for v in pads.values()),(ref,'4-pin holder')
 for v in pads.values():
  for p in v:assert abs(pcbnew.ToMM(p.GetDrillSize().x)-1.8)<.001,(ref,'drill')
 xs=sorted({round(pcbnew.ToMM(p.GetFPRelativePosition().x),3) for v in pads.values() for p in v})
 assert xs==[0.0,9.8],(ref,'XF-508P pin pitch',xs)
pads=numbered('U902')
assert str(fps['U902'].GetFPID().GetLibItemName())=='SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.95x4.9mm_Mask2.71x3.4mm'
assert set(pads)==set('123456789'),('U902','DDA pads')
assert nodes[('U902','9')]==nodes[('U902','7')]==gnd,'LMR16020 thermal pad must be GND'
assert nodes[('U902','6')].startswith('unconnected-')
assert nodes[('D902','1')]==nodes[('U902','8')]==nodes[('L902','1')],'catch diode cathode to SW'
assert nodes[('D902','2')]==gnd
assert nodes[('L902','2')]==nodes[('U101','3')]==nodes[('U601','6')],'12 V aux feeds 3.3 V buck and gate driver'
assert str(fps['L902'].GetFPID().GetLibItemName())=='L_Changjiang_FXL0630'
assert nodes[('U710','1')]==nodes[('U720','1')]==nodes[('L902','2')],'AL8853 bias must use 12 V'
assert str(fps['C909'].GetFPID().GetLibItemName())=='CP_Elec_8x6.9'
assert nodes[('C909','1')]==nodes[('L902','2')] and nodes[('C909','2')]==gnd,'C909 polymer polarity'
assert all(size(p)==(4.15,1.9) for v in numbered('C909').values() for p in v),'C909 E7 lands'
for ref in ['F501','F511','F521','F711','F721','F904']:
 pads=numbered(ref)
 assert str(fps[ref].GetFPID().GetLibItemName())=='Fuse_Littelfuse_451'
 assert set(pads)=={'1','2'} and all(len(v)==1 for v in pads.values()),(ref,'fuse terminals')
 assert nodes[(ref,'1')]!=nodes[(ref,'2')],(ref,'fuse bypass')
 for v in pads.values():assert size(v[0])==(1.96,3.15),(ref,'451 recommended lands')
 assert abs(pcbnew.ToMM(pads['1'][0].GetFPRelativePosition().x-pads['2'][0].GetFPRelativePosition().x))==4.91,(ref,'pad span')
assert str(fps['U201'].GetFPID().GetLibItemName())=='ESP32-WROOM-32E_NoVias'
assert not [p for p in fps['U201'].Pads() if p.GetAttribute()==pcbnew.PAD_ATTRIB_PTH and pcbnew.ToMM(p.GetDrillSize().x)<0.3],'ESP32 sub-0.3 mm vias'
assert {p.GetNumber() for p in fps['U201'].Pads() if p.GetNumber()}==set(str(i) for i in range(1,40)),'ESP32 pads'
print('PASS: schematic instance paths; XT60 polarity, mini-blade holder, six SMT fuses, LMR16020 DDA, 12 V bias wiring, ESP32 without 0.2 mm vias')

# Reviewed procurement changes: pitch alone does not establish terminal fit.
for refs,kind,drill,land,count in [
 (['J302','J521','J601'],'TerminalBlock_DORABO_DB125-3.5_1x02_P3.50mm_Horizontal',1.2,2.4,2),
 (['J501','J511'],'TerminalBlock_DORABO_DB125-3.5_1x04_P3.50mm_Horizontal',1.2,2.4,4),
 (['J711','J721','J731'],'TerminalBlock_KANGNEX_WJ500V-5.08_1x02_P5.08mm_Horizontal',1.5,2.8,2),
]:
 for ref in refs:
  fp=fps[ref]
  assert str(fp.GetFPID().GetLibNickname())=='GrowBox' and str(fp.GetFPID().GetLibItemName())==kind,ref
  assert set(numbered(ref))==set(str(i) for i in range(1,count+1)),ref
  for pad in fp.Pads():
   assert abs(pcbnew.ToMM(pad.GetDrillSize().x)-drill)<.001 and size(pad)==(land,land),(ref,'terminal lands')
assert str(fps['BT301'].GetFPID().GetLibItemName())=='BatteryHolder_MYOUNG_BS-07-A1BJ001_CR2032'
assert len(list(fps['BT301'].Pads()))==2
assert nodes[('BT301','2')]==gnd and nodes[('BT301','1')]!=gnd,'CR2032 polarity'
for pad in fps['BT301'].Pads():
 assert pad.GetAttribute()==pcbnew.PAD_ATTRIB_PTH and abs(pcbnew.ToMM(pad.GetDrillSize().x)-1.5)<.001,'Battery holder lead hole'
# L101 cjiang FXL0630-100-M and L902 PROD PSPMAA0604-220M-ANP (land 2.1 x 3.5 at 5.8 mm) share KiCad's FXL0630 lands.
for ref,mpn in [('L101','FXL0630-100-M'),('L902','PSPMAA0604-220M-ANP')]:
 assert str(fps[ref].GetFPID().GetLibItemName())=='L_Changjiang_FXL0630'
 assert fps[ref].GetField('MPN').GetText()==mpn
 assert all(size(pad)==(2.35,3.5) for pad in fps[ref].Pads()),(ref,'FXL0630 lands')
# v0.22 HRO TF-01A microSD (drawing rev A): nine 0.70 x 1.30 contacts at 1.10 mm, four shell lands, two NPTH d1.00 at 8.00 mm.
card=fps['J401']
assert str(card.GetFPID().GetLibNickname())=='GrowBox' and str(card.GetFPID().GetLibItemName())=='microSD_HRO_TF-01A'
pads=numbered('J401')
assert set(pads)==set('123456789')|{'SH'} and len(pads['SH'])==4,('J401','TF-01A pads')
xs=[round(pcbnew.ToMM(pads[str(n)][0].GetFPRelativePosition().x),3) for n in range(1,10)]
assert all(abs(a-b-1.1)<.001 for a,b in zip(xs,xs[1:])) and all(size(pads[str(n)][0])==(.7,1.3) for n in range(1,10)),('J401','contact pitch/lands')
assert sorted(size(p) for p in pads['SH'])==[(1.2,1.4)]*2+[(1.2,2.0)]*2,('J401','shell lands')
holes=[p for p in card.Pads() if p.GetAttribute()==pcbnew.PAD_ATTRIB_NPTH]
assert len(holes)==2 and all(abs(pcbnew.ToMM(h.GetDrillSize().x)-1.0)<.001 for h in holes),('J401','locating holes')
assert abs(pcbnew.ToMM(abs(holes[0].GetFPRelativePosition().x-holes[1].GetFPRelativePosition().x))-8.0)<.001,('J401','hole pitch')
assert all(nodes[('J401',str(n))]!=gnd for n in (1,2,3,5,7,8)) and nodes[('J401','6')]==gnd and nodes[('J401','SH')]==gnd,('J401','pinout')
print('PASS: reviewed XT60 slots, DORABO/KANGNEX terminal holes, THT battery polarity, FXL0630 inductor lands and TF-01A microSD')
