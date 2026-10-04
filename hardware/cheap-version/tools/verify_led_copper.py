"""Copper-width regression screen for the LED / +24V distribution stage (reinforce_led.py).

  python verify_led_copper.py board.json        # board.json from export_view.py (KiCad Python) of the filled board

Plain Python with numpy, scipy and Pillow. For every entry of PATHS the widest continuous copper path of one net on one
layer between two points is computed on the FILLED copper (pads, tracks, vias and zone fills of that net), as the largest
w such that discs of diameter w fit along a connected route (bottleneck width, 0.05 mm raster, conservative by one pixel).
The via arrays that join the layers are counted separately. CLI DRC and the whole-board power-path review remain necessary.
"""
import json
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

RES = 0.05
X0, Y0, X1, Y1 = 50.0, 50.0, 150.0, 150.0
W, H = int((X1 - X0) / RES), int((Y1 - Y0) / RES)
LED = '/LEDDrivers/'
# (label, net, layer, A, B, minimum width in mm)
PATHS = [
    ('+24V input pour -> crossing vias', '+24V', 'F', (77, 72), (82.5, 76.4), 3.5),
    ('+24V trunk to the CH1 via array', '+24V', 'B', (82.5, 76.4), (75, 106.4), 3.5),
    ('+24V trunk to the CH2 branch', '+24V', 'B', (75, 104.3), (100.0, 106.0), 2.4),
    ('+24V CH1 feed to F711', '+24V', 'F', (75, 107.2), (57.8, 106.3), 3.0),
    ('+24V CH2 feed to F721', '+24V', 'F', (100.0, 106.0), (102.19, 106.25), 2.0),
    ('LED1_VIN F711 -> L711', LED + 'LED1_VIN', 'F', (57.8, 111.2), (62.15, 120.0), 2.5),
    ('LED1_VIN F711 -> C715', LED + 'LED1_VIN', 'F', (57.8, 111.2), (55.88, 120.0), 1.5),
    ('LED1_SW L711 -> Q711', LED + 'LED1_SW', 'F', (79.65, 120.0), (85.8, 116.85), 3.0),
    ('LED1_SW Q711 -> D711', LED + 'LED1_SW', 'F', (85.8, 116.85), (83.93, 113.06), 1.4),
    ('LED2_VIN F721 -> L721', LED + 'LED2_VIN', 'F', (107.11, 106.25), (108.55, 114.85), 2.5),
    ('LED2_SW L721 -> Q721', LED + 'LED2_SW', 'F', (119.65, 114.85), (124.45, 115.2), 3.0),
    ('LED2_SW Q721 -> D721', LED + 'LED2_SW', 'F', (124.45, 115.2), (123.08, 111.41), 1.4),
    ('LED2_OUT via -> J731 on B.Cu', LED + 'LED2_OUT', 'B', (109.95, 109.76), (94.0, 144.1), 1.0),
]
# (label, net, region x0, y0, x1, y1, minimum count of vias of the net inside)
VIA_ARRAYS = [
    ('crossing vias', '+24V', (79.5, 73, 86, 79.2), 10),
    ('CH1 feed vias', '+24V', (71.5, 105.5, 79.2, 108.5), 12),
    ('CH2 feed vias', '+24V', (99.5, 104.3, 105.2, 108.0), 6),
]
LNAME = {'F': 'F.Cu', 'B': 'B.Cu'}


def px(pt):
    return ((pt[0] - X0) / RES, (pt[1] - Y0) / RES)


def copper(data, net, layer):
    img = Image.new('L', (W, H), 0)
    d = ImageDraw.Draw(img)
    for z in data['zones']:
        if z['net'] == net and z['layer'] == layer:
            for poly in z['polys']:
                d.polygon([px(q) for q in poly['o']], fill=255)
                for hole in poly['h']:
                    d.polygon([px(q) for q in hole], fill=0)
    for pad in data['pads']:
        if pad['net'] == net:
            for poly in pad['layers'].get(layer, []):
                d.polygon([px(q) for q in poly['o']], fill=255)
    for t in data['tracks']:
        if t['net'] == net and t['layer'] == LNAME[layer]:
            r = t['w'] / 2 / RES
            d.line([px((t['x0'], t['y0'])), px((t['x1'], t['y1']))], fill=255, width=max(1, int(round(t['w'] / RES))))
            for q in ((t['x0'], t['y0']), (t['x1'], t['y1'])):
                cx, cy = px(q)
                d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    for v in data['vias']:
        if v['net'] == net:
            cx, cy = px((v['x'], v['y']))
            r = v['d'] / 2 / RES
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    return np.array(img) > 0


def widest(mask, a, b):
    """Bottleneck width between the copper next to a and next to b (mm); 0 when not connected."""
    inner = ndimage.distance_transform_edt(mask) * RES
    ya, xa = (int(round(c)) for c in px(a)[::-1])
    yb, xb = (int(round(c)) for c in px(b)[::-1])
    near = int(round(1.6 / RES))

    def touching(lab, y, x):
        win = lab[max(0, y - near):y + near + 1, max(0, x - near):x + near + 1]
        return set(np.unique(win)) - {0}

    lo, hi = 0.0, 20.0
    if not (mask[max(0, ya - near):ya + near + 1, max(0, xa - near):xa + near + 1].any() and
            mask[max(0, yb - near):yb + near + 1, max(0, xb - near):xb + near + 1].any()):
        return 0.0
    for _ in range(16):
        mid = (lo + hi) / 2
        lab, _n = ndimage.label(inner >= mid / 2, structure=np.ones((3, 3)))
        if touching(lab, ya, xa) & touching(lab, yb, xb):
            lo = mid
        else:
            hi = mid
    return max(0.0, lo - RES)


def main(path):
    data = json.load(open(path))
    cache = {}
    bad = 0
    for label, net, layer, a, b, minimum in PATHS:
        key = (net, layer)
        if key not in cache:
            cache[key] = copper(data, net, layer)
        width = widest(cache[key], a, b)
        ok = width >= minimum
        bad += not ok
        print(f'{"ok  " if ok else "FAIL"} {label}: {width:.2f} mm (need {minimum})')
    for label, net, (x0, y0, x1, y1), minimum in VIA_ARRAYS:
        n = sum(1 for v in data['vias'] if v['net'] == net and x0 <= v['x'] <= x1 and y0 <= v['y'] <= y1)
        ok = n >= minimum
        bad += not ok
        print(f'{"ok  " if ok else "FAIL"} {label}: {n} vias (need {minimum})')
    for t in data['tracks']:
        if t['layer'] == 'In2.Cu' and t['net'].split('/')[-1] in ('+24V', 'LED2_OUT'):
            print('FAIL', t['net'], 'still has an In2 track', t['x0'], t['y0'])
            bad += 1
            break
    print('PASS' if not bad else f'{bad} FAILED')
    return bad


if __name__ == '__main__':
    sys.exit(1 if main(sys.argv[1]) else 0)
