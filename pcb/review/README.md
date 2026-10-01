# Review artifacts

Current revision **v22** (PCB_V1 0.22). Electrical, cost and assembly reports are produced by the check scripts from the `pcb` directory; do not edit generated reports by hand. Placement images are exported directly from KiCad; the final check log is captured from `check_all.py`.

| File | Content |
|---|---|
| `ERC_v22.rpt` | KiCad ERC report (0 errors / 0 warnings) |
| `DRC_placement_v22.rpt` | KiCad DRC of the placed, unrouted board before routing (0 violations; 341 unconnected links) |
| `DRC_routed_v22.rpt` | KiCad DRC of the routed board (0 violations, 0 unconnected pads); written by `check_all.py --write` |
| `LED_power_v22.txt` | `analyze_led_power.py` — LED boost sizing, 72 cases per channel |
| `Power_path_v22.txt` | `analyze_power_path.py` — input, fuses, TVS margins, 12 V buck, switches |
| `Copper_v22.txt` | `analyze_copper.py` — conductor widths, via counts and drops for the confirmed stack (1.6 mm, 1 oz outer, 0.5 oz inner) |
| `JLC_assembly_v22.txt` | `estimate_jlc_assembly.py` — JLCPCB PCB + assembly for 2 and 5 boards (fees, JLC part prices, joints, stock) |
| `BOM_cost_v22.txt` | `audit_bom_cost.py` — every schematic reference priced from `PCB_V1/price_snapshot_v22.json` (1 and 5 boards, MOQ, EUR) |
| `Checks_v22.txt` | Full `check_all.py` log for 0.22 |
| `Placement_v22_top.png` / `.svg`, `Placement_v22_bottom.png` / `.svg` | Placement exported from KiCad (top: F.Cu, F.Fab, F.Silkscreen, outline; bottom mirrored) |
| `Root_v22.png` … `LEDDrivers_v22.png` | Schematic sheets rendered from KiCad SVG export |
| `DFM_JLCPCB_v22.txt` | `check_fab.py` — the board against the published JLCPCB limits (0 FAIL, 2 WARN) |
| `Routed_v22_top.png`, `Routed_v22_bottom.png` | 3D renders (`kicad-cli pcb render`) of the routed board, top and bottom |
| `Routed_v22_F.png`, `Routed_v22_In1.png`, `Routed_v22_In2.png`, `Routed_v22_B.png` | Copper layers of the routed board (`kicad-cli pcb export svg`; B.Cu mirrored): GND pours red, white = clearance |

Only the current revision is kept here. When `REV` in `check_all.py` changes, delete the previous revision's files in the same commit. Reports of earlier revisions (v16–v21, and 0.1–0.15 under `history/`) are in git history; links are in the archive section of `../PCB_V1/CHANGELOG.md`.

The first routed layout of 0.22 (2026-10-01, `../PCB_V1/ROUTING.md`) adds `DRC_routed_v22.rpt`, the `Routed_v22_*` images and a `Checks_v22.txt` that includes `verify_routing.py`.
