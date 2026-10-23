from partscat.robots import Rules

ELECTROBASE = """
User-agent: *
Content-Signal: search=yes, ai-input=yes, ai-train=no
Disallow: /includes/
Disallow: /search/
Disallow: /cart
Disallow: /*?search=
Disallow: /*&search=
Disallow: /*?sort=
Disallow: /*?items_per_page=

User-agent: Yandex
Disallow: /

User-agent: Claude-User
User-agent: ChatGPT-User
Allow: /
Disallow: /search/
Crawl-delay: 2
"""

BASE = 'https://electrobase.lv'


def test_wildcard_disallow_blocks_search_but_not_paging():
    rules = Rules(ELECTROBASE)
    assert rules.allowed(BASE + '/katalogs/pusvaditaji/tranzistori?page=3')
    assert not rules.allowed(BASE + '/search/node/fdb5800')
    assert not rules.allowed(BASE + '/katalogs/x?search=fdb5800')
    assert not rules.allowed(BASE + '/katalogs/x?page=2&search=fdb5800')
    assert not rules.allowed(BASE + '/katalogs/x?sort=price')
    assert not rules.allowed(BASE + '/katalogs/x?items_per_page=100')
    assert not rules.allowed(BASE + '/cart/checkout')
    assert rules.allowed(BASE + '/')


def test_our_agent_uses_the_star_group_and_no_crawl_delay():
    rules = Rules(ELECTROBASE, agent='parts-catalog')
    assert rules.crawl_delay is None
    assert not rules.allowed(BASE + '/includes/x.js')


def test_a_named_group_is_used_when_the_agent_matches():
    rules = Rules(ELECTROBASE, agent='Claude-User')
    assert rules.crawl_delay == 2
    assert rules.allowed(BASE + '/katalogs/x?sort=price')      # this group has no sort rule
    assert not rules.allowed(BASE + '/search/x')
    blocked = Rules(ELECTROBASE, agent='Yandex')
    assert not blocked.allowed(BASE + '/')


def test_longest_match_wins_and_allow_wins_ties():
    rules = Rules("User-agent: *\nDisallow: /a/\nAllow: /a/b\nDisallow: /c\nAllow: /c\n")
    assert not rules.allowed('https://x.lv/a/z')
    assert rules.allowed('https://x.lv/a/b/1')
    assert rules.allowed('https://x.lv/c')


def test_dollar_anchor():
    rules = Rules("User-agent: *\nDisallow: /*.pdf$\n")
    assert not rules.allowed('https://x.lv/files/a.pdf')
    assert rules.allowed('https://x.lv/files/a.pdf?download=1')


def test_empty_disallow_and_missing_file_allow_everything():
    assert Rules("User-agent: *\nDisallow:\n").allowed('https://x.lv/anything')
    assert Rules(None).allowed('https://x.lv/anything')
    assert Rules('').allowed('https://x.lv/anything')


def test_comments_and_garbage_lines_are_ignored():
    rules = Rules("# hello\nUser-agent: *   # everyone\nDisallow: /private # secret\nnot a rule\n")
    assert not rules.allowed('https://x.lv/private/a')
    assert rules.allowed('https://x.lv/public')
