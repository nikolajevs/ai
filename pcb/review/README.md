# Review artifacts

Current revision **v17** (PCB_V1 0.17). Electrical, cost and assembly reports are produced by the check scripts from the `pcb` directory; do not edit generated reports by hand. Placement images are exported directly from KiCad; the final check log is captured from `check_all.py`.

| File | Content |
|---|---|
| `ERC_v17.rpt` | KiCad ERC report (0 errors / 0 warnings) |
| `DRC_placement_v17.rpt` | KiCad DRC of the placed, unrouted board (0 violations; unconnected pads expected) |
| `LED_power_v17.txt` | `analyze_led_power.py` — LED boost sizing, 72 cases per channel |
| `Power_path_v17.txt` | `analyze_power_path.py` — input, fuses, TVS margins, 12 V buck, switches |
| `JLC_assembly_v17.txt` | `estimate_jlc_assembly.py` — JLCPCB PCB + assembly for 2 and 5 boards (fees, JLC part prices, joints, stock) |
| `BOM_cost_v17.txt` | `audit_bom_cost.py` — every schematic reference priced from `PCB_V1/price_snapshot_v16.json` (1 and 5 boards, MOQ, EUR) |
| `Root_v17.png` … `LEDDrivers_v17.png` | Schematic sheets rendered from KiCad SVG export |

`history/` keeps the reports, images and partial cost audit of revisions 0.1–0.15 unchanged; historical documents in `../PCB_V1/history` link to them.

Price inputs remain the dated v16 snapshots from 2026-09-28, reused for the reviewed parts in hardware 0.17. Older v16 and P1 artifacts remain historical. Current placement previews: `Placement_v17_top.png` and `Placement_v17_bottom.png`; complete verification: `Checks_v17.txt`.
