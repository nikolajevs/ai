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

# TI SLPS583B top view: S1/2/3, G4, D5/6/7/8 plus exposed drain.
# Project DNH0008A footprint combines all drain copper under number 5.
pads=numbered('Q721')
assert str(fps['Q721'].GetFPID().GetLibItemName())=='TI_DNH0008A_CSD19538Q3A'
assert fps['Q721'].GetValue()=='CSD19538Q3A'
assert set(pads)=={'1','2','3','4','5'}, ('Q721','NexFET pin count')
for number in ['1','2','3','4']:
 assert len(pads[number])==1 and size(pads[number][0])==(.7,.4),('Q721',number,'pad geometry')
assert sorted(size(p) for p in pads['5'])==[(.835,.4)]*4+[(1.875,2.55)],('Q721','drain geometry')
for ps in pads.values():
 for p in ps:
  assert abs(pcbnew.ToMM(p.GetLocalSolderMaskMargin())+.05)<.001,('Q721','mask-defined land')
# TI SLPS483 (CSD19534Q5A, DQJ): project copy of KiCad VSONP-8 5x6 renumbered S1/2/3 G4 D5.
pads=numbered('Q711')
assert str(fps['Q711'].GetFPID().GetLibItemName())=='TI_DQJ0008A_CSD19534Q5A'
assert fps['Q711'].GetValue()=='CSD19534Q5A'
assert set(pads)=={'1','2','3','4','5'}, ('Q711','NexFET pin count')
for number in ['1','2','3','4']:
 assert len(pads[number])==1 and size(pads[number][0])==(.7,.7),('Q711',number,'pad geometry')
 assert abs(pcbnew.ToMM(pads[number][0].GetFPRelativePosition().x)+2.8)<.001,('Q711','S/G row')
assert sorted(size(p) for p in pads['5'])==[(.7,.7)]*4+[(4.35,4.51)],('Q711','drain geometry')
assert str(fps['U301'].GetFPID().GetLibItemName())=='SOIC-8_3.9x4.9mm_P1.27mm'
assert fps['U301'].GetValue()=='DS3231MZ+TRL'
assert {p.GetNumber() for p in fps['U301'].Pads()}==set('12345678')
print('PASS: NexFET S1/2/3 G4 D5 (Q711 DQJ, Q721 DNH) and SOIC-8 RTC package/pin mapping')

# Check selected LED passive packages, including the DPAK's otherwise unused lead.
for ref in ['D711','D721','L711','L721']:
 for pad in fps[ref].Pads():
  if pad.GetNumber():
   key=(ref,pad.GetNumber())
   assert key in nodes and pad.GetNetname()==nodes[key],key
assert nodes[('D711','2')]==nodes[('C716','1')]
assert nodes[('D711','3')]==nodes[('Q711','5')]
assert nodes[('D711','1')].startswith('unconnected-')
assert str(fps['D711'].GetFPID().GetLibItemName())=='TO-252-2'
assert str(fps['D721'].GetFPID().GetLibItemName())=='D_SOD-128'
for ref,sz in [('L711',(3.15,12.5)),('L721',(3.1,5.0)),('D721',(1.4,2.1))]:
 pads=[p for p in fps[ref].Pads() if p.GetNumber()]
 assert {p.GetNumber() for p in pads}=={'1','2'}
 for pad in pads:
  assert size(pad)==sz,(ref,'land dimensions')
assert str(fps['L721'].GetFPID().GetLibItemName())=='L_Bourns_SRP1265A'
assert str(fps['L711'].GetFPID().GetLibItemName())=='L_Bourns_SRP1770TA_16.9x16.9mm'
assert nodes[('J721','1')]==nodes[('J731','1')] and nodes[('J721','2')]==nodes[('J731','2')],'CH2 bars not paralleled'
print('PASS: all values/footprints agree; LED diode polarity/NC, CH2 parallel bars and selected passive lands checked')

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
assert str(fps['L902'].GetFPID().GetLibItemName())=='L_Bourns_SRP1265A'
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
assert str(fps['L101'].GetFPID().GetLibItemName())=='L_Bourns_SRP7028A_7.3x6.6mm'
assert fps['L101'].GetField('MPN').GetText()=='SRP7028A-100M'
assert all(size(pad)==(2.95,3.5) for pad in fps['L101'].Pads()),'SRP7028A lands'
print('PASS: reviewed XT60 slots, DORABO/KANGNEX terminal holes, THT battery polarity and SRP7028A lands')
