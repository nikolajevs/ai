#!/usr/bin/env python3
"""Screening of copper ampacity on the 24 V power nets of PCB_EU.

For every net in SCENARIOS the tracks and vias are turned into a resistive network. The design
current is injected at the source pad and taken out at the sink pads; Kirchhoff's laws give the real
split between parallel tracks and layers. Each track piece gets a temperature rise from IPC-2221,
which is conservative (IPC-2152 gives lower values, especially with a plane next to the trace).

Only tracks and vias are modelled; pours are not, and a through-hole pad is a single node (its barrel
is not checked). Vias are compared with a rule of thumb, not a formula. The GND return, pours and the 12 V / 3.3 V rails
are not covered. Currents are worst-case design values, not measurements.

    python3 tools/ampacity.py [--board PCB_EU.kicad_pcb] [--outer-um 35] [--inner-um 17.5] [--json OUT]
"""
import argparse
import collections
import json
import math
import sys
from pathlib import Path

import numpy as np
import pcbnew

HERE = Path(__file__).resolve().parents[1]
RHO = 1.72e-5      # copper, ohm * mm at 20 C
VIA_R = 1.2e-3     # whole 0.3 mm drill barrel through 1.6 mm board, ohm
LAYERS = {pcbnew.F_Cu: 'F.Cu', pcbnew.In1_Cu: 'In1.Cu', pcbnew.In2_Cu: 'In2.Cu', pcbnew.B_Cu: 'B.Cu'}
ORDER = ['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu']
OUTER = ('F.Cu', 'B.Cu')

# net -> (source pad, {sink pad: A}). Worst-case DC design currents (DESIGN.md "Требования"):
# PTC 4.5, LED1 input 2.8, LED2 input 1.2, AUX 0.7, pump 0.3 -> 9.5 A total at the input.
SCENARIOS = {
    '+24V_RAW': ('J101.1', {'F101.1': 9.5}),
    'PSU_RTN': ('J101.2', {'Q102.2': 9.5}),
    'RTN_SHUNT': ('Q102.3', {'R111.2': 4.75, 'R112.2': 4.75}),
    '+24V_FUSED': ('F101.2', {'F102.1': 4.5, 'F103.1': 2.8, 'F104.1': 1.2, 'F105.1': 0.7, 'F106.1': 0.3}),
    '+24V_PTC': ('F102.2', {'J701.1': 4.5}),
    'PTC_DRAIN': ('J701.2', {'Q703.2': 4.5}),
    '+24V_LED1': ('F103.2', {'L501.1': 2.8}),
    '+24V_LED2': ('F104.2', {'L601.1': 1.2}),
}


def delta_t(i, width_mm, um, outer):
    """IPC-2221: I = k * dT^0.44 * A^0.725 (A in mil^2); k = 0.048 outer, 0.024 inner."""
    if i <= 0:
        return 0.0
    area_mil2 = width_mm * um * 1e-3 / (0.0254 ** 2)
    k = 0.048 if outer else 0.024
    return (i / (k * area_mil2 ** 0.725)) ** (1 / 0.44)


