"""Assembly document of cheap-1 for the operator (Russian PDF): make_assembly_doc.py assembly.json out.pdf

1. "C:/Program Files/KiCad/10.0/bin/python.exe" tools/export_assembly.py assembly.json      (KiCad Python, board dump)
2. python tools/make_assembly_doc.py assembly.json assembly/Assembly_cheap1.pdf             (Python with Pillow, PyMuPDF)

Pages: title and the rules that matter, polarity summary, kit list, one page per assembly step (overview of the board,
parts by value, instructions), the 16 board tiles (25 x 25 mm: every reference with its value, pads coloured by step,
polarity badges), polarity and orientation cards per part type, final checks.
"""
import io
import json
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw

import asm_data as ad
import asm_draw as dr
import asm_text as at

HERE = Path(__file__).resolve().parents[1]
TILE = 25.0
OVERLAP = 1.0
TILE_PX_PER_MM = 60.0
FONTS = Path(tempfile.gettempdir()) / 'cheap1_asm_fonts'      # Arial copied from Windows, not stored in the repository
A4 = (595, 842)
M = 36


# ------------------------------------------------------------------------------------------------- data
def load(path):
    data = json.load(open(path, encoding='utf-8'))
    bom = ad.load_bom()
    for fp in data['fps']:
        fp['step'] = ad.step_of(fp)
        info = bom.get(fp['ref'], {})
        fp['bom_value'] = info.get('value', fp['value'])
        mpn = info.get('mpn', '')
        # BOM_cheap1.csv falls back to the PCB_V1 part number for stock parts without one (a 0603 MPN on a 0805 or 1206 part):
        # such a number would mislead the operator, so it is not shown
        if re.search(r'0603', mpn) and ad.package(fp) in ('0805', '1206'):
            mpn = ''
        fp['mpn'] = mpn
        fp['source'] = info.get('source', '')
        fp['pkg'] = ad.package(fp)
        bb = dr.pads_bbox(fp)
        fp['cx'], fp['cy'] = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
    return data


def tiles():
    out = []
    for r in range(4):
        for c in range(4):
            region = (max(50.0, 50 + c * TILE - OVERLAP), max(50.0, 50 + r * TILE - OVERLAP),
                      min(150.0, 50 + (c + 1) * TILE + OVERLAP), min(150.0, 50 + (r + 1) * TILE + OVERLAP))
            core = (50 + c * TILE, 50 + r * TILE, 50 + (c + 1) * TILE, 50 + (r + 1) * TILE)
            out.append((f'{"ABCD"[c]}{r + 1}', region, core))
    return out


def tile_of(fp):
    for name, _region, core in tiles():
        if core[0] <= fp['cx'] < core[2] + (0.01 if core[2] >= 150 else 0) and core[1] <= fp['cy'] < core[3] + (0.01 if core[3] >= 150 else 0):
            return name
    return '?'


