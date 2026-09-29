# Review artifacts

Current revision **v19** (PCB_V1 0.19). Electrical, cost and assembly reports are produced by the check scripts from the `pcb` directory; do not edit generated reports by hand. Placement images are exported directly from KiCad; the final check log is captured from `check_all.py`.

| File | Content |
|---|---|
| `ERC_v19.rpt` | KiCad ERC report (0 errors / 0 warnings) |
| `DRC_placement_v19.rpt` | KiCad DRC of the placed, unrouted board (0 violations; unconnected pads expected) |
| `LED_power_v19.txt` | `analyze_led_power.py` — LED boost sizing, 72 cases per channel |
| `Power_path_v19.txt` | `analyze_power_path.py` — input, fuses, TVS margins, 12 V buck, switches |
| `JLC_assembly_v19.txt` | `estimate_jlc_assembly.py` — JLCPCB PCB + assembly for 2 and 5 boards (fees, JLC part prices, joints, stock) |
| `BOM_cost_v19.txt` | `audit_bom_cost.py` — every schematic reference priced from `PCB_V1/price_snapshot_v19.json` (1 and 5 boards, MOQ, EUR) |
| `Checks_v19.txt` | Full `check_all.py` log for 0.19 |
| `Root_v19.png` … `LEDDrivers_v19.png` | Schematic sheets rendered from KiCad SVG export |

`history/` keeps the reports, images and partial cost audit of revisions 0.1–0.15 unchanged; historical documents in `../PCB_V1/history` link to them.

Revision 0.19 changed the schematic only (same footprints and nets, see `../PCB_V1/COST_DOWN.md`). The board file was not edited, so the latest placement previews are still `Placement_v18_top.png` / `Placement_v18_bottom.png`, and `verify_board.py` reports 17 value differences until the board is synced. Reports with suffixes v16–v18 are kept for comparison.
