# Sources of project library data

The `EU` symbol library is generated from the explicitly numbered pin maps in `tools/generate.py`; sources are linked in `design.json` and the schematic Datasheet fields. These are schematic-stage symbols, not a manufacturer-approved CAD package.

The NMOS graphics in `NMOS_graphics.sexpr` are taken from the cached KiCad `Transistor_FET:AO3400A` symbol in the original repository's `hardware/PCB_V1/Outputs.kicad_sch`, commit `1d6b1eaf1273149b32eb1cf5c91fc69ff6a6ca09`. Physical pin numbering is separately assigned to NMOS (GDS) and NMOS_GSD; AO3422 is GSD.

Selected stock footprints were retrieved on 20 October 2026 from the official [KiCad footprint library](https://github.com/KiCad/kicad-footprints). Only the selected footprints are bundled, with their library names retained in `fp-lib-table`. The upstream license is included alongside this file.

`EU_Parts:ESP32-WROOM-32E_NoVias` and `EU_Parts:Vishay_TO-277A_D_K1_A2` are copied without geometry changes from `hardware/PCB_V1/libraries/GrowBox.pretty` at the same source commit. They describe the same module package and rectifier already used in PCB_V1. Paths to old 3D models are not a claim that models are included or validated for this new assembly.

All assigned footprints remain subject to datasheet/physical qualification in the new board. Missing exact footprints are deliberately left blank in the schematic; no generic terminal, battery or SD socket footprint is substituted for an unverified part.

## Mechanical preflight candidates

Two unmodified footprints are additionally bundled in `EU_Mechanical.pretty`, attributed to the KiCad library contributors under the existing `LICENSE-footprints.md` (CC-BY-SA-4.0 with the KiCad library exception). Their source is the archived official GitHub mirror at the pinned commit `7ebfa6b23cc292a56f751b7b5f4a0e12eeef69dd`, not a claim to contain the current complete KiCad library.

| File | Upstream path | Upstream Git blob |
|---|---|---|
| `Fuse_Schurter_UMT250.kicad_mod` | `Fuse.pretty/Fuse_Schurter_UMT250.kicad_mod` | `cbb208235980bc128463c367f6f680e68beb9030` |
| `HTSSOP-16-1EP_4.4x5mm_P0.65mm_EP3x3mm.kicad_mod` | `Package_SO.pretty/HTSSOP-16-1EP_4.4x5mm_P0.65mm_EP3x3mm.kicad_mod` | `3e3c314a9d47be6f4bea83ce8ed1b0ffd3de7064` |

[Upstream commit](https://github.com/KiCad/kicad-footprints/tree/7ebfa6b23cc292a56f751b7b5f4a0e12eeef69dd). No geometry, numbering, model path or attributes were modified. Numerical suitability for the proposed F104/F105/F106/F401 and U101 is discussed in `../DESIGN.md` against the SCHURTER UMT 250 and ST L7987 datasheets. These candidates are not registered in `fp-lib-table` or assigned in the schematic. Native KiCad parsing, visual inspection and assembly/PCB qualification remain pending. The referenced legacy 3D models are not bundled.
