"""Silkscreen geometry helpers shared by fix_silk.py (KiCad Python).

Everything is a set of SHAPE parts in board nanometres: a text is the list of its glyph strokes (SHAPE_SEGMENT with the
pen width, from GetEffectiveTextShape), a silk line is its segments/arcs, a pad is its outline, a via is its drill.
DRC compares silk by these strokes (a text is NOT judged by its bounding box: two texts 0.3 mm apart stroke to stroke pass
although their boxes overlap), so the model does the same. The clearances mirror the project's DRC (silk to silk 0.15 mm,
silk to a hole 0.15 mm in JLCDFM) with a small reserve.
"""
import pcbnew as p

MM = p.FromMM
SILK_CLEAR = 0.18           # mm between silk items (DRC 0.15 mm)
PAD_CLEAR = 0.17            # mm between silk and a pad (mask opening; JLCDFM 0.15 mm)
HOLE_CLEAR = 0.2            # mm between silk and a drilled hole or via (JLCDFM 0.15 mm)
EDGE_MARGIN = 0.45          # mm from the outline for text (DRC wants 0.15 mm)
GRAVEYARD = []              # removed items stay referenced: destroying their Python proxies breaks later pcbnew calls


def silk_layer(flipped):
    return p.B_SilkS if flipped else p.F_SilkS


def parts(shape):
    """the simple shapes of a (possibly compound) SHAPE"""
    if hasattr(shape, 'GetSubshapes'):
        out = []
        for s in shape.GetSubshapes():
            out += parts(s)
        return out
    return [shape]


def box_of(shapes, clearance_mm=0.0):
    boxes = [s.BBox(MM(clearance_mm)) for s in shapes]
    return (min(b.GetLeft() for b in boxes), min(b.GetTop() for b in boxes),
            max(b.GetRight() for b in boxes), max(b.GetBottom() for b in boxes))


def boxes_touch(a, b):
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def refresh(text):
    for name in ('ClearBoundingBoxCache', 'ClearRenderCache'):
        if hasattr(text, name):
            getattr(text, name)()


class Item:
    """one obstacle or text: its simple shapes, bounding box, the clearance it demands, owner reference and kind"""
    __slots__ = ('parent', 'shapes', 'box', 'clear', 'owner', 'kind')

    def __init__(self, shape, clear_mm, owner, kind):
        self.parent = shape          # the sub-shapes are owned by it: keep it alive or Collide crashes
        self.shapes = parts(shape)
        self.clear = MM(clear_mm)
        self.box = box_of(self.shapes, clear_mm)
        self.owner = owner
        self.kind = kind


def pad_items(board, flipped=False):
    """pads (mask openings) and every drilled hole including vias: JLCDFM wants silk 0.15 mm off holes too"""
    layer = p.B_Cu if flipped else p.F_Cu
    items = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.IsOnLayer(layer) or pad.GetDrillSizeX() > 0:
                items.append(Item(pad.GetEffectiveShape(layer), PAD_CLEAR, fp.GetReference(), 'pad'))
    for t in board.GetTracks():
        if isinstance(t, p.PCB_VIA):
            items.append(Item(p.SHAPE_CIRCLE(t.GetPosition(), t.GetDrillValue() // 2), HOLE_CLEAR, '', 'via'))
    return items


def graphic_items(board, flipped=False, skip=()):
    layer = silk_layer(flipped)
    items = []
    for fp in board.GetFootprints():
        for g in fp.GraphicalItems():
            if g.GetLayer() == layer and not hasattr(g, 'GetText') and g not in skip:
                items.append(Item(g.GetEffectiveShape(), SILK_CLEAR, fp.GetReference(), 'line'))
    for d in board.GetDrawings():
        if d.GetLayer() == layer and not hasattr(d, 'GetText'):
            items.append(Item(d.GetEffectiveShape(), SILK_CLEAR, '', 'line'))
    return items


def silk_graphics(fp):
    layer = silk_layer(fp.IsFlipped())
    return [g for g in fp.GraphicalItems() if g.GetLayer() == layer and not hasattr(g, 'GetText')]


def text_item(text, owner, kind):
    return Item(text.GetEffectiveTextShape(), SILK_CLEAR, owner, kind)


def collides(a, b, extra_clear=0):
    """True when some part of `a` comes closer than the larger of the two clearances to some part of `b`"""
    if not boxes_touch(a.box, b.box):
        return False
    clearance = max(a.clear, b.clear) + extra_clear
    for sa in a.shapes:
        for sb in b.shapes:
            if p.SHAPE.Collide(sa, sb, clearance):
                return True
    return False


def outside_edge(box, lo=50.0, hi=150.0, margin=EDGE_MARGIN):
    return (box[0] < MM(lo + margin) or box[1] < MM(lo + margin) or box[2] > MM(hi - margin) or box[3] > MM(hi - margin))
