"""Smart Alerts — AI-powered anomaly detection for price drops,
trending spikes, and unusual patterns across dashboard data."""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

from ..config import Config

logger = logging.getLogger(__name__)


class SmartAlertAnalyzer:
    """Analyzes dashboard data and generates intelligent alerts using the local LLM."""

    def __init__(self, app_config: dict | None = None):
        cfg = app_config or {}
        self.enabled = cfg.get("AI_LOCAL_ENABLED", Config.AI_LOCAL_ENABLED)
        self.backend = cfg.get("AI_LOCAL_BACKEND", Config.AI_LOCAL_BACKEND)
        self.url = cfg.get("AI_LOCAL_URL", Config.AI_LOCAL_URL)
        self.model = cfg.get("AI_LOCAL_MODEL", Config.AI_LOCAL_MODEL)
        self.timeout = cfg.get("AI_LOCAL_TIMEOUT_SECONDS", Config.AI_LOCAL_TIMEOUT_SECONDS)
        self.chat_endpoint = cfg.get(
            "AI_LOCAL_LLAMA_CPP_CHAT_ENDPOINT",
            Config.AI_LOCAL_LLAMA_CPP_CHAT_ENDPOINT,
        )

    def _call_llm(self, prompt: str) -> str:
        """Send a chat completion to the local LLM and return text."""
        if self.backend == "llama_cpp":
            endpoint = self.chat_endpoint or "/v1/chat/completions"
            url = f"{self.url.rstrip('/')}{endpoint}"
            resp = requests.post(
                url,
                timeout=self.timeout,
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Você é um assistente de análise de dados. "
                                "Retorne somente JSON válido sem markdown."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.3,
                    "stream": False,
                    "max_tokens": 500,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            choices = resp.json().get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return ""

        # Ollama fallback
        resp = requests.post(
            f"{self.url.rstrip('/')}/api/generate",
            timeout=self.timeout,
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            },
        )
        resp.raise_for_status()
        return resp.json().get("response", "")

    def analyze(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        """Analyze dashboard snapshot and return a list of smart alert dicts.

        Each alert has: type (info|success|warning|danger), title, message, ai_reason
        """
        if not self.enabled:
            return self._fallback_analysis(snapshot)

        try:
            return self._ai_analysis(snapshot)
        except Exception as exc:
            logger.warning("Smart alert AI analysis failed: %s", exc)
            return self._fallback_analysis(snapshot)

    def _ai_analysis(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        """Use LLM for sophisticated pattern detection."""
        # Build compact summary for the LLM
        prices = snapshot.get("prices", [])
        price_summary = []
        for p in prices[:10]:
            price_summary.append({
                "name": p.get("name", "")[:40],
                "last_price": p.get("last_price"),
                "target_price": p.get("target_price"),
                "currency": p.get("currency", "BRL"),
            })

        trending = snapshot.get("trending", [])[:5]
        trending_summary = [
            {"title": t.get("title", "")[:60], "count": t.get("mention_count", 0)}
            for t in trending
        ]

        alert_count = len(snapshot.get("alerts", []))
        monitor_count = len(snapshot.get("service_monitors", []))
        news_count = len(snapshot.get("news", []))

        prompt = f"""Analise os seguintes dados do dashboard e identifique padrões, anomalias ou oportunidades:

PREÇOS MONITORADOS:
{json.dumps(price_summary, ensure_ascii=False)}

TRENDING (mais mencionados):
{json.dumps(trending_summary, ensure_ascii=False)}

Resumo: {news_count} notícias, {alert_count} alertas, {monitor_count} monitores.

Retorne um JSON com a chave "alerts" contendo um array de até 3 alertas inteligentes.
Cada alerta deve ter:
- "type": "info" | "success" | "warning" | "danger"
- "title": título curto (max 60 chars)
- "message": mensagem descritiva (max 150 chars)
- "ai_reason": explicação do padrão detectado (max 200 chars)

Se não houver padrão relevante, retorne {{"alerts": []}}.
Apenas alerte sobre coisas relevantes como: preço abaixo do alvo, spike de menções, anomalias."""

        raw = self._call_llm(prompt)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Try to extract JSON from the response
            import re
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                return []

        alerts = data.get("alerts", [])
        result = []
        for a in alerts[:3]:
            result.append({
                "type": a.get("type", "info"),
                "title": str(a.get("title", ""))[:60],
                "message": str(a.get("message", ""))[:200],
                "ai_reason": str(a.get("ai_reason", ""))[:200],
                "source": "ai",
            })
        return result

    def _fallback_analysis(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        """Rule-based fallback when LLM is unavailable."""
        alerts: list[dict[str, Any]] = []
        prices = snapshot.get("prices", [])

        for p in prices:
            last = p.get("last_price")
            target = p.get("target_price")
            if last is not None and target is not None:
                try:
                    last_f = float(last)
                    target_f = float(target)
                    if last_f <= target_f:
                        alerts.append({
                            "type": "success",
                            "title": f"🎯 {p.get('name', 'Produto')} atingiu o alvo!",
                            "message": f"Preço atual R$ {last_f:.2f} ≤ alvo R$ {target_f:.2f}",
                            "ai_reason": "Preço atingiu ou ficou abaixo do valor alvo configurado.",
                            "source": "rule",
                        })
                    elif target_f > 0 and last_f / target_f < 1.05:
                        alerts.append({
                            "type": "warning",
                            "title": f"📉 {p.get('name', 'Produto')} próximo do alvo",
                            "message": f"Preço R$ {last_f:.2f} está a {((last_f/target_f - 1)*100):.1f}% do alvo",
                            "ai_reason": "Diferença menor que 5% entre preço atual e alvo.",
                            "source": "rule",
                        })
                except (ValueError, TypeError, ZeroDivisionError):
                    pass

        # Trending spike detection
        trending = snapshot.get("trending", [])
        for t in trending[:3]:
            count = t.get("mention_count", 0)
            if count >= 10:
                alerts.append({
                    "type": "info",
                    "title": f"🔥 {t.get('title', 'Tópico')[:35]} em alta",
                    "message": f"{count} menções detectadas — tópico em destaque",
                    "ai_reason": "Volume de menções acima do limiar de 10.",
                    "source": "rule",
                })

        return alerts[:5]
