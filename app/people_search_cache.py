# Cache de buscas para evitar scraping repetido
import hashlib
from functools import lru_cache

CACHE_SIZE = 32

@lru_cache(maxsize=CACHE_SIZE)
def cached_search(name):
    from .people_scraper import search_people
    return search_people(name)

# ...existing code...

# No people_search_routes.py:
# Substituir search_people(name) por cached_search(name)
