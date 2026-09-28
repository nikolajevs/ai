# История: документы прежних ревизий

Эти документы описывают 12-вольтовую версию платы и промежуточные решения. Они сохранены без изменений содержания, кроме исправленных ссылок, и **не отражают текущую схему**. Актуальное описание — [../DESIGN.md](../DESIGN.md), журнал — [../CHANGELOG.md](../CHANGELOG.md).

| Документ | Ревизия | Содержание |
|---|---|---|
| [README_v01.md](README_v01.md) | 0.1 | Первая логическая часть: TPS54202, ESP32, UART |
| [MOSFET_SELECTION.md](MOSFET_SELECTION.md) | 0.10–0.11 | Выбор ключей LED-лент (DMT10H009LK3 → CSD19538Q3A) |
| [LED_COST_DOWN.md](LED_COST_DOWN.md) | 0.9–0.11 | Переход с LT3756 на AL8853, первые шаги удешевления |
| [LED_POWER_COMPONENTS.md](LED_POWER_COMPONENTS.md) | 0.12 | Силовые детали LED при 12 В и методика расчёта |
| [INPUT_PROTECTION.md](INPUT_PROTECTION.md) | 0.13 | Вход 12 В с LM74700, LDO 5 В для драйвера PTC |
| [price_snapshot_v15.json](price_snapshot_v15.json) | 0.15 | Частичный ценовой снимок (53 из 169 деталей), отчёт — `../../review/history/BOM_cost_v15.txt` |

Отчёты и изображения этих ревизий — [../../review/history/](../../review/history).
