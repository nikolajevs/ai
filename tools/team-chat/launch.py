"""Open the room, starting a hidden local server if needed."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import webbrowser

HERE = Path(__file__).resolve().parent
DATA = HERE / '.local'


def running_url():
    try:
        url = next(line[4:] for line in (DATA / 'room.url').read_text(encoding='utf-8').splitlines()
                   if line.startswith('URL='))
        parts = urlsplit(url)
        if parts.scheme != 'http' or parts.hostname != '127.0.0.1' or parts.port != 8767:
            return None
        req = Request('http://127.0.0.1:8767/api/state',
                      headers={'Authorization': 'Bearer ' + parts.fragment})
        with urlopen(req, timeout=1) as response:
            if isinstance(json.load(response).get('messages'), list):
                return url
    except (OSError, ValueError, StopIteration):
        pass
    return None


def main():
    url = running_url()
    if not url:
        DATA.mkdir(exist_ok=True)
        with (DATA / 'server.log').open('ab') as out, (DATA / 'server-error.log').open('ab') as err:
            process = subprocess.Popen([sys.executable, str(HERE / 'server.py')], cwd=HERE,
                                       stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for _ in range(30):
            if process.poll() is not None:
                raise SystemExit('Server failed. See .local/server-error.log (port 8767 may be in use).')
            url = running_url()
            if url:
                (DATA / 'server.pid').write_text(str(process.pid), encoding='ascii')
                break
            time.sleep(.2)
        else:
            raise SystemExit('Server did not start. See .local/server-error.log.')
    webbrowser.open(url)


if __name__ == '__main__':
    main()
