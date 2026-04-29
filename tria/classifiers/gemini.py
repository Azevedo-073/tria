"""Gemini classifier — Gemini 2.5 Flash with JSON mode + few-shot examples + retry.

Few-shot strategy:
  - 6 exemplos canônicos cobrem casos ambíguos reais (job-mkt, banco, promo)
  - Especial: 2 exemplos de Catho (vaga real vs upsell promocional) pra
    desambiguar essa fonte que tendia a oscilar entre categorias.

Retry strategy:
  - Exponential backoff em ResourceExhausted/Unavailable/DeadlineExceeded
  - 3 tentativas com sleep 1s → 2s → 4s
  - sleep(0.5) entre chamadas pra respeitar rate limit do free tier
"""
import json
import logging
import re
import time
from typing import List

import google.generativeai as genai

from .base import Classifier, Classification
from ..sources.base import Email
from ..config import CategoryConfig


logger = logging.getLogger("tria.classifier")


# ──────────────────── Few-shot examples ────────────────────
# Cobrem os casos onde zero-shot oscila (especialmente Catho, que aparecia
# em important, read_later E spam dependendo do tipo de notificação).
FEW_SHOT_EXAMPLES = [
    {
        "from": "Banco do Brasil <noreply@bb.com.br>",
        "subject": "Boleto Caixa — Vencimento 30/04",
        "snippet": "Seu boleto no valor de R$ 200,00 vence em 30/04. Pague para evitar juros.",
        "category_id": "important",
        "reasoning": "Cobrança bancária com prazo iminente — ação requerida.",
    },
    {
        "from": "Maria Silva — RH Cobrape <maria.silva@cobrape.com>",
        "subject": "Re: Vaga Programador Junior — próximos passos",
        "snippet": "Marco, gostei do seu CV. Podemos marcar uma conversa essa semana?",
        "category_id": "important",
        "reasoning": "Pessoa real respondendo candidatura específica — resposta requerida.",
    },
    {
        "from": "Substack Daily <newsletter@substack.com>",
        "subject": "Hoje na Substack: 5 ensaios sobre tecnologia",
        "snippet": "Conteúdo curado da semana sobre IA, produtos e startups",
        "category_id": "read_later",
        "reasoning": "Newsletter de conteúdo — ler quando der tempo.",
    },
    {
        "from": "Catho <vagas@catho.com.br>",
        "subject": "5 novas vagas em São Paulo combinam com seu perfil",
        "snippet": "Confira as vagas selecionadas. Atualizamos diariamente.",
        "category_id": "read_later",
        "reasoning": "Alerta automático de vagas — relevante mas não urgente.",
    },
    {
        "from": "Catho <marketing@catho.com.br>",
        "subject": "🔥 Suba 938 posições agora! Salte na frente",
        "snippet": "Por apenas R$ 19,90 garanta destaque no seu CV.",
        "category_id": "spam",
        "reasoning": "Upsell promocional disfarçado de oportunidade — comportamento de spam.",
    },
    {
        "from": "SHEIN <promo@sheinemail.com>",
        "subject": "⚡ 70% OFF só hoje em vestidos!",
        "snippet": "Aproveite descontos exclusivos. Frete grátis acima de R$ 99.",
        "category_id": "spam",
        "reasoning": "Promoção comercial massiva — sem ação requerida.",
    },
]


def _format_examples_block() -> str:
    """Render few-shot examples in the prompt."""
    parts = ["Examples (study these carefully — they show edge cases):"]
    for i, ex in enumerate(FEW_SHOT_EXAMPLES, 1):
        parts.append(f"\nExample {i}:")
        parts.append(f"From: {ex['from']}")
        parts.append(f"Subject: {ex['subject']}")
        parts.append(f"Snippet: {ex['snippet']}")
        parts.append(
            json.dumps(
                {"category_id": ex["category_id"], "reasoning": ex["reasoning"]},
                ensure_ascii=False,
            )
        )
    return "\n".join(parts)


