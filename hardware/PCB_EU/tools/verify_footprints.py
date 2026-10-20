#!/usr/bin/env python3
"""Check actual footprint files against symbol pads and manufacturer land sizes.

Uses the KiCad CLI to parse/plot the selected libraries. Does not prove physical
fit, solderability, thermal performance or a board layout. SPDX-License-Identifier: MIT
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parents[1]


def parse(text):
    stack=[];root=None
    for token in re.findall(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+', text):
        if token=='(':
            item=[]
            if stack:stack[-1].append(item)
            stack.append(item)
        elif token==')':
            root=stack.pop()
        else:
            stack[-1].append(json.loads(token) if token.startswith('"') else token)
    if stack or not isinstance(root,list):raise ValueError('Invalid S-expression')
    return root


def children(node, key):
    return [x for x in node if isinstance(x,list) and x and x[0]==key]


def child(node,key):
    found=children(node,key)
    if len(found)!=1:raise ValueError((key,len(found)))
    return found[0]


def values(node,key):return [float(x) for x in child(node,key)[1:]]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kicad-cli',required=True)
    ap.add_argument('--netlist',type=Path,default=HERE/'review/netlist.xml')
    ap.add_argument('--output',type=Path,default=HERE/'review/footprints.json')
    args=ap.parse_args()
    parts=[p for p in json.loads((HERE/'design.json').read_text())['parts'] if not p['ref'].startswith('#')]
    assignments=json.loads((HERE/'footprint_assignments.json').read_text())['assignments']
    actual={c.attrib['ref']:c.findtext('footprint') for c in ET.parse(args.netlist).findall('./components/comp')}
    cache={};checks=[]

    def check(label,condition):
        if not condition:raise AssertionError(label)
        checks.append(label)

    table=parse((HERE/'fp-lib-table').read_text())
    libs={child(lib,'name')[1]:child(lib,'uri')[1].replace('${KIPRJMOD}',str(HERE)) for lib in children(table,'lib')}
    for p in parts:
        ref=p['ref'];fp=p['footprint']
        check(f'{ref}: nonempty assigned footprint and exported schematic field agree',bool(fp) and actual.get(ref)==fp)
        lib,name=fp.split(':',1)
        check(f'{ref}: footprint library is project-local',lib in libs and Path(libs[lib]).resolve().is_relative_to(HERE))
        if fp not in cache:
            path=Path(libs[lib])/(name+'.kicad_mod')
            check(f'{fp}: source file exists',path.is_file())
            node=parse(path.read_text());pads=children(node,'pad')
            copper=[x for x in pads if any(y.endswith('.Cu') for y in child(x,'layers')[1:])]
            ids={str(x[1]) for x in copper if x[1]}
            cache[fp]={'node':node,'pads':pads,'copper':copper,'ids':ids,'path':path}
        check(f'{ref}: numbered copper pads match all symbol pins including NC',cache[fp]['ids']==set(p['nets']))
        if p['mpn'] in assignments:check(f'{ref}: exact MPN land assignment retained',assignments[p['mpn']]['footprint']==fp)

    def footprint(name):return cache['EU_Mechanical:'+name]
    def pads(name,number):return [x for x in footprint(name)['copper'] if str(x[1])==str(number)]
    def near(a,b):return len(a)==len(b) and all(abs(x-y)<1e-5 for x,y in zip(a,b))
    def geom(name,no,at,size):
        pp=pads(name,no)
        return len(pp)==1 and near(values(pp[0],'at')[:2],at) and near(values(pp[0],'size'),size)
    for name,size,pitch in [
            ('Fuse_Schurter_UMT250',[2,3.75],8.5),
            ('Fuse_Schurter_UST_USI1206_Reflow',[1.1,2],2.6),
            ('L_Jantek_JNRH1207',[4.2,9],8.2),
            ('L_Bourns_SRN6045',[2,6],4.3),
            ('Crystal_Abracon_ABS07',[1.1,1.9],2.5)]:
        check(name+': manufacturer land dimensions and inner gap',all(geom(name,no,[x,0],size) for no,x in [(1,-pitch/2),(2,pitch/2)]))
    name='HTSSOP-16-1EP_4.4x5mm_P0.65mm_EP3x3mm'
    check('L7987: counterclockwise 16 lead map, 0.65 pitch and 3x3 EP17',
          all(geom(name,i,[-2.875,-2.275+(i-1)*.65],[1.55,.4]) for i in range(1,9)) and
          all(geom(name,i,[2.875,2.275-(i-9)*.65],[1.55,.4]) for i in range(9,17)) and geom(name,17,[0,0],[3,3]))
    # Verify the imported geometry still matches the attributed upstream blobs.
    for name,sha in [('Fuse_Schurter_UMT250','cbb208235980bc128463c367f6f680e68beb9030'),
                     ('HTSSOP-16-1EP_4.4x5mm_P0.65mm_EP3x3mm','3e3c314a9d47be6f4bea83ce8ed1b0ffd3de7064')]:
        raw=footprint(name)['path'].read_bytes()
        check(name+': unchanged upstream Git blob',hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==sha)
    name='TI_PWP0014A_LM3429'
    check('LM3429: TI 14-lead map, 0.65 pitch, 5.8 opposing-row pitch and 3.4x5 copper EP15',
          all(geom(name,i+1,[-2.9,-1.95+i*.65],[1.5,.45]) and geom(name,14-i,[2.9,-1.95+i*.65],[1.5,.45]) for i in range(7)) and geom(name,15,[0,0],[3.4,5]))
    apertures=[p for p in footprint(name)['pads'] if not p[1]]
    check('LM3429: mask-defined 3.155x3.255 EP and 0.125 mm stencil example',len(apertures)==1 and near(values(apertures[0],'size'),[3.155,3.255]) and set(child(apertures[0],'layers')[1:])=={'F.Mask','F.Paste'} and child(pads(name,15)[0],'layers')[1:]==['F.Cu'])
    name='Battery_COMF_BC-2001'
    check('BC-2001: positive side tabs at +/-12.95 and separate negative 4x4 contact without paste',
          len(pads(name,1))==2 and all(near(values(p,'size'),[5.2,5.2]) for p in pads(name,1)) and
          sorted(values(p,'at')[0] for p in pads(name,1))==[-12.95,12.95] and geom(name,2,[0,0],[4,4]) and 'F.Paste' not in child(pads(name,2)[0],'layers'))
    check('BC-2001: other top copper under the cell is excluded',len(children(footprint(name)['node'],'zone'))==4)
    name='SW_Ninigi_TACTB-64K-F'
    check('TACTB: 1.8x1.1 lands; electrical pairs occupy separate rows',all(len(pads(name,no))==2 and all(near(values(p,'size'),[1.8,1.1]) and near(values(p,'at')[:2],[x,y]) for p,x in zip(sorted(pads(name,no),key=lambda p:values(p,'at')[0]),[-3.1,3.1])) for no,y in [(1,-1.85),(2,1.85)]))
    for family,drill in [('DG301R',1.2),('DG306',1.4)]:
        name=f'TerminalBlock_Degson_{family}-5.0_1x02'
        check(f'{family}: 5 mm pitch and manufacturer finished hole diameter {drill}',
              all(near(values(pads(name,no)[0],'at')[:2],[x,0]) and near(values(pads(name,no)[0],'drill'),[drill]) for no,x in [(1,0),(2,5)]))
    name='microSD_GCT_MEM2061-01-188-00-A'
    check('MEM2061: component-side P8-to-P1 order and staggered signal lands',all(geom(name,i,[8.94-(i-1)*1.1,10.55 if i==2 else (11.15 if i in [4,6] else 10.95)],[.8,2]) for i in range(1,9)))
    check('MEM2061: two ground tabs and separate unused CD contact pads',len(pads(name,'SH'))==2 and geom(name,'CD1',[2.05,.4],[1.8,1.4]) and geom(name,'CD2',[7.75,.4],[1.8,1.4]) and next(p for p in parts if p['ref']=='J301')['nets']['CD1'] is None and next(p for p in parts if p['ref']=='J301')['nets']['CD2'] is None)
    zone=child(footprint(name)['node'],'zone')
    points=child(child(zone,'polygon'),'pts')[1:]
    check('MEM2061: manufacturer contact keepout retained',near([float(c) for xy in points for c in xy[1:]],[0,2.55,10.37,2.55,10.37,4.63,0,4.63]) and child(zone,'layers')[1:]==['F.Cu'])

    # Independent geometric screen over all assigned pads. Rotated rectangles
    # use their projected bounding box; same-number copper pieces may overlap.
    min_gap=math.inf
    for fp,entry in cache.items():
        cp=entry['copper']
        def box(p):
            at=values(p,'at');x,y=at[:2];angle=math.radians(at[2] if len(at)>2 else 0)
            sx,sy=values(p,'size');c=abs(math.cos(angle));s=abs(math.sin(angle))
            return x,y,(c*sx+s*sy)/2,(s*sx+c*sy)/2
        for i,a in enumerate(cp):
            for b in cp[i+1:]:
                if a[1]==b[1]:continue
                ax,ay,aw,ah=box(a);bx,by,bw,bh=box(b)
                gap=math.hypot(max(abs(ax-bx)-aw-bw,0),max(abs(ay-by)-ah-bh,0))
                min_gap=min(min_gap,gap)
                check(f'{fp}: pads {a[1]} / {b[1]} copper gap >=0.15 mm',gap>=.15-1e-6)
    # Native KiCad loading and plotting reject malformed / unsupported sources.
    with tempfile.TemporaryDirectory(prefix='eu-footprints-') as temp:
        for lib in sorted({p['footprint'].split(':')[0] for p in parts}):
            dest=Path(temp)/lib;dest.mkdir()
            subprocess.run([args.kicad_cli,'fp','export','svg','--layers','F.Cu,F.Fab,F.CrtYd','--sketch-pads-on-fab-layers','--output',str(dest),libs[lib]],check=True,stdout=subprocess.DEVNULL)
            expected={p['footprint'].split(':')[1] for p in parts if p['footprint'].split(':')[0]==lib}
            check(lib+': native KiCad plots every assigned footprint',expected<={p.stem for p in dest.glob('*.svg')})
    reviewed=[p['ref'] for p in parts if p['mpn'] in assignments]
    result={'status':'drawing/pad-map checks; no board placement, routing, thermal or physical-fit qualification',
            'kicad_version':subprocess.check_output([args.kicad_cli,'version'],text=True).strip(),
            'components_with_footprints':len(parts),'missing_footprints':[],
            'unique_assigned_footprints':len(cache),'drawing_checked_references':reviewed,
            'other_package_assignments_still_require_datasheet_review':len(parts)-len(reviewed),
            'minimum_distinct_pad_bounding_box_gap_mm':round(min_gap,6),'checks_passed':len(checks),
            'source_sha256':{str(e['path'].relative_to(HERE)):hashlib.sha256(e['path'].read_bytes()).hexdigest() for e in cache.values()}}
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(f'PASS | footprints | {len(parts)} references, {len(cache)} lands, {len(reviewed)} drawing-checked references; {len(checks)} checks')


if __name__=='__main__':main()
