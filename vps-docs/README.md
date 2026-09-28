# KiCad VPS workstation

Удалённая рабочая станция для репозитория `nikolajevs/ai`.

## VPS

- Ubuntu Server 24.04 LTS 64-bit
- 2 CPU cores
- 4 GB RAM
- 4 GB swap
- ~63 GB SSD
- 100 Mbps
- KiCad 10.0.6
- XFCE / X11
- TigerVNC
- noVNC
- Tailscale
- Git
- Python 3

На VPS также работают существующие сайты, Node.js/PM2 и Telegram-бот.

---

## Архитектура

```text
Phone / PC
    |
    | HTTPS через Tailscale
    v
Tailscale Serve
    |
    v
noVNC 127.0.0.1:6080
    |
    v
TigerVNC 127.0.0.1:5901
    |
    v
XFCE / X11
    |
    v
KiCad 10
```

Порты `5901` и `6080` должны слушать только localhost и не должны быть открыты в публичный интернет.

Tailscale Funnel для KiCad не используется.

---

# Удалённый рабочий стол

## Проверка сервисов

```bash
systemctl status kicad-vnc.service --no-pager
systemctl status kicad-novnc.service --no-pager
```

Проверка портов:

```bash
ss -ltnp | grep -E '5901|6080'
```

Ожидается примерно:

```text
127.0.0.1:5901
127.0.0.1:6080
```

## Перезапуск

```bash
sudo systemctl restart kicad-vnc.service
sudo systemctl restart kicad-novnc.service
```

## Логи

```bash
sudo journalctl -u kicad-vnc.service -n 100 --no-pager
sudo journalctl -u kicad-novnc.service -n 100 --no-pager
```

---

# TigerVNC

Сервис:

```text
/etc/systemd/system/kicad-vnc.service
```

Конфигурация:

```ini
[Unit]
Description=KiCad XFCE TigerVNC desktop
After=network.target

[Service]
Type=oneshot
User=administrator
RemainAfterExit=yes
ExecStart=/usr/bin/tigervncserver :1 -localhost yes -geometry 1600x900 -depth 24
ExecStop=/usr/bin/tigervncserver -kill :1

[Install]
WantedBy=multi-user.target
```

XFCE startup:

```text
~/.vnc/xstartup
```

Содержимое:

```sh
#!/bin/sh

unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS

export XDG_SESSION_TYPE=x11
export XDG_CURRENT_DESKTOP=XFCE

exec dbus-launch --exit-with-session startxfce4
```

VNC password задаётся:

```bash
vncpasswd
```

---

# noVNC

Сервис:

```text
/etc/systemd/system/kicad-novnc.service
```

Конфигурация:

```ini
[Unit]
Description=KiCad noVNC web interface
After=kicad-vnc.service
Requires=kicad-vnc.service

[Service]
Type=simple
User=administrator
ExecStart=/usr/share/novnc/utils/novnc_proxy --listen 127.0.0.1:6080 --vnc 127.0.0.1:5901
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

---

# Tailscale

Проверка:

```bash
tailscale status
tailscale ip -4
sudo tailscale serve status
```

noVNC публикуется только внутри tailnet:

```bash
sudo tailscale serve --bg localhost:6080
```

Доступ осуществляется по адресу вида:

```text
https://<hostname>.<tailnet>.ts.net/vnc.html
```

Tailscale Funnel не включать.

---

# KiCad

Версия:

```bash
kicad-cli version
```

Текущая установленная версия:

```text
10.0.6
```

Основной проект:

```text
~/kicad/main/pcb/PCB_V1/PCB_V1.kicad_pro
```

Запуск KiCad из SSH в существующей VNC-сессии:

```bash
DISPLAY=:1 kicad \
  ~/kicad/main/pcb/PCB_V1/PCB_V1.kicad_pro \
  >/tmp/kicad.log 2>&1 &
```

Проверка:

```bash
pgrep -a kicad
```

KiCad специально не запускается автоматически после reboot, чтобы экономить RAM.

---

# Проверка проекта

Основной скрипт:

```text
pcb/check_all.py
```

Запуск:

```bash
cd ~/kicad/main/pcb

