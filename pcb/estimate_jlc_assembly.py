"""Estimate a JLCPCB PCB + assembly order for the whole schematic.

  python estimate_jlc_assembly.py netlist.xml PCB_V1/price_snapshot_v16.json PCB_V1/jlc_snapshot_v16.json [--output report.txt]

Parts: every priced schematic line of the LCSC price snapshot, re-priced from the JLCPCB parts
library record in the JLC snapshot. JLCPCB charges max(BOM x boards + attrition, minimum) pieces at
the tier for that quantity; leftovers stay in the customer's JLCPCB parts library.
Fees: the published fee table stored in the JLC snapshot. Solder joints are counted from the pads
of each reference's footprint (SMD pads -> SMT, plated through-holes -> manual/wave soldering).
Consumables outside the schematic are bought separately and priced from the LCSC snapshot.
Not included: shipping, VAT/duty, coupons, parts JLCPCB cannot source (flagged), programming, testing.
"""
import argparse
import json
import xml.etree.ElementTree as ET
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

BUILDS = (2, 5)
D = lambda x: Decimal(str(x))


def money(x):
    return D(x).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def tier(tiers, qty):
    price = D(tiers[0][1])
    for start, usd in tiers:
        if qty >= start:
            price = D(usd)
    return price


def lcsc_order(line, need):
    step = max(line['mult'], 1)
    qty = max(line['min'], -(-need // step) * step)
    return qty, tier(line['tiers'], qty) * qty


def report(netlist, price_snapshot, jlc_snapshot):
    root = ET.parse(netlist).getroot()
    comps = {c.get('ref'): c for c in root.findall('.//components/comp')}
    revision = root.findtext('./design/sheet/title_block/rev', 'unknown').removesuffix('-DRAFT')
    prices = json.loads(price_snapshot.read_text(encoding='utf-8'))
    jlc = json.loads(jlc_snapshot.read_text(encoding='utf-8'))
    rate = D(prices['eur_usd']['rate'])
    parts, joints = jlc['parts'], jlc['joints']
    lines, extras = [], []
    for line in prices['lines']:
        if line['kind'] == 'zero':
            continue
        if not line['refs']:
            extras.append(line)
            continue
        assert line['lcsc'] in parts, (line['lcsc'], 'no JLCPCB record')
        smt = tht = 0
        for ref in line['refs']:
            fp = comps[ref].findtext('footprint')
            assert fp in joints, (ref, fp, 'footprint missing from the joint table')
            smt += joints[fp][0]
            tht += joints[fp][1]
        lines.append(dict(line=line, part=parts[line['lcsc']], qty=len(line['refs']), smt=smt, tht=tht))
    covered = {ref for item in lines for ref in item['line']['refs']}
    zero = {ref for line in prices['lines'] if line['kind'] == 'zero' for ref in line['refs']}
    assert covered | zero == set(comps), ('schematic references not covered', sorted(set(comps) - covered - zero))

    types, ext_tht = {}, set()
    for item in lines:
        types.setdefault(item['part']['t'], set()).add(item['line']['lcsc'])
        if item['part']['t'] == 'E' and not item['smt']:
            ext_tht.add(item['line']['lcsc'])
    # The Economic extended fee is a pick-and-place feeder charge; wave-soldered parts use no feeder.
    n_ext = len(types.get('E', set()) - ext_tht)
    n_all = sum(len(v) for v in types.values())
    smt1, tht1 = sum(i['smt'] for i in lines), sum(i['tht'] for i in lines)
    fees = jlc['fees']
    out = [f'PCB_V1 v{revision} JLCPCB PCB + assembly estimate, JLC snapshot {jlc["captured"]}',
           f'Fees: {jlc["sources"]["fees"]}. EUR at ECB {prices["eur_usd"]["date"]}: 1 EUR = {rate} USD.',
           f'PCB: {jlc["sources"]["pcb"]}: USD {jlc["pcb"]["usd"]:.2f} for {jlc["pcb"]["qty"]} pcs ({jlc["pcb"]["breakdown"]}).',
           f'Unique parts {n_all}: basic {len(types.get("B", ()))}, preferred {len(types.get("P", ()))}, extended '
           f'{len(types.get("E", ()))} ({n_ext} placed by machine, {len(ext_tht)} through-hole). '
           f'Joints per board: SMT {smt1} (pads), through-hole {tht1}. X-ray refs per board: {", ".join(jlc["xray_refs"])}.',
           'Not included: shipping, VAT/duty, coupons, programming/testing. Leftover parts stay in the JLCPCB parts library.', '']

    def xray(count):
        return tier(fees['xray_tiers'], count) * count if count else D(0)

    def assembly(kind, n):
        f = fees[kind]
        smt_j, tht_j = smt1 * n, tht1 * n
        rows = [('setup', D(f['setup'])), ('stencil', D(f['stencil'])),
                (f'SMT {smt_j} joints', D(f['smt_joint']) * smt_j),
                (f'through-hole {tht_j} joints', D(f['manual_joint']) * tht_j),
                ('hand-soldering labour', D(f['hand_labor']) if tht_j else D(0))]
        if kind == 'economic':
            rows.append((f'extended part loading x{n_ext}', D(f['feeder_extended']) * n_ext))
        else:
            rows.append((f'feeder loading x{n_all}', D(f['feeder_basic']) * n_all))
            rows.append(('packing', D(f['packing_base']) + D(f['packing_per_cm2']) * jlc['pcb']['area_cm2'] * n))
            rows.append(('fixtures', D(f['fixtures'])))
        rows.append((f'X-ray {len(jlc["xray_refs"]) * n} pcs', xray(len(jlc['xray_refs']) * n)))
        return rows

    parts_cost, shortages = {}, []
    for n in BUILDS:
        total = D(0)
        for item in lines:
            p = item['part']
            need = item['qty'] * n
            charged = max(need + p['loss'], p['moq'])
            item[n] = (charged, tier(p['prices'], charged) * charged)
            total += item[n][1]
            if p['presale'] < charged:
                shortages.append((n, item, charged))
        parts_cost[n] = total
    extra_cost = {n: sum((lcsc_order(line, line['qty'] * n)[1] for line in extras if line['tiers']), D(0)) for n in BUILDS}

    out.append('Order totals (5 PCBs made in every case; n boards assembled):')
    summary = {}
    for kind, label in (('economic', 'Economic PCBA, single-sided'), ('standard_double', 'Standard PCBA, double-sided')):
        for n in BUILDS:
            rows = assembly(kind, n)
            fee = sum(v for _, v in rows)
            total = D(jlc['pcb']['usd']) + fee + parts_cost[n] + extra_cost[n]
            summary[(kind, n)] = total
            out.append(f'  {label}, {n} assembled: PCB {money(jlc["pcb"]["usd"])} + assembly {money(fee)} + JLC parts '
                       f'{money(parts_cost[n])} + separate {money(extra_cost[n])} = USD {money(total)} = EUR {money(total / rate)}; '
                       f'USD {money(total / n)} per assembled board')
            out.append('      ' + '; '.join(f'{name} {money(v)}' for name, v in rows))
    out += ['', f'{"refs":30} {"LCSC":>10} {"type":4} {"qty":>3} {"SMT":>4} {"THT":>4} {"n=2 pcs":>7} {"USD":>7} {"n=5 pcs":>7} {"USD":>7}  part']
    for item in lines:
        refs = item['line']['refs']
        label = ','.join(refs) if len(','.join(refs)) <= 30 else f'{refs[0]}..{refs[-1]} ({len(refs)})'
        out.append(f'{label:30} {item["line"]["lcsc"]:>10} {item["part"]["t"]:4} {item["qty"]:3d} {item["smt"]:4d} {item["tht"]:4d} '
                   f'{item[2][0]:7d} {money(item[2][1]):7} {item[5][0]:7d} {money(item[5][1]):7}  {item["line"]["part"]}')
    out += ['', 'Bought separately (not assembled by JLCPCB):']
    for line in extras:
        if line['tiers']:
            out.append(f'  {line["part"]}: LCSC {line["lcsc"]}, order ' +
                       ', '.join(f'{n} boards {lcsc_order(line, line["qty"] * n)[0]} pcs USD {money(lcsc_order(line, line["qty"] * n)[1])}' for n in BUILDS))
        else:
            out.append(f'  {line["part"]}: not priced - {line["note"]}')
    out += ['', 'JLCPCB availability below the charged quantity (orderable stock at the snapshot date):']
    out += [f'  {n} boards: {",".join(item["line"]["refs"])} {item["line"]["lcsc"]} {item["line"]["part"]}: '
            f'orderable {item["part"]["presale"]}, needs {charged}' for n, item, charged in shortages] or ['  none']
    out += ['', f'X-ray assumption: {jlc["xray_note"]}.',
            f'Extended loading is charged for the {n_ext} machine-placed extended types only; if JLCPCB also charges the '
            f'{len(ext_tht)} through-hole extended types, add USD {money(D(fees["economic"]["feeder_extended"]) * len(ext_tht))} '
            f'(Economic).']
    return '\n'.join(out) + '\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('netlist', type=Path)
    parser.add_argument('price_snapshot', type=Path)
    parser.add_argument('jlc_snapshot', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = report(args.netlist, args.price_snapshot, args.jlc_snapshot)
    if args.output:
        args.output.write_text(result, encoding='utf-8')
    print(result, end='')
