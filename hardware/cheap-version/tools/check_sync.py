"""Schematic <-> board net check, pin by pin (KiCad Python): check_sync.py netlist.xml board.kicad_pcb

netlist.xml: kicad-cli sch export netlist --format kicadxml -o netlist.xml cheap-version.kicad_sch
Every pin of the netlist must sit on the same net on the board (nets named unconnected-* count as no net). Pads without a
number (exposed pads that are not pins) are skipped. Exit code 1 on any difference.
"""
import sys
import xml.etree.ElementTree as ET

import pcbnew as p

root = ET.parse(sys.argv[1]).getroot()
sch = {}
for net in root.findall('.//nets/net'):
    for node in net.findall('node'):
        sch[(node.get('ref'), node.get('pin'))] = net.get('name')
board = p.LoadBoard(sys.argv[2])
brd = {}
for fp in board.GetFootprints():
    for pad in fp.Pads():
        if pad.GetNumber():
            brd[(fp.GetReference(), pad.GetNumber())] = pad.GetNetname()
bad = 0
for key in sorted(set(sch) | set(brd)):
    s, b = sch.get(key), brd.get(key)
    s = None if s and s.startswith('unconnected-') else s
    b = None if b and b.startswith('unconnected-') else b
    if s != b:
        bad += 1
        print(f'DIFF {key}: schematic {s}, board {b}')
print(f'{len(sch)} schematic pins, {sum(1 for v in brd.values() if v and not v.startswith("unconnected-"))} board pads with a net, {bad} difference(s)')
sys.exit(1 if bad else 0)
