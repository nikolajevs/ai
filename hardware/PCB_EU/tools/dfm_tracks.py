#!/usr/bin/env python3
"""Pull routed tracks and vias off the edge of pads they only pass by (JLCPCB: the mask opening exposes them).

A track of the pad's own net that runs past the pad without touching it, closer than SKIM_MM, has the
mask opening of the pad cut across its copper. Only the bend or junction of the track nearest to the
pad moves (relax_skims), by the smallest step that leaves SKIM_CLEAR_MM between track and pad, keeps
every other net 0.2 mm away, stays out of track keepouts and keeps 0.3 mm from the board edge.
Positions that keep all touching segments at multiples of 45 degrees are preferred. A junction inside
a via or a pad of the net stays inside it; a junction in the middle of another track of the net is
not moved; if one junction cannot move, the whole track is shifted. check_fab.py reports what is left.

Vias get the same treatment (relax_vias): a via of the pad's net within VIA_PAD_MM of the pad without
touching it moves with the track ends on it, keeping 0.2 mm to other nets and 0.25 mm hole to hole.
A via that overlaps its pad (a thermal via) is left alone.

route_board.py calls both after the grid completion, before the pours are filled. On its own this
file only reports and never writes a board:

  dfm_tracks.py --board B.kicad_pcb

SPDX-License-Identifier: MIT
"""
import argparse
import math
from pathlib import Path

import pcbnew as p

MM = p.FromMM
SKIM_MM = 0.09         # JLCPCB / JLCDFM: a track closer than this to a pad without touching it is exposed
SKIM_CLEAR_MM = 0.095  # what the relaxed track keeps from the pad (check_fab.py flags below 0.09)
VIA_PAD_MM = 0.10      # check_fab.py: a via closer than this to a pad of its net without overlapping it
VIA_CLEAR_MM = 0.105   # what a relaxed via keeps from the pad
TOUCH_NM = 2000        # 2 um: shapes closer than this count as touching
OTHER_NET_MM = 0.2
EDGE_MM = 0.3
STEP_MM = 0.05
FINE_MM = 0.01         # finer steps within 0.2 mm of the junction
ULTRA_MM = 0.002       # and 2 um steps within 0.04 mm, for junctions squeezed between two pads
REACH_MM = 0.9         # farthest a junction moves
HERE = Path(__file__).resolve().parents[1]


def collide(a, b, clearance_mm):
    return p.SHAPE.Collide(a, b, MM(clearance_mm))


def is_skim(shape, pad_shape, clear=SKIM_CLEAR_MM):
    return not p.SHAPE.Collide(shape, pad_shape, TOUCH_NM) and collide(shape, pad_shape, clear)


def uid(item):
    return item.m_Uuid.AsString()


def tracks_of(board):
    return [t for t in board.GetTracks() if not isinstance(t, p.PCB_VIA)]


def find_skims(board):
    """[(track, pad)] of same-net tracks that pass a pad without touching it, closer than SKIM_MM."""
    pads = [(pad, pad.GetBoundingBox()) for fp in board.GetFootprints() for pad in fp.Pads()]
    reach = MM(SKIM_MM)
    found = []
    for t in tracks_of(board):
        shape, tb = t.GetEffectiveShape(), t.GetBoundingBox()
        for pad, pb in pads:
            if pad.GetNetCode() != t.GetNetCode() or not pad.IsOnLayer(t.GetLayer()) or \
               tb.GetRight() + reach < pb.GetLeft() or pb.GetRight() + reach < tb.GetLeft() or \
               tb.GetBottom() + reach < pb.GetTop() or pb.GetBottom() + reach < tb.GetTop():
                continue
            pad_shape = pad.GetEffectiveShape(t.GetLayer())
            if not p.SHAPE.Collide(shape, pad_shape, TOUCH_NM) and collide(shape, pad_shape, SKIM_MM):
                found.append((t, pad))
    return found


def at(point, other, tol=5000):
    return abs(point.x - other.x) <= tol and abs(point.y - other.y) <= tol


def on_45(a, b):
    dx, dy = abs(b.x - a.x), abs(b.y - a.y)
    if dx == 0 or dy == 0:
        return True
    return abs(dx - dy) <= max(1000, 0.003 * max(dx, dy))


