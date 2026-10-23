# Плата GrowBox

**Текущая плата — [PCB_EU / EU-0.1](PCB_EU/README.md)**: детали только из магазинов ЕС, плата разведена полностью, прошивка — [softwareEU/](../softwareEU/README.md). Состав закупки, оценка цены и состояние проверок — в [README](PCB_EU/README.md) и [DESIGN.md](PCB_EU/DESIGN.md) этой платы. PCB_V1 ниже — предыдущий проект, отдельный от PCB_EU.

## Проверки PCB_EU

С установленным KiCad 10.0.7, из корня репозитория:

```sh
python3 hardware/PCB_EU/tools/run_checks.py
```

Без KiCad работают `tools/generate.py` (пересборка схем и BOM) и `tools/verify.py` (соединения и закупка). Подробности — [PCB_EU/README.md](PCB_EU/README.md), раздел «Проверки». `check_all.py` ниже проверяет только PCB_V1.

## PCB_V1 (предыдущая плата)

Проект KiCad 10: [PCB_V1/PCB_V1.kicad_pro](PCB_V1/PCB_V1.kicad_pro).
Текущая ревизия — **0.22**. Схема, размещение и трассировка выполнены; Gerber и заказной BOM подготовлены. Состояние проекта и навигация — [PCB_V1/README.md](PCB_V1/README.md).

## Проверки PCB_V1

Из папки `hardware`, с установленным KiCad 10:

```sh
python check_all.py
```

При нестандартной установке задайте `KICAD_CLI` (путь к `kicad-cli`) и `KICAD_PYTHON` (Python с модулем `pcbnew`). На Windows можно запускать через `"C:\Program Files\KiCad\10.0\bin\python.exe"`.

Проверяются ERC, соединения схемы и платы, размещение, правила трассировки, расчёты, BOM, DFM и DRC. Команда завершается ошибкой при нарушениях или несоединённых площадках. Сохранённые отчёты — [review/](review/).

`python check_all.py --write` обновляет отчёты, изображения листов и BOM. Используйте его только при намеренном обновлении этих файлов.

## Работа с готовой платой PCB_V1

- После изменения схемы обновляйте плату через **Update PCB from Schematic** в KiCad. `sync_board.py` предназначен для неразведённой платы и отказывается менять разведённую.
- После изменения платы выполните проверки и пересоберите производственный архив по [FAB.md](PCB_V1/FAB.md).
- Скрипты `route_power.py`, `route_signals.py`, `route_complete.py` пересоздают трассировку; это не обычная проверка. Зафиксированный результат — файл платы. Подробности — [ROUTING.md](PCB_V1/ROUTING.md).

## Инструменты

| Задача | Скрипты / инструкция |
|---|---|
| PCB_EU: схемы, BOM, проверки, разводка | [PCB_EU/tools/](PCB_EU/tools): `generate.py`, `verify.py`, `run_checks.py`; порядок — [PCB_EU/README.md](PCB_EU/README.md) |
| PCB_V1: все проверки | `check_all.py`; отдельные проверки — `verify_*.py`, `check_fab.py` |
| PCB_V1: расчёты питания и меди | `analyze_led_power.py`, `analyze_power_path.py`, `analyze_copper.py` |
| PCB_V1: заказ деталей и оценка цены | [BOM.md](PCB_V1/BOM.md), `export_lcsc_bom.py`, `audit_bom_cost.py`, `estimate_jlc_assembly.py` |
| PCB_V1: Gerber и сверловка | [FAB.md](PCB_V1/FAB.md), `export_fab.py` |
| PCB_V1: 3D-модели | `models3d/mechanical.py`, `models3d/power.py`, `sync_models.py`; [источники](PCB_V1/PLACEMENT.md) |
| Одноразовая плата из склада | [cheap-version/README.md](cheap-version/README.md) — отдельный проект cheap-1 (копия схемы PCB_V1 с заменами деталей) |
| Корпус (3D-печать) | [enclosure/README.md](enclosure/README.md), `enclosure/enclosure.py`, `enclosure/check_enclosure.py` |

Правила веток и проверки — [AGENTS.md](../AGENTS.md). Состояние VPS после удаления KiCad — [vps-docs/README.md](../vps-docs/README.md).
