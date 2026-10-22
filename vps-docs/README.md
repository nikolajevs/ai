# VPS: состояние и обслуживание

## Текущее состояние — 2026-10-22

VPS больше не используется как удалённая KiCad-станция. Очистка выполнена
пользователем в SSH-сессии; сведения ниже основаны на присланном выводе команд.

Удалены:

- восемь пакетов: `kicad`, `kicad-demos`, `kicad-doc-en`, `kicad-footprints`,
  `kicad-libraries`, `kicad-packages3d`, `kicad-symbols`, `kicad-templates`;
  APT сообщил об освобождении около 4,37 ГБ;
- unit-файлы `kicad-vnc.service` и `kicad-novnc.service`; последующая попытка
  остановки показала, что обе службы не загружены;
- PPA KiCad 10 и файл `/etc/sysctl.d/99-kicad-vps.conf`;
- `/home/administrator/kicad` целиком, включая checkout, worktrees и локальную
  Git-историю;
- настройки, данные и кэш KiCad пользователя `administrator`, связанные записи
  проектов Claude, найденные кэшированные файлы PPA и Launchpad.

Итоговый поиск по имени `*kicad*` в `/etc`, `/opt`, `/srv`, `/usr/local`,
`/usr/share`, `/var/lib`, `/var/cache`, `/home` и `/root` не вернул результатов.
Это проверка имён файлов в перечисленных каталогах, а не аудит всей системы.
Вывод проверки процессов не предоставлен. Выполнение `apt-get autoremove --purge`
не подтверждено; удаление общих пакетов XFCE, TigerVNC, noVNC и Tailscale
также не подтверждено.

## Работа с репозиторием после очистки

Источник истины — `nikolajevs/ai`, ветка `main`. Файлы плат в репозитории
сохраняются; удалены их локальные копии на VPS.

- Не использовать прежние пути `~/kicad/main`, `~/kicad/worktrees/` и
  `~/kicad/claude-control`: они удалены.
- Не запускать прежние `ai-codex` / `ai-claude`, пока их конфигурация не проверена:
  они были привязаны к удалённым checkout и worktrees.
- `kicad-cli` и проверки `hardware/check_all.py` на этом VPS больше не подготовлены
  к запуску. Для аппаратных проверок нужна другая среда с KiCad и библиотеками.
- Прежние команды `systemctl start/enable kicad-vnc` и `kicad-novnc` не восстанавливают
  рабочую станцию: unit-файлы и KiCad удалены.
- Старые инструкции развёртывания доступны в Git-истории этого документа.

## SSH-доступ

На сервере `vps-ypoe` SSH подтверждённо слушал `0.0.0.0:22` и `[::]:22`.
Подключения из облачной среды к `93.127.143.133` на портах `22`, `1066` и
`10066` завершались `Connection refused`. Рабочий внешний порт или правило
перенаправления не установлены; не считать `10066` проверенным портом доступа.
Не менять SSH, firewall или сетевую конфигурацию без отдельной задачи.

## Прочие сервисы

Очистка была направлена на KiCad. Состояние Telegram-бота, PM2, сайтов и Tailscale
после неё не проверялось. Ниже сохранены сведения прежней конфигурации и команды
обслуживания; перед изменениями необходимо проверить фактическое состояние.

# Ресурсы VPS

Быстрая проверка:

```bash
free -h
swapon --show
df -h /
uptime
```

Процессы по RAM:

```bash
ps aux --sort=-%mem | head -15
```

Интерактивный мониторинг:

```bash
htop
```

---

# Swap

На сервере используется:

```text
4 GB RAM
4 GB swap
```

Проверка:

```bash
free -h
swapon --show
```

Файл `/etc/sysctl.d/99-kicad-vps.conf` удалён. Текущее значение
`vm.swappiness` после очистки не проверялось; удаление файла само по себе
не меняет уже применённые параметры ядра.

---

# Контроль диска

Проверить filesystem:

```bash
df -h /
```

Крупные каталоги:

```bash
sudo du -xhd1 / 2>/dev/null | sort -h
sudo du -xhd1 /home/administrator 2>/dev/null | sort -h
```

Файлы больше 500 MB:

```bash
sudo find /home/administrator \
  -xdev \
  -type f \
  -size +500M \
  -printf '%s %p\n' 2>/dev/null \
  | sort -n \
  | numfmt --field=1 --to=iec
```

---

# Telegram-бот и PM2

