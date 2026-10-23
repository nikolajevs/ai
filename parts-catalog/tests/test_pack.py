"""The Windows archive: sources and a BOM snapshot, no database, start.bat with CRLF."""
import importlib.util
import zipfile
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parent.parent / 'tools' / 'pack_windows.py'
pytestmark = pytest.mark.skipif(not TOOL.is_file(), reason='tools/ is not part of the Windows archive')


@pytest.fixture
def pack():
    spec = importlib.util.spec_from_file_location('pack_windows', TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def board(tmp_path):
    folder = tmp_path / 'board'
    (folder / 'review').mkdir(parents=True)
    for name in ('BOM_allocated.csv', 'BOM_allocated.json', 'design.json'):
        (folder / name).write_text('x', encoding='utf-8')
    (folder / 'review' / 'BOM_summary.json').write_text('{}', encoding='utf-8')
    return folder


def test_archive_holds_the_program_and_a_bom_snapshot_but_no_data(pack, board, tmp_path):
    out = tmp_path / 'out' / 'pc.zip'
    pack.build(out, board)
    with zipfile.ZipFile(out) as archive:
        names = set(archive.namelist())
        bat = archive.read('parts-catalog/start.bat')
    assert {'parts-catalog/run.py', 'parts-catalog/start.bat', 'parts-catalog/README.md', 'parts-catalog/requirements.txt',
            'parts-catalog/partscat/web.py', 'parts-catalog/partscat/static/htmx.min.js'} <= names
    assert {'parts-catalog/bom/BOM_allocated.csv', 'parts-catalog/bom/BOM_allocated.json', 'parts-catalog/bom/design.json',
            'parts-catalog/bom/BOM_summary.json', 'parts-catalog/bom/SNAPSHOT.txt'} <= names
    assert not [n for n in names if '/data/' in n or '__pycache__' in n or n.endswith(('.db', '.pyc', '.zip'))]
    assert not [n for n in names if n.startswith('parts-catalog/tools/')]
    assert bat.count(b'\r\n') == bat.count(b'\n') > 10
    assert not bat.startswith(b'\xef\xbb\xbf')


def test_missing_bom_file_stops_the_build(pack, board, tmp_path):
    (board / 'design.json').unlink()
    with pytest.raises(SystemExit) as stop:
        pack.build(tmp_path / 'pc.zip', board)
    assert 'design.json' in str(stop.value)
    assert not (tmp_path / 'pc.zip').exists()