KICAD_CLI=/usr/bin/kicad-cli \
KICAD_PYTHON=/usr/bin/python3 \
python3 check_all.py
```

`check_all.py` выполняет в том числе:

- ERC;
- экспорт netlist;
- `verify_netlist.py`;
- электрические расчётные проверки;
- проверку BOM;
- проверку PCB;
- DRC.

Для обновления committed review-файлов:

```bash
python3 check_all.py --write
```

`--write` использовать только намеренно, когда нужно обновить артефакты проекта.

---

# GitHub

Репозиторий:

```text
nikolajevs/ai
```

SSH remote:

```text
git@github-ai:nikolajevs/ai.git
```

Основной checkout на VPS:

```text
~/kicad/main
```

Рабочие деревья:

```text
~/kicad/worktrees/
```

GitHub остаётся источником истины.

---

# SSH для GitHub

Для `nikolajevs/ai` используется отдельный SSH deploy key.

Alias:

```text
github-ai
```

Фрагмент `~/.ssh/config`:

```text
Host github-ai
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_ai
    IdentitiesOnly yes
```

Проверка:

```bash
ssh -T git@github-ai
```

Ожидается:

```text
Hi nikolajevs/ai! You've successfully authenticated...
```

Private SSH key никогда не коммитить в репозиторий.

---

# Git workflow для AI

Основной принцип:

```text
origin/main
    |
    +--- новая task branch
            |
            +--- ChatGPT / Claude
            +--- изменения
            +--- проверки
            +--- commit
            +--- push
            +--- review
            +--- merge
                    |
                    v
                  main
```

AI не должен работать непосредственно в `main`.

Одна задача = одна ветка.

Для параллельной работы желательно использовать отдельный Git worktree для каждой ветки.

Это особенно важно для:

```text
*.kicad_sch
*.kicad_pcb
```

Сложные merge conflicts в этих файлах не следует разрешать автоматически без визуальной проверки.

---

# Обновить main

```bash
cd ~/kicad/main

git fetch origin --prune
git switch main
git pull --ff-only
```

Рекомендуемые настройки:

```bash
git config pull.ff only
git config fetch.prune true
```

---

# Создать новую рабочую ветку

Пример:

```bash
cd ~/kicad/main

git fetch origin --prune
git switch main
git pull --ff-only

git worktree add \
  -b ai/layout-led \
  ~/kicad/worktrees/ai__layout-led \
  origin/main
```

Рабочий каталог:

```text
~/kicad/worktrees/ai__layout-led
```

---

# Подключить ветку, уже созданную AI на GitHub

Сначала:

```bash
cd ~/kicad/main
git fetch origin --prune
```

Затем:

```bash
git worktree add \
  --track \
  -b ai/layout-led \
  ~/kicad/worktrees/ai__layout-led \
  origin/ai/layout-led
```

Если локальная ветка уже существует:

```bash
git worktree add \
  ~/kicad/worktrees/ai__layout-led \
  ai/layout-led
```

---

# Список worktree

```bash
git -C ~/kicad/main worktree list
```

---

# Проверить AI-ветку

Пример:

```bash
cd ~/kicad/worktrees/ai__layout-led/pcb

KICAD_CLI=/usr/bin/kicad-cli \
KICAD_PYTHON=/usr/bin/python3 \
python3 check_all.py
```

---

# Открыть AI-ветку в KiCad

```bash
DISPLAY=:1 kicad \
  ~/kicad/worktrees/ai__layout-led/pcb/PCB_V1/PCB_V1.kicad_pro \
  >/tmp/kicad-ai-layout-led.log 2>&1 &
