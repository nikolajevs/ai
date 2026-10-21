#!/usr/bin/env python3
"""Complete the PCB routing after route_power.py: RF keepout, Freerouting result, ground pours.

  route_board.py --board B.kicad_pcb                 reproduce from routing/pass1.ses + pass2.ses
  route_board.py --board B.kicad_pcb --jar freerouting.jar --java java --work DIR [--passes 40]

Requires KiCad pcbnew. The board must come from build_board.py + route_power.py (the reviewed
LED1 plan is kept as fixed wiring). Earlier output of this script is removed first, so the step
can be repeated. The order is:

1. All-layer copper keepout over the ESP32 antenna (the RF reserve checked by verify_board.py).
2. Specctra DSN export. In1.Cu (GND plane) is declared a power layer, so no signal uses it.
   Router widths of the LOAD class are narrowed to reach fine-pitch pins (ROUTER_WIDTHS).
3. Freerouting 2.4.1 (Java 25) without fan-out and telemetry, or import of a saved session.
   The router is not deterministic; the committed session file is the record of the result.
4. Imported copper gets UUIDs derived from its geometry, so the same session gives the same board.
5. Ground stitching vias next to the high-current ground pads, GND pours on F.Cu and B.Cu,
   zone fill.

Ampacity, temperature and EMC are not qualified by this script.
SPDX-License-Identifier: MIT
"""
import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
from pathlib import Path

import pcbnew as p

from build_board import HERE, identity, point
from route_complete import complete
from route_power import plan_items

MM = p.FromMM
NO_ROUTE_LAYERS = ['In1.Cu']
# Router-only widths (mm): the project classes stay wider for review. The router cannot neck a
# wide track down to 0.65 mm pitch pins of U101/U501/U601.
ROUTER_WIDTHS = {'LOAD': 0.6}
# Second pass, everything from the first pass fixed: narrower widths for the leftovers that need
# to pass between fine-pitch pins or other copper. Heavy paths themselves come from pass one.
# Short controller nets around the LM3429 (B side, between the heatsink keepouts) and the
# L7987 AUX buck: routed first by the grid router so the autorouter cannot box them in.
PREROUTE = {f'LED{k}_{n}' for k in (1, 2) for n in ('CSH', 'CSH_MID', 'RCT', 'RT_MID', 'HSN', 'HSP', 'VCC', 'COMP', 'OVP', 'OVP_MID', 'GATE_RAW')} | \
    {'AUX_FB', 'AUX_FB_MID', 'AUX_COMP', 'AUX_COMP_MID', 'AUX_SS', 'AUX_FSW', 'AUX_ILIM', 'AUX_BOOT'}
SECOND_PASS_WIDTHS = {'HEAVY24': 1.0, 'LOAD': 0.4, 'PWR': 0.3}
RF_KEEPOUT = [4.5, 0.0, 52.5, 7.44]       # ESP32 antenna reserve on the board, verify_board.py
POUR_CLEARANCE = .2
# High-current ground pads: (pad, vias wanted). Each 0.3 mm via carries about 1 A.
GROUND_TIES = {'Q102.3': 10, 'Q703.3': 6, 'R501.2': 4, 'R601.2': 4, 'Q704.2': 2, 'D101.2': 2,
               'C101.2': 3, 'J501.2': 3, 'J602.2': 3}
TIE_VIA = (0.6, 0.3)


def um(v):
    return round(v / 1000)


def snap(x, y):
    """Board point on a 1 um grid; Freerouting writes 0.1 um, so session copies compare equal."""
    return p.VECTOR2I(um(x) * 1000, um(y) * 1000)


def geometry(item):
    if isinstance(item, p.PCB_VIA):
        pos = item.GetPosition()
        return ('via', item.GetNetCode(), (pos.x, pos.y))
    a, b = item.GetStart(), item.GetEnd()
    return ('track', item.GetNetCode(), item.GetLayer(), item.GetWidth(), (a.x, a.y), (b.x, b.y))


