"""Tests for pure helpers in obsidian output (no I/O)."""
from tria.outputs.obsidian import (
    _clean_snippet,
    _gmail_url,
    _parse_sender,
    _short_time,
)


class TestParseSender:
    def test_simple_name_email(self):
        name, addr = _parse_sender("Test User <test@example.com>")
        assert name == "Test User"
        assert addr == "test@example.com"

    def test_email_only(self):
        name, addr = _parse_sender("test@example.com")
        assert name == ""
        assert addr == "test@example.com"

    def test_name_with_quotes(self):
        name, addr = _parse_sender('"Quoted Name" <quoted@example.com>')
        assert name == "Quoted Name"
        assert addr == "quoted@example.com"

    def test_blackboard_pattern_inner_email_wins(self):
        """Blackboard puts real sender in display name (quoted), fake in envelope."""
        raw = '"Helio Viana - helio@unipe.edu.br" <do-not-reply@blackboard.com>'
        name, addr = _parse_sender(raw)
        assert name == "Helio Viana"
        assert addr == "helio@unipe.edu.br"

    def test_empty_input(self):
        name, addr = _parse_sender("")
        assert name == ""
        assert addr == ""

    def test_unicode_name(self):
        name, addr = _parse_sender("José Silva <jose@example.com>")
        assert name == "José Silva"
        assert addr == "jose@example.com"


class TestShortTime:
    def test_iso_extracts_hhmm(self):
        assert _short_time("2026-04-28T15:32:10+00:00") == "15:32"

    def test_no_match_returns_input(self):
        assert _short_time("garbage") == "garbage"

    def test_empty(self):
        assert _short_time("") == ""


class TestGmailUrl:
    def test_builds_inbox_url(self):
        url = _gmail_url("abc123")
        assert url == "https://mail.google.com/mail/u/0/#inbox/abc123"

    def test_empty_thread_returns_empty(self):
        assert _gmail_url("") == ""


class TestCleanSnippet:
    def test_collapses_whitespace(self):
        assert _clean_snippet("hello   \n\n\t world") == "hello world"

    def test_truncates_long(self):
        long = "a" * 600
        result = _clean_snippet(long)
        assert len(result) <= 500
        assert result.endswith("...")

    def test_preserves_short(self):
        assert _clean_snippet("hello world") == "hello world"

    def test_empty(self):
        assert _clean_snippet("") == ""

    def test_strips_outer_whitespace(self):
        assert _clean_snippet("   hello   ") == "hello"
