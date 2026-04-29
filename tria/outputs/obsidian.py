"""Obsidian output adapter via Local REST API.

Escreve dois arquivos por run:
  1. {date}.md     — digest narrativo (callouts + tabela + snippet)
  2. {date}.canvas — kanban visual (banner + 3 colunas + cards)
"""
import json
import re
import urllib3
from datetime import datetime
from email.utils import parseaddr
from typing import Dict, List, Tuple

import requests

from .base import Output, TriagedEmail
from ..config import CategoryConfig


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# Detects "Real Name - real@email.com" inside the display name
# (common Blackboard/mailing-list pattern where envelope sender is a noreply)
_NAME_EMAIL_RE = re.compile(r"^(.+?)\s*-\s*([\w.+-]+@[\w.-]+)$")


def _parse_sender(raw: str) -> Tuple[str, str]:
    """Parse 'Name <email@host>' into (name, email).

    If the display name itself contains 'Real Name - real@email', prefer that
    inner email over the envelope sender (Blackboard & co. use do-not-reply@...).
    """
    name, addr = parseaddr(raw or "")
    name = name.strip().strip('"').strip()

    m = _NAME_EMAIL_RE.match(name)
    if m:
        name = m.group(1).strip()
        addr = m.group(2).strip()

    return name, (addr or raw or "").strip()


def _short_time(received_at: str) -> str:
    if not received_at:
        return ""
    m = re.search(r"(\d{2}:\d{2})", received_at)
    return m.group(1) if m else received_at


def _gmail_url(thread_id: str) -> str:
    if not thread_id:
        return ""
    return f"https://mail.google.com/mail/u/0/#inbox/{thread_id}"


def _clean_snippet(snippet: str) -> str:
    """Clean up snippet for inline display."""
    if not snippet:
        return ""
    s = snippet.strip()
    # Collapse whitespace, keep single spaces
    s = re.sub(r"\s+", " ", s)
    # Truncate very long snippets
    if len(s) > 500:
        s = s[:497] + "..."
    return s


# ──────────────────── Canvas builder (pure, testable) ────────────────────

# Obsidian Canvas color codes:
# 1=red · 2=orange · 3=yellow · 4=green · 5=cyan · 6=purple
_CATEGORY_CANVAS_COLOR = {
    "important": "1",   # vermelho
    "read_later": "3",  # amarelo
    "spam": "",         # default cinza
}

# Layout constants
_BANNER_W = 1320
_BANNER_H = 140
_COL_W = 420
_COL_GAP = 30
_COL_HEADER_H = 130
_COL_HEADER_Y = 180
_CARD_Y_START = 340
_CARD_GAP = 30
# Heights por categoria — important e read_later usam mais conteúdo,
# spam é mais enxuto
_CARD_H_DEFAULT = 280


def _column_x(idx: int) -> int:
    """X-coord of column idx (0=important, 1=read_later, 2=spam)."""
    return idx * (_COL_W + _COL_GAP)


