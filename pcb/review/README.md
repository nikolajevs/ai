# Review artifacts

Current revision **v21** (PCB_V1 0.21). Electrical, cost and assembly reports are produced by the check scripts from the `pcb` directory; do not edit generated reports by hand. Placement images are exported directly from KiCad; the final check log is captured from `check_all.py`.

| File | Content |
|---|---|
| `ERC_v21.rpt` | KiCad ERC report (0 errors / 0 warnings) |
| `DRC_placement_v21.rpt` | KiCad DRC of the placed, unrouted board (0 violations; unconnected pads expected) |
| `LED_power_v21.txt` | `analyze_led_power.py` — LED boost sizing, 72 cases per channel |
| `Power_path_v21.txt` | `analyze_power_path.py` — input, fuses, TVS margins, 12 V buck, switches |
| `JLC_assembly_v21.txt` | `estimate_jlc_assembly.py` — JLCPCB PCB + assembly for 2 and 5 boards (fees, JLC part prices, joints, stock) |
| `BOM_cost_v21.txt` | `audit_bom_cost.py` — every schematic reference priced from `PCB_V1/price_snapshot_v21.json` (1 and 5 boards, MOQ, EUR) |
| `Checks_v21.txt` | Full `check_all.py` log for 0.21 |
| `Placement_v21_top.png` / `.svg`, `Placement_v21_bottom.png` / `.svg` | Placement exported from KiCad (top: F.Cu, F.Fab, F.Silkscreen, outline; bottom mirrored) |
| `Root_v21.png` … `LEDDrivers_v21.png` | Schematic sheets rendered from KiCad SVG export |

`history/` keeps the reports, images and partial cost audit of revisions 0.1–0.15 unchanged; historical documents in `../PCB_V1/history` link to them.

Revision 0.20 changed footprints (Q711/Q721 DPAK, D711/D721 TO-277A, L101/L902 FXL0630 land) and added the RTC crystal parts; the LED switch areas were re-placed, see `../PCB_V1/COST_DOWN_020.md` and `Placement_v21_top.png`. Reports with suffixes v16–v20 are kept for comparison.

Revision 0.21 changes only D303 to JSCJ BAV170 on the same SOT-23 land. Connectivity and placement are preserved. RTC voltage screening and limitations: `../PCB_V1/RTC_BACKUP_021.md`.
