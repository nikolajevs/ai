# GrowBox controller PCB

Hardware source of truth: `pcb/PCB_V1/PCB_V1.kicad_pro` (KiCad 10).

Save subsequent schematic, board, custom-library and design-note changes in this directory and commit them to this repository. Do not use the original desktop prototype as a second working copy.

The project is in schematic development. The PCB is not routed and is not ready for fabrication. See the project notes for completed blocks and remaining verification.

Target: external 24 V supply (24.0 V set point, never above 25 V), <=100 x 100 mm, four copper layers, mixed SMT/THT, ESP32-WROOM-32E, one 100 W 24 V PTC, two four-wire 12 V PC fans on an on-board 24 V to 12 V buck, one 24 V pump, two constant-current LED channels (panel; two identical bars in parallel) with common dimming and <=80 W combined output.

Current revision 0.14: 24 V input on a keyed XT60PW-M (no electronic reverse protection), SMBJ26CA TVS, mini-blade fuses (10 A loads, 7.5 A LED), LMR16020 24 V to 12 V aux buck feeding the fans, the heater gate driver and the 3.3 V buck. LED CH2 now drives both bars in parallel; the third AL8853 channel was removed. 163 components, estimated ~USD37 per board at LCSC unit prices. See [REDESIGN_24V.md](PCB_V1/REDESIGN_24V.md).

Previous revision 0.13 (12 V): LM74700 with an NTMFS5C628NL input MOSFET, bidirectional 14 V TVS and a TPS70950 5 V supply for the heater gate driver. Three AL8853 LED controllers retain the v0.12 Bourns/ST/Samsung power parts; RTC is DS3231MZ+TRL. Around USD30 is a cost-control guide, not a hard cap. The priced subset is USD29.7910 for 25 of 175 components; the remaining 150 are unpriced. See [input protection and power calculations](PCB_V1/INPUT_PROTECTION.md), [LED sizing](PCB_V1/LED_POWER_COMPONENTS.md) and [cost notes](PCB_V1/LED_COST_DOWN.md).
