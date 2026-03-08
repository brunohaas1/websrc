import requests
from bs4 import BeautifulSoup
import logging
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import re
from transformers import pipeline

SEARCH_ENGINE_URL = "https://duckduckgo.com/html/"

CATEGORIES = [
    "Informações Gerais",
    "Profissional",
    "Redes Sociais",
    "Notícias",
    "Links Relevantes"
]

SOCIAL_PATTERNS = [
    "linkedin", "instagram", "facebook", "twitter", "tiktok", "youtube"
]
NEWS_PATTERNS = ["news", "noticia", "article"]

MAX_RESULTS = 10

# Carrega pipeline de classificação de texto (zero-shot)
try:
    classifier = pipeline(
        "zero-shot-classification",
        model="facebook/bart-large-mnli"
    )
except Exception:
    classifier = None


# Robust requests session with retries and default headers
USER_AGENT = "websrc-people-search/1.0 (+https://example.com)"
DEFAULT_TIMEOUT = 6  # seconds
MAX_RETRIES = 3

session = None
try:
    session = __import__("requests").Session()
    session.headers.update({"User-Agent": USER_AGENT})
    retries = Retry(
        total=MAX_RETRIES,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
except Exception:
    session = None



def search_people(name):
    params = {"q": name}
    try:
        if session:
            resp = session.post(SEARCH_ENGINE_URL, data=params, timeout=DEFAULT_TIMEOUT)
        else:
            import requests as _requests
            resp = _requests.post(SEARCH_ENGINE_URL, data=params, timeout=DEFAULT_TIMEOUT)
    except Exception:
        logging.exception("search_people: search engine request failed")
        return {cat: [] for cat in CATEGORIES}

    soup = BeautifulSoup(resp.text, "html.parser")
    links = []
    for a in soup.select("a.result__a"):
        href = a.get("href")
        if href and href not in links:
            links.append(href)
        if len(links) >= MAX_RESULTS:
            break

    results = {cat: [] for cat in CATEGORIES}

    # 2. Visitar links e extrair dados
    for url in links:
        try:
            if session:
                page = session.get(url, timeout=DEFAULT_TIMEOUT)
            else:
                import requests as _requests
                page = _requests.get(url, timeout=DEFAULT_TIMEOUT)

            psoup = BeautifulSoup(page.text, "html.parser")
            title = psoup.title.text if psoup.title else url
            desc = "".join([t.text for t in psoup.find_all("p")])[:300]
            item = {"titulo": title, "descricao": desc, "link": url}

            # NLP classificação
            if classifier:
                try:
                    pred = classifier(f"{title} {desc}", CATEGORIES)
                    best = pred['labels'][0] if (pred.get('scores') and pred['scores'][0] > 0.5) else None
                    score = float(pred['scores'][0]) if pred.get('scores') else 0.0
                    item['score'] = round(score, 3)
                    if best:
                        results[best].append(item)
                        continue
                except Exception:
                    logging.debug("search_people: classifier error", exc_info=True)

            # fallback regras
            if any(s in url for s in SOCIAL_PATTERNS):
                item['score'] = item.get('score', 0.7)
                results["Redes Sociais"].append(item)
            elif any(n in url for n in NEWS_PATTERNS):
                item['score'] = item.get('score', 0.6)
                results["Notícias"].append(item)
            elif re.search(r"curriculo|cv|linkedin|empresa|cargo|profissao", url, re.I):
                item['score'] = item.get('score', 0.65)
                results["Profissional"].append(item)
            elif re.search(r"blog|site|personal|portfolio", url, re.I):
                item['score'] = item.get('score', 0.5)
                results["Links Relevantes"].append(item)
            else:
                item['score'] = item.get('score', 0.4)
                results["Informações Gerais"].append(item)

        except Exception:
            logging.debug("search_people: failed to fetch %s", url, exc_info=True)
            continue

    return results
