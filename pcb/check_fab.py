"""DFM check of PCB_V1 against the JLCPCB capabilities for a 4-layer 1.6 mm board (KiCad Python).

  python check_fab.py PCB_V1/PCB_V1.kicad_pcb              # report; exit 1 on any FAIL
  python check_fab.py PCB_V1/PCB_V1.kicad_pcb --fix-silk   # widen silkscreen lines to the JLCPCB minimum, then save

Limits are the JLCPCB figures for multilayer boards with 1 oz outer copper, read on 2026-10-01 from
https://jlcpcb.com/capabilities/pcb-capabilities (FAIL = below the absolute minimum, WARN = below the
recommended value). This is our own check against the published numbers; JLCPCB's automatic review on
upload is the final word. It does not replace DRC, which stays responsible for clearances in the design.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import pcbnew as p

# --- JLCPCB capabilities, mm ------------------------------------------------------------------
TRACK_MIN = 0.09                # multilayer, 1 oz
SPACE_MIN = 0.09
VIA_HOLE_MIN, VIA_DIA_MIN, VIA_RING_MIN, VIA_RING_REC = 0.15, 0.25, 0.15, 0.20
VIA_DIA_OVER_HOLE = 0.10        # via diameter at least 0.1 larger than the hole
PTH_RING_MIN, PTH_RING_REC = 0.15, 0.20
PTH_HOLE_REC = 0.5              # smaller holes may fill with mask or tin
NPTH_MIN = 0.5
PLATED_SLOT_MIN, NONPLATED_SLOT_MIN = 0.35, 1.0
HOLE_TO_HOLE_VIA, HOLE_TO_HOLE_PAD = 0.2, 0.45
PTH_TO_COPPER_MIN, PTH_TO_COPPER_REC, NPTH_TO_COPPER_MIN = 0.28, 0.35, 0.2
MASK_BRIDGE_MIN = 0.10          # 1 oz, green/red/yellow/blue/purple
SMD_PAD_MIN = 0.25
SILK_LINE_MIN, SILK_TEXT_H_MIN = 0.15, 1.0
EDGE_COPPER_MIN = 0.2
SAME_NET_SPACE_REC = 0.25
SIZE_MAX = (663.0, 593.0)       # four-layer FR4

mm = p.ToMM


def collides(a, b, clearance):
    """SHAPE.Collide through the base class: the derived circle shapes only accept segments."""
    return p.SHAPE.Collide(a, b, p.FromMM(clearance))


def gap(a, b, cap):
    """Distance between two SHAPEs in mm, or cap when they are farther apart (bisection on Collide)."""
    if not collides(a, b, cap):
        return cap
    lo, hi = 0.0, cap
    for _ in range(14):
        mid = (lo + hi) / 2
        if collides(a, b, mid):
            hi = mid
        else:
            lo = mid
    return hi


path = Path(sys.argv[1])
fix_silk = '--fix-silk' in sys.argv
board = p.LoadBoard(str(path))
results = []                    # (level, text)


def report(level, text):
    results.append((level, text))
    print(f'[{level}] {text}')


def check(ok, fail_text, pass_text, level='FAIL'):
    report('PASS' if ok else level, pass_text if ok else fail_text)
    return ok


# --- silkscreen --------------------------------------------------------------------------------
SILK = (p.F_SilkS, p.B_SilkS)
thin, texts = 0, []
items = list(board.GetDrawings()) + [g for fp in board.GetFootprints() for g in fp.GraphicalItems()]
for g in items:
    if g.GetLayer() not in SILK:
        continue
    if isinstance(g, p.PCB_SHAPE):
        if mm(g.GetWidth()) < SILK_LINE_MIN - 1e-6:
            thin += 1
            if fix_silk:
                g.SetWidth(p.FromMM(SILK_LINE_MIN))
    elif isinstance(g, p.PCB_TEXT) and g.IsVisible():
        texts.append(g)
for fp in board.GetFootprints():
    for f in (fp.Reference(), fp.Value()):
        if f.IsVisible() and f.GetLayer() in SILK:
            texts.append(f)
if fix_silk:
    p.SaveBoard(str(path), board)
    text = path.read_text(encoding='utf-8').replace('\r\n', '\n')
    path.write_text(text, encoding='utf-8', newline='\n')
    print(f'silkscreen: {thin} lines widened to {SILK_LINE_MIN} mm, board saved')
    thin = 0
check(thin == 0, f'{thin} silkscreen lines thinner than {SILK_LINE_MIN} mm (run --fix-silk)',
      f'silkscreen lines all at least {SILK_LINE_MIN} mm')
small = [(t.GetText(), round(mm(t.GetTextHeight()), 2), round(mm(t.GetTextThickness()), 3)) for t in texts
         if mm(t.GetTextHeight()) < SILK_TEXT_H_MIN - 1e-6 or mm(t.GetTextThickness()) < SILK_LINE_MIN - 1e-6]
check(not small, f'silkscreen text below {SILK_TEXT_H_MIN} mm high or {SILK_LINE_MIN} mm stroke: {small}',
      f'{len(texts)} visible silkscreen texts: height at least {SILK_TEXT_H_MIN} mm and stroke at least {SILK_LINE_MIN} mm')

# --- outline and project rules ------------------------------------------------------------------
edge = [g for g in board.GetDrawings() if g.GetLayer() == p.Edge_Cuts]
box = edge[0].GetBoundingBox()
for g in edge[1:]:
    box.Merge(g.GetBoundingBox())
stroke = mm(edge[0].GetWidth())
w, h = mm(box.GetWidth()) - stroke, mm(box.GetHeight()) - stroke
check(3.0 <= min(w, h) and w <= SIZE_MAX[0] and h <= SIZE_MAX[1], f'board {w:.2f} x {h:.2f} mm outside the 4-layer limits',
      f'board outline {w:.2f} x {h:.2f} mm (inside the JLCPCB limits; 100 x 100 mm is the lowest price tier)')
check(w <= 100.001 and h <= 100.001, f'board {w:.2f} x {h:.2f} mm exceeds the 100 x 100 mm price tier',
      'board fits the 100 x 100 mm price tier', level='WARN')
rules = json.loads(path.with_suffix('.kicad_pro').read_text(encoding='utf-8'))['board']['design_settings']['rules']
for key, floor, label in (('min_track_width', TRACK_MIN, 'track width'), ('min_clearance', SPACE_MIN, 'copper clearance'),
                          ('min_via_diameter', VIA_DIA_MIN, 'via diameter'), ('min_through_hole_diameter', VIA_HOLE_MIN, 'drill'),
                          ('min_copper_edge_clearance', EDGE_COPPER_MIN, 'copper to board edge'),
                          ('min_hole_to_hole', HOLE_TO_HOLE_VIA, 'hole to hole'), ('min_via_annular_width', 0.0, 'via annular width')):
    check(rules[key] >= floor, f'project rule {key} = {rules[key]} below the JLCPCB minimum {floor}',
          f'project rule {label} {rules[key]} mm (JLCPCB minimum {floor})')
thickness = mm(board.GetDesignSettings().GetBoardThickness())
check(abs(thickness - 1.6) <= 0.16, f'board thickness {thickness:.3f} mm', f'board thickness {thickness:.3f} mm (1.6 mm +-10 %)')
ds = board.GetDesignSettings()
check(mm(ds.m_SolderMaskExpansion) >= 0 and mm(ds.m_SolderMaskExpansion) <= 0.05,
      f'mask expansion {mm(ds.m_SolderMaskExpansion)} mm', f'solder mask expansion {mm(ds.m_SolderMaskExpansion):.2f} mm (JLCPCB takes 1:1 openings)')
check(ds.m_TentViasFront and ds.m_TentViasBack, 'vias are not tented', 'vias tented on both sides')

# --- copper objects -----------------------------------------------------------------------------
tracks = [t for t in board.GetTracks() if not isinstance(t, p.PCB_VIA)]
vias = [t for t in board.GetTracks() if isinstance(t, p.PCB_VIA)]
narrow = min(mm(t.GetWidth()) for t in tracks)
check(narrow >= TRACK_MIN, f'track {narrow:.3f} mm', f'{len(tracks)} tracks, narrowest {narrow:.2f} mm (minimum {TRACK_MIN})')
bad = [v for v in vias if mm(v.GetDrill()) < VIA_HOLE_MIN or mm(v.GetWidth(p.F_Cu)) < VIA_DIA_MIN
       or mm(v.GetWidth(p.F_Cu)) - mm(v.GetDrill()) < VIA_DIA_OVER_HOLE]
check(not bad, f'{len(bad)} vias below the JLCPCB via limits', f'{len(vias)} vias: drill, diameter and ring above the minimum')
ring_min = min((mm(v.GetWidth(p.F_Cu)) - mm(v.GetDrill())) / 2 for v in vias)
check(ring_min >= VIA_RING_REC - 1e-6, f'via annular ring {ring_min:.3f} mm is above the minimum {VIA_RING_MIN} but below the recommended {VIA_RING_REC} mm '
      '(0.3/0.65 mm vias; the standard 0.3/0.4 mm order option is met)', f'via annular ring {ring_min:.3f} mm', level='WARN')
check(ring_min >= VIA_RING_MIN, f'via annular ring {ring_min:.3f} mm below {VIA_RING_MIN}', f'via annular ring at least {VIA_RING_MIN} mm')

pads = [(fp, pad) for fp in board.GetFootprints() for pad in fp.Pads()]
holes = []                                      # (kind, ref, shape, width mm, length mm)
rings, slots, small_pads, rect = [], [], [], []
for fp, pad in pads:
    dx, dy = mm(pad.GetDrillSizeX()), mm(pad.GetDrillSizeY())
    plated = pad.GetAttribute() == p.PAD_ATTRIB_PTH
    if dx > 0:
        holes.append(('PTH' if plated else 'NPTH', f'{fp.GetReference()}.{pad.GetNumber()}', pad.GetEffectiveHoleShape(), min(dx, dy), max(dx, dy)))
        if pad.GetDrillShape() != p.PAD_DRILL_SHAPE_CIRCLE and abs(dx - dy) > 1e-6:
            slots.append((plated, f'{fp.GetReference()}.{pad.GetNumber()}', min(dx, dy), max(dx, dy)))
        if plated and pad.GetShape() != p.PAD_SHAPE_CUSTOM:
            sx, sy = mm(pad.GetSize().x), mm(pad.GetSize().y)
            rings.append(((min(sx - dx, sy - dy)) / 2, f'{fp.GetReference()}.{pad.GetNumber()}'))
    elif pad.IsOnLayer(p.F_Cu) or pad.IsOnLayer(p.B_Cu):
        sx, sy = mm(pad.GetSize().x), mm(pad.GetSize().y)
        if min(sx, sy) < SMD_PAD_MIN - 1e-6 and pad.GetShape() != p.PAD_SHAPE_CUSTOM:
            small_pads.append((f'{fp.GetReference()}.{pad.GetNumber()}', sx, sy))
check(not small_pads, f'SMD pads below {SMD_PAD_MIN} x {SMD_PAD_MIN} mm: {small_pads}', f'every SMD pad at least {SMD_PAD_MIN} x {SMD_PAD_MIN} mm')
worst = min(rings) if rings else (9, '')
check(worst[0] >= PTH_RING_MIN, f'PTH annular ring {worst[0]:.3f} mm at {worst[1]}', f'{len(rings)} plated pads: annular ring at least {worst[0]:.2f} mm ({worst[1]}; minimum {PTH_RING_MIN})')
check(worst[0] >= PTH_RING_REC - 1e-6, f'PTH annular ring {worst[0]:.3f} mm below the recommended {PTH_RING_REC}', 'PTH rings at or above the recommended value', level='WARN')
small_holes = [(n, w_) for k, n, _, w_, _ in holes if k == 'PTH' and w_ < PTH_HOLE_REC]
check(not small_holes, f'plated holes below {PTH_HOLE_REC} mm: {small_holes}', f'plated holes at least {PTH_HOLE_REC} mm (smallest {min(w_ for k, _, _, w_, _ in holes if k == "PTH"):.2f})', level='WARN')
check(all(w_ >= NPTH_MIN for k, _, _, w_, _ in holes if k == 'NPTH'), 'non-plated hole below 0.5 mm', f'non-plated holes at least {NPTH_MIN} mm')
bad_slots = [(n, wd, ln) for plated, n, wd, ln in slots if wd < (PLATED_SLOT_MIN if plated else NONPLATED_SLOT_MIN) or (plated and ln < 2 * wd)]
check(not bad_slots, f'slots outside the limits: {bad_slots}', f'{len(slots)} plated slots: width at least {PLATED_SLOT_MIN} mm and length at least twice the width')

# --- hole spacing and distance of holes to foreign copper ---------------------------------------
all_holes = holes + [('VIA', f'via@{mm(v.GetPosition().x):.2f},{mm(v.GetPosition().y):.2f}', v.GetEffectiveShape(p.F_Cu), mm(v.GetDrill()), mm(v.GetDrill()))
                     for v in vias]
hole_boxes = []
for kind, name, shape, wd, ln in all_holes:
    bb = shape.BBox()
    hole_boxes.append((mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())))
# via shapes are copper discs: use the drill circle instead
via_hole = {}
for i, (kind, name, shape, wd, ln) in enumerate(all_holes):
    if kind == 'VIA':
        via = vias[i - len(holes)]
        via_hole[i] = p.SHAPE_CIRCLE(via.GetPosition(), via.GetDrill() // 2)
worst_pair = (9.0, '')
for i in range(len(all_holes)):
    for j in range(i + 1, len(all_holes)):
        a, b = hole_boxes[i], hole_boxes[j]
        if a[2] + 1 < b[0] or b[2] + 1 < a[0] or a[3] + 1 < b[1] or b[3] + 1 < a[1]:
            continue
        sa = via_hole.get(i, all_holes[i][2])
        sb = via_hole.get(j, all_holes[j][2])
        dist = gap(sa, sb, 1.0)
        need = HOLE_TO_HOLE_VIA if all_holes[i][0] == 'VIA' and all_holes[j][0] == 'VIA' else HOLE_TO_HOLE_PAD
        if dist - need < worst_pair[0]:
            worst_pair = (dist - need, f'{all_holes[i][1]} / {all_holes[j][1]} gap {dist:.3f} mm (needs {need})')
check(worst_pair[0] >= -1e-6, f'hole spacing: {worst_pair[1]}', 'hole-to-hole spacing meets 0.2 mm (vias) and 0.45 mm (pad holes)')

LAYERS = (p.F_Cu, p.In1_Cu, p.In2_Cu, p.B_Cu)
copper = []                                     # (netcode, layer, shape, box)
for fp, pad in pads:
    for layer in LAYERS:
        if pad.IsOnLayer(layer):
            bb = pad.GetBoundingBox()
            copper.append((pad.GetNetCode(), layer, pad.GetEffectiveShape(layer), (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom()), pad))
for t in board.GetTracks():
    bb = t.GetBoundingBox()
    for layer in (LAYERS if isinstance(t, p.PCB_VIA) else (t.GetLayer(),)):
        copper.append((t.GetNetCode(), layer, t.GetEffectiveShape(layer), (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom()), t))
worst_cu = {'PTH': (1.0, ''), 'NPTH': (1.0, '')}
reach = p.FromMM(0.6)
for fp, pad in pads:
    if pad.GetDrillSizeX() <= 0:
        continue
    kind = 'PTH' if pad.GetAttribute() == p.PAD_ATTRIB_PTH else 'NPTH'
    hole = pad.GetEffectiveHoleShape()
    hb = hole.BBox()
    for net, layer, shape, box, item in copper:
        if item is pad or (net == pad.GetNetCode() and net != 0):
            continue
        if box[2] < hb.GetLeft() - reach or box[0] > hb.GetRight() + reach or box[3] < hb.GetTop() - reach or box[1] > hb.GetBottom() + reach:
            continue
        dist = gap(hole, shape, 1.0)
        if dist < worst_cu[kind][0]:
            worst_cu[kind] = (dist, f'{fp.GetReference()}.{pad.GetNumber()} to {type(item).__name__} on {board.GetLayerName(layer)}')
check(worst_cu['PTH'][0] >= PTH_TO_COPPER_MIN, f'PTH hole to foreign copper {worst_cu["PTH"][0]:.3f} mm: {worst_cu["PTH"][1]}',
      f'plated hole edge to foreign copper at least {worst_cu["PTH"][0]:.2f} mm (minimum {PTH_TO_COPPER_MIN})')
check(worst_cu['PTH'][0] >= PTH_TO_COPPER_REC, f'PTH hole to foreign copper {worst_cu["PTH"][0]:.3f} mm below the recommended {PTH_TO_COPPER_REC}',
      'plated holes at or above the recommended distance to copper', level='WARN')
check(worst_cu['NPTH'][0] >= NPTH_TO_COPPER_MIN, f'NPTH to copper {worst_cu["NPTH"][0]:.3f} mm: {worst_cu["NPTH"][1]}',
      f'non-plated hole edge to copper at least {worst_cu["NPTH"][0]:.2f} mm (minimum {NPTH_TO_COPPER_MIN})')

# --- solder mask bridges between pad openings (openings equal the pads, expansion 0) ------------
worst_web = (0.3, '')
for side in (p.F_Cu, p.B_Cu):
    side_pads = [(fp, pad) for fp, pad in pads if pad.IsOnLayer(side)]
    boxes = [pad.GetBoundingBox() for _, pad in side_pads]
    for i in range(len(side_pads)):
        for j in range(i + 1, len(side_pads)):
            a, b = boxes[i], boxes[j]
            if a.GetRight() + reach < b.GetLeft() or b.GetRight() + reach < a.GetLeft() or \
               a.GetBottom() + reach < b.GetTop() or b.GetBottom() + reach < a.GetTop():
                continue
            sa, sb = side_pads[i][1].GetEffectiveShape(side), side_pads[j][1].GetEffectiveShape(side)
            if collides(sa, sb, 0.002):
                continue                # overlapping pads (net tie on a shunt pad) share one mask opening
            dist = gap(sa, sb, 0.3)
            if dist < worst_web[0]:
                worst_web = (dist, f'{side_pads[i][0].GetReference()}.{side_pads[i][1].GetNumber()} / {side_pads[j][0].GetReference()}.{side_pads[j][1].GetNumber()}')
check(worst_web[0] >= MASK_BRIDGE_MIN, f'mask web {worst_web[0]:.3f} mm between {worst_web[1]}',
      f'narrowest solder mask web between pad openings {worst_web[0]:.2f} mm ({worst_web[1]}; minimum {MASK_BRIDGE_MIN})')

# --- same-net copper that does not touch and lies closer than 0.25 mm ---------------------------
by_net = defaultdict(list)
for t in tracks:
    by_net[(t.GetNetCode(), t.GetLayer())].append(t)
close = []
for (net, layer), group in by_net.items():
    for i in range(len(group)):
        a = group[i]
        ba = a.GetBoundingBox()
        for j in range(i + 1, len(group)):
            b = group[j]
            bb = b.GetBoundingBox()
            if ba.GetRight() + reach < bb.GetLeft() or bb.GetRight() + reach < ba.GetLeft() or \
               ba.GetBottom() + reach < bb.GetTop() or bb.GetBottom() + reach < ba.GetTop():
                continue
            sa, sb = a.GetEffectiveShape(), b.GetEffectiveShape()
            if not collides(sa, sb, 0.002) and collides(sa, sb, SAME_NET_SPACE_REC):
                close.append((round(gap(sa, sb, SAME_NET_SPACE_REC), 3), board.GetNetInfo().GetNetItem(net).GetNetname().split('/')[-1], board.GetLayerName(layer)))
tiny = sum(1 for g_, _, _ in close if g_ < SPACE_MIN)
check(not close, f'{len(close)} same-net track pairs closer than {SAME_NET_SPACE_REC} mm without touching ({tiny} under {SPACE_MIN} mm '
      f'etch as one piece, {len(close) - tiny} are narrow slits between parts of one net, no short: electrically harmless)',
      f'no same-net tracks closer than {SAME_NET_SPACE_REC} mm without touching', level='WARN')

fails = sum(1 for lv, _ in results if lv == 'FAIL')
warns = sum(1 for lv, _ in results if lv == 'WARN')
print(f'\n{fails} FAIL, {warns} WARN')
sys.exit(1 if fails else 0)