# ------------------------------------------------------------------------------------------------- drawing
def render_view(data, region, scale, mirror=False, only_steps=None, highlight=None, labels=True, polarity=True, f1_px=26,
                f2_px=20, badge_px=24, grid=False, faint_others=True, ring=False, ghost=False):
    """Board region as an image. only_steps / highlight select the parts drawn in colour (the others are faint)."""
    view = dr.View(region, scale, mirror)
    img = Image.new('RGB', (view.w, view.h), (255, 255, 255))
    d = ImageDraw.Draw(img, 'RGBA')
    side = 'B' if mirror else 'F'

    def active(fp):
        if fp['step'] is None:
            return False
        if only_steps is not None and fp['step'] not in only_steps:
            return False
        if highlight is not None and fp['ref'] not in highlight:
            return False
        return True

    items = [fp for fp in data['fps'] if view.inside(dr.fp_bbox(fp), 1.0) and (fp['side'] == side or fp['kind'] == 'THT')]
    selective = only_steps is not None or highlight is not None
    if ghost:                           # the other side of the board, faint, so the operator sees what is on top of the part
        for fp in data['fps']:
            if fp['side'] != side and fp['kind'] == 'SMD' and fp['step'] and view.inside(dr.fp_bbox(fp), 1.0):
                dr.draw_fp(d, view, fp, faint=True)
                b = dr.pads_bbox(fp)
                (u0, v0), (u1, v1) = view.px(b[0], b[1]), view.px(b[2], b[3])
                d.text(((u0 + u1) / 2 - 40, min(v0, v1) - 4), fp['ref'] + ' (сверху)', font=dr.font(f1_px * 0.8, True), fill=(130, 130, 130))
    obstacles = []
    for fp in sorted(items, key=lambda f: 0 if not active(f) else 1):
        on = active(fp)
        dr.draw_fp(d, view, fp, faint=(selective and not on and faint_others and fp['step'] is not None) or (fp['step'] is None and True),
                   step_color=dr.STEP_COLORS.get(fp['step']) if (on or not selective) and fp['step'] else None)
        if fp['step'] is not None:
            for pad in fp['pads']:
                b = dr.poly_bbox(pad['poly'])
                if b:
                    (u0, v0), (u1, v1) = view.px(b[0], b[1]), view.px(b[2], b[3])
                    obstacles.append((min(u0, u1), min(v0, v1), max(u0, u1), max(v0, v1)))
    # parts on the other side seen through the board: dashed rectangle
    for fp in data['fps']:
        if fp['kind'] == 'SMD' and fp['side'] != side and fp['step'] and active(fp) and view.inside(dr.fp_bbox(fp), 1.0):
            b = dr.pads_bbox(fp)
            (u0, v0), (u1, v1) = view.px(b[0] - 0.4, b[1] - 0.4), view.px(b[2] + 0.4, b[3] + 0.4)
            d.rectangle([min(u0, u1), min(v0, v1), max(u0, u1), max(v0, v1)], outline=dr.STEP_COLORS[fp['step']], width=4)
            items.append(fp)
    badges = []
    if polarity:
        for fp in items:
            spec = ad.POLARITY.get(fp['ref'])
            if not spec or not active(fp):
                continue
            for number, text in spec:
                pos = dr.marker_position(fp, number, size_mm=badge_px / 2 / scale)
                if pos and view.x0 - 1 <= pos[0] <= view.x1 + 1 and view.y0 - 1 <= pos[1] <= view.y1 + 1:
                    badges.append((pos, text))
    if ring:
        for fp in items:
            if active(fp):
                b = dr.pads_bbox(fp)
                (u0, v0), (u1, v1) = view.px(b[0], b[1]), view.px(b[2], b[3])
                cx, cy = (u0 + u1) / 2, (v0 + v1) / 2
                r = max(abs(u1 - u0), abs(v1 - v0)) / 2 + 0.9 * scale
                d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=dr.STEP_COLORS[fp['step']] + (255,), width=3)
    lab = dr.Labeler(view, obstacles)
    for (x, y), _t in badges:
        u, v = view.px(x, y)
        r = badge_px / 2
        lab.boxes.append((u - r, v - r, u + r, v + r))
    if labels:
        f1, f2 = dr.font(f1_px, True), dr.font(f2_px)
        order = sorted((f for f in items if active(f)),
                       key=lambda f: -((dr.pads_bbox(f)[2] - dr.pads_bbox(f)[0]) * (dr.pads_bbox(f)[3] - dr.pads_bbox(f)[1])))
        for fp in order:
            if not (view.x0 <= fp['cx'] <= view.x1 and view.y0 <= fp['cy'] <= view.y1):
                continue
            tag = fp['ref'] + (' (снизу)' if fp['side'] != side else '')
            lab.place(d, dr.pads_bbox(fp), [tag, ad.short_value(fp['bom_value'])], dr.STEP_COLORS[fp['step']], [f1, f2])
    for (x, y), text in badges:
        dr.badge(d, view, x, y, text, r_mm=badge_px / 2 / scale)
    if grid:
        gf = dr.font(max(20, scale * 2.2), True)
        for name, _region, core in tiles():
            (u0, v0), (u1, v1) = view.px(core[0], core[1]), view.px(core[2], core[3])
            x0, x1 = sorted((u0, u1))
            d.rectangle([x0, v0, x1, v1], outline=(120, 120, 120, 200), width=2)
            d.text((x0 + 6, v0 + 4), name, font=gf, fill=(120, 120, 120, 255))
    return img


def jpeg_bytes(img, quality=88):
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=quality, optimize=True)
    return buf.getvalue()