def same(g, h, tol=2000):
    """Equal up to the 0.1 um rounding of a Freerouting session (2 um tolerance)."""
    if g[:2] != h[:2] or len(g) != len(h) or (g[0] == 'track' and (g[2] != h[2] or abs(g[3] - h[3]) > tol)):
        return False
    pts_g, pts_h = g[2:3] if g[0] == 'via' else g[4:], h[2:3] if h[0] == 'via' else h[4:]
    close = lambda u, v: abs(u[0] - v[0]) <= tol and abs(u[1] - v[1]) <= tol
    return all(close(u, v) for u, v in zip(pts_g, pts_h)) or (len(pts_g) == 2 and close(pts_g[0], pts_h[1]) and close(pts_g[1], pts_h[0]))


def key_of(item):
    if isinstance(item, p.PCB_VIA):
        pos = item.GetPosition()
        return f'via/{item.GetNetname()}/{um(pos.x)}/{um(pos.y)}'
    return (f'track/{item.GetNetname()}/{item.GetLayer()}/{um(item.GetWidth())}/'
            f'{um(item.GetStart().x)}/{um(item.GetStart().y)}/{um(item.GetEnd().x)}/{um(item.GetEnd().y)}')


def rect_zone(board, name, net, layers, box, rule=False):
    zone = p.ZONE(board)
    identity(zone, name)
    ls = p.LSET()
    for layer in layers:
        ls.AddLayer(board.GetLayerID(layer))
    zone.SetLayerSet(ls)
    if rule:
        zone.SetIsRuleArea(True)
        zone.SetDoNotAllowTracks(True)
        zone.SetDoNotAllowVias(True)
        zone.SetDoNotAllowZoneFills(True)
        zone.SetDoNotAllowPads(False)
        zone.SetDoNotAllowFootprints(False)
    else:
        zone.SetNet(board.FindNet(net))
        zone.SetLocalClearance(MM(POUR_CLEARANCE))
        zone.SetMinThickness(MM(.25))
        zone.SetPadConnection(p.ZONE_CONNECTION_THT_THERMAL)
        zone.SetThermalReliefGap(MM(.3))
        zone.SetThermalReliefSpokeWidth(MM(.5))
        zone.SetIslandRemovalMode(p.ISLAND_REMOVAL_MODE_ALWAYS)
        zone.SetAssignedPriority(0)
    zone.SetZoneName(name)
    outline = zone.Outline()
    outline.NewOutline()
    x0, y0, x1, y1 = box
    for x, y in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]:
        outline.Append(MM(x), MM(y))
    return zone


def clear_previous(board, plan):
    keep = {i.m_Uuid.AsString() for i in plan_items(board, plan)}
    planned = {v.m_Uuid.AsString() for v in [*board.GetTracks(), *board.Zones()]} & keep
    if len(planned) != len(keep):
        raise RuntimeError('Run route_power.py first: the reviewed LED1 plan is incomplete')
    removed = 0
    for item in list(board.GetTracks()):
        if item.m_Uuid.AsString() not in keep:
            board.Delete(item)
            removed += 1
    for zone in list(board.Zones()):
        if zone.GetZoneName().startswith('route_board/'):
            board.Delete(zone)
            removed += 1
    return removed


