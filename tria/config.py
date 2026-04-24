"""Configuration loader — merges config.yaml + .env into a typed Config object."""
import os
from dataclasses import dataclass, field
from typing import List, Optional

import yaml
from dotenv import load_dotenv


@dataclass
class CategoryConfig:
    id: str
    emoji: str
    label: str
    description: str


@dataclass
class SourceConfig:
    type: str
    lookback_hours: int = 3
    max_emails_per_run: int = 50


@dataclass
class ClassifierConfig:
    type: str
    model: str
    temperature: float = 0.2


@dataclass
class OutputConfig:
    type: str
    folder: str
    filename_format: str
    append: bool = True


@dataclass
class PrivacyConfig:
    send_body: bool = False
    snippet_chars: int = 300
    redact_patterns: List[str] = field(default_factory=list)


@dataclass
class Config:
    tenant: str
    source: SourceConfig
    classifier: ClassifierConfig
    output: OutputConfig
    categories: List[CategoryConfig]
    privacy: PrivacyConfig
    # Secrets (from env)
    gemini_api_key: str = ""
    obsidian_api_key: str = ""
    obsidian_url: str = "https://127.0.0.1:27124"
    gmail_credentials_path: str = "./credentials.json"
    gmail_token_path: str = "./token.pickle"
    vault_path: str = ""


def load_config(config_path: str = "config.yaml") -> Config:
    """Load tenant config from YAML + secrets from .env."""
    load_dotenv()

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    cfg = Config(
        tenant=raw["tenant"],
        source=SourceConfig(**raw["source"]),
        classifier=ClassifierConfig(**raw["classifier"]),
        output=OutputConfig(**raw["output"]),
        categories=[CategoryConfig(**c) for c in raw["categories"]],
        privacy=PrivacyConfig(**raw["privacy"]),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        obsidian_api_key=os.getenv("OBSIDIAN_API_KEY", ""),
        obsidian_url=os.getenv("OBSIDIAN_URL", "https://127.0.0.1:27124"),
        gmail_credentials_path=os.getenv("GMAIL_CREDENTIALS_PATH", "./credentials.json"),
        gmail_token_path=os.getenv("GMAIL_TOKEN_PATH", "./token.pickle"),
        vault_path=os.getenv("VAULT_PATH", ""),
    )

    # Validation
    if not cfg.gemini_api_key:
        raise ValueError("GEMINI_API_KEY not set in .env")
    if not cfg.obsidian_api_key:
        raise ValueError("OBSIDIAN_API_KEY not set in .env")

    return cfg
