#!/usr/bin/env python3
"""Generate the cheap-1 schematic from the PCB_V1 rev 0.22 baseline; SPDX-License-Identifier: MIT.

Usage (any Python 3.9+, no KiCad modules needed):
    python pcb/cheap-version/tools/make_cheap1.py

Reads ../PCB_V1/*.kicad_sch and ../PCB_V1/libraries/GrowBox.kicad_sym, applies the substitutions from
README.md (parts from the user's stock, stock id in the "Source" field) and writes the sheets and the
GrowBox symbol library into pcb/cheap-version/. Every run starts from the baseline, so manual edits made
in KiCad to the sheets are overwritten: stop using the script once the schematic is edited by hand.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sch_edit import Sheet, load_stock_symbol  # noqa: E402

HERE = Path(__file__).resolve().parents[1]
V1 = HERE.parent / "PCB_V1"
SYM_DIR = Path(os.environ.get("KICAD10_SYMBOL_DIR", r"C:\Program Files\KiCad\10.0\share\kicad\symbols"))
SHEETS = ["Heater", "InputPower", "LEDDrivers", "MCU", "Outputs", "Peripherals"]

# ---------------------------------------------------------------- stock parts (id from stock/components-20261003.csv)
R0805_10K = dict(value="10k 5%", footprint="Resistor_SMD:R_0805_2012Metric", mpn="", mfr="", lcsc="", source="stock:70")
R0805_10K1 = dict(value="10k 1%", footprint="Resistor_SMD:R_0805_2012Metric", mpn="", mfr="", lcsc="", source="stock:59")
R0805_4K7 = dict(value="4.7k 5%", footprint="Resistor_SMD:R_0805_2012Metric", mpn="", mfr="", lcsc="", source="stock:72")
R0603_100K = dict(value="100k 1%", mpn="RC0603FR-07100KL", mfr="Yageo", lcsc="C14675", source="stock:55")
R0603_1K = dict(value="1k 1%", mpn="RC0603FR-071KL", mfr="Yageo", lcsc="C21190", source="stock:62")
R1206_10R = dict(value="10R 5%", footprint="Resistor_SMD:R_1206_3216Metric", mpn="", mfr="", lcsc="", source="stock:41")
R1206_47K = dict(value="47k 1%", footprint="Resistor_SMD:R_1206_3216Metric", mpn="", mfr="", lcsc="", source="stock:61")
C1210_10U35 = dict(value="10u 35V X5R", footprint="Capacitor_SMD:C_1210_3225Metric", mpn="CL32A106KLULNNE",
                   mfr="Samsung Electro-Mechanics", lcsc="C2980162", source="stock:6")
C1210_10U50 = dict(mpn="CL32B106KBJNNNE", mfr="Samsung Electro-Mechanics", lcsc="C92388", source="stock:47")
C1210_4U7_100 = dict(value="4.7u 100V X7R", mpn="CL32B475KCI6PJE", mfr="Samsung Electro-Mechanics", lcsc="", source="stock:2")
C1206_2U2_50 = dict(value="2.2u 50V X7R", footprint="Capacitor_SMD:C_1206_3216Metric", mpn="12065C225KATM-HW", mfr="KYOCERA AVX",
                    lcsc="", source="stock:3")
C0805_2U2_16 = dict(value="2.2u 16V X5R", footprint="Capacitor_SMD:C_0805_2012Metric", mpn="CL21A225KOFNNNE",
                    mfr="Samsung Electro-Mechanics", lcsc="", source="stock:57")
C0805_22U10 = dict(mpn="CL21A226KPCLRNC", mfr="Samsung Electro-Mechanics", lcsc="C318688", source="stock:7")
C0805_10U16 = dict(value="10u 16V X5R", mpn="", mfr="", lcsc="", source="stock:58")
C0603_100N = dict(source="stock:54")
SS56 = dict(value="SS56", mpn="SS56", mfr="", lcsc="", source="stock:20")
KF301 = dict(footprint="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2_1x02_P5.00mm_Horizontal", mpn="KF301-5.0-2P",
             mfr="", lcsc="", source="stock:93")
FS15 = dict(footprint="TerminalBlock_Phoenix:TerminalBlock_Phoenix_PT-1,5-2-3.5-H_1x02_P3.50mm_Horizontal",
            mpn="FS1.5-02-350-2601R", mfr="", lcsc="", source="stock:86")


def load(name: str) -> Sheet:
    src = V1 / ("PCB_V1" if name == "cheap-version" else name)
    sh = Sheet(src.with_suffix(".kicad_sch"))
    sh.text = sh.text.replace('(project "PCB_V1"', '(project "cheap-version"')
    sh.text = sh.text.replace('(rev "0.22-DRAFT")', '(rev "cheap-1-DRAFT")')
    sh.text = sh.text.replace('(date "2026-09-30")', '(date "2026-10-03")')
    sh.text = sh.text.replace("Simplified prototype; unrouted; hardware qualification pending",
                              "cheap-1: one-off board from stock parts, schematic derived from PCB_V1 0.22; unrouted")
    sh.path = HERE / (name + ".kicad_sch")
    return sh


def part(sh: Sheet, refs, value=None, footprint=None, mpn=None, mfr=None, lcsc=None, source=None, datasheet=None):
    for ref in ([refs] if isinstance(refs, str) else refs):
        for key, val in (("Value", value), ("Footprint", footprint), ("MPN", mpn), ("Manufacturer", mfr),
                         ("LCSC", lcsc), ("Datasheet", datasheet), ("Source", source)):
            if val is not None:
                sh.set_prop(ref, key, val)


def use(sh: Sheet, refs, spec: dict, **override):
    part(sh, refs, **{**spec, **override})


def replace_symbol(sh: Sheet, ref: str, lib_id: str, lib_text: str | None, nets_new, props: dict):
    """remove the old instance with its stubs and put a new symbol at the same place"""
    old = sh.pin_nets(ref)
    X, Y, rot = sh.instance_transform(sh.text[slice(*sh.symbol(ref))])[1:4]
    pos_ref, pos_value = sh.prop_pos(ref, "Reference"), sh.prop_pos(ref, "Value")
    globals_ = sh.global_net_names()
    sh.remove_symbol(ref)
    if lib_text:
        sh.ensure_lib_symbol(lib_id, lib_text)
    sh.add_symbol(lib_id, ref, (X, Y), rot, props, nets_new(old), pos_ref=pos_ref, pos_value=pos_value, global_nets=globals_)


def clone_lib_symbol(sh: Sheet, old: str, new: str, repl: dict):
    s, e = sh.lib_symbol_span(old)
    blk = sh.text[s:e].replace(f'"{old}"', f'"{new}"').replace(f'"{old.split(":")[1]}_', f'"{new.split(":")[1]}_')
    for key, val in repl.items():
        blk = re.sub(r'(\(property "' + key + r'" )"[^"]*"', lambda m: m.group(1) + '"' + val + '"', blk, count=1)
    sh.ensure_lib_symbol(new, "\t\t" + blk)


# ---------------------------------------------------------------- sheets
def input_power():
    sh = load("InputPower")
    st1s14 = load_stock_symbol(SYM_DIR / "Regulator_Switching.kicad_sym", "ST1S14PHR", "Regulator_Switching")
    replace_symbol(
        sh, "U902", "Regulator_Switching:ST1S14PHR", st1s14,
        lambda o: {"1": o["1"], "2": None, "3": "GND", "4": o["5"], "5": o["3"], "6": "GND", "7": o["2"], "8": o["8"], "9": "GND"},
        dict(Value="ST1S14PHR", Footprint="Package_SO:SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.41x3.3mm",
             Datasheet="https://www.st.com/resource/en/datasheet/st1s14.pdf", Manufacturer="STMicroelectronics",
             MPN="ST1S14PHR", LCSC="C84130", Source="stock:26"))
    sh.remove_symbol("R906")                                  # no RT pin on the ST1S14
    part(sh, "R907", value="470k 1%", mpn="0603WAF4703T5E", lcsc="")          # EN2 threshold 1.5 V: on from about 16.5 V
    part(sh, "R904", value="88.7k 0.1%", mpn="RT0603BRD0788K7L", lcsc="", source="buy: verify MPN on LCSC")  # 12.06 V at VFB 1.222 V
    use(sh, "R908", R1206_47K)
    use(sh, "C909", dict(value="820u 25V", footprint="Capacitor_SMD:CP_Elec_10x10.5", mpn="EEEFT1E821AP", mfr="Panasonic",
                         lcsc="C178593", source="stock:14"))
    use(sh, "C910", C1210_10U35)
    use(sh, "C901", dict(value="470u / 63V", footprint="Capacitor_SMD:CP_Elec_16x17.5", mpn="EEVFK1J471M", mfr="Panasonic",
                         lcsc="C178728", source="stock:13"))
    use(sh, "D902", SS56)
    use(sh, ["C905", "C906"], C1210_10U50)
    use(sh, "C902", C1206_2U2_50)
    use(sh, ["C907", "C908"], C0603_100N)
    use(sh, "J901", KF301, value="24V IN (KF301-5.0-2P)")
    sh.prune_lib_symbols()
    return sh


def heater():
    sh = load("Heater")
    tc4427 = load_stock_symbol(SYM_DIR / "Driver_FET.kicad_sym", "TC4427xOA", "Driver_FET")
    replace_symbol(
        sh, "U601", "Driver_FET:TC4427xOA", tc4427,
        lambda o: {"1": None, "2": o["2"], "3": "GND", "4": "GND", "5": None, "6": o["6"], "7": o["7"], "8": None},
        dict(Value="IRS4427S", Footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", Datasheet="",
             Manufacturer="Infineon", MPN="IRS4427STRPBF", LCSC="", Source="stock:11"))
    nmos = load_stock_symbol(SYM_DIR / "Transistor_FET.kicad_sym", "Q_NMOS_GDS", "Transistor_FET")
    replace_symbol(
        sh, "Q601", "Transistor_FET:Q_NMOS_GDS", nmos,
        lambda o: {"1": o["4"], "2": o["5"], "3": "GND"},
        dict(Value="IRL2505", Footprint="Package_TO_SOT_THT:TO-220-3_Vertical", Datasheet="", Manufacturer="",
             MPN="IRL2505", LCSC="", Source="stock:78"))
    use(sh, "R601", R1206_10R)
    use(sh, "R602", R0603_100K)
    use(sh, "C602", C1210_10U35)
    use(sh, "C601", C0603_100N)
    use(sh, "J601", FS15)
    sh.prune_lib_symbols()
    return sh


def outputs():
    sh = load("Outputs")
    use(sh, "D521", SS56)
    use(sh, "C521", C1210_10U50)
    use(sh, ["R502", "R512", "R522"], R0603_100K)
    use(sh, ["R503", "R513"], R0603_1K)
    use(sh, "J521", FS15)
    for ref in ("J501", "J511"):
        part(sh, ref, footprint="Connector_Molex:Molex_KK-254_AE-6410-04A_1x04_P2.54mm_Vertical", mpn="KF2510-4P", mfr="",
             lcsc="", source="stock:87")
    return sh


def led_drivers(extra_lib: dict):
    sh = load("LEDDrivers")
    old = "GrowBox:AOD66923"
    new = "GrowBox:BSC146N10LS5"
    clone_lib_symbol(sh, old, new, dict(Value="BSC146N10LS5", Footprint="Package_TO_SOT_SMD:TDSON-8-1",
                                        Datasheet="https://www.infineon.com/dgdl/Infineon-BSC146N10LS5-DS-v02_00-EN.pdf"))
    for ref in ("Q711", "Q721"):
        sh.set_lib_id(ref, new)
        part(sh, ref, value="BSC146N10LS5", footprint="Package_TO_SOT_SMD:TDSON-8-1", mpn="BSC146N10LS5",
             mfr="Infineon Technologies", lcsc="", source="stock:112")
    part(sh, "L711", value="47u DTMSS-27/0.047/15-V", footprint="GrowBox:L_Feryster_DTMSS-27_THT", mpn="DTMSS-27/0.047/15-V",
         mfr="Feryster", lcsc="", source="stock:12")
    use(sh, ["C710", "C715", "C725"], C1210_10U50)
    use(sh, ["C716", "C717", "C718", "C719", "C726", "C727", "C728"], C1210_4U7_100)
    use(sh, ["C711", "C721"], C1206_2U2_50)
    use(sh, ["R711", "R721"], R1206_10R)
    use(sh, "R703", R1206_47K)
    use(sh, ["R712"], R0603_1K)
    use(sh, ["R713", "R723"], R0603_100K)
    use(sh, ["R714", "R724"], R0805_10K)
    use(sh, ["R718", "R728"], R0805_10K1)
    use(sh, "C700", C0603_100N)
    for ref in ("J711", "J721", "J731"):
        use(sh, ref, KF301)
    sh.prune_lib_symbols()
    extra_lib["BSC146N10LS5"] = ("AOD66923", dict(Value="BSC146N10LS5", Footprint="Package_TO_SOT_SMD:TDSON-8-1",
                                                  Datasheet="https://www.infineon.com/dgdl/Infineon-BSC146N10LS5-DS-v02_00-EN.pdf"))
    return sh


def peripherals():
    sh = load("Peripherals")
    use(sh, ["R301", "R302"], R0805_4K7)
    use(sh, ["R305", "R307"], R0603_1K)
    use(sh, "R306", R0805_10K)
    use(sh, ["R405", "R406", "R407", "R408", "R410"], R0805_10K)
    use(sh, "C401", C0805_22U10)
    use(sh, "C302", C0805_2U2_16)
    use(sh, ["C301", "C303", "C402"], C0603_100N)
    use(sh, "J302", FS15)
    part(sh, "J301", footprint="Connector_JST:JST_XH_S4B-XH-A_1x04_P2.50mm_Horizontal", mpn="XH2.54-4P-90", mfr="", lcsc="",
         source="stock:90")
    return sh


def mcu():
    sh = load("MCU")
    use(sh, ["R201", "R202", "R203", "R207", "R208", "R209", "R210", "R211", "R212"], R0805_10K)
    use(sh, ["R204", "R205", "R206"], R0603_1K)
    use(sh, "C201", C0805_10U16)
    use(sh, "C203", C0805_2U2_16)
    use(sh, "C202", C0603_100N)
    for ref in ("SW201", "SW202"):
        part(sh, ref, footprint="Button_Switch_THT:SW_PUSH_6mm_H9.5mm", mpn="6X6X10MM Tact Switch", mfr="", lcsc="", source="stock:95")
    return sh


def root():
    sh = load("cheap-version")
    use(sh, "C101", C1210_10U35)
    use(sh, ["C104", "C105"], C0805_22U10)
    use(sh, ["C102", "C103"], C0603_100N)
    use(sh, "R101", R0603_100K)
    return sh


def library(extra_lib: dict):
    text = (V1 / "libraries" / "GrowBox.kicad_sym").read_text(encoding="utf-8")
    for new, (old, props) in extra_lib.items():
        i = text.index(f'(symbol "{old}"')
        depth, j, in_str = 0, i, False
        while True:
            c = text[j]
            if in_str:
                if c == "\\":
                    j += 1
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        blk = text[i:j + 1].replace(f'(symbol "{old}"', f'(symbol "{new}"').replace(f'"{old}_', f'"{new}_')
        for key, val in props.items():
            blk = re.sub(r'(\(property "' + key + r'" )"[^"]*"', lambda m: m.group(1) + '"' + val + '"', blk, count=1)
        close = text.rstrip().rindex(")")
        k = close
        while text[k - 1] == "\t":
            k -= 1
        text = text[:k] + "\t" + blk + "\n" + text[k:]
    (HERE / "libraries" / "GrowBox.kicad_sym").write_text(text, encoding="utf-8", newline="\n")


def main():
    extra_lib: dict = {}
    sheets = [input_power(), heater(), outputs(), led_drivers(extra_lib), peripherals(), mcu(), root()]
    for sh in sheets:
        sh.save()
        print(f"{sh.path.name}: pins ok/unconnected {sh.check_pins()}")
    library(extra_lib)


if __name__ == "__main__":
    main()