def run_router(board, args, widths, name):
    work = Path(args.work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    dsn = work / f'{name}.dsn'
    if not p.ExportSpecctraDSN(board, str(dsn)):
        raise RuntimeError('DSN export failed')
    text = dsn.read_text(encoding='utf-8')
    for layer in NO_ROUTE_LAYERS:
        marker = f'(layer {layer}\n      (type signal)'
        if text.count(marker) != 1:
            raise RuntimeError(f'DSN layer {layer} not found')
        text = text.replace(marker, f'(layer {layer}\n      (type power)')
    for cls, width in widths.items():
        head = text.index(f'(class {cls} ')
        rule = text.index('(width ', head)
        end = text.index(')', rule)
        text = text[:rule] + f'(width {round(width * 1000)}' + text[end:]
    dsn.write_text(text, encoding='utf-8')
    out = work / f'{name}.ses'
    if out.exists():
        out.unlink()
    cmd = [args.java, '-jar', str(Path(args.jar).resolve()), '-de', dsn.name, '-do', out.name,
           '-mp', str(args.passes), '-l', 'en', '--gui.enabled=false', '--router.fanout.enabled=false',
           '--usage_and_diagnostic_data.disable_analytics=true', '--profile.allow_telemetry=false']
    with open(work / f'{name}.log', 'w') as log:
        subprocess.run(cmd, cwd=work, stdout=log, stderr=subprocess.STDOUT, check=True)
    if not out.exists():
        raise RuntimeError('Freerouting wrote no session file')
    return out


def import_session(board, ses, work):
    # KiCad 10 rejects a session that carries Freerouting's placement block; the placement
    # is unchanged, so only the routes are imported. Locked copper is kept by the importer.
    text = Path(ses).read_text(encoding='utf-8')
    start = text.find('  (placement')
    if start >= 0:
        text = text[:start] + text[text.index('  (routes', start):]
    stripped = Path(work).resolve() / 'routes_only.ses'
    stripped.parent.mkdir(parents=True, exist_ok=True)
    stripped.write_text(text, encoding='utf-8')
    present = []
    for item in board.GetTracks():
        item.SetLocked(True)                # the importer replaces unlocked copper
        present.append(geometry(item))
    if not p.ImportSpecctraSES(board, str(stripped)):
        raise RuntimeError(f'session import failed: {ses}')
    # Fixed wiring comes back as protected session wires; drop these copies.
    for item in list(board.GetTracks()):
        if not item.IsLocked() and any(same(geometry(item), g) for g in present):
            board.Delete(item)


HOLE_TO_HOLE = 0.25  # board setup minimum hole-to-hole spacing, mm


def drop_conflicts(board, fixed):
    """Delete imported router copper that breaks clearance to copper fixed before the router ran.

    A session made before a change in routing.json may cross new planned copper; the grid
    completion then reroutes the connections that lose a track."""
    gap = MM(POUR_CLEARANCE) - 1000
    layers = (p.F_Cu, p.In2_Cu, p.B_Cu)

    def box(item):
        b = item.GetBoundingBox()
        return b.GetLeft() - gap, b.GetTop() - gap, b.GetRight() + gap, b.GetBottom() + gap

    def near(a, b):
        return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]

    def item_layers(item):
        return [l for l in layers if item.IsOnLayer(l)]

    others = [(t, box(t), item_layers(t)) for t in board.GetTracks() if t.m_Uuid.AsString() in fixed]
    others += [(pad, box(pad), item_layers(pad)) for fp in board.GetFootprints() for pad in fp.Pads()
               if pad.GetAttribute() != p.PAD_ATTRIB_NPTH]
    holes = [(t.GetPosition(), t.GetDrillValue() // 2) for t in board.GetTracks()
             if t.m_Uuid.AsString() in fixed and isinstance(t, p.PCB_VIA)]
    holes += [(pad.GetPosition(), max(pad.GetDrillSize().x, pad.GetDrillSize().y) // 2)
              for fp in board.GetFootprints() for pad in fp.Pads() if pad.HasHole()]
    dropped = []
    for item in list(board.GetTracks()):
        if item.m_Uuid.AsString() in fixed:
            continue
        if isinstance(item, p.PCB_VIA):
            # Hole spacing applies to every net, including the via's own.
            pos, r = item.GetPosition(), item.GetDrillValue() // 2
            if any((pos - at).EuclideanNorm() - r - hr < MM(HOLE_TO_HOLE) for at, hr in holes):
                dropped.append(item.GetNetname())
                board.Delete(item)
                continue
        b, own = box(item), item_layers(item)
        for other, ob, olayers in others:
            if other.GetNetCode() == item.GetNetCode() or not near(b, ob):
                continue
            if any(other.GetEffectiveShape(l).Collide(item.GetEffectiveShape(l), gap) for l in own if l in olayers):
                dropped.append(item.GetNetname())
                board.Delete(item)
                break
    return dropped


def replace_session_nets(board, fixed, plan):
    """Delete imported router copper on nets that routing.json now plans by hand.

    Sessions made before such a plan still carry the old autorouted copper of these nets;
    the plan and the grid completion connect them instead."""
    nets = set(plan.get('replace_session_nets', []))
    dropped = []
    for item in list(board.GetTracks()):
        if item.m_Uuid.AsString() not in fixed and item.GetNetname() in nets:
            dropped.append(item.GetNetname())
            board.Delete(item)
    return dropped


def prune_dangling(board, nets):
    """Remove dead-end tracks and vias of the given nets, left over from dropped session copper."""
    removed = 0
    while True:
        board.BuildConnectivity()
        conn = board.GetConnectivity()
        items = [i for i in board.GetTracks() if i.GetNetname() in nets]
        dead = []
        for item in items:
            if isinstance(item, p.PCB_VIA):
                pos, r = item.GetPosition(), item.GetWidth(p.F_Cu) // 2
                layers = set()
                for other in items:
                    if not isinstance(other, p.PCB_VIA) and any((e - pos).EuclideanNorm() <= r for e in (other.GetStart(), other.GetEnd())):
                        layers.add(other.GetLayer())
                for fp in board.GetFootprints():
                    for pad in fp.Pads():
                        if pad.GetNetCode() == item.GetNetCode():
                            layers |= {l for l in (p.F_Cu, p.In2_Cu, p.B_Cu) if pad.IsOnLayer(l) and pad.HitTest(pos)}
                if len(layers) < 2:
                    dead.append(item)
            elif conn.TestTrackEndpointDangling(item, False):
                dead.append(item)
        if not dead:
            return removed
        for item in dead:
            board.Delete(item)
            removed += 1


def blocked(board, pos, radius, net):
    """True if a via of this radius at pos would come within POUR_CLEARANCE of foreign copper."""
    circle = p.SHAPE_CIRCLE(pos, radius)
    gap = MM(.25)
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetCode() == net.GetNetCode() and pad.GetAttribute() != p.PAD_ATTRIB_NPTH:
                if pad.GetEffectiveShape(p.B_Cu if fp.IsFlipped() else p.F_Cu).Collide(circle, MM(.1)):
                    return True     # keep vias off pads (no via-in-pad)
                continue
            for layer in (p.F_Cu, p.B_Cu, p.In2_Cu):
                if pad.IsOnLayer(layer) and pad.GetEffectiveShape(layer).Collide(circle, gap):
                    return True
            # keep the escape area of fine-pitch IC pins free for their own routes
            if fp.GetReference().startswith('U') and pad.GetAttribute() == p.PAD_ATTRIB_SMD and \
                    min(pad.GetSize().x, pad.GetSize().y) <= MM(.6) and pad.GetEffectiveShape(p.B_Cu if fp.IsFlipped() else p.F_Cu).Collide(circle, MM(1.3)):
                return True
            if pad.HasHole() and pad.GetEffectiveHoleShape().Collide(circle, MM(.3)):
                return True
    for item in board.GetTracks():
        if item.GetNetCode() == net.GetNetCode() and not isinstance(item, p.PCB_VIA):
            continue
        if isinstance(item, p.PCB_VIA):
            if item.GetEffectiveShape(p.F_Cu).Collide(circle, MM(.3)):
                return True
        elif item.GetLayer() != p.In1_Cu and item.GetEffectiveShape().Collide(circle, gap):
            return True
    for zone in [*board.Zones(), *(z for fp in board.GetFootprints() for z in fp.Zones())]:
        if zone.GetIsRuleArea() and (zone.GetDoNotAllowVias() or zone.GetDoNotAllowTracks()):
            if zone.Outline().Collide(pos, radius + MM(.2)):
                return True
    edge = board.GetBoardEdgesBoundingBox()
    margin = MM(.5) + radius
    return not (edge.GetLeft() + margin < pos.x < edge.GetRight() - margin and edge.GetTop() + margin < pos.y < edge.GetBottom() - margin)


def ground_ties(board):
    """Stitching vias on a ring around each high-current ground pad, joined by the outer pours."""
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    gnd = board.FindNet('GND')
    added = {}
    for anchor, wanted in GROUND_TIES.items():
        ref, number = anchor.split('.')
        pad = next(v for v in fps[ref].Pads() if v.GetNumber() == number)
        if pad.GetNetname() != 'GND':
            raise RuntimeError(f'{anchor} is not GND')
        bb = pad.GetBoundingBox()
        c = pad.GetPosition()
        half = max(bb.GetWidth(), bb.GetHeight()) / 2
        count = 0
        for ring in (half + MM(.9), half + MM(1.7), half + MM(2.5)):
            steps = max(8, int(2 * math.pi * ring / MM(1.1)))
            for k in range(steps):
                if count >= wanted:
                    break
                a = 2 * math.pi * k / steps
                pos = snap(c.x + ring * math.cos(a), c.y + ring * math.sin(a))
                if blocked(board, pos, MM(TIE_VIA[0]) // 2, gnd):
                    continue
                via = p.PCB_VIA(board)
                via.SetPosition(pos)
                via.SetWidth(MM(TIE_VIA[0]))
                via.SetDrill(MM(TIE_VIA[1]))
                via.SetViaType(p.VIATYPE_THROUGH)
                via.SetLayerPair(p.F_Cu, p.B_Cu)
                via.SetNet(gnd)
                identity(via, f'route_board/tie/{anchor}/{k}/{ring}')
                board.Add(via)
                count += 1
        added[anchor] = count
    return added


def stub_blocked(board, track, layer, net, pad):
    shape = track.GetEffectiveShape()
    gap = MM(.25)
    for zone in [*board.Zones(), *(z for fp in board.GetFootprints() for z in fp.Zones())]:
        if zone.GetIsRuleArea() and zone.GetDoNotAllowTracks() and zone.IsOnLayer(layer):
            if zone.Outline().Collide(shape, MM(.1)):
                return True
    for fp in board.GetFootprints():
        for other in fp.Pads():
            if other.GetNetCode() == net.GetNetCode() or not other.IsOnLayer(layer):
                continue
            if other.GetEffectiveShape(layer).Collide(shape, gap):
                return True
    for item in board.GetTracks():
        if item.GetNetCode() == net.GetNetCode():
            continue
        if isinstance(item, p.PCB_VIA):
            if item.GetEffectiveShape(layer).Collide(shape, gap):
                return True
        elif item.GetLayer() == layer and item.GetEffectiveShape().Collide(shape, gap):
            return True
    return False


def exposed_pad_vias(board):
    """Thermal/ground vias inside the exposed GND pads of ICs (via-in-pad is normal for these)."""
    gnd = board.FindNet('GND')
    added = {}
    r = MM(TIE_VIA[0]) // 2
    for fp in board.GetFootprints():
        if not fp.GetReference().startswith(('U', 'BT')):
            continue
        for pad in fp.Pads():
            bb = pad.GetBoundingBox()
            if pad.GetNetname() != 'GND' or bb.GetWidth() * bb.GetHeight() < MM(1.4) * MM(1.4):
                continue
            layer = p.B_Cu if fp.IsFlipped() else p.F_Cu
            shape = pad.GetEffectiveShape(layer)
            count = 0
            pitch = MM(1.2)
            nx = max(1, int((bb.GetWidth() - 2 * r) // pitch) + 1)
            ny = max(1, int((bb.GetHeight() - 2 * r) // pitch) + 1)
            x0 = bb.Centre().x - (nx - 1) * pitch // 2
            y0 = bb.Centre().y - (ny - 1) * pitch // 2
            for i in range(nx):
                for j in range(ny):
                    pos = snap(x0 + i * pitch, y0 + j * pitch)
                    circle = p.SHAPE_CIRCLE(pos, r + MM(.05))
                    inside = all(shape.Collide(p.VECTOR2I(int(pos.x + (r + MM(.05)) * math.cos(a)), int(pos.y + (r + MM(.05)) * math.sin(a))))
                                 for a in [k * math.pi / 4 for k in range(8)])
                    if not inside or foreign_copper(board, circle, gnd, (p.F_Cu, p.In2_Cu, p.B_Cu)):
                        continue
                    new_via(board, pos, f'route_board/ep/{fp.GetReference()}.{pad.GetNumber()}/{i}/{j}')
                    count += 1
            added[f'{fp.GetReference()}.{pad.GetNumber()}'] = count
    return added


def foreign_copper(board, circle, net, layers):
    gap = MM(.25)
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetCode() == net.GetNetCode():
                continue
            for layer in layers:
                if pad.IsOnLayer(layer) and pad.GetEffectiveShape(layer).Collide(circle, gap):
                    return True
    for item in board.GetTracks():
        if item.GetNetCode() == net.GetNetCode():
            continue
        if isinstance(item, p.PCB_VIA):
            if item.GetEffectiveShape(p.F_Cu).Collide(circle, MM(.3)):
                return True
        elif item.GetLayer() in layers and item.GetEffectiveShape().Collide(circle, gap):
            return True
    for zone in [*board.Zones(), *(z for fp in board.GetFootprints() for z in fp.Zones())]:
        if zone.GetIsRuleArea() and zone.GetDoNotAllowVias() and zone.Outline().Collide(circle.GetCenter(), circle.GetRadius()):
            return True
    return False


def tie_remaining_ground(board):
    """A via and a short stub for every GND pad that the filled copper does not join to In1."""
    p.ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()
    conn = board.GetConnectivity()
    gnd = board.FindNet('GND')
    plane = [z for z in board.Zones() if z.GetNetname() == 'GND' and z.GetLayer() == p.In1_Cu]
    plane_ids = {z.m_Uuid.AsString() for z in plane}
    tied, failed = [], []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname() != 'GND' or pad.GetAttribute() in (p.PAD_ATTRIB_NPTH, p.PAD_ATTRIB_PTH):
                continue
            reached = {i.m_Uuid.AsString() for i in conn.GetConnectedItems(pad)}
            if reached & plane_ids:
                continue
            layer = p.B_Cu if fp.IsFlipped() else p.F_Cu
            c = pad.GetPosition()
            done = False
            for r in (1.0, 1.4, 1.8, 2.3, 2.9, 3.6):
                for ang in range(0, 360, 15):
                    pos = snap(c.x + MM(r) * math.cos(math.radians(ang)), c.y + MM(r) * math.sin(math.radians(ang)))
                    if blocked(board, pos, MM(TIE_VIA[0]) // 2, gnd):
                        continue
                    stub = p.PCB_TRACK(board)
                    stub.SetStart(c)
                    stub.SetEnd(pos)
                    stub.SetWidth(MM(.3))
                    stub.SetLayer(layer)
                    stub.SetNet(gnd)
                    if stub_blocked(board, stub, layer, gnd, pad):
                        continue
                    via = p.PCB_VIA(board)
                    via.SetPosition(pos)
                    via.SetWidth(MM(TIE_VIA[0]))
                    via.SetDrill(MM(TIE_VIA[1]))
                    via.SetViaType(p.VIATYPE_THROUGH)
                    via.SetLayerPair(p.F_Cu, p.B_Cu)
                    via.SetNet(gnd)
                    name = f'{fp.GetReference()}.{pad.GetNumber()}'
                    identity(via, f'route_board/gtie/{name}/via')
                    identity(stub, f'route_board/gtie/{name}/stub')
                    board.Add(stub)
                    board.Add(via)
                    tied.append(name)
                    done = True
                    break
                if done:
                    break
            if not done:
                failed.append(f'{fp.GetReference()}.{pad.GetNumber()}')
    return tied, failed


def new_via(board, pos, name):
    via = p.PCB_VIA(board)
    via.SetPosition(pos)
    via.SetWidth(MM(TIE_VIA[0]))
    via.SetDrill(MM(TIE_VIA[1]))
    via.SetViaType(p.VIATYPE_THROUGH)
    via.SetLayerPair(p.F_Cu, p.B_Cu)
    via.SetNet(board.FindNet('GND'))
    identity(via, name)
    board.Add(via)
    return via


def stitch_islands(board):
    """Join every outer-layer GND pour island without a plane connection to In1 with vias."""
    p.ZONE_FILLER(board).Fill(board.Zones())
    gnd = board.FindNet('GND')
    anchors = [v.GetPosition() for v in board.GetTracks() if isinstance(v, p.PCB_VIA) and v.GetNetname() == 'GND']
    anchors += [pad.GetPosition() for fp in board.GetFootprints() for pad in fp.Pads()
                if pad.GetNetname() == 'GND' and pad.GetAttribute() == p.PAD_ATTRIB_PTH]
    r = MM(TIE_VIA[0]) // 2
    ring = [(math.cos(a * math.pi / 4), math.sin(a * math.pi / 4)) for a in range(8)]
    added, failed = 0, 0
    for zone in board.Zones():
        if not zone.GetZoneName().startswith('route_board/gnd-'):
            continue
        layer = zone.GetLayer()
        filled = zone.GetFilledPolysList(layer)
        for i in range(filled.OutlineCount()):
            island = p.SHAPE_POLY_SET()
            island.AddOutline(filled.Outline(i))
            for h in range(filled.HoleCount(i)):
                island.AddHole(filled.Hole(i, h))
            if any(island.Contains(a) for a in anchors):
                continue
            bb = island.BBox()
            done = False
            step = MM(.25)
            y = bb.GetTop() + r
            while y < bb.GetBottom() - r and not done:
                x = bb.GetLeft() + r
                while x < bb.GetRight() - r:
                    pos = snap(x, y)
                    if island.Contains(pos) and all(island.Contains(p.VECTOR2I(int(x + (r + MM(.15)) * c), int(y + (r + MM(.15)) * s))) for c, s in ring) \
                            and not blocked(board, pos, r, gnd):
                        new_via(board, pos, f'route_board/stitch/{layer}/{x}/{y}')
                        anchors.append(pos)
                        added += 1
                        done = True
                        break
                    x += step
                y += step
            if not done:
                failed += 1
                print('unjoined island', board.GetLayerName(layer), [round(p.ToMM(v), 1) for v in (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom())], round(island.Area() / 1e12, 2))
    p.ZONE_FILLER(board).Fill(board.Zones())
    return added, failed


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--board', type=Path, default=HERE / 'PCB_EU.kicad_pcb')
    ap.add_argument('--ses-dir', type=Path, default=HERE / 'routing')
    ap.add_argument('--jar', help='run Freerouting and overwrite the session files in --ses-dir')
    ap.add_argument('--java', default=os.environ.get('JAVA', 'java'))
    ap.add_argument('--passes', type=int, default=40)
    ap.add_argument('--work', default='freerouting-work')
    ap.add_argument('--reuse-pass1', type=Path, help='skip the first router pass and use this session')
    args = ap.parse_args()
    if not args.board.with_suffix('.kicad_pro').exists():
        raise RuntimeError('Copy PCB_EU.kicad_pro beside the board with the same basename')
    plan = json.loads((HERE / 'routing.json').read_text())

    def prepare():
        board = p.LoadBoard(str(args.board))
        removed = clear_previous(board, plan)
        # Ground vias first, so the router keeps clear of them (as in PCB_V1).
        ties = ground_ties(board)
        ep = exposed_pad_vias(board)
        tied, untied = tie_remaining_ground(board)
        pre, pre_failed = complete(board, only=PREROUTE)
        if pre_failed:
            print('pre-route failed:', pre_failed)
        return board, removed, ties, ep, tied, untied

    board, removed, ties, ep, tied, untied = prepare()
    fixed = len(board.GetTracks())
    sessions = [args.ses_dir / 'pass1.ses', args.ses_dir / 'pass2.ses']
    if args.jar:
        args.ses_dir.mkdir(parents=True, exist_ok=True)
        if not args.reuse_pass1:
            shutil.copyfile(run_router(board, args, ROUTER_WIDTHS, 'pass1'), sessions[0])
        elif args.reuse_pass1.resolve() != sessions[0].resolve():
            shutil.copyfile(args.reuse_pass1, sessions[0])
        import_session(board, sessions[0], args.work)
        for item in board.GetTracks():
            item.SetLocked(True)
        shutil.copyfile(run_router(board, args, SECOND_PASS_WIDTHS, 'pass2'), sessions[1])
        board, removed, ties, ep, tied, untied = prepare()
    fixed_ids = {item.m_Uuid.AsString() for item in board.GetTracks()}
    for ses in sessions:
        import_session(board, ses, args.work)
    dropped = replace_session_nets(board, fixed_ids, plan) + drop_conflicts(board, fixed_ids)
    for item in board.GetTracks():
        item.SetLocked(False)
    keep = {i.m_Uuid.AsString() for i in plan_items(board, plan)}
    seen = set()
    for item in sorted(board.GetTracks(), key=key_of):
        if item.m_Uuid.AsString() in keep:
            continue
        name = 'route_board/auto/' + hashlib.sha1(key_of(item).encode()).hexdigest()
        while name in seen:
            name += '+'
        seen.add(name)
        identity(item, name)
    routed, failed = complete(board)
    # GND is left out: its session vias are stitching vias that only connect once the pours exist.
    pruned = prune_dangling(board, set(dropped) - {'GND'})
    for layer, name in (('F.Cu', 'gnd-top'), ('B.Cu', 'gnd-bottom')):
        board.Add(rect_zone(board, 'route_board/' + name, 'GND', [layer], [0.3, 0.3, 99.7, 99.7]))
    stitched, unstitched = stitch_islands(board)
    p.ZONE_FILLER(board).Fill(board.Zones())
    g_routed, g_failed = complete(board, only={'GND'})
    routed += g_routed
    failed += g_failed
    board.BuildConnectivity()
    p.ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()
    for item in board.GetDrawings():
        if isinstance(item, p.PCB_TEXT) and 'ROUTING' in item.GetText() and item.GetText().startswith('EU-0.1'):
            item.SetText('EU-0.1 / ROUTED, NOT RELEASED / 100 x 100 mm / 4 Cu')
    p.SaveBoard(str(args.board), board)
    unrouted = board.GetConnectivity().GetUnconnectedCount(False)
    print(json.dumps(dict(removed_previous=removed, fixed_before_router=fixed, tracks_and_vias=len(board.GetTracks()),
                          ground_tie_vias=ties, exposed_pad_vias=ep, pad_ties=len(tied), untied_ground_pads=untied, dropped_session_copper=sorted(set(dropped)), pruned_dead_ends=pruned, island_vias=stitched, unjoined_islands=unstitched, completed=len(routed), completion_failed=failed, unrouted=unrouted)))


if __name__ == '__main__':
    main()
