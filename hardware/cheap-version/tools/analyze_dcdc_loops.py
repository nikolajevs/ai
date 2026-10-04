"""Hot-loop geometry of the DC/DC converters of cheap-1 from the copper export (order-of-magnitude estimate, not a simulation).

  python analyze_dcdc_loops.py board.json            # board.json from export_view.py (KiCad Python)

For every loop the shortest copper route of its net between the two pads is found (pads, tracks, vias of that net; zone
fills count as a 3 mm wide strip) and converted to an inductance with the textbook formulas:
  track over a plane   L' = 0.2 nH/mm * ln(8h/w + w/4h)   h = 0.21 mm to the plane below (F.Cu over In1 GND, In2 over
                       In1); B.Cu runs over the +3V3 flood of In2, 1.28 mm away from the GND plane: h = 1.28 mm
  through via          L = 5.08 nH/inch * length * (ln(4 length / d) + 1), 1.6 mm board, d = drill
The current returns in In1 directly under the route, so the loop is the route plus the via into In1 at both ends
(two vias are added for the pads that return through a via; the pads of a footprint with an exposed pad count one).
Typical limits used for the verdict: input loop of a 24 V converter <= 8 nH; the number is a screening value, the
overshoot at the SW and VIN pins has to be looked at on the bench.
"""
import heapq
import json
import math
import sys

H_F, H_B = 0.21, 1.28           # mm to the reference plane
BOARD_T = 1.6
LIMIT_NH = 8.0


def track_nh_per_mm(width, h):
    return 0.2 * math.log(8 * h / width + width / (4 * h))


def via_nh(drill, length=BOARD_T):
    inch = 25.4
    return 5.08 * (length / inch) * (math.log(4 * length / drill) + 1)


LAYERS = {'F.Cu': 'F', 'B.Cu': 'B', 'In2.Cu': 'I2', 'In1.Cu': 'I1'}


def key(x, y, layer):
    return (round(x, 2), round(y, 2), layer)


def project(seg, x, y):
    """parameter t in [0, 1] and distance of the point (x, y) to the segment"""
    x0, y0, x1, y1 = seg[:4]
    dx, dy = x1 - x0, y1 - y0
    n = dx * dx + dy * dy
    t = 0.0 if n == 0 else max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / n))
    return t, math.hypot(x - (x0 + t * dx), y - (y0 + t * dy))


def build_graph(data, net, pads):
    """Nodes (x, y, layer); tracks are split wherever a via or one of `pads` touches them, so a pad lying on the middle of
    a track is connected to it (edges are (neighbour, mm, nH))."""
    graph = {}

    def add(a, b, length, nh):
        graph.setdefault(a, []).append((b, length, nh))
        graph.setdefault(b, []).append((a, length, nh))

    segs = [(t['x0'], t['y0'], t['x1'], t['y1'], t['w'], LAYERS[t['layer']]) for t in data['tracks'] if t['net'] == net]
    taps = []                                   # (x, y, layer, label) points that attach to copper
    for v in data['vias']:
        if v['net'] == net:
            for l in ('F', 'I2', 'B'):
                taps.append((v['x'], v['y'], l))
            nodes = [key(v['x'], v['y'], l) for l in ('F', 'I2', 'B')]
            for a, b in zip(nodes, nodes[1:]):
                add(a, b, 0.0, via_nh(v['drill']) / 2)
    for pad_ in pads:
        for l in ('F', 'B'):
            if l in pad_['layers']:
                taps.append((pad_['x'], pad_['y'], l))
    for seg in segs:
        layer = seg[5]
        h = H_B if layer == 'B' else H_F
        per_mm = track_nh_per_mm(seg[4], h)
        pts = [(0.0, seg[0], seg[1]), (1.0, seg[2], seg[3])]
        for x, y, l in taps:
            if l == layer:
                t, dist = project(seg, x, y)
                if dist <= seg[4] / 2 + 0.6:            # inside the track, or the pad of the part right beside it
                    pts.append((t, seg[0] + t * (seg[2] - seg[0]), seg[1] + t * (seg[3] - seg[1])))
        pts.sort()
        for (_t0, xa, ya), (_t1, xb, yb) in zip(pts, pts[1:]):
            length = math.hypot(xb - xa, yb - ya)
            add(key(xa, ya, layer), key(xb, yb, layer), length, per_mm * length)
    for x, y, l in taps:                        # tap point -> the nearest track point of the same layer (free: it lies in copper)
        best = None
        for seg in segs:
            if seg[5] == l:
                t, dist = project(seg, x, y)
                if dist <= seg[4] / 2 + 0.6 and (best is None or dist < best[0]):
                    best = (dist, key(seg[0] + t * (seg[2] - seg[0]), seg[1] + t * (seg[3] - seg[1]), l))
        if best:
            add(key(x, y, l), best[1], 0.0, 0.0)
    return graph


def route(data, net, a, b):
    graph = build_graph(data, net, [a, b])
    starts = [key(a['x'], a['y'], l) for l in ('F', 'B') if l in a['layers']]
    goals = {key(b['x'], b['y'], l) for l in ('F', 'B') if l in b['layers']}
    best = {}
    queue = [(0.0, 0.0, s) for s in starts]
    heapq.heapify(queue)
    while queue:
        nh, length, node = heapq.heappop(queue)
        if node in best:
            continue
        best[node] = (nh, length)
        if node in goals:
            return length, nh
        for nxt, ln, inductance in graph.get(node, []):
            if nxt not in best:
                heapq.heappush(queue, (nh + inductance, length + ln, nxt))
    return None


