"""Create the unrouted cheap-1 board from the PCB_V1 placement and the cheap-1 netlist (KiCad Python).

  kicad-cli sch export netlist --format kicadxml -o netlist.xml pcb/cheap-version/cheap-version.kicad_sch
  "C:/Program Files/KiCad/10.0/bin/python.exe" pcb/cheap-version/tools/make_board.py netlist.xml [--keep-placement-of cheap-version.kicad_pcb]

Starting point is the PCB_V1 board with all copper (tracks, vias, zones) removed; stack-up, outline, silk and net
classes stay. Every footprint is synchronised with the netlist like "Update PCB from Schematic":
  * references that no longer exist are removed (R906);
  * a footprint whose library id changed is replaced in place (position, rotation and side kept);
  * values, fields, schematic paths and pad nets are refreshed.
Writes pcb/cheap-version/cheap-version.kicad_pcb and refuses to overwrite a board that has copper.
"""
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pcbnew as p

HERE = Path(__file__).resolve().parents[1]
SOURCE = HERE.parent / "PCB_V1" / "PCB_V1.kicad_pcb"
OUT = HERE / "cheap-version.kicad_pcb"
stock = Path(os.environ.get("KICAD10_FOOTPRINT_DIR", r"C:\Program Files\KiCad\10.0\share\kicad\footprints"))

netlist = Path(sys.argv[1])
if OUT.exists():
    old = p.LoadBoard(str(OUT))
    if len(old.GetTracks()) or old.GetAreaCount():
        raise SystemExit("cheap-version.kicad_pcb already has copper: not overwriting")

board = p.LoadBoard(str(SOURCE))
GRAVEYARD = []          # removed items stay referenced: destroying their Python proxies breaks later pcbnew calls
for item in list(board.GetTracks()) + list(board.Zones()):
    board.Remove(item)
    GRAVEYARD.append(item)

root = ET.parse(netlist).getroot()
comps = {c.get("ref"): c for c in root.findall("./components/comp")}
root_uuid = re.search(r'\(uuid "([^"]+)"', (HERE / "cheap-version.kicad_sch").read_text(encoding="utf-8")).group(1)


def lib_id(fp):
    fpid = fp.GetFPID()
    return f"{fpid.GetLibNickname()}:{fpid.GetLibItemName()}"


def load(fpid):
    nick, name = fpid.split(":", 1)
    lib = HERE / "libraries" / "GrowBox.pretty" if nick == "GrowBox" else stock / f"{nick}.pretty"
    fp = p.FootprintLoad(str(lib), name)
    assert fp, f"footprint not found: {fpid}"
    fp.SetFPID(p.LIB_ID(nick, name))
    return fp


existing = {f.GetReference() for f in board.GetFootprints()}
staging_y = 215.0
removed = sorted(ref for ref in existing if ref not in comps)
for ref in removed:
    item = board.FindFootprintByReference(ref)
    board.Delete(item)
added, replaced, slot = [], [], 0
for ref, comp in sorted(comps.items()):
    fpid = comp.findtext("footprint")
    old = board.FindFootprintByReference(ref) if ref in existing else None
    if old is None or lib_id(old) != fpid:
        fp = load(fpid)
        fp.SetReference(ref)
        board.Add(fp)         # Flip needs the board's layer stack: add before flipping
        if old is not None:
            pos, orient, flipped = p.VECTOR2I(old.GetPosition()), old.GetOrientation(), old.IsFlipped()
            board.Delete(old)
            fp.SetPosition(pos)
            if flipped:
                fp.Flip(pos, False)
            fp.SetOrientation(orient)
            replaced.append(ref)
        else:
            fp.SetPosition(p.VECTOR2I(p.FromMM(175 + (slot % 5) * 50), p.FromMM(staging_y + (slot // 5) * 50)))
            slot += 1
            added.append(ref)
    fp = board.FindFootprintByReference(ref)
    fp.SetReference(ref)
    fp.SetValue(comp.findtext("value"))
    fields = {f.get("name"): f.text or "" for f in comp.findall("fields/field")}
    metadata = {k: fields.get(k, "") for k in ("Manufacturer", "MPN", "LCSC")}
    metadata["Datasheet"] = comp.findtext("datasheet", "")
    for key, value in metadata.items():
        if value or fp.HasField(key):
            fp.SetField(key, value)
            fp.GetField(key).SetVisible(False)
    path = p.KIID_PATH()
    for u in [root_uuid] + [u for u in comp.find("sheetpath").get("tstamps").split("/") if u] + [comp.findtext("tstamps")]:
        path.push_back(p.KIID(u))
    fp.SetPath(path)

fps = {f.GetReference(): f for f in board.GetFootprints()}
for fp in fps.values():
    for pad in fp.Pads():
        pad.SetNetCode(0)
used = set()
for net in root.findall("./nets/net"):
    name = net.get("name")
    info = board.FindNet(name)
    if info is None:
        info = p.NETINFO_ITEM(board, name)
        board.Add(info)
    used.add(name)
    for node in net.findall("node"):
        pads = [pad for pad in fps[node.get("ref")].Pads() if pad.GetNumber() == node.get("pin")]
        assert pads, (node.attrib, "missing footprint pad")
        for pad in pads:
            pad.SetNet(info)
stale = [n for n in list(board.GetNetsByName().keys()) if str(n) and str(n) not in used]
for name in stale:
    board.Remove(board.FindNet(str(name)))

tb = board.GetTitleBlock()
tb.SetRevision("cheap-1-DRAFT")
tb.SetDate("2026-10-03")
board.SetTitleBlock(tb)

p.SaveBoard(str(OUT), board)
check = p.LoadBoard(str(OUT))
assert {f.GetReference() for f in check.GetFootprints()} == set(comps)
print(f"Removed {len(removed)}: {' '.join(removed)}")
print(f"Replaced {len(replaced)}: {' '.join(replaced)}")
print(f"Added {len(added)}: {' '.join(added)}")
print(f"Dropped {len(stale)} stale nets; board has {len(comps)} footprints, no copper")
print("texts:", [t.GetText() for t in check.GetDrawings() if isinstance(t, p.PCB_TEXT)])
