"""Abstract base for email sources."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List


@dataclass
class Email:
    """Normalized email representation across providers."""
    message_id: str
    thread_id: str
    sender: str
    subject: str
    snippet: str
    received_at: str          # ISO 8601


class Source(ABC):
    @abstractmethod
    def fetch(self, lookback_hours: int, max_results: int) -> List[Email]:
        """Return emails received in the last N hours, up to max_results."""
        raise NotImplementedError