def analyze_net(board, pads, net, source, sinks, outer_um, inner_um):
    mm = lambda v: v / 1e6
    tracks = [t for t in board.GetTracks() if t.GetNetname() == net and t.GetClass() != 'PCB_VIA']
    vias = [t for t in board.GetTracks() if t.GetNetname() == net and t.GetClass() == 'PCB_VIA']
    netpads = {k: p for k, p in pads.items() if p.GetNetname() == net}

    def key_at(x, y, layer):
        for name, p in netpads.items():
            if p.IsOnLayer(layer) and p.HitTest(pcbnew.VECTOR2I(int(x), int(y))):
                return ('P', name)
        for i, v in enumerate(vias):
            if math.hypot(x - v.GetPosition().x, y - v.GetPosition().y) <= v.GetWidth(layer) / 2 + 1000:
                return ('V', i, LAYERS[layer])
        return ('J', LAYERS[layer], round(mm(x), 3), round(mm(y), 3))

    ends = collections.defaultdict(list)
    for t in tracks:
        ends[t.GetLayer()] += [(t.GetStart().x, t.GetStart().y), (t.GetEnd().x, t.GetEnd().y)]
    edges = []
    for t in tracks:
        layer, w = t.GetLayer(), t.GetWidth()
        ax, ay, cx, cy = t.GetStart().x, t.GetStart().y, t.GetEnd().x, t.GetEnd().y
        length = math.hypot(cx - ax, cy - ay)
        if length == 0:
            continue
        dx, dy = (cx - ax) / length, (cy - ay) / length
        cuts = {0.0, 1.0}
        cand = list(ends[layer]) + [(v.GetPosition().x, v.GetPosition().y) for v in vias]
        cand += [(p.GetPosition().x, p.GetPosition().y) for p in netpads.values() if p.IsOnLayer(layer)]
        for px, py in cand:
            s = (px - ax) * dx + (py - ay) * dy
            if 1000 < s < length - 1000 and abs((px - ax) * dy - (py - ay) * dx) <= w / 2:
                cuts.add(s / length)
        cuts = sorted(cuts)
        for u, v in zip(cuts, cuts[1:]):
            p0 = (ax + (cx - ax) * u, ay + (cy - ay) * u)
            p1 = (ax + (cx - ax) * v, ay + (cy - ay) * v)
            ka, kb = key_at(*p0, layer), key_at(*p1, layer)
            piece = math.hypot(p1[0] - p0[0], p1[1] - p0[1]) / 1e6
            if ka == kb or piece <= 0:
                continue
            name = LAYERS[layer]
            um = outer_um if name in OUTER else inner_um
            edges.append((ka, kb, RHO * piece / (mm(w) * um * 1e-3), ('trk', name, piece, mm(w), um)))
    for i, v in enumerate(vias):
        for l1, l2 in zip(ORDER, ORDER[1:]):
            edges.append((('V', i, l1), ('V', i, l2), VIA_R / 3, ('via', i)))

    keys = {}
    for ka, kb, _, _ in edges:
        for k in (ka, kb):
            keys.setdefault(k, len(keys))
    for pad in [source, *sinks]:
        if ('P', pad) not in keys:
            return {'net': net, 'error': f'pad {pad} is not on a track of the net'}
    n = len(keys)
    g = np.zeros((n, n))
    for ka, kb, r, _ in edges:
        i, j = keys[ka], keys[kb]
        g[i, i] += 1 / r
        g[j, j] += 1 / r
        g[i, j] -= 1 / r
        g[j, i] -= 1 / r
    inj = np.zeros(n)
    inj[keys[('P', source)]] += sum(sinks.values())
    for pad, amps in sinks.items():
        inj[keys[('P', pad)]] -= amps
    ref = keys[('P', next(iter(sinks)))]
    mask = np.ones(n, bool)
    mask[ref] = False
    volt = np.zeros(n)
    volt[mask] = np.linalg.lstsq(g[np.ix_(mask, mask)], inj[mask], rcond=None)[0]

    loss = 0.0
    segs = collections.defaultdict(lambda: {'length_mm': 0.0, 'i_max': 0.0})
    via_i = collections.defaultdict(float)
    for ka, kb, r, info in edges:
        cur = abs(volt[keys[ka]] - volt[keys[kb]]) / r
        loss += cur * cur * r
        if info[0] == 'trk':
            _, layer, piece, w, um = info
            s = segs[(layer, round(w, 2))]
            s['length_mm'] += piece
            s['i_max'] = max(s['i_max'], cur)
            s['um'] = um
        else:
            via_i[info[1]] = max(via_i[info[1]], cur)
    rows = []
    for (layer, w), s in sorted(segs.items()):
        rows.append({'layer': layer, 'width_mm': w, 'length_mm': round(s['length_mm'], 1), 'i_max_a': round(s['i_max'], 2),
                     'dt_ipc2221_c': round(delta_t(s['i_max'], w, s['um'], layer in OUTER), 1)})
    first = next(iter(sinks))
    drop = volt[keys[('P', source)]] - volt[keys[('P', first)]]
    # rule of thumb at ~20 C rise: about 1 A per 0.3 mm drill, 2 A per 0.5 mm drill, 3 A per 0.8 mm drill
    over = []
    for i, cur in sorted(via_i.items(), key=lambda kv: -kv[1]):
        drill = vias[i].GetDrillValue() / 1e6
        limit = 1.0 if drill < 0.4 else 2.0 if drill < 0.7 else 3.0
        if cur > limit:
            over.append({'at_mm': [round(mm(vias[i].GetPosition().x), 2), round(mm(vias[i].GetPosition().y), 2)],
                         'drill_mm': drill, 'i_a': round(cur, 2), 'rule_of_thumb_a': limit})
    return {'net': net, 'source': source, 'sinks': sinks, 'current_a': sum(sinks.values()),
            'drop_mv': round(drop * 1000, 1), 'loss_mw': round(loss * 1000), 'segments': rows,
            'vias': len(vias), 'via_i_max_a': round(max(via_i.values(), default=0.0), 2), 'vias_over_limit': over}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--board', type=Path, default=HERE / 'PCB_EU.kicad_pcb')
    ap.add_argument('--outer-um', type=float, default=35.0, help='outer copper thickness, um (35 = 1 oz)')
    ap.add_argument('--inner-um', type=float, default=17.5, help='inner copper thickness, um (17.5 = 0.5 oz)')
    ap.add_argument('--json', type=Path, help='also write the result as JSON')
    args = ap.parse_args()
    board = pcbnew.LoadBoard(str(args.board))
    pads = {fp.GetReference() + '.' + p.GetNumber(): p for fp in board.GetFootprints() for p in fp.Pads()}
    result = [analyze_net(board, pads, net, src, snk, args.outer_um, args.inner_um)
              for net, (src, snk) in SCENARIOS.items()]
    print(f'outer {args.outer_um:g} um, inner {args.inner_um:g} um, IPC-2221 temperature rise (conservative)')
    for r in result:
        if 'error' in r:
            print(f"{r['net']}: {r['error']}")
            continue
        print(f"\n{r['net']}  {r['source']} -> {', '.join(r['sinks'])}  {r['current_a']:g} A  "
              f"drop {r['drop_mv']} mV  copper loss {r['loss_mw']} mW  vias {r['vias']} (max {r['via_i_max_a']} A each)")
        for s in r['segments']:
            if s['i_max_a'] >= 0.05:
                print(f"  {s['layer']:6s} {s['width_mm']:4.2f} mm  {s['length_mm']:6.1f} mm  {s['i_max_a']:5.2f} A  dT {s['dt_ipc2221_c']:5.1f} C")
        for v in r['vias_over_limit']:
            print(f"  via at {v['at_mm']} drill {v['drill_mm']:g} mm carries {v['i_a']} A (rule of thumb {v['rule_of_thumb_a']:g} A)")
    if args.json:
        args.json.write_text(json.dumps({'outer_um': args.outer_um, 'inner_um': args.inner_um, 'nets': result},
                                        ensure_ascii=False, indent=1) + '\n')


if __name__ == '__main__':
    sys.exit(main())
