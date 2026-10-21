#!/usr/bin/env python3
"""Generate project-specific lands from the drawings in libraries/SOURCES.md.

Dimensions are millimetres, viewed from the component side. This does not
qualify an assembled part or a routed PCB. SPDX-License-Identifier: MIT
"""
from pathlib import Path
import json

HERE = Path(__file__).resolve().parents[1]
LIB = HERE / 'libraries/EU_Mechanical.pretty'


def n(v):
    return f'{v:.5f}'.rstrip('0').rstrip('.') if v else '0'


def q(v):
    return json.dumps(str(v))


class Footprint:
    def __init__(self, name, description, height, tht=False):
        self.name = name
        self.reference_at = (0, -5)
        self.items = [f'(footprint {q(name)} (version 20241229) (generator "pcbnew")',
                      '(layer "F.Cu")', f'(descr {q(description + "; height " + str(height) + " mm")})',
                      f'(attr {"through_hole" if tht else "smd"})',
                      '(property "Reference" "REF**" (at 0 -5 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))',
                      f'(property "Value" {q(name)} (at 0 5 0) (layer "F.Fab") (hide yes) (effects (font (size 1 1) (thickness 0.15))))']

    def line(self, x1, y1, x2, y2, layer='F.SilkS', width=.12):
        self.items.append(f'(fp_line (start {n(x1)} {n(y1)}) (end {n(x2)} {n(y2)}) (stroke (width {n(width)}) (type solid)) (layer {q(layer)}))')

    def rect(self, x1, y1, x2, y2, layer='F.Fab', width=.1):
        if layer == 'F.CrtYd': self.reference_at = ((x1+x2)/2, y1-1.1)
        self.items.append(f'(fp_rect (start {n(x1)} {n(y1)}) (end {n(x2)} {n(y2)}) (stroke (width {n(width)}) (type solid)) (fill none) (layer {q(layer)}))')

    def circle(self, x, y, r, layer='F.SilkS'):
        self.items.append(f'(fp_circle (center {n(x)} {n(y)}) (end {n(x+r)} {n(y)}) (stroke (width 0.12) (type solid)) (fill none) (layer {q(layer)}))')

    def text(self, value, x, y, layer='F.Fab', size=.8):
        self.items.append(f'(fp_text user {q(value)} (at {n(x)} {n(y)}) (layer {q(layer)}) (effects (font (size {n(size)} {n(size)}) (thickness 0.12))))')

    def pad(self, number, x, y, sx, sy, layers='"F.Cu" "F.Paste" "F.Mask"', drill=None, shape='rect'):
        typ = 'smd' if drill is None else 'thru_hole'
        hole = '' if drill is None else f'(drill {n(drill)})'
        self.items.append(f'(pad {q(number)} {typ} {shape} (at {n(x)} {n(y)}) (size {n(sx)} {n(sy)}) {hole} (layers {layers}))')

    def keepout(self, x1, y1, x2, y2, layers='"F.Cu"'):
        self.items.append(f'(zone (layers {layers}) (hatch edge 0.5) (connect_pads (clearance 0)) (min_thickness 0.25) (keepout (tracks not_allowed) (vias not_allowed) (pads not_allowed) (copperpour not_allowed) (footprints allowed)) (polygon (pts (xy {n(x1)} {n(y1)}) (xy {n(x2)} {n(y1)}) (xy {n(x2)} {n(y2)}) (xy {n(x1)} {n(y2)}))))')

    def save(self):
        from models3d import config, replace_model, PREFIX
        x,y = self.reference_at
        content = '\n'.join(self.items)+')\n'
        content = content.replace('(at 0 -5 0)', f'(at {n(x)} {n(y)} 0)', 1)
        mapping = config()['footprints']
        content = replace_model(content, PREFIX + mapping['EU_Mechanical:' + self.name])
        (LIB/(self.name+'.kicad_mod')).write_text(content)


