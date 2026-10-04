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
    part(sh, "R907", value="470k 1%", mpn="0603WAF4703T5E", lcsc="C23178")          # EN2 threshold 1.5 V: on from about 16.5 V
    part(sh, "R904", value="88.7k 0.1%", mpn="RT0603BRD0788K7L", lcsc="C728599", source="buy")  # 12.06 V at VFB 1.222 V
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
    # 04.10.2026: local HF bypass at the ST1S14 VIN pin. The route from the input capacitors to pin 7 is about 15 mm with
    # two vias (B.Cu in between); the cap sits on the bottom side right under the pin, GND via beside it (add_c911.py)
    c907 = {k: v for k, v in sh.props("C907").items() if k != "Reference"}
    sh.add_symbol("Device:C", "C911", (86.36, 124.46), 0, c907, {"1": "AUX_VIN", "2": "GND"},
                  pos_ref=(90.17, 123.19), pos_value=(90.17, 125.73), global_nets=sh.global_net_names())
    use(sh, "J901", {**KF301, "footprint": "GrowBox:TerminalBlock_KF301_1x02_P5.00mm_Horizontal_Input"}, value="24V IN (KF301-5.0-2P)")
    sh.prune_lib_symbols()
    return sh


def heater():
    sh = load("Heater")
    # 04.10.2026: back to the PCB_V1 driver UCC27524ADR (the IRS4427S input threshold left 0.14 V of margin);
    # pin 1 (ENA) goes to +12V instead of +3V3, pin 8 (ENB) to GND, OUTB unused
    replace_symbol(
        sh, "U601", "Driver_FET:UCC27524D", None,
        lambda o: {**o, "1": "+12V", "5": None},
        dict(Value="UCC27524ADR", Footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
             Datasheet="https://www.ti.com/lit/ds/symlink/ucc27524a.pdf", Manufacturer="TI",
             MPN="UCC27524ADR", LCSC="C185857", Source="buy"))
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
    part(sh, "L711", value="47u DTMSS-27/0.047/15-V", footprint="GrowBox:L_Feryster_DTMSS-27_V", mpn="DTMSS-27/0.047/15-V",
         mfr="Feryster", lcsc="", source="stock:12")
    part(sh, ["D711", "D721"], value="SBRT15U100SP5", footprint="GrowBox:Diodes_PowerDI5", mpn="SBRT15U100SP5-13",
         mfr="Diodes Incorporated", lcsc="C2934601", source="stock:8",
         datasheet="https://www.diodes.com/assets/Datasheets/SBRT15U100SP5.pdf")
    part(sh, "R716", value="0.12 1% 3W 50ppm", mpn="JER2512F3R120", mfr="JIERR", lcsc="C49164917", datasheet="https://datasheet.lcsc.com/datasheet/pdf/02ae4b20613551dea68a63964573e262.pdf")   # CH1 80 W (04.10.2026; 0.18 ohm = 53 W)
    sh.replace_text("CH1: 1.111 A", "CH1: 1.667 A nominal = 80 W at 48 V (panel rated up to 120 W)")
    use(sh, ["C710", "C715", "C725"], C1210_10U50)
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


ROOT_NETS = {   # the 3.3 V sheet: pin number -> net (labels without a leading slash are global)
    "C101": {"1": "+12V", "2": "GND"}, "C102": {"1": "+12V", "2": "GND"}, "C103": {"1": "+12V", "2": "GND"},
    "C104": {"1": "+3V3", "2": "GND"}, "C105": {"1": "+3V3", "2": "GND"}, "C106": {"1": "+3V3", "2": "BUCK_FB"},
    "L101": {"1": "BUCK_SW", "2": "+3V3"}, "R101": {"1": "+3V3", "2": "BUCK_FB"}, "R102": {"1": "BUCK_FB", "2": "GND"},
    "TP101": {"1": "+12V"}, "TP102": {"1": "+3V3"}, "TP103": {"1": "GND"},
    "#FLG0101": {"1": "+12V"}, "#FLG0102": {"1": "GND"}, "#FLG0103": {"1": "+3V3"},
}


def root():
    """U101: ST1S10PHR (INH to VIN = on, SYNC to GND = 900 kHz, no bootstrap) instead of TPS54202."""
    sh = load("cheap-version")
    st1s10 = load_stock_symbol(SYM_DIR / "Regulator_Switching.kicad_sym", "ST1S10PHR", "Regulator_Switching")
    X, Y, rot = sh.instance_transform(sh.text[slice(*sh.symbol("U101"))])[1:4]
    pos_ref, pos_value = sh.prop_pos("U101", "Reference"), sh.prop_pos("U101", "Value")
    # this sheet was drawn with plain wires: redraw it in the stub-and-label style of the other sheets
    sh.delete_blocks({"wire", "junction", "label", "global_label", "no_connect"})
    sh.remove_symbol("U101")
    sh.ensure_lib_symbol("Regulator_Switching:ST1S10PHR", st1s10)
    globals_ = {"+12V", "+3V3", "GND"}
    sh.add_symbol(
        "Regulator_Switching:ST1S10PHR", "U101", (X, Y), rot,
        dict(Value="ST1S10PHR", Footprint="Package_SO:SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.41x3.3mm",
             Datasheet="https://www.st.com/resource/en/datasheet/st1s10.pdf", Manufacturer="STMicroelectronics",
             MPN="ST1S10PHR", LCSC="C11175", Source="stock:27"),
        {"1": "+12V", "2": "+12V", "3": "BUCK_FB", "4": "GND", "5": "GND", "6": "+12V", "7": "BUCK_SW", "8": "GND", "9": "GND"},
        pos_ref=pos_ref, pos_value=pos_value, global_nets=globals_)
    for ref, nets in ROOT_NETS.items():
        sh.attach_stubs(ref, nets, globals_)
    use(sh, "C101", C1210_10U35)                      # VIN_SW: 10 uF or more with 47..100 uF on the output
    use(sh, "C102", C0603_100N)
    use(sh, "C103", C0805_2U2_16)                     # was the BOOT capacitor; now the VIN_A bypass (1 uF or more)
    use(sh, ["C104", "C105"], C0805_22U10)
    use(sh, "R101", R0603_100K)
    part(sh, "R102", value="31.6k 1%", mpn="0603WAF3162T5E", lcsc="C25967", source="buy")   # 3.33 V at VFB 0.8 V
    part(sh, "L101", value="4.7u FXL0630-4R7-M", mpn="FXL0630-4R7-M", lcsc="C167220")  # same 7x6.6 mm package as the 10 uH part
    sh.replace_text("Vout = 0.596", "Vout = 0.8 V x (1 + 100k/31.6k) = 3.33 V (ST1S10 VFB 0.784..0.816 V); dividers 1%.\\n"
                    "ST1S10: 2.5..18 V in, 3 A, synchronous, 900 kHz (SYNC to GND), INH tied to VIN (on), no BOOT.\\n"
                    "L101 FXL0630-4R7-M: 4.7 uH, Isat 9 A, DCR 33 mOhm; C103 is the VIN_A bypass.\\n"
                    "Cout 3 x 22u/10V X5R (C104, C105, C401); verify load-step response. C106 is NOT fitted.")
    sh.replace_text("EN ", "INH (EN) соединён с +12V: регулятор включён всегда.\\nSYNC на GND: 900 кГц без внешней синхронизации.")
    sh.replace_text("0.22 DRAFT", "cheap-1 DRAFT: schematic derived from PCB_V1 0.22 with stock-part substitutions; unrouted.")
    sh.prune_lib_symbols()
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
