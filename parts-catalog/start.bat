@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

rem Python: сначала свой в C:\PST\py, потом python из PATH, потом лаунчер py.
set "PY=C:\PST\py\python.exe"
if exist "%PY%" goto have_python
set "PY=python"
python --version >nul 2>&1
if not errorlevel 1 goto have_python
set "PY=py -3"
py -3 --version >nul 2>&1
if not errorlevel 1 goto have_python
echo Python 3.10 или новее не найден. Установите его с python.org и запустите start.bat снова.
pause
exit /b 1

:have_python
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
  echo Нужен Python 3.10 или новее. Найден:
  %PY% --version
  pause
  exit /b 1
)

%PY% -c "import fastapi, uvicorn, jinja2, requests, bs4" >nul 2>&1
if errorlevel 1 (
  echo Устанавливаю библиотеки, один раз, нужен интернет...
  %PY% -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Не удалось установить библиотеки. Установите вручную:
    echo   %PY% -m pip install -r requirements.txt
    pause
    exit /b 1
  )
)

rem Без аргументов запускает страницу http://127.0.0.1:8086 и открывает браузер.
rem start.bat doctor  - проверка установки и связи с магазинами
rem start.bat bom     - проверка BOM в этом окне
%PY% run.py %*
pause
