# Review artifacts

Current revision **v16** (PCB_V1 0.16). All files here are produced by `python check_all.py --write` from the `pcb` directory; do not edit them by hand.

| File | Content |
|---|---|
| `ERC_v16.rpt` | KiCad ERC report (0 errors / 0 warnings) |
| `DRC_staging_v16.rpt` | KiCad DRC of the unrouted staging board (0 violations; unconnected pads expected) |
| `LED_power_v16.txt` | `analyze_led_power.py` — LED boost sizing, 72 cases per channel |
| `Power_path_v16.txt` | `analyze_power_path.py` — input, fuses, TVS margins, 12 V buck, switches |
| `BOM_cost_v16.txt` | `audit_bom_cost.py` — every schematic reference priced from `PCB_V1/price_snapshot_v16.json` (1 and 5 boards, MOQ, EUR) |
| `Root_v16.png` … `LEDDrivers_v16.png` | Schematic sheets rendered from KiCad SVG export |

`history/` keeps the reports, images and partial cost audit of revisions 0.1–0.15 unchanged; historical documents in `../PCB_V1/history` link to them.
