"""Return-path and reference-plane check of the cheap-1 board from the copper export.

  python check_return_paths.py board.json [--png out.png]      # board.json from export_view.py (KiCad Python)

Plain Python with numpy, scipy and Pillow. In1 is the solid GND plane (JLC04161H-7628: 0.21 mm of prepreg to F.Cu and
to In2, so F.Cu and In2 signals run over GND, B.Cu runs over the In2 +3V3 flood). The script reports

 1. In1 integrity: copper islands, voids larger than 8 mm2 (THT antipads, via fields) with their position;
 2. the narrowest continuous GND copper (bottleneck width) between the 24 V input GND terminal and the GND of the power
    stages (LED shunts, converters, heater, connectors) - the return path of every switching current;
 3. for every F.Cu and In2 track the length that runs over a void of In1 (no GND underneath), per net, with the longest
    uninterrupted stretch; for B.Cu the same against the In2 +3V3 flood;
 4. signal vias (power nets excluded) that change between a GND-referenced layer (F.Cu, In2) and B.Cu (referenced to +3V3) with
   no GND via within 2.5 mm (information only).
Switching nets (SW nodes, boost nodes, converter inputs) are listed separately.
"""
import json
import math
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

RES = 0.05
X0, Y0, X1, Y1 = 50.0, 50.0, 150.0, 150.0
W, H = int((X1 - X0) / RES), int((Y1 - Y0) / RES)
# nets with fast edges or switched current; the DC LED outputs and returns are not in this list
SWITCHING = ('LED1_SW', 'LED2_SW', 'BUCK12_SW', 'BUCK_SW', 'LED1_VIN', 'LED2_VIN', 'AUX_VIN', 'HEATER_DRAIN',
             'LED1_SOURCE', 'LED2_SOURCE', 'BUCK12_BOOT')
MAX_BARE_SWITCHING = 3.0      # mm of a switching track that may run without GND underneath
POWER_VIAS = ('+12V', '+3V3', 'AUX_VIN', 'LED1_OUT', 'LED2_OUT', 'LED1_VIN', 'LED2_VIN', '+24V', '+24V_LOADS')
# (label, reference of a pad whose GND copper is the target)
TARGETS = [('LED1 shunt R715', 'R715', '2'), ('LED2 shunt R725', 'R725', '2'), ('LED1 return R716', 'R716', '2'),
           ('LED2 return R726', 'R726', '2'), ('heater Q601 source', 'Q601', '3'), ('ST1S14 U902 EP', 'U902', '9'),
           ('ST1S10 U101 EP', 'U101', '9'), ('input cap C901', 'C901', '2'), ('ESP32 U201 EP', 'U201', '39'),
           ('boost diode side C716', 'C716', '2'), ('boost diode side C726', 'C726', '2')]


def px(pt):
    return ((pt[0] - X0) / RES, (pt[1] - Y0) / RES)


def zone_mask(data, net, layer):
    img = Image.new('L', (W, H), 0)
    d = ImageDraw.Draw(img)
    for z in data['zones']:
        if z['layer'] == layer and z['net'] == net:
            for poly in z['polys']:
                d.polygon([px(q) for q in poly['o']], fill=255)
                for hole in poly['h']:
                    d.polygon([px(q) for q in hole], fill=0)
    return np.array(img) > 0


def pad_point(data, ref, number, net='GND'):
    for pad in data['pads']:
        if pad['ref'] == ref and pad['n'] == number:
            return (pad['x'], pad['y'])
    return None


def widest(mask, a, b):
    inner = ndimage.distance_transform_edt(mask) * RES
    near = int(round(2.0 / RES))
    ya, xa = (int(round(c)) for c in px(a)[::-1])
    yb, xb = (int(round(c)) for c in px(b)[::-1])

    def touching(lab, y, x):
        win = lab[max(0, y - near):y + near + 1, max(0, x - near):x + near + 1]
        return set(np.unique(win)) - {0}

    lo, hi = 0.0, 60.0
    for _ in range(14):
        mid = (lo + hi) / 2
        lab, _n = ndimage.label(inner >= mid / 2, structure=np.ones((3, 3)))
        if touching(lab, ya, xa) & touching(lab, yb, xb):
            lo = mid
        else:
            hi = mid
    return max(0.0, lo - RES)


