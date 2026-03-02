"""Tests for app.repository module."""

from __future__ import annotations

from app.repository import Repository


# ── upsert / exists ───────────────────────────────────────────

def test_upsert_item_inserts(repo, sample_item):
    assert repo.upsert_item(sample_item) is True


def test_upsert_item_rejects_duplicate(repo, sample_item):
    repo.upsert_item(sample_item)
    assert repo.upsert_item(sample_item) is False


def test_item_exists_true_after_insert(repo, sample_item):
    assert repo.item_exists(sample_item) is False
    repo.upsert_item(sample_item)
    assert repo.item_exists(sample_item) is True


# ── list_items ─────────────────────────────────────────────────

def test_list_items_returns_inserted(repo, sample_item):
    repo.upsert_item(sample_item)
    items = repo.list_items(item_type="news")
    assert len(items) == 1
    assert items[0]["title"] == sample_item["title"]


def test_list_items_filter_by_type(repo, sample_item):
    repo.upsert_item(sample_item)
    assert repo.list_items(item_type="job") == []


def test_list_items_search(repo, sample_item):
    repo.upsert_item(sample_item)
    assert len(repo.list_items(q="Test")) >= 1


def test_list_items_search_escapes_wildcards(repo, sample_item):
    repo.upsert_item(sample_item)
    # Should not crash even with SQL wildcard chars
    result = repo.list_items(q="100%")
    assert isinstance(result, list)


def test_list_items_empty_db(repo):
    assert repo.list_items() == []


# ── dedupe ─────────────────────────────────────────────────────

def test_dedupe_removes_same_title():
    items = [
        {"item_type": "news", "source": "a", "title": "Same Title",
         "url": "https://a.com/1"},
        {"item_type": "news", "source": "b", "title": "Same Title",
         "url": "https://b.com/2"},
    ]
    deduped = Repository._dedupe_items(items, 10)
    assert len(deduped) == 1


def test_dedupe_keeps_different_titles():
    items = [
        {"item_type": "news", "source": "a", "title": "Title One",
         "url": "https://a.com/1"},
        {"item_type": "news", "source": "b", "title": "Title Two",
         "url": "https://b.com/2"},
    ]
    deduped = Repository._dedupe_items(items, 10)
    assert len(deduped) == 2


def test_dedupe_respects_limit():
    items = [
        {"item_type": "news", "source": "a", "title": f"Title {i}",
         "url": f"https://a.com/{i}"}
        for i in range(20)
    ]
    deduped = Repository._dedupe_items(items, 5)
    assert len(deduped) == 5


# ── ai observability ──────────────────────────────────────────

def test_ai_observability_empty(repo):
    obs = repo.get_ai_observability()
    assert obs["total_items"] == 0
    assert obs["enriched_items"] == 0
    assert obs["fallback_rate_by_hour"] == []
    assert obs["source_accuracy"] == []
    assert obs["reason_breakdown"] == []


def test_ai_observability_with_data(repo, sample_item):
    repo.upsert_item(sample_item)
    obs = repo.get_ai_observability()
    assert obs["total_items"] >= 1


# ── price watches ──────────────────────────────────────────────

def test_add_price_watch(repo):
    watch_id = repo.add_price_watch({
        "name": "Test Watch",
        "product_url": "https://store.example.com/item/1",
        "css_selector": ".price",
        "target_price": 99.90,
        "currency": "BRL",
    })
    assert isinstance(watch_id, int)
    assert watch_id > 0


def test_price_history_empty(repo):
    watch_id = repo.add_price_watch({
        "name": "Test",
        "product_url": "https://store.example.com/item/2",
        "css_selector": None,
        "target_price": 50.0,
        "currency": "BRL",
    })
    history = repo.get_price_history(watch_id)
    assert isinstance(history, list)
