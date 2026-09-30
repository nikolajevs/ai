# Review artifacts

Current revision **v22** (PCB_V1 0.22). Electrical, cost and assembly reports are produced by the check scripts from the `pcb` directory; do not edit generated reports by hand. Placement images are exported directly from KiCad; the final check log is captured from `check_all.py`.

| File | Content |
|---|---|
| `ERC_v22.rpt` | KiCad ERC report (0 errors / 0 warnings) |
| `DRC_placement_v22.rpt` | KiCad DRC of the placed, unrouted board (0 violations; unconnected pads expected) |
| `LED_power_v22.txt` | `analyze_led_power.py` — LED boost sizing, 72 cases per channel |
| `Power_path_v22.txt` | `analyze_power_path.py` — input, fuses, TVS margins, 12 V buck, switches |
| `Copper_v22.txt` | `analyze_copper.py` — conductor widths, via counts and drops for the confirmed stack (1.6 mm, 1 oz outer, 0.5 oz inner) |
| `JLC_assembly_v22.txt` | `estimate_jlc_assembly.py` — JLCPCB PCB + assembly for 2 and 5 boards (fees, JLC part prices, joints, stock) |
| `BOM_cost_v22.txt` | `audit_bom_cost.py` — every schematic reference priced from `PCB_V1/price_snapshot_v22.json` (1 and 5 boards, MOQ, EUR) |
| `Checks_v22.txt` | Full `check_all.py` log for 0.22 |
| `Placement_v22_top.png` / `.svg`, `Placement_v22_bottom.png` / `.svg` | Placement exported from KiCad (top: F.Cu, F.Fab, F.Silkscreen, outline; bottom mirrored) |
| `Root_v22.png` … `LEDDrivers_v22.png` | Schematic sheets rendered from KiCad SVG export |

`history/` keeps the reports, images and partial cost audit of revisions 0.1–0.15 unchanged; historical documents in `../PCB_V1/history` link to them.

Revision 0.20 changed footprints (Q711/Q721 DPAK, D711/D721 TO-277A, L101/L902 FXL0630 land) and added the RTC crystal parts; the LED switch areas were re-placed, see `../PCB_V1/COST_DOWN_020.md` and `Placement_v22_top.png`. Reports with suffixes v16–v20 are kept for comparison.

Revision 0.21 changes only D303 to JSCJ BAV170 on the same SOT-23 land. Connectivity and placement are preserved. RTC voltage screening and limitations: `../PCB_V1/RTC_BACKUP_021.md`.

Revision 0.22 prepares routing: Murata LED output MLCCs (same land), HRO TF-01A microSD on a project footprint, TP301 on the RTC CLKOUT and four Kelvin net ties at the LED-driver shunts; see `../PCB_V1/ROUTING_PREP.md`. Reports with suffixes v16–v21 are kept for comparison.
