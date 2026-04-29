"""Pipeline orchestrator — wires Source + Classifier + Output together."""
import logging
from typing import List

from .config import Config
from .sources.base import Source
from .sources.gmail import GmailSource
from .classifiers.base import Classifier
from .classifiers.gemini import GeminiClassifier
from .outputs.base import Output, TriagedEmail
from .outputs.obsidian import ObsidianOutput
from . import db


logger = logging.getLogger("tria")


def build_source(cfg: Config) -> Source:
    if cfg.source.type == "gmail":
        return GmailSource(
            credentials_path=cfg.gmail_credentials_path,
            token_path=cfg.gmail_token_path,
        )
    raise ValueError(f"Unknown source type: {cfg.source.type}")


def build_classifier(cfg: Config) -> Classifier:
    if cfg.classifier.type == "gemini":
        return GeminiClassifier(
            api_key=cfg.gemini_api_key,
            model=cfg.classifier.model,
            temperature=cfg.classifier.temperature,
            redact_patterns=cfg.privacy.redact_patterns,
        )
    raise ValueError(f"Unknown classifier type: {cfg.classifier.type}")


def build_output(cfg: Config) -> Output:
    if cfg.output.type == "obsidian":
        return ObsidianOutput(
            api_key=cfg.obsidian_api_key,
            base_url=cfg.obsidian_url,
            folder=cfg.output.folder,
            filename_format=cfg.output.filename_format,
            append=cfg.output.append,
            write_canvas=cfg.output.write_canvas,
            canvas_filename=cfg.output.canvas_filename,
        )
    raise ValueError(f"Unknown output type: {cfg.output.type}")


def run_once(cfg: Config, db_path: str = "tria.db") -> dict:
    """Run the full pipeline once. Returns a summary dict."""
    db.init_db(db_path)
    conn = db.get_conn(db_path)
    run_id = db.start_run(conn, cfg.tenant)

    try:
        source = build_source(cfg)
        classifier = build_classifier(cfg)
        output = build_output(cfg)

        logger.info("Fetching emails...")
        emails = source.fetch(
            lookback_hours=cfg.source.lookback_hours,
            max_results=cfg.source.max_emails_per_run,
        )
        logger.info("Fetched %d emails.", len(emails))

        # Dedup — skip already-classified messages
        fresh = [e for e in emails if not db.is_processed(conn, e.message_id)]
        skipped = len(emails) - len(fresh)
        if skipped:
            logger.info("Skipping %d already-processed emails.", skipped)

        # Map category_id → label.label pra montar "Tria/{Categoria}"
        cat_by_id = {c.id: c for c in cfg.categories}

        triaged: List[TriagedEmail] = []
        skipped_failures = 0
        for email in fresh:
            classification = classifier.classify(email, cfg.categories)

            # Falha persistente — NÃO salva, NÃO aplica label, NÃO entra no digest.
            # Próxima run re-tenta do zero (sem registro no SQLite = não dedupa).
            if not classification.success:
                skipped_failures += 1
                logger.warning(
                    "  [SKIP] %s — %s — %s",
                    email.subject[:60],
                    email.sender[:40],
                    classification.reasoning,
                )
                continue

            db.save_classification(
                conn,
                run_id=run_id,
                message_id=email.message_id,
                thread_id=email.thread_id,
                sender=email.sender,
                subject=email.subject,
                snippet=email.snippet,
                received_at=email.received_at,
                category_id=classification.category_id,
                reasoning=classification.reasoning,
            )
            triaged.append(TriagedEmail(email=email, classification=classification))
            logger.info(
                "  [%s] %s — %s",
                classification.category_id,
                email.subject[:60],
                email.sender[:40],
            )

            # Aplica label no Gmail (se habilitado e source suportar)
            if cfg.source.apply_labels and hasattr(source, "apply_label"):
                cat = cat_by_id.get(classification.category_id)
                if cat:
                    label_name = f"{cfg.source.label_prefix}/{cat.label}"
                    try:
                        source.apply_label(email.message_id, label_name)
                        logger.info("    ↳ label applied: %s", label_name)
                    except Exception as exc:
                        # Não falha o pipeline por causa de label — só loga
                        logger.warning(
                            "    ↳ failed to apply label %s: %s", label_name, exc
                        )

        if triaged:
            logger.info("Writing digest to Obsidian...")
            output.write_digest(triaged, cfg.categories)
        else:
            logger.info("No new emails to digest.")

        db.finish_run(
            conn,
            run_id=run_id,
            emails_fetched=len(emails),
            emails_classified=len(triaged),
            status="success",
        )

        return {
            "run_id": run_id,
            "fetched": len(emails),
            "classified": len(triaged),
            "skipped": skipped,
            "failed": skipped_failures,
            "status": "success",
        }
    except Exception as e:
        logger.exception("Pipeline failed")
        db.finish_run(
            conn,
            run_id=run_id,
            emails_fetched=0,
            emails_classified=0,
            status="error",
            error_message=str(e),
        )
        raise
    finally:
        conn.close()
