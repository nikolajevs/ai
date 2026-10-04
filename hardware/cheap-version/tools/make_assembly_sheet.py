"""Short assembly sheets of cheap-1 for the operator (A4 portrait, Russian PDF):

  python tools/make_assembly_sheet.py assembly.json assembly/Assembly_cheap1_A4.pdf [--a3 assembly/Assembly_cheap1_SMD_A3.pdf] [--png out_dir]

assembly.json comes from tools/export_assembly.py (KiCad Python). The A4 file has 4 pages:
  1  SMD parts: one picture of the top side with every reference, its value where it fits and the polarity marks
     (green = no polarity, orange = polar), inset of the bottom side
  2  SMD parts: one table, reference designators next to the MPN (one line per part type)
  3  through-hole parts: the same picture (+ inset of the bottom side with BT301)
  4  through-hole parts: the table
--a3 also writes page 1 as a separate one-page A3 file: the same picture 1.41 times larger, the values next to 140 of 141
references (on A4: 110). The long step-by-step document is make_assembly_doc.py; both use the same board dump and the same BOM.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw

import asm_data as ad
import asm_draw as dr
import asm_text as at
import make_assembly_doc as mad

A4 = (595, 842)
A3 = (842, 1191)
M = 18
REG = (46.0, 46.0, 154.0, 154.0)         # the board plus a 4 mm margin for the zone letters
BOARD = (49.975, 49.975, 150.025, 150.025)
LABEL_PT, VALUE_PT = 6.8, 5.6
GREEN, ORANGE = dr.STEP_COLORS[5], dr.STEP_COLORS[3]      # SMD picture: no polarity / has a polarity or a pin 1


def polar_color(fp):
    """orange = a part that goes in one way only (it has a red mark on the picture), green = no polarity"""
    return ORANGE if fp['ref'] in ad.POLARITY else GREEN

CSS = """
@font-face { font-family: 'AR'; src: url(arial.ttf); }
@font-face { font-family: 'AR'; font-weight: bold; src: url(arialbd.ttf); }
@font-face { font-family: 'AR'; font-style: italic; src: url(ariali.ttf); }
body { font-family: 'AR'; font-size: 8pt; line-height: 1.2; color: #111; }
h1 { font-size: 13pt; margin: 0 0 2pt 0; }
h2 { font-size: 9pt; margin: 2pt 0 2pt 0; }
p { margin: 1pt 0 2pt 0; }
table { border-collapse: collapse; width: 100%; }
th { background: #e4e4e4; text-align: left; font-size: 7pt; border: 0.5pt solid #555; padding: 1.5pt 2pt; }
td { border: 0.5pt solid #888; padding: 0.7pt 2pt; font-size: 7pt; vertical-align: top; }
.small { font-size: 7pt; color: #333; }
.sw { font-weight: bold; text-align: center; color: #fff; }
.k { font-weight: bold; color: #c80000; text-align: center; }
"""


def scaled_css(k):
    """the same style with every size multiplied by k (legends of the A3 page)"""
    return re.sub(r'(\d+(?:\.\d+)?)pt', lambda m: f'{float(m.group(1)) * k:.2f}pt', CSS)


# ------------------------------------------------------------------------------------------------- picture
def render_sheet(data, mirror, active, width_pt, scale, values=False, badge_mm=0.85, label_pt=LABEL_PT, value_pt=VALUE_PT,
                 dnp_labels=True, color_of=None, value_gaps=6):
    """Board (parts only) as an image: parts selected by active() in colour with reference labels and polarity badges,
    the others faint. width_pt is the width the image will have on the page, to size text in points.
    values: False = reference only, True = reference and value, 'fit' = the value only where it fits within value_gaps
    distance steps of the part (6 = next to it, 10 = up to about 6 mm away, with a leader line).
    color_of(fp) = colour of a part (default: the colour of its assembly step)."""
    color_of = color_of or (lambda fp: dr.STEP_COLORS[fp['step']])
    view = dr.View(REG, scale, mirror)
    ppt = view.w / width_pt
    img = Image.new('RGB', (view.w, view.h), (255, 255, 255))
    d = ImageDraw.Draw(img, 'RGBA')
    (u0, v0), (u1, v1) = view.px(BOARD[0], BOARD[1]), view.px(BOARD[2], BOARD[3])
    d.rectangle([min(u0, u1), min(v0, v1), max(u0, u1), max(v0, v1)], fill=(236, 244, 236), outline=(50, 70, 50), width=max(2, int(1.1 * ppt)))
    # zone grid 25 x 25 mm
    for k in range(5):
        x = 50 + 25 * k
        (ua, va), (ub, vb) = view.px(x, 50), view.px(x, 150)
        d.line([(ua, va), (ub, vb)], fill=(176, 196, 176, 255), width=max(1, int(0.5 * ppt)))
        (ua, va), (ub, vb) = view.px(50, x), view.px(150, x)
        d.line([(ua, va), (ub, vb)], fill=(176, 196, 176, 255), width=max(1, int(0.5 * ppt)))
    band = (BOARD[0] - REG[0]) * scale                    # the margin around the board, in pixels
    f_zone = dr.font(min(8 * ppt, 0.7 * band), True)
    zone_color = (90, 120, 90)

    def centred(text, cx, cy):
        bb = d.textbbox((0, 0), text, font=f_zone)
        d.text((cx - (bb[0] + bb[2]) / 2, cy - (bb[1] + bb[3]) / 2), text, font=f_zone, fill=zone_color)
    for name, _region, core in mad.tiles():
        (ua, va), (ub, vb) = view.px(core[0], core[1]), view.px(core[2], core[3])
        cu, cv = (ua + ub) / 2, (va + vb) / 2
        col, row = name[0], name[1]
        if row == '1':
            centred(col, cu, band / 2)
        if row == '4':
            centred(col, cu, view.h - band / 2)
        if min(ua, ub) < view.w * 0.3:
            centred(row, band / 2, cv)
        if min(ua, ub) > view.w * 0.6:
            centred(row, view.w - band / 2, cv)
    side = 'B' if mirror else 'F'
    items = [fp for fp in data['fps'] if fp['side'] == side or fp['kind'] == 'THT']
    act = [fp for fp in items if active(fp)]
    for fp in items:
        if not active(fp):
            dr.draw_fp(d, view, fp, faint=True)
    obstacles = []
    for fp in items:
        if active(fp):
            dr.draw_fp(d, view, fp, step_color=color_of(fp))
        for pad in fp['pads']:
            b = dr.poly_bbox(pad['poly'])
            if b:
                (ua, va), (ub, vb) = view.px(b[0], b[1]), view.px(b[2], b[3])
                obstacles.append((min(ua, ub), min(va, vb), max(ua, ub), max(va, vb)))
    badges = []
    for fp in act:
        for number, text in ad.POLARITY.get(fp['ref'], []):
            pos = dr.marker_position(fp, number, size_mm=badge_mm)
            if pos:
                badges.append((pos, text))
    lab = dr.Labeler(view, obstacles)
    lab.gaps = tuple(int(g * ppt) for g in (0.6, 1.5, 2.5, 4, 6, 8, 11, 14, 18, 24))
    for (x, y), _t in badges:
        u, v = view.px(x, y)
        r = badge_mm * view.s
        lab.boxes.append((u - r, v - r, u + r, v + r))
    f1, f2 = dr.font(label_pt * ppt, True), dr.font(value_pt * ppt)
    order = sorted(act, key=lambda f: -((dr.pads_bbox(f)[2] - dr.pads_bbox(f)[0]) * (dr.pads_bbox(f)[3] - dr.pads_bbox(f)[1])))
    n_values, without = 0, []
    for fp in order:
        bb, col = dr.pads_bbox(fp), color_of(fp)
        if values is True:
            lab.place(d, bb, [fp['ref'], pic_value(fp)], col, [f1, f2])
            n_values += 1
        elif values == 'fit' and lab.place(d, bb, [fp['ref'], pic_value(fp)], col, [f1, f2], max_cost=0, ngaps=value_gaps) is not None:
            n_values += 1
        else:
            lab.place(d, bb, [fp['ref']], col, [f1])
            without.append(fp['ref'])
    if values:
        print(f'  labels with a value: {n_values} of {len(order)}' + (f', without: {" ".join(without)}' if without else ''))
    if dnp_labels:
        for fp in items:
            if fp['kind'] == 'SMD' and fp['side'] == side and fp['step'] is None and not active(fp):
                lab.place(d, dr.pads_bbox(fp), [fp['ref'] + ' — не ставить'], (130, 130, 130), [f2])
    for (x, y), text in badges:
        dr.badge(d, view, x, y, text, r_mm=badge_mm)
    return img


# ------------------------------------------------------------------------------------------------- tables
def ref_key(ref):
    letters = ''.join(c for c in ref if c.isalpha())
    digits = ''.join(c for c in ref if c.isdigit())
    return letters, int(digits or 0)


def pol_text(data, refs):
    """short polarity / orientation note of a table row (nets only for single parts)"""
    ref = refs[0]
    single = len(refs) == 1
    nets = at.nets_of(data, ref)

    def n(p):
        return nets.get(str(p), '?')
    if ref in ('D601', 'D901'):
        return 'нет (двунаправленный)'
    if ref in ('C901', 'C909'):
        return f'«+» — пл.1{" (" + n(1) + ")" if single else ""}; минус — полоса'
    if ref in ('D521', 'D902'):
        return 'K (полоса) — пл.1'
    if ref in ('D711', 'D721'):
        return 'K — широкая пл.1 (вывод 1)'
    if ref == 'D303':
        return 'K — пл.3; пл.1, 2 — аноды'
    if ref in ('D301', 'D302', 'D501', 'D511', 'U101', 'U301', 'U601', 'U700', 'U710', 'U720', 'U902'):
        return 'вывод 1 — точка / скос'
    if ref in ('Q501', 'Q511', 'Q521'):
        return '1 = G, 2 = S, 3 = D'
    if ref in ('Q711', 'Q721'):
        return '1 — точка; D — пл. 5–8 и большая'
    if ref == 'Q601':
        return '1 = G, 2 = D, 3 = S; надпись к верху платы'
    if ref == 'U201':
        return 'вывод 1 — угол у левого края; антенна вверх'
    if ref == 'BT301':
        return f'«+» — пл.1 ({n(1)}), «−» — пл.2; снизу'
    if ref == 'J901':
        return f'1 = − ({n(1)}), 2 = + ({n(2)})'
    if ref in ('J601', 'J521'):
        return f'1 = + ({n(1)}), 2 = − ({n(2)})'
    if ref in ('J711', 'J721', 'J731'):
        return '1 = +, 2 = − (вход светильника)'
    if ref in ('J201', 'J301', 'J501', 'J511', 'J302'):
        pins = ' '.join(f'{p}={nets[p]}' for p in sorted(nets, key=lambda s: int(s) if s.isdigit() else 99))
        return (f'вывод 1 — метка; ' + pins) if single else 'вывод 1 — метка; ' + 'см. таблицу выводов'
    if ref == 'J401':
        return 'по контуру на шёлке'
    return ''


SHORT_PKG = {
    'SOT-323 (SC-70)': 'SC-70', 'SMC (DO-214AB)': 'SMC', 'SMB (DO-214AA)': 'SMB', 'Littelfuse 451 (SMD)': 'Littelfuse 451',
    'FXL0630 (SMD)': 'FXL0630', 'SRP1265A (SMD)': 'SRP1265A', 'microSD HRO TF-01A': 'microSD', 'SOIC-8 с площадкой EP': 'SOIC-8 EP',
    'модуль ESP32-WROOM-32E': 'модуль', 'кварц SMD 3,2×1,5': 'SMD 3,2×1,5', 'электролит SMD Ø16×17,5': 'SMD Ø16×17,5',
    'электролит SMD Ø10×10,5': 'SMD Ø10×10,5', 'тороид Ø32,5 мм, стоя': 'тороид, стоя', 'кнопка 6×6×10, выводная': 'кнопка 6×6×10',
    'штыревая гребёнка 1×6, шаг 2,54': 'гребёнка 1×6', 'JST XH 4 pin, угловой': 'JST XH 4, угловой', 'KK-254 4 pin, прямой': 'KK-254 4, прямой',
    'клеммник 2 pin, шаг 3,5': 'клеммник 3,5', 'клеммник 2 pin, шаг 5,0': 'клеммник 5,0', 'клеммник KF301 2 pin, шаг 5,0': 'клеммник 5,0',
    'держатель ATM mini': 'держатель ATM', 'держатель CR2032': 'держатель CR2032', 'TO-220, стоя': 'TO-220, стоя',
}


def short_pkg(pkg):
    name = at.pkg_name(pkg)
    return SHORT_PKG.get(name, name)


def short_val(value):
    """the value without the part number repeated from the MPN column (4.7u FXL0630-4R7-M -> 4.7u)"""
    if value.startswith('HRO '):
        return 'microSD'
    v = re.sub(r'\s*/\s*[\d.]+MRL$', '', value)
    return re.sub(r'^(\S+) [A-Z]{2,}[A-Z0-9]*[-/][\w.\-/]+$', lambda m: m.group(1), v)


def pic_value(fp):
    """value for a label on the picture: the MPN column already has the part number, the tolerance stays"""
    v = short_val(ad.short_value(fp['bom_value']))
    for tail in (' / >=16V', ' >=0.25W', ' >=1W', ' 50ppm'):
        v = v.replace(tail, '')
    return v


def rows_for(data, fps):
    groups = defaultdict(list)
    for fp in fps:
        groups[(ad.short_value(fp['bom_value']), fp['pkg'], fp['mpn'], fp['source'])].append(fp)
    rows = []
    for (value, pkg, mpn, source), items in groups.items():
        items.sort(key=lambda f: ref_key(f['ref']))
        rows.append(dict(value=value, pkg=pkg, mpn=mpn, source=source, fps=items))
    rows.sort(key=lambda r: ref_key(r['fps'][0]['ref']))
    return rows


def row_html(data, r):
    fps = r['fps']
    refs = [f['ref'] for f in fps]
    refs_html = ' '.join(f['ref'] + ('<span class="small"> (снизу)</span>' if f['side'] == 'B' else '') for f in fps)
    steps = ', '.join(str(s) for s in sorted({f['step'] for f in fps}))
    zones = ' '.join(sorted({mad.tile_of(f) for f in fps}))
    mpn = r['mpn'] or '<span class="small">по номиналу' + (f', склад {r["source"].split(":")[1]}' if r['source'].startswith('stock:') else '') + '</span>'
    note = pol_text(data, refs)
    return (f'<tr><td><b>{refs_html}</b></td><td>{len(fps)}</td><td>{short_val(r["value"])}</td><td>{short_pkg(r["pkg"])}</td>'
            f'<td><b>{mpn}</b></td><td>{note or "—"}</td><td>{steps}</td><td>{zones}</td></tr>')


COLUMNS = (('Позиции', 25), ('Шт.', 4), ('Номинал', 12), ('Корпус', 11), ('MPN', 17), ('Полярность / ориентация', 20), ('Шаг', 4), ('Зоны', 7))   # widths in %
HEAD = '<tr>' + ''.join(f'<th width="{w}%">{t}</th>' for t, w in COLUMNS) + '</tr>'


def table_html(data, rows, extra=''):
    return '<table>' + HEAD + ''.join(row_html(data, r) for r in rows) + extra + '</table>'


def fits(fonts, rect, html):
    tmp = pymupdf.open()
    pg = tmp.new_page(width=A4[0], height=A4[1])
    spare, scale = pg.insert_htmlbox(pymupdf.Rect(*rect), html, css=CSS, archive=fonts)
    tmp.close()
    return spare >= 0 and scale >= 0.999


def paginate(fonts, data, rows, rect_first, rect_next, title_first, title_next, extra=''):
    """pages of a table: as many rows per page as fit at full text size"""
    pages, i = [], 0
    while i < len(rows):
        rect = rect_first if not pages else rect_next
        title = title_first if not pages else title_next
        lo, hi = 1, len(rows) - i
        while lo < hi:
            mid = (lo + hi + 1) // 2
            tail = extra if i + mid == len(rows) else ''
            if fits(fonts, rect, title + table_html(data, rows[i:i + mid], tail)):
                lo = mid
            else:
                hi = mid - 1
        tail = extra if i + lo == len(rows) else ''
        pages.append((rect, title + table_html(data, rows[i:i + lo], tail)))
        i += lo
    return pages


# ------------------------------------------------------------------------------------------------- pages
def step_legend(steps):
    rows = ''.join(f'<tr><td class="sw" style="background:rgb{at.ad_color(k)}; width:9%">{k}</td><td>{ad.STEPS[k][0]}</td></tr>' for k in steps)
    return f'<h2>Порядок установки (цвет = шаг)</h2><table>{rows}</table>'


def polar_legend():
    return ('<h2>Цвет детали</h2><table>'
            f'<tr><td class="sw" style="background:rgb{at.ad_color(5)}; width:9%">&nbsp;</td><td><b>без полярности</b>: резисторы, керамика, индуктивности, '
            'предохранители, кварц, SMBJ (D601, D901), microSD</td></tr>'
            f'<tr><td class="sw" style="background:rgb{at.ad_color(3)}">&nbsp;</td><td><b>с полярностью или выводом 1</b>: диоды, электролиты, '
            'транзисторы, микросхемы, ESP32 — по красной метке</td></tr></table>'
            '<h2>Порядок пайки (колонка «Шаг»)</h2>'
            '<p class="small">1 — C911 снизу; 2 — микросхемы; 3 — транзисторы и диоды; 4 — 0603; 5 — 0805; 6 — 1206, 1210, 2512, F301; '
            '7 — индуктивности, предохранители Littelfuse, кварц, C901 и C909; 8 — ESP32 и microSD.</p>')


def marks_legend(rows_html):
    return ('<h2>Метки полярности на схеме</h2><table>' + rows_html + '</table>'
            '<p class="small">Серые детали — не из этой схемы (контекст). Сетка A–D, 1–4 — зоны 25 × 25 мм, как в столбце «Зоны» таблицы.</p>')


def picture_page(doc, fonts, title, subtitle, image, inset, inset_title, legend_marks, legend_steps, page=A4, k=1.0):
    """a page of the given size (A4 or A3, k = text scale): title, the board picture across the page, below it the inset
    of the bottom side and two legends"""
    css = CSS if k == 1.0 else scaled_css(k)
    pg = doc.new_page(width=page[0], height=page[1])
    pg.insert_htmlbox(pymupdf.Rect(M, 10, page[0] - M, 48 * k), f'<h1>{title}</h1><p class="small">{subtitle}</p>', css=css, archive=fonts)
    w = page[0] - 2 * M
    top = 50 * k
    pg.insert_image(pymupdf.Rect(M, top, M + w, top + w * image.size[1] / image.size[0]), stream=mad.jpeg_bytes(image, 90))
    y = top + w * image.size[1] / image.size[0] + 4
    inset_w = min(page[1] - 12 - y - 12 * k, 190 * k)
    pg.insert_htmlbox(pymupdf.Rect(M, y, M + inset_w, y + 12 * k), f'<p class="small"><b>{inset_title}</b></p>', css=css, archive=fonts)
    pg.insert_image(pymupdf.Rect(M, y + 12 * k, M + inset_w, y + 12 * k + inset_w * inset.size[1] / inset.size[0]), stream=mad.jpeg_bytes(inset, 88))
    x1 = M + inset_w + 8
    mid = x1 + (page[0] - M - x1) * 0.52
    pg.insert_htmlbox(pymupdf.Rect(x1, y, mid - 4, page[1] - 12), legend_marks, css=css, archive=fonts)
    pg.insert_htmlbox(pymupdf.Rect(mid, y, page[0] - M, page[1] - 12), legend_steps, css=css, archive=fonts)
    return pg


def build(data, out_path, png_dir=None, a3_path=None):
    fonts = pymupdf.Archive(str(mad.FONTS))
    doc = pymupdf.open()
    smd_top = lambda fp: fp['step'] is not None and fp['kind'] == 'SMD' and fp['side'] == 'F'
    smd_bot = lambda fp: fp['step'] is not None and fp['kind'] == 'SMD' and fp['side'] == 'B'
    tht_top = lambda fp: fp['step'] is not None and fp['kind'] == 'THT' and fp['side'] == 'F'
    tht_bot = lambda fp: fp['step'] is not None and fp['kind'] == 'THT' and fp['side'] == 'B'
    W = A4[0] - 2 * M
    previews = {}

    n_smd = sum(1 for fp in data['fps'] if fp['step'] and fp['kind'] == 'SMD')
    n_tht = sum(1 for fp in data['fps'] if fp['step'] and fp['kind'] == 'THT')
    # ------------------------------------------------------------------ SMD picture
    main = render_sheet(data, False, smd_top, W, 36, values='fit', color_of=polar_color)
    inset = render_sheet(data, True, smd_bot, 190, 14, values=True, badge_mm=0.8, color_of=polar_color)
    previews['1_smd'] = main
    marks = ('<tr><td class="k">K</td><td>катод диода — полоса на корпусе</td></tr><tr><td class="k">+ / −</td><td>плюс / минус</td></tr>'
             '<tr><td class="k">1</td><td>вывод 1: точка, скос или метка на корпусе микросхемы</td></tr>'
             '<tr><td class="k">G S D</td><td>затвор, исток, сток</td></tr>')
    smd_note = ('Зелёные детали — без полярности, оранжевые — с полярностью; красный кружок — вывод, к которому должна встать метка на детали. ')
    smd_inset_title = 'Нижняя сторона (плата перевёрнута, зеркально): C911'
    picture_page(doc, fonts, 'GrowBox cheap-1 — схема установки SMD-деталей (вид сверху)',
                 f'{n_smd} SMD-деталей, из них {n_smd - 1} сверху и C911 снизу. Позиции — по таблице на следующей странице. ' + smd_note +
                 'Номинал рядом с позицией — там, где хватило места, полный список — в таблице.',
                 main, inset, smd_inset_title, marks_legend(marks), polar_legend())
    if a3_path:
        # the same picture on one A3 sheet, a separate file: 1.41 times larger, so the values fit next to the references
        k3 = A3[0] / A4[0]
        doc3 = pymupdf.open()
        main3 = render_sheet(data, False, smd_top, A3[0] - 2 * M, 40, values='fit', color_of=polar_color, label_pt=7.5, value_pt=6.2,
                             value_gaps=10)
        inset3 = render_sheet(data, True, smd_bot, 190 * k3, 20, values=True, badge_mm=0.8, color_of=polar_color, label_pt=7.5, value_pt=6.2)
        previews['1_smd_a3'] = main3
        picture_page(doc3, fonts, 'GrowBox cheap-1 — схема установки SMD-деталей (вид сверху, лист A3)',
                     f'{n_smd} SMD-деталей, из них {n_smd - 1} сверху и C911 снизу. Таблица позиций и MPN — в Assembly_cheap1_A4.pdf, страница 2. ' + smd_note +
                     'Номинал стоит рядом с позицией; если для него не нашлось места, он есть в таблице.',
                     main3, inset3, smd_inset_title, marks_legend(marks), polar_legend(), page=A3, k=k3)
        doc3.subset_fonts()
        doc3.save(a3_path, garbage=4, deflate=True, deflate_fonts=True)
        print('saved', a3_path, 'A3 sheet')
    # ------------------------------------------------------------------ SMD table
    smd_rows = rows_for(data, [fp for fp in data['fps'] if fp['step'] and fp['kind'] == 'SMD'])
    extra = ('<tr><td colspan="8" class="small"><b>Не ставить:</b> C106 (DNP); TP101–TP103, TP301, TP901, TP902, NT711, NT712, NT721, NT722 — '
             'только медные площадки. «Шаг» — порядок пайки (расшифровка на схеме), «Зоны» — сетка A–D, 1–4 на схеме.</td></tr>')
    rect1 = (M, 30, A4[0] - M, A4[1] - 8)
    for i, (rect, html) in enumerate(paginate(fonts, data, smd_rows, rect1, (M, 10, A4[0] - M, A4[1] - 8),
                                              f'<h1>SMD-детали — позиции и MPN ({n_smd} шт., {len(smd_rows)} строк)</h1>',
                                              '<h1>SMD-детали (продолжение)</h1>', extra)):
        pg = doc.new_page(width=A4[0], height=A4[1])
        pg.insert_htmlbox(pymupdf.Rect(*rect), html, css=CSS, archive=fonts)
    # ------------------------------------------------------------------ THT picture
    main = render_sheet(data, False, tht_top, W, 36, values=True, badge_mm=1.1, label_pt=7.6, value_pt=6.0)
    inset = render_sheet(data, True, tht_bot, 190, 14, values=True, badge_mm=1.3, label_pt=7.6, value_pt=6.0)
    previews['3_tht'] = main
    marks = ('<tr><td class="k">+ / −</td><td>плюс / минус: клеммник, держатель батарейки</td></tr>'
             '<tr><td class="k">1</td><td>вывод 1 разъёма, штыревой гребёнки; точка на корпусе</td></tr>'
             '<tr><td class="k">G S D</td><td>затвор, исток, сток транзистора Q601</td></tr>')
    picture_page(doc, fonts, 'GrowBox cheap-1 — схема установки выводных деталей (вид сверху)',
                 f'{n_tht} выводных деталей, из них {n_tht - 1} сверху и держатель батарейки BT301 снизу. SMD-детали показаны серым. '
                 'Провод в клеммники входит со стороны ближайшего края платы.',
                 main, inset, 'Нижняя сторона (плата перевёрнута, зеркально): BT301', marks_legend(marks), step_legend([9, 10]))
    # ------------------------------------------------------------------ THT table
    tht_rows = rows_for(data, [fp for fp in data['fps'] if fp['step'] and fp['kind'] == 'THT'])
    extra = ('<tr><td><b>BT301</b> <span class="small">(батарейка)</span></td><td>1</td><td>CR2032</td><td>батарейка 20 мм</td><td><b>CR2032</b></td>'
             '<td>плюсом к плюсовому контакту держателя</td><td>10</td><td>—</td></tr>'
             '<tr><td colspan="8" class="small"><b>F902:</b> в держатель вставляется свой предохранитель 10 А (ATM mini) — после проверки платы, '
             'в закупку он не входит. Батарейку CR2032 тоже вставлять после проверки. Порядок: кнопки и гребёнка, разъёмы JST и KK, клеммники, F902, Q601, '
             'тороид L711 последним; BT301 — снизу.</td></tr>')
    pg = doc.new_page(width=A4[0], height=A4[1])
    html = f'<h1>Выводные детали — позиции и MPN ({n_tht} шт., {len(tht_rows)} строк)</h1>' + table_html(data, tht_rows, extra)
    if not fits(fonts, (M, 40, A4[0] - M, A4[1] - 14), html):
        print('  WARNING: through-hole table does not fit on one page at full size')
    pg.insert_htmlbox(pymupdf.Rect(M, 40, A4[0] - M, A4[1] - 14), html, css=CSS, archive=fonts)
    doc.subset_fonts()
    doc.save(out_path, garbage=4, deflate=True, deflate_fonts=True)
    print('saved', out_path, doc.page_count, 'pages')
    if png_dir:
        Path(png_dir).mkdir(parents=True, exist_ok=True)
        for k, im in previews.items():
            im.save(Path(png_dir) / f'{k}.png')
        for i, page in enumerate(pymupdf.open(out_path)):
            page.get_pixmap(dpi=110).save(str(Path(png_dir) / f'page{i + 1}.png'))


if __name__ == '__main__':
    mad.FONTS.mkdir(exist_ok=True)
    for name in ('arial.ttf', 'arialbd.ttf', 'ariali.ttf'):
        if not (mad.FONTS / name).exists():
            (mad.FONTS / name).write_bytes((dr.FONT_DIR / name).read_bytes())
    d = mad.load(sys.argv[1])
    build(d, sys.argv[2], sys.argv[sys.argv.index('--png') + 1] if '--png' in sys.argv else None,
          sys.argv[sys.argv.index('--a3') + 1] if '--a3' in sys.argv else None)
