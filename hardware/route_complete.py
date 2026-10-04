"""Finish the connections the autorouter left open (KiCad Python).

  python route_complete.py PCB_V1/PCB_V1.kicad_pcb [--write]

Run after route_signals.py and before `route_power.py --finish`. Every net whose pads form more than
one connected group is joined by a grid router (0.1 mm, 45-degree moves, layers F.Cu / In2.Cu / B.Cu,
through vias), searched in a window around the two closest pads. Clearances are the net-class values
(never below 0.2 mm) and are tested with the KiCad collision shapes, so the result is checked against
the same geometry as DRC. Copper of other nets, script zones of other nets, the board edge and the
antenna keepout are obstacles; the GND pours of the finish stage are not (they refill around tracks).
"""
import heapq
import math
import sys

import pcbnew as p

import route_power

MM = p.FromMM
GRID = 0.1
WINDOW = 14.0               # mm around the two pads
LAYERS = [p.F_Cu, p.In2_Cu, p.B_Cu]
WIDTH = {'+12V': 0.5, '+3V3': 0.4}
DEFAULT_WIDTH = 0.25
VIA_COST, TURN_COST = 12.0, 0.4
DIRS = [(1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (-1, 1), (-1, -1), (1, -1)]


def clearance_of(item):
    try:
        return max(p.ToMM(item.GetEffectiveNetClass().GetClearance()), 0.2)
    except Exception:
        return 0.5


def components(board, netcode):
    """Connected groups of pads of one net, as lists of pads."""
    conn = board.GetConnectivity()
    pads = {pad.m_Uuid.AsString(): pad for fp in board.GetFootprints() for pad in fp.Pads() if pad.GetNetCode() == netcode}
    seen, groups = set(), []
    for key, pad in pads.items():
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


class Grid:
    def __init__(self, board, netcode, netname, x0, y0, x1, y1, width):
        self.x0, self.y0 = x0, y0
        self.nx, self.ny = int((x1 - x0) / GRID) + 1, int((y1 - y0) / GRID) + 1
        self.track = {layer: bytearray(self.nx * self.ny) for layer in LAYERS}
        self.via = bytearray(self.nx * self.ny)
        self.width = width
        edge = board.GetBoardEdgesBoundingBox()
        self.bounds = tuple(p.ToMM(v) for v in (edge.GetLeft(), edge.GetTop(), edge.GetRight(), edge.GetBottom()))
        self.paint(board, netcode, netname)

    def cell(self, x, y):
        return round((x - self.x0) / GRID), round((y - self.y0) / GRID)

    def xy(self, i, j):
        return self.x0 + i * GRID, self.y0 + j * GRID

    def mark(self, layer, shape, clr, box):
        """Block the cells whose track (and via) probe collides with the shape."""
        for kind, radius in (('track', self.width / 2), ('via', route_power.VIA['S'][0] / 2)):
            reach = radius + clr
            i0, j0 = self.cell(box[0] - reach, box[1] - reach)
            i1, j1 = self.cell(box[2] + reach, box[3] + reach)
            for i in range(max(i0, 0), min(i1, self.nx - 1) + 1):
                for j in range(max(j0, 0), min(j1, self.ny - 1) + 1):
                    x, y = self.xy(i, j)
                    probe = p.SHAPE_CIRCLE(p.VECTOR2I(MM(x), MM(y)), MM(radius))
                    if shape.Collide(probe, MM(clr)):
                        if kind == 'track':
                            self.track[layer][i * self.ny + j] = 1
                        else:
                            self.via[i * self.ny + j] = 1

    def paint(self, board, netcode, netname):
        win = (self.x0, self.y0, self.x0 + self.nx * GRID, self.y0 + self.ny * GRID)

        def near(box, m=3.0):
            return not (box[2] < win[0] - m or box[0] > win[2] + m or box[3] < win[1] - m or box[1] > win[3] + m)

        def box_of(item):
            bb = item.GetBoundingBox()
            return (p.ToMM(bb.GetLeft()), p.ToMM(bb.GetTop()), p.ToMM(bb.GetRight()), p.ToMM(bb.GetBottom()))

        for fp in board.GetFootprints():
            for pad in fp.Pads():
                if pad.GetNetCode() != netcode and near(box_of(pad)):
                    for layer in LAYERS:
                        if pad.IsOnLayer(layer):
                            self.mark(layer, pad.GetEffectiveShape(layer), clearance_of(pad), box_of(pad))
        for fp in board.GetFootprints():        # no new via in a pad of the same net either
            for pad in fp.Pads():
                if pad.GetNetCode() == netcode and near(box_of(pad)):
                    a, b_, c, d = box_of(pad)
                    i0, j0 = self.cell(a - 0.5, b_ - 0.5)
                    i1, j1 = self.cell(c + 0.5, d + 0.5)
                    for i in range(max(i0, 0), min(i1, self.nx - 1) + 1):
                        for j in range(max(j0, 0), min(j1, self.ny - 1) + 1):
                            self.via[i * self.ny + j] = 1
        hole = MM(route_power.VIA['S'][1] / 2 + 0.25) / 1e6      # drill radius + hole-to-hole rule, mm
        for t in board.GetTracks():
            if t.GetNetCode() == netcode and isinstance(t, p.PCB_VIA) and near(box_of(t)):
                self.keep_away(t.GetPosition(), 2 * hole + route_power.VIA['S'][1] / 2 + 0.15)
            if t.GetNetCode() != netcode and near(box_of(t)):
                if isinstance(t, p.PCB_VIA):
                    for layer in LAYERS:
                        self.mark(layer, t.GetEffectiveShape(layer), clearance_of(t), box_of(t))
                else:
                    self.mark(t.GetLayer(), t.GetEffectiveShape(), clearance_of(t), box_of(t))
        short = netname.split('/')[-1]
        for name, netname, layer, outline in route_power.POURS:
            if netname == short or layer not in ('F.Cu', 'B.Cu'):
                continue
            lay = board.GetLayerID(layer)
            xs, ys = [q[0] for q in outline], [q[1] for q in outline]
            if max(xs) < win[0] or min(xs) > win[2] or max(ys) < win[1] or min(ys) > win[3]:
                continue
            margin = self.width / 2 + 0.4
            for i in range(self.nx):
                for j in range(self.ny):
                    pt = self.xy(i, j)
                    if route_power.inside(pt, outline) or route_power.edge_distance(pt, outline) < margin:
                        self.track[lay][i * self.ny + j] = 1
                        if route_power.inside(pt, outline) or route_power.edge_distance(pt, outline) < margin + 0.3:
                            self.via[i * self.ny + j] = 1
        left, top, right, bottom = self.bounds
        edge = 0.5 + self.width / 2
        for i in range(self.nx):
            for j in range(self.ny):
                x, y = self.xy(i, j)
                if x < left + edge or x > right - edge or y < top + edge or y > bottom - edge:
                    for layer in LAYERS:
                        self.track[layer][i * self.ny + j] = 1
                    self.via[i * self.ny + j] = 1
        for fp in board.GetFootprints():
            for z in fp.Zones():
                if z.GetIsRuleArea():
                    bb = z.GetBoundingBox()
                    a, b, c, d = (p.ToMM(v) for v in (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom()))
                    for i in range(self.nx):
                        for j in range(self.ny):
                            x, y = self.xy(i, j)
                            if a - 0.3 <= x <= c + 0.3 and b - 0.3 <= y <= d + 0.3:
                                for layer in LAYERS:
                                    self.track[layer][i * self.ny + j] = 1
                                self.via[i * self.ny + j] = 1

    def keep_away(self, pos, radius):
        """No new via within radius mm of an existing hole of the same net (hole-to-hole rule)."""
        cx, cy = p.ToMM(pos.x), p.ToMM(pos.y)
        i0, j0 = self.cell(cx - radius, cy - radius)
        i1, j1 = self.cell(cx + radius, cy + radius)
        for i in range(max(i0, 0), min(i1, self.nx - 1) + 1):
            for j in range(max(j0, 0), min(j1, self.ny - 1) + 1):
                x, y = self.xy(i, j)
                if math.hypot(x - cx, y - cy) < radius:
                    self.via[i * self.ny + j] = 1

    def free_pad(self, pad, layer):
        """Cells inside the pad being connected carry its own copper: usable by the track, never by a via."""
        bb = pad.GetBoundingBox()
        a, b, c, d = (p.ToMM(v) for v in (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom()))
        i0, j0 = self.cell(a, b)
        i1, j1 = self.cell(c, d)
        for i in range(max(i0, 0), min(i1, self.nx - 1) + 1):
            for j in range(max(j0, 0), min(j1, self.ny - 1) + 1):
                self.track[layer][i * self.ny + j] = 0
                self.via[i * self.ny + j] = 1

    def free(self, layer, i, j):
        return 0 <= i < self.nx and 0 <= j < self.ny and not self.track[layer][i * self.ny + j]


def search(grid, start, goal, layers):
    """A* over (layer, i, j); returns the list of (layer, i, j) or None."""
    (sl, si, sj), (gl, gi, gj) = start, goal
    best = {(sl, si, sj, -1): 0.0}
    heap = [(0.0, 0.0, sl, si, sj, -1)]
    parent = {}
    while heap:
        _, cost, layer, i, j, d = heapq.heappop(heap)
        if (layer, i, j) == (gl, gi, gj):
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
                continue            # no corner cutting
            step = 1.0 if not (di and dj) else 1.4142
            ncost = cost + step + (TURN_COST if d != -1 and nd != d else 0.0)
            key = (layer, ni, nj, nd)
            if ncost < best.get(key, 1e18):
                best[key] = ncost
                parent[key] = (layer, i, j, d)
                h = (abs(ni - gi) + abs(nj - gj)) * 0.9
                heapq.heappush(heap, (ncost + h, ncost, layer, ni, nj, nd))
        if not grid.via[i * grid.ny + j]:
            for other in layers:
                if other != layer and grid.free(other, i, j):
                    ncost = cost + VIA_COST
                    key = (other, i, j, -1)
                    if ncost < best.get(key, 1e18):
                        best[key] = ncost
                        parent[key] = (layer, i, j, d)
                        heapq.heappush(heap, (ncost + (abs(i - gi) + abs(j - gj)) * 0.9, ncost, other, i, j, -1))
    return None


def emit(board, netname, netinfo, grid, path, start_pad, goal_pad, width):
    """Turn a grid path into tracks and vias; the ends are joined to the pad centres."""
    pts = [(layer, *grid.xy(i, j)) for layer, i, j in path]
    pts[0] = (pts[0][0], p.ToMM(start_pad.GetPosition().x), p.ToMM(start_pad.GetPosition().y))
    pts[-1] = (pts[-1][0], p.ToMM(goal_pad.GetPosition().x), p.ToMM(goal_pad.GetPosition().y))
    runs, run = [], [pts[0]]
    for a, b in zip(pts, pts[1:]):
        if a[0] != b[0]:
            runs.append(run)
            route_power.add_via(board, netname, 'S', a[1], a[2])
            run = [b]
        else:
            run.append(b)
    runs.append(run)
    for run in runs:
        if len(run) < 2:
            continue
        pruned = [run[0]]
        for k in range(1, len(run) - 1):
            a, b, c = pruned[-1], run[k], run[k + 1]
            if (b[1] - a[1]) * (c[2] - b[2]) - (b[2] - a[2]) * (c[1] - b[1]) != 0 and abs(
                    (b[1] - a[1]) * (c[2] - b[2]) - (b[2] - a[2]) * (c[1] - b[1])) > 1e-9:
                pruned.append(b)
        pruned.append(run[-1])
        layer = board.GetLayerName(run[0][0])
        route_power.add_track(board, netname, layer, width, [(q[1], q[2]) for q in pruned])
    return len(runs) - 1


def complete(board):
    route_power.net(board, 'GND')
    todo, done, failed = 0, 0, []
    for netname, info in sorted(route_power.NETS.items()):
        netcode = info.GetNetCode()
        if netcode == 0 or netname == 'GND':
            continue
        guard = 0
        while guard < 12:
            guard += 1
            groups = components(board, netcode)
            if len(groups) < 2:
                break
            groups.sort(key=len, reverse=True)
            main = groups[0]
            best = None
            for other in groups[1:]:
                for a in other:
                    for b in main:
                        d = math.dist((p.ToMM(a.GetPosition().x), p.ToMM(a.GetPosition().y)),
                                      (p.ToMM(b.GetPosition().x), p.ToMM(b.GetPosition().y)))
                        if best is None or d < best[0]:
                            best = (d, a, b)
            dist, a, b = best
            todo += 1
            short = netname.split('/')[-1]
            width = WIDTH.get(short, DEFAULT_WIDTH)
            ax, ay = p.ToMM(a.GetPosition().x), p.ToMM(a.GetPosition().y)
            bx, by = p.ToMM(b.GetPosition().x), p.ToMM(b.GetPosition().y)
            grid = Grid(board, netcode, netname, min(ax, bx) - WINDOW / 2, min(ay, by) - WINDOW / 2,
                        max(ax, bx) + WINDOW / 2, max(ay, by) + WINDOW / 2, width)
            sl = p.B_Cu if a.GetParentFootprint().IsFlipped() else p.F_Cu
            gl = p.B_Cu if b.GetParentFootprint().IsFlipped() else p.F_Cu
            grid.free_pad(a, sl)
            grid.free_pad(b, gl)
            si, sj = grid.cell(ax, ay)
            gi, gj = grid.cell(bx, by)
            path = search(grid, (sl, si, sj), (gl, gi, gj), LAYERS)
            label = f'{netname} {a.GetParentFootprint().GetReference()}.{a.GetNumber()} -> {b.GetParentFootprint().GetReference()}.{b.GetNumber()} ({dist:.1f} mm)'
            if not path:
                failed.append(label)
                print('NO PATH', label)
                break
            vias = emit(board, netname, info, grid, path, a, b, width)
            board.BuildConnectivity()
            print('routed', label, f'{len(path)} cells, {vias} vias')
            done += 1
    print(f'completion: {done} connections routed, {len(failed)} failed')
    return failed


def main():
    path = sys.argv[1]
    board = p.LoadBoard(path)
    failed = complete(board)
    route_power.p.ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()
    print('unrouted', board.GetConnectivity().GetUnconnectedCount(False))
    if '--write' in sys.argv:
        p.SaveBoard(path, board)
        text = open(path, encoding='utf-8').read().replace('\r\n', '\n')
        open(path, 'w', encoding='utf-8', newline='\n').write(text)
        print('saved')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
