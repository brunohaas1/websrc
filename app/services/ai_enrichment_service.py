from __future__ import annotations

from collections import defaultdict, deque
import json
import logging
import re
import time
from typing import Any

import requests


class LocalAIEnricher:
    ALLOWED_TYPES = {
        "news",
        "tech_ai",
        "youtube",
        "job",
        "release",
        "promotion",
    }

    CATEGORIES = [
        "ia",
        "programacao",
        "seguranca",
        "mobile",
        "mercado",
        "guerra_ucrania",
        "guerra_ira",
        "brasil_hoje",
        "open_source",
        "games",
        "outros",
    ]

    KEYWORDS_BY_CATEGORY = {
        "ia": [
            "ia",
            "ai",
            "inteligência artificial",
            "machine learning",
            "llm",
            "chatgpt",
            "modelo",
        ],
        "programacao": [
            "programação",
            "programacao",
            "python",
            "javascript",
            "java",
            "go",
            "framework",
            "backend",
            "frontend",
            "dev",
        ],
        "seguranca": [
            "segurança",
            "seguranca",
            "malware",
            "ransomware",
            "cve",
            "phishing",
            "hacker",
            "vulnerabilidade",
        ],
        "mobile": [
            "android",
            "iphone",
            "ios",
            "smartphone",
            "celular",
            "aplicativo",
            "app",
        ],
        "mercado": [
            "mercado",
            "economia",
            "empresa",
            "startup",
            "investimento",
            "negócio",
            "negocio",
        ],
        "guerra_ucrania": [
            "ucrânia",
            "ucrania",
            "ukraine",
            "zelensky",
            "rússia",
            "russia",
            "putin",
            "kyiv",
        ],
        "guerra_ira": [
            "irã",
            "ira",
            "iran",
            "tehran",
            "israel",
            "oriente médio",
            "oriente medio",
        ],
        "brasil_hoje": [
            "brasil",
            "brasileiro",
            "brasileira",
            "brasilia",
            "governo",
            "senado",
            "stf",
            "câmara",
            "camara",
            "agência brasil",
            "agencia brasil",
        ],
        "open_source": [
            "github",
            "open source",
            "release",
            "repository",
            "repo",
        ],
        "games": [
            "jogo",
            "game",
            "epic",
            "steam",
            "promoção",
            "promocao",
            "grátis",
            "gratis",
        ],
    }

    RELEVANCE_KEYWORDS = {
        "ia",
        "ai",
        "inteligência artificial",
        "inteligencia artificial",
        "machine learning",
        "llm",
        "python",
        "javascript",
        "java",
        "backend",
        "frontend",
        "framework",
        "cve",
        "segurança",
        "seguranca",
        "vulnerabilidade",
        "open source",
        "github",
        "release",
        "trend",
        "tendência",
        "tendencia",
        "dev",
    }

    _source_model_attempts: dict[str, int] = defaultdict(int)
    _source_model_successes: dict[str, int] = defaultdict(int)
    _recent_model_latencies_ms: deque[float] = deque(maxlen=180)
    _recent_model_outcomes: deque[bool] = deque(maxlen=180)
    _circuit_open_until: float = 0.0
    _consecutive_model_failures: int = 0

    def __init__(self, app):
        self.app = app
        self.logger = logging.getLogger(self.__class__.__name__)
        self.enabled = app.config.get("AI_LOCAL_ENABLED", False)
        self.backend = str(
            app.config.get("AI_LOCAL_BACKEND", "ollama"),
        ).strip().lower()
        self.url = app.config.get("AI_LOCAL_URL", "http://127.0.0.1:11434")
        self.llamacpp_chat_endpoint = str(
            app.config.get(
                "AI_LOCAL_LLAMA_CPP_CHAT_ENDPOINT",
                "/v1/chat/completions",
            ),
        )
        self.model = app.config.get("AI_LOCAL_MODEL", "qwen2.5:3b-instruct")
        self.timeout = int(app.config.get("AI_LOCAL_TIMEOUT_SECONDS", 25))
        self.retries = int(app.config.get("AI_LOCAL_RETRIES", 2))
        self.backoff_ms = int(app.config.get("AI_LOCAL_BACKOFF_MS", 400))
        self.circuit_fail_threshold = int(
            app.config.get("AI_LOCAL_CIRCUIT_FAIL_THRESHOLD", 3),
        )
        self.circuit_open_seconds = int(
            app.config.get("AI_LOCAL_CIRCUIT_OPEN_SECONDS", 120),
        )
        self.min_adaptive_per_run = int(
            app.config.get("AI_LOCAL_ADAPTIVE_MIN_PER_RUN", 4),
        )

    @staticmethod
    def _extract_json_text(raw: str) -> str:
        text = str(raw or "").strip()
        if not text:
            return ""

        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text).strip()
            text = re.sub(r"```$", "", text).strip()

        if text.startswith("{") and text.endswith("}"):
            return text

        match = re.search(r"\{[\s\S]*\}", text)
        return match.group(0).strip() if match else text

    def _request_model_raw(self, prompt: str) -> str:
        backend = self.backend or "ollama"

        if backend == "llama_cpp":
            endpoint = self.llamacpp_chat_endpoint or "/v1/chat/completions"
            url = f"{self.url.rstrip('/')}{endpoint}"
            response = requests.post(
                url,
                timeout=self.timeout,
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Retorne somente JSON válido sem markdown."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.1,
                    "stream": False,
                },
            )
            response.raise_for_status()
            payload = response.json()

            choices = payload.get("choices")
            if not isinstance(choices, list) or not choices:
                raise ValueError("Resposta sem choices no llama.cpp")

            message = choices[0].get("message")
            if not isinstance(message, dict):
                raise ValueError("Resposta sem message no llama.cpp")

            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Resposta vazia do llama.cpp")

            return self._extract_json_text(content)

        response = requests.post(
            f"{self.url.rstrip('/')}/api/generate",
            timeout=self.timeout,
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1},
            },
        )
        response.raise_for_status()
        payload = response.json()
        raw = payload.get("response")
        if not raw:
            raise ValueError("Resposta vazia da IA local")
        return self._extract_json_text(str(raw))

    @staticmethod
    def _strip_html(text: str) -> str:
        if not text:
            return ""
        plain = re.sub(r"<[^>]*>", " ", text)
        plain = re.sub(r"\s+", " ", plain)
        return plain.strip()

    def _build_prompt(self, item: dict[str, Any]) -> str:
        title = self._strip_html(str(item.get("title") or ""))
        summary = self._strip_html(str(item.get("summary") or ""))
        source = self._strip_html(str(item.get("source") or ""))
        item_type = self._strip_html(str(item.get("item_type") or ""))

        categories = ", ".join(self.CATEGORIES)
        return (
            "Você é um classificador de notícias/itens de dashboard. "
            "Retorne APENAS JSON válido com as chaves: "
            "summary_one_line, category, relevance_score, reason. "
            "summary_one_line deve ter no máximo 140 caracteres em português; "
            f"category deve ser uma destas: {categories}; "
            "relevance_score deve ser inteiro de 0 a 100. "
            f"Item type: {item_type}. "
            f"Source: {source}. "
            f"Title: {title}. "
            f"Summary: {summary}."
        )

    def _fallback_enrichment(self, item: dict[str, Any]) -> dict[str, Any]:
        title = self._strip_html(str(item.get("title") or ""))
        summary = self._strip_html(str(item.get("summary") or ""))
        source = self._strip_html(str(item.get("source") or ""))
        combined = f"{title} {summary} {source}".lower()

        best_category = "outros"
        best_score = 0
        for category, keywords in self.KEYWORDS_BY_CATEGORY.items():
            matches = sum(1 for keyword in keywords if keyword in combined)
            if matches > best_score:
                best_score = matches
                best_category = category

        relevance = min(100, 35 + best_score * 12)
        one_line = title or (
            summary[:140] if summary else "Sem resumo disponível"
        )
        if len(one_line) > 140:
            one_line = f"{one_line[:137]}..."

        return {
            "summary_one_line": one_line,
            "category": best_category,
            "relevance_score": relevance,
            "reason": "fallback-heuristic",
            "heuristic_matches": best_score,
        }

    def _is_circuit_open(self) -> bool:
        return time.time() < self.__class__._circuit_open_until

    def _register_model_attempt(self, source: str) -> None:
        self.__class__._source_model_attempts[source] += 1

    def _register_model_success(self, source: str, latency_ms: float) -> None:
        self.__class__._source_model_successes[source] += 1
        self.__class__._consecutive_model_failures = 0
        self.__class__._recent_model_outcomes.append(True)
        self.__class__._recent_model_latencies_ms.append(latency_ms)

    def _register_model_failure(self, latency_ms: float | None = None) -> None:
        self.__class__._consecutive_model_failures += 1
        self.__class__._recent_model_outcomes.append(False)
        if latency_ms is not None:
            self.__class__._recent_model_latencies_ms.append(latency_ms)

        if (
            self.__class__._consecutive_model_failures
            >= self.circuit_fail_threshold
        ):
            self.__class__._circuit_open_until = (
                time.time() + self.circuit_open_seconds
            )
            self.logger.warning(
                (
                    "Circuito da IA local aberto por %ss "
                    "após %s falhas consecutivas"
                ),
                self.circuit_open_seconds,
                self.__class__._consecutive_model_failures,
            )

    def _source_success_rate(self, source: str) -> float:
        attempts = self.__class__._source_model_attempts.get(source, 0)
        if attempts <= 0:
            return 0.5
        successes = self.__class__._source_model_successes.get(source, 0)
        return successes / attempts

    def _adjust_score(
        self,
        source: str,
        enrichment: dict[str, Any],
    ) -> tuple[int, int]:
        raw_score = int(enrichment.get("relevance_score") or 0)
        raw_score = max(0, min(100, raw_score))

        success_rate = self._source_success_rate(source)
        source_bonus = round((success_rate - 0.5) * 12)

        heuristic_matches = int(enrichment.get("heuristic_matches") or 0)
        heuristic_bonus = min(8, heuristic_matches * 2)
        if str(enrichment.get("reason") or "").startswith("local-ai"):
            heuristic_bonus = 0

        adjustment = source_bonus + heuristic_bonus
        adjusted = max(0, min(100, raw_score + adjustment))
        return adjusted, adjustment

    def should_enrich(self, item: dict[str, Any]) -> bool:
        item_type = str(item.get("item_type") or "")
        if item_type not in self.ALLOWED_TYPES:
            return False

        if item_type in {"tech_ai", "release", "promotion"}:
            return True

        title = self._strip_html(str(item.get("title") or "")).lower()
        summary = self._strip_html(str(item.get("summary") or "")).lower()
        source = self._strip_html(str(item.get("source") or "")).lower()
        text = f"{title} {summary} {source}"

        matches = sum(
            1 for keyword in self.RELEVANCE_KEYWORDS if keyword in text
        )
        return matches >= 1

    def adaptive_limit(self, base_limit: int, candidate_count: int) -> int:
        if candidate_count <= 0:
            return 0

        limit = max(
            self.min_adaptive_per_run,
            min(base_limit, candidate_count),
        )

        outcomes = list(self.__class__._recent_model_outcomes)
        latencies = list(self.__class__._recent_model_latencies_ms)
        success_rate = (
            sum(1 for value in outcomes if value) / len(outcomes)
            if outcomes
            else 0.6
        )
        avg_latency = (
            sum(latencies) / len(latencies)
            if latencies
            else 0.0
        )

        if self._is_circuit_open():
            return max(2, min(limit, self.min_adaptive_per_run))

        if avg_latency >= 4500 or success_rate < 0.35:
            limit = max(2, int(limit * 0.5))
        elif avg_latency <= 1800 and success_rate >= 0.75:
            limit = min(candidate_count, int(limit * 1.4))

        return max(1, min(candidate_count, limit))

    def _call_local_model(
        self,
        item: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str, float | None]:
        source = str(item.get("source") or "desconhecida").strip().lower()

        if self._is_circuit_open():
            return None, "fallback-circuit-open", None

        self._register_model_attempt(source)

        for attempt in range(self.retries + 1):
            started_at = time.perf_counter()
            try:
                prompt = self._build_prompt(item)
                raw = self._request_model_raw(prompt)

                parsed = json.loads(raw)
                if not isinstance(parsed, dict):
                    raise ValueError("Resposta não é objeto JSON")

                category = str(parsed.get("category") or "outros")
                category = category.strip().lower()
                if category not in self.CATEGORIES:
                    category = "outros"

                summary_one_line = str(
                    parsed.get("summary_one_line") or "",
                ).strip()
                if not summary_one_line:
                    raise ValueError("summary_one_line ausente")
                if len(summary_one_line) > 140:
                    summary_one_line = f"{summary_one_line[:137]}..."

                try:
                    relevance_score = int(parsed.get("relevance_score", 0))
                except (TypeError, ValueError):
                    relevance_score = 0
                relevance_score = max(0, min(100, relevance_score))

                reason = str(parsed.get("reason") or "local-ai").strip()
                latency_ms = (time.perf_counter() - started_at) * 1000
                self._register_model_success(source, latency_ms)

                return (
                    {
                        "summary_one_line": summary_one_line,
                        "category": category,
                        "relevance_score": relevance_score,
                        "reason": reason or "model-output",
                    },
                    "local-ai",
                    latency_ms,
                )
            except Exception as exc:
                latency_ms = (time.perf_counter() - started_at) * 1000
                self._register_model_failure(latency_ms)
                is_last_attempt = attempt >= self.retries

                if not is_last_attempt:
                    backoff_seconds = (
                        self.backoff_ms * (2**attempt)
                    ) / 1000.0
                    time.sleep(backoff_seconds)
                    continue

                self.logger.warning(
                    "IA local indisponível após retries, usando fallback: %s",
                    exc,
                )
                return None, "fallback-model-error", latency_ms

        return None, "fallback-model-error", None

    def enrich_item(self, item: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return item

        if not self.should_enrich(item):
            return item

        extra_raw = item.get("extra")
        extra: dict[str, Any] = (
            dict(extra_raw)
            if isinstance(extra_raw, dict)
            else {}
        )
        if extra.get("ai_summary") and extra.get("ai_category"):
            return item

        source = str(item.get("source") or "desconhecida").strip().lower()
        enrichment, pipeline_reason, latency_ms = self._call_local_model(item)
        if not enrichment:
            enrichment = self._fallback_enrichment(item)
            if pipeline_reason.startswith("fallback-"):
                enrichment["reason"] = pipeline_reason

        adjusted_score, adjustment = self._adjust_score(source, enrichment)

        merged_extra: dict[str, Any] = dict(extra)
        merged_extra.update(
            {
                "ai_summary": enrichment.get("summary_one_line"),
                "ai_category": enrichment.get("category"),
                "ai_score": adjusted_score,
                "ai_score_raw": int(enrichment.get("relevance_score") or 0),
                "ai_score_adjustment": adjustment,
                "ai_reason": (
                    "local-ai"
                    if pipeline_reason == "local-ai"
                    else enrichment.get("reason")
                ),
                "ai_reason_detail": (
                    enrichment.get("reason")
                    if pipeline_reason == "local-ai"
                    else None
                ),
                "ai_model": self.model,
                "ai_latency_ms": round(latency_ms or 0.0, 1),
                "ai_stage": (
                    "model"
                    if pipeline_reason == "local-ai"
                    else "fallback"
                ),
            }
        )

        merged = dict(item)
        merged["extra"] = merged_extra
        return merged
