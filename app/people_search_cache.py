from functools import lru_cache

CACHE_SIZE = 32

@lru_cache(maxsize=CACHE_SIZE)
def cached_search(name):
    from .people_scraper import search_people
    return search_people(name)
