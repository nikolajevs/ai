"""Compare the pin-to-net connectivity of two KiCad XML netlists: netdiff.py baseline.xml new.xml [replaced refs ...]

Nets are compared by connectivity, not by name: a net of the baseline must map to exactly one net of the
new netlist with the same pins (pins of removed/replaced references are ignored on both sides).
"""
import sys
import xml.etree.ElementTree as ET


def load(path):
    root = ET.parse(path).getroot()
    comps = {c.get('ref'): (c.findtext('value'), c.findtext('footprint')) for c in root.findall('.//components/comp')}
    nets = {}
    for n in root.findall('.//nets/net'):
        nets[n.get('name')] = {(p.get('ref'), p.get('pin')) for p in n}
    return comps, nets


a_comps, a_nets = load(sys.argv[1])
b_comps, b_nets = load(sys.argv[2])
removed = sorted(set(a_comps) - set(b_comps))
added = sorted(set(b_comps) - set(a_comps))
changed = sorted(r for r in set(a_comps) & set(b_comps) if a_comps[r] != b_comps[r])
print('removed refs:', removed)
print('added refs:', added)
print(f'value/footprint changed: {len(changed)}')
touched = set(removed) | set(added) | set(sys.argv[3:]) | {r for r in a_comps if r.startswith('#')}
b_by_pin = {pin: name for name, pins in b_nets.items() for pin in pins}
bad = 0
for name, pins in sorted(a_nets.items()):
    keep = {p for p in pins if p[0] not in touched}
    if not keep:
        continue
    targets = {b_by_pin.get(p) for p in keep}
    if len(targets) != 1:
        print('NET SPLIT/MOVED', name, sorted(keep), targets)
        bad += 1
        continue
    t = targets.pop()
    new_keep = {p for p in b_nets[t] if p[0] not in touched}
    if new_keep != keep:
        print('NET CHANGED', name, '->', t, 'lost', sorted(keep - new_keep), 'gained', sorted(new_keep - keep))
        bad += 1
print('connectivity differences among untouched pins:', bad)
