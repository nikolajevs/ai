"""Board side of the 04.10.2026 schematic changes (KiCad Python): swap_heater_driver.py board.kicad_pcb [--write]

* U601 is the UCC27524ADR again (as in PCB_V1) instead of the IRS4427S: pin 1 (ENA) tied to +12V (VDD; a +3V3 via does
  not fit beside the pin, TI: tie an unused ENx to VDD) by a stub to the +12V track 0.2 mm away, pin 8 (ENB) to GND;
  value and part fields of the footprint follow the schematic;
* R716 (CH1 shunt) 0.12 ohm, 80 W at 48 V: only its value/MPN change on the board.
Repeatable: pads, fields and the stage's own stub are set to the same state every time.
"""
import sys
from pathlib import Path
import route_power as rp

p = rp.p
U601_FIELDS = dict(Value='UCC27524ADR', Manufacturer='TI', MPN='UCC27524ADR', LCSC='C185857', Source='buy',
                   Datasheet='https://www.ti.com/lit/ds/symlink/ucc27524a.pdf')
R716_FIELDS = dict(Value='0.12 1% 3W 50ppm', MPN='JER2512F3R120', Manufacturer='JIERR', LCSC='C49164917', Datasheet='https://datasheet.lcsc.com/datasheet/pdf/02ae4b20613551dea68a63964573e262.pdf')
PAD1 = (83.41, 89.78)
STUB = [(83.5, 90.3), (84.3, 90.79)]     # inside pad 1 -> onto the +12V track (82.84,92.25)-(85.38,89.71)


def set_fields(fp, fields):
    """Value and the part fields the footprint already carries (the board has no 'Source' field)"""
    for key, val in fields.items():
        if key == 'Value':
            fp.SetValue(val)
        elif fp.HasField(key):
            fp.GetField(key).SetText(val)


def apply(board):
    u = board.FindFootprintByReference('U601')
    assert u is not None
    pads = {pad.GetNumber(): pad for pad in u.Pads()}
    assert len(pads) == 8 and abs(p.ToMM(pads['1'].GetPosition().x) - PAD1[0]) < 0.01 and \
        abs(p.ToMM(pads['1'].GetPosition().y) - PAD1[1]) < 0.01, 'U601 moved'
    pads['1'].SetNet(rp.net(board, '+12V'))
    pads['8'].SetNet(rp.net(board, 'GND'))
    for number in ('1', '8'):
        pads[number].SetLocalZoneConnection(p.ZONE_CONNECTION_FULL)
    set_fields(u, U601_FIELDS)
    set_fields(board.FindFootprintByReference('R716'), R716_FIELDS)
    for t in list(board.GetTracks()):          # this stage's own stub, for a repeated run
        if (not isinstance(t, p.PCB_VIA) and t.GetNetname() == '+12V' and t.GetLayer() == p.F_Cu
                and abs(p.ToMM(t.GetStart().x) - STUB[0][0]) < 0.01 and abs(p.ToMM(t.GetStart().y) - STUB[0][1]) < 0.01):
            rp.discard(board, t)
    rp.add_track(board, '+12V', 'F.Cu', 0.25, STUB)
    p.ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()


if __name__ == '__main__':
    board = rp.load_board(sys.argv[1])
    apply(board)
    print('unrouted', board.GetConnectivity().GetUnconnectedCount(False))
    if '--write' in sys.argv:
        p.SaveBoard(sys.argv[1], board)
        path = Path(sys.argv[1])
        path.write_text(path.read_text(encoding='utf-8'), encoding='utf-8', newline='\n')
