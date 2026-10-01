"""Export the order BOM for LCSC from the schematic and the dated price snapshots.

  python export_lcsc_bom.py netlist.xml PCB_V1/price_snapshot_v22.json PCB_V1/jlc_snapshot_v22.json OUTDIR [--rev v22] [--boards 5]

Writes into OUTDIR (all deterministic: same inputs give the same bytes):
  BOM_LCSC_<rev>.csv / .xlsx   upload file for https://www.lcsc.com/bom (.csv/.xlsx, up to 800 lines): Quantity,
                               LCSC Part Number, Manufacturer Part Number, Manufacturer, Description, Customer Part Number
                               (the designators). Only parts LCSC can supply at the snapshot date, quantities for
                               --boards boards including spares and LCSC minimum/multiple. The workbook also has the
                               full BOM, the parts to buy elsewhere and the totals.
  BOM_PCB_V1_<rev>.csv         full grouped BOM: one line per purchasing code, with package, mounting, price tiers
                               applied, stock, JLCPCB library class, notes; not fitted lines and extras included.

Quantities: parts per board x boards, plus spares (10 %, at least one piece; the LCSC minimum/multiple may already
cover it), then rounded up to the LCSC minimum and multiple. The unit price is the list price tier at the order
quantity. Prices, stock and minimums are the snapshot of the dates in the snapshot file, not a live quote: the LCSC
BOM tool shows the live values after upload and the quantities can be edited there.
"""
import argparse
import csv
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

import audit_bom_cost as audit

SPARE_RATE = Decimal('0.1')
CATEGORY = {'U': 'IC / module', 'Q': 'Transistor / MOSFET', 'D': 'Diode / TVS / ESD', 'L': 'Inductor', 'C': 'Capacitor',
            'R': 'Resistor', 'F': 'Fuse / holder', 'J': 'Connector', 'SW': 'Switch', 'BT': 'Battery holder', 'Y': 'Crystal',
            'NT': 'Net tie (copper only)', 'TP': 'Test pad (copper only)'}
THT = ('Connector_JST', 'PinHeader', 'AMASS_XT60', 'BatteryHolder', 'TerminalBlock', 'Fuseholder_Blade')
PART_TYPE = {'mpn': 'Exact MPN', 'generic': 'Equivalent allowed', 'clone': 'Second source', 'option': 'Pending decision',
             'extra': 'Extra, not on schematic', 'zero': 'Not fitted'}
JLC_CLASS = {'B': 'Basic', 'E': 'Extended', 'P': 'Preferred extended'}


TUNE = re.compile(r'\s*/\s*(comp|CS|slope)\s+tune$')


def clean_value(value):
    """Schematic values carry function labels ('100p / comp tune'); the order BOM wants the electrical value only."""
    return TUNE.sub('', value).strip()


def short_package(package):
    m = re.search(r'_(\d{4})_\d{4}Metric', package)
    return m.group(1) if m else package


def natural(ref):
    return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', ref)]


def category(refs):
    if not refs:
        return 'Extra'
    prefix = re.match(r'[A-Z]+', refs[0]).group()
    return CATEGORY.get(prefix, prefix)


def split_part(part):
    """'UNI-ROYAL 0603WAF1002T5E' -> ('UNI-ROYAL', '0603WAF1002T5E'); a trailing note in brackets is dropped."""
    text = re.sub(r'\s*\(.*?\)\s*$', '', part).strip()
    manufacturer, _, mpn = text.rpartition(' ')
    return manufacturer, mpn


