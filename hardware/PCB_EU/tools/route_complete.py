#!/usr/bin/env python3
"""Grid router for the connections Freerouting leaves open; used by route_board.py.

Adapted from hardware/route_complete.py (PCB_V1). Every net whose pads form more than one
connected copper group is joined pad to pad by an A* search (0.1 mm grid, 45-degree moves,
F.Cu / In2.Cu / B.Cu, through vias) in a window around the two closest pads. Clearances are the
net-class values (at least 0.2 mm) tested with KiCad collision shapes; copper of other nets, rule
areas on their layers and the board edge are obstacles. Deterministic for a given board.
SPDX-License-Identifier: MIT
"""
import heapq
import math

import pcbnew as p

from build_board import identity

MM = p.FromMM
GRID = 0.1
WINDOW = 12.0
LAYERS = [p.F_Cu, p.In2_Cu, p.B_Cu]
VIA = (0.6, 0.3)
WIDTH = {'HEAVY24': 0.8, 'LOAD': 0.4, 'PWR': 0.4}
DEFAULT_WIDTH = 0.25
VIA_COST, TURN_COST = 12.0, 0.4
DIRS = [(1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (-1, 1), (-1, -1), (1, -1)]


def mm_box(item):
    bb = item.GetBoundingBox()
    return (p.ToMM(bb.GetLeft()), p.ToMM(bb.GetTop()), p.ToMM(bb.GetRight()), p.ToMM(bb.GetBottom()))


def clearance_of(item):
    try:
        return max(p.ToMM(item.GetEffectiveNetClass().GetClearance()), 0.2)
    except Exception:
        return 0.2


def components(board, netcode):
    """Connected groups of the pads of one net, through tracks, vias and filled zones."""
    conn = board.GetConnectivity()
    pads = {pad.m_Uuid.AsString(): pad for fp in board.GetFootprints() for pad in fp.Pads() if pad.GetNetCode() == netcode}
    seen, groups = set(), []
    for key, pad in sorted(pads.items()):
        if key in seen:
            continue
        group, stack, visited = [], [pad], {key}
        while stack:
            item = stack.pop()
            k = item.m_Uuid.AsString()
            if k in pads:
                group.append(pads[k])
                seen.add(k)
            for other in conn.GetConnectedItems(item):
                ko = other.m_Uuid.AsString()
                if ko not in visited:
                    visited.add(ko)
                    stack.append(other)
        groups.append(group)
    return groups


def pad_layer(pad):
    if pad.GetAttribute() == p.PAD_ATTRIB_PTH:
        return None                 # any layer
    return p.B_Cu if pad.GetParentFootprint().IsFlipped() else p.F_Cu


class Grid:
    def __init__(self, board, netcode, box, width):
        x0, y0, x1, y1 = box
        self.x0, self.y0 = x0, y0
        self.nx, self.ny = int((x1 - x0) / GRID) + 1, int((y1 - y0) / GRID) + 1
        self.track = {layer: bytearray(self.nx * self.ny) for layer in LAYERS}
        self.via = bytearray(self.nx * self.ny)
        self.width = width
        self.paint(board, netcode)

    def cell(self, x, y):
        return round((x - self.x0) / GRID), round((y - self.y0) / GRID)

    def xy(self, i, j):
        return self.x0 + i * GRID, self.y0 + j * GRID

    def cells(self, box, reach):
        i0, j0 = self.cell(box[0] - reach, box[1] - reach)
        i1, j1 = self.cell(box[2] + reach, box[3] + reach)
        for i in range(max(i0, 0), min(i1, self.nx - 1) + 1):
            for j in range(max(j0, 0), min(j1, self.ny - 1) + 1):
                yield i, j

    def mark(self, layer, shape, clr, box):
        for kind, radius in (('track', self.width / 2), ('via', VIA[0] / 2)):
            for i, j in self.cells(box, radius + clr):
                x, y = self.xy(i, j)
                if shape.Collide(p.SHAPE_CIRCLE(p.VECTOR2I(MM(x), MM(y)), MM(radius)), MM(clr)):
                    if kind == 'track':
                        self.track[layer][i * self.ny + j] = 1
                    else:
                        self.via[i * self.ny + j] = 1

    def block_disc(self, cx, cy, radius, layers, via=True):
        for i, j in self.cells((cx, cy, cx, cy), radius):
            x, y = self.xy(i, j)
            if math.hypot(x - cx, y - cy) < radius:
                for layer in layers:
                    self.track[layer][i * self.ny + j] = 1
                if via:
                    self.via[i * self.ny + j] = 1

    def paint(self, board, netcode):
        win = (self.x0, self.y0, self.x0 + self.nx * GRID, self.y0 + self.ny * GRID)

        def near(box, m=2.0):
            return not (box[2] < win[0] - m or box[0] > win[2] + m or box[3] < win[1] - m or box[1] > win[3] + m)

        for fp in board.GetFootprints():
            for pad in fp.Pads():
                box = mm_box(pad)
                if not near(box):
                    continue
                if pad.GetNetCode() != netcode:
                    for layer in LAYERS:
                        if pad.IsOnLayer(layer):
                            self.mark(layer, pad.GetEffectiveShape(layer), clearance_of(pad), box)
                    if pad.HasHole():
                        c = pad.GetPosition()
                        hole = p.ToMM(max(pad.GetDrillSize().x, pad.GetDrillSize().y)) / 2
                        self.block_disc(p.ToMM(c.x), p.ToMM(c.y), hole + VIA[1] / 2 + 0.3, [], True)
                else:                   # no via in or against a pad of the own net
                    for i, j in self.cells(box, VIA[0] / 2 + 0.1):
                        self.via[i * self.ny + j] = 1
        for t in board.GetTracks():
            box = mm_box(t)
            if not near(box):
                continue
            if isinstance(t, p.PCB_VIA):
                c = t.GetPosition()
                # hole-to-hole spacing applies to every net
                self.block_disc(p.ToMM(c.x), p.ToMM(c.y), VIA[1] + 0.3, [], True)
                if t.GetNetCode() != netcode:
                    for layer in LAYERS:
                        self.mark(layer, t.GetEffectiveShape(layer), clearance_of(t), box)
            elif t.GetNetCode() != netcode and t.GetLayer() in LAYERS:
                self.mark(t.GetLayer(), t.GetEffectiveShape(), clearance_of(t), box)
        rules = [*board.Zones(), *(z for fp in board.GetFootprints() for z in fp.Zones())]
        for z in rules:
            if not z.GetIsRuleArea() or not near(mm_box(z)):
                continue
            layers = [layer for layer in LAYERS if z.IsOnLayer(layer)]
            if not layers:
                continue
            outline = z.Outline()
            for i, j in self.cells(mm_box(z), max(self.width / 2, VIA[0] / 2) + 0.2):
                x, y = self.xy(i, j)
                pt = p.VECTOR2I(MM(x), MM(y))
                if outline.Collide(pt, MM(self.width / 2 + 0.1)):
                    if z.GetDoNotAllowTracks():
                        for layer in layers:
                            self.track[layer][i * self.ny + j] = 1
                if outline.Collide(pt, MM(VIA[0] / 2 + 0.1)) and z.GetDoNotAllowVias():
                    self.via[i * self.ny + j] = 1
        edge = board.GetBoardEdgesBoundingBox()
        left, top, right, bottom = (p.ToMM(v) for v in (edge.GetLeft(), edge.GetTop(), edge.GetRight(), edge.GetBottom()))
        m = 0.5 + max(self.width, VIA[0]) / 2
        for i in range(self.nx):
            for j in range(self.ny):
                x, y = self.xy(i, j)
                if x < left + m or x > right - m or y < top + m or y > bottom - m:
                    for layer in LAYERS:
                        self.track[layer][i * self.ny + j] = 1
                    self.via[i * self.ny + j] = 1

    def open_pad(self, pad, layer):
        """The pad being joined is own copper: usable by the track, never by a new via."""
        for i, j in self.cells(mm_box(pad), 0):
            self.track[layer][i * self.ny + j] = 0
            self.via[i * self.ny + j] = 1

    def free(self, layer, i, j):
        return 0 <= i < self.nx and 0 <= j < self.ny and not self.track[layer][i * self.ny + j]


def search(grid, starts, goals):
    goals = set(goals)
    gx = sum(g[1] for g in goals) / len(goals)
    gy = sum(g[2] for g in goals) / len(goals)
    best, parent, heap = {}, {}, []
    for s in starts:
        key = (*s, -1)
        best[key] = 0.0
        heapq.heappush(heap, (0.0, 0.0, *s, -1))
    while heap:
        _, cost, layer, i, j, d = heapq.heappop(heap)
        if (layer, i, j) in goals:
            path, node = [], (layer, i, j, d)
            while node in parent:
                path.append(node[:3])
                node = parent[node]
            path.append(node[:3])
            return path[::-1]
        if cost > best.get((layer, i, j, d), 1e18):
            continue
        for nd, (di, dj) in enumerate(DIRS):
            ni, nj = i + di, j + dj
            if not grid.free(layer, ni, nj):
                continue
            if di and dj and not (grid.free(layer, i + di, j) and grid.free(layer, i, j + dj)):
                continue
            ncost = cost + (1.4142 if di and dj else 1.0) + (TURN_COST if d != -1 and nd != d else 0.0)
            key = (layer, ni, nj, nd)
            if ncost < best.get(key, 1e18):
                best[key] = ncost
                parent[key] = (layer, i, j, d)
                heapq.heappush(heap, (ncost + math.hypot(ni - gx, nj - gy) * 0.9, ncost, layer, ni, nj, nd))
        if not grid.via[i * grid.ny + j]:
            for other in LAYERS:
                if other != layer and grid.free(other, i, j):
                    ncost = cost + VIA_COST
                    key = (other, i, j, -1)
                    if ncost < best.get(key, 1e18):
                        best[key] = ncost
                        parent[key] = (layer, i, j, d)
                        heapq.heappush(heap, (ncost + math.hypot(i - gx, j - gy) * 0.9, ncost, other, i, j, -1))
    return None


def emit(board, net, grid, path, a, b, width, tag):
    """Tracks and vias along the path; the ends run to the pad centres."""
    pts = [(layer, *grid.xy(i, j)) for layer, i, j in path]
    pa, pb = a.GetPosition(), b.GetPosition()
    pts.insert(0, (pts[0][0], p.ToMM(pa.x), p.ToMM(pa.y)))
    pts.append((pts[-1][0], p.ToMM(pb.x), p.ToMM(pb.y)))
    runs, run, vias, added = [], [pts[0]], 0, []
    for u, v in zip(pts, pts[1:]):
        if u[0] != v[0]:
            runs.append(run)
            via = p.PCB_VIA(board)
            via.SetPosition(p.VECTOR2I(MM(round(u[1], 4)), MM(round(u[2], 4))))
            via.SetWidth(MM(VIA[0]))
            via.SetDrill(MM(VIA[1]))
            via.SetViaType(p.VIATYPE_THROUGH)
            via.SetLayerPair(p.F_Cu, p.B_Cu)
            via.SetNet(net)
            identity(via, f'{tag}/via/{vias}')
            board.Add(via)
            added.append(via)
            vias += 1
            run = [v]
        else:
            run.append(v)
    runs.append(run)
    n = 0
    for run in runs:
        pruned = [run[0]]
        for k in range(1, len(run) - 1):
            u, v, w = pruned[-1], run[k], run[k + 1]
            if abs((v[1] - u[1]) * (w[2] - v[2]) - (v[2] - u[2]) * (w[1] - v[1])) > 1e-9:
                pruned.append(v)
        pruned.append(run[-1])
        for u, v in zip(pruned, pruned[1:]):
            if (u[1], u[2]) == (v[1], v[2]):
                continue
            t = p.PCB_TRACK(board)
            t.SetStart(p.VECTOR2I(MM(round(u[1], 4)), MM(round(u[2], 4))))
            t.SetEnd(p.VECTOR2I(MM(round(v[1], 4)), MM(round(v[2], 4))))
            t.SetWidth(MM(width))
            t.SetLayer(u[0])
            t.SetNet(net)
            identity(t, f'{tag}/track/{n}')
            board.Add(t)
            added.append(t)
            n += 1
    return added


def complete_once(board, only, skip, first):
    nets = board.GetNetInfo().NetsByNetcode()
    routed, failed, added = [], [], []
    order = sorted(nets.keys(), key=lambda c: (nets[c].GetNetname() not in first, first.index(nets[c].GetNetname()) if nets[c].GetNetname() in first else 0, c))
    for code in order:
        net = nets[code]
        name = net.GetNetname()
        if code == 0 or (only is not None and name not in only) or (only is None and name in skip):
            continue
        for attempt in range(16):
            board.BuildConnectivity()
            groups = components(board, code)
            if len(groups) < 2:
                break
            groups.sort(key=lambda g: (-len(g), sorted(x.m_Uuid.AsString() for x in g)))
            main = groups[0]
            pairs = []
            for other in groups[1:]:
                for a in other:
                    for b in main:
                        pairs.append((math.dist((a.GetPosition().x, a.GetPosition().y), (b.GetPosition().x, b.GetPosition().y)), a, b))
            pairs.sort(key=lambda t: t[0])
            width = WIDTH.get(net.GetNetClassName(), DEFAULT_WIDTH)
            success = False
            for dist, a, b in pairs[:4]:
                ax, ay = p.ToMM(a.GetPosition().x), p.ToMM(a.GetPosition().y)
                bx, by = p.ToMM(b.GetPosition().x), p.ToMM(b.GetPosition().y)
                box = (min(ax, bx) - WINDOW / 2, min(ay, by) - WINDOW / 2, max(ax, bx) + WINDOW / 2, max(ay, by) + WINDOW / 2)
                grid = Grid(board, code, box, width)
                la, lb = pad_layer(a), pad_layer(b)
                for pad, layer in ((a, la), (b, lb)):
                    for lay in ([layer] if layer is not None else LAYERS):
                        grid.open_pad(pad, lay)
                si, sj = grid.cell(ax, ay)
                gi, gj = grid.cell(bx, by)
                starts = [(lay, si, sj) for lay in ([la] if la is not None else LAYERS)]
                goals = [(lay, gi, gj) for lay in ([lb] if lb is not None else LAYERS)]
                path = search(grid, starts, goals)
                label = f'{name} {a.GetParentFootprint().GetReference()}.{a.GetNumber()} -> {b.GetParentFootprint().GetReference()}.{b.GetNumber()}'
                if path:
                    added += emit(board, net, grid, path, a, b, width, f'route_complete/{name}/{label}')
                    routed.append(label)
                    success = True
                    break
            if not success:
                failed.append(name)
                break
    board.BuildConnectivity()
    return routed, failed, added


def complete(board, only=None, skip=('GND',), attempts=4):
    """Join split nets; on failure rip up this stage and retry with the failed nets first.

    Returns (routed labels, failed nets) of the best attempt."""
    first, tried = [], []
    for attempt in range(attempts):
        routed, failed, added = complete_once(board, only, skip, first)
        tried.append((len(failed), list(first)))
        if not failed or attempt == attempts - 1:
            break
        for item in added:
            board.Delete(item)
        first = failed + [n for n in first if n not in failed]
    best = min(tried, key=lambda t: t[0])
    if best[0] < len(failed):          # an earlier order was better: rebuild it
        for item in added:
            board.Delete(item)
        routed, failed, added = complete_once(board, only, skip, best[1])
    return routed, failed
