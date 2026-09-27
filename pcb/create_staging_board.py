"""Create an unrouted staging board from a checked KiCad XML netlist.
Run using KiCad's bundled Python. Refuses to overwrite an existing populated board.
"""
from pathlib import Path
import sys, re, xml.etree.ElementTree as ET
import pcbnew as p
xml, output, libs = map(Path, sys.argv[1:4])
if output.exists() and len(p.LoadBoard(str(output)).GetFootprints()):
    raise SystemExit('Refusing to overwrite a populated board')
r=ET.parse(xml).getroot()
comps=r.findall('./components/comp')
assert len({c.get('ref') for c in comps})==len(comps)
b=p.BOARD();b.SetCopperLayerCount(4)
def point(x,y): return p.VECTOR2I(p.FromMM(x),p.FromMM(y))
for a,z in [((50,50),(150,50)),((150,50),(150,150)),((150,150),(50,150)),((50,150),(50,50))]:
 s=p.PCB_SHAPE();s.SetShape(p.SHAPE_T_SEGMENT);s.SetStart(point(*a));s.SetEnd(point(*z));s.SetLayer(p.Edge_Cuts);s.SetWidth(p.FromMM(.05));b.Add(s)
def label(txt,x,y):
 s=p.PCB_TEXT(b);s.SetText(txt);s.SetPosition(point(x,y));s.SetLayer(p.Dwgs_User);s.SetTextSize(point(1.5,1.5));b.Add(s)
label('100 x 100 mm / 4 Cu layers / UNROUTED DRAFT',100,45)
label('Candidate footprints staged outside outline',100,155)
rootuuid=re.search(r'\(uuid "([^"]+)"',output.with_suffix('.kicad_sch').read_text(encoding='utf-8')).group(1)
groups={}
for c in comps: groups.setdefault(c.find('sheetpath').get('names'),[]).append(c)
fps={}
for gi,(sheet,items) in enumerate(groups.items()):
 gx=175+(gi%3)*270;gy=50+(gi//3)*550
 label(sheet,gx+55,gy-10)
 for i,c in enumerate(items):
  lib,name=c.findtext('footprint').split(':',1)
  fp=p.FootprintLoad(str(libs/(lib+'.pretty')),name)
  assert fp, c.get('ref')
  fp.SetReference(c.get('ref'));fp.SetValue(c.findtext('value'));fp.SetPosition(point(gx+(i%5)*50,gy+(i//5)*50))
  path=p.KIID_PATH()
  for u in [rootuuid]+[u for u in c.find('sheetpath').get('tstamps').split('/') if u]+[c.findtext('tstamps')]:path.push_back(p.KIID(u))
  fp.SetPath(path);b.Add(fp);fps[c.get('ref')]=fp
for n in r.findall('./nets/net'):
 net=p.NETINFO_ITEM(b,n.get('name'));b.Add(net)
 for node in n.findall('node'):
  pads=[pad for pad in fps[node.get('ref')].Pads() if pad.GetNumber()==node.get('pin')]
  assert pads,(node.attrib,'missing footprint pad')
  for pad in pads:pad.SetNet(net)
p.SaveBoard(str(output),b)
check=p.LoadBoard(str(output));assert len(check.GetFootprints())==len(comps)
assert check.GetCopperLayerCount()==4
print(f'Created {len(comps)} footprints; four copper layers; 100x100 mm outline; no routed tracks')
