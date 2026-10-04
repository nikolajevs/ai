"""Silkscreen geometry helpers shared by fix_silk.py and the silk checks (KiCad Python).

Items are SHAPEs in board nanometres; the clearances mirror the project's DRC (silk to silk 0.15 mm, silk to the
solder-mask opening of a pad, silk to the board edge 0.15 mm) with a small reserve.
"""
import pcbnew as p

MM = p.FromMM
SILK = p.F_SilkS
EDGE_MARGIN = 0.45          # mm from the outline for text (DRC wants 0.15 mm)
SILK_CLEAR = 0.22           # mm between silk items (DRC 0.15 mm)
PAD_CLEAR = 0.12            # mm between silk and a pad (mask opening)
HOLE_CLEAR = 0.2            # mm between silk and a drilled hole or via (JLCDFM 0.15 mm)
GRAVEYARD = []              # removed items stay referenced: destroying their Python proxies breaks later pcbnew calls


def box_of(shape, clearance_mm=0.0):
    b = shape.BBox(MM(clearance_mm))
    return (b.GetLeft(), b.GetTop(), b.GetRight(), b.GetBottom())


def boxes_touch(a, b):
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def refresh(text):
    for name in ('ClearBoundingBoxCache', 'ClearRenderCache'):
        if hasattr(text, name):
            getattr(text, name)()


class Item:
    """one obstacle: shape, bounding box, the clearance it demands, the owner reference and a label"""
    __slots__ = ('shape', 'box', 'clear', 'owner', 'kind')

    def __init__(self, shape, clear_mm, owner, kind):
        self.shape = shape
        self.clear = MM(clear_mm)
        self.box = box_of(shape, clear_mm)
        self.owner = owner
        self.kind = kind


def silk_graphics(fp):
    return [g for g in fp.GraphicalItems() if g.GetLayer() == SILK and not hasattr(g, 'GetText')]


def pad_items(board):
    """pads (mask openings) and every drilled hole including vias: JLCDFM wants silk 0.15 mm off holes too"""
    items = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.IsOnLayer(p.F_Cu) or pad.GetDrillSizeX() > 0:
                items.append(Item(pad.GetEffectiveShape(p.F_Cu), PAD_CLEAR, fp.GetReference(), 'pad'))
    for t in board.GetTracks():
        if isinstance(t, p.PCB_VIA):
            items.append(Item(p.SHAPE_CIRCLE(t.GetPosition(), t.GetDrillValue() // 2), HOLE_CLEAR, '', 'via'))
    return items


def graphic_items(board, skip=()):
    items = []
    for fp in board.GetFootprints():
        for g in silk_graphics(fp):
            if g in skip:
                continue
            items.append(Item(g.GetEffectiveShape(), SILK_CLEAR, fp.GetReference(), 'line'))
    for d in board.GetDrawings():
        if d.GetLayer() == SILK and not hasattr(d, 'GetText'):
            items.append(Item(d.GetEffectiveShape(), SILK_CLEAR, '', 'line'))
    return items


def text_item(text, owner, kind):
    # DRC treats a text by (a box around) its glyphs, wider than the strokes: use the bounding box
    b = text.GetBoundingBox()
    return Item(p.SHAPE_RECT(b.GetLeft(), b.GetTop(), b.GetWidth(), b.GetHeight()), SILK_CLEAR, owner, kind)


def collides(shape_item, obstacle, extra_clear=0):
    if not boxes_touch(shape_item.box, obstacle.box):
        return False
    return shape_item.shape.Collide(obstacle.shape, max(shape_item.clear, obstacle.clear) + extra_clear)


def outside_edge(box, lo=50.0, hi=150.0, margin=EDGE_MARGIN):
    return (box[0] < MM(lo + margin) or box[1] < MM(lo + margin) or box[2] > MM(hi - margin) or box[3] > MM(hi - margin))
