# PCB_V1 — подбор компонентов, ревизия 0.14 (24 В)

Курируемый частичный список выбранных деталей; не заказной BOM. Полный экспорт схемы — `BOM_schematic.csv`, расчёты и решения — [REDESIGN_24V.md](REDESIGN_24V.md). Цены — отображаемые цены LCSC на 27.09.2026 за 1 шт.; оценка всей платы около $37 без MOQ, доставки и налогов.

| Ref | Qty | Назначение | MPN/требование | Корпус | Статус | Примечание |
|---|---:|---|---|---|---|---|
| J901 | 1 | 24V input connector (keyed) | Amass XT60PW-M | AMASS_XT60PW-M_1x02_P7.20mm_Horizontal | PROTOTYPE | LCSC C98732 USD0.6072 (0 in stock at check; buy elsewhere); pin1 GND pin2 +24V per KiCad footprint silkscreen; polarity protected only by the connector |
| D901 | 1 | Input TVS | SMBJ26CA-E3/52 | D_SMB | PROTOTYPE | LCSC C515606 USD0.0985; VWM26V > 25V PSU max; clamp 42.1V at 14.3A 10/1000us leaves 0.9V to AL8853 43V abs max - measure |
| C901 | 1 | Input bulk | Panasonic EEEFK1H221P 220uF 50V | CP_Elec_10x10.5 | PROTOTYPE | LCSC C178549 USD0.5157; 502mA ripple at 120Hz |
| C902 | 1 | Input ceramic | 1uF 50V X7R 1210 MPN pending | C_1210_3225Metric | VERIFY | Effective capacitance at 25V |
| F902/F903 | 2 | Branch fuse holders | XFCN XF-508P-B-B + ATM mini blade fuse 10A (loads) / 7.5A (LED) | Fuseholder_Blade_Mini_XFCN_XF-508P | PROTOTYPE | LCSC C19727305 USD0.2637 each; contact <=5mOhm; fuses are consumables; check interrupt rating and I2t with the real PSU |
| U902 | 1 | 24V to 12V aux buck | TI LMR16020PDDAR | SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.95x4.9mm_Mask2.71x3.4mm | PROTOTYPE | LCSC C190006 USD0.8159; 500kHz RT49.9k; Vout 12.03V; EN 560k/47k start ~14.9V; EP to GND with vias |
| L902 | 1 | Aux buck inductor | Bourns SRP1265A-220M | L_Bourns_SRP1265A | PROTOTYPE | LCSC C2041465 USD1.1784; 22uH Isat 9A > IC limit 3.8A |
| D902 | 1 | Aux buck catch diode | Vishay SS36-E3/57T | D_SMC | PROTOTYPE | LCSC C35722 USD0.3337; 60V 3A |
| C905/C906 | 2 | Aux buck input | Murata GRM32ER71H106KA12L | C_1210_3225Metric | PROTOTYPE | LCSC C77102 USD0.3304 each; 10uF 50V X7R |
| C909/C910 | 2 | Aux buck output | Samsung CL32B226KAJNNNE | C_1210_3225Metric | PROTOTYPE | LCSC C309062 USD0.3569 each; 22uF 25V X7R |
| R904/R905/R906/R907/R908 | 5 | Aux buck FB/RT/EN | 100k/6.65k/49.9k/560k/47k 1% 0603 MPN pending | R_0603_1608Metric | VERIFY | FB 0.75V; see Power_path_v14.txt |
| U101 | 1 | 12V aux to 3V3 buck | TPS54202DDCR | SOT-23-6 | CANDIDATE | Now fed from +12V aux (28V max part isolated from 24V transients) |
| U710/U720 | 2 | LED boost controller | AL8853S-13 | SOIC-8 3.9x4.9 P1.27 | PROTOTYPE | LCSC C3192318 USD0.9392 each; VIN 24V; analog dimming via PWM |
| Q711 | 1 | Panel boost MOSFET | TI CSD19534Q5A | TI_DQJ0008A_CSD19534Q5A | PROTOTYPE | LCSC C114200 USD0.9862; 100V 15.1mOhm max at 10V; gate ~13V from AL8853 |
| Q721 | 1 | Bars boost MOSFET | TI CSD19538Q3A | TI_DNH0008A_CSD19538Q3A | PROTOTYPE | LCSC C478471 USD1.0754 |
| D711 | 1 | Panel boost diode | STPS5H100B-TR | TO-252-2 | PROTOTYPE | LCSC C10648 USD0.5802; NC1 K2 A3 |
| D721 | 1 | Bars boost diode | STPS2H100AFY | D_SOD-128 | PROTOTYPE | LCSC C3757915 USD0.4753; 0.5A output |
| L711 | 1 | Panel boost inductor | Bourns SRP1770TA-470M | L_Bourns_SRP1770TA_16.9x16.9mm | PROTOTYPE | LCSC C2041872 USD2.9304 (26 in stock at check); copper loss 0.77W worst at 24V |
| L721 | 1 | Bars boost inductor | Bourns SRP1265A-470M | L_Bourns_SRP1265A | PROTOTYPE | LCSC C840530 USD1.1226; DCM at 24V |
| C716/C717/C718/C719/C726/C727/C728 | 7 | LED output capacitance | Samsung CL32Y106KCV6PNE | C_1210_3225Metric | PROTOTYPE | LCSC C22380050 USD0.8941 each; 10uF 100V X7S; ~2.6uF each at 48V |
| C710/C715/C725 | 3 | LED boost input | Murata GRM32ER71H106KA12L | C_1210_3225Metric | PROTOTYPE | LCSC C77102 USD0.3304 each; 10uF 50V X7R |
| C711/C721 | 2 | AL8853 VIN decoupling | Samsung CL21B105KBFNNNE | C_0805_2012Metric | PROTOTYPE | LCSC C28323 USD0.04; 1uF 50V X7R |
| R715 | 1 | Panel switch current sense | 0.027 ohm 1% >=1W MPN pending | R_2512_6332Metric | VERIFY | 0.17W worst at 24V; Kelvin connection |
| R716 | 1 | Panel LED sense | 0.182 ohm 1% >=1W MPN pending | R_2512_6332Metric | VERIFY | Low side; nominal 1.099A |
| R725 | 1 | Bars switch current sense | 0.047 ohm 1% >=1W MPN pending | R_2512_6332Metric | VERIFY | With Rsl 2.7k |
| R726 | 1 | Bars LED sense | 0.40 ohm 1% >=0.25W MPN pending | R_1206_3216Metric | VERIFY | Low side; 0.5A total for J721 || J731 |
| U700 | 1 | PWM and enable gate | SN74LVC1G08DBVR | SOT-23-5 | PROTOTYPE | 3.3V; LED_DIM = LIGHT_PWM AND LIGHT_ENABLE |
| Q601 | 1 | PTC MOSFET | NTMFS5C628NLT1G | ONSemi_SO-8FL_488AA | PROTOTYPE | LCSC C145537 USD0.7717; 24V PTC 4.17A; gate ~12V; external thermal cutoff required |
| U601 | 1 | PTC gate driver | UCC27524ADR | SOIC-8 | CANDIDATE | VDD = +12V aux (4.5..18V); channel A |
| D601 | 1 | PTC drain TVS | SMBJ30A-E3/52 | D_SMB | PROTOTYPE | LCSC C1973126 USD0.1731; VWM30V; clamp 48.4V < 60V |
| Q501/Q511 | 2 | Fan PWM open-drain | AO3400A | SOT-23 | CANDIDATE | Fan PWM line only (<=5V) |
| Q521 | 1 | Pump switch | AOS AO3422 | SOT-23 | PROTOTYPE | LCSC C37130 USD0.1356; 55V; 3.3V gate; measure pump current |
| D521 | 1 | Pump flyback | Vishay SS36-E3/57T | D_SMC | PROTOTYPE | LCSC C35722 USD0.3337; 60V |
| C521 | 1 | Pump branch bypass | Murata GRM32ER71H106KA12L | C_1210_3225Metric | PROTOTYPE | LCSC C77102; 10uF 50V |
| U201 | 1 | MCU | ESP32-WROOM-32E-N4 | RF module | CANDIDATE | LCSC C701341 USD3.7644; GPIO map unchanged |
| U301 | 1 | RTC | DS3231MZ+TRL | SOIC-8_3.9x4.9mm_P1.27mm | PROTOTYPE | LCSC C107410 USD3.2976; existing RTC code compatible |
| J401 | 1 | microSD | Molex 104031-0811 | microSD | CANDIDATE | 4MHz initial SPI |
| J301 | 1 | SHT4x connector | JST XH B4B-XH-A | JST-XH 2.50 | CANDIDATE | 0.5m cable and 100kHz I2C |
| BT301 | 1 | RTC battery holder | Keystone 3002 | CR2032 THT | CANDIDATE | No charger; not stocked at LCSC |
| J501/J511 | 2 | 4-wire fan terminal | DORABO DB125-3.5-4P-GN-S | TerminalBlock_Phoenix_PT-1,5-4-3.5-H_1x04_P3.50mm_Horizontal | PROTOTYPE | LCSC C2757925 USD0.3584; 10A; fans on +12V aux |
| J302/J521/J601 | 3 | 2-wire terminal (float/pump/PTC) | DORABO DB125-3.5-2P-GN-S | TerminalBlock_Phoenix_PT-1,5-2-3.5-H_1x02_P3.50mm_Horizontal | PROTOTYPE | LCSC C466970 USD0.1631; 10A; PTC 4.8A cold |
| J711/J721/J731 | 3 | LED terminals | KANGNEX WJ500V-5.08-2P | TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal | PROTOTYPE | LCSC C8465 USD0.1258; J721 and J731 are paralleled on CH2 |
| J201 | 1 | Programming header | 1x06 pin header | 2.54mm | CANDIDATE | External USB-UART programmer |
| SW201/SW202 | 2 | RESET/BOOT | XKB TS-1187A-B-A-B | SW_Push_1P1T_XKB_TS-1187A | PROTOTYPE | LCSC C318884 USD0.0207 |

До заказа: подтвердить наличие (XT60PW-M и SRP1770TA-470M у LCSC ограничены), выбрать MPN резисторов-шунтов и делителей, проверить предохранители с реальным БП и измерить ток помпы 24 В. Прежние списки 0.12–0.13 — в истории git.
