import requests
from bs4 import BeautifulSoup
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


def search_people(name):
    # 1. Buscar links
    params = {"q": name}
    resp = requests.post(SEARCH_ENGINE_URL, data=params)
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
            page = requests.get(url, timeout=5)
            psoup = BeautifulSoup(page.text, "html.parser")
            title = psoup.title.text if psoup.title else url
            desc = "".join([t.text for t in psoup.find_all("p")])[:300]
            score = 0.0
            item = {"titulo": title, "descricao": desc, "link": url}
            # NLP classificação
            if classifier:
                text = f"{title} {desc}"
                pred = classifier(text, CATEGORIES)
                best = pred['labels'][0] if pred['scores'][0] > 0.5 else None
                score = float(pred['scores'][0]) if pred['scores'] else 0.0
                item['score'] = round(score, 3)
                if best:
                    results[best].append(item)
                    continue
            # fallback regras
            if any(s in url for s in SOCIAL_PATTERNS):
                item['score'] = 0.7
                results["Redes Sociais"].append(item)
            elif any(n in url for n in NEWS_PATTERNS):
                item['score'] = 0.6
                results["Notícias"].append(item)
            elif re.search(
                r"curriculo|cv|linkedin|empresa|cargo|profissao",
                url,
                re.I
            ):
                item['score'] = 0.65
                results["Profissional"].append(item)
            elif re.search(
                r"blog|site|personal|portfolio",
                url,
                re.I
            ):
                item['score'] = 0.5
                results["Links Relevantes"].append(item)
            else:
                item['score'] = 0.4
                results["Informações Gerais"].append(item)
        except Exception:
            continue
    return results
