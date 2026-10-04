"""Simplified parametric STEP models for the power SMD parts and the microSD socket (CadQuery).

    uv venv -p 3.12 .cq && uv pip install --python .cq cadquery
    .cq/Scripts/python hardware/models3d/power.py        (Windows; .cq/bin/python elsewhere)

Writes hardware/PCB_V1/libraries/GrowBox.3dshapes/*.step. Bodies and heights follow the manufacturer drawings
listed in SOURCES_power.md next to the models; terminals are simplified. Models sit on z = 0 (board top)
with the footprint origin at (0, 0). KiCad maps footprint +Y (down) to model -Y, so features that are
asymmetric in Y are mirrored here.
"""
from pathlib import Path

import cadquery as cq

OUT = Path(__file__).resolve().parents[1] / 'PCB_V1' / 'libraries' / 'GrowBox.3dshapes'
BODY = cq.Color(0.15, 0.15, 0.16)
CERAMIC = cq.Color(0.90, 0.88, 0.80)
GOLD = cq.Color(0.85, 0.68, 0.25)
TIN = cq.Color(0.78, 0.78, 0.80)
STEEL = cq.Color(0.70, 0.72, 0.75)
PLASTIC = cq.Color(0.10, 0.10, 0.10)


def box(dx, dy, dz, x=0.0, y=0.0, z=0.0):
    """Box of size dx*dy*dz whose bottom-centre sits at (x, y, z)."""
    return cq.Workplane('XY').box(dx, dy, dz, centered=(True, True, False)).translate((x, y, z))


def save(name, parts):
    asm = cq.Assembly(name=name)
    for i, (shape, color) in enumerate(parts):
        asm.add(shape, name=f'{name}_{i}', color=color)
    OUT.mkdir(parents=True, exist_ok=True)
    asm.export(str(OUT / f'{name}.step'), exportType='STEP')
    print('wrote', name)


def fuse_451():
    # Littelfuse 451/453 NANO2: 6.10 +/-0.20 long, 2.69 +/-0.25 square, end caps 1.45 mm.
    length, side, cap = 6.10, 2.69, 1.45
    body = box(length - 2 * cap, side, side)
    caps = box(cap, side, side, -(length - cap) / 2).union(box(cap, side, side, (length - cap) / 2))
    save('Fuse_Littelfuse_451', [(body, CERAMIC), (caps, GOLD)])


def bourns_inductor(name, bx, by, height, term_w, foot, overall_x):
    """Molded power inductor: body bx*by*height, lead-frame terminals term_w wide on the +/-X ends."""
    body = box(bx, by, height)
    t = 0.25
    half = overall_x / 2
    terms = None
    for s in (-1, 1):
        wall = box(t, term_w, min(2.3, height), s * (half - t / 2))
        base = box(foot, term_w, t, s * (half - foot / 2))
        piece = wall.union(base)
        terms = piece if terms is None else terms.union(piece)
    save(name, [(body.cut(terms), BODY), (terms, TIN)])


def so8fl():
    # onsemi SO-8FL (case 488AA): body 5.0 x 6.0, A 0.90..1.10 (1.00 nominal); pins 1-4 source/gate on -X,
    # drain frame on +X. Body centre follows the KiCad F.Fab outline (x offset 0.048 mm).
    height = 1.00
    body = box(6.0 - 0.3, 5.0, height, 0.048 + 0.15)
    leads = None
    for y in (-1.905, -0.635, 0.635, 1.905):
        lead = box(0.55, 0.42, 0.20, -2.952 + 0.275, y)
        leads = lead if leads is None else leads.union(lead)
    drain = box(0.45, 4.2, 0.20, 3.048 - 0.225)
    save('ONSemi_SO-8FL_488AA', [(body, PLASTIC), (leads.union(drain), TIN)])


def tf01a():
    # HRO TF-01A (drawing rev A): shell 14.76 x 14.50, 1.85 high; contacts 1..9 at 1.10 mm pitch behind the
    # shell (footprint y = -7.601 -> model y = +7.601); card mouth at footprint +Y (model -Y).
    sx, sy, h = 14.76, 14.50, 1.85
    shell = box(sx, sy, h)
    mouth = box(11.3, 1.2, 1.1, 0, -sy / 2 + 0.6, 0.35)          # card slot at the front edge
    shell = shell.cut(mouth)
    contacts = None
    for n in range(1, 10):
        x = 2.24 - (n - 1) * 1.10
        c = box(0.40, 1.10, 0.15, x, 7.601)
        contacts = c if contacts is None else contacts.union(c)
    tabs = None
    for x, y, w, l in ((-7.76, 6.751, 1.0, 1.2), (6.92, 6.751, 1.0, 1.2), (-7.76, -2.951, 1.0, 1.8), (7.76, -2.951, 1.0, 1.8)):
        tab = box(w, l, 0.15, x, y)
        tabs = tab if tabs is None else tabs.union(tab)
    housing = box(sx - 0.6, 1.2, h - 0.2, 0, sy / 2 - 0.6)        # black contact block at the rear
    save('microSD_HRO_TF-01A', [(shell.cut(housing), STEEL), (housing, PLASTIC), (contacts, GOLD), (tabs, STEEL)])


if __name__ == '__main__':
    fuse_451()
    # SRP1265A: 13.5 x 12.5 x 6.2, lead-frame terminals 4.7 wide, foot 2.75.
    bourns_inductor('L_Bourns_SRP1265A', 13.5, 12.5, 6.2, 4.7, 2.75, 13.5)
    # SRP1770TA: 16.9 x 16.9 x 6.7, 17.6 across terminals, terminals 11.9 wide, foot 2.3.
    bourns_inductor('L_Bourns_SRP1770TA_16.9x16.9mm', 16.9, 16.9, 6.7, 11.9, 2.3, 17.6)
    so8fl()
    tf01a()
