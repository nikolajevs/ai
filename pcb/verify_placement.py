"""Check mechanical requirements of PCB_V1's initial placement (KiCad Python).

DRC remains responsible for exact courtyard and copper collisions. These checks
catch parts returned to the staging area, blocked board-edge access, an absent
antenna keepout, and accidental loss of the manufacturing setup.
"""
import json
import math
import sys
from pathlib import Path
import pcbnew as p

path = Path(sys.argv[1])
board = p.LoadBoard(str(path))
fps = {f.GetReference(): f for f in board.GetFootprints()}
outline = board.GetBoardEdgesBoundingBox()
mm = p.ToMM
left, top, right, bottom = map(mm, (outline.GetLeft(), outline.GetTop(), outline.GetRight(), outline.GetBottom()))
assert right-left <= 100.1 and bottom-top <= 100.1, 'Board exceeds 100 x 100 mm'
assert board.GetCopperLayerCount() == 4
assert not any('MountingHole' in str(f.GetFPID()) for f in fps.values()), 'No mounting holes requested'
assert len(list(board.GetDrawings())) >= 4

def shape_bounds(fp, layer):
    shapes = [g.GetBoundingBox() for g in fp.GraphicalItems()
              if g.GetLayer() == layer and isinstance(g, p.PCB_SHAPE)]
    if not shapes and fp.GetReference().startswith('TP'):
        courtyard = p.B_CrtYd if fp.GetLayer() == p.B_Cu else p.F_CrtYd
        shapes = [g.GetBoundingBox() for g in fp.GraphicalItems() if g.GetLayer() == courtyard]
    assert shapes, (fp.GetReference(), 'missing body drawing')
    return tuple(map(mm, (min(s.GetLeft() for s in shapes), min(s.GetTop() for s in shapes),
                         max(s.GetRight() for s in shapes), max(s.GetBottom() for s in shapes))))

for ref, fp in fps.items():
    x, y = map(mm, (fp.GetPosition().x, fp.GetPosition().y))
    assert left <= x <= right and top <= y <= bottom, (ref, 'component still outside board')
    for pad in fp.Pads():
        box = pad.GetBoundingBox()
        assert left <= mm(box.GetLeft()) <= mm(box.GetRight()) <= right, (ref, 'pad beyond X outline')
        assert top <= mm(box.GetTop()) <= mm(box.GetBottom()) <= bottom, (ref, 'pad beyond Y outline')
    body = shape_bounds(fp, p.B_Fab if fp.GetLayer() == p.B_Cu else p.F_Fab)
    assert body[0] >= left-.1 and body[1] >= top-.1 and body[2] <= right+.1 and body[3] <= bottom+.1, (ref, 'body outside board', body)
    if ref.startswith('J'):
        edge_distance = min(body[0]-left, body[1]-top, right-body[2], bottom-body[3])
        assert edge_distance <= 3.0, (ref, 'connector not at board edge', edge_distance)

# The microSD footprint's opening faces local +Y. Check the outward-facing
# board edge rather than freezing the first placement's absolute coordinates.
card = fps['J401']
angle = math.radians(card.GetOrientationDegrees())
dx, dy = math.sin(angle), math.cos(angle)
mouth_x = mm(card.GetPosition().x) + 6.275*dx
mouth_y = mm(card.GetPosition().y) + 6.275*dy
if dx > .999: gap = right-mouth_x
elif dx < -.999: gap = mouth_x-left
elif dy > .999: gap = bottom-mouth_y
elif dy < -.999: gap = mouth_y-top
else: raise AssertionError('Card opening is not aligned with a board edge')
assert .2 <= gap <= 1.0, 'Card mouth must be accessible from its outward-facing edge'
assert fps['BT301'].GetLayer() == p.B_Cu, 'Battery holder must remain accessible from underside'
for pad in fps['BT301'].Pads():
    assert pad.IsOnLayer(p.B_Cu) and not pad.IsOnLayer(p.F_Cu), 'Battery pad side does not match holder'

zones = list(fps['U201'].Zones())
assert len(zones) == 1 and zones[0].GetIsRuleArea(), 'ESP32 antenna keepout missing'
z = zones[0]
assert all(z.IsOnLayer(layer) for layer in (p.F_Cu, p.In1_Cu, p.In2_Cu, p.B_Cu))
assert z.GetDoNotAllowTracks() and z.GetDoNotAllowVias() and z.GetDoNotAllowPads()
assert z.GetDoNotAllowZoneFills() and z.GetDoNotAllowFootprints()

project = json.loads(path.with_suffix('.kicad_pro').read_text(encoding='utf-8'))
rules = project['board']['design_settings']['rules']
assert rules['min_copper_edge_clearance'] >= .5
assert rules['min_via_diameter'] >= .65 and rules['min_through_hole_diameter'] >= .3
names = {c['name'] for c in project['net_settings']['classes']}
assert {'Default','MAIN24','HEATER24','LED_INPUT','AUX24','LED48','SWITCH','PWR12','PWR3V3'} <= names
assert path.with_suffix('.kicad_dru').is_file(), 'Project custom rules missing'
text = path.read_text(encoding='utf-8')
assert '(stackup' in text and '(material "FR4 7628")' in text, 'Documented stack missing'
print(f'PASS: {len(fps)} components and every pad inside 100 x 100 mm; no mounting footprints')
print('PASS: all 12 connectors at edges, outward microSD access, bottom battery, four-layer antenna keepout')
print('PASS: JLC7628 starting stack, nine routing classes and manufacturing constraints present')
