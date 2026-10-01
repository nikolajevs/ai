# GrowBox controller PCB

Hardware source of truth: `PCB_V1/PCB_V1.kicad_pro` (KiCad 10). All hardware changes belong in this directory.

**Revision 0.22** — 24 V input on a keyed XT60PW-M (no electronic reverse-polarity protection), LMR16020 12 V auxiliary buck (fans, heater gate driver, AL8853 bias, 3.3 V buck), 24 V/100 W PTC, 24 V pump, two AL8853 constant-current LED channels (panel; two paralleled bars) with common dimming, seven fused load branches, PCF8563 RTC with CR2032 backup. 170 components (four of them copper-only net ties). ERC 0/0, DRC 0 violations; all components are now placed on the 100 x 100 mm board, with twelve edge connectors and a bottom battery holder. Manufacturing rules are set and the stack is confirmed (1.6 mm, 1 oz outer, 0.5 oz inner). The board is prepared for routing, which has not started (341 unconnected links); **not ready for fabrication**. Components: USD 30.04 per board (USD 28.42 each for five) at dated LCSC list prices (base snapshot 2026-09-28; 0.18/0.19 substitutions 2026-09-29; 0.20-0.22 parts 2026-09-30). Revision 0.22 prepares routing: Murata LED output MLCCs, HRO TF-01A microSD, RTC CLKOUT test pad, Kelvin net ties at the four LED-driver shunts and a copper screen for the confirmed stack: [PCB_V1/ROUTING_PREP.md](PCB_V1/ROUTING_PREP.md). Revision 0.21 replaces the RTC supply OR diode with low-leakage JSCJ BAV170; the higher forward drop is checked at 25 C, while temperature, battery leakage and supply transitions still require a prototype: [PCB_V1/RTC_BACKUP_021.md](https://github.com/nikolajevs/ai/blob/1887d866ac820a41e9d1717056d188d7af6e6b51/pcb/PCB_V1/RTC_BACKUP_021.md). Revision 0.20 changed the RTC (DS3231MZ to PCF8563T + crystal; the firmware detects either), the boost switches/diodes (AOD66923 DPAK, SS5P10 TO-277A) and both small power inductors, with new footprints and a re-placed LED switch area: [PCB_V1/COST_DOWN_020.md](https://github.com/nikolajevs/ai/blob/1887d866ac820a41e9d1717056d188d7af6e6b51/pcb/PCB_V1/COST_DOWN_020.md). All checks pass. First boards will be hand assembled; all SMT parts are on the top side.

- Routing preparation 0.22 (parts, net ties, copper, routing rules): [PCB_V1/ROUTING_PREP.md](PCB_V1/ROUTING_PREP.md)
- Current design, calculations and open items: [PCB_V1/DESIGN.md](PCB_V1/DESIGN.md) (Russian)
- Revision history and archive of earlier revision reports (0.1–0.21): [PCB_V1/CHANGELOG.md](PCB_V1/CHANGELOG.md)
- Reports and sheet images of the current revision: [review/](review)

## Checks

Run from this directory (needs KiCad 10; `pymupdf` only for sheet images):

```text
python check_all.py           # ERC, netlist + board verification, sizing reports, BOM export, price audit, JLC estimate, DRC
python check_all.py --write   # also refresh review/*_v22, sheet images and PCB_V1/BOM_schematic.csv
```

| Script | Purpose |
|---|---|
| `check_all.py` | Runs everything below; fails on any error or any DRC violation |
| `verify_netlist.py` | Critical connectivity, supply domains, fuse branches, LED return isolation, GPIO map |
| `verify_board.py` | Board vs schematic (every pin), power-footprint pad geometry — KiCad Python |
| `verify_placement.py` | Board boundary, edge access, battery side, antenna keepout and manufacturing setup |
| `analyze_led_power.py` | LED boost sizing over 72 cases per channel |
| `analyze_power_path.py` | Input, fuse loading, TVS margins, 12 V / 3.3 V bucks, switch conduction |
| `export_bom.py` | Full schematic BOM to `PCB_V1/BOM_schematic.csv` |
| `sync_board.py` | Update the unrouted board, retaining component side and orientation from the netlist (refuses routed boards) — KiCad Python |
| `create_staging_board.py` | Create the initial staging board — KiCad Python |
| `sync_models.py` | Attach 3D models to the board (project library models, overrides for stock footprints whose KiCad 10 model is missing) and list parts still without a model — KiCad Python |
| `models3d/power.py` | CadQuery generator of the simplified STEP models for the power SMD parts and the microSD socket (`PCB_V1/libraries/GrowBox.3dshapes/`, sources in `SOURCES_power.md`) |
| `estimate_jlc_assembly.py` | JLCPCB PCB + Economic/Standard assembly estimate for 2 and 5 boards from `PCB_V1/jlc_snapshot_v22.json` |
| `analyze_copper.py` | Copper screen before routing: IPC-2221 widths for the confirmed stack, via counts, drops and Kelvin notes (`review/Copper_<REV>.txt`) |
| `audit_bom_cost.py` | Whole-BOM LCSC price audit from the dated snapshot `PCB_V1/price_snapshot_v22.json` (1 and 5 boards, MOQ, EUR) |

Typical edit loop: change the schematic → `kicad-cli sch export netlist --format kicadxml -o netlist.xml PCB_V1/PCB_V1.kicad_sch` → `"<KiCad>/bin/python.exe" sync_board.py netlist.xml PCB_V1/PCB_V1.kicad_pcb` → `python check_all.py --write`.
