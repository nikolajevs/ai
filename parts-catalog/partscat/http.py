"""Polite HTTP client: honest user agent, robots.txt, per-host pause, disk cache, visible errors.

Every failure raises FetchError with a kind the crawler can report: robots, banned, blocked, http, network,
stopped. Nothing is swallowed here; the caller decides whether a missing page matters.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import requests

from .robots import Rules

USER_AGENT = 'Mozilla/5.0 (compatible; parts-catalog/2.0; personal BOM price check)'
BAN_COOLDOWN = 600.0


class FetchError(Exception):
    def __init__(self, kind: str, message: str, url: str = '', status: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.url = url
        self.status = status

    def as_dict(self) -> dict:
        return dict(kind=self.kind, message=str(self), url=self.url, status=self.status)


@dataclass
class Response:
    url: str
    status: int
    text: str
    from_cache: bool = False

    def json(self):
        return json.loads(self.text)


class Client:
    def __init__(self, cache_dir: str | Path | None = None, *, user_agent: str = USER_AGENT, respect_robots: bool = True,
                 min_interval: dict[str, float] | None = None, default_interval: float = 2.0, ttl_hours: float = 20.0,
                 timeout: tuple[float, float] = (10, 45), retries: int = 2, session_factory=requests.Session,
                 clock=time.monotonic, sleep=time.sleep):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.user_agent = user_agent
        self.respect_robots = respect_robots
        self.min_interval = {host: value for host, value in (min_interval or {}).items()}
        self.default_interval = default_interval
        self.ttl = ttl_hours * 3600
        self.timeout = timeout
        self.retries = retries
        self._session_factory = session_factory
        self._clock, self._sleep = clock, sleep
        self._sessions: dict[str, requests.Session] = {}
        self._last: dict[str, float] = {}
        self._robots: dict[str, Rules] = {}
        self._cooldown: dict[str, float] = {}
        self._lock = threading.Lock()
        self.stop_event = threading.Event()
        self.stats = dict(requests=0, cache_hits=0, errors=0, bytes=0)

    # ---- public --------------------------------------------------------------------------------------

    def get(self, url: str, *, params: dict | None = None, headers: dict | None = None, ttl_hours: float | None = None,
            check_robots: bool = True) -> Response:
        return self._fetch('GET', url, params=params, headers=headers, ttl_hours=ttl_hours, check_robots=check_robots)

    def post_json(self, url: str, payload: dict, *, headers: dict | None = None, ttl_hours: float | None = None) -> Response:
        return self._fetch('POST', url, payload=payload, headers=headers, ttl_hours=ttl_hours, check_robots=True)

    def host_interval(self, host: str) -> float:
        wanted = self.min_interval.get(host, self.default_interval)
        rules = self._robots.get(host)
        if rules and rules.crawl_delay:
            wanted = max(wanted, rules.crawl_delay)
        return wanted

    # ---- internals -----------------------------------------------------------------------------------

    def _session(self, host: str):
        if host not in self._sessions:
            session = self._session_factory()
            session.headers.update({'User-Agent': self.user_agent, 'Accept-Language': 'lv,en;q=0.8,ru;q=0.6',
                                    'Accept': 'text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8'})
            self._sessions[host] = session
        return self._sessions[host]

    def _fetch(self, method: str, url: str, *, params=None, payload=None, headers=None, ttl_hours=None,
               check_robots=True) -> Response:
        if self.stop_event.is_set():
            raise FetchError('stopped', 'остановлено пользователем', url)
        host = urlsplit(url).netloc
        full = _with_params(url, params)
        key = hashlib.sha1(f'{method} {full} {json.dumps(payload, sort_keys=True) if payload else ""}'.encode()).hexdigest()
        ttl = self.ttl if ttl_hours is None else ttl_hours * 3600
        cached = self._cache_read(host, key, ttl)
        if cached is not None:
            self.stats['cache_hits'] += 1
            return cached
        until = self._cooldown.get(host)
        if until and self._clock() < until:
            raise FetchError('banned', f'{host}: магазин ограничил частоту запросов, пауза ещё {int(until - self._clock())} с', url, 423)
        if check_robots and self.respect_robots and not url.rstrip('/').endswith('/robots.txt'):
            self._ensure_robots(host, url)
            if not self._robots[host].allowed(full):
                raise FetchError('robots', f'{host}: robots.txt запрещает {urlsplit(full).path}', url)
        response = self._send(method, host, full, payload, headers)
        if response.status == 200 and ttl > 0:
            self._cache_write(host, key, response)
        return response

    def _ensure_robots(self, host: str, url: str) -> None:
        if host in self._robots:
            return
        scheme = urlsplit(url).scheme or 'https'
        robots_url = f'{scheme}://{host}/robots.txt'
        cached = self._cache_read(host, hashlib.sha1(f'GET {robots_url} '.encode()).hexdigest(), 24 * 3600)
        if cached is None:
            try:
                cached = self._send('GET', host, robots_url, None, None)
            except FetchError as error:
                if error.kind == 'http' and error.status in (404, 410):
                    self._robots[host] = Rules(None, 'parts-catalog')
                    return
                raise
            if cached.status == 200:
                self._cache_write(host, hashlib.sha1(f'GET {robots_url} '.encode()).hexdigest(), cached)
        self._robots[host] = Rules(cached.text, 'parts-catalog')

    def _send(self, method: str, host: str, url: str, payload, headers) -> Response:
        attempt = 0
        while True:
            self._pause(host)
            self.stats['requests'] += 1
            try:
                reply = self._request(method, host, url, payload, headers)
                # some shops answer a first visit with a tiny script that sets a cookie and reloads the page
                for _ in range(2):
                    if _is_js_gate(reply.text):
                        reply = self._request(method, host, url, payload, headers)
                    else:
                        break
            except requests.RequestException as error:
                self.stats['errors'] += 1
                if isinstance(error, requests.exceptions.ProxyError) and '403' in str(error):
                    raise FetchError('blocked', f'{host}: сетевая политика среды запрещает этот адрес (прокси ответил 403); '
                                                 'его нужно разрешить в настройках среды', url, 403) from error
                if attempt < self.retries:
                    attempt += 1
                    self._sleep(2.0 * attempt)
                    continue
                raise FetchError('network', f'{host}: {_describe(error)}', url) from error
            status = reply.status_code
            text = _decode(reply)
            if status == 423 or (status == 403 and 'banned' in text[:200].lower()):
                self._cooldown[host] = self._clock() + BAN_COOLDOWN
                self.stats['errors'] += 1
                raise FetchError('banned', f'{host}: {text.strip()[:80] or "доступ ограничен"} (HTTP {status})', url, status)
            if status in (429, 502, 503, 504) and attempt < self.retries:
                attempt += 1
                wait = _retry_after(reply.headers.get('Retry-After')) or 5.0 * attempt
                self._sleep(min(wait, 60.0))
                continue
            if status == 403 and _proxy_denied(reply):
                self.stats['errors'] += 1
                raise FetchError('blocked', f'{host}: запрос запрещён сетевой политикой среды (HTTP 403), адрес нужно разрешить в настройках среды', url, status)
            if status >= 400:
                self.stats['errors'] += 1
                raise FetchError('http', f'{host}: HTTP {status}', url, status)
            self.stats['bytes'] += len(reply.content)
            return Response(url=str(reply.url), status=status, text=text)

    def _request(self, method: str, host: str, url: str, payload, headers):
        session = self._session(host)
        if method == 'POST':
            return session.post(url, json=payload, headers=headers, timeout=self.timeout)
        return session.get(url, headers=headers, timeout=self.timeout)

    def _pause(self, host: str) -> None:
        with self._lock:
            interval = self.host_interval(host)
            wait = self._last.get(host, -1e9) + interval - self._clock()
            if wait > 0:
                self._sleep(wait)
            self._last[host] = self._clock()

    # ---- cache ---------------------------------------------------------------------------------------

    def _cache_path(self, host: str, key: str) -> Path | None:
        if not self.cache_dir:
            return None
        return self.cache_dir / re.sub(r'[^A-Za-z0-9.-]', '_', host) / f'{key}.json.gz'

    def _cache_read(self, host: str, key: str, ttl: float) -> Response | None:
        path = self._cache_path(host, key)
        if not path or ttl <= 0 or not path.exists():
            return None
        if time.time() - path.stat().st_mtime > ttl:
            return None
        try:
            with gzip.open(path, 'rt', encoding='utf-8') as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return None
        return Response(url=data['url'], status=data['status'], text=data['text'], from_cache=True)

    def _cache_write(self, host: str, key: str, response: Response) -> None:
        path = self._cache_path(host, key)
        if not path:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        with gzip.open(tmp, 'wt', encoding='utf-8') as handle:
            json.dump(dict(url=response.url, status=response.status, text=response.text), handle)
        tmp.replace(path)


def _with_params(url: str, params: dict | None) -> str:
    if not params:
        return url
    return requests.Request('GET', url, params=params).prepare().url


def _decode(reply) -> str:
    content_type = reply.headers.get('Content-Type', '').lower()
    if 'charset' in content_type:
        return reply.text
    return reply.content.decode('utf-8', 'replace')


def _is_js_gate(text: str) -> bool:
    return len(text) < 400 and 'document.location' in text and 'setTimeout' in text


def _retry_after(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None


def _proxy_denied(reply) -> bool:
    text = _decode(reply)[:300].lower()
    return 'not allowed' in text or 'blocked by' in text or 'policy' in text


def _describe(error: Exception) -> str:
    text = str(error)
    return re.sub(r'\s+', ' ', text)[:200] or error.__class__.__name__
