# GrowBox controller PCB

Hardware source of truth: `pcb/PCB_V1/PCB_V1.kicad_pro` (KiCad 10). All hardware changes belong in this directory. Current work continues branch `pcb-24v` from `dacd659`.

Revision 0.15: external 24 V input (24.0 V set point, design ceiling 25 V), XT60PW-M with no electronic reverse-polarity protection. One 24 V/100 W PTC, one 24 V/6 W pump, two 12 V four-wire fans. LMR16020 creates 12 V for fans, gate/LED controllers and the 3.3 V buck. Two constant-current LED power stages share one brightness command: panel and two paralleled bars. AL8853 IC bias is now 12 V, separately from the 24 V power stage. Six individual branch fuses added; CH2 total current limited to 0.465 A nominal / 0.484 A tolerance corner. Sharing between bars is not guaranteed.

169 schematic components. The priced subset is USD31.3786 for 53 parts; 116 parts remain unpriced. This is not a complete board cost. Around USD30 is a cost-control guide. Details: [design and calculations](PCB_V1/REDESIGN_24V.md), [BOM](PCB_V1/BOM_v0.1.md), [price audit](review/BOM_cost_v15.txt).

ERC: 0 errors/warnings; netlist/board checks pass. PCB 100x100 mm, four layers: footprints remain in staging outside the outline, placement/routing are unfinished. Not ready for fabrication. See [current status](PCB_V1/README.md).
