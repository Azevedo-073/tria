"""Abstract base for output adapters (Obsidian, Notion, Slack, ...)."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List

from ..sources.base import Email
from ..classifiers.base import Classification
from ..config import CategoryConfig


@dataclass
class TriagedEmail:
    email: Email
    classification: Classification


class Output(ABC):
    @abstractmethod
    def write_digest(
        self,
        triaged: List[TriagedEmail],
        categories: List[CategoryConfig],
    ) -> None:
        """Write (or append) the digest of classified emails to the output target."""
        raise NotImplementedError
