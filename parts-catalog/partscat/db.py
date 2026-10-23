"""SQLite storage: offers of the four shops, price history, crawl runs.

One connection per operation (SQLite is cheap to open), WAL so that the web page can read while the
crawler writes. No FTS: the catalog holds tens of thousands of rows, a LIKE scan over one folded text
column is fast enough and works on every Python build.
"""
from __future__ import annotations

import contextlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from . import params as params_mod
from .models import Offer
from .normalize import fold, norm_mpn

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS offers (
    id            INTEGER PRIMARY KEY,
    shop          TEXT NOT NULL,
    shop_id       TEXT NOT NULL,
    url           TEXT NOT NULL,
    title         TEXT NOT NULL,
    mpn           TEXT,
    mpn_norm      TEXT NOT NULL DEFAULT '',
    shop_sku      TEXT,
    sku_norm      TEXT NOT NULL DEFAULT '',
    brand         TEXT,
    category      TEXT,
    kind          TEXT NOT NULL DEFAULT 'other',
    pkg           TEXT,
    sale_price    REAL,
    pack_qty      INTEGER NOT NULL DEFAULT 1,
    unit_price    REAL,
    tiers         TEXT NOT NULL DEFAULT '[]',
    stock_qty     INTEGER,
    stock_atleast INTEGER NOT NULL DEFAULT 0,
    stock_text    TEXT,
    stock_state   TEXT NOT NULL DEFAULT 'unknown',
    min_qty       INTEGER NOT NULL DEFAULT 1,
    note          TEXT,
    params        TEXT NOT NULL DEFAULT '{}',
    props         TEXT NOT NULL DEFAULT '{}',
    search_text   TEXT NOT NULL DEFAULT '',
    detail_at     TEXT,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    UNIQUE (shop, shop_id)
);
CREATE INDEX IF NOT EXISTS offers_mpn ON offers (mpn_norm);
CREATE INDEX IF NOT EXISTS offers_sku ON offers (sku_norm);
CREATE INDEX IF NOT EXISTS offers_kind ON offers (kind, pkg);
CREATE INDEX IF NOT EXISTS offers_url ON offers (url);
CREATE TABLE IF NOT EXISTS price_history (
    id          INTEGER PRIMARY KEY,
    offer_id    INTEGER NOT NULL REFERENCES offers (id) ON DELETE CASCADE,
    at          TEXT NOT NULL,
    unit_price  REAL,
    sale_price  REAL,
    stock_qty   INTEGER
);
CREATE INDEX IF NOT EXISTS history_offer ON price_history (offer_id, at);
CREATE TABLE IF NOT EXISTS watch (
    url         TEXT PRIMARY KEY,
    shop        TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    added_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS crawl_runs (
    id          INTEGER PRIMARY KEY,
    plan        TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL,
    stats       TEXT NOT NULL DEFAULT '{}',
    errors      TEXT NOT NULL DEFAULT '[]'
);
"""

JSON_COLUMNS = ('tiers', 'params', 'props')


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def age_days(timestamp: str | None, now: str | None = None) -> float | None:
    """Days between an ISO timestamp from this module and now."""
    if not timestamp:
        return None
    fmt = '%Y-%m-%dT%H:%M:%SZ'
    then = datetime.strptime(timestamp, fmt).replace(tzinfo=timezone.utc)
    current = datetime.strptime(now, fmt).replace(tzinfo=timezone.utc) if now else datetime.now(timezone.utc)
    return (current - then).total_seconds() / 86400


def search_text(offer: Offer, props: dict) -> str:
    parts = [offer.title, offer.mpn, offer.shop_sku, offer.brand, offer.category, offer.shop, *props.values()]
    compact = ' '.join(p for p in (norm_mpn(offer.mpn), norm_mpn(offer.shop_sku)) if p)
    return fold(' '.join(str(p) for p in parts if p) + ' ' + compact)


class Database:
    """Handle to one catalog file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._retire_old_schema()
        with self.conn() as c:
            c.executescript(SCHEMA)
            c.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))

    @contextlib.contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        try:
            connection.execute('PRAGMA journal_mode = WAL')
        except sqlite3.DatabaseError:
            pass
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _retire_old_schema(self) -> None:
        """The first version of the catalog used table 'components'; keep that file aside, start a clean one."""
        if not self.path.exists() or self.path.stat().st_size == 0:
            return
        probe = sqlite3.connect(self.path)
        try:
            tables = {row[0] for row in probe.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        finally:
            probe.close()
        if 'components' in tables and 'offers' not in tables:
            backup = self.path.with_name(self.path.stem + '.v1-backup' + self.path.suffix)
            n = 1
            while backup.exists():
                n += 1
                backup = self.path.with_name(f'{self.path.stem}.v1-backup{n}{self.path.suffix}')
            for suffix in ('', '-wal', '-shm'):
                source = Path(str(self.path) + suffix)
                if source.exists():
                    source.rename(Path(str(backup) + suffix))

    # ---- writing -------------------------------------------------------------------------------------

    def upsert(self, offer: Offer, now: str | None = None) -> tuple[int, str]:
        """Insert or merge one offer. Returns (id, 'new' | 'changed' | 'same').

        A listing row never erases what a product page told earlier (MPN, properties, tiers).
        'changed' means price or stock differ from the last stored values, and then a history row is written.
        """
        now = now or now_iso()
        with self.conn() as c:
            old = c.execute('SELECT * FROM offers WHERE shop = ? AND shop_id = ?', (offer.shop, offer.shop_id)).fetchone()
            props = json.loads(old['props']) if old else {}
            props.update({k: v for k, v in offer.props.items() if v})
            mpn = offer.mpn or (old['mpn'] if old else None)
            sku = offer.shop_sku or (old['shop_sku'] if old else None)
            brand = offer.brand or (old['brand'] if old else None)
            category = offer.category or (old['category'] if old else None)
            tiers = offer.tiers or (json.loads(old['tiers']) if old else [])
            merged = Offer(**{**offer.__dict__, 'mpn': mpn, 'shop_sku': sku, 'brand': brand, 'category': category,
                              'props': props, 'tiers': tiers})
            if old and offer.sale_price is None:      # a page without a readable price keeps the last known one
                merged.sale_price, merged.pack_qty = old['sale_price'], old['pack_qty']
            if old and offer.stock_state == 'unknown':
                merged.stock_qty, merged.stock_atleast = old['stock_qty'], bool(old['stock_atleast'])
                merged.stock_text, merged.stock_state = old['stock_text'], old['stock_state']
            parsed = params_mod.extract(merged.title, props, category)
            record = dict(
                shop=merged.shop, shop_id=merged.shop_id, url=merged.url, title=merged.title,
                mpn=mpn, mpn_norm=norm_mpn(mpn), shop_sku=sku, sku_norm=norm_mpn(sku), brand=brand, category=category,
                kind=parsed.get('kind', 'other'), pkg=parsed.get('pkg'),
                sale_price=merged.sale_price, pack_qty=max(merged.pack_qty, 1), unit_price=merged.unit_price,
                tiers=json.dumps([list(t) for t in tiers]), stock_qty=merged.stock_qty,
                stock_atleast=int(merged.stock_atleast), stock_text=merged.stock_text, stock_state=merged.stock_state,
                min_qty=max(merged.min_qty, 1), note=merged.note, params=json.dumps(parsed, ensure_ascii=False),
                props=json.dumps(props, ensure_ascii=False), search_text=search_text(merged, props),
                last_seen=now,
            )
            if old is None:
                record.update(first_seen=now, detail_at=now if offer.detail else None)
                columns = ', '.join(record)
                marks = ', '.join('?' for _ in record)
                cursor = c.execute(f'INSERT INTO offers ({columns}) VALUES ({marks})', list(record.values()))
                offer_id = cursor.lastrowid
                self._history(c, offer_id, now, record)
                return offer_id, 'new'
            record['detail_at'] = now if offer.detail else old['detail_at']
            assignments = ', '.join(f'{k} = ?' for k in record)
            c.execute(f'UPDATE offers SET {assignments} WHERE id = ?', [*record.values(), old['id']])
            changed = (old['unit_price'], old['stock_qty'], old['stock_state']) != \
                      (record['unit_price'], record['stock_qty'], record['stock_state'])
            if changed:
                self._history(c, old['id'], now, record)
            return old['id'], 'changed' if changed else 'same'

    @staticmethod
    def _history(c: sqlite3.Connection, offer_id: int, now: str, record: dict) -> None:
        c.execute('INSERT INTO price_history (offer_id, at, unit_price, sale_price, stock_qty) VALUES (?, ?, ?, ?, ?)',
                  (offer_id, now, record['unit_price'], record['sale_price'], record['stock_qty']))

    def watch_add(self, url: str, shop: str, note: str = '') -> bool:
        """Put a page on the watch list (refreshed by every BOM / watch run). False when it was already there."""
        with self.conn() as c:
            return c.execute('INSERT OR IGNORE INTO watch (url, shop, note, added_at) VALUES (?, ?, ?, ?)',
                             (url, shop, note, now_iso())).rowcount > 0

    def watch_remove(self, url: str) -> bool:
        with self.conn() as c:
            return c.execute('DELETE FROM watch WHERE url = ?', (url,)).rowcount > 0

    def watch_list(self) -> list[dict]:
        with self.conn() as c:
            return [dict(r) for r in c.execute('SELECT * FROM watch ORDER BY added_at, url')]

    def start_run(self, plan: str) -> int:
        with self.conn() as c:
            return c.execute("INSERT INTO crawl_runs (plan, started_at, status) VALUES (?, ?, 'running')",
                             (plan, now_iso())).lastrowid

    def finish_run(self, run_id: int, status: str, stats: dict, errors: list) -> None:
        with self.conn() as c:
            c.execute('UPDATE crawl_runs SET finished_at = ?, status = ?, stats = ?, errors = ? WHERE id = ?',
                      (now_iso(), status, json.dumps(stats, ensure_ascii=False), json.dumps(errors[-200:], ensure_ascii=False), run_id))

    def close_stale_runs(self) -> int:
        """Runs left 'running' by a killed process are marked interrupted at the next start."""
        with self.conn() as c:
            return c.execute("UPDATE crawl_runs SET status = 'interrupted', finished_at = ? WHERE status = 'running'",
                             (now_iso(),)).rowcount

    # ---- reading -------------------------------------------------------------------------------------

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        item = dict(row)
        for column in JSON_COLUMNS:
            item[column] = json.loads(item[column] or ('[]' if column == 'tiers' else '{}'))
        item['stock_atleast'] = bool(item['stock_atleast'])
        return item

    def offer(self, offer_id: int) -> dict | None:
        with self.conn() as c:
            return self._decode(c.execute('SELECT * FROM offers WHERE id = ?', (offer_id,)).fetchone())

    def find(self, shop: str, shop_id: str) -> dict | None:
        with self.conn() as c:
            return self._decode(c.execute('SELECT * FROM offers WHERE shop = ? AND shop_id = ?', (shop, shop_id)).fetchone())

    def find_by_url(self, url: str) -> dict | None:
        with self.conn() as c:
            return self._decode(c.execute('SELECT * FROM offers WHERE url = ?', (url,)).fetchone())

    def by_mpn(self, mpn: str) -> list[dict]:
        """Offers whose MPN or shop SKU equals the part number after normalization."""
        key = norm_mpn(mpn)
        if not key:
            return []
        with self.conn() as c:
            rows = c.execute('SELECT * FROM offers WHERE mpn_norm = ? OR sku_norm = ? ORDER BY unit_price', (key, key)).fetchall()
        return [self._decode(r) for r in rows]

    def candidates(self, words: list[str], shops: list[str] | None = None, kind: str | tuple[str, ...] | None = None,
                   limit: int = 3000) -> list[dict]:
        """Offers that contain every word (folded) in title, MPN, SKU, brand or category."""
        clauses, args = [], []
        for word in words:
            word_fold = fold(word)
            compact = norm_mpn(word)
            piece = 'search_text LIKE ?'
            args.append(f'%{word_fold}%')
            if len(compact) >= 3:
                piece += ' OR mpn_norm LIKE ? OR sku_norm LIKE ?'
                args.extend([f'%{compact}%', f'%{compact}%'])
            clauses.append(f'({piece})')
        if shops:
            clauses.append(f"shop IN ({', '.join('?' for _ in shops)})")
            args.extend(shops)
        if kind:
            kinds = (kind,) if isinstance(kind, str) else tuple(kind)
            clauses.append(f"kind IN ({', '.join('?' for _ in kinds)})")
            args.extend(kinds)
        where = ' AND '.join(clauses) or '1'
        with self.conn() as c:
            rows = c.execute(f'SELECT * FROM offers WHERE {where} LIMIT ?', [*args, limit]).fetchall()
        return [self._decode(r) for r in rows]

    def by_kind(self, kind: str | tuple[str, ...], shops: list[str] | None = None, pkg: str | None = None) -> list[dict]:
        kinds = (kind,) if isinstance(kind, str) else tuple(kind)
        clauses, args = [f"kind IN ({', '.join('?' for _ in kinds)})"], list(kinds)
        if shops:
            clauses.append(f"shop IN ({', '.join('?' for _ in shops)})")
            args.extend(shops)
        if pkg:
            clauses.append('pkg = ?')
            args.append(pkg)
        with self.conn() as c:
            rows = c.execute(f"SELECT * FROM offers WHERE {' AND '.join(clauses)}", args).fetchall()
        return [self._decode(r) for r in rows]

    def without_detail(self, *, shops: list[str] | None = None, kinds: list[str] | None = None,
                       ids: list[int] | None = None, limit: int = 50, unknown_mpn_only: bool = True) -> list[dict]:
        """Offers whose product page was never read. By default only those whose part number is therefore unknown
        (listing cards carry none at Electrobase and Semikom); with ids given, every unread card among them. In stock first."""
        clauses, args = ['detail_at IS NULL'], []
        if unknown_mpn_only and not ids:
            clauses.append("mpn_norm = ''")
        for column, values in (('shop', shops), ('kind', kinds), ('id', ids)):
            if values:
                clauses.append(f"{column} IN ({', '.join('?' for _ in values)})")
                args.extend(values)
        with self.conn() as c:
            rows = c.execute(f"SELECT * FROM offers WHERE {' AND '.join(clauses)} "
                             "ORDER BY CASE stock_state WHEN 'out' THEN 1 ELSE 0 END, last_seen DESC, id LIMIT ?",
                             [*args, limit]).fetchall()
        return [self._decode(r) for r in rows]

    def history(self, offer_id: int) -> list[dict]:
        with self.conn() as c:
            rows = c.execute('SELECT at, unit_price, sale_price, stock_qty FROM price_history WHERE offer_id = ? ORDER BY at, id',
                             (offer_id,)).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        with self.conn() as c:
            shops = {r['shop']: dict(count=r['n'], detail=r['d'], newest=r['newest'], oldest=r['oldest'])
                     for r in c.execute('SELECT shop, COUNT(*) n, COUNT(detail_at) d, MAX(last_seen) newest, MIN(last_seen) oldest '
                                        'FROM offers GROUP BY shop')}
            kinds = {r['kind']: r['n'] for r in c.execute('SELECT kind, COUNT(*) n FROM offers GROUP BY kind ORDER BY n DESC')}
            total = c.execute('SELECT COUNT(*) FROM offers').fetchone()[0]
            with_mpn = c.execute("SELECT COUNT(*) FROM offers WHERE mpn_norm != ''").fetchone()[0]
        return dict(total=total, with_mpn=with_mpn, shops=shops, kinds=kinds)

    def recent_runs(self, limit: int = 10) -> list[dict]:
        with self.conn() as c:
            rows = c.execute('SELECT * FROM crawl_runs ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item['stats'] = json.loads(item['stats'] or '{}')
            item['errors'] = json.loads(item['errors'] or '[]')
            out.append(item)
        return out

    def rows_for_export(self) -> Iterator[dict]:
        with self.conn() as c:
            for row in c.execute('SELECT * FROM offers ORDER BY shop, category, title'):
                yield self._decode(row)