def main(path, png=None):
    data = json.load(open(path))
    gnd = zone_mask(data, 'GND', 'I1')
    flood = zone_mask(data, '+3V3', 'I2')
    board = np.zeros((H, W), bool)
    board[int(0.5 / RES):H - int(0.5 / RES), int(0.5 / RES):W - int(0.5 / RES)] = True
    problems = 0

    # 1. integrity
    lab, n = ndimage.label(gnd, structure=np.ones((3, 3)))
    sizes = ndimage.sum(gnd, lab, range(1, n + 1)) * RES * RES
    big = sorted(sizes, reverse=True)
    print(f'In1 GND: {n} copper piece(s), largest {big[0]:.0f} mm2' + (f', others {[round(s, 1) for s in big[1:6]]} mm2' if n > 1 else ''))
    if n > 1 and big[1] > 2:
        problems += 1
        print('  FAIL: In1 has isolated copper islands above 2 mm2')
    voids, nv = ndimage.label(board & ~gnd, structure=np.ones((3, 3)))
    areas = ndimage.sum(board & ~gnd, voids, range(1, nv + 1)) * RES * RES
    rows = []
    for i, a in enumerate(areas, 1):
        if a >= 8:
            ys, xs = np.nonzero(voids == i)
            rows.append((a, X0 + xs.mean() * RES, Y0 + ys.mean() * RES, (xs.max() - xs.min()) * RES, (ys.max() - ys.min()) * RES))
    rows.sort(reverse=True)
    print(f'In1 voids above 8 mm2: {len(rows)}')
    for a, x, y, w, h in rows[:12]:
        print(f'  {a:6.1f} mm2 at ({x:.1f}, {y:.1f}), {w:.1f} x {h:.1f} mm')
    solid = gnd.sum() / board.sum()
    print(f'In1 GND covers {solid * 100:.1f} % of the board')

    # 2. return-path bottlenecks from the input terminal
    src = pad_point(data, 'J901', '1')
    union = gnd | zone_mask(data, 'GND', 'F') | zone_mask(data, 'GND', 'B')
    print(f'GND bottleneck from the input terminal J901.1 {src}: In1 alone (0.5 oz) / F.Cu + In1 + B.Cu fills, each at least 5 mm')
    for label, ref, number in TARGETS:
        pt = pad_point(data, ref, number)
        if pt is None:
            print(f'  {label}: pad {ref}.{number} not found')
            continue
        w1, w3 = widest(gnd, src, pt), widest(union, src, pt)
        ok = w1 >= 5 and w3 >= 5
        problems += not ok
        print(f'  {"ok  " if ok else "FAIL"} {label} {ref}.{number}: {w1:.1f} / {w3:.1f} mm')

    # 3. tracks over voids
    refs = {'F.Cu': gnd, 'In2.Cu': gnd, 'B.Cu': flood}
    per_net = {}
    for t in data['tracks']:
        mask = refs.get(t['layer'])
        net = t['net'].split('/')[-1]
        if mask is None or net in ('GND',) or not net:
            continue
        length = math.hypot(t['x1'] - t['x0'], t['y1'] - t['y0'])
        steps = max(1, int(length / 0.25))
        run = per_net.setdefault((net, t['layer']), dict(length=0.0, bare=0.0, longest=0.0, cur=0.0, at=None))
        for i in range(steps + 1):
            x = t['x0'] + (t['x1'] - t['x0']) * i / steps
            y = t['y0'] + (t['y1'] - t['y0']) * i / steps
            ix, iy = int((x - X0) / RES), int((y - Y0) / RES)
            covered = 0 <= ix < W and 0 <= iy < H and mask[iy, ix]
            seg = length / steps
            run['length'] += seg
            if covered:
                run['cur'] = 0.0
            else:
                run['bare'] += seg
                run['cur'] += seg
                if run['cur'] > run['longest']:
                    run['longest'] = run['cur']
                    run['at'] = (round(x, 1), round(y, 1))
    print('tracks over a void of their reference plane (F.Cu/In2 over In1 GND, B.Cu over In2 +3V3):')
    worst = sorted(((v['bare'], k, v) for k, v in per_net.items() if v['bare'] > 0.5), reverse=True)
    for bare, (net, layer), v in worst[:15]:
        switching = net in SWITCHING
        flag = 'SWITCHING ' if switching else ''
        if switching and v['longest'] > MAX_BARE_SWITCHING:
            problems += 1
            flag = 'FAIL ' + flag
        print(f'  {flag}{net} {layer}: {bare:.1f} of {v["length"]:.1f} mm bare, longest {v["longest"]:.1f} mm near {v["at"]}')
    for net in SWITCHING:
        for layer in ('F.Cu', 'In2.Cu', 'B.Cu'):
            v = per_net.get((net, layer))
            if v and v['bare'] <= 0.5:
                pass
    bare_total = sum(v['bare'] for v in per_net.values())
    print(f'  total track length without its reference: {bare_total:.1f} mm of {sum(v["length"] for v in per_net.values()):.0f} mm')

    # 4. signal vias between a GND-referenced layer and B.Cu
    on_b = {(round(t['x0'], 2), round(t['y0'], 2)) for t in data['tracks'] if t['layer'] == 'B.Cu'} | \
           {(round(t['x1'], 2), round(t['y1'], 2)) for t in data['tracks'] if t['layer'] == 'B.Cu'}
    gvias = [(v['x'], v['y']) for v in data['vias'] if v['net'] == 'GND']
    lonely = []
    for v in data['vias']:
        net = v['net'].split('/')[-1]
        if net in ('GND', '') or net in POWER_VIAS or (round(v['x'], 2), round(v['y'], 2)) not in on_b:
            continue
        near = min((math.hypot(v['x'] - gx, v['y'] - gy) for gx, gy in gvias), default=99)
        if near > 2.5:
            lonely.append((net, round(v['x'], 1), round(v['y'], 1), round(near, 1)))
    print(f'signal vias onto B.Cu with no GND via within 2.5 mm: {len(lonely)}')
    for row in lonely[:12]:
        print('  ', row)
    if png:
        rgb = np.zeros((H, W, 3), np.uint8) + 255
        rgb[board & gnd] = (200, 225, 200)
        rgb[board & ~gnd] = (230, 120, 120)
        Image.fromarray(rgb).resize((W // 2, H // 2)).save(png)
    print('PASS' if not problems else f'{problems} problem(s)')
    return problems


if __name__ == '__main__':
    sys.exit(1 if main(sys.argv[1], sys.argv[sys.argv.index('--png') + 1] if '--png' in sys.argv else None) else 0)
