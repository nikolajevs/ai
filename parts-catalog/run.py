"""Launcher: python run.py [serve | crawl | bom | search | analogs | doctor | export].

Without a command it starts the web page on http://127.0.0.1:8086 and opens it in the browser.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from partscat.cli import main  # noqa: E402

if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
