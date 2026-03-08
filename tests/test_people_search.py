import types
from bs4 import BeautifulSoup

import pytest

from app.people_scraper import search_people


class DummyResponse:
    def __init__(self, text):
        self.text = text


def test_search_people_basic(monkeypatch):
    # Mock search engine response
    html = '<html><body><a class="result__a" href="http://example.com/profile">Profile</a></body></html>'
    monkeypatch.setattr('app.people_scraper.session', None)

    def fake_post(url, data=None, timeout=None):
        return DummyResponse(html)

    def fake_get(url, timeout=None):
        page_html = '<html><head><title>John Doe - Profile</title></head><body><p>Software engineer at ACME</p></body></html>'
        return DummyResponse(page_html)

    monkeypatch.setattr('requests.post', fake_post)
    monkeypatch.setattr('requests.get', fake_get)

    results = search_people('John Doe')
    assert isinstance(results, dict)
    # Expect at least one category to have an item
    total = sum(len(v) for v in results.values())
    assert total >= 1


def test_search_people_no_name():
    # search_people expects a name but should handle empty gracefully
    res = search_people('')
    assert isinstance(res, dict)