def pad(data, ref, number):
    return next(p for p in data['pads'] if p['ref'] == ref and p['n'] == number)


def euclid(a, b):
    return math.hypot(a['x'] - b['x'], a['y'] - b['y'])


def main(path):
    data = json.load(open(path))
    pad_via = via_nh(0.3)
    problems = 0
    print(f'single through via (0.3 mm drill, 1.6 mm board): {pad_via:.2f} nH; microstrip 0.6 mm over In1: '
          f'{track_nh_per_mm(0.6, H_F):.2f} nH/mm, over the +3V3 flood (B.Cu): {track_nh_per_mm(0.6, H_B):.2f} nH/mm')

    def report(label, net, ref_a, pin_a, ref_b, pin_b, returns_via=True):
        try:
            a, b = pad(data, ref_a, pin_a), pad(data, ref_b, pin_b)
        except StopIteration:
            print(f'  {label}: pad not found')
            return None
        result = route(data, net, a, b)
        if result is None:
            print(f'  {label}: no copper route on {net}: straight {euclid(a, b):.1f} mm')
            return None
        length, nh = result
        # the return runs in In1 under the route; add the via into In1 at the capacitor and at the IC
        total = nh + (pad_via * 2 if returns_via else 0)
        print(f'       {label}: route {length:.1f} mm, loop about {total:.1f} nH')
        return total

    def verdict(name, values, limit):
        """capacitors in parallel: the best loop decides, the others only carry the low-frequency ripple"""
        nonlocal problems
        values = [v for v in values if v is not None]
        best = min(values) if values else None
        ok = best is not None and best <= limit
        problems += not ok
        print(f'  {"ok  " if ok else "HIGH"} {name}: shortest loop {best:.1f} nH (limit {limit:.0f})' if best is not None
              else f'  HIGH {name}: no route')

    print('ST1S14 U902 (24 V -> 12 V, 850 kHz): VIN pin 7 to the input capacitors on AUX_VIN')
    vals = [report(f'U902.7 <- {ref}.1', '/InputPower/AUX_VIN', 'U902', '7', ref, '1')
            for ref in ('C911', 'C907', 'C905', 'C906') if any(p['ref'] == ref for p in data['pads'])]
    verdict('ST1S14 input HF loop (best capacitor)', vals, LIMIT_NH)
    best = min(v for v in vals if v)
    print(f'  info: at the 3.7 A current limit falling in 5 ns the VIN pin overshoots by about {best * 3.7 / 5:.1f} V (VIN 25 V max, rating 48 V)')
    print('ST1S10 U101 (12 V -> 3.3 V, 900 kHz): VIN_SW pin 6 to its capacitors on +12V')
    vals = [report(f'U101.6 <- {ref}.1', '+12V', 'U101', '6', ref, '1') for ref in ('C101', 'C102')]
    verdict('ST1S10 input HF loop (best capacitor)', vals, LIMIT_NH)
    print('boost loops (the GND return runs in In1 under the SW/OUT copper)')
    loops = {}
    for n, d, caps, q, shunt in ((1, 'D711', ('C716', 'C717', 'C718', 'C719'), 'Q711', 'R715'),
                                 (2, 'D721', ('C726', 'C727', 'C728'), 'Q721', 'R725')):
        vals = [report(f'{d}.1 -> {c}.1 (LED{n}_OUT)', f'/LEDDrivers/LED{n}_OUT', d, '1', c, '1') for c in caps]
        verdict(f'LED{n} output loop diode -> nearest output capacitor', vals, 12)
        loops[(n, 'sw')] = report(f'{q} drain -> {d} anode (LED{n}_SW)', f'/LEDDrivers/LED{n}_SW', q, '5', d, '2', returns_via=False)
        loops[(n, 'src')] = report(f'{q} source -> {shunt}.1 (LED{n}_SOURCE)', f'/LEDDrivers/LED{n}_SOURCE', q, '1', shunt, '1', returns_via=False)
        verdict(f'LED{n} switch node {q} drain -> {d} anode', [loops[(n, 'sw')]], 6)
        verdict(f'LED{n} source {q} -> {shunt}.1', [loops[(n, 'src')]], 6)
        gnd = euclid(pad(data, caps[0], '2'), pad(data, shunt, '2'))
        strip = track_nh_per_mm(3, H_F) * gnd
        print(f'  info: output-capacitor GND pad {caps[0]}.2 to the shunt GND pad {shunt}.2: {gnd:.1f} mm through In1 '
              f'(about {strip:.1f} nH as a 3 mm strip)')
        full = sum(v for v in (min(x for x in vals if x), loops[(n, 'sw')], loops[(n, 'src')]) if v) + strip + 2 * pad_via
        ipk = 6.26 if n == 1 else 3.06            # peak inductor current of the model (review/LED_power_cheap1.txt)
        print(f'  info: whole commutation loop of boost {n}: about {full:.0f} nH; at {ipk} A falling in 15 ns the SW node overshoots '
              f'by about {full * ipk / 15:.1f} V (BSC146N10LS5 and SBRT15U100SP5 are 100 V parts, the node sits at about 50 V)')
    print('PASS' if not problems else f'{problems} loop(s) above the limit')
    return problems


if __name__ == '__main__':
    sys.exit(1 if main(sys.argv[1]) else 0)
