"""Audit a partial price snapshot against the current schematic, without pricing missing parts.
Usage: python audit_bom_cost.py netlist.xml PCB_V1/price_snapshot_v15.json [--output report.txt]
"""
import argparse,json
from decimal import Decimal
from pathlib import Path
import xml.etree.ElementTree as ET


def report(netlist, snapshot):
    comps={c.get('ref'):c for c in ET.parse(netlist).findall('.//components/comp')}
    data=json.loads(snapshot.read_text(encoding='utf-8'))
    seen=set();total=Decimal('0')
    out=['PCB_V1 v0.15 partial BOM price audit',
         'Historical unit-use prices, NOT a purchase quote or a complete board cost.',
         'Unit tier/MOQ, unavailable stock, shipping, tax, PCB and assembly are not priced.',
         'F902/F903 price covers holders ONLY; fuse inserts and battery are extra.', '',
         'refs                          qty   unit_USD    line_USD']
    for line in data['lines']:
        refs=line['refs'];price=Decimal(str(line['unit_usd']))
        assert price>=0 and refs and len(refs)==len(set(refs)),line
        assert not seen.intersection(refs),'duplicate priced reference'
        for ref in refs:
            assert ref in comps,(ref,'priced reference absent from schematic')
            fields={f.get('name'):f.text or '' for f in comps[ref].findall('fields/field')}
            mpn=fields.get('MPN','')
            assert not mpn or mpn in line['part'],(ref,mpn,'price uses a different part')
        seen.update(refs);subtotal=price*len(refs);total+=subtotal
        out.append(f'{"/".join(refs):29} {len(refs):3d} {price:10.4f} {subtotal:11.4f}')
    missing=sorted(set(comps)-seen)
    out += ['',f'PRICED SUBSET: USD{total:.4f}, {len(seen)} of {len(comps)} schematic components.',
            f'UNPRICED: {len(missing)} components. Whole-board total is UNKNOWN.',
            ', '.join(missing), '', 'Each source and pricing basis is recorded in the input JSON.']
    return '\n'.join(out)+'\n'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('netlist',type=Path);parser.add_argument('snapshot',type=Path)
    parser.add_argument('--output',type=Path);args=parser.parse_args()
    result=report(args.netlist,args.snapshot)
    if args.output:args.output.write_text(result,encoding='utf-8')
    print(result,end='')
