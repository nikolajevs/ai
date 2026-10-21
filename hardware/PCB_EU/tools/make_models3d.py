#!/usr/bin/env python3
"""Own simplified AP214 component models. Requires CadQuery 2.7.0.

All dimensions are mm: STEP X=footprint X, STEP Y=-footprint Y, Z=0 is
the component-side PCB face. KiCad, not this script, flips bottom parts.
Bodies follow the cited drawings; undimensioned moulding/contact details
are illustrative. These are placement models, not manufacturing CAD.
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import re

import cadquery as cq
from OCP.Interface import Interface_Static

HERE = Path(__file__).resolve().parents[1]
OUT = HERE / 'libraries/EU.3dshapes'
BLACK = cq.Color(.10, .11, .12)
FERRITE = cq.Color(.22, .23, .24)
METAL = cq.Color(.72, .74, .76)
GREEN = cq.Color(.03, .40, .22)
BLUE = cq.Color(.06, .20, .37)
GOLD = cq.Color(.78, .57, .13)
CERAMIC = cq.Color(.78, .73, .58)


def box(x, y, z, dx, dy, dz):
    return cq.Workplane('XY').box(dx, dy, dz, centered=False).translate((x, y, z))


def cyl(x, y, z, radius, height):
    return cq.Workplane('XY').circle(radius).extrude(height).translate((x, y, z))


@dataclass
class Model:
    name: str
    assembly: cq.Assembly
    bounds: tuple[float, float, float, float, float, float]
    footprint: str | None = None
    # Bottom contact sections only, not the whole gull-wing bend.
    contacts: list[tuple[str, cq.Workplane]] = field(default_factory=list)
    issue: str | None = None


def add(a, s, name, color):
    a.add(s, name=name, color=color)


def chip_fuse():
    name = 'Fuse_Schurter_UST_USI1206'
    a = cq.Assembly(name=name)
    add(a, box(-1.6, -.8, .08, 3.2, 1.6, .52), 'ceramic', CERAMIC)
    contacts = []
    for no, x in [('1', -1.6), ('2', 1.1)]:
        s = box(x, -.8, 0, .5, 1.6, .60)
        add(a, s, 'terminal_' + no, METAL)
        contacts.append((no, box(x, -.8, 0, .5, 1.6, .08)))
    return Model(name, a, (-1.6, 1.6, -.8, .8, 0, .6),
                 'EU_Mechanical:Fuse_Schurter_UST_USI1206_Reflow', contacts)


def umt_fuse():
    name = 'Fuse_Schurter_UMT250'
    a = cq.Assembly(name=name)
    add(a, box(-5.05, -1.5, .08, 10.1, 3, 2.92), 'ceramic', CERAMIC)
    contacts = []
    for no, x in [('1', -5.05), ('2', 3.45)]:
        s = box(x, -1.5, 0, 1.6, 3, 3)
        add(a, s, 'terminal_' + no, METAL)
        contacts.append((no, box(x, -1.5, 0, 1.6, 3, .08)))
    return Model(name, a, (-5.05, 5.05, -1.5, 1.5, 0, 3),
                 'EU_Mechanical:Fuse_Schurter_UMT250', contacts)


def inductor(name, size, height, terminal_x, terminal_w, terminal_y, footprint):
    a = cq.Assembly(name=name)
    body = box(-size/2, -size/2, .15, size, size, height-.15)
    body = body.edges('|Z').fillet(.35 if size < 7 else .7)
    add(a, body, 'coated_ferrite', FERRITE)
    contacts = []
    for no, x in [('1', -terminal_x), ('2', terminal_x)]:
        s = box(x-terminal_w/2, -terminal_y/2, 0, terminal_w, terminal_y, .2)
        add(a, s, 'terminal_' + no, METAL)
        contacts.append((no, s))
    return Model(name, a, (-size/2, size/2, -size/2, size/2, 0, height), footprint, contacts)


def crystal():
    name = 'Crystal_Abracon_ABS07'
    a = cq.Assembly(name=name)
    add(a, box(-1.6, -.75, .08, 3.2, 1.5, .42), 'ceramic', BLACK)
    lid = box(-1.6, -.75, .50, 3.2, 1.5, .40).edges('|Z').fillet(.12)
    add(a, lid, 'seam_sealed_lid', METAL)
    contacts = []
    for no, x in [('1', -1.6), ('2', .95)]:
        s = box(x, -.6, 0, .65, 1.2, .10)
        add(a, s, 'terminal_' + no, GOLD)
        contacts.append((no, s))
    return Model(name, a, (-1.6, 1.6, -.75, .75, 0, .9),
                 'EU_Mechanical:Crystal_Abracon_ABS07', contacts)


def tssop(name, leads, ep_x, ep_y, footprint):
    a = cq.Assembly(name=name)
    body = box(-2.2, -2.5, .15, 4.4, 5, 1.05).edges('|Z').fillet(.10)
    body = body.cut(cyl(-1.55, 1.8, 1.16, .20, .10))
    add(a, body, 'moulding_pin1_dimple', BLACK)
    contacts = []
    count = leads//2
    for i in range(count):
        y = (count-1)*.65/2-i*.65
        for sign, no in [(-1, i+1), (1, leads-i)]:
            # Simplified bent lead; toe is 0.6 long, maximum spread 6.6.
            poly = [(2.15,.50),(2.45,.50),(2.75,0),(3.3,0),
                    (3.3,.15),(2.84,.15),(2.54,.65),(2.15,.65)]
            poly = [(sign*x,z) for x,z in poly]
            pin = cq.Workplane('XZ').polyline(poly).close().extrude(.245)
            pin = pin.translate((0,y+.245/2,0))
            add(a, pin, f'lead_{no}', METAL)
            x = -3.3 if sign < 0 else 2.75
            contacts.append((str(no), box(x,y-.245/2,0,.55,.245,.15)))
    ep = box(-ep_x/2, -ep_y/2, 0, ep_x, ep_y, .15)
    add(a, ep, 'exposed_pad', METAL)
    contacts.append((str(leads+1),ep))
    return Model(name, a, (-3.3,3.3,-2.5,2.5,0,1.2), footprint, contacts)


def tactile():
    name = 'SW_Ninigi_TACTB-64K-F'
    a = cq.Assembly(name=name)
    body = box(-2.6,-2.6,.15,5.2,5.2,.80).edges('|Z').chamfer(.65)
    lid = box(-2.5,-2.5,.95,5,5,.25).edges('|Z').chamfer(.65)
    lid = lid.cut(cyl(0,0,.9,1.52,.4))
    add(a, body, 'housing', BLACK)
    add(a, lid, 'cover', METAL)
    add(a, cyl(0,0,1.05,1.5,.45), 'actuator', GOLD)
    contacts = []
    for no, y in [('1',1.85),('2',-1.85)]:
        for side, x in enumerate([-3.2,2.2]):
            s = box(x,y-.4,0,1,.8,.15)
            add(a,s,f'tail_{no}_{side}',METAL)
            contacts.append((no,s))
    return Model(name,a,(-3.2,3.2,-2.6,2.6,0,1.5),
                 'EU_Mechanical:SW_Ninigi_TACTB-64K-F',contacts)


def terminal(family):
    name = f'TerminalBlock_Degson_{family}-5.0_1x02'
    height, depth, row, tail = (7.6,10,2.65,4.6) if family=='DG301R' else (10,7.6,4.5,3.9)
    a = cq.Assembly(name=name)
    # The wire face is at negative STEP Y (positive footprint Y).
    front, back = depth-row, row
    outline = [(-front,0),(back,0),(back,height*.88),
               (back-1.4,height),(-front+1.5,height),(-front,height*.90)]
    body = cq.Workplane('YZ').polyline(outline).close().extrude(10).translate((-2.5,0,0))
    contacts = []
    for i,x in enumerate((0,5),1):
        body = body.cut(box(x-1.55,-front-.05,1.3,3.1,2,height*.40))
        body = body.cut(cyl(x,0,height-1.1,1.5,1.2))
        screw = cyl(x,0,height-1.0,1.30,.70)
        screw = screw.cut(box(x-1.4,-.17,height-.65,2.8,.34,.45))
        add(a,screw,f'slotted_screw_{i}',METAL)
        add(a,box(x-1.15,-front+1.2,1.6,2.3,.2,height*.28),f'cage_{i}',METAL)
        if family=='DG301R':pin=cyl(x,0,-tail,.5,tail+.4)
        else:pin=box(x-.5,-.4,-tail,1,.8,tail+.4)
        add(a,pin,f'tail_{i}',METAL)
        contacts.append((str(i),pin))
    lock_x = 7.5 if family=='DG301R' else -3.1
    body = body.union(box(lock_x,back-1.1,.8,.6,.8,height*.5))
    add(a,body,'housing',GREEN)
    x0,x1 = (-2.5,8.1) if family=='DG301R' else (-3.1,7.5)
    return Model(name,a,(x0,x1,-front,back,-tail,height),f'EU_Mechanical:{name}',contacts)


def battery():
    name = 'Battery_COMF_BC-2001_with_CR2032'
    a = cq.Assembly(name=name)
    cell = cyl(0,0,.1,10,3.2)
    add(a,cell,'CR2032_installed_nominal',METAL)
    outline = [(-10.55,-6),(-10.55,6),(-7,9.9),(-3.75,9.9),
               (3.75,9.9),(10.55,6),(10.55,-6),(7,-9.9),(-7,-9.9)]
    clip = cq.Workplane('XY').polyline(outline).close().extrude(.3).translate((0,0,3.55))
    for x in (-5.5,5.5):
        clip = clip.cut(cyl(x,-1.5,3.5,2.2,.5))
        clip = clip.cut(box(x-1.5,-1.5,3.5,3,7,.5))
        add(a,box(x-1.1,-1.5,3.35,2.2,6.5,.3),'spring_'+str(x),METAL)
    contacts = []
    for i,x in enumerate((-12.95,12.95)):
        tab = box(x-2.3,-2.55,0,4.6,5.1,.3)
        add(a,tab,f'positive_tab_{i}',METAL)
        contacts.append(('1',tab))
        sx = -10.55 if x<0 else 10.25
        clip = clip.union(box(sx,-2.55,.25,.3,5.1,3.30))
    add(a,clip,'positive_clip',METAL)
    # The centre negative contact is PCB copper, not another holder terminal.
    return Model(name,a,(-15.25,15.25,-10,10,0,3.85),
                 'EU_Mechanical:Battery_COMF_BC-2001',contacts)


def microsd():
    name = 'microSD_GCT_MEM2061-01-188-00-A'
    a = cq.Assembly(name=name)
    add(a,box(.4,-14.8,.12,12.9,14.4,.38),'plastic_base',BLACK)
    shell = box(0,-15.45,1.63,14,15.45,.25)
    shell = shell.cut(box(.9,-15.5,1.5,10.5,5.7,.6))
    # Stamped roof slots, wall details and latch mechanics are illustrative.
    for x in (1.6,7.4):shell=shell.cut(box(x,-7,1.5,.6,5.5,.6))
    shell = shell.union(box(0,-15.45,.15,.2,15.45,1.5))
    shell = shell.union(box(13.8,-15.45,.15,.2,15.45,1.5))
    shell = shell.union(box(0,-.2,.15,14,.2,1.5))
    add(a,shell,'stainless_shell',METAL)
    contacts = []
    for no in range(1,9):
        x = 8.94-(no-1)*1.1
        y = -(10.55 if no==2 else 11.15 if no in (4,6) else 10.95)
        toe = box(x-.20,y-.65,0,.40,1.3,.15)
        add(a,toe,f'signal_{no}',GOLD)
        contacts.append((str(no),toe))
        add(a,box(x-.18,y-.4,.15,.36,3.8,.20),f'contact_{no}',GOLD)
    for no,x,y,w,d in [('CD1',2.05,-.4,1.0,.9),('CD2',7.75,-.4,1.0,.9),
                         ('SH',.45,-13.55,.9,1.4),('SH',13.6,-14.55,.9,1.4)]:
        toe=box(x-w/2,y-d/2,0,w,d,.15)
        add(a,toe,f'toe_{no}_{x}',METAL)
        contacts.append((no,toe))
    return Model(name,a,(0,14.05,-15.45,.05,0,1.88),
                 'EU_Mechanical:microSD_GCT_MEM2061-01-188-00-A',contacts)


def radial(name,diameter,length,pitch,wire,footprint,issue=None):
    a=cq.Assembly(name=name)
    x=pitch/2
    sleeve=cyl(x,0,.15,diameter/2,length-.10)
    stripe=sleeve.intersect(box(x+diameter*.37,-diameter/2,.15,
                               diameter*.13,diameter,length-.10))
    add(a,sleeve.cut(stripe),'sleeve',BLUE)
    add(a,stripe,'negative_stripe',cq.Color(.73,.75,.77))
    top=cyl(x,0,length+.05,diameter/2-.18,.10)
    for dx,dy in ((diameter,.08),(.08,diameter)):
        top=top.cut(box(x-dx/2,-dy/2,length+.12,dx,dy,.06))
    add(a,top,'top_cap_pressure_vent',METAL)
    # Nominal body length; 0.15 mm mounting standoff is an assembly assumption.
    contacts=[]
    for no,px in [('1',0),('2',pitch)]:
        lead=cyl(px,0,-3,wire/2,3.25)
        add(a,lead,'lead_'+no,METAL);contacts.append((no,lead))
    return Model(name,a,(x-diameter/2,x+diameter/2,-diameter/2,diameter/2,-3,length+.15),
                 footprint,contacts,issue)


def heatsink_envelope():
    name='RAD-DY-GF_3_ENVELOPE_ONLY_30x30x15'
    a=cq.Assembly(name=name)
    # No invented fin, guide, hole or TO-220 screw geometry. Not attached to PCB.
    add(a,box(-15,-15,0,30,30,15),'UNQUALIFIED_ENVELOPE',cq.Color(.75,.32,.10,.35))
    return Model(name,a,(-15,15,-15,15,0,15))


def models():
    return [chip_fuse(),umt_fuse(),
            inductor('L_Jantek_JNRH1207',12.5,8.05,4.10,3.50,7.5,'EU_Mechanical:L_Jantek_JNRH1207'),
            inductor('L_Bourns_SRN6045',6.2,4.5,2.15,1.8,5.5,'EU_Mechanical:L_Bourns_SRN6045'),
            crystal(),tssop('TI_PWP0014A_LM3429',14,3.155,3.255,'EU_Mechanical:TI_PWP0014A_LM3429'),
            tssop('ST_HTSSOP16_L7987',16,3,3,'EU_Mechanical:HTSSOP-16-1EP_4.4x5mm_P0.65mm_EP3x3mm'),
            tactile(),terminal('DG301R'),terminal('DG306'),battery(),microsd(),
            radial('Nichicon_UPW1H221MPD_D10_L16_P5',10,16,5,.6,'Capacitor_THT:CP_Radial_D10.0mm_P5.00mm'),
            radial('Panasonic_EEUFR1E102_D10_L20_P5',10,20,5,.6,'Capacitor_THT:CP_Radial_D10.0mm_P5.00mm'),
            radial('Panasonic_EEUFR1J101LB_D8_L15_P5',8,15,5,.6,'Capacitor_THT:CP_Radial_D8.0mm_P3.50mm',
                   'EEUFR1J101LB taped B leads are 5 mm; PCB holes are 3.5 mm. Physical fit is NOT verified.'),
            heatsink_envelope()]


def export(model):
    path=OUT/(model.name+'.step')
    Interface_Static.SetCVal_s('write.step.schema','AP214IS')
    model.assembly.save(str(path),exportType='STEP',mode='default',write_pcurves=False)
    text=path.read_text()
    text=re.sub(r"FILE_NAME\('.*?',\s*'.*?'",f"FILE_NAME('{path.name}','2026-10-21T00:00:00'",text,count=1)
    path.write_text('\n'.join(line.rstrip() for line in text.splitlines())+'\n')


def check(model):
    from verify_footprints import parse,children,child,values
    path=OUT/(model.name+'.step')
    raw=path.read_text()
    assert 'AUTOMOTIVE_DESIGN' in raw and 'SI_UNIT(.MILLI.,.METRE.)' in raw,(model.name,'AP214/mm')
    shape=cq.importers.importStep(str(path)).val()
    assert shape.isValid() and shape.Volume()>0,(model.name,'invalid solid')
    bb=shape.BoundingBox()
    got=(bb.xmin,bb.xmax,bb.ymin,bb.ymax,bb.zmin,bb.zmax)
    assert all(abs(a-b)<.002 for a,b in zip(got,model.bounds)),(model.name,got,model.bounds)
    issue=None
    if model.footprint:
        lib,name=model.footprint.split(':')
        table=parse((HERE/'fp-lib-table').read_text())
        libs={child(v,'name')[1]:child(v,'uri')[1] for v in children(table,'lib')}
        fp=Path(libs[lib].replace('${KIPRJMOD}',str(HERE)))/(name+'.kicad_mod')
        pads=children(parse(fp.read_text()),'pad')
        failures=[]
        for no,contact in model.contacts:
            b=contact.val().BoundingBox();x,y=(b.xmin+b.xmax)/2,(b.ymin+b.ymax)/2
            candidates=[p for p in pads if p[1]==no]
            nearest=min(candidates,key=lambda p:math.hypot(values(p,'at')[0]-x,values(p,'at')[1]+y))
            px,py=values(nearest,'at')[:2];sx,sy=values(nearest,'size')
            dx,dy=abs(x-px),abs(y+py)
            if nearest[2]=='smd':ok=dx+b.xlen/2<=sx/2+.001 and dy+b.ylen/2<=sy/2+.001
            else:
                drill=values(nearest,'drill')[0]/2
                # Circular leads use radius; rectangular tails use corner reach.
                round_wire=model.name.startswith(('Nichicon_','Panasonic_')) or 'DG301R' in model.name
                reach=math.hypot(dx,dy)+b.xlen/2 if round_wire else math.hypot(dx+b.xlen/2,dy+b.ylen/2)
                ok=reach<=drill+.001
            if not ok:failures.append(no)
        if model.issue:
            assert failures==['2'],(model.name,'expected pitch discrepancy no longer matches',failures)
            issue=model.issue
        else:assert not failures,(model.name,'terminals outside lands/holes',failures)
    return dict(model=path.name,valid_AP214_mm=True,bounds_mm=[round(v,4) for v in got],
                contact_sections=len(model.contacts),known_fit_issue=issue)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--check',action='store_true',help='Read existing STEP files without overwriting them')
    ap.add_argument('--output',type=Path,help='Write check results here')
    args=ap.parse_args();OUT.mkdir(exist_ok=True)
    result=[]
    for model in models():
        if not args.check:export(model)
        result.append(check(model))
        print(('KNOWN FIT ISSUE' if result[-1]['known_fit_issue'] else 'PASS')+' '+model.name,flush=True)
    manifest=HERE/'models3d.json'
    if not args.check and manifest.exists():
        cfg=json.loads(manifest.read_text())
        for row in result:
            record=cfg['models'][row['model']]
            assert record['origin']=='project-generated',row['model']
            record['sha256']=hashlib.sha256((OUT/row['model']).read_bytes()).hexdigest()
            record['geometry_check']=row
        manifest.write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n')
    if args.output:args.output.write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
