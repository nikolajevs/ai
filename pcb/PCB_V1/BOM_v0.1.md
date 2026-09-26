# PCB_V1 — BOM v0.1 (предварительный)

Этот файл фиксирует стартовые компоненты для ревизии схемы 0.4. Он не является заказным BOM: позиции со статусом `VERIFY` требуют сверки доступности, корпуса, теплового режима и измерений на макете.

## Расчётные режимы

- Вход: внешний изолированный источник 12 V DC, около 300 W.
- Нагрузка PTC: 100 W / 12 V = 8.33 A номинально; пусковой ток принят 9.6 A (+15%).
- LED1: 16S18P, стартовый лимит 1.10 A, около 52.8 W при 48 V.
- LED2/LED3: по 0.25 A, около 12 W каждый при 48 V.
- Суммарная целевая мощность LED: около 76.8 W; ток со стороны 12 V зависит от КПД boost и составляет ориентировочно 7.5–8.5 A.
- F902/F903 и входной ключ выбираются по реальному пусковому току, температуре меди и допустимому падению напряжения.

## Силовые и преобразователи

| Ref | Qty | Назначение | Кандидат MPN / серия | Корпус / footprint | Статус | Примечание |
|---|---:|---|---|---|---|---|
| U101 | 1 | 12 V → 3.3 V buck | TPS54202DDCR | SOT-23-6 | CANDIDATE | Проверить тепловой режим при токе логики и effective C под DC bias. |
| Q901 | 1 | защита от переполюсовки | Vishay SiSS5623DN, P-channel 60 V | PowerPAK SO-8 / по drawing | VERIFY | Проверить RDS(on) при доступном VGS, SOA при 25 A и рассеяние на 4 слоях. |
| D901 | 1 | TVS входа | SMBJ18A-E3/52 | SMB | CANDIDATE | TVS не заменяет fuse; проверить совместно с БП и проводом. |
| D902 | 1 | ограничение |VGS| Q901 | MMSZ5242B-7-F, 12 V zener | SOD-323 | CANDIDATE | Проверить ток через R902 и импульс при подключении БП. |
| F901 | 1 | общий входной предохранитель | Bourns SF-2923HC-C series, 25 A variant | 2920 / 7451 | VERIFY | Утвердить конкретный part number и I²t; вариант зависит от источника 300 W. |
| F902 | 1 | ветвь PTC/pump/fans | SF-2923HC-C series, 15–20 A variant | 2920 / 7451 | VERIFY | 20 A — стартовое значение, согласовать с кабелем и пуском PTC. |
| F903 | 1 | ветвь LED boost | SF-2923HC-C series, 10 A variant | 2920 / 7451 | VERIFY | 10 A — стартовое значение; селективность относительно F901 проверить. |
| U710/U720/U730 | 3 | контроллер boost CC | LT3756EMSE-2#PBF | MSOP-16 + EP | CANDIDATE | Версия -2 удобна для OPENLED; точную компенсацию и частоту проверить на макете. |
| Q711/Q721/Q731 | 3 | внешний boost MOSFET | TI CSD19532Q5B, 100 V, 4.9 mΩ | SON/VSON 5×6 mm | CANDIDATE | Использовать только footprint по оригинальному drawing; запас по VDS обязателен. |
| D711/D721/D731 | 3 | boost rectifier | STPS5H100SF, 100 V / 5 A | PSMC (TO-277A) | CANDIDATE | Проверить посадочное место: PSMC не равен обычному SMA. |
| L711 | 1 | дроссель LED1 | Bourns SRP1265A-220M, 22 µH | 13.5×12.5 mm | CANDIDATE | Isat около 12.5 A; подтвердить ripple/Irms в расчёте LT3756. |
| L721/L731 | 2 | дроссель LED2/3 | Bourns SRP1265A-470M, 47 µH | 13.5×12.5 mm | CANDIDATE | Isat около 6.5 A; проверить режим при 0.25 A и выбранной частоте. |
| R716 | 1 | LED1 current sense | 0.091 Ω, 1%, ≥1 W pulse-rated | 2512 | CANDIDATE | Номинал из целевого порога около 100 mV; сверить с выбранной версией LT3756. |
| R726/R736 | 2 | LED2/3 current sense | 0.40 Ω, 1%, ≥0.25 W | 0603/0805 | CANDIDATE | Проверить мощность и температурный коэффициент. |
| Q601 | 1 | ключ PTC | NTMFS5C628NLT1G | SO-8FL | CANDIDATE | VDS и тепловой режим проверены для 12 V; добавить внешний термостат/термопредохранитель. |
| U601 | 1 | драйвер затвора PTC | UCC27524ADR | SOIC-8 | CANDIDATE | Канал A; ENA удерживает выход выключенным при отсутствии 3.3 V. |
| Q501/Q511/Q521 | 3 | вентиляторы/помпа | AO3400A | SOT-23 | CANDIDATE | Проверить ток запуска помпы и поведение 4-wire PWM вентиляторов. |
| D521 | 1 | flyback помпы | SS34-E3/57T | SMC | CANDIDATE | Для фактического пускового/заклинившего тока нужна проверка осциллографом. |

