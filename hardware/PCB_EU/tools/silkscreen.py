#!/usr/bin/env python3
"""Add readable, net-checked assembly silk without rewriting any routed geometry.

Run after routing, using KiCad 10's Python and Shapely. Existing Fab references,
library polarity marks and all underlying PCB items are preserved. The only change to
existing items is silk_clean.py: the silkscreen lines of library footprints are cut back to
0.15 mm from pads and holes and widened to 0.15 mm, as JLCPCB requires.
SPDX-License-Identifier: MIT
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile
import uuid

import pcbnew as p
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union
from shapely.strtree import STRtree

from models3d import spans
from silk_clean import clean_board
from verify_footprints import parse, child, children

HERE = Path(__file__).resolve().parents[1]
GROUP = 'PCB_EU assembly silkscreen'
TEXT_MM = 1.0   # JLCPCB: character height of at least 1.0 mm, stroke 0.15 mm (0.8-0.9 mm texts were used before 22.10.2026)
NS = uuid.UUID('b5e58c64-044f-432a-98f0-a378af7ff276')
# Pin labels are explicit: switched load returns and the raw PSU return are NOT GND.
CONNECTORS = {
    'J101': ('24V IN', [('+24V_RAW', '+'), ('PSU_RTN', '-')]),
    'J501': ('LED1', [('LED1_LED_POS', '+'), ('GND', '-')]),
    'J601': ('LED2', [('LED2_LED_POS', '+'), ('GND', '-')]),
    'J602': ('LED2 BAR2', [('LED2_LED_POS', '+'), ('GND', '-')]),
    'J701': ('PTC', [('+24V_PTC', '+'), ('PTC_DRAIN', '-')]),
    'J702': ('PUMP', [('+24V_PUMP', '+'), ('PUMP_DRAIN', '-')]),
    'J403': ('FLOAT', [('FLOAT_EXT', 'SIG'), ('GND', 'GND')]),
    'J401': ('SHT4x', [('+3V3', '3V3'), ('GND', 'GND'), ('SHT_SDA', 'SDA'), ('SHT_SCL', 'SCL')]),
    'J411': ('FAN1', [('GND', 'GND'), ('+12V_FANS', '+12V'), ('FAN1_TACH_EXT', 'TACH'), ('FAN1_PWM', 'PWM')]),
    'J421': ('FAN2', [('GND', 'GND'), ('+12V_FANS', '+12V'), ('FAN2_TACH_EXT', 'TACH'), ('FAN2_PWM', 'PWM')]),
    'J201': ('UART', [('GND', 'GND'), ('+3V3', '3V3'), ('UART_TX', 'TX'), ('UART_RX', 'RX'), ('ESP_EN', 'EN'), ('ESP_BOOT', 'BOOT')]),
}


def ident(name):
    return str(uuid.uuid5(NS, name))


def without_generated(text):
    """Remove only our group and its board texts/dots, never native library marks."""
    edits = []
    members = set()
    for a, b in spans(text, 'group'):
        node = parse(text[a:b])
        if node[1] == GROUP:
            members.update(child(node, 'members')[1:])
            edits.append((a, b))
    for tag in ('gr_text', 'gr_circle'):
        for a, b in spans(text, tag):
            node = parse(text[a:b])
            if child(node, 'uuid')[1] in members:
                edits.append((a, b))
                members.remove(child(node, 'uuid')[1])
    if members:
        raise RuntimeError('Managed silkscreen group contains unexpected items (only texts and dots are generated)')
    for a, b in sorted(edits, reverse=True):
        text = text[:a] + text[b:]
    # Native KiCad saves managed texts on indented lines. Removing their forms
    # must not retain hundreds of whitespace-only lines on each regeneration.
    text = re.sub(r'(?m)^[ \t]+$', '', text)
    # Generated nodes are inserted immediately before the final board close.
    return text[:text.rfind(')')].rstrip() + '\n)\n'


FP_SILK_SHAPES = ('fp_line', 'fp_arc', 'fp_circle', 'fp_rect', 'fp_poly', 'fp_text')


def without_footprint_silk(board_node):
    """Board tree minus the silkscreen shapes and texts of its footprints (the only items silk_clean.py may change)."""
    def on_silk(node):
        return any(isinstance(x, list) and x[:1] == ['layer'] and x[1:2] and x[1] in ('F.SilkS', 'B.SilkS') for x in node)
    out = []
    for node in board_node:
        if isinstance(node, list) and node[:1] == ['footprint']:
            node = [c for c in node if not (isinstance(c, list) and c[:1] and c[0] in FP_SILK_SHAPES and on_silk(c))]
        out.append(node)
    return out


def clean_library_silk(text):
    """(text, {reference: [pieces kept, shapes cut]}): the library silk of the board cut back from pads and holes.

    pcbnew does the geometry on a temporary copy; only the footprints it changed are spliced into the
    text, so every other byte of the board stays."""
    with tempfile.TemporaryDirectory(prefix='eu-silk-clean-') as tmp:
        source = Path(tmp) / 'PCB_EU.kicad_pcb'
        source.write_text(text)
        board = p.LoadBoard(str(source))
        changed = clean_board(board)
        if not changed:
            return text, changed
        target = Path(tmp) / 'cleaned.kicad_pcb'
        p.SaveBoard(str(target), board)
        saved = target.read_text()
    old, new = spans(text, 'footprint'), spans(saved, 'footprint')
    if len(old) != len(new):
        raise RuntimeError('pcbnew changed the number of footprints')
    edits = []
    for (a, b), (c, d) in zip(old, new):
        if text[a:b] != saved[c:d]:
            ref = re.search(r'\(property "Reference" "([^"]+)"', saved[c:d]).group(1)
            if ref not in changed:
                raise RuntimeError(f'{ref}: pcbnew rewrote a footprint that silk_clean.py did not change')
            edits.append((a, b, saved[c:d]))
    result = text
    for a, b, value in sorted(edits, reverse=True):
        result = result[:a] + value + result[b:]
    if without_footprint_silk(parse(result)) != without_footprint_silk(parse(text)):
        raise RuntimeError('silk_clean.py changed more than footprint silkscreen shapes')
    return result, changed


def rect(item):
    r = item.GetBoundingBox()
    return box(p.ToMM(r.GetX()), p.ToMM(r.GetY()),
               p.ToMM(r.GetRight()), p.ToMM(r.GetBottom()))


def courtyard(fp):
    poly = fp.GetCourtyard(p.B_CrtYd if fp.IsFlipped() else p.F_CrtYd)
    outline = poly.Outline(0)
    return Polygon([(p.ToMM(outline.CPoint(i).x), p.ToMM(outline.CPoint(i).y))
                    for i in range(outline.PointCount())])


class Layout:
    def __init__(self, board):
        self.board = board
        self.fps = {f.GetReference(): f for f in board.GetFootprints()}
        self.bodies = {r: courtyard(fp) for r, fp in self.fps.items()}
        self.obstacles = {'F': [], 'B': []}
        self.owners = {'F': [], 'B': []}  # (footprint ref or None, kind, tight keep-out) for each obstacle
        self.pad_rects = {'F': [], 'B': []}  # (ref, bounding box) of every copper pad on each face
        self.labels = []
        self.skipped = []
        self.native_marks = []
        for ref, fp in self.fps.items():
            face = 'B' if fp.IsFlipped() else 'F'
            self.obstruct(face, self.bodies[ref].buffer(.12), ref, 'courtyard')
            if re.fullmatch(r'H\d+', ref):
                self.obstruct('B', self.bodies[ref].buffer(.12), ref, 'courtyard')
            for pad in fp.Pads():
                for side, layer in [('F', p.F_Mask), ('B', p.B_Mask)]:
                    if pad.IsOnLayer(layer):
                        self.pad_rects[side].append((ref, rect(pad)))
                        expansion = max(0, p.ToMM(pad.GetSolderMaskExpansion(layer)))
                        self.obstruct(side, rect(pad).buffer(.25 + expansion), ref, 'pad', rect(pad).buffer(.15 + expansion))
            for g in [*fp.GraphicalItems(), *fp.GetFields()]:
                if g.GetLayer() in (p.F_SilkS, p.B_SilkS):
                    if not hasattr(g, 'IsVisible') or g.IsVisible():
                        self.obstruct('B' if g.GetLayer() == p.B_SilkS else 'F', rect(g).buffer(.2), ref, 'silk')
        for g in board.GetDrawings():
            if g.GetLayer() in (p.F_SilkS, p.B_SilkS):
                self.obstruct('B' if g.GetLayer() == p.B_SilkS else 'F', rect(g).buffer(.2))
        # Conservatively avoid all vias, including those covered by solder mask.
        for track in board.GetTracks():
            if isinstance(track, p.PCB_VIA):
                for side in ['F', 'B']:
                    self.obstruct(side, rect(track).buffer(.25), None, 'via')
        spec = json.loads((HERE / 'placement.json').read_text())
        for reserve in spec['heatsink_reserves']:
            self.obstruct(reserve['side'], box(*reserve['box']).buffer(.25), None, 'reserve')
        self.trees = {side: STRtree(items) for side, items in self.obstacles.items()}
        self.pad_trees = {side: STRtree([r for _, r in items]) for side, items in self.pad_rects.items()}
        self.placed = {'F': [], 'B': []}

    def native_pin1(self, ref, pin):
        """True if the library footprint already draws a pin-1 mark on silk: a filled shape within 3 mm
        of pad `pin`, or a (hollow) circle nearer to pad `pin` than to any other pad of the part."""
        fp = self.fps[ref]
        layer = p.B_SilkS if fp.IsFlipped() else p.F_SilkS
        target = rect([a for a in fp.Pads() if a.GetNumber() == str(pin)][0])
        others = [rect(a) for a in fp.Pads() if a.GetNumber() and a.GetNumber() != str(pin)]
        for g in fp.GraphicalItems():
            if g.GetLayer() != layer or not isinstance(g, p.PCB_SHAPE):
                continue
            mark = rect(g)
            if g.IsSolidFill() and mark.distance(target) < 3:
                return True
            if g.GetShape() == p.SHAPE_T_CIRCLE and mark.distance(target) < 1 \
                    and all(mark.distance(o) > mark.distance(target) for o in others):
                return True
        return False

    def obstruct(self, side, geometry, ref=None, kind='other', tight=None):
        self.obstacles[side].append(geometry)
        self.owners[side].append((ref, kind, tight))  # tight: smaller keep-out used only by pin-1 dots

    def dot(self, ref, pin, net, diameters=(.6, .5), margins=(.25, .05), foreign=(.3, .1, 0), max_outside=1.0):
        """Filled silk dot beside pad `pin` on the component side.

        Library IC footprints carry pin 1 only on Fab. The dot may sit inside the IC's own
        courtyard (between its pads and the courtyard edge) but not on pads, vias, other silk
        or other parts' courtyards, and it must be nearer to pad `pin` than to any other pad.
        Outside the IC's pad rows it must be within `max_outside` mm of the pad and 0.3 mm
        (0.1 mm if nothing else fits) nearer to pad `pin` than to any pad of another part, so it
        cannot be read as the mark of a neighbour; between the pad rows (under the package) it
        needs neither.
        Pads keep 0.15 mm (+ mask expansion) clear of a dot instead of the 0.25 mm used for text.
        Where the neighbourhood is too tight, the dot shrinks from 0.6 to 0.5 mm and may be only
        0.05 mm nearer to pad `pin` than to any other pad (it then marks the pin-1 end of the
        package, which fixes the rotation of a dual-row part), otherwise the margin is 0.25 mm.
        """
        fp = self.fps[ref]
        side = 'B' if fp.IsFlipped() else 'F'
        pads = [pad for pad in fp.Pads() if pad.GetNumber() == str(pin)]
        if not pads or any(pad.GetNetname() != net for pad in pads):
            raise RuntimeError(f'{ref}.{pin}: pin-1 dot disagrees with PCB net {net}')
        target = rect(pads[0])
        cx, cy = target.centroid.x, target.centroid.y
        others = [rect(a) for a in fp.Pads() if a.GetNumber() and a.GetNumber() != str(pin)]
        hull = unary_union([rect(a) for a in fp.Pads()]).convex_hull
        for apart, margin, diameter in [(f, m, d) for f in foreign for m in margins for d in diameters]:
            reach = max(target.bounds[2] - target.bounds[0], target.bounds[3] - target.bounds[1]) / 2 + max_outside + diameter
            candidates = []
            for step in range(0, int(reach / .1) + 1):
                for angle in range(0, 360, 10):
                    x = cx + step * .1 * math.cos(math.radians(angle))
                    y = cy + step * .1 * math.sin(math.radians(angle))
                    point = Point(x, y)
                    edge = target.distance(point) - diameter / 2
                    inside = hull.contains(point)
                    if edge > max_outside and not inside:
                        continue
                    candidates.append((inside, round(edge, 3), angle, step, x, y))
            candidates.sort()
            for under_body, edge, _, _, x, y in candidates:
                area = Point(x, y).buffer(diameter / 2)
                if not box(.3, .3, 99.7, 99.7).contains(area):
                    continue
                blocked = False
                for i in self.trees[side].query(area, predicate='intersects'):
                    owner, kind, tight = self.owners[side][i]
                    if (owner, kind) == (ref, 'courtyard'):
                        continue
                    if tight is None or area.intersects(tight):
                        blocked = True
                        break
                if blocked or any(area.intersects(o) for o in self.placed[side]):
                    continue
                if any(o.distance(Point(x, y)) < target.distance(Point(x, y)) + margin for o in others):
                    continue  # Always nearer to pad `pin` than to any other pad.
                if not under_body:
                    reach_own = target.distance(Point(x, y)) + apart
                    if any(self.pad_rects[side][i][0] != ref
                           for i in self.pad_trees[side].query(Point(x, y).buffer(reach_own), predicate='intersects')
                           if self.pad_rects[side][i][1].distance(Point(x, y)) < reach_own):
                        continue  # A neighbouring part's pad is as close: ambiguous.
                self.placed[side].append(area.buffer(.2))
                entry = dict(name=f'{ref}/pin/{pin}/dot/{side}', kind='dot', ref=ref, side=side, pin=str(pin), net=net,
                             at=[round(x, 4), round(y, 4)], diameter_mm=diameter, nearer_than_other_pads_mm=margin,
                             nearer_than_other_parts_mm=None if under_body else apart,
                             under_body=bool(under_body),
                             uuid=ident(f'{ref}/pin/{pin}/dot/{side}'))
                self.labels.append(entry)
                return entry
        self.skipped.append(dict(ref=ref, pin=str(pin), reason=f'no clear unambiguous space for a pin-1 dot within {max_outside} mm of the pad or between its pad rows'))
        return None

    def add(self, name, text, ref, side, size=TEXT_MM, anchor=None, max_distance=4, other_pins=(), rotation=0):
        fp = self.fps[ref]
        body = self.bodies[ref]
        # Native KiCad stroke-font bounds, including the bottom-side mirror.
        t = p.PCB_TEXT(self.board)
        t.SetText(text)
        t.SetLayer(p.B_SilkS if side == 'B' else p.F_SilkS)
        t.SetMirrored(side == 'B')
        t.SetTextAngle(p.EDA_ANGLE(rotation, p.DEGREES_T))
        t.SetTextSize(p.VECTOR2I(p.FromMM(size), p.FromMM(size)))
        t.SetTextThickness(p.FromMM(.15))
        t.SetPosition(p.VECTOR2I(0, 0))
        bounds = rect(t).bounds
        hw, hh = max(abs(bounds[0]), abs(bounds[2])), max(abs(bounds[1]), abs(bounds[3]))
        x0, y0, x1, y1 = body.bounds
        ax, ay = anchor or ((x0 + x1) / 2, (y0 + y1) / 2)
        candidates = []
        for distance in [.3, .7, 1.1, 1.5, 2, 2.5, 3]:
            for delta in [0, -.5, .5, -1, 1, -1.5, 1.5, -2, 2]:
                candidates.extend([(ax + delta, y0 - hh - distance),
                                   (ax + delta, y1 + hh + distance),
                                   (x0 - hw - distance, ay + delta),
                                   (x1 + hw + distance, ay + delta)])
        if anchor:
            # On the reverse of a through-hole connector/capacitor there is no
            # component body: place legends beside the actual joint if clear.
            for distance in [1.5, 1.8, 2.2, 2.6, 3, 3.5]:
                candidates.extend([(ax, ay - distance - hh), (ax, ay + distance + hh),
                                   (ax - distance - hw, ay), (ax + distance + hw, ay)])
        elif side != ('B' if fp.IsFlipped() else 'F'):
            # A connector body occupies only its mounting face; on the reverse,
            # use the empty space between solder joints before moving farther.
            candidates.extend([(x, y) for x in [ax, x0 + hw + .3, x1 - hw - .3]
                               for y in [ay, y0 + hh + .3, y1 - hh - .3]])
        candidates.sort(key=lambda xy: math.dist(xy, (ax, ay)))
        for x, y in candidates:
            area = box(x - hw, y - hh, x + hw, y + hh)
            if not box(.3, .3, 99.7, 99.7).contains(area):
                continue
            if anchor and math.dist((x, y), anchor) > max_distance:
                continue
            if ref == 'U202' and not anchor:
                # ESP32's courtyard includes a very wide RF reserve. Do not
                # mistake its remote corner for the actual module body.
                pos = fp.GetPosition()
                if abs(x - p.ToMM(pos.x)) > 12 or abs(y - p.ToMM(pos.y)) > 18:
                    continue
            if anchor and any(math.dist((x, y), other) < math.dist((x, y), anchor) + .25
                              for other in other_pins):
                continue  # Never move a polarity label closer to the opposite pin.
            if len(self.trees[side].query(area, predicate='intersects')) or any(area.intersects(o) for o in self.placed[side]):
                continue
            if not anchor:
                point = Point(x, y)
                own_distance = body.distance(point)
                if any(other.distance(point) + .05 < own_distance
                       for other_ref, other in self.bodies.items()
                       if other_ref != ref and (('B' if self.fps[other_ref].IsFlipped() else 'F') == side
                                                or ref.startswith('J') and other_ref.startswith('J'))):
                    continue
            self.placed[side].append(area.buffer(.2))
            entry = dict(name=name, text=text, ref=ref, side=side,
                         at=[round(x, 4), round(y, 4)], rotation_deg=rotation, size_mm=size, uuid=ident(name))
            self.labels.append(entry)
            return entry
        return None

    def pin(self, ref, pin, text, net, faces=None):
        fp = self.fps[ref]
        pads = [pad for pad in fp.Pads() if pad.GetNumber() == str(pin)]
        if not pads or any(pad.GetNetname() != net for pad in pads):
            raise RuntimeError(f'{ref}.{pin}: polarity legend disagrees with PCB net {net}')
        pos = pads[0].GetPosition()
        anchor = p.ToMM(pos.x), p.ToMM(pos.y)
        other_pins = [(p.ToMM(a.GetPosition().x), p.ToMM(a.GetPosition().y))
                      for a in fp.Pads() if a.GetNumber() and a.GetNumber() != str(pin)]
        # Pin legends on both faces where accessible; back viewed from below.
        result = []
        sides = faces or (['F', 'B'] if ref.startswith('J') or not (fp.GetAttributes() & p.FP_SMD) else ['B' if fp.IsFlipped() else 'F'])
        for side in sides:
            item = self.add(f'{ref}/pin/{pin}/{side}', text, ref, side,
                            TEXT_MM, anchor, 6, other_pins)
            if item:
                item.update(pin=str(pin), net=net)
                result.append(item)
        if not result:
            self.skipped.append(dict(ref=ref, pin=str(pin), text=text, reason='no clear space within 6 mm of pin'))


def render(labels):
    blocks = []
    for v in labels:
        x, y = v['at']
        if v.get('kind') == 'dot':
            # Filled circle: centre radius + half the 0.15 mm stroke (the JLCPCB minimum) = outer radius diameter / 2.
            r = round(v['diameter_mm'] / 2 - .075, 4)
            blocks.append(f'\t(gr_circle (center {x} {y}) (end {round(x + r, 4)} {y}) (stroke (width 0.15) (type default)) '
                          f'(fill yes) (layer "{v["side"]}.SilkS") (uuid "{v["uuid"]}"))')
            continue
        mirror = ' (justify mirror)' if v['side'] == 'B' else ''
        blocks.append(f'\t(gr_text {json.dumps(v["text"])} (at {x} {y} {v["rotation_deg"]}) '
                      f'(layer "{v["side"]}.SilkS") (uuid "{v["uuid"]}") '
                      f'(effects (font (size {v["size_mm"]} {v["size_mm"]}) (thickness 0.15)){mirror}))')
    members = ' '.join('"' + v['uuid'] + '"' for v in labels)
    blocks.append(f'\t(group "{GROUP}" (uuid "{ident(GROUP)}") (members {members}))')
    return '\n'.join(blocks) + '\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--board', type=Path, default=HERE / 'PCB_EU.kicad_pcb')
    ap.add_argument('--check', action='store_true', help='Require existing managed silk to match regeneration')
    ap.add_argument('--output', type=Path, default=HERE / 'review/silkscreen.json')
    args = ap.parse_args()
    if not p.Version().startswith('10.'):
        ap.error('KiCad 10 pcbnew is required; never downgrade the PCB file')
    original = args.board.read_text()
    base = without_generated(original)
    base, library_silk = clean_library_silk(base)
    if args.check and library_silk:
        raise RuntimeError(f'Library silkscreen is not cut back from pads: regenerate with tools/silkscreen.py ({sorted(library_silk)})')
    # pcbnew is used for geometry only; apart from the footprints in clean_library_silk its serializer never rewrites this board.
    with tempfile.TemporaryDirectory(prefix='eu-silkscreen-') as tmp:
        path = Path(tmp) / 'PCB_EU.kicad_pcb'
        path.write_text(base)
        layout = Layout(p.LoadBoard(str(path)))
    parts = {v['ref']: v for v in json.loads((HERE / 'design.json').read_text())['parts']}
    for ref, (_, pins) in CONNECTORS.items():
        for pin, (net, text) in enumerate(pins, 1):
            if parts[ref]['nets'][str(pin)] != net:
                raise RuntimeError(f'{ref}.{pin}: update reviewed connector legend for changed schematic net')
            layout.pin(ref, pin, text, net)
    for ref, (function, _) in CONNECTORS.items():
        placed = False
        for side in ['F', 'B']:
            item = layout.add(f'{ref}/function/{side}', f'{ref} {function}', ref, side)
            if not item:
                item = layout.add(f'{ref}/function/{side}', f'{ref} {function}', ref, side, rotation=90)
            placed |= item is not None
        if not placed:
            layout.skipped.append(dict(ref=ref, reason='connector title has no clear space'))
    for ref, text, side in [('J301', 'J301 microSD', 'B'), ('BT301', 'BT301 CR2032', 'B')]:
        if not (layout.add(f'{ref}/function', text, ref, side) or
                layout.add(f'{ref}/function', text, ref, side, rotation=90)):
            layout.skipped.append(dict(ref=ref, reason='no clear space for function label'))
    layout.pin('BT301', 1, '+', 'VBAT')
    # Library electrolytics already carry + and a negative half-disc on their
    # mounting face; add + on the solder face without duplicating native marks.
    for ref, fp in sorted(layout.fps.items()):
        if str(fp.GetFPID().GetLibItemName()).startswith('CP_Radial'):
            layout.pin(ref, 1, '+', parts[ref]['nets']['1'], faces=['F' if fp.IsFlipped() else 'B'])
    for ref, pin in [('D101', 1), ('D102', 1), ('D103', 1), ('D501', 1), ('D601', 1), ('D701', 1), ('D801', 3)]:
        layout.pin(ref, pin, 'K', parts[ref]['nets'][str(pin)])
    for ref in sorted(layout.fps):
        if ref.startswith('U'):
            if layout.native_pin1(ref, 1):
                layout.native_marks.append(ref)
                continue
            layout.dot(ref, 1, parts[ref]['nets']['1'])
    priorities = lambda r: (0 if r.startswith(('U', 'Q', 'D', 'C', 'BT', 'F')) else 1, r)
    for ref in sorted(layout.fps, key=priorities):
        if ref.startswith(('J', 'H')):
            continue
        side = 'B' if layout.fps[ref].IsFlipped() else 'F'
        if not layout.add(f'{ref}/reference', ref, ref, side):
            layout.skipped.append(dict(ref=ref, reason='no clear space for readable reference on component side'))
    updated = base[:base.rfind(')')] + render(layout.labels) + ')\n'
    if parse(without_generated(updated)) != parse(base):
        raise RuntimeError('Non-silkscreen PCB data changed')
    if args.check:
        old = {child(g, 'uuid')[1]: g for tag in ('gr_text', 'gr_circle') for g in children(parse(original), tag)}
        new = {child(g, 'uuid')[1]: g for tag in ('gr_text', 'gr_circle') for g in children(parse(updated), tag)}
        if old != new:
            raise RuntimeError('Managed silk is stale: regenerate with tools/silkscreen.py')
    else:
        args.board.write_text(updated)
    report = dict(pcbnew_version=p.Version(), minimum_text_mm=TEXT_MM, stroke_mm=.15,
                  generated_labels=len(layout.labels), labels_by_face=dict(Counter(v['side'] for v in layout.labels)),
                  references_placed=sum(v['name'].endswith('/reference') for v in layout.labels),
                  ic_pin1_dots=sum(v.get('kind') == 'dot' for v in layout.labels),
                  ic_native_pin1_marks=layout.native_marks,
                  preserved_native_marks='electrolytic + / negative half-disc, diode cathode outlines; library IC footprints without a silk pin-1 mark get a dot; native marks are kept; Fab references unchanged',
                  non_silkscreen_data_unchanged=True, labels=layout.labels, omitted=layout.skipped,
                  library_silk_cut={ref: dict(pieces_kept=v[0], shapes_cut=v[1]) for ref, v in sorted(library_silk.items())},
                  base_pcb_sha256=hashlib.sha256(base.encode()).hexdigest(),
                  source_sha256=hashlib.sha256(args.board.read_bytes()).hexdigest())
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(f'PASS | silkscreen | {len(layout.labels)} labels incl. {report["ic_pin1_dots"]} IC pin-1 dots; {report["references_placed"]} references; {len(layout.skipped)} omitted; all underlying PCB data preserved')


if __name__ == '__main__':
    main()
