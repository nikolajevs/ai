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
nodes={}
for net in root.findall('.//nets/net'):
 for node in net.findall('node'):
  key=(node.get('ref'),node.get('pin'));nodes[key]=net.get('name')
  pads=[p for p in fps[key[0]].Pads() if p.GetNumber()==key[1]]
  assert pads and all(p.GetNetname()==net.get('name') for p in pads),key
for ref in ['U301','Q901','Q711','Q721','Q731','Q601']:
 for pad in fps[ref].Pads():
  number=pad.GetNumber()
  if number:assert (ref,number) in nodes and pad.GetNetname()==nodes[(ref,number)],(ref,number)
 if ref == 'U301':continue
 source_pins, gate, drain = ['1','2','3'], '4', '5'
 source=[nodes[(ref,n)] for n in source_pins]
 assert len(set(source))==1,(ref,'source pads differ')
 assert len({source[0],nodes[(ref,gate)],nodes[(ref,drain)]})==3,(ref,'G/D/S short')
print(f'PASS: {len(fps)} footprints, {len(nodes)} nodes; every numbered power MOSFET pad checked')

# TI SLPS583B top view: S1/2/3, G4, D5/6/7/8 plus exposed drain.
# Project DNH0008A footprint combines all drain copper under number 5.
for ref in ['Q721','Q731']:
 pads={}
 for p in fps[ref].Pads():
  if p.GetNumber():pads.setdefault(p.GetNumber(),[]).append(p)
 assert str(fps[ref].GetFPID().GetLibItemName())=='TI_DNH0008A_CSD19538Q3A'
 assert fps[ref].GetValue()=='CSD19538Q3A'
 assert set(pads)=={'1','2','3','4','5'}, (ref,'NexFET pin count')
 for number in ['1','2','3','4']:
  assert len(pads[number])==1
  got=pads[number][0].GetSize();size=(.7,.4)
  assert abs(pcbnew.ToMM(got.x)-size[0])<0.001 and abs(pcbnew.ToMM(got.y)-size[1])<0.001,(ref,number,'pad geometry')
 assert len(pads['5'])==5, (ref,'drain core plus four connected fingers')
 sizes=sorted((round(pcbnew.ToMM(p.GetSize().x),4),round(pcbnew.ToMM(p.GetSize().y),4)) for p in pads['5'])
 assert sizes==[(.835,.4)]*4+[(1.875,2.55)],(ref,'drain geometry')
 for ps in pads.values():
  for p in ps:
   assert abs(pcbnew.ToMM(p.GetLocalSolderMaskMargin())+.05)<.001,(ref,'mask-defined land')
assert str(fps['U301'].GetFPID().GetLibItemName())=='SOIC-8_3.9x4.9mm_P1.27mm'
assert fps['U301'].GetValue()=='DS3231MZ+TRL'
assert {p.GetNumber() for p in fps['U301'].Pads()}==set('12345678')
print('PASS: NexFET S1/2/3 G4 D5 and SOIC-8 RTC package/pin mapping')