class Move:
    """Shift one junction of a track (or, with drag, both ends of the track) by the smallest clear offset."""

    def __init__(self, board, track, pad, drag=False):
        self.board, self.track, self.pad = board, track, pad
        self.layer, self.net = track.GetLayer(), track.GetNetCode()
        centre = pad.GetPosition()
        copy = lambda e: p.VECTOR2I(e.x, e.y)  # a copy: the track's own point moves with it
        if drag:
            self.ends = [copy(track.GetStart()), copy(track.GetEnd())]
        else:
            self.ends = [copy(min((track.GetStart(), track.GetEnd()), key=lambda e: (e - centre).EuclideanNorm()))]
        # (track, True for its start / False for its end, index of the junction it belongs to)
        self.members = []
        for t in tracks_of(board):
            if t.GetLayer() == self.layer and t.GetNetCode() == self.net:
                for k, e in enumerate(self.ends):
                    if at(t.GetStart(), e):
                        self.members.append((t, True, k))
                    if at(t.GetEnd(), e):
                        self.members.append((t, False, k))
        self.incident = list({uid(t): t for t, _, _ in self.members}.values())
        self.incident_ids = {uid(t) for t in self.incident}
        self.original = {(uid(t), start): copy(t.GetStart() if start else t.GetEnd()) for t, start, _ in self.members}

    def anchors(self):
        """Per junction, same-net copper it sits in: a candidate must stay inside all of it, or connectivity changes."""
        found = []
        for k, end in enumerate(self.ends):
            for fp in self.board.GetFootprints():
                for pad in fp.Pads():
                    if pad.GetNetCode() == self.net and pad.IsOnLayer(self.layer) and pad.HitTest(end):
                        found.append((k, lambda pt, pad=pad: pad.HitTest(pt)))
            for via in self.board.GetTracks():
                if isinstance(via, p.PCB_VIA) and via.GetNetCode() == self.net:
                    centre, reach = via.GetPosition(), via.GetWidth(self.layer) // 2 - MM(0.02)
                    if (centre - end).EuclideanNorm() <= reach:
                        found.append((k, lambda pt, centre=centre, reach=reach: (centre - pt).EuclideanNorm() <= reach))
        return found

    def blocked_junction(self):
        """Why a junction must not move, or None."""
        for end in self.ends:
            probe = p.SHAPE_CIRCLE(end, 1000)
            for t in tracks_of(self.board):
                if t.GetLayer() == self.layer and t.GetNetCode() == self.net and uid(t) not in self.incident_ids \
                   and p.SHAPE.Collide(t.GetEffectiveShape(), probe, 0):
                    return 'middle of another track'
        return None

    def obstacles(self):
        """Foreign copper near the moved segments."""
        xs = [e.x for e in self.ends] + [e.x for t in self.incident for e in (t.GetStart(), t.GetEnd())]
        ys = [e.y for e in self.ends] + [e.y for t in self.incident for e in (t.GetStart(), t.GetEnd())]
        margin = MM(REACH_MM + 1.5 + max(p.ToMM(t.GetWidth()) for t in self.incident))
        box = p.BOX2I(p.VECTOR2I(min(xs) - margin, min(ys) - margin), p.VECTOR2I(max(xs) - min(xs) + 2 * margin, max(ys) - min(ys) + 2 * margin))
        out = []
        for t in self.board.GetTracks():
            if uid(t) in self.incident_ids or t.GetNetCode() == self.net or not box.Intersects(t.GetBoundingBox()):
                continue
            if isinstance(t, p.PCB_VIA):
                out.append(t.GetEffectiveShape(self.layer))
            elif t.GetLayer() == self.layer:
                out.append(t.GetEffectiveShape())
        for fp in self.board.GetFootprints():
            for pad in fp.Pads():
                if pad.GetNetCode() != self.net and pad.IsOnLayer(self.layer) and box.Intersects(pad.GetBoundingBox()):
                    out.append(pad.GetEffectiveShape(self.layer))
        return out

    def keepouts(self):
        out = []
        for zone in [*self.board.Zones(), *(z for fp in self.board.GetFootprints() for z in fp.Zones())]:
            if zone.GetIsRuleArea() and zone.GetDoNotAllowTracks() and zone.IsOnLayer(self.layer):
                out.append(zone.Outline())
        return out

    def shift(self, dx, dy):
        for t, start, k in self.members:
            o = self.original[(uid(t), start)]
            point = p.VECTOR2I(o.x + dx, o.y + dy)
            t.SetStart(point) if start else t.SetEnd(point)

    def valid(self, dx, dy, obstacles, keepouts, pads, edge, anchors, straight):
        if not all(inside(p.VECTOR2I(self.ends[k].x + dx, self.ends[k].y + dy)) for k, inside in anchors):
            return False
        self.shift(dx, dy)
        try:
            for t in self.incident:
                if (t.GetStart() - t.GetEnd()).EuclideanNorm() < MM(0.05):
                    return False
                if straight and on_45(*self.before[uid(t)]) and not on_45(t.GetStart(), t.GetEnd()):
                    return False
                shape, bb = t.GetEffectiveShape(), t.GetBoundingBox()
                if bb.GetLeft() < edge.GetLeft() + MM(EDGE_MM) or bb.GetRight() > edge.GetRight() - MM(EDGE_MM) or \
                   bb.GetTop() < edge.GetTop() + MM(EDGE_MM) or bb.GetBottom() > edge.GetBottom() - MM(EDGE_MM):
                    return False
                if any(collide(shape, o, OTHER_NET_MM - 0.0001) for o in obstacles):
                    return False
                if any(k.Collide(shape, MM(0.1)) for k in keepouts):
                    return False
                if any(is_skim(shape, ps) for ps in pads):
                    return False
            return True
        finally:
            self.shift(0, 0)

    def relax(self):
        reason = self.blocked_junction()
        if reason:
            return None, reason
        obstacles, keepouts, anchors = self.obstacles(), self.keepouts(), self.anchors()
        pads = [pad.GetEffectiveShape(self.layer) for fp in self.board.GetFootprints() for pad in fp.Pads()
                if pad.GetNetCode() == self.net and pad.IsOnLayer(self.layer)]
        edge = self.board.GetBoardEdgesBoundingBox()
        self.before = {uid(t): (p.VECTOR2I(t.GetStart().x, t.GetStart().y), p.VECTOR2I(t.GetEnd().x, t.GetEnd().y)) for t in self.incident}
        offsets = {(dx * STEP_MM, dy * STEP_MM) for dx in range(-18, 19) for dy in range(-18, 19)}
        offsets |= {(dx * FINE_MM, dy * FINE_MM) for dx in range(-20, 21) for dy in range(-20, 21)}
        offsets |= {(dx * ULTRA_MM, dy * ULTRA_MM) for dx in range(-20, 21) for dy in range(-20, 21)}
        candidates = sorted((o for o in offsets if o != (0, 0) and math.hypot(*o) <= REACH_MM + 1e-9),
                            key=lambda o: (round(math.hypot(*o), 6), o))
        for straight in (True, False):
            for dx, dy in candidates:
                if self.valid(MM(dx), MM(dy), obstacles, keepouts, pads, edge, anchors, straight):
                    self.shift(MM(dx), MM(dy))
                    return [(e.x + MM(dx), e.y + MM(dy)) for e in self.ends], None
        return None, 'no clear position within %.1f mm' % REACH_MM


