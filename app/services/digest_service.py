"""Daily AI Digest — uses local LLM to generate top-5 highlights."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from ..config import Config
from ..repository import Repository
from ..utils import json_dumps, json_loads


logger = logging.getLogger(__name__)


class DailyDigestGenerator:
    """Generate a daily digest of top news highlights using the local LLM."""

    def __init__(self, app, repo: Repository):
        self.app = app
        self.repo = repo

    def run(self) -> bool:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Check if digest already exists for today
        existing = self.repo.get_latest_digest()
        if existing and existing.get("digest_date") == today:
            logger.info("Digest already exists for %s", today)
            return False

        # Gather top items from the last 24h
        items = self._gather_items()
        if not items:
            logger.info("No items to generate digest")
            return False

        # Build prompt
        prompt = self._build_prompt(items)

        # Call LLM
        if not Config.AI_LOCAL_ENABLED:
            # Fallback: create simple digest without AI
            content, highlights = self._fallback_digest(items)
        else:
            content, highlights = self._ai_digest(prompt, items)

        self.repo.save_daily_digest(today, content, highlights)
        logger.info("Daily digest generated for %s", today)
        return True

    def _gather_items(self) -> list[dict]:
        """Get recent items for digest generation."""
        news = self.repo.list_items("news", 15)
        tech = self.repo.list_items("tech_ai", 10)
        jobs = self.repo.list_items("job", 5)
        promos = self.repo.list_items("promotion", 5)
        return news + tech + jobs + promos

    def _build_prompt(self, items: list[dict]) -> str:
        summaries = []
        for i, item in enumerate(items[:30], 1):
            title = item.get("title", "")
            source = item.get("source", "")
            summary = item.get("extra", {}).get("ai_summary", "") or item.get("summary", "")
            summaries.append(f"{i}. [{source}] {title}")
            if summary:
                summaries.append(f"   {summary[:150]}")

        items_text = "\n".join(summaries)

        return f"""Você é um assistente de resumo diário. Com base nos títulos e resumos abaixo das últimas 24 horas, crie um resumo diário com os 5 destaques mais importantes.

Itens coletados:
{items_text}

Instruções:
- Escreva em português do Brasil
- Selecione os 5 itens mais relevantes e impactantes
- Para cada destaque, escreva 1-2 frases de resumo
- Formato: numerado de 1 a 5
- Seja conciso e informativo
"""

    def _ai_digest(
        self, prompt: str, items: list[dict],
    ) -> tuple[str, list[dict]]:
        try:
            url = Config.AI_LOCAL_URL.rstrip("/") + Config.AI_LOCAL_LLAMA_CPP_CHAT_ENDPOINT
            payload = {
                "model": Config.AI_LOCAL_MODEL,
                "messages": [
                    {"role": "system", "content": "Você é um assistente de resumo diário de notícias."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 800,
            }
            resp = requests.post(
                url,
                json=payload,
                timeout=Config.AI_LOCAL_TIMEOUT_SECONDS * 2,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

            if content:
                highlights = [
                    {"title": item.get("title", ""), "source": item.get("source", "")}
                    for item in items[:5]
                ]
                return content.strip(), highlights

        except Exception as exc:
            logger.warning("AI digest failed, using fallback: %s", exc)

        return self._fallback_digest(items)

    def _fallback_digest(
        self, items: list[dict],
    ) -> tuple[str, list[dict]]:
        highlights = []
        lines = ["## Destaques do dia\n"]

        for i, item in enumerate(items[:5], 1):
            title = item.get("title", "Sem título")
            source = item.get("source", "")
            summary = (
                item.get("extra", {}).get("ai_summary", "")
                or item.get("summary", "")
                or ""
            )
            lines.append(f"**{i}. {title}** ({source})")
            if summary:
                lines.append(f"   {summary[:200]}")
            lines.append("")
            highlights.append({"title": title, "source": source})

        return "\n".join(lines), highlights
