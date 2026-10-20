# Sources of project library data

The `EU` symbol library is generated from the explicitly numbered pin maps in `tools/generate.py`; sources are linked in `design.json` and the schematic Datasheet fields. These are schematic-stage symbols, not a manufacturer-approved CAD package.

The NMOS graphics in `NMOS_graphics.sexpr` are taken from the cached KiCad `Transistor_FET:AO3400A` symbol in the original repository's `hardware/PCB_V1/Outputs.kicad_sch`, commit `1d6b1eaf1273149b32eb1cf5c91fc69ff6a6ca09`. Physical pin numbering is separately assigned to NMOS (GDS) and NMOS_GSD; AO3422 is GSD.

Selected stock footprints were retrieved on 20 October 2026 from the official [KiCad footprint library](https://github.com/KiCad/kicad-footprints). Only the selected footprints are bundled, with their library names retained in `fp-lib-table`. The upstream license is included alongside this file.

`EU_Parts:ESP32-WROOM-32E_NoVias` and `EU_Parts:Vishay_TO-277A_D_K1_A2` are copied without geometry changes from `hardware/PCB_V1/libraries/GrowBox.pretty` at the same source commit. They describe the same module package and rectifier already used in PCB_V1. Paths to old 3D models are not a claim that models are included or validated for this new assembly.

All assigned footprints remain subject to datasheet/physical qualification in the new board. Missing exact footprints are deliberately left blank in the schematic; no generic terminal, battery or SD socket footprint is substituted for an unverified part.