def _email_card_text(t: TriagedEmail) -> str:
    """Compose markdown for one email card."""
    subject = (t.email.subject or "(sem assunto)").strip()
    name, addr = _parse_sender(t.email.sender)
    time_short = _short_time(t.email.received_at)
    reasoning = (t.classification.reasoning or "—").strip()
    gmail = _gmail_url(t.email.thread_id)

    lines = [f"### {subject}", ""]
    if name:
        lines.append(f"📧 {name}")
        lines.append(f"`{addr}`")
    else:
        lines.append(f"📧 `{addr}`")
    if time_short:
        lines.append(f"🕒 {time_short}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"💭 _{reasoning}_")
    if gmail:
        lines.append("")
        lines.append(f"[🔗 Abrir no Gmail]({gmail})")
    return "\n".join(lines)


def build_canvas_json(
    triaged: List[TriagedEmail],
    categories: List[CategoryConfig],
    run_label: str,
    date_str: str,
) -> str:
    """Build a `.canvas` JSON document representing the kanban layout.

    Pure function — no I/O. Input drives output deterministically (good pra teste).
    """
    by_cat: Dict[str, List[TriagedEmail]] = {c.id: [] for c in categories}
    for t in triaged:
        by_cat.setdefault(t.classification.category_id, []).append(t)

    total = len(triaged)
    counts = {c.id: len(by_cat.get(c.id, [])) for c in categories}

    nodes = []

    # ---- Banner card ----
    summary_parts = []
    for c in categories:
        n = counts.get(c.id, 0)
        summary_parts.append(f"{c.emoji} {n}")
    summary = " · ".join(summary_parts)

    banner_text = (
        f"# 📧 Tria — Email Triage Kanban\n"
        f"**{date_str} · Run {run_label}** · "
        f"{total} {'email' if total == 1 else 'emails'} · {summary}\n\n"
        f"_Agente autônomo · Gmail → Gemini → Obsidian · "
        f"roda sozinho a cada 3h_"
    )
    nodes.append(
        {
            "id": "banner",
            "type": "text",
            "text": banner_text,
            "x": 0,
            "y": 0,
            "width": _BANNER_W,
            "height": _BANNER_H,
        }
    )

    # ---- Column headers + email cards ----
    for col_idx, cat in enumerate(categories):
        col_x = _column_x(col_idx)
        items = by_cat.get(cat.id, [])
        n = len(items)
        pct = int(round((n / total * 100) if total else 0))

        # Column header
        header_text = (
            f"## {cat.emoji} {cat.label.upper()}\n\n"
            f"**{n} {'email' if n == 1 else 'emails'}** · {pct}%\n\n"
            f"_{cat.description}_"
        )
        header_node = {
            "id": f"col-{cat.id}",
            "type": "text",
            "text": header_text,
            "x": col_x,
            "y": _COL_HEADER_Y,
            "width": _COL_W,
            "height": _COL_HEADER_H,
        }
        color = _CATEGORY_CANVAS_COLOR.get(cat.id, "")
        if color:
            header_node["color"] = color
        nodes.append(header_node)

        # Email cards stack
        card_y = _CARD_Y_START
        for i, t in enumerate(items):
            card_node = {
                "id": f"{cat.id}-{i}-{t.email.message_id[:12]}",
                "type": "text",
                "text": _email_card_text(t),
                "x": col_x,
                "y": card_y,
                "width": _COL_W,
                "height": _CARD_H_DEFAULT,
            }
            if color:
                card_node["color"] = color
            nodes.append(card_node)
            card_y += _CARD_H_DEFAULT + _CARD_GAP

    canvas = {"nodes": nodes, "edges": []}
    return json.dumps(canvas, ensure_ascii=False, indent=2)


# ──────────────────────── Obsidian output adapter ────────────────────────


class ObsidianOutput(Output):
    def __init__(
        self,
        api_key,
        base_url,
        folder,
        filename_format,
        append=True,
        write_canvas=True,
        canvas_filename="📧 Tria Kanban.canvas",
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.folder = folder.strip("/")
        self.filename_format = filename_format
        self.append = append
        self.write_canvas = write_canvas
        self.canvas_filename = canvas_filename

    def _headers(self, content_type: str = "text/markdown"):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": content_type,
        }

    def _url(self, path):
        return f"{self.base_url}/vault/{path}"

    def _file_exists(self, path):
        r = requests.get(self._url(path), headers=self._headers(), verify=False)
        return r.status_code == 200

    def _get_content(self, path):
        r = requests.get(self._url(path), headers=self._headers(), verify=False)
        return r.text if r.status_code == 200 else ""

    def _put_content(self, path, content, content_type="text/markdown"):
        r = requests.put(
            self._url(path),
            headers=self._headers(content_type),
            data=content.encode("utf-8"),
            verify=False,
        )
        r.raise_for_status()

    def write_digest(self, triaged, categories):
        if not triaged:
            return

        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%Hh%M")

        # ---- Markdown digest (append mode por dia) ----
        md_filename = self.filename_format.format(date=date_str, time=time_str)
        md_path = f"{self.folder}/{md_filename}"

        run_block = self._format_run(triaged, categories, time_str)

        if self.append and self._file_exists(md_path):
            existing = self._get_content(md_path)
            new_content = existing.rstrip() + "\n\n" + run_block
        else:
            header = self._format_header(date_str)
            new_content = header + "\n\n" + run_block

        self._put_content(md_path, new_content)

        # ---- Canvas kanban (1 arquivo fixo = dashboard vivo) ----
        # Filename suporta placeholders {date} e {time} — default é fixo.
        # Markdown digest já é o histórico; canvas é "estado atual".
        if self.write_canvas:
            canvas_name = self.canvas_filename.format(date=date_str, time=time_str)
            canvas_path = f"{self.folder}/{canvas_name}"
            canvas_json = build_canvas_json(
                triaged=triaged,
                categories=categories,
                run_label=time_str,
                date_str=date_str,
            )
            self._put_content(
                canvas_path, canvas_json, content_type="application/json"
            )

    @staticmethod
    def _format_header(date_str):
        return (
            f"---\n"
            f"tags: [tria, email-digest]\n"
            f"date: {date_str}\n"
            f"criado: {date_str}\n"
            f"source: tria\n"
            f"---\n\n"
            f"# 📧 Email Digest — {date_str}\n\n"
            f"> [!abstract] Triagem automática · [[Tria]]\n"
            f"> Agente que lê o Gmail, classifica com IA e escreve o resumo aqui.\n"
            f"> **Privacidade:** apenas metadados + snippet são enviados à LLM."
        )

    def _format_run(self, triaged, categories, time_str):
        total = len(triaged)

        by_cat = {c.id: [] for c in categories}
        for t in triaged:
            by_cat.setdefault(t.classification.category_id, []).append(t)

        lines = []
        lines.append("---")
        lines.append("")
        lines.append(
            f"## 🕒 Run {time_str} · {total} {'email' if total == 1 else 'emails'}"
        )
        lines.append("")

        lines.append("| Categoria | Qtd | % |")
        lines.append("|---|---:|---:|")
        for c in categories:
            n = len(by_cat.get(c.id, []))
            pct = (n / total * 100) if total else 0
            lines.append(f"| {c.emoji} **{c.label}** | {n} | {pct:.0f}% |")
        lines.append("")

        callout_for = {
            "important": "danger",
            "read_later": "tip",
            "spam": "failure",
        }

        for c in categories:
            items = by_cat.get(c.id, [])
            if not items:
                continue
            lines.append(f"### {c.emoji} {c.label} · {len(items)}")
            lines.append("")

            callout_type = callout_for.get(c.id, "example")

            for t in items:
                subject = (t.email.subject or "(sem assunto)").strip()
                name, addr = _parse_sender(t.email.sender)
                time_short = _short_time(t.email.received_at)
                reasoning = (t.classification.reasoning or "—").strip()
                snippet = _clean_snippet(t.email.snippet)
                gmail = _gmail_url(t.email.thread_id)

                subject_safe = subject.replace("|", "\\|")
                reasoning_safe = reasoning.replace("|", "\\|")

                # --- Main callout ---
                lines.append(f"> [!{callout_type}] {subject_safe}")
                if name:
                    lines.append(f"> **De:** {name} · `{addr}`")
                else:
                    lines.append(f"> **De:** `{addr}`")
                if time_short:
                    lines.append(f"> **Recebido:** {time_short}")
                lines.append("> ")
                lines.append(f"> 💭 _{reasoning_safe}_")

                # --- Nested collapsible with the email snippet ---
                if snippet:
                    lines.append("> ")
                    lines.append("> > [!quote]- 📄 Ver conteúdo")
                    lines.append(f"> > {snippet}")

                # --- Gmail link ---
                if gmail:
                    lines.append("> ")
                    lines.append(f"> 🔗 [Abrir no Gmail]({gmail})")

                lines.append("")

        lines.append(f"^run-{time_str}")
        return "\n".join(lines)
