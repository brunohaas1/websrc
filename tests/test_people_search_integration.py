import json
import pytest

from app import create_app


def test_people_search_endpoint(monkeypatch):
    app = create_app(start_scheduler=False)
    client = app.test_client()

    # Stub cached_search to avoid network
    def fake_cached_search(name):
        return {"Informações Gerais": [{"titulo": "Test", "descricao": "Desc", "link": "http://example.com"}]}

    monkeypatch.setattr('app.people_search_cache.cached_search', fake_cached_search)

    resp = client.post('/api/people_search', json={"name": "John Doe"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "Informações Gerais" in data
