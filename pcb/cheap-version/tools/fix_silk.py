"""Clean up the silkscreen of the cheap-1 board (KiCad Python): fix_silk.py board.kicad_pcb [--write]

1. silk lines of footprints that cross a pad or leave the board outline (connector bodies overhanging the edge, the
   L711 axis lines through its pads) are removed on this board, and where outlines of two footprints touch the shorter
   line goes;
2. every visible reference designator and board label that touches a pad, a silk line, another text or the board edge is
   moved to the nearest free place (both orientations), hidden only as a last resort (listed in the output); text height stays 1.0 mm (JLCPCB minimum), stroke 0.2 mm.

Texts without a conflict are not touched, so the script is repeatable. The clearances are in silk_model.py (a little
above the project's DRC values); CLI DRC remains the judge.
"""
import math
import sys
from pathlib import Path

import pcbnew as p
import silk_model as m

MM = p.FromMM
MAX_GAP = 10.0          # mm between the footprint pads and the moved text
STEP_GAP = 0.2
STEP_SLIDE = 0.4
SIZES = (1.0,)          # JLCPCB: silk text at least 1.0 mm high, so there is no smaller fallback


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
    text.SetTextThickness(MM(0.2))     # JLCDFM warns below 0.2 mm strokes
    text.SetTextAngleDegrees(angle)
    text.SetHorizJustify(p.GR_TEXT_H_ALIGN_CENTER)
    text.SetVertJustify(p.GR_TEXT_V_ALIGN_CENTER)
    m.refresh(text)


def place(text, cx, cy):
    text.SetPosition(p.VECTOR2I(int(cx), int(cy)))
    m.refresh(text)


def centre_of(item):
    return (item.box[0] + item.box[2]) / 2, (item.box[1] + item.box[3]) / 2


def run(board, verbose=True):
    removed = []
    pads = m.pad_items(board)
    # --- 1. silk lines that cross pads or the outline ------------------------------------------------------
    for fp in board.GetFootprints():
        for g in m.silk_graphics(fp):
            it = m.Item(g.GetEffectiveShape(), 0.0, fp.GetReference(), 'line')
            if m.outside_edge(it.box, margin=0.15) or any(m.collides(it, o) for o in pads if o.kind == 'pad'):
                removed.append((fp.GetReference(), g.GetShapeStr()))
                fp.Remove(g)
                m.GRAVEYARD.append(g)
    # silk lines of different footprints that touch each other (outlines of tightly packed parts): drop the shorter one
    lines = [(g, fp, m.Item(g.GetEffectiveShape(), m.SILK_CLEAR, fp.GetReference(), 'line'))
             for fp in board.GetFootprints() for g in m.silk_graphics(fp)]
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
    graphics = m.graphic_items(board)
    # --- 2. texts -------------------------------------------------------------------------------------------
    texts = {}
    for fp in board.GetFootprints():
        r = fp.Reference()
        if r.IsVisible() and r.GetLayer() == m.SILK:
            texts[fp.GetReference()] = (r, fp)
    for d in board.GetDrawings():
        if d.GetLayer() == m.SILK and hasattr(d, 'GetText'):
            texts['text:' + d.GetText()] = (d, d)
    live = {name: m.text_item(t, name, 'text') for name, (t, _o) in texts.items()}

    def conflicts(name, it):
        n = 0
        for o in pads:
            n += m.collides(it, o)
        for o in graphics:
            n += m.collides(it, o)
        for other, o in live.items():
            if other != name:
                n += m.collides(it, o)
        return n + (1 if m.outside_edge(it.box) else 0)

    order = sorted(texts, key=lambda k: -conflicts(k, live[k]))
    moved, shrunk, hidden = [], [], []
    for name in order:
        text, owner = texts[name]
        if conflicts(name, live[name]) == 0:
            continue
        orig = (text.GetPosition().x, text.GetPosition().y, text.GetTextAngleDegrees(), text.GetTextWidth())
        A = anchor_box(owner)
        found = None
        for size in SIZES:
            for angle in (0.0, 90.0):
                set_text(text, size, angle)
                place(text, *centre_of(live[name]))      # measure the size once at the old centre
                shape = m.text_item(text, name, 'text')
                hw, hh = (shape.box[2] - shape.box[0]) / 2, (shape.box[3] - shape.box[1]) / 2
                cands = []
                ng = int(MAX_GAP / STEP_GAP)
                for gi in range(ng + 1):
                    gap = MM(gi * STEP_GAP)
                    for side in range(4):
                        if side < 2:                        # above / below
                            cy = A[1] - gap - hh if side == 0 else A[3] + gap + hh
                            lo, hi = A[0] - hw, A[2] + hw
                            slide = [(x, cy) for x in range(int(lo), int(hi) + 1, MM(STEP_SLIDE))]
                        else:                               # left / right
                            cx = A[0] - gap - hw if side == 2 else A[2] + gap + hw
                            lo, hi = A[1] - hh, A[3] + hh
                            slide = [(cx, y) for y in range(int(lo), int(hi) + 1, MM(STEP_SLIDE))]
                        mid = ((A[0] + A[2]) / 2, (A[1] + A[3]) / 2)
                        for x, y in slide:
                            cands.append((gi * STEP_GAP + 0.01 * math.hypot(x - mid[0], y - mid[1]) / 1e6, x, y))
                cands.sort()
                for _score, x, y in cands:
                    place(text, x, y)
                    it = m.text_item(text, name, 'text')
                    if conflicts(name, it) == 0:
                        found = (size, angle, x, y, it)
                        break
                if found:
                    break
            if found:
                break
        if found:
            size, angle, x, y, it = found
            place(text, x, y)
            live[name] = m.text_item(text, name, 'text')
            moved.append(name)
            if size < 1.0:
                shrunk.append(name)
        else:
            set_text(text, 1.0, orig[2])
            place(text, orig[0], orig[1])
            if hasattr(text, 'SetVisible') and name in texts and hasattr(owner, 'Pads'):
                text.SetVisible(False)
                del live[name]
                hidden.append(name)
            else:
                live[name] = m.text_item(text, name, 'text')
                hidden.append(name + ' (label left in place)')
    left = [k for k in live if conflicts(k, live[k])]
    if verbose:
        print('removed silk lines:', len(removed), sorted({r[0] for r in removed}))
        print('moved texts:', len(moved), '| shrunk to 0.8 mm:', shrunk, '| hidden:', hidden)
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