def two_pad(name, description, body_x, body_y, pad_w, pad_h, gap, height):
    fp = Footprint(name, description, height)
    pitch = gap + pad_w
    for no, x in [(1,-pitch/2),(2,pitch/2)]:fp.pad(no,x,0,pad_w,pad_h)
    fp.rect(-body_x/2,-body_y/2,body_x/2,body_y/2)
    xmax = max(body_x/2,(gap+2*pad_w)/2)+.25
    ymax = max(body_y/2,pad_h/2)+.25
    fp.rect(-xmax,-ymax,xmax,ymax,'F.CrtYd',.05)
    for y in [-max(body_y,pad_h)/2-.3,max(body_y,pad_h)/2+.3]:fp.line(-body_x/2,y,body_x/2,y)
    fp.save()


def main():
    LIB.mkdir(exist_ok=True)
    two_pad('Fuse_Schurter_UST_USI1206_Reflow','SCHURTER UST <=25A / USI 1206; reflow recommendation; not the >25A UST variant',3.2,1.6,1.1,2,1.5,.6)
    two_pad('L_Jantek_JNRH1207','Jantek JNRH1207 100N/220M/330M rev A; D=4.2 E=4 F=9; 12.5 max body',12.5,12.5,4.2,9,4,8.05)
    two_pad('L_Bourns_SRN6045','Bourns SRN6045 (not SRN6045TA); recommended layout 2 x 6, gap 2.3',6.2,6.2,2,6,2.3,4.5)
    two_pad('Crystal_Abracon_ABS07','Abracon ABS07 rev 08-10-22; 1.1 x 1.9 lands, gap 1.4',3.3,1.6,1.1,1.9,1.4,.9)

    fp = Footprint('TI_PWP0014A_LM3429','TI PWP0014A drawing 4214867/A 09/2016; mask-defined EP; 0.125 mm stencil example; add board-specific thermal vias',1.2)
    for i in range(7):
        fp.pad(i+1,-2.9,-1.95+i*.65,1.5,.45)
        fp.pad(14-i,2.9,-1.95+i*.65,1.5,.45)
    fp.pad(15,0,0,3.4,5,layers='"F.Cu"')
    fp.pad('',0,0,3.155,3.255,layers='"F.Mask" "F.Paste"')
    fp.rect(-2.2,-2.5,2.2,2.5)
    fp.rect(-3.9,-2.8,3.9,2.8,'F.CrtYd',.05)
    fp.line(-2.2,-2.7,2.2,-2.7);fp.line(-2.2,2.7,2.2,2.7)
    fp.circle(-3.7,-2.6,.15);fp.text('15 GND',0,0)
    fp.save()

    fp = Footprint('SW_Ninigi_TACTB-64K-F','Ninigi TACTB-64K-F, image_15200; 1/2 upper contact, 3/4 lower contact; pad IDs denote the two electrical pairs',1.5)
    for no,y in [(1,-1.85),(2,1.85)]:
        for x in [-3.1,3.1]:fp.pad(no,x,y,1.8,1.1)
    fp.rect(-2.6,-2.6,2.6,2.6)
    fp.circle(0,0,1.5,'F.Fab')
    fp.rect(-4.3,-2.9,4.3,2.9,'F.CrtYd',.05)
    fp.line(-2.6,-2.8,2.6,-2.8);fp.line(-2.6,2.8,2.6,2.8)
    fp.save()

    fp = Footprint('Battery_COMF_BC-2001','COMF BC-2001: two positive clip tabs, centre negative cell contact; no paste on cell contact; centre contact needs durable plated finish; four top copper keepouts are project additions',3.85)
    for x in [-12.95,12.95]:fp.pad(1,x,0,5.2,5.2)
    fp.pad(2,0,0,4,4,layers='"F.Cu" "F.Mask"')
    fp.circle(0,0,10,'F.Fab');fp.rect(-10.55,-9.9,10.55,9.9)
    fp.rect(-15.55,-2.55,-10.55,2.55);fp.rect(10.55,-2.55,15.55,2.55)
    fp.circle(0,0,10)
    fp.text('+',-12.95,-3.5,'F.SilkS',1.2);fp.text('-',0,0)
    fp.rect(-15.85,-10.8,15.85,10.8,'F.CrtYd',.05)
    # The battery underside must only touch the negative contact. Leave room
    # around pad 2 for its GND via; other top copper under the cell is forbidden.
    for box in [(-10,-10,10,-2.2),(-10,2.2,10,10),(-10,-2.2,-2.2,2.2),(2.2,-2.2,10,2.2)]:fp.keepout(*box)
    fp.save()

    for family,depth,row_from_top,drill,body_x1,body_x2,height in [
            ('DG301R',10,2.65,1.2,-2.5,8.1,7.6),
            ('DG306',7.6,4.5,1.4,-3.1,7.5,10)]:
        name=f'TerminalBlock_Degson_{family}-5.0_1x02'
        fp=Footprint(name,f'DEGSON {family}-5.0 two positions; A(H) drawing rev T1 2020-05-25; 5 mm pitch; includes 0.6 mm interlock envelope',height,tht=True)
        pad_d=drill+1.2
        for no,x in [(1,0),(2,5)]:fp.pad(no,x,0,pad_d,pad_d,layers='"*.Cu" "*.Mask"',drill=drill,shape='rect' if no==1 else 'circle')
        y1=-row_from_top;y2=depth-row_from_top
        fp.rect(body_x1,y1,body_x2,y2)
        fp.rect(body_x1-.5,y1-.5,body_x2+.5,y2+.5,'F.CrtYd',.05)
        fp.rect(body_x1-.12,y1-.12,body_x2+.12,y2+.12,'F.SilkS',.12)
        # Keep pin numbers within the terminal body envelope so an edge-mounted
        # terminal does not print text beyond the board or across its neighbour.
        label_y = 4.5 if family == 'DG301R' else 2.0
        fp.text('1',0,label_y,'F.SilkS');fp.text('2',5,label_y,'F.SilkS')
        fp.save()

    fp=Footprint('microSD_GCT_MEM2061-01-188-00-A','GCT MEM2061 A1 02/12/25; component-side PCB layout; without pegs; CD1/CD2 both unused; SH two ground tabs; card access envelope on Dwgs.User',1.88)
    # Origin is the top-left body edge in the recommended component-side view.
    for pin in range(1,9):
        x=8.94-(pin-1)*1.1
        y=10.55 if pin==2 else (11.15 if pin in [4,6] else 10.95)
        fp.pad(pin,x,y,.8,2)
    for no,x in [('CD1',2.05),('CD2',7.75)]:fp.pad(no,x,.4,1.8,1.4)
    fp.pad('SH',.45,13.55,1.4,1.9)
    fp.pad('SH',13.6,14.55,1.4,1.9)
    fp.rect(0,0,14,15.45)
    fp.rect(-.5,-.55,14.55,16,'F.CrtYd',.05)
    # Manufacturer keepout: no top copper under the indicated contact area.
    fp.keepout(0,2.55,10.37,4.63)
    fp.rect(0,2.55,10.37,4.63,'Dwgs.User',.1)
    # Inserted card protrudes 1.70 mm; ejected card 5.60 mm, measured from
    # the 14.45 mm insertion face. This is an access guide, not a courtyard.
    fp.rect(.25,14.45,11.25,20.05,'Dwgs.User',.1)
    fp.text('CARD ACCESS / OUT',5.5,21.3,'Dwgs.User')
    fp.line(-.2,-.15,-.2,12);fp.line(14.25,-.15,14.25,13.1)
    fp.text('1',9.5,9,'F.SilkS')
    fp.save()
    print('Generated 10 project-specific footprints with local 3D models; UMT250/HTSSOP16 retain upstream geometry.')


if __name__=='__main__':main()
