"""Abstract base for LLM classifiers."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List

from ..sources.base import Email
from ..config import CategoryConfig


@dataclass
class Classification:
    category_id: str
    reasoning: str          # Short one-liner explaining the decision
    success: bool = True    # False = classification failed; pipeline should skip
                            # the email (no db save, no label, no digest entry)
                            # so the next run retries from scratch.


class Classifier(ABC):
    @abstractmethod
    def classify(self, email: Email, categories: List[CategoryConfig]) -> Classification:
        """Return the chosen category + short reasoning."""
        raise NotImplementedError
