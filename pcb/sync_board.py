"""Synchronise the UNROUTED staging board with a checked KiCad XML netlist.

Run with KiCad's bundled Python:
  kicad-cli sch export netlist --format kicadxml -o netlist.xml PCB_V1/PCB_V1.kicad_sch
  python sync_board.py netlist.xml PCB_V1/PCB_V1.kicad_pcb

Equivalent of "Update PCB from Schematic" for the staging phase:
- footprints whose reference disappeared from the schematic are removed;
- a footprint whose library id changed is replaced in place (position/rotation kept);
- new footprints are staged in a free row below the existing groups;
- values and schematic instance paths are refreshed, every pad net is reassigned
  from the netlist and nets that no longer exist are dropped.
Refuses to touch a board that already has tracks, vias or zones: once routing starts,
use KiCad's own Update PCB from Schematic.
"""
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pcbnew as p

netlist_path, board_path = map(Path, sys.argv[1:3])
project = board_path.parent
stock = Path(os.environ.get('KICAD10_FOOTPRINT_DIR', r'C:\Program Files\KiCad\10.0\share\kicad\footprints'))

board = p.LoadBoard(str(board_path))
assert len(board.GetTracks()) == 0 and board.GetAreaCount() == 0, 'board has routing; use KiCad Update PCB'
root = ET.parse(netlist_path).getroot()
comps = {c.get('ref'): c for c in root.findall('./components/comp')}
root_uuid = re.search(r'\(uuid "([^"]+)"', (project / 'PCB_V1.kicad_sch').read_text(encoding='utf-8')).group(1)


def lib_id(fp):
    fpid = fp.GetFPID()
    return f'{fpid.GetLibNickname()}:{fpid.GetLibItemName()}'


def load(fpid):
    nick, name = fpid.split(':', 1)
    lib = project / 'libraries' / 'GrowBox.pretty' if nick == 'GrowBox' else stock / f'{nick}.pretty'
    fp = p.FootprintLoad(str(lib), name)
    assert fp, f'footprint not found: {fpid}'
    fp.SetFPID(p.LIB_ID(nick, name))
    return fp


fps = {f.GetReference(): f for f in board.GetFootprints()}
staging_y = max(p.ToMM(f.GetPosition()[1]) for f in fps.values()) + 60
existing = set(fps)
del fps  # SWIG proxies become unreliable once the footprint list changes; look up by reference.
removed = sorted(ref for ref in existing if ref not in comps)
for ref in removed:
    board.Delete(board.FindFootprintByReference(ref))
added, replaced, slot = [], [], 0
for ref, comp in sorted(comps.items()):
    fpid = comp.findtext('footprint')
    old = board.FindFootprintByReference(ref) if ref in existing else None
    if old is None or lib_id(old) != fpid:
        fp = load(fpid)
        if old is not None:
            pos, orient = p.VECTOR2I(old.GetPosition()), old.GetOrientation()
            board.Delete(old)
            fp.SetPosition(pos)
            fp.SetOrientation(orient)
            replaced.append(ref)
        else:
            fp.SetPosition(p.VECTOR2I(p.FromMM(175 + (slot % 5) * 50), p.FromMM(staging_y + (slot // 5) * 50)))
            slot += 1
            added.append(ref)
        fp.SetReference(ref)
        board.Add(fp)
    fp = board.FindFootprintByReference(ref)
    fp.SetReference(ref)
    fp.SetValue(comp.findtext('value'))
    path = p.KIID_PATH()
    for u in [root_uuid] + [u for u in comp.find('sheetpath').get('tstamps').split('/') if u] + [comp.findtext('tstamps')]:
        path.push_back(p.KIID(u))
    fp.SetPath(path)

fps = {f.GetReference(): f for f in board.GetFootprints()}
for fp in fps.values():
    for pad in fp.Pads():
        pad.SetNetCode(0)
used = set()
for net in root.findall('./nets/net'):
    name = net.get('name')
    info = board.FindNet(name)
    if info is None:
        info = p.NETINFO_ITEM(board, name)
        board.Add(info)
    used.add(name)
    for node in net.findall('node'):
        pads = [pad for pad in fps[node.get('ref')].Pads() if pad.GetNumber() == node.get('pin')]
        assert pads, (node.attrib, 'missing footprint pad')
        for pad in pads:
            pad.SetNet(info)
stale = [n for n in list(board.GetNetsByName().keys()) if str(n) and str(n) not in used]
for name in stale:
    board.Remove(board.FindNet(str(name)))

p.SaveBoard(str(board_path), board)
check = p.LoadBoard(str(board_path))
assert {f.GetReference() for f in check.GetFootprints()} == set(comps)
print(f'Removed {len(removed)}: {" ".join(removed)}')
print(f'Replaced {len(replaced)}: {" ".join(replaced)}')
print(f'Added {len(added)}: {" ".join(added)}')
print(f'Dropped {len(stale)} stale nets; board now {len(comps)} footprints, no tracks')
