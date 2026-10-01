# GrowBox controller PCB

Hardware source of truth: `PCB_V1/PCB_V1.kicad_pro` (KiCad 10). All hardware changes belong in this directory.

**Revision 0.22** — 24 V input on a keyed XT60PW-M (no electronic reverse-polarity protection), LMR16020 12 V auxiliary buck (fans, heater gate driver, AL8853 bias, 3.3 V buck), 24 V/100 W PTC, 24 V pump, two AL8853 constant-current LED channels (panel; two paralleled bars) with common dimming, seven fused load branches, PCF8563 RTC with CR2032 backup. 170 components (four of them copper-only net ties). ERC 0/0, DRC 0 violations; all components are now placed on the 100 x 100 mm board, with twelve edge connectors and a bottom battery holder. Manufacturing rules are set and the stack is confirmed (1.6 mm, 1 oz outer, 0.5 oz inner). The board is **fully routed** (first layout, 2026-10-01): DRC 0 violations and 0 unconnected, solid GND on In1, power pours by script, signals by Freerouting and a completion router: [PCB_V1/ROUTING.md](PCB_V1/ROUTING.md); **not ready for fabrication** (inspection in KiCad, mechanics check and DFM review remain). Components: USD 30.04 per board (USD 28.42 each for five) at dated LCSC list prices (base snapshot 2026-09-28; 0.18/0.19 substitutions 2026-09-29; 0.20-0.22 parts 2026-09-30). Revision 0.22 prepares routing: Murata LED output MLCCs, HRO TF-01A microSD, RTC CLKOUT test pad, Kelvin net ties at the four LED-driver shunts and a copper screen for the confirmed stack: [PCB_V1/ROUTING_PREP.md](PCB_V1/ROUTING_PREP.md). Revision 0.21 replaces the RTC supply OR diode with low-leakage JSCJ BAV170; the higher forward drop is checked at 25 C, while temperature, battery leakage and supply transitions still require a prototype: [PCB_V1/RTC_BACKUP_021.md](https://github.com/nikolajevs/ai/blob/1887d866ac820a41e9d1717056d188d7af6e6b51/pcb/PCB_V1/RTC_BACKUP_021.md). Revision 0.20 changed the RTC (DS3231MZ to PCF8563T + crystal; the firmware detects either), the boost switches/diodes (AOD66923 DPAK, SS5P10 TO-277A) and both small power inductors, with new footprints and a re-placed LED switch area: [PCB_V1/COST_DOWN_020.md](https://github.com/nikolajevs/ai/blob/1887d866ac820a41e9d1717056d188d7af6e6b51/pcb/PCB_V1/COST_DOWN_020.md). All checks pass. First boards will be hand assembled; all SMT parts are on the top side.

- Fabrication files for JLCPCB (Gerber, drill, order settings, DFM check): [PCB_V1/FAB.md](PCB_V1/FAB.md), archive in [fab/](fab)
- Order BOM for LCSC (upload file, quantities, what to buy elsewhere): [PCB_V1/BOM.md](PCB_V1/BOM.md)
- Routing of 0.22 (method, power paths, results, what remains): [PCB_V1/ROUTING.md](PCB_V1/ROUTING.md)
- Routing preparation 0.22 (parts, net ties, copper, routing rules): [PCB_V1/ROUTING_PREP.md](PCB_V1/ROUTING_PREP.md)
- Current design, calculations and open items: [PCB_V1/DESIGN.md](PCB_V1/DESIGN.md) (Russian)
- Revision history and archive of earlier revision reports (0.1–0.21): [PCB_V1/CHANGELOG.md](PCB_V1/CHANGELOG.md)
- Reports and sheet images of the current revision: [review/](review)

## Checks

Run from this directory (needs KiCad 10; `pymupdf` only for sheet images):

```text
python check_all.py           # ERC, netlist + board + routing verification, sizing reports, BOM export, price audit, JLC estimate, DRC
python check_all.py --write   # also refresh review/*_v22 (incl. DRC_routed_v22.rpt), sheet images, PCB_V1/BOM_schematic.csv and the LCSC BOM files
```

| Script | Purpose |
|---|---|
| `check_all.py` | Runs everything below; fails on any error, any DRC violation or any unconnected pad |
| `verify_netlist.py` | Critical connectivity, supply domains, fuse branches, LED return isolation, GPIO map |
| `verify_board.py` | Board vs schematic (every pin), power-footprint pad geometry — KiCad Python |
| `verify_placement.py` | Board boundary, edge access, battery side, antenna keepout and manufacturing setup |
| `check_fab.py` | DFM check of the board against the published JLCPCB limits (4 layers, 1 oz outer) and the JLCDFM categories (silkscreen to pad/hole, via to pad, track to pad, THT to SMD); `--fix-silk` sets silkscreen strokes to 0.2 mm, cuts them away from pads and holes and nudges texts (`review/DFM_JLCPCB_<REV>.txt`) — KiCad Python |
| `fab_touchups.py` | One-off board edits after the JLCDFM report of 2026-10-01 (a via, three ground ties, four track corners, one footprint); a record, tied to the coordinates of the committed routing — KiCad Python |
| `export_fab.py` | Gerber + Excellon export for JLCPCB, read-back verification and `fab/PCB_V1_<REV>_jlcpcb.zip` (reproducible; `--check` compares with the committed archive) — KiCad Python |
| `verify_routing.py` | Routing rules DRC cannot see: no tracks on the In1 GND plane, no power loops on In2, no vias on switching nodes, thin Kelvin lines, short RTC crystal nets, via counts and copper areas of the power nets — KiCad Python |
| `route_power.py` | Power stage of the routing (planes, pours, power tracks and vias, ground ties) and its finish stage (GND/+3V3 fills): geometry tables in the script — KiCad Python |
| `route_signals.py` | Freerouting 2.4.1 on the board left by the power stage (patched DSN, session import) — KiCad Python, Java 25 |
| `route_complete.py` | Grid router that finishes the connections the autorouter left open — KiCad Python |
| `analyze_led_power.py` | LED boost sizing over 72 cases per channel |
| `analyze_power_path.py` | Input, fuse loading, TVS margins, 12 V / 3.3 V bucks, switch conduction |
| `export_bom.py` | Full schematic BOM to `PCB_V1/BOM_schematic.csv` |
| `export_lcsc_bom.py` | Order BOM for LCSC from the schematic and the dated price snapshot: `PCB_V1/BOM_LCSC_<REV>.csv` / `.xlsx` (upload file for lcsc.com/bom, quantities per board) and the full grouped `PCB_V1/BOM_PCB_V1_<REV>.csv` |
| `sync_board.py` | Update an unrouted board from the netlist, retaining component side and orientation (refuses routed boards: after routing use KiCad's Update PCB) — KiCad Python |
| `create_staging_board.py` | Create the initial staging board — KiCad Python |
| `sync_models.py` | Attach 3D models to the board (project library models, overrides for stock footprints whose KiCad 10 model is missing) and list parts still without a model — KiCad Python |
| `models3d/power.py` | CadQuery generator of the simplified STEP models for the power SMD parts and the microSD socket (`PCB_V1/libraries/GrowBox.3dshapes/`, sources in `SOURCES_power.md`) |
| `estimate_jlc_assembly.py` | JLCPCB PCB + Economic/Standard assembly estimate for 2 and 5 boards from `PCB_V1/jlc_snapshot_v22.json` |
| `analyze_copper.py` | Copper screen before routing: IPC-2221 widths for the confirmed stack, via counts, drops and Kelvin notes (`review/Copper_<REV>.txt`) |
| `audit_bom_cost.py` | Whole-BOM LCSC price audit from the dated snapshot `PCB_V1/price_snapshot_v22.json` (1 and 5 boards, MOQ, EUR) |

Typical edit loop: change the schematic → `kicad-cli sch export netlist --format kicadxml -o netlist.xml PCB_V1/PCB_V1.kicad_sch` → `"<KiCad>/bin/python.exe" sync_board.py netlist.xml PCB_V1/PCB_V1.kicad_pcb` → `python check_all.py --write`.
