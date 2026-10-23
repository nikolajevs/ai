"""Собрать архив каталога для Windows: программа, пустая база и снимок BOM платы.

Запуск из корня репозитория:

    python parts-catalog/tools/pack_windows.py [--out parts-catalog-windows.zip] [--bom-dir hardware/PCB_EU]

В архив попадают исходники, README, start.bat (переводы строк CRLF), тесты и папка bom/ со снимком файлов платы.
Базы и кэша страниц (data/) в нём нет: каталог создаёт их при первом запуске.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
REPO = APP.parent
TOP = 'parts-catalog'
SKIP_TOP = {'data', 'bom', 'dist', 'tools'}            # рядом с run.py: база, прежний снимок BOM, готовые архивы, этот скрипт
SKIP_ANYWHERE = {'__pycache__', '.pytest_cache'}
SKIP_FILES = {'.gitignore', '.gitattributes'}
SKIP_SUFFIXES = {'.pyc', '.pyo', '.zip', '.db', '.db-wal', '.db-shm'}
# (файл платы, имя в архиве); BOM_summary.json в репозитории лежит в review/
BOM_FILES = (('BOM_allocated.csv', 'BOM_allocated.csv'), ('BOM_allocated.json', 'BOM_allocated.json'),
             ('design.json', 'design.json'), ('review/BOM_summary.json', 'BOM_summary.json'))


def app_files() -> list[Path]:
    found = []
    for path in sorted(APP.rglob('*')):
        relative = path.relative_to(APP)
        if not path.is_file() or relative.parts[0] in SKIP_TOP or SKIP_ANYWHERE & set(relative.parts):
            continue
        if path.name in SKIP_FILES or path.suffix in SKIP_SUFFIXES:
            continue
        found.append(path)
    return found


def git_revision() -> str:
    try:
        out = subprocess.run(['git', '-C', str(REPO), 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        return ''


def as_crlf(data: bytes) -> bytes:
    return data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')


def build(out: Path, bom_dir: Path) -> list[str]:
    missing = [name for name, _ in BOM_FILES if not (bom_dir / name).is_file()]
    if missing:
        raise SystemExit(f'В {bom_dir} нет файлов BOM: {", ".join(missing)}')
    out.parent.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in app_files():
            data = path.read_bytes()
            if path.suffix == '.bat':
                data = as_crlf(data)
            name = f'{TOP}/{path.relative_to(APP).as_posix()}'
            archive.writestr(name, data)
            names.append(name)
        for source, target in BOM_FILES:
            name = f'{TOP}/bom/{target}'
            archive.writestr(name, (bom_dir / source).read_bytes())
            names.append(name)
        note = (f'Снимок {bom_dir.name} из репозитория на {datetime.now(timezone.utc):%Y-%m-%d}'
                + (f', коммит {git_revision()}' if git_revision() else '')
                + '.\nЧтобы обновить, замените файлы или укажите папку hardware/PCB_EU в переменной PARTSCAT_BOM_DIR.\n')
        archive.writestr(f'{TOP}/bom/SNAPSHOT.txt', note.encode('utf-8'))
        names.append(f'{TOP}/bom/SNAPSHOT.txt')
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--out', type=Path, default=APP / 'dist' / 'parts-catalog-windows.zip')
    parser.add_argument('--bom-dir', type=Path, default=REPO / 'hardware' / 'PCB_EU')
    args = parser.parse_args()
    names = build(args.out, args.bom_dir)
    print(f'{args.out}: {len(names)} файлов, {args.out.stat().st_size // 1024} КБ')
    return 0


if __name__ == '__main__':
    sys.exit(main())
