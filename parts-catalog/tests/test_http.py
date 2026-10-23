import pytest
import requests

from partscat.http import Client, FetchError

ROBOTS = 'User-agent: *\nDisallow: /search/\nDisallow: /*?sort=\n'


class FakeReply:
    def __init__(self, status=200, text='', headers=None, url='https://x.lv/'):
        self.status_code = status
        self.text = text
        self.content = text.encode()
        self.headers = {'Content-Type': 'text/html; charset=utf-8', **(headers or {})}
        self.url = url


class FakeSession:
    """Answers from a dict {url: reply or list of replies}; records every call."""
    calls: list = []
    routes: dict = {}

    def __init__(self):
        self.headers = {}

    def _answer(self, method, url):
        FakeSession.calls.append((method, url))
        route = FakeSession.routes.get(url)
        if route is None:
            return FakeReply(404, 'not found', url=url)
        if isinstance(route, list):
            reply = route.pop(0) if len(route) > 1 else route[0]
        else:
            reply = route
        if isinstance(reply, Exception):
            raise reply
        reply.url = url
        return reply

    def get(self, url, headers=None, timeout=None):
        return self._answer('GET', url)

    def post(self, url, json=None, headers=None, timeout=None):
        return self._answer('POST', url)


@pytest.fixture()
def world():
    FakeSession.calls, FakeSession.routes = [], {'https://x.lv/robots.txt': FakeReply(200, ROBOTS)}
    clock = {'t': 1000.0}
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock['t'] += seconds

    return FakeSession, clock, sleeps, sleep


def client(world, tmp_path=None, **kw):
    session, clock, sleeps, sleep = world
    return Client(tmp_path, session_factory=session, clock=lambda: clock['t'], sleep=sleep, retries=1, **kw)


def test_get_returns_text_and_sends_robots_first(world):
    FakeSession.routes['https://x.lv/a'] = FakeReply(200, '<p>hi</p>')
    c = client(world)
    assert c.get('https://x.lv/a').text == '<p>hi</p>'
    assert [u for _, u in FakeSession.calls] == ['https://x.lv/robots.txt', 'https://x.lv/a']


def test_robots_blocks_without_touching_the_page(world):
    c = client(world)
    with pytest.raises(FetchError) as caught:
        c.get('https://x.lv/search/fdb5800')
    assert caught.value.kind == 'robots'
    with pytest.raises(FetchError):
        c.get('https://x.lv/cat?sort=price')
    assert ('GET', 'https://x.lv/search/fdb5800') not in FakeSession.calls


def test_missing_robots_means_allowed(world):
    del FakeSession.routes['https://x.lv/robots.txt']
    FakeSession.routes['https://x.lv/search/a'] = FakeReply(200, 'ok')
    assert client(world).get('https://x.lv/search/a').text == 'ok'


def test_pause_between_requests_to_one_host(world):
    FakeSession.routes['https://x.lv/a'] = FakeReply(200, 'a')
    FakeSession.routes['https://x.lv/b'] = FakeReply(200, 'b')
    c = client(world, min_interval={'x.lv': 3.0})
    c.get('https://x.lv/a')
    c.get('https://x.lv/b')
    assert max(world[2]) == pytest.approx(3.0)


def test_cache_avoids_the_second_request(world, tmp_path):
    FakeSession.routes['https://x.lv/a'] = FakeReply(200, 'first')
    c = client(world, tmp_path)
    assert not c.get('https://x.lv/a').from_cache
    FakeSession.routes['https://x.lv/a'] = FakeReply(200, 'second')
    again = c.get('https://x.lv/a')
    assert again.from_cache and again.text == 'first' and c.stats['cache_hits'] == 1
    assert c.get('https://x.lv/a', ttl_hours=0).text == 'second'


def test_js_gate_is_retried_at_once(world):
    gate = FakeReply(200, '<script>window.setTimeout(function(){document.location.href = "/a";}, 5);</script>')
    FakeSession.routes['https://x.lv/a'] = [gate, FakeReply(200, 'real page')]
    assert client(world).get('https://x.lv/a').text == 'real page'


def test_423_is_a_ban_and_the_host_cools_down(world):
    FakeSession.routes['https://x.lv/a'] = FakeReply(423, 'Banned (1.2.3.4)')
    c = client(world)
    with pytest.raises(FetchError) as caught:
        c.get('https://x.lv/a')
    assert caught.value.kind == 'banned' and caught.value.status == 423
    calls = len(FakeSession.calls)
    with pytest.raises(FetchError) as again:
        c.get('https://x.lv/b')
    assert again.value.kind == 'banned' and len(FakeSession.calls) == calls     # no new request
    world[1]['t'] += 700
    FakeSession.routes['https://x.lv/b'] = FakeReply(200, 'b')
    assert c.get('https://x.lv/b').text == 'b'


def test_429_waits_for_retry_after_then_succeeds(world):
    FakeSession.routes['https://x.lv/a'] = [FakeReply(429, 'slow down', {'Retry-After': '7'}), FakeReply(200, 'ok')]
    c = client(world)
    assert c.get('https://x.lv/a').text == 'ok'
    assert 7.0 in world[2]


def test_404_is_an_http_error_with_status(world):
    with pytest.raises(FetchError) as caught:
        client(world).get('https://x.lv/missing')
    assert caught.value.kind == 'http' and caught.value.status == 404


def test_network_error_after_retries(world):
    FakeSession.routes['https://x.lv/a'] = requests.ConnectionError('boom')
    with pytest.raises(FetchError) as caught:
        client(world).get('https://x.lv/a')
    assert caught.value.kind == 'network'


def test_proxy_403_is_reported_as_blocked(world):
    FakeSession.routes['https://x.lv/a'] = requests.exceptions.ProxyError('Tunnel connection failed: 403 Forbidden')
    with pytest.raises(FetchError) as caught:
        client(world).get('https://x.lv/a')
    assert caught.value.kind == 'blocked'


def test_stop_event_aborts(world):
    c = client(world)
    c.stop_event.set()
    with pytest.raises(FetchError) as caught:
        c.get('https://x.lv/a')
    assert caught.value.kind == 'stopped'


def test_post_json_uses_post_and_robots(world):
    FakeSession.routes['https://x.lv/graphql'] = FakeReply(200, '{"data": {"ok": 1}}')
    reply = client(world).post_json('https://x.lv/graphql', {'query': '{ok}'})
    assert reply.json() == {'data': {'ok': 1}}
    assert ('POST', 'https://x.lv/graphql') in FakeSession.calls


def test_crawl_delay_from_robots_raises_the_interval(world):
    FakeSession.routes['https://x.lv/robots.txt'] = FakeReply(200, 'User-agent: *\nCrawl-delay: 6\n')
    FakeSession.routes['https://x.lv/a'] = FakeReply(200, 'a')
    c = client(world, min_interval={'x.lv': 1.0})
    c.get('https://x.lv/a')
    assert c.host_interval('x.lv') == 6.0