Node.js установлен через `nvm`. В неинтерактивных shell (systemd, агенты, `ssh host cmd`) `pm2` может отсутствовать в `PATH`, поэтому используется полный путь:

```bash
export PATH=/home/administrator/.nvm/versions/node/v24.21.0/bin:$PATH
```

## Приложения

| PM2 name | Путь | Статус |
|---|---|---|
| `ss-bot` | `/opt/SS_COM/src/index.js` | запущен, в автозапуске |
| `pm2-logrotate` | модуль PM2 | запускается вместе с PM2 |
| `my-app` | `/home/administrator/BRIDGE/server/index.js` | выключен |
| `todo-app` | `/home/administrator/todo-app/server.js` | выключен |

Бот читает `BOT_TOKEN` и остальные настройки из `/opt/SS_COM/.env` сам; SQLite — встроенный `node:sqlite` Node 24, пересборка `better-sqlite3` не нужна. Деплой бота описан в `/opt/SS_COM/DEPLOY.md`.

## Автозапуск

PM2 запускается systemd-сервисом `pm2-administrator.service` (создан через `pm2 startup`), который после reboot восстанавливает список из `~/.pm2/dump.pm2`. Сейчас в нём только `ss-bot`.

```bash
systemctl status pm2-administrator --no-pager
pm2 status
pm2 logs ss-bot --lines 50 --nostream
```

Процессы PM2 должны принадлежать `pm2-administrator.service`:

```bash
ps -eo pid,cgroup:50,args | grep -E 'God Daemon|SS_COM' | grep -v grep
```

Если `pm2` запустить вручную из сессии агента (например, `claude-remote.service`) при остановленном сервисе, демон окажется внутри этой сессии и погибнет при её перезапуске (`KillMode=control-group`). Правильный перезапуск:

```bash
pm2 kill
sudo systemctl start pm2-administrator
```

Сервис привязан к `~/.nvm/versions/node/v24.21.0`. Если эту версию Node удалить или сменить, нужно заново выполнить `pm2 startup` (он выведет команду с `sudo`) и `pm2 save`.

## Вернуть сайты

Список процессов до выключения сайтов сохранён в:

```text
~/.pm2/dump.pm2.before-ss-bot-20260929-164457
```

Запустить сайт и добавить его в автозапуск:

```bash
cd /home/administrator/todo-app && pm2 start server.js --name todo-app
cd /home/administrator/BRIDGE/server && pm2 start index.js --name my-app
pm2 save
```

`todo-app` и `ss-bot` работали на Node 24.21.0, `my-app` — на 24.18.0.

---

# PM2 logs

На VPS уже была проблема, когда PM2 logs заняли около 40 GB.

Главные файлы были:

```text
~/.pm2/pm2.log
~/.pm2/logs/my-app-error.log
```

Проверка:

```bash
du -sh ~/.pm2
du -sh ~/.pm2/logs
ls -lh ~/.pm2/logs
```

Очистить конкретный огромный лог без удаления файла:

```bash
truncate -s 0 ~/.pm2/logs/<application>-error.log
```

PM2 log:

```bash
truncate -s 0 ~/.pm2/pm2.log
```

---

# PM2 log rotation

Модуль `pm2-logrotate` уже установлен и запускается вместе с PM2. Проверить настройки:

```bash
pm2 conf pm2-logrotate
```

Первичная установка:

```bash
pm2 install pm2-logrotate

pm2 set pm2-logrotate:max_size 50M
pm2 set pm2-logrotate:retain 7
pm2 set pm2-logrotate:compress true
```

---

# Node.js / better-sqlite3

На VPS уже возникала ошибка ABI:

```text
better_sqlite3.node was compiled against a different Node.js version
ERR_DLOPEN_FAILED
```

В результате PM2 постоянно перезапускал приложение и быстро увеличивал error log.

Исправление:

```bash
pm2 stop <application>

cd <application-directory>
npm rebuild better-sqlite3

pm2 start <application>
```

Если не хватает build tools:

```bash
sudo apt install -y build-essential python3 make g++
```

---

# Проверка после перезагрузки

```bash
systemctl status pm2-administrator --no-pager
pm2 status
tailscale status
free -h
df -h /
```

# Безопасность

- Не коммитить пароли, токены, приватные SSH-ключи и учётные данные Tailscale.
- Не менять посторонние PM2/web-сервисы, SSH, firewall или Tailscale без отдельной задачи.
- Не открывать VNC/noVNC в публичный интернет при возможном новом развёртывании.
