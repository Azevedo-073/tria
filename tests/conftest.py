"""Pytest fixtures and shared helpers."""
import os
import sys
from typing import List

import pytest

# Garante que o pacote `tria` é importável quando rodando `pytest` da raiz
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tria.classifiers.base import Classification
from tria.config import CategoryConfig
from tria.outputs.base import TriagedEmail
from tria.sources.base import Email


@pytest.fixture
def categories() -> List[CategoryConfig]:
    """Default 3-category setup matching production config.yaml."""
    return [
        CategoryConfig(
            id="important",
            emoji="🔴",
            label="Importante",
            description="Banco, trabalho, pessoa real",
        ),
        CategoryConfig(
            id="read_later",
            emoji="🟡",
            label="Pra ler",
            description="Newsletter, notificação, conteúdo",
        ),
        CategoryConfig(
            id="spam",
            emoji="⚫",
            label="Spam / Lixo",
            description="Promoção, scam, automático",
        ),
    ]


def make_email(
    message_id: str = "msg123",
    thread_id: str = "thread456",
    sender: str = "Test <test@example.com>",
    subject: str = "Test subject",
    snippet: str = "Test snippet content",
    received_at: str = "2026-04-28T15:30:00+00:00",
) -> Email:
    """Factory pra Email — defaults sãos pra simplificar testes."""
    return Email(
        message_id=message_id,
        thread_id=thread_id,
        sender=sender,
        subject=subject,
        snippet=snippet,
        received_at=received_at,
    )


def make_triaged(
    category_id: str = "read_later",
    reasoning: str = "Default reasoning",
    success: bool = True,
    **email_kwargs,
) -> TriagedEmail:
    """Factory pra TriagedEmail — combina email + classification."""
    return TriagedEmail(
        email=make_email(**email_kwargs),
        classification=Classification(
            category_id=category_id, reasoning=reasoning, success=success
        ),
    )
