import json
import threading
from pathlib import Path

import pytest

from partscat.http import Response

FIXTURES = Path(__file__).parent / 'fixtures'


def fixture_text(shop: str, name: str) -> str:
    return (FIXTURES / shop / name).read_text(encoding='utf-8')


class FakeClient:
    """Stands in for partscat.http.Client: answers from a {url: text} map and records the calls."""

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.calls = []
        self.min_interval = {}
        self.stop_event = threading.Event()
        self.ttl = 72000.0

    def get(self, url, *, params=None, **kw):
        self.calls.append(('GET', url, params))
        if url not in self.routes:
            raise AssertionError(f'unexpected GET {url} {params}')
        return Response(url=url, status=200, text=self.routes[url])

    def post_json(self, url, payload, **kw):
        self.calls.append(('POST', url, payload))
        answer = self.routes[url]
        text = answer(payload) if callable(answer) else answer
        return Response(url=url, status=200, text=text if isinstance(text, str) else json.dumps(text))


@pytest.fixture()
def fake_client():
    return FakeClient