def card_region(data, refs, aspect=1.45, margin=2.2, min_w=11.0):
    boxes = []
    for fp in data['fps']:
        if fp['ref'] in refs:
            boxes.append(dr.fp_bbox(fp))
    x0, y0 = min(b[0] for b in boxes) - margin, min(b[1] for b in boxes) - margin
    x1, y1 = max(b[2] for b in boxes) + margin, max(b[3] for b in boxes) + margin
    w, h = x1 - x0, y1 - y0
    w = max(w, h * aspect, min_w)
    h = w / aspect
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    cx = min(max(cx, 50 + w / 2), 150 - w / 2)
    cy = min(max(cy, 50 + h / 2), 150 - h / 2)
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


# ------------------------------------------------------------------------------------------------- PDF
CSS = """
@font-face { font-family: 'AR'; src: url(arial.ttf); }
@font-face { font-family: 'AR'; font-weight: bold; src: url(arialbd.ttf); }
@font-face { font-family: 'AR'; font-style: italic; src: url(ariali.ttf); }
body { font-family: 'AR'; font-size: 9pt; line-height: 1.25; color: #111; }
h1 { font-size: 17pt; margin: 0 0 4pt 0; }
h2 { font-size: 12pt; margin: 6pt 0 3pt 0; }
p { margin: 2pt 0 3pt 0; }
table { border-collapse: collapse; width: 100%; }
th { background: #e8e8e8; text-align: left; font-size: 8pt; border: 0.5pt solid #666; padding: 2pt 3pt; }
td { border: 0.5pt solid #888; padding: 2pt 3pt; font-size: 8.5pt; vertical-align: top; }
.warn { background: #fff0c8; border: 1pt solid #c80; padding: 3pt; }
.bad { background: #ffe0e0; border: 1pt solid #c00; padding: 3pt; }
.small { font-size: 7.5pt; color: #333; }
.sw { font-weight: bold; }
"""


class Doc:
    def __init__(self):
        self.doc = pymupdf.open()
        self.fonts = pymupdf.Archive(str(FONTS))
        self.n = 0

    def page(self):
        self.n += 1
        return self.doc.new_page(width=A4[0], height=A4[1])

    def html(self, page, rect, html):
        spare, scale = page.insert_htmlbox(pymupdf.Rect(*rect), html, css=CSS, archive=self.fonts)
        if spare < 0 or scale < 0.97:
            print(f'  WARNING page {self.n}: text does not fit at full size (scale {scale:.2f}, spare {spare:.0f})')
        return spare

    def footer(self, page, text):
        page.insert_htmlbox(pymupdf.Rect(M, A4[1] - 28, A4[0] - M, A4[1] - 10),
                            f'<p class="small">{text} — стр. {self.n}</p>', css=CSS, archive=self.fonts)

    def image(self, page, rect, img, quality=88):
        page.insert_image(pymupdf.Rect(*rect), stream=jpeg_bytes(img, quality))


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def group_parts(data, steps):
    """rows for the parts tables: (value, package, mpn, source, [refs]) grouped, sorted by refs"""
    groups = defaultdict(list)
    for fp in data['fps']:
        if fp['step'] in steps:
            groups[(ad.short_value(fp['bom_value']), fp['pkg'], fp['mpn'], fp['source'])].append(fp)
    rows = []
    for (value, pkg, mpn, source), fps in groups.items():
        fps.sort(key=lambda f: (f['ref'][0], int(''.join(c for c in f['ref'] if c.isdigit()) or 0)))
        rows.append((value, pkg, mpn, source, fps))
    rows.sort(key=lambda r: (r[4][0]['ref'][0], r[1], r[0]))
    return rows


def source_text(source):
    if source.startswith('stock:'):
        return 'склад (№ ' + source.split(':')[1] + ')'
    return 'докупка'


def parts_table(rows, with_tiles=True):
    out = ['<table><tr><th>Позиции</th><th>Шт.</th><th>Номинал</th><th>Корпус</th><th>MPN</th><th>Откуда</th>'
           + ('<th>Плоскости</th>' if with_tiles else '') + '</tr>']
    for value, pkg, mpn, source, fps in rows:
        refs = ' '.join(f['ref'] for f in fps)
        tl = ' '.join(sorted({tile_of(f) for f in fps}))
        out.append(f'<tr><td><b>{refs}</b></td><td>{len(fps)}</td><td>{value}</td><td>{at.pkg_name(pkg)}</td>'
                   f'<td>{mpn}</td><td>{source_text(source)}</td>' + (f'<td>{tl}</td>' if with_tiles else '') + '</tr>')
    out.append('</table>')
    return ''.join(out)