COPPER = (p.F_Cu, p.In1_Cu, p.In2_Cu, p.B_Cu)
HOLE_TO_HOLE_MM = 0.25


def find_via_skims(board):
    """[(via, pad)] of vias that stand within VIA_PAD_MM of a pad of their net without touching it."""
    pads = [(fp, pad, layer) for fp in board.GetFootprints() for pad in fp.Pads() for layer in (p.F_Cu, p.B_Cu) if pad.IsOnLayer(layer)]
    found = []
    for v in board.GetTracks():
        if not isinstance(v, p.PCB_VIA):
            continue
        for fp, pad, layer in pads:
            if pad.GetNetCode() == v.GetNetCode() and not p.SHAPE.Collide(v.GetEffectiveShape(layer), pad.GetEffectiveShape(layer), TOUCH_NM) \
               and collide(v.GetEffectiveShape(layer), pad.GetEffectiveShape(layer), VIA_PAD_MM):
                found.append((v, pad))
                break
    return found


class ViaMove:
    """Shift a via, with the track ends on it, by the smallest clear offset that leaves SKIM_CLEAR_MM to its pad."""

    def __init__(self, board, via):
        self.board, self.via, self.net = board, via, via.GetNetCode()
        o = via.GetPosition()
        self.origin = p.VECTOR2I(o.x, o.y)
        self.members = [(t, at(t.GetStart(), self.origin)) for t in tracks_of(board)
                        if t.GetNetCode() == self.net and (at(t.GetStart(), self.origin) or at(t.GetEnd(), self.origin))]
        self.incident_ids = {uid(t) for t, _ in self.members} | {uid(via)}
        self.original = {uid(t): p.VECTOR2I(*((t.GetStart() if start else t.GetEnd()).x, (t.GetStart() if start else t.GetEnd()).y))
                         for t, start in self.members}

    def shift(self, dx, dy):
        point = p.VECTOR2I(self.origin.x + dx, self.origin.y + dy)
        self.via.SetPosition(point)
        for t, start in self.members:
            t.SetStart(point) if start else t.SetEnd(point)

    def obstacles(self):
        """Per copper layer, foreign copper within reach of the via and of its tracks."""
        box = self.via.GetBoundingBox()
        box.Inflate(MM(REACH_MM + 1.5))
        for t, _ in self.members:
            box.Merge(t.GetBoundingBox())
        out = {layer: [] for layer in COPPER}
        for t in self.board.GetTracks():
            if uid(t) in self.incident_ids or t.GetNetCode() == self.net or not box.Intersects(t.GetBoundingBox()):
                continue
            for layer in COPPER:
                if isinstance(t, p.PCB_VIA) or t.GetLayer() == layer:
                    out[layer].append(t.GetEffectiveShape(layer) if isinstance(t, p.PCB_VIA) else t.GetEffectiveShape())
        for fp in self.board.GetFootprints():
            for pad in fp.Pads():
                if pad.GetNetCode() != self.net and box.Intersects(pad.GetBoundingBox()):
                    for layer in COPPER:
                        if pad.IsOnLayer(layer):
                            out[layer].append(pad.GetEffectiveShape(layer))
        return out

    def holes(self):
        out = []
        box = self.via.GetBoundingBox()
        box.Inflate(MM(REACH_MM + 1.5))
        for fp in self.board.GetFootprints():
            for pad in fp.Pads():
                if pad.GetDrillSizeX() > 0 and box.Intersects(pad.GetBoundingBox()):
                    out.append(pad.GetEffectiveHoleShape())
        for t in self.board.GetTracks():
            if isinstance(t, p.PCB_VIA) and uid(t) != uid(self.via) and box.Intersects(t.GetBoundingBox()):
                out.append(p.SHAPE_CIRCLE(t.GetPosition(), t.GetDrill() // 2))
        return out

    def valid(self, dx, dy, obstacles, holes, pads, edge, no_via_areas, no_track_areas):
        self.shift(dx, dy)
        try:
            hole = p.SHAPE_CIRCLE(self.via.GetPosition(), self.via.GetDrill() // 2)
            if any(collide(hole, h, HOLE_TO_HOLE_MM - 0.0001) for h in holes):
                return False
            bb = self.via.GetBoundingBox()
            if bb.GetLeft() < edge.GetLeft() + MM(EDGE_MM) or bb.GetRight() > edge.GetRight() - MM(EDGE_MM) or \
               bb.GetTop() < edge.GetTop() + MM(EDGE_MM) or bb.GetBottom() > edge.GetBottom() - MM(EDGE_MM):
                return False
            if any(zone.Collide(self.via.GetEffectiveShape(p.F_Cu), 0) for zone in no_via_areas):
                return False
            for layer in COPPER:
                shape = self.via.GetEffectiveShape(layer)
                if any(collide(shape, o, OTHER_NET_MM - 0.0001) for o in obstacles[layer]):
                    return False
            for pad, layer in pads:  # off the pad, not onto it: a via in a small pad takes the solder
                if collide(self.via.GetEffectiveShape(layer), pad.GetEffectiveShape(layer), VIA_CLEAR_MM):
                    return False
            for t, _ in self.members:
                shape = t.GetEffectiveShape()
                if (t.GetStart() - t.GetEnd()).EuclideanNorm() < MM(0.05):
                    return False
                if any(collide(shape, o, OTHER_NET_MM - 0.0001) for o in obstacles[t.GetLayer()]):
                    return False
                if any(zone.Collide(shape, MM(0.1)) for layer, zone in no_track_areas if layer == t.GetLayer()):
                    return False
                if any(is_skim(shape, pad.GetEffectiveShape(t.GetLayer())) for pad, layer in pads if layer == t.GetLayer()):
                    return False
            return True
        finally:
            self.shift(0, 0)

    def relax(self):
        obstacles, holes, edge = self.obstacles(), self.holes(), self.board.GetBoardEdgesBoundingBox()
        pads = [(pad, layer) for fp in self.board.GetFootprints() for pad in fp.Pads() if pad.GetNetCode() == self.net
                for layer in (p.F_Cu, p.B_Cu) if pad.IsOnLayer(layer)]
        areas = [z for z in [*self.board.Zones(), *(z for fp in self.board.GetFootprints() for z in fp.Zones())] if z.GetIsRuleArea()]
        no_via = [z.Outline() for z in areas if z.GetDoNotAllowVias()]
        no_track = [(layer, z.Outline()) for z in areas if z.GetDoNotAllowTracks() for layer in COPPER if z.IsOnLayer(layer)]
        offsets = {(dx * STEP_MM, dy * STEP_MM) for dx in range(-10, 11) for dy in range(-10, 11)}
        offsets |= {(dx * FINE_MM, dy * FINE_MM) for dx in range(-20, 21) for dy in range(-20, 21)}
        offsets |= {(dx * ULTRA_MM, dy * ULTRA_MM) for dx in range(-20, 21) for dy in range(-20, 21)}
        for dx, dy in sorted((o for o in offsets if o != (0, 0)), key=lambda o: (round(math.hypot(*o), 6), o)):
            if self.valid(MM(dx), MM(dy), obstacles, holes, pads, edge, no_via, no_track):
                self.shift(MM(dx), MM(dy))
                return (self.origin.x + MM(dx), self.origin.y + MM(dy))
        return None


def relax_vias(board, fixed=frozenset()):
    """Move vias off the edge of pads of their net; returns (moved, unresolved) as lists of strings.

    Copper whose UUID is in fixed (the reviewed plan of routing.json) never moves: change the plan instead."""
    moved, unresolved = [], []
    for via, pad in find_via_skims(board):
        name = f'{pad.GetParentFootprint().GetReference()}.{pad.GetNumber()}'
        m = ViaMove(board, via)
        point = None if m.incident_ids & fixed else m.relax()
        if point is None:
            unresolved.append(f'via at ({p.ToMM(m.origin.x):.2f}, {p.ToMM(m.origin.y):.2f}) near {name}')
        else:
            moved.append(f'{name} via: ({p.ToMM(m.origin.x):.3f}, {p.ToMM(m.origin.y):.3f})->({p.ToMM(point[0]):.3f}, {p.ToMM(point[1]):.3f})')
    return moved, unresolved


def relax_skims(board, fixed=frozenset(), passes=4):
    """Move junctions off pad edges; returns (moved, unresolved) as lists of strings.

    Copper whose UUID is in fixed (the reviewed plan of routing.json) never moves: change the plan instead."""
    moved, unresolved = [], []
    for _ in range(passes):
        skims = find_skims(board)
        if not skims:
            return moved, []
        unresolved = []
        done = set()
        for track, pad in skims:
            tag = uid(track)
            if tag in done:
                continue
            done.add(tag)
            name = f'{pad.GetParentFootprint().GetReference()}.{pad.GetNumber()}'
            for drag in (False, True):
                m = Move(board, track, pad, drag)
                old = [(e.x, e.y) for e in m.ends]
                points, why = (None, 'planned copper') if m.incident_ids & fixed else m.relax()
                if points:
                    kind = 'track dragged' if drag else 'junction'
                    moved.append(f'{name} {kind}: ' + ' '.join(f'({p.ToMM(a):.3f}, {p.ToMM(b):.3f})->({p.ToMM(c):.3f}, {p.ToMM(d):.3f})'
                                                              for (a, b), (c, d) in zip(old, points)))
                    break
            else:
                unresolved.append(f'{name} at ({p.ToMM(old[0][0]):.2f}, {p.ToMM(old[0][1]):.2f}): {why}')
    return moved, unresolved if find_skims(board) else []


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--board', type=Path, default=HERE / 'PCB_EU.kicad_pcb')
    args = ap.parse_args()
    board = p.LoadBoard(str(args.board))
    left = find_skims(board)
    for t, pad in left:
        print(f'{pad.GetParentFootprint().GetReference()}.{pad.GetNumber()} {t.GetNetname()} {t.GetLayerName()}')
    vias = find_via_skims(board)
    for v, pad in vias:
        print(f'{pad.GetParentFootprint().GetReference()}.{pad.GetNumber()} via at ({p.ToMM(v.GetPosition().x):.2f}, {p.ToMM(v.GetPosition().y):.2f})')
    print(f'{len(left)} tracks (within {SKIM_MM} mm) and {len(vias)} vias (within {VIA_PAD_MM} mm) stand next to a pad of their net without touching it')
    raise SystemExit(1 if left or vias else 0)


if __name__ == '__main__':
    main()