PROMPT_TEMPLATE = """You are an email triage assistant. Classify the email below into EXACTLY ONE category.

Categories:
{categories_block}

Decision principles:
  - "important": real action required by ME (banking, billing, real-person reply, security alert from a service I trust).
  - "read_later": low-urgency content from services I actually use (newsletters, course notifications, job-market alerts that aggregate listings).
  - "spam": promotional pushes, upsells disguised as opportunities, marketplace ads, generic discount blasts, phishing-shaped messages.

Edge cases (read carefully):
  - Same source can land in different categories depending on INTENT of the message
    (e.g., a job site sending real recruiter outreach vs. a paid CV-boost upsell).
  - Job aggregators sending "today's selected jobs" → read_later.
  - Job aggregators pushing "pay R$X to jump ahead" → spam.
  - Banking transactional notice → important; banking marketing newsletter → read_later.

{examples_block}

Now classify this new email:
From: {sender}
Subject: {subject}
Snippet: {snippet}

Respond with a JSON object ONLY, no markdown fences, no preamble:
{{
  "category_id": "<one of: {category_ids}>",
  "reasoning": "<one short sentence in Portuguese explaining why>"
}}
"""


# Erros que valem retry — todos transientes
_RETRYABLE_ERROR_NAMES = {
    "ResourceExhausted",
    "Unavailable",
    "DeadlineExceeded",
    "InternalServerError",
    "ServiceUnavailable",
}


class GeminiClassifier(Classifier):
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        temperature: float = 0.2,
        redact_patterns: List[str] = None,
        max_retries: int = 4,
        request_pacing_seconds: float = 4.0,
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
        self.max_retries = max_retries
        self.request_pacing_seconds = request_pacing_seconds

    def _redact(self, text: str) -> str:
        """Remove PII (CPF, CNPJ, cards) before sending to LLM."""
        for pattern in self.redact_patterns:
            text = pattern.sub("[REDACTED]", text)
        return text

    # Delays grandes pra respeitar a janela de 60s do rate limit do Gemini free tier
    _RETRY_DELAYS = [5, 15, 45, 60]

    def _call_with_retry(self, prompt: str):
        """Call Gemini with long backoff on transient errors (rate-limit aware)."""
        last_exc = None
        for attempt in range(self.max_retries):
            try:
                response = self.model.generate_content(prompt)
                return response
            except Exception as e:
                last_exc = e
                err_name = type(e).__name__
                if err_name not in _RETRYABLE_ERROR_NAMES:
                    # Não-retryable — relança imediatamente
                    raise
                if attempt < self.max_retries - 1:
                    delay = self._RETRY_DELAYS[
                        min(attempt, len(self._RETRY_DELAYS) - 1)
                    ]
                    logger.warning(
                        "Transient error %s, retrying in %ds (attempt %d/%d)",
                        err_name,
                        delay,
                        attempt + 1,
                        self.max_retries,
                    )
                    time.sleep(delay)
                    continue
        # Esgotou retries
        raise last_exc

    def classify(self, email: Email, categories: List[CategoryConfig]) -> Classification:
        # Build category block
        categories_block = "\n".join(
            f"- {c.id} ({c.emoji} {c.label}): {c.description}" for c in categories
        )
        category_ids = ", ".join(c.id for c in categories)
        examples_block = _format_examples_block()

        prompt = PROMPT_TEMPLATE.format(
            categories_block=categories_block,
            category_ids=category_ids,
            examples_block=examples_block,
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

            # If LLM returned invalid category, treat as failure (skip)
            valid_ids = {c.id for c in categories}
            if category_id not in valid_ids:
                return Classification(
                    category_id="",
                    reasoning=(
                        f"Categoria inválida retornada ({data.get('category_id')}). "
                        f"Email será re-tentado na próxima run."
                    ),
                    success=False,
                )

            return Classification(
                category_id=category_id, reasoning=reasoning, success=True
            )
        except Exception as e:
            # Falha persistente — sinaliza skip pra pipeline. NUNCA cair em spam por engano:
            # email com falha não é salvo no SQLite, então a próxima run re-tenta.
            return Classification(
                category_id="",
                reasoning=(
                    f"Erro ao classificar: {type(e).__name__}. "
                    f"Email será re-tentado na próxima run."
                ),
                success=False,
            )
        finally:
            # Rate-limit pacing — fica abaixo dos 10 RPM do Gemini free tier (1 req/6s)
            if self.request_pacing_seconds > 0:
                time.sleep(self.request_pacing_seconds)
