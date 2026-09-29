# GrowBox controller PCB

Hardware source of truth: `PCB_V1/PCB_V1.kicad_pro` (KiCad 10). All hardware changes belong in this directory.

**Revision 0.19** — 24 V input on a keyed XT60PW-M (no electronic reverse-polarity protection), LMR16020 12 V auxiliary buck (fans, heater gate driver, AL8853 bias, 3.3 V buck), 24 V/100 W PTC, 24 V pump, two AL8853 constant-current LED channels (panel; two paralleled bars) with common dimming, seven fused load branches. 161 components. ERC 0/0, DRC 0 violations; all components are now placed on the 100 x 100 mm board, with twelve edge connectors and a bottom battery holder. Manufacturing rules and a provisional four-layer stack are set. Routing is deferred; it has not started (336 unconnected links); **not ready for fabrication**. Components: USD 37.50 per board at dated LCSC list prices (base snapshot 2026-09-28; 0.18/0.19 substitutions fetched 2026-09-29, [PCB_V1/COST_DOWN.md](PCB_V1/COST_DOWN.md)). Revision 0.19 changed parts in the schematic only (same footprints and nets); the board was then synced for the 17 new values without moving any part. All checks pass. First boards will be hand assembled; all SMT parts are on the top side.

- Cost-down 0.19 (schematic only, same footprints; board values await sync): [PCB_V1/COST_DOWN.md](PCB_V1/COST_DOWN.md)
- Simplification 0.18 and before/after cost: [PCB_V1/SIMPLIFICATION.md](PCB_V1/SIMPLIFICATION.md)
- Current design, calculations and open items: [PCB_V1/DESIGN.md](PCB_V1/DESIGN.md) (Russian)
- Revision history: [PCB_V1/CHANGELOG.md](PCB_V1/CHANGELOG.md)
- Reports and sheet images of the current revision: [review/](review)

## Checks

Run from this directory (needs KiCad 10; `pymupdf` only for sheet images):

```text
python check_all.py           # ERC, netlist + board verification, sizing reports, BOM export, price audit, JLC estimate, DRC
python check_all.py --write   # also refresh review/*_v19, sheet images and PCB_V1/BOM_schematic.csv
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
| `estimate_jlc_assembly.py` | JLCPCB PCB + Economic/Standard assembly estimate for 2 and 5 boards from `PCB_V1/jlc_snapshot_v19.json` |
| `audit_bom_cost.py` | Whole-BOM LCSC price audit from the dated snapshot `PCB_V1/price_snapshot_v19.json` (1 and 5 boards, MOQ, EUR) |

Typical edit loop: change the schematic → `kicad-cli sch export netlist --format kicadxml -o netlist.xml PCB_V1/PCB_V1.kicad_sch` → `"<KiCad>/bin/python.exe" sync_board.py netlist.xml PCB_V1/PCB_V1.kicad_pcb` → `python check_all.py --write`.