## Логика и разъёмы

| Ref | Qty | Кандидат | Корпус / footprint | Статус | Примечание |
|---|---:|---|---|---|---|
| U201 | 1 | ESP32-WROOM-32E-N4 | RF module | CANDIDATE | Распиновка сохранена совместимой с текущей прошивкой. |
| U301 | 1 | DS3231SN# | SOIC-16W | CANDIDATE | CR2032 без зарядки; VBAT изолирована от 3.3 V. |
| J401 | 1 | Molex 104031-0811 | microSD push-push | CANDIDATE | Начальная SPI частота 4 MHz, обязательна проверка на прототипе. |
| J301 | 1 | JST XH B4B-XH-A | JST-XH 2.50 mm | CANDIDATE | Кабель SHT4x около 0.5 m; I²C 100 kHz, series 33 Ω. |
| BT301 | 1 | Keystone 3002 | CR2032 THT | CANDIDATE | Плата не должна иметь цепь заряда батарейки. |
| J901 | 1 | 2-pin power terminal, ≥25 A | 5.08 mm, exact family VERIFY | VERIFY | Phoenix MKDS-1,5 footprint пока только кандидат; для 25 A может понадобиться более крупный connector. |
| J501/J511 | 2 | DA803R/WAGO 2601-compatible 4-pin | 3.50 mm | VERIFY | Сверить механический drawing и длительный ток конкретного продавца. |
| J521/J601/J711/J721/J731 | 5 | DA803R/WAGO 2601-compatible 2-pin | 3.50 mm | VERIFY | Для PTC и LED проверить ток/нагрев контактов; при необходимости перейти на 5.08 mm. |
| J201 | 1 | 1×06 pin header | 2.54 mm | CANDIDATE | Только UART/EN/IO0/3V3 reference; отдельный программатор. |

## Обязательные решения перед PCB layout

1. Заказать/получить фактические MPN Q901, F901–F903, Q711/Q721/Q731, D711/D721/D731 и дросселей из доступного поставщика.
2. Сверить реальные посадочные места по drawings: Q901 и boost MOSFET, PSMC диоды, дроссели 13.5×12.5 mm, входной и силовые клеммники.
3. На макете подтвердить частоту/компенсацию LT3756, токи 1.10/0.25/0.25 A, overshoot на SW и температуру MOSFET/диодов/дросселей.
4. Измерить холодный старт PTC, запуск насоса и совместную работу входного БП; после этого утвердить fuse/I²t и ширину силовой меди.
5. Только после пунктов 1–4 заменить placeholder footprints и начать placement/routing платы 4 слоя до 100×100 mm.

## Источники

- LT3756: https://www.analog.com/media/en/technical-documentation/data-sheets/lt3756-3756-1-3756-2.pdf
- CSD19532Q5B: https://www.ti.com/product/CSD19532Q5B
- STPS5H100SF: https://www.st.com/en/diodes-and-rectifiers/stps5h100sf.html
- SiSS5623DN: https://www.vishay.com/en/product/62197/
- SRP1265A: https://www.bourns.com/docs/product-datasheets/srp1265a.pdf
- Littelfuse SMD fuses: https://www.littelfuse.com/products/fuses-overcurrent-protection/smd-fuses