```

Не следует одновременно редактировать одну и ту же ветку из нескольких открытых KiCad-сессий.

---

# После merge ветки

Обновить main:

```bash
cd ~/kicad/main
git fetch origin --prune
git switch main
git pull --ff-only
```

Удалить старый worktree:

```bash
git worktree remove ~/kicad/worktrees/ai__layout-led
git worktree prune
```

Удалить локальную ветку после merge:

```bash
git branch -d ai/layout-led
```

---

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

Параметр:

```text
vm.swappiness=10
```

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

Рекомендуемая защита:

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

# TigerVNC: display :1 already running

Ошибка:

```text
A X11 server is already running for display :1
```

Проверить реальные процессы:

```bash
pgrep -af 'Xtigervnc|Xorg|Xvnc|Xwayland'
sudo ss -ltnp | grep 5901
```

Проверить lock:

```bash
ls -l /tmp/.X1-lock /tmp/.X11-unix/X1 2>/dev/null
```

Если `Xtigervnc` действительно жив, сначала остановить процесс:

```bash
kill -TERM <PID>
sleep 2
```

Проверить:

```bash
ps -p <PID>
ss -ltnp | grep 5901
```

Только после остановки процесса можно удалить stale lock/socket:

```bash
sudo rm -f /tmp/.X1-lock
sudo rm -f /tmp/.X11-unix/X1
```

Затем:

```bash
sudo systemctl reset-failed kicad-vnc.service
sudo systemctl start kicad-vnc.service
```

---

# noVNC не открывается

Проверить:

```bash
systemctl status kicad-novnc.service --no-pager
ss -ltnp | grep 6080
```

Проверить backend VNC:

```bash
ss -ltnp | grep 5901
```

Проверить Tailscale:

```bash
tailscale status
sudo tailscale serve status
```

---

# KiCad AT-SPI warning

Предупреждение вида:

```text
AT-SPI: Error retrieving accessibility bus address
```

в VNC/XFCE-сессии само по себе не означает сбой KiCad.

Проверить процесс:

```bash
pgrep -a kicad
```

---

# systemd после reboot

Проверить:

```bash
systemctl status kicad-vnc.service --no-pager
systemctl status kicad-novnc.service --no-pager
tailscale status
sudo tailscale serve status
```

---

# Основные правила безопасности

1. Не открывать VNC `5901` в публичный интернет.
2. Не открывать noVNC `6080` в публичный интернет.
3. Не использовать Tailscale Funnel для KiCad.
4. Не коммитить SSH private keys.
5. Не коммитить VNC passwords.
6. Не коммитить GitHub tokens.
7. Не коммитить Tailscale credentials.
8. AI работает только через отдельные ветки.
9. `main` обновляется из GitHub после merge.
10. Перед merge KiCad-изменений запускать проверки проекта.
11. Сложные конфликты `.kicad_sch` и `.kicad_pcb` проверять визуально.

---

# Краткая памятка

Обновить проект:

```bash
cd ~/kicad/main
git fetch origin --prune
git switch main
git pull --ff-only
```

Проверить VPS:

```bash
free -h
df -h /
```

Проверить desktop:

```bash
systemctl status kicad-vnc.service --no-pager
systemctl status kicad-novnc.service --no-pager
```

Проверить Tailscale:

```bash
tailscale status
sudo tailscale serve status
```

Проверить KiCad:

```bash
kicad-cli version
```

Запустить KiCad:

```bash
DISPLAY=:1 kicad \
  ~/kicad/main/pcb/PCB_V1/PCB_V1.kicad_pro \
  >/tmp/kicad.log 2>&1 &
```

Проверить проект:

```bash
cd ~/kicad/main/pcb
KICAD_CLI=/usr/bin/kicad-cli KICAD_PYTHON=/usr/bin/python3 python3 check_all.py
```

---

# AI launchers

На VPS установлены OpenAI Codex CLI и Claude Code.

Безопасный запуск выполняется через wrapper-команды:

```bash
ai-codex <branch>
ai-claude <branch>
```

Примеры:

```bash
ai-codex ai/power-fix
ai-claude ai/layout-led
```

Wrapper:

- обновляет ветки через `git fetch`;
- запрещает работу напрямую в `main`;
- создаёт отдельный worktree в `~/kicad/worktrees/`;
- использует существующую ветку, если она уже есть;
- иначе создаёт новую ветку от `origin/main`;
- запускает агента внутри его worktree.

Codex и Claude могут работать параллельно только в разных ветках/worktree.

После запуска агент должен прочитать `AGENTS.md` и `vps-docs/README.md`.

Проверка KiCad из worktree:

```bash
cd pcb
KICAD_CLI=/usr/bin/kicad-cli \
KICAD_PYTHON=/usr/bin/python3 \
python3 check_all.py
```

Перед push:

```bash
git status
git diff
git push -u origin HEAD
```

После merge worktree можно удалить:

```bash
git -C ~/kicad/main worktree remove ~/kicad/worktrees/<worktree>
git -C ~/kicad/main worktree prune
```
