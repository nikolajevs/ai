"""Clean up the silkscreen of the cheap-1 board (KiCad Python): fix_silk.py board.kicad_pcb [--write]

1. silk lines of footprints that cross a pad or leave the board outline (connector bodies overhanging the edge, the
   L711 axis lines through its pads) are removed on this board, and where outlines of two footprints touch the shorter
   line goes;
2. EVERY reference designator is put on the silkscreen of its side (F.Silkscreen, or B.Silkscreen for a footprint on the
   bottom), visible, 1.0 mm high with a 0.2 mm stroke (JLCPCB minimum height 1.0 mm). A designator that lived on F.Fab
   or was hidden is brought over; a designator or board label that touches a pad, a hole or via, a silk line, another
   text or the board edge is moved to the nearest free place (both orientations). Only when nothing is free within
   MAX_GAP the designator is hidden and listed in the output.

The check is geometric, stroke against stroke (silk_model.py), as DRC does. Texts without a conflict are not touched,
so the script is repeatable. CLI DRC and check_fab.py remain the judges.
"""
import math
import sys
from pathlib import Path

import pcbnew as p
import silk_model as m

MM = p.FromMM
MAX_GAP = 8.0           # mm between the footprint pads and the moved text
STEP_GAP = 0.25
STEP_SLIDE = 0.5
SIZE = 1.0              # JLCPCB: silk text at least 1.0 mm high, so there is no smaller fallback
STROKE = 0.2            # JLCDFM warns below 0.2 mm strokes


def anchor_box(owner):
    """bounding box (nm) of what the text belongs to: the pads of a footprint, or the label itself"""
    if hasattr(owner, 'Pads'):
        boxes = [pad.GetBoundingBox() for pad in owner.Pads()]
        return (min(b.GetLeft() for b in boxes), min(b.GetTop() for b in boxes),
                max(b.GetRight() for b in boxes), max(b.GetBottom() for b in boxes))
    b = owner.GetBoundingBox()
    return (b.GetLeft(), b.GetTop(), b.GetRight(), b.GetBottom())


def set_text(text, size, angle):
    text.SetTextSize(p.VECTOR2I(MM(size), MM(size)))
    text.SetTextThickness(MM(STROKE))
    text.SetTextAngleDegrees(angle)
    text.SetHorizJustify(p.GR_TEXT_H_ALIGN_CENTER)
    text.SetVertJustify(p.GR_TEXT_V_ALIGN_CENTER)
    m.refresh(text)


def place(text, cx, cy):
    text.SetPosition(p.VECTOR2I(int(cx), int(cy)))
    m.refresh(text)


def centre_of(item):
    return (item.box[0] + item.box[2]) / 2, (item.box[1] + item.box[3]) / 2


def remove_lines(board, removed):
    """step 1: silk lines that cross pads or the outline, and the shorter of two touching outlines"""
    for flipped in (False, True):
        pads = [o for o in m.pad_items(board, flipped) if o.kind == 'pad']
        for fp in board.GetFootprints():
            if fp.IsFlipped() != flipped:
                continue
            for g in m.silk_graphics(fp):
                it = m.Item(g.GetEffectiveShape(), 0.0, fp.GetReference(), 'line')
                if m.outside_edge(it.box, margin=0.15) or any(m.collides(it, o) for o in pads):
                    removed.append((fp.GetReference(), g.GetShapeStr()))
                    fp.Remove(g)
                    m.GRAVEYARD.append(g)
        lines = [(g, fp, m.Item(g.GetEffectiveShape(), m.SILK_CLEAR, fp.GetReference(), 'line'))
                 for fp in board.GetFootprints() if fp.IsFlipped() == flipped for g in m.silk_graphics(fp)]
        gone = set()
        for i, (g1, fp1, a) in enumerate(lines):
            for g2, fp2, b in lines[i + 1:]:
                if fp1 is fp2 or id(g1) in gone or id(g2) in gone or not m.collides(a, b):
                    continue
                span = lambda it: (it.box[2] - it.box[0]) ** 2 + (it.box[3] - it.box[1]) ** 2
                g, fp = (g1, fp1) if span(a) <= span(b) else (g2, fp2)
                gone.add(id(g))
                removed.append((fp.GetReference(), g.GetShapeStr()))
                fp.Remove(g)
                m.GRAVEYARD.append(g)


