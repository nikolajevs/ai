"""Touch-ups of the routed PCB_V1 after the JLCDFM report of 2026-10-01 (KiCad Python, one-off).

  python fab_touchups.py PCB_V1/PCB_V1.kicad_pcb [--write]

Each edit is tied to coordinates of the committed routing: an edit whose objects are not found is skipped
with a message, so the script does nothing on a differently routed board. It is a record of what was changed
and why, not part of the routing pipeline (route_power.tie_ground already keeps ties off neighbouring pads).

  1. Via between C716.2 and C717.2: sat 0.075 mm from both pads (JLCDFM "via to pad"); removed.
  2. Ground ties of C601.2, C602.2 and U601.3 overlapped the neighbouring GND pads R210.2, C906.2 and U601.4;
     redone with the current tie rules.
  3. Five router corners that run past a pad of their own net within 0.04 - 0.07 mm without touching it, so the
     mask opening exposes them (JLCDFM "solder mask opening exposing trace"): vertices moved or segments merged.
  4. F301 moved 0.1 mm away from BT301.2: the copper gap F301.1 / BT301.2 was 0.41 mm (JLCDFM "THT to SMD").
Then the zones are refilled. DRC must stay at 0 violations / 0 unconnected: run check_all.py.
"""
import math
import sys
from pathlib import Path

import pcbnew as p

import route_power

mm, FM = p.ToMM, p.FromMM
path = Path(sys.argv[1])
board = p.LoadBoard(str(path))
route_power.net(board, 'GND')
graveyard = []


def near(a, x, y, tol=0.002):
    return abs(mm(a.x) - x) < tol and abs(mm(a.y) - y) < tol


def tracks():
    return [t for t in board.GetTracks() if not isinstance(t, p.PCB_VIA)]


def vias():
    return [t for t in board.GetTracks() if isinstance(t, p.PCB_VIA)]


def drop(item):
    board.Remove(item)
    graveyard.append(item)


def find_segment(a, b, layer=None):
    for t in tracks():
        if layer is not None and board.GetLayerName(t.GetLayer()) != layer:
            continue
        if (near(t.GetStart(), *a) and near(t.GetEnd(), *b)) or (near(t.GetStart(), *b) and near(t.GetEnd(), *a)):
            return t
    return None


def replace(layer, old, new, label):
    """Replace the segments `old` (list of (a, b)) by `new`; same net, width and layer as the first old segment."""
    found = [find_segment(a, b, layer) for a, b in old]
    if not all(found):
        print(f'skip {label}: segments not found')
        return
    proto = found[0]
    width, net_, lay = proto.GetWidth(), proto.GetNet(), proto.GetLayer()
    for t in found:
        drop(t)
    for a, b in new:
        t = p.PCB_TRACK(board)
        t.SetStart(p.VECTOR2I(FM(a[0]), FM(a[1])))
        t.SetEnd(p.VECTOR2I(FM(b[0]), FM(b[1])))
        t.SetWidth(width)
        t.SetLayer(lay)
        t.SetNet(net_)
        board.Add(t)
    print(f'done {label}')


# 1. via between C716.2 and C717.2
gone = [v for v in vias() if near(v.GetPosition(), 92.475, 107.95)]
for v in gone:
    drop(v)
print('done via C716/C717' if gone else 'skip via C716/C717: not found')

# 2. ground ties that overlapped a neighbouring pad: (via position, pad of the part whose tie it is)
redo = set()
for (vx, vy), (ref, num) in {(83.275, 79.3): ('C601', '2'), (83.95, 83.35): ('C602', '2'), (74.53, 80.53): ('U601', '3')}.items():
    hit = [v for v in vias() if near(v.GetPosition(), vx, vy, 0.01)]
    if not hit:
        print(f'skip re-tie {ref}.{num}: via not found')
        continue
    stubs = [t for t in tracks() if near(t.GetStart(), vx, vy, 0.01) or near(t.GetEnd(), vx, vy, 0.01)]
    for item in hit + stubs:
        drop(item)
    redo.add((ref, num))
if redo:
    failed = route_power.tie_ground(board, only=redo)
    if 'C602.2' in failed:      # the only free spot is 0.15 mm above where the old via sat, between C602.2 and C906.2
        route_power.add_via(board, 'GND', 'S', 83.95, 83.2)
        route_power.add_track(board, 'GND', 'F.Cu', route_power.TIE_WIDTH, [(83.95, 82.0), (83.95, 83.2)])
        print('done C602.2 tie placed by hand at (83.95, 83.2)')

# 3. router corners that skim a pad of their own net
replace('F.Cu', [((101.960, 118.535), (101.960, 117.515)), ((101.960, 117.515), (102.475, 117.000))],
        [((101.960, 118.535), (102.475, 117.000))], 'LED1_COMP at C712.1')
replace('F.Cu', [((138.175, 132.354), (131.429, 132.354)), ((138.567, 131.962), (138.175, 132.354)), ((138.175, 132.354), (138.175, 133.000))],
        [((131.429, 132.354), (138.175, 132.080)), ((138.567, 131.962), (138.175, 132.080)), ((138.175, 132.080), (138.175, 133.000))],
        'FAN2_TACH at R513.1')
replace('F.Cu', [((142.525, 126.000), (142.028, 125.503)), ((142.028, 125.503), (142.028, 120.657))],
        [((142.525, 126.000), (142.028, 125.300)), ((142.028, 125.300), (142.028, 120.657))], 'WATER_LEVEL at R306.2')
replace('F.Cu', [((102.725, 99.000), (102.145, 99.579)), ((102.145, 99.579), (102.145, 100.024))],
        [((102.725, 99.000), (102.145, 100.024))], '+3V3 at C106.1')

# 4. F301 0.1 mm away from the battery holder pad BT301.2
f301 = board.FindFootprintByReference('F301')
dx, dy = FM(0.1), FM(-0.1)
if f301 is not None and near(f301.Pads()[0].GetPosition(), 137.6, 100.0, 0.05):
    centres = [pad.GetPosition() for pad in f301.Pads()]
    ends = []
    for t in tracks():
        for c in centres:
            if near(t.GetStart(), mm(c.x), mm(c.y)):
                ends.append((t, True))
            if near(t.GetEnd(), mm(c.x), mm(c.y)):
                ends.append((t, False))
    f301.Move(p.VECTOR2I(dx, dy))
    for t, is_start in ends:
        if is_start:
            t.SetStart(t.GetStart() + p.VECTOR2I(dx, dy))
        else:
            t.SetEnd(t.GetEnd() + p.VECTOR2I(dx, dy))
    print(f'done F301 moved by (0.1, -0.1) mm, {len(ends)} track ends followed')
else:
    print('skip F301: not found at the expected place')

for t in board.GetTracks():
    t.SetLocked(False)
p.ZONE_FILLER(board).Fill(board.Zones())
board.BuildConnectivity()
print('unrouted', board.GetConnectivity().GetUnconnectedCount(False))
if '--write' in sys.argv:
    p.SaveBoard(str(path), board)
    text = path.read_text(encoding='utf-8').replace('\r\n', '\n')
    path.write_text(text, encoding='utf-8', newline='\n')
    print('saved')
