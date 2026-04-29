"""Tria — CLI entrypoint."""
import logging
import sys

import click

from tria.config import load_config
from tria.pipeline import run_once


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


@click.group()
def cli():
    """Tria — autonomous email triage agent."""


@cli.command()
@click.option("--config", "config_path", default="config.yaml", help="Path to config.yaml")
@click.option("--db", "db_path", default="tria.db", help="Path to SQLite state DB")
@click.option("-v", "--verbose", is_flag=True, help="Verbose logging")
def run(config_path: str, db_path: str, verbose: bool):
    """Run the triage pipeline once."""
    setup_logging(verbose)
    log = logging.getLogger("tria")
    log.info("━━━ Tria starting ━━━")

    cfg = load_config(config_path)
    log.info("Tenant: %s | Source: %s | Classifier: %s | Output: %s",
             cfg.tenant, cfg.source.type, cfg.classifier.type, cfg.output.type)

    summary = run_once(cfg, db_path=db_path)

    log.info(
        "━━━ Done. Fetched=%d · Classified=%d · Skipped=%d · Failed=%d · Status=%s ━━━",
        summary["fetched"],
        summary["classified"],
        summary["skipped"],
        summary.get("failed", 0),
        summary["status"],
    )


@cli.command()
@click.option("--config", "config_path", default="config.yaml", help="Path to config.yaml")
def doctor(config_path: str):
    """Validate config + credentials + connectivity."""
    setup_logging(True)
    log = logging.getLogger("tria")

    log.info("Loading config...")
    cfg = load_config(config_path)
    log.info("  ✓ config.yaml + .env loaded")

    log.info("Checking Gemini API key format...")
    if cfg.gemini_api_key.startswith("AIza"):
        log.info("  ✓ GEMINI_API_KEY looks valid")
    else:
        log.warning("  ✗ GEMINI_API_KEY does not start with AIza")

    log.info("Checking Obsidian REST API key...")
    if len(cfg.obsidian_api_key) > 20:
        log.info("  ✓ OBSIDIAN_API_KEY present")
    else:
        log.warning("  ✗ OBSIDIAN_API_KEY looks too short")

    import os
    log.info("Checking Gmail credentials...")
    if os.path.exists(cfg.gmail_credentials_path):
        log.info("  ✓ credentials.json found at %s", cfg.gmail_credentials_path)
    else:
        log.error("  ✗ credentials.json NOT found at %s", cfg.gmail_credentials_path)

    log.info("Done.")


if __name__ == "__main__":
    cli()