def build(data, out_path):
    doc = Doc()
    steps_present = sorted({fp['step'] for fp in data['fps'] if fp['step']})
    total = {k: sum(1 for fp in data['fps'] if fp['step'] == k) for k in steps_present}
    overview = render_view(data, (50, 50, 150, 150), 12, labels=False, polarity=False, grid=True)
    # ------------------------------------------------------------------ title
    pg = doc.page()
    doc.html(pg, (M, M, A4[0] - M, 250), at.title_html(data, total))
    doc.image(pg, (M, 262, M + 330, 262 + 330), overview)
    doc.html(pg, (M + 340, 262, A4[0] - M, 600), at.legend_html(total))
    doc.html(pg, (M, 610, A4[0] - M, A4[1] - 36), at.rules_html())
    doc.footer(pg, 'GrowBox cheap-1 — сборка')
    # ------------------------------------------------------------------ polarity summary
    pg = doc.page()
    doc.html(pg, (M, M, A4[0] - M, A4[1] - 36), at.critical_html(data))
    doc.footer(pg, 'GrowBox cheap-1 — главное о полярности и ориентации')
    # ------------------------------------------------------------------ steps
    for step in steps_present:
        rows = group_parts(data, {step})
        mirror = step in (1, 10)
        img = render_view(data, (50, 50, 150, 150), 12, mirror=mirror, only_steps={step}, labels=False, polarity=True,
                          f1_px=26, badge_px=16, grid=not mirror, ring=True)
        pg = doc.page()
        doc.html(pg, (M, M, A4[0] - M, 150), at.step_head_html(step, total[step], mirror))
        doc.image(pg, (M, 150, M + 300, 450), img)
        if step in (1, 10):
            refs = {fp['ref'] for fp in data['fps'] if fp['step'] == step}
            region = card_region(data, refs, aspect=1.2, margin=3.0, min_w=14.0)
            zoom = render_view(data, region, 1000 / (region[2] - region[0]), mirror=True, only_steps={step}, f1_px=34, f2_px=26, badge_px=34, ghost=True)
            doc.image(pg, (M + 310, 150, A4[0] - M, 150 + (A4[0] - M - M - 310) * zoom.size[1] / zoom.size[0]), zoom, quality=88)
            doc.html(pg, (M + 310, 300, A4[0] - M, 450), at.step_notes_html(step))
        else:
            doc.html(pg, (M + 310, 150, A4[0] - M, 450), at.step_notes_html(step))
        sizes = len(rows)
        if sizes <= 14:
            doc.html(pg, (M, 458, A4[0] - M, A4[1] - 36), parts_table(rows))
        else:
            first, rest = rows[:14], rows[14:]
            doc.html(pg, (M, 458, A4[0] - M, A4[1] - 36), parts_table(first))
            doc.footer(pg, f'Шаг {step}')
            for chunk in chunks(rest, 30):
                pg = doc.page()
                doc.html(pg, (M, M, A4[0] - M, A4[1] - 36), f'<h2>Шаг {step} (продолжение)</h2>' + parts_table(chunk))
                doc.footer(pg, f'Шаг {step}')
            continue
        doc.footer(pg, f'Шаг {step}')
    # ------------------------------------------------------------------ tiles
    for name, region, core in tiles():
        scale = TILE_PX_PER_MM
        img = render_view(data, region, scale, f1_px=27, f2_px=21, badge_px=26)
        pg = doc.page()
        x0, y0 = core[0] - 50, core[1] - 50
        doc.html(pg, (M, M, A4[0] - M - 80, 94),
                 f'<h1>Плоскость {name}</h1><p>x {x0:.0f}–{x0 + TILE:.0f} мм, y {y0:.0f}–{y0 + TILE:.0f} мм от левого верхнего угла платы. '
                 f'Цвет площадок и рамки подписи — шаг. Красный кружок: K — катод, + — плюс, 1 — вывод 1, G/S/D — затвор/исток/сток.</p>')
        iw = A4[0] - 2 * M
        ih = iw * img.size[1] / img.size[0]
        doc.image(pg, (M, 82, M + iw, 96 + ih), img, quality=86)
        mini = render_view(data, (50, 50, 150, 150), 3, labels=False, polarity=False)
        d = ImageDraw.Draw(mini)
        u0, v0, u1, v1 = (core[0] - 50) * 3, (core[1] - 50) * 3, (core[2] - 50) * 3, (core[3] - 50) * 3
        d.rectangle([u0, v0, u1, v1], outline=(220, 0, 0), width=4)
        doc.image(pg, (A4[0] - M - 70, M, A4[0] - M, M + 70), mini)
        refs = sorted([fp for fp in data['fps'] if fp['step'] and tile_of(fp) == name],
                      key=lambda f: (f['ref'][0], int(''.join(c for c in f['ref'] if c.isdigit()) or 0)))
        if 96 + ih + 10 < A4[1] - 60:
            cells = ''.join(f'<td><b>{f["ref"]}</b> {ad.short_value(f["bom_value"])}</td>' for f in refs)
            rowsh = ''.join('<tr>' + ''.join(f'<td><b>{f["ref"]}</b> {ad.short_value(f["bom_value"])} <span class="small">шаг {f["step"]}</span></td>' for f in chunk)
                            + '</tr>' for chunk in chunks(refs, 4))
            doc.html(pg, (M, 96 + ih + 6, A4[0] - M, A4[1] - 34), f'<table>{rowsh}</table>')
        doc.footer(pg, f'Плоскость {name}')
    # ------------------------------------------------------------------ polarity cards
    cards = at.cards(data)
    import re as _re
    cw = (A4[0] - 2 * M - 10) / 2
    img_h = cw / 1.5

    def text_h(card):
        plain = _re.sub(r'<[^>]+>', '', card['html'])
        return 10.5 * (len(plain) / 58 + 1.2) + 12 * card['html'].count('<tr>') + 6

    rows, pairs = [], list(chunks(cards, 2))
    pages, cur, used = [], [], 0.0
    for pair in pairs:
        h = img_h + max(text_h(c) for c in pair) + 6
        if used + h > A4[1] - 100 and cur:
            pages.append(cur)
            cur, used = [], 0.0
        cur.append((pair, h))
        used += h
    if cur:
        pages.append(cur)
    for page_rows in pages:
        pg = doc.page()
        doc.html(pg, (M, M, A4[0] - M, 60), '<h1>Полярность и ориентация</h1>')
        y = 62
        for pair, h in page_rows:
            for col, card in enumerate(pair):
                x = M + col * (cw + 10)
                refs = set(card['refs'])
                region = card_region(data, set(card['crop'] or card['refs'][:1]), aspect=1.5)
                width_px = 1100
                scale = width_px / (region[2] - region[0])
                px_per_pt = width_px / cw
                img = render_view(data, region, scale, highlight=refs, f1_px=8.5 * px_per_pt, f2_px=7 * px_per_pt,
                                  badge_px=9 * px_per_pt, faint_others=True)
                doc.image(pg, (x, y, x + cw, y + img_h), img, quality=86)
                doc.html(pg, (x, y + img_h + 1, x + cw, y + h - 2), card['html'])
            y += h
        doc.footer(pg, 'Полярность и ориентация')
    # ------------------------------------------------------------------ final checks
    pg = doc.page()
    doc.html(pg, (M, M, A4[0] - M, A4[1] - 36), at.final_html())
    doc.footer(pg, 'Контроль после сборки')
    doc.doc.subset_fonts()
    doc.doc.save(out_path, garbage=4, deflate=True, deflate_fonts=True)
    print('saved', out_path, doc.n, 'pages')


if __name__ == '__main__':
    FONTS.mkdir(exist_ok=True)
    for name in ('arial.ttf', 'arialbd.ttf', 'ariali.ttf'):
        if not (FONTS / name).exists():
            (FONTS / name).write_bytes((dr.FONT_DIR / name).read_bytes())
    d = load(sys.argv[1])
    if '--tile' in sys.argv:
        name = sys.argv[sys.argv.index('--tile') + 1]
        for n, region, core in tiles():
            if n == name:
                render_view(d, region, TILE_PX_PER_MM, f1_px=27, f2_px=21, badge_px=26).save(sys.argv[sys.argv.index('--tile') + 2], quality=90)
    else:
        build(d, sys.argv[2])