def build(netlist, snapshot, jlc_snapshot, boards):
    root = ET.parse(netlist).getroot()
    comps = {c.get('ref'): c for c in root.findall('.//components/comp')}
    data = json.loads(snapshot.read_text(encoding='utf-8'))
    jlc = json.loads(jlc_snapshot.read_text(encoding='utf-8'))['parts']
    rows = []
    for line in data['lines']:
        refs = sorted(line['refs'], key=natural)
        qty = len(refs) if refs else line['qty']
        kind = line['kind']
        fields = [{f.get('name'): f.text or '' for f in comps[r].findall('fields/field')} for r in refs]
        values = Counter(clean_value(comps[r].findtext('value')) for r in refs)
        best = max(values.values()) if refs else 0
        value = max((v for v, n in values.items() if n == best), key=len) if refs else line['part']
        extra_values = []
        footprint = comps[refs[0]].findtext('footprint') if refs else ''
        package = footprint.split(':')[-1]
        if kind == 'mpn' and fields and fields[0].get('MPN') and fields[0]['MPN'] in line['part']:
            manufacturer, mpn = fields[0].get('Manufacturer', ''), fields[0]['MPN']
        elif kind == 'zero':
            manufacturer, mpn, value = '', '', line['part']
        elif kind == 'extra' and not line['lcsc']:
            manufacturer, mpn = '', re.sub(r'\s*\(.*?\)\s*$', '', line['part']).strip()
        else:
            manufacturer, mpn = split_part(line['part'])
        mount = 'THT' if any(t in footprint for t in THT) else ('SMD' if refs else 'Loose part')
        row = dict(line=line, refs=refs, qty=qty, kind=kind, category=category(refs), value=value, package=package, mount=mount,
                   manufacturer=manufacturer, mpn=mpn, lcsc=line['lcsc'] or '', stock=line['stock'], moq=line['min'], mult=line['mult'],
                   source=line.get('source', ''), jlc=jlc.get(line['lcsc'] or '', None))
        notes = []
        if kind == 'generic':
            notes.append('equivalent allowed: representative LCSC part for this value and package')
        if kind == 'clone':
            notes.append('second source: the original part is out of stock')
        if line['note']:
            notes.append(line['note'])
        if extra_values:
            notes.append('also labelled ' + ', '.join(extra_values))
        if 'BT301' in refs:
            notes.append('mounted on the bottom side')
        said = line['note'].lower()
        if kind != 'zero' and line['lcsc'] and line['stock'] == 0:
            if 'stock' not in said:
                notes.append('OUT OF STOCK at LCSC on the snapshot date: buy elsewhere')
            if row['jlc'] and row['jlc']['stock']:
                notes.append(f'JLCPCB parts library lists {row["jlc"]["stock"]} in stock (assembly service)')
        if kind != 'zero' and not line['lcsc'] and 'buy' not in said:
            notes.append('not at LCSC: buy elsewhere')
        row['notes'] = '; '.join(notes)
        if kind == 'zero' or not line['tiers']:
            row['orderable'] = False
            rows.append(row)
            continue
        row['orderable'] = line['stock'] > 0
        for n, spares in ((1, False), (boards, True)):
            need = qty * n
            spare = max(1, math.ceil(Decimal(need) * SPARE_RATE)) if spares else 0
            order = audit.order_quantity(line, need + spare)
            price = audit.tier_price(line['tiers'], order)
            row[f'build{n}'] = dict(need=need, order=order, spare=order - need, price=price, cost=price * order)
        base = audit.order_quantity(line, qty * boards)
        row['nospare'] = dict(order=base, cost=audit.tier_price(line['tiers'], base) * base)
        rows.append(row)
    order_key = {name: i for i, name in enumerate(CATEGORY.values())}
    rows.sort(key=lambda r: (r['kind'] == 'zero', r['category'] == 'Extra', order_key.get(r['category'], 99),
                             natural(r['refs'][0]) if r['refs'] else [r['line']['part']]))
    return rows, data


def money(x):
    return f'{audit.money(x):f}'


def description(r):
    """Passives: value and size. Everything else: manufacturer and part number."""
    if r['category'] in ('Capacitor', 'Resistor', 'Inductor'):
        return f'{r["value"]} {short_package(r["package"])}'
    if r['refs']:
        return f'{r["manufacturer"]} {r["mpn"]}'.strip()
    return re.sub(r'\s*\(.*?\)\s*$', '', r['line']['part'])


