"""Price the whole schematic from a committed LCSC price snapshot.

  python audit_bom_cost.py netlist.xml PCB_V1/price_snapshot_v22.json [--output report.txt]

Every schematic reference must appear in exactly one snapshot line (parts that are not bought,
such as DNP positions and bare test pads, are listed with kind "zero"). Lines with no references
are consumables outside the schematic. For each build size the order quantity is rounded up to the
LCSC minimum and multiple, and the price tier is taken at that order quantity:
  per board = parts actually fitted x tier price / boards
  order     = order quantity x tier price (includes minimum-quantity leftovers)
List prices only: promotional discounts, shipping, VAT/duty, PCB, assembly and stock changes after
the snapshot date are not included. The snapshot is a dated record, not a live quote.
"""
import argparse
import json
import math
import xml.etree.ElementTree as ET
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

BUILDS = (1, 5)


def money(x):
    return Decimal(x).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)


def tier_price(tiers, qty):
    price = Decimal(str(tiers[0][1]))
    for tier_qty, tier_usd in tiers:
        if qty >= tier_qty:
            price = Decimal(str(tier_usd))
    return price


def order_quantity(line, need):
    step = max(line['mult'], 1)
    return max(line['min'], math.ceil(need / step) * step)


def label(refs, width=30):
    text = ','.join(refs) if refs else '(not in schematic)'
    return text if len(text) <= width else f'{refs[0]}..{refs[-1]} ({len(refs)})'


def report(netlist, snapshot):
    root = ET.parse(netlist).getroot()
    comps = {c.get('ref'): c for c in root.findall('.//components/comp')}
    revision = root.findtext('./design/sheet/title_block/rev', 'unknown').removesuffix('-DRAFT')
    data = json.loads(snapshot.read_text(encoding='utf-8'))
    rate = Decimal(str(data['eur_usd']['rate']))
    seen = set()
    purchasing_codes = set()
    rows, unpriced, short = [], [], []
    totals = {n: {'board': Decimal(0), 'order': Decimal(0)} for n in BUILDS}
    for line in data['lines']:
        refs = line['refs']
        assert len(refs) == len(set(refs)) and not seen.intersection(refs), ('duplicate reference', refs)
        for ref in refs:
            assert ref in comps, (ref, 'priced reference absent from schematic')
            fields = {f.get('name'): f.text or '' for f in comps[ref].findall('fields/field')}
            assert not fields.get('MPN') or fields['MPN'] in line['part'], (ref, fields['MPN'], 'different part')
        seen.update(refs)
        qty = len(refs) if refs else line['qty']
        if line['kind'] == 'zero':
            continue
        if line['lcsc']:
            assert line['lcsc'] not in purchasing_codes, (line['lcsc'], 'merge equal purchasing codes before applying MOQ/tier prices')
            purchasing_codes.add(line['lcsc'])
        if not line['tiers']:
            unpriced.append(line)
            continue
        row = dict(line=line, qty=qty)
        for n in BUILDS:
            need = qty * n
            order = order_quantity(line, need)
            price = tier_price(line['tiers'], order)
            row[n] = dict(price=price, board=price * need / n, order=price * order, order_qty=order)
            totals[n]['board'] += row[n]['board']
            totals[n]['order'] += row[n]['order']
            if line['stock'] < need:
                short.append((n, line))
        rows.append(row)
    missing = sorted(set(comps) - seen)
    assert not missing, ('schematic references without a price line', missing)

    date, src = data['captured'], data['source']
    out = [f'PCB_V1 v{revision} BOM price audit, LCSC snapshot {date}',
           f'{src}. EUR at ECB {data["eur_usd"]["date"]}: 1 EUR = {rate} USD.',
           'Per board = fitted parts x tier price; order = LCSC minimum/multiple applied (leftovers included).',
           f'Priced on-board purchasing codes: {len({r["line"]["lcsc"] for r in rows if r["line"]["refs"]})}; '
           f'fitted on-board parts: {sum(r["qty"] for r in rows if r["line"]["refs"])} (DNP and copper test pads excluded).',
           'Not included: shipping, VAT/duty, PCB, assembly, promotional discounts, parts marked unpriced.', '',
           f'{"refs":30} {"qty":>3} {"LCSC":>10} {"kind":8} {"USD@1":>8} {"1 board":>8} {"order 1":>8} '
           f'{"USD@5":>8} {"5: /board":>9} {"order 5":>8}  part']
    for row in rows:
        line = row['line']
        out.append(f'{label(line["refs"]):30} {row["qty"]:3d} {line["lcsc"]:>10} {line["kind"]:8} '
                   f'{money(row[1]["price"]):8} {money(row[1]["board"]):8} {money(row[1]["order"]):8} '
                   f'{money(row[5]["price"]):8} {money(row[5]["board"]):9} {money(row[5]["order"]):8}  '
                   f'{line["part"]}')
    out.append('')
    for n in BUILDS:
        board, order = totals[n]['board'], totals[n]['order']
        out.append(f'{n} board(s): parts per board USD {money(board)} = EUR {money(board / rate)}; '
                   f'order USD {money(order)} = EUR {money(order / rate)}')
    out += ['', 'Largest per-board contributors (1 board):']
    top = sorted(rows, key=lambda r: r[1]['board'], reverse=True)[:12]
    total1 = totals[1]['board']
    for row in top:
        share = row[1]['board'] / total1 * 100
        out.append(f'  {money(row[1]["board"]):8} USD {share:5.1f}%  {label(row["line"]["refs"], 40)}  {row["line"]["part"]}')
    by_kind, by_sheet = {}, {}
    for row in rows:
        by_kind[row['line']['kind']] = by_kind.get(row['line']['kind'], Decimal(0)) + row[1]['board']
        for ref in row['line']['refs'] or [None]:
            sheet = (comps[ref].find('sheetpath').get('names').strip('/') or 'root') if ref else 'consumables'
            share = row[1]['price'] * (1 if ref else row['qty'])
            by_sheet[sheet] = by_sheet.get(sheet, Decimal(0)) + share
    out += ['', 'Per board by line kind (1 board): ' + ', '.join(f'{k} USD {money(v)}' for k, v in sorted(by_kind.items()))]
    out += ['', 'Per board by schematic sheet (1 board):']
    out += [f'  {money(v):8} USD {v / total1 * 100:5.1f}%  {k}' for k, v in sorted(by_sheet.items(), key=lambda kv: -kv[1])]
    out += ['', 'Stock shortfalls at the snapshot date:']
    out += [f'  {n} board(s): {label(line["refs"], 40)} {line["lcsc"]} stock {line["stock"]}, {line["part"]}'
            for n, line in short] or ['  none']
    out += ['', 'Unpriced lines:']
    out += [f'  {label(line["refs"], 40)} qty {line["qty"] if not line["refs"] else len(line["refs"])}: {line["part"]} - {line["note"]}'
            for line in unpriced] or ['  none']
    notes = [line for line in data['lines'] if line.get('note') and line['kind'] in ('clone', 'option', 'generic', 'zero')]
    out += ['', 'Line notes:'] + [f'  {label(line["refs"], 40)} [{line["kind"]}] {line["note"]}' for line in notes]
    out += ['', f'{len(seen)} of {len(comps)} schematic references covered; '
            f'{sum(1 for line in data["lines"] if line["kind"] == "zero")} zero-cost lines.']
    return '\n'.join(out) + '\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('netlist', type=Path)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = report(args.netlist, args.snapshot)
    if args.output:
        args.output.write_text(result, encoding='utf-8')
    print(result, end='')
