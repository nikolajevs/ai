# Review artifacts

Current revision **v20** (PCB_V1 0.20). Electrical, cost and assembly reports are produced by the check scripts from the `pcb` directory; do not edit generated reports by hand. Placement images are exported directly from KiCad; the final check log is captured from `check_all.py`.

| File | Content |
|---|---|
| `ERC_v20.rpt` | KiCad ERC report (0 errors / 0 warnings) |
| `DRC_placement_v20.rpt` | KiCad DRC of the placed, unrouted board (0 violations; unconnected pads expected) |
| `LED_power_v20.txt` | `analyze_led_power.py` — LED boost sizing, 72 cases per channel |
| `Power_path_v20.txt` | `analyze_power_path.py` — input, fuses, TVS margins, 12 V buck, switches |
| `JLC_assembly_v20.txt` | `estimate_jlc_assembly.py` — JLCPCB PCB + assembly for 2 and 5 boards (fees, JLC part prices, joints, stock) |
| `BOM_cost_v20.txt` | `audit_bom_cost.py` — every schematic reference priced from `PCB_V1/price_snapshot_v20.json` (1 and 5 boards, MOQ, EUR) |
| `Checks_v20.txt` | Full `check_all.py` log for 0.20 |
| `Placement_v20_top.png` / `.svg`, `Placement_v20_bottom.png` / `.svg` | Placement exported from KiCad (top: F.Cu, F.Fab, F.Silkscreen, outline; bottom mirrored) |
| `Root_v20.png` … `LEDDrivers_v20.png` | Schematic sheets rendered from KiCad SVG export |

`history/` keeps the reports, images and partial cost audit of revisions 0.1–0.15 unchanged; historical documents in `../PCB_V1/history` link to them.

Revision 0.20 changed footprints (Q711/Q721 DPAK, D711/D721 TO-277A, L101/L902 FXL0630 land) and added the RTC crystal parts; the LED switch areas were re-placed, see `../PCB_V1/COST_DOWN_020.md` and `Placement_v20_top.png`. Reports with suffixes v16–v19 are kept for comparison.
