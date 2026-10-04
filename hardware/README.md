# Плата GrowBox

Проект KiCad 10: [PCB_V1/PCB_V1.kicad_pro](PCB_V1/PCB_V1.kicad_pro).
Текущая ревизия — **0.22**. Схема, размещение и трассировка выполнены; Gerber и заказной BOM подготовлены. Состояние проекта и навигация — [PCB_V1/README.md](PCB_V1/README.md).

## Проверки

Из папки `hardware`, с установленным KiCad 10:

```sh
python check_all.py
```

При нестандартной установке задайте `KICAD_CLI` (путь к `kicad-cli`) и `KICAD_PYTHON` (Python с модулем `pcbnew`). На Windows можно запускать через `"C:\Program Files\KiCad\10.0\bin\python.exe"`.

Проверяются ERC, соединения схемы и платы, размещение, правила трассировки, расчёты, BOM, DFM и DRC. Команда завершается ошибкой при нарушениях или несоединённых площадках. Сохранённые отчёты — [review/](review/).

`python check_all.py --write` обновляет отчёты, изображения листов и BOM. Используйте его только при намеренном обновлении этих файлов.

## Работа с готовой платой

- После изменения схемы обновляйте плату через **Update PCB from Schematic** в KiCad. `sync_board.py` предназначен для неразведённой платы и отказывается менять разведённую.
- После изменения платы выполните проверки и пересоберите производственный архив по [FAB.md](PCB_V1/FAB.md).
- Скрипты `route_power.py`, `route_signals.py`, `route_complete.py` пересоздают трассировку; это не обычная проверка. Зафиксированный результат — файл платы. Подробности — [ROUTING.md](PCB_V1/ROUTING.md).

## Инструменты

| Задача | Скрипты / инструкция |
|---|---|
| Все проверки | `check_all.py`; отдельные проверки — `verify_*.py`, `check_fab.py` |
| Расчёты питания и меди | `analyze_led_power.py`, `analyze_power_path.py`, `analyze_copper.py` |
| Заказ деталей и оценка цены | [BOM.md](PCB_V1/BOM.md), `export_lcsc_bom.py`, `audit_bom_cost.py`, `estimate_jlc_assembly.py` |
| Gerber и сверловка | [FAB.md](PCB_V1/FAB.md), `export_fab.py` |
| 3D-модели | `models3d/mechanical.py`, `models3d/power.py`, `sync_models.py`; [источники](PCB_V1/PLACEMENT.md) |
| Одноразовая плата из склада | [cheap-version/README.md](cheap-version/README.md) — отдельный проект cheap-1 (копия схемы PCB_V1 с заменами деталей) |
| Корпус (3D-печать) | [enclosure/README.md](enclosure/README.md), `enclosure/enclosure.py`, `enclosure/check_enclosure.py` |

Правила веток и проверки — [AGENTS.md](../AGENTS.md). Работа с удалённой KiCad-станцией — [vps-docs/README.md](../vps-docs/README.md).
