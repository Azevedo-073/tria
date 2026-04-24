"""Gemini classifier — uses Gemini with JSON mode for structured output."""
import json
import re
import time
from typing import List

import google.generativeai as genai

from .base import Classifier, Classification
from ..sources.base import Email
from ..config import CategoryConfig


PROMPT_TEMPLATE = """You are an email triage assistant. Classify the email below into EXACTLY ONE category.

Categories:
{categories_block}

Email metadata:
- From: {sender}
- Subject: {subject}
- Snippet (first chars): {snippet}

Respond with a JSON object ONLY, no markdown fences, no preamble:
{{
  "category_id": "<one of: {category_ids}>",
  "reasoning": "<one short sentence in Portuguese explaining why>"
}}
"""


class GeminiClassifier(Classifier):
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        temperature: float = 0.2,
        redact_patterns: List[str] = None,
    ):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(
            model_name=model,
            generation_config={
                "temperature": temperature,
                "response_mime_type": "application/json",
            },
        )
        self.redact_patterns = [re.compile(p) for p in (redact_patterns or [])]

    def _redact(self, text: str) -> str:
        for pattern in self.redact_patterns:
            text = pattern.sub("[REDACTED]", text)
        return text

    def _call_with_retry(self, prompt: str, max_tries: int = 3):
        """Retry with exponential backoff on ResourceExhausted / transient errors."""
        last_err = None
        for attempt in range(max_tries):
            try:
                return self.model.generate_content(prompt)
            except Exception as e:
                last_err = e
                err_name = type(e).__name__
                # Retry on rate limit / quota / transient errors
                if "Exhausted" in err_name or "Unavailable" in err_name or "DeadlineExceeded" in err_name:
                    wait = 2 ** attempt  # 1, 2, 4 seconds
                    time.sleep(wait)
                    continue
                # Non-retryable error → re-raise immediately
                raise
        # All retries exhausted
        raise last_err

    def classify(self, email: Email, categories: List[CategoryConfig]) -> Classification:
        categories_block = "\n".join(
            f"- {c.id} ({c.emoji} {c.label}): {c.description}" for c in categories
        )
        category_ids = ", ".join(c.id for c in categories)

        prompt = PROMPT_TEMPLATE.format(
            categories_block=categories_block,
            category_ids=category_ids,
            sender=self._redact(email.sender),
            subject=self._redact(email.subject),
            snippet=self._redact(email.snippet),
        )

        try:
            response = self._call_with_retry(prompt)
            raw = response.text.strip()
            data = json.loads(raw)
            category_id = data.get("category_id", "").strip()
            reasoning = data.get("reasoning", "").strip()

            valid_ids = {c.id for c in categories}
            if category_id not in valid_ids:
                category_id = categories[-1].id
                reasoning = f"Categoria inválida retornada ({data.get('category_id')}), fallback aplicado."

            # Polite pacing: stay under 15 RPM free tier
            time.sleep(0.5)

            return Classification(category_id=category_id, reasoning=reasoning)
        except Exception as e:
            return Classification(
                category_id=categories[-1].id,
                reasoning=f"Erro ao classificar: {type(e).__name__}",
            )