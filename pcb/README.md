# GrowBox controller PCB

Hardware source of truth: `pcb/PCB_V1/PCB_V1.kicad_pro` (KiCad 10).

Save subsequent schematic, board, custom-library and design-note changes in this directory and commit them to this repository. Do not use the original desktop prototype as a second working copy.

The project is in schematic development. The PCB is not routed and is not ready for fabrication. See the project notes for completed blocks and remaining verification.

Target: external 12 V supply, <=100 x 100 mm, four copper layers, mixed SMT/THT, ESP32-WROOM-32E, one 100 W PTC, two four-wire PC fans, one 12 V pump, three constant-current LED outputs with common dimming and <=80 W combined output.

Current revision 0.14 adds six individually fused load branches, a 15 A common LED fuse and a DEGSON DG636 input terminal. See [branch protection and its limits](PCB_V1/BRANCH_PROTECTION.md). The v0.13 ideal-diode input and 5 V heater-driver supply remain. The priced subset is USD32.2914 for 33 of 181 components; 148 remain unpriced. Around USD30 is a cost-control guide, already exceeded by the priced subset. Placement/routing and protection qualification are unfinished. See [current design status](PCB_V1/README.md).
