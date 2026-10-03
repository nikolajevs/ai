"""Scripted power routing for cheap-1 (KiCad Python): GND plane, ground ties, optional power pours and tracks.

  python route_power.py cheap-version.kicad_pcb [--write]            power stage, before the autorouter
  python route_power.py cheap-version.kicad_pcb --finish [--write]   finish stage, after route_complete.py

Same pipeline as PCB_V1/ROUTING.md (route_power.py -> route_signals.py -> route_complete.py -> route_power.py --finish),
with the cheap-1 tables below. The power stage deletes every track, via and script zone of the board and rebuilds
them from the tables, so geometry is edited here and not by hand.
"""
import math
import sys

import pcbnew as p

MM = p.FromMM
TAG = 'auto:'           # zone-name prefix of script-generated zones
VIA = {'S': (0.65, 0.3), 'M': (0.8, 0.4)}   # diameter, drill
BOARD = [(50.0, 50.0), (150.0, 50.0), (150.0, 150.0), (50.0, 150.0)]


def R(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


# --- zones: (name, net, layer, outline) -------------------------------------------------------
PLANES = [
    ('GND plane', 'GND', 'In1.Cu', BOARD),
]
FINISH = [
    ('GND top', 'GND', 'F.Cu', BOARD),
    ('GND bottom', 'GND', 'B.Cu', BOARD),
    ('3V3 fill', '+3V3', 'In2.Cu', BOARD),
]
POURS = [
    # (name, net, layer, outline)
]
TRACKS = [
    # (net, layer, width, [(x, y), ...])
]
VIAS = [
    # (net, 'S' | 'M', [(x, y), ...])
]
TIED_BY_TRACK = set()       # ground pads connected by a hand-placed track in TRACKS
# pads joined solidly to every zone they touch
SOLID_PADS = [('J901', '1'), ('J901', '2'), ('Q601', '2'), ('J301', '2'), ('J401', 'SH')]


NETS = {}


def net(board, name):
    if not NETS:    # read once: the net table proxy is not reliable after zones have been removed
        for n, info in board.GetNetsByName().items():
            NETS[str(n)] = info
    found = [info for n, info in NETS.items() if n == name or n.split('/')[-1] == name]
    if len(found) != 1:
        raise KeyError(name)
    return found[0]


def add_zone(board, name, netname, layer, outline, solid):
    z = p.ZONE(board)
    z.SetZoneName(TAG + name)
    z.SetLayer(board.GetLayerID(layer))
    z.SetNet(net(board, netname))
    z.SetAssignedPriority(10 if solid else 0)
    z.SetMinThickness(MM(0.25))
    z.SetLocalClearance(0)                      # net-class clearance applies
    z.SetPadConnection(p.ZONE_CONNECTION_FULL if solid else p.ZONE_CONNECTION_THERMAL)
    z.SetThermalReliefGap(MM(0.4))
    z.SetThermalReliefSpokeWidth(MM(0.5))
    z.SetIslandRemovalMode(p.ISLAND_REMOVAL_MODE_ALWAYS)
    poly = z.Outline()
    poly.NewOutline()
    for x, y in outline:
        poly.Append(MM(x), MM(y))
    board.Add(z)
    return z


def add_track(board, netname, layer, width, points):
    for a, b in zip(points, points[1:]):
        t = p.PCB_TRACK(board)
        t.SetStart(p.VECTOR2I(MM(a[0]), MM(a[1])))
        t.SetEnd(p.VECTOR2I(MM(b[0]), MM(b[1])))
        t.SetWidth(MM(width))
        t.SetLayer(board.GetLayerID(layer))
        t.SetNet(net(board, netname))
        t.SetLocked(True)                       # exported to the autorouter as fixed wiring
        board.Add(t)


def add_via(board, netname, size, x, y):
    dia, drill = VIA[size]
    v = p.PCB_VIA(board)
    v.SetViaType(p.VIATYPE_THROUGH)
    v.SetLayerPair(p.F_Cu, p.B_Cu)
    v.SetPosition(p.VECTOR2I(MM(x), MM(y)))
    v.SetWidth(p.F_Cu, MM(dia))
    v.SetDrill(MM(drill))
    v.SetNet(net(board, netname))
    v.SetLocked(True)
    board.Add(v)


GRAVEYARD = []      # removed items stay referenced: destroying their Python proxies breaks later pcbnew calls


def discard(board, item):
    board.Remove(item)
    GRAVEYARD.append(item)


def remove_zones(board, names=None):
    for z in list(board.Zones()):
        name = z.GetZoneName()
        if name.startswith(TAG) and (names is None or name[len(TAG):] in names):
            discard(board, z)


def inside(pt, poly):
    """Ray-casting point-in-polygon test, board mm."""
    x, y = pt
    hit = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            hit = not hit
    return hit


def edge_distance(pt, poly):
    best = 1e9
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        dx, dy = x1 - x0, y1 - y0
        s = max(0.0, min(1.0, ((pt[0] - x0) * dx + (pt[1] - y0) * dy) / (dx * dx + dy * dy)))
        best = min(best, ((pt[0] - x0 - s * dx) ** 2 + (pt[1] - y0 - s * dy) ** 2) ** 0.5)
    return best


def islands():
    """GND copper islands of the power stage: they exist only while the autorouter runs."""
    return [(name, layer, outline) for name, netname, layer, outline in POURS if netname == 'GND']


COPPER = [p.F_Cu, p.In1_Cu, p.In2_Cu, p.B_Cu]
TIE_RADII = (0.9, 1.1, 1.35, 1.65, 2.0, 2.5, 3.2)
TIE_ANGLES = (0, 180, 90, 270, 45, 225, 135, 315, 22.5, 202.5, 112.5, 292.5, 67.5, 247.5, 157.5, 337.5)
TIE_MARGIN = 0.3            # clearance of a tie to foreign copper, above the 0.2 mm default class
TIE_WIDTH = 0.3


def obstacles(board):
    """Copper of every net: [net, (x0, y0, x1, y1) in mm, {layer: shape}, clearance mm, uuid, kind]."""
    out = []

    def add(item, layers, kind):
        bb = item.GetBoundingBox()
        box = (p.ToMM(bb.GetLeft()), p.ToMM(bb.GetTop()), p.ToMM(bb.GetRight()), p.ToMM(bb.GetBottom()))
        try:
            clr = p.ToMM(item.GetEffectiveNetClass().GetClearance())
        except Exception:
            clr = 0.5
        out.append([item.GetNetname(), box, {layer: item.GetEffectiveShape(layer) for layer in layers}, max(clr, 0.2),
                    item.m_Uuid.AsString(), kind])

    for fp in board.GetFootprints():
        for pad in fp.Pads():
            add(pad, [layer for layer in COPPER if pad.IsOnLayer(layer)], 'pad')
    for t in board.GetTracks():
        add(t, COPPER if isinstance(t, p.PCB_VIA) else [t.GetLayer()], 'via' if isinstance(t, p.PCB_VIA) else 'track')
    return out


def tie_ground(board, only=None):
    """A via and a short stub for every GND pad outside the copper islands: SMD pads reach In1 locally.

    A tie via keeps clear of every other pad and via, also of its own net (no via touching a neighbouring pad);
    `only` limits the work to a set of (reference, pad number), used when a tie is redone on a finished board."""
    pours = [outline for name, netname, layer, outline in POURS if netname != 'GND']
    keepouts = []
    for fp in board.GetFootprints():
        for z in fp.Zones():
            if z.GetIsRuleArea():
                bb = z.GetBoundingBox()
                keepouts.append((p.ToMM(bb.GetLeft()), p.ToMM(bb.GetTop()), p.ToMM(bb.GetRight()), p.ToMM(bb.GetBottom())))
    edge = board.GetBoardEdgesBoundingBox()
    left, top, right, bottom = (p.ToMM(v) for v in (edge.GetLeft(), edge.GetTop(), edge.GetRight(), edge.GetBottom()))
    obst = obstacles(board)
    gnd = net(board, 'GND')
    dia, drill = VIA['S']
    placed, failed = 0, []

    def clear_of(shape, layer, box, via, own):
        x0, y0, x1, y1 = box
        for netname, (a, b, c, d), shapes, clr, uid, kind in obst:
            if uid == own or layer not in shapes:
                continue
            if netname == 'GND':
                if kind == 'track' or (kind == 'via' and not via):
                    continue
                m = 0.35 if kind == 'via' else 0.15        # same net: hole spacing / no sliver against a neighbouring pad
            else:
                m = max(clr, TIE_MARGIN)
            if c < x0 - m or a > x1 + m or d < y0 - m or b > y1 + m:
                continue
            if shape.Collide(shapes[layer], MM(m)):
                return False
        return True

    for fp in board.GetFootprints():
        if fp.IsNetTie():
            continue
        for pad in fp.Pads():
            if pad.GetNetname() != 'GND' or pad.GetAttribute() == p.PAD_ATTRIB_PTH or (fp.GetReference(), pad.GetNumber()) in TIED_BY_TRACK:
                continue
            if only is not None and (fp.GetReference(), pad.GetNumber()) not in only:
                continue
            cx, cy = p.ToMM(pad.GetPosition().x), p.ToMM(pad.GetPosition().y)
            if any(inside((cx, cy), outline) for _, layer, outline in islands() if layer == 'F.Cu'):
                continue
            pad_layer = p.B_Cu if fp.IsFlipped() else p.F_Cu
            found = None
            for r in TIE_RADII:
                for ang in TIE_ANGLES:
                    vx = cx + r * math.cos(math.radians(ang))
                    vy = cy + r * math.sin(math.radians(ang))
                    if not (left + 0.9 <= vx <= right - 0.9 and top + 0.9 <= vy <= bottom - 0.9):
                        continue
                    if any(a - 0.5 <= vx <= c + 0.5 and b - 0.5 <= vy <= d + 0.5 for a, b, c, d in keepouts):
                        continue
                    if any(inside((vx, vy), outline) or edge_distance((vx, vy), outline) < 0.6 for outline in pours):
                        continue
                    v = p.PCB_VIA(board)
                    v.SetViaType(p.VIATYPE_THROUGH)
                    v.SetLayerPair(p.F_Cu, p.B_Cu)
                    v.SetPosition(p.VECTOR2I(MM(vx), MM(vy)))
                    v.SetWidth(p.F_Cu, MM(dia))
                    v.SetDrill(MM(drill))
                    v.SetNet(gnd)
                    box = (vx - dia / 2, vy - dia / 2, vx + dia / 2, vy + dia / 2)
                    if v.GetEffectiveShape(pad_layer).Collide(pad.GetEffectiveShape(pad_layer), MM(0.15)):
                        continue            # never a via in or against the pad being tied (hand soldering)
                    own = pad.m_Uuid.AsString()
                    if not all(clear_of(v.GetEffectiveShape(layer), layer, box, True, own) for layer in (p.F_Cu, p.In2_Cu, p.B_Cu)):
                        continue
                    stub = p.PCB_TRACK(board)
                    stub.SetStart(pad.GetPosition())
                    stub.SetEnd(p.VECTOR2I(MM(vx), MM(vy)))
                    stub.SetWidth(MM(TIE_WIDTH))
                    stub.SetLayer(pad_layer)
                    sbox = (min(cx, vx) - TIE_WIDTH, min(cy, vy) - TIE_WIDTH, max(cx, vx) + TIE_WIDTH, max(cy, vy) + TIE_WIDTH)
                    if not clear_of(stub.GetEffectiveShape(), pad_layer, sbox, False, own):
                        continue
                    found = (v, stub)
                    break
                if found:
                    break
            if not found:
                failed.append(f'{fp.GetReference()}.{pad.GetNumber()}')
                continue
            for item, layers in ((found[0], COPPER), (found[1], [pad_layer])):
                item.SetNet(gnd)
                item.SetLocked(True)
                board.Add(item)
                bb = item.GetBoundingBox()
                obst.append(['GND', (p.ToMM(bb.GetLeft()), p.ToMM(bb.GetTop()), p.ToMM(bb.GetRight()), p.ToMM(bb.GetBottom())),
                             {layer: item.GetEffectiveShape(layer) for layer in layers}, 0.2, item.m_Uuid.AsString(),
                             'via' if isinstance(item, p.PCB_VIA) else 'track'])
            placed += 1
    print(f'GND ties: {placed} vias with stubs; no room for {failed if failed else "none"}')
    return failed


def apply_solid(board):
    for ref, number in SOLID_PADS:
        for pad in board.FindFootprintByReference(ref).Pads():
            if pad.GetNumber() == number:
                pad.SetLocalZoneConnection(p.ZONE_CONNECTION_FULL)


def power_stage(board):
    for t in list(board.GetTracks()):
        discard(board, t)
    remove_zones(board)
    for name, netname, layer, outline in PLANES:
        add_zone(board, name, netname, layer, outline, solid=False)
    for name, netname, layer, outline in POURS:
        add_zone(board, name, netname, layer, outline, solid=True)
    for netname, layer, width, points in TRACKS:
        add_track(board, netname, layer, width, points)
    for netname, size, points in VIAS:
        for x, y in points:
            add_via(board, netname, size, x, y)
    apply_solid(board)
    tie_ground(board)


def finish_stage(board):
    """After autorouting the GND islands give way to the full-board pours; their pads stay solid."""
    for name, layer, outline in islands():
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                if pad.GetNetname() == 'GND' and inside((p.ToMM(pad.GetPosition().x), p.ToMM(pad.GetPosition().y)), outline):
                    pad.SetLocalZoneConnection(p.ZONE_CONNECTION_FULL)
    apply_solid(board)
    for t in board.GetTracks():
        t.SetLocked(False)          # locked only to hand the power stage to the router as fixed wiring
    remove_zones(board, {name for name, *_ in FINISH} | {name for name, _, _ in islands()})
    for name, netname, layer, outline in FINISH:
        add_zone(board, name, netname, layer, outline, solid=False)


def main():
    path = sys.argv[1]
    board = p.LoadBoard(path)
    net(board, 'GND')
    if '--finish' in sys.argv:
        finish_stage(board)
    else:
        power_stage(board)
    p.ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()
    vias = sum(1 for t in board.GetTracks() if isinstance(t, p.PCB_VIA))
    print('zones', len(list(board.Zones())), 'tracks', len(board.GetTracks()) - vias, 'vias', vias,
          'unrouted', board.GetConnectivity().GetUnconnectedCount(False))
    if '--write' in sys.argv:
        p.SaveBoard(path, board)
        text = open(path, encoding='utf-8').read().replace('\r\n', '\n')
        open(path, 'w', encoding='utf-8', newline='\n').write(text)
        print('saved')


if __name__ == '__main__':
    main()
