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
for ref in ['Q901','Q711','Q721','Q731','Q601']:
 for pad in fps[ref].Pads():
  number=pad.GetNumber()
  if number:assert (ref,number) in nodes and pad.GetNetname()==nodes[(ref,number)],(ref,number)
 source_pins, gate, drain = (['3'], '1', '2') if ref in ['Q721','Q731'] else (['1','2','3'], '4', '5')
 source=[nodes[(ref,n)] for n in source_pins]
 assert len(set(source))==1,(ref,'source pads differ')
 assert len({source[0],nodes[(ref,gate)],nodes[(ref,drain)]})==3,(ref,'G/D/S short')
print(f'PASS: {len(fps)} footprints, {len(nodes)} nodes; every numbered power MOSFET pad checked')

# Pin mapping and copper dimensions from Diodes DS42130 Rev3 p6.
for ref in ['Q721','Q731']:
 pads={p.GetNumber():p for p in fps[ref].Pads() if p.GetNumber()}
 assert set(pads)=={'1','2','3'}, (ref,'DPAK pin count')
 for number, size in {'1':(1.06,2.6),'2':(5.632,5.7),'3':(1.06,2.6)}.items():
  got=pads[number].GetSize()
  assert abs(pcbnew.ToMM(got.x)-size[0])<0.001 and abs(pcbnew.ToMM(got.y)-size[1])<0.001,(ref,number,'pad geometry')
print('PASS: DPAK G1/D2/S3 pin mapping and manufacturer copper dimensions')