def customer_part(r):
    if r['refs']:
        return ' '.join(r['refs'])
    m = re.search(r'\((.*?)\)\s*$', r['line']['part'])
    return m.group(1) if m else r['line']['part']


def upload_rows(rows, boards):
    out = []
    for r in rows:
        if r['kind'] == 'zero' or not r['orderable']:
            continue
        b = r[f'build{boards}']
        out.append([b['order'], r['lcsc'], r['mpn'], r['manufacturer'], description(r), customer_part(r)])
    return out


UPLOAD_HEADER = ['Quantity', 'LCSC Part Number', 'Manufacturer Part Number', 'Manufacturer', 'Description', 'Customer Part Number']


def full_rows(rows, boards):
    header = ['Line', 'Category', 'Designators', 'Qty per board', 'Value / function', 'Package', 'Mount', 'Manufacturer', 'MPN', 'LCSC Part Number',
              'Part type', 'JLCPCB class', 'LCSC stock (snapshot)', 'LCSC minimum', 'LCSC multiple',
              'Order qty 1 board', 'Unit USD 1 board', 'Order USD 1 board',
              f'Needed {boards} boards', 'Spares and MOQ surplus', f'Order qty {boards} boards', f'Unit USD {boards} boards', f'Order USD {boards} boards',
              'LCSC page', 'Notes']
    out = []
    for i, r in enumerate(rows, 1):
        jlc = JLC_CLASS.get(r['jlc']['t'], r['jlc']['t']) if r['jlc'] else ''
        base = [i, r['category'], customer_part(r), r['qty'], r['value'] if r['refs'] and r['kind'] != 'zero' else (r['line']['part'] if r['kind'] == 'zero' else description(r)), r['package'], r['mount'],
                r['manufacturer'], r['mpn'], r['lcsc'], PART_TYPE[r['kind']], jlc, r['stock'] if r['lcsc'] else '',
                r['moq'] or '', r['mult'] or '']
        if 'build1' in r:
            one, many = r['build1'], r[f'build{boards}']
            base += [one['order'], money(one['price']), money(one['cost']), many['need'], many['spare'], many['order'],
                     money(many['price']), money(many['cost'])]
        else:
            base += ['', '', '', '', '', '', '', '']
        out.append(base + [r['source'], r['notes']])
    return header, out


def totals(rows, boards):
    t = {'parts': sum(r['qty'] for r in rows if r['kind'] != 'zero' and r['refs']),
         'codes': len({r['lcsc'] for r in rows if r['kind'] != 'zero' and r['lcsc'] and r['refs']}),
         'lines': sum(1 for r in rows if r['orderable'] and r['kind'] != 'zero')}
    ok = [r for r in rows if r.get('orderable') and 'build1' in r]
    t['order1'] = sum(r['build1']['cost'] for r in ok)
    t['orderN'] = sum(r[f'build{boards}']['cost'] for r in ok)
    t['orderN_nospare'] = sum(r['nospare']['cost'] for r in ok)
    t['elsewhere'] = [r for r in rows if r['kind'] != 'zero' and not r['orderable']]
    return t


def write_csv(path, header, body):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream, lineterminator='\r\n')
        writer.writerow(header)
        writer.writerows(body)


# --- a minimal .xlsx writer: no dependencies, fixed timestamps, inline strings -------------------------------------
def col_name(i):
    name = ''
    while True:
        name = chr(65 + i % 26) + name
        i = i // 26 - 1
        if i < 0:
            return name


STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<numFmts count="1"><numFmt numFmtId="164" formatCode="0.0000"/></numFmts>'
    '<fonts count="3"><font><sz val="10"/><name val="Arial"/></font><font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Arial"/></font>'
    '<font><b/><sz val="12"/><name val="Arial"/></font></fonts>'
    '<fills count="5"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/></patternFill></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFFFF2CC"/></patternFill></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFF2F2F2"/></patternFill></fill></fills>'
    '<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>'
    '<border><left style="thin"><color rgb="FFBFBFBF"/></left><right style="thin"><color rgb="FFBFBFBF"/></right>'
    '<top style="thin"><color rgb="FFBFBFBF"/></top><bottom style="thin"><color rgb="FFBFBFBF"/></bottom><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="8">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'                                                      # 0 plain
    '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>'   # 1 header
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'                                                          # 2 text
    '<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment vertical="top"/></xf>'                                              # 3 price
    '<xf numFmtId="1" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment vertical="top"/></xf>'                                                 # 4 integer
    '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>'                                                                                                                        # 5 title
    '<xf numFmtId="0" fontId="0" fillId="3" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'                                           # 6 attention
    '<xf numFmtId="0" fontId="0" fillId="4" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'                                           # 7 grey
    '</cellXfs></styleSheet>')


def sheet_xml(rows, widths, freeze_row=None, filter_ref=None):
    """rows: list of rows; a cell is a value or (value, style). Numbers become numeric cells."""
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">']
    if freeze_row:
        out.append(f'<sheetViews><sheetView workbookViewId="0"><pane ySplit="{freeze_row}" topLeftCell="A{freeze_row + 1}" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>')
    out.append('<cols>' + ''.join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths)) + '</cols>')
    out.append('<sheetData>')
    for r, row in enumerate(rows, 1):
        out.append(f'<row r="{r}">')
        for c, cell in enumerate(row):
            value, style = cell if isinstance(cell, tuple) else (cell, 0)
            ref = f'{col_name(c)}{r}'
            if value is None or value == '':
                out.append(f'<c r="{ref}" s="{style}"/>')
            elif isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
                out.append(f'<c r="{ref}" s="{style}"><v>{value}</v></c>')
            else:
                out.append(f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>')
        out.append('</row>')
    out.append('</sheetData>')
    if filter_ref:
        out.append(f'<autoFilter ref="{filter_ref}"/>')
    out.append('<pageSetup orientation="landscape" fitToWidth="1" fitToHeight="0"/></worksheet>')
    return ''.join(out)


def write_xlsx(path, sheets):
    """sheets: list of (name, xml)."""
    content = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
               '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
               '<Default Extension="xml" ContentType="application/xml"/>'
               '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
               '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>']
    content += [f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                for i in range(1, len(sheets) + 1)]
    content.append('</Types>')
    workbook = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                + ''.join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, (name, _) in enumerate(sheets, 1))
                + '</sheets></workbook>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                      for i in range(1, len(sheets) + 1))
            + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '</Relationships>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    parts = {'[Content_Types].xml': ''.join(content), '_rels/.rels': root_rels, 'xl/workbook.xml': workbook,
             'xl/_rels/workbook.xml.rels': rels, 'xl/styles.xml': STYLES}
    parts.update({f'xl/worksheets/sheet{i}.xml': xml for i, (_, xml) in enumerate(sheets, 1)})
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, text in parts.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, text.encode('utf-8'))


