# GrowBox controller PCB

Hardware source of truth: `pcb/PCB_V1/PCB_V1.kicad_pro` (KiCad 10).

Save subsequent schematic, board, custom-library and design-note changes in this directory and commit them to this repository. Do not use the original desktop prototype as a second working copy.

The project is in schematic development. The PCB is not routed and is not ready for fabrication. See the project notes for completed blocks and remaining verification.

Target: external 12 V supply, <=100 x 100 mm, four copper layers, mixed SMT/THT, ESP32-WROOM-32E, one 100 W PTC, two four-wire PC fans, one 12 V pump, three constant-current LED outputs with common dimming and <=80 W combined output.

Current revision 0.12: three AL8853 LED controllers with selected Bourns inductors, ST rectifiers and Samsung output MLCCs; DS3231MZ+TRL RTC and CSD19538Q3A strip-channel MOSFETs. Around USD30 is a cost-control guide, not a hard cap. The priced subset is USD25.8896 for 21 of 171 components; the complete BOM has not been priced. See [LED power sizing](PCB_V1/LED_POWER_COMPONENTS.md) and [cost notes](PCB_V1/LED_COST_DOWN.md).
