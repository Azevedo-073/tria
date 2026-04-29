"""Tests for build_canvas_json — pure function, deterministic output."""
import json

from tria.outputs.obsidian import build_canvas_json
from tests.conftest import make_triaged


class TestCanvasJsonStructure:
    def test_returns_valid_json(self, categories):
        triaged = [make_triaged(category_id="important")]
        out = build_canvas_json(triaged, categories, "15h32", "2026-04-28")
        parsed = json.loads(out)  # raises if invalid
        assert "nodes" in parsed
        assert "edges" in parsed

    def test_edges_is_empty_list(self, categories):
        out = build_canvas_json([], categories, "15h32", "2026-04-28")
        assert json.loads(out)["edges"] == []

    def test_node_count_matches_input(self, categories):
        """1 banner + 3 column headers + N email cards."""
        triaged = [
            make_triaged(category_id="important", message_id="m1"),
            make_triaged(category_id="read_later", message_id="m2"),
            make_triaged(category_id="spam", message_id="m3"),
        ]
        out = build_canvas_json(triaged, categories, "15h32", "2026-04-28")
        nodes = json.loads(out)["nodes"]
        assert len(nodes) == 1 + 3 + 3  # banner + 3 col headers + 3 cards

    def test_empty_triaged_still_renders_columns(self, categories):
        """Even with 0 emails, banner + column headers should render."""
        out = build_canvas_json([], categories, "15h32", "2026-04-28")
        nodes = json.loads(out)["nodes"]
        assert len(nodes) == 1 + 3  # banner + 3 column headers (no email cards)


class TestCanvasBanner:
    def test_banner_is_first_node(self, categories):
        out = build_canvas_json([], categories, "15h32", "2026-04-28")
        nodes = json.loads(out)["nodes"]
        assert nodes[0]["id"] == "banner"

    def test_banner_includes_run_label_and_date(self, categories):
        out = build_canvas_json([], categories, "15h32", "2026-04-28")
        nodes = json.loads(out)["nodes"]
        assert "15h32" in nodes[0]["text"]
        assert "2026-04-28" in nodes[0]["text"]

    def test_banner_summary_counts(self, categories):
        triaged = [
            make_triaged(category_id="important", message_id="m1"),
            make_triaged(category_id="important", message_id="m2"),
            make_triaged(category_id="spam", message_id="m3"),
        ]
        out = build_canvas_json(triaged, categories, "15h32", "2026-04-28")
        banner = json.loads(out)["nodes"][0]
        assert "🔴 2" in banner["text"]
        assert "🟡 0" in banner["text"]
        assert "⚫ 1" in banner["text"]


class TestCanvasColumns:
    def test_column_headers_have_correct_color(self, categories):
        out = build_canvas_json([], categories, "15h32", "2026-04-28")
        nodes = json.loads(out)["nodes"]
        headers = {n["id"]: n for n in nodes if n["id"].startswith("col-")}
        assert headers["col-important"]["color"] == "1"   # red
        assert headers["col-read_later"]["color"] == "3"  # yellow
        # spam has no color set (default gray) — key may be absent
        assert "color" not in headers["col-spam"] or headers["col-spam"]["color"] == ""

    def test_column_x_positions_increase(self, categories):
        out = build_canvas_json([], categories, "15h32", "2026-04-28")
        nodes = json.loads(out)["nodes"]
        headers = sorted(
            (n for n in nodes if n["id"].startswith("col-")),
            key=lambda n: n["x"],
        )
        # Sequence x = 0, 450, 900 (column width 420 + gap 30)
        assert [h["x"] for h in headers] == [0, 450, 900]


class TestEmailCards:
    def test_cards_in_correct_column(self, categories):
        triaged = [
            make_triaged(category_id="important", message_id="m1"),
            make_triaged(category_id="spam", message_id="m2"),
        ]
        out = build_canvas_json(triaged, categories, "15h32", "2026-04-28")
        nodes = json.loads(out)["nodes"]
        cards = [n for n in nodes if n["id"].startswith(("important-", "spam-"))]

        # Important card → x=0; spam card → x=900
        important_card = next(c for c in cards if c["id"].startswith("important-"))
        spam_card = next(c for c in cards if c["id"].startswith("spam-"))
        assert important_card["x"] == 0
        assert spam_card["x"] == 900

    def test_cards_stack_vertically(self, categories):
        triaged = [
            make_triaged(category_id="spam", message_id=f"m{i}") for i in range(3)
        ]
        out = build_canvas_json(triaged, categories, "15h32", "2026-04-28")
        nodes = json.loads(out)["nodes"]
        cards = sorted(
            (n for n in nodes if n["id"].startswith("spam-")),
            key=lambda n: n["y"],
        )
        # Y must strictly increase between stacked cards
        ys = [c["y"] for c in cards]
        assert ys == sorted(ys)
        assert ys[1] > ys[0]
        assert ys[2] > ys[1]

    def test_card_text_includes_subject(self, categories):
        triaged = [
            make_triaged(
                category_id="important",
                message_id="m1",
                subject="Boleto urgente",
            )
        ]
        out = build_canvas_json(triaged, categories, "15h32", "2026-04-28")
        nodes = json.loads(out)["nodes"]
        card = next(n for n in nodes if n["id"].startswith("important-"))
        assert "Boleto urgente" in card["text"]

    def test_card_includes_gmail_link(self, categories):
        triaged = [
            make_triaged(
                category_id="important",
                message_id="m1",
                thread_id="threadXYZ",
            )
        ]
        out = build_canvas_json(triaged, categories, "15h32", "2026-04-28")
        nodes = json.loads(out)["nodes"]
        card = next(n for n in nodes if n["id"].startswith("important-"))
        assert "mail.google.com" in card["text"]
        assert "threadXYZ" in card["text"]


class TestUnicodeHandling:
    def test_emoji_preserved_in_json(self, categories):
        triaged = [
            make_triaged(
                category_id="important",
                message_id="m1",
                subject="🔥 Promoção quente 🔥",
            )
        ]
        out = build_canvas_json(triaged, categories, "15h32", "2026-04-28")
        # Critical: ensure_ascii=False MUST keep emojis as-is, not as \u escapes
        assert "🔥" in out

    def test_portuguese_accents_preserved(self, categories):
        triaged = [
            make_triaged(
                category_id="read_later",
                message_id="m1",
                subject="Programação avançada",
            )
        ]
        out = build_canvas_json(triaged, categories, "15h32", "2026-04-28")
        assert "Programação avançada" in out