def workbook(rows, data, boards, rev):
    t = totals(rows, boards)
    up_header, up_body = UPLOAD_HEADER, upload_rows(rows, boards)
    sheet1 = [[(h, 1) for h in up_header]]
    for body in up_body:
        sheet1.append([(body[0], 4), (body[1], 2), (body[2], 2), (body[3], 2), (body[4], 2), (body[5], 2)])
    full_header, full_body = full_rows(rows, boards)
    numeric = {0, 3, 12, 13, 14, 15, 17, 18, 19, 20, 22}
    price = {16, 21}
    sheet2 = [[(h, 1) for h in full_header]]
    for body in full_body:
        cells = []
        for i, v in enumerate(body):
            style = 4 if i in numeric and v != '' else 3 if i in price and v != '' else 2
            cells.append((float(v) if style == 3 else v, style))
        if 'OUT OF STOCK' in body[-1] or 'not at LCSC' in body[-1]:
            cells = [(v, 6) for v, _ in cells]
        elif body[10] == 'Not fitted':
            cells = [(v, 7) for v, _ in cells]
        sheet2.append(cells)
    summary = [[(f'PCB_V1 {rev} - order BOM for LCSC', 5)], [],
               ['Price snapshot', data['captured']], ['Source', data['source']],
               ['EUR rate', f'1 EUR = {data["eur_usd"]["rate"]} USD ({data["eur_usd"]["date"]})'],
               ['Build', f'{boards} boards; quantities include spares (10 %, at least one piece) and the LCSC minimum/multiple'], [],
               [('Totals (list prices, USD, no shipping, VAT or discounts)', 5)],
               ['Parts on one board', t['parts']], ['Distinct LCSC codes on the board', t['codes']], ['Lines in the upload file', t['lines']],
               ['Order for 1 board, no spares', money(t['order1'])],
               [f'Order for {boards} boards, no spares', money(t['orderN_nospare'])],
               [f'Order for {boards} boards, with spares (upload file)', money(t['orderN'])], [],
               [('Not in the upload file: buy elsewhere', 5)]]
    for r in t['elsewhere']:
        summary.append([(', '.join(r['refs']) or r['line']['part'], 6), (f'{r["qty"]} per board: {r["manufacturer"]} {r["mpn"]}'.strip(), 6), (r['notes'], 6)])
    summary += [[], [('Not fitted / copper only', 5)]]
    for r in rows:
        if r['kind'] == 'zero':
            summary.append([(', '.join(r['refs']), 7), (r['value'] + ' - ' + r['line']['note'], 7)])
    summary += [[], [('Before ordering', 5)],
                ['Stock and prices are the snapshot above; the LCSC BOM tool shows the live values after upload and the quantities can be edited there.'],
                ['Generic lines are representative parts: an equivalent with the same value, package and rating is fine.']]
    return [('LCSC upload', sheet_xml(sheet1, [10, 18, 28, 22, 40, 60], 1, f'A1:F{len(sheet1)}')),
            ('Full BOM', sheet_xml(sheet2, [6, 18, 36, 8, 22, 28, 9, 20, 28, 14, 16, 12, 10, 9, 9, 10, 10, 10, 10, 8, 10, 10, 10, 34, 60], 1, f'A1:{col_name(len(full_header) - 1)}{len(sheet2)}')),
            ('Summary', sheet_xml(summary, [48, 48, 70]))]


def export(netlist, snapshot, jlc_snapshot, outdir, boards, rev):
    rows, data = build(netlist, snapshot, jlc_snapshot, boards)
    outdir.mkdir(parents=True, exist_ok=True)
    write_csv(outdir / f'BOM_LCSC_{rev}.csv', UPLOAD_HEADER, upload_rows(rows, boards))
    header, body = full_rows(rows, boards)
    write_csv(outdir / f'BOM_PCB_V1_{rev}.csv', header, body)
    write_xlsx(outdir / f'BOM_LCSC_{rev}.xlsx', workbook(rows, data, boards, rev))
    t = totals(rows, boards)
    print(f'{t["lines"]} lines for LCSC ({t["parts"]} parts on the board, {t["codes"]} codes); order for {boards} boards with spares USD {money(t["orderN"])} '
          f'(without spares {money(t["orderN_nospare"])}), 1 board USD {money(t["order1"])}')
    print('buy elsewhere: ' + '; '.join(f'{", ".join(r["refs"]) or r["line"]["part"]} {r["mpn"]}' for r in t['elsewhere']))
    return t


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('netlist', type=Path)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('jlc_snapshot', type=Path)
    parser.add_argument('outdir', type=Path)
    parser.add_argument('--rev', default='v22')
    parser.add_argument('--boards', type=int, default=5)
    args = parser.parse_args()
    export(args.netlist, args.snapshot, args.jlc_snapshot, args.outdir, args.boards, args.rev)