def run(board, verbose=True):
    removed = []
    remove_lines(board, removed)
    # --- 2. every designator on the silkscreen of its side ----------------------------------------------------
    texts, side_of, brought = {}, {}, []
    for fp in board.GetFootprints():
        r = fp.Reference()
        layer = m.silk_layer(fp.IsFlipped())
        was_hidden = not r.IsVisible()
        if r.GetLayer() != layer or was_hidden or abs(p.ToMM(r.GetTextHeight()) - SIZE) > 1e-6:
            if r.GetLayer() != layer or was_hidden:
                brought.append(fp.GetReference())
            r.SetLayer(layer)
            r.SetVisible(True)
            set_text(r, SIZE, r.GetTextAngleDegrees() if r.GetTextAngleDegrees() in (0.0, 90.0) else 0.0)
        texts[fp.GetReference()] = (r, fp)
        side_of[fp.GetReference()] = fp.IsFlipped()
    for d in board.GetDrawings():
        if d.GetLayer() in (p.F_SilkS, p.B_SilkS) and hasattr(d, 'GetText'):
            name = 'text:' + d.GetText()
            texts[name] = (d, d)
            side_of[name] = d.GetLayer() == p.B_SilkS
    obstacles = {flipped: m.pad_items(board, flipped) + m.graphic_items(board, flipped) for flipped in (False, True)}
    live = {name: m.text_item(t, name, 'text') for name, (t, _o) in texts.items()}

    def conflicts(name, it):
        flipped = side_of[name]
        n = sum(m.collides(it, o) for o in obstacles[flipped])
        for other, o in live.items():
            if other != name and side_of[other] == flipped:
                n += m.collides(it, o)
        return n + (1 if m.outside_edge(it.box) else 0)

    order = sorted(texts, key=lambda k: -conflicts(k, live[k]))
    moved, hidden = [], []
    for name in order:
        text, owner = texts[name]
        if conflicts(name, live[name]) == 0:
            continue
        orig = (text.GetPosition().x, text.GetPosition().y, text.GetTextAngleDegrees())
        A = anchor_box(owner)
        mid = ((A[0] + A[2]) / 2, (A[1] + A[3]) / 2)
        found = None
        for angle in (0.0, 90.0):
            set_text(text, SIZE, angle)
            place(text, *centre_of(live[name]))      # measure the size once at the old centre
            shape = m.text_item(text, name, 'text')
            hw, hh = (shape.box[2] - shape.box[0]) / 2, (shape.box[3] - shape.box[1]) / 2
            cands = []
            for gi in range(int(MAX_GAP / STEP_GAP) + 1):
                gap = MM(gi * STEP_GAP)
                for side in range(4):
                    if side < 2:                        # above / below
                        cy = A[1] - gap - hh if side == 0 else A[3] + gap + hh
                        slide = [(x, cy) for x in range(int(A[0] - hw), int(A[2] + hw) + 1, MM(STEP_SLIDE))]
                    else:                               # left / right
                        cx = A[0] - gap - hw if side == 2 else A[2] + gap + hw
                        slide = [(cx, y) for y in range(int(A[1] - hh), int(A[3] + hh) + 1, MM(STEP_SLIDE))]
                    for x, y in slide:
                        cands.append((gi * STEP_GAP + 0.01 * math.hypot(x - mid[0], y - mid[1]) / 1e6, x, y))
            cands.sort()
            for _score, x, y in cands:
                place(text, x, y)
                it = m.text_item(text, name, 'text')
                if conflicts(name, it) == 0:
                    found = (angle, x, y)
                    break
            if found:
                break
        if found:
            place(text, found[1], found[2])
            live[name] = m.text_item(text, name, 'text')
            moved.append(name)
        else:
            set_text(text, SIZE, orig[2])
            place(text, orig[0], orig[1])
            if hasattr(owner, 'Pads'):
                text.SetVisible(False)
                del live[name]
                hidden.append(name)
            else:
                live[name] = m.text_item(text, name, 'text')
                hidden.append(name + ' (label left in place)')
    left = [k for k in live if conflicts(k, live[k])]
    if verbose:
        print('removed silk lines:', len(removed), sorted({r[0] for r in removed}))
        print(f'designators brought onto the silkscreen: {len(brought)}; moved: {len(moved)}; hidden: {len(hidden)} {hidden}')
        print('texts still in conflict:', left)
    return not left


if __name__ == '__main__':
    path = sys.argv[1]
    board = p.LoadBoard(path)
    ok = run(board)
    if '--write' in sys.argv:
        p.SaveBoard(path, board)
        text = Path(path).read_text(encoding='utf-8')
        Path(path).write_text(text, encoding='utf-8', newline='\n')
    sys.exit(0 if ok else 1)
