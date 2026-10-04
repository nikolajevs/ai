"""Create the extra footprints of cheap-1 in libraries/GrowBox.pretty; SPDX-License-Identifier: MIT.

Run with KiCad's bundled Python (it needs pcbnew):
    "C:/Program Files/KiCad/10.0/bin/python.exe" hardware/cheap-version/tools/make_footprints.py

Diodes_PowerDI5: Diodes Inc. SBRT15U100SP5 (DS36524 Rev. 9-2, package outline and suggested pad layout).
Pad 1 = cathode (large pad: exposed pad and tab), pad 2 (two pads) = anode, so that it fits Device:D_Schottky
(K = 1, A = 2) like the TO-277A footprint of PCB_V1.
"""
import sys
from pathlib import Path

import pcbnew as p

LIB = Path(__file__).resolve().parents[1] / "libraries" / "GrowBox.pretty"
mm = p.FromMM


def v(x, y):
    return p.VECTOR2I(mm(x), mm(y))


def pad(fp, number, x, y, w, h):
    pd = p.PAD(fp)
    pd.SetNumber(number)
    pd.SetAttribute(p.PAD_ATTRIB_SMD)
    pd.SetShape(p.PAD_SHAPE_ROUNDRECT)
    pd.SetRoundRectRadiusRatio(0.1)
    pd.SetSize(v(w, h))
    pd.SetPosition(v(x, y))
    pd.SetLayerSet(p.PAD.SMDMask())
    fp.Add(pd)


def line(fp, layer, x0, y0, x1, y1, width):
    s = p.PCB_SHAPE(fp)
    s.SetShape(p.SHAPE_T_SEGMENT)
    s.SetStart(v(x0, y0))
    s.SetEnd(v(x1, y1))
    s.SetLayer(layer)
    s.SetWidth(mm(width))
    fp.Add(s)


def rect(fp, layer, x0, y0, x1, y1, width):
    for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
        line(fp, layer, a[0], a[1], b[0], b[1], width)


def powerdi5():
    fp = p.FOOTPRINT(p.BOARD())
    fp.SetFPID(p.LIB_ID("GrowBox", "Diodes_PowerDI5"))
    fp.SetAttributes(p.FP_SMD)
    fp.SetReference("REF**")
    fp.SetValue("Diodes_PowerDI5")
    # suggested pad layout: X1 x Y1 cathode pad, two X x Y anode pads, pitch C, gap G
    x1, y1, x, y, c, g = 3.36, 4.86, 1.39, 1.40, 1.84, 0.852
    top = -(y1 + g + y) / 2
    pad(fp, "1", 0, top + y1 / 2, x1, y1)
    pad(fp, "2", -c / 2, top + y1 + g + y / 2, x, y)
    pad(fp, "2", c / 2, top + y1 + g + y / 2, x, y)
    # body 3.966 x 6.504 (D x E) on Fab, outline on silk clear of the pads, cathode side marked by a bar
    rect(fp, p.F_Fab, -1.983, -3.252, 1.983, 3.252, 0.1)
    line(fp, p.F_SilkS, -2.15, -3.7, -2.15, 3.7, 0.12)
    line(fp, p.F_SilkS, 2.15, -3.7, 2.15, 3.7, 0.12)
    line(fp, p.F_SilkS, -2.15, -3.85, 2.15, -3.85, 0.12)
    rect(fp, p.F_CrtYd, -2.35, -3.95, 2.35, 3.95, 0.05)
    fp.Reference().SetPosition(v(0, -4.8))
    fp.Reference().SetLayer(p.F_SilkS)
    fp.Value().SetPosition(v(0, 4.8))
    fp.Value().SetLayer(p.F_Fab)
    add_model(fp, "Diodes_PowerDI5")
    return fp


def add_model(fp, name):
    m = p.FP_3DMODEL()
    m.m_Filename = "${KIPRJMOD}/libraries/GrowBox.3dshapes/" + name + ".step"
    fp.Add3DModel(m)


def tht_pad(fp, number, x, y, size, drill):
    pd = p.PAD(fp)
    pd.SetNumber(number)
    pd.SetAttribute(p.PAD_ATTRIB_PTH)
    pd.SetShape(p.PAD_SHAPE_CIRCLE)
    pd.SetSize(v(size, size))
    pd.SetDrillSize(v(drill, drill))
    pd.SetPosition(v(x, y))
    pd.SetLayerSet(p.PAD.PTHMask())
    fp.Add(pd)


def dtmss27():
    """Feryster DTMSS-27/0.047/15-V (mounting V): leads D = 1.9 mm, E = 17.5 mm apart, ring on edge A x C = 32.5 x 16."""
    fp = p.FOOTPRINT(p.BOARD())
    fp.SetFPID(p.LIB_ID("GrowBox", "L_Feryster_DTMSS-27_V"))
    fp.SetAttributes(p.FP_THROUGH_HOLE)
    fp.SetReference("REF**")
    fp.SetValue("L_Feryster_DTMSS-27_V")
    tht_pad(fp, "1", -8.75, 0, 4.2, 2.4)
    tht_pad(fp, "2", 8.75, 0, 4.2, 2.4)
    rect(fp, p.F_Fab, -8.0, -16.25, 8.0, 16.25, 0.1)          # body A x C, nominal
    rect(fp, p.F_SilkS, -9.0, -17.25, 9.0, 17.25, 0.12)       # +10 % tolerance, clear of the pads' annular rings
    rect(fp, p.F_CrtYd, -11.1, -18.1, 11.1, 18.1, 0.05)
    fp.Reference().SetPosition(v(0, -19.5))
    fp.Reference().SetLayer(p.F_SilkS)
    fp.Value().SetPosition(v(0, 19.5))
    fp.Value().SetLayer(p.F_Fab)
    add_model(fp, "L_Feryster_DTMSS-27_V")
    return fp


def main():
    for fp in (powerdi5(), dtmss27()):
        p.FootprintSave(str(LIB), fp)
        print("saved", LIB / (str(fp.GetFPID().GetLibItemName()) + ".kicad_mod"))


if __name__ == "__main__":
    sys.exit(main())
