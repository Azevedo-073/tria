"""Tests for SQLite dedup — is_processed + save_classification idempotency."""
import gc

import pytest

from tria import db


@pytest.fixture
def fresh_db(tmp_path):
    """DB temporário gerenciado pelo pytest (tmp_path auto-cleanup).

    gc.collect() no teardown garante que conexões SQLite órfãs sejam
    fechadas antes do cleanup do pytest — necessário no Windows onde
    arquivos com handle aberto não podem ser deletados.
    """
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    yield db_path
    gc.collect()  # libera handles SQLite pendentes (Windows-safe)


class TestIsProcessed:
    def test_unknown_message_not_processed(self, fresh_db):
        with db.get_conn(fresh_db) as conn:
            assert db.is_processed(conn, "never-seen-id") is False

    def test_processed_after_save(self, fresh_db):
        with db.get_conn(fresh_db) as conn:
            run_id = db.start_run(conn, tenant="test")
            db.save_classification(
                conn,
                run_id=run_id,
                message_id="msg-1",
                thread_id="th-1",
                sender="a@b.c",
                subject="Test",
                snippet="Hi",
                received_at="2026-04-28T15:00:00+00:00",
                category_id="important",
                reasoning="test",
            )
            assert db.is_processed(conn, "msg-1") is True

    def test_other_messages_still_unprocessed(self, fresh_db):
        with db.get_conn(fresh_db) as conn:
            run_id = db.start_run(conn, tenant="test")
            db.save_classification(
                conn, run_id=run_id, message_id="msg-1", thread_id="t",
                sender="a", subject="s", snippet="n", received_at="x",
                category_id="spam", reasoning="r",
            )
            assert db.is_processed(conn, "msg-1") is True
            assert db.is_processed(conn, "msg-2") is False


class TestSaveIdempotency:
    def test_duplicate_save_does_not_raise(self, fresh_db):
        """save_classification uses INSERT OR IGNORE — duplicado é silencioso."""
        with db.get_conn(fresh_db) as conn:
            run_id = db.start_run(conn, tenant="test")
            kwargs = dict(
                run_id=run_id, message_id="msg-1", thread_id="t",
                sender="a", subject="s", snippet="n", received_at="x",
                category_id="spam", reasoning="r",
            )
            db.save_classification(conn, **kwargs)
            db.save_classification(conn, **kwargs)  # mesmo message_id

            # Só 1 row na tabela
            cur = conn.execute(
                "SELECT COUNT(*) FROM classifications WHERE message_id = ?",
                ("msg-1",),
            )
            assert cur.fetchone()[0] == 1


class TestRunLifecycle:
    def test_start_and_finish_run(self, fresh_db):
        with db.get_conn(fresh_db) as conn:
            run_id = db.start_run(conn, tenant="marco")
            assert run_id > 0

            db.finish_run(
                conn,
                run_id=run_id,
                emails_fetched=5,
                emails_classified=4,
                status="success",
            )

            cur = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
            row = cur.fetchone()
            assert row["status"] == "success"
            assert row["emails_fetched"] == 5
            assert row["emails_classified"] == 4
            assert row["finished_at"] is not None
