"""robots.txt rules with wildcards (RFC 9309), which urllib.robotparser does not understand.

Electrobase forbids '/*?search=' and '/*?sort='; the standard library would read those as literal paths and
allow everything. The rule of the longest matching pattern wins, Allow wins a tie.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit


class Rules:
    def __init__(self, text: str | None, agent: str = 'parts-catalog'):
        self.agent = agent.lower()
        self.allow_all = text is None
        self._rules: list[tuple[str, bool, re.Pattern]] = []   # (pattern, allow, compiled)
        self.crawl_delay: float | None = None
        if text:
            self._parse(text)

    def _parse(self, text: str) -> None:
        groups: list[tuple[list[str], list[tuple[bool, str]], float | None]] = []
        agents: list[str] = []
        rules: list[tuple[bool, str]] = []
        delay: float | None = None
        collecting_agents = False
        for raw in text.splitlines():
            line = raw.split('#', 1)[0].strip()
            if ':' not in line:
                continue
            field, value = (part.strip() for part in line.split(':', 1))
            field = field.lower()
            if field == 'user-agent':
                if not collecting_agents:
                    if agents:
                        groups.append((agents, rules, delay))
                    agents, rules, delay = [], [], None
                collecting_agents = True
                agents.append(value.lower())
            elif field in ('allow', 'disallow'):
                collecting_agents = False
                rules.append((field == 'allow', value))
            elif field == 'crawl-delay':
                collecting_agents = False
                try:
                    delay = float(value)
                except ValueError:
                    pass
        if agents:
            groups.append((agents, rules, delay))
        chosen = self._choose(groups)
        if chosen is None:
            return
        for allow, pattern in chosen[1]:
            if pattern == '' and not allow:      # 'Disallow:' with an empty value allows everything
                continue
            self._rules.append((pattern, allow, _compile(pattern)))
        self.crawl_delay = chosen[2]

    def _choose(self, groups):
        best, best_len = None, -1
        for group in groups:
            for name in group[0]:
                if name != '*' and name and name in self.agent and len(name) > best_len:
                    best, best_len = group, len(name)
        if best is not None:
            return best
        return next((g for g in groups if '*' in g[0]), None)

    def allowed(self, url: str) -> bool:
        if self.allow_all:
            return True
        parts = urlsplit(url)
        target = parts.path or '/'
        if parts.query:
            target += '?' + parts.query
        verdict, best_len = True, -1
        for pattern, allow, compiled in self._rules:
            if compiled.match(target) and (len(pattern) > best_len or (len(pattern) == best_len and allow)):
                verdict, best_len = allow, len(pattern)
        return verdict


def _compile(pattern: str) -> re.Pattern:
    anchored = pattern.endswith('$')
    body = pattern[:-1] if anchored else pattern
    regex = '.*'.join(re.escape(piece) for piece in body.split('*'))
    return re.compile(regex + ('$' if anchored else ''))
