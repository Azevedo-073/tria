"""Obsidian output adapter via Local REST API."""
import re
import urllib3
from datetime import datetime
from email.utils import parseaddr
from typing import List, Tuple

import requests

from .base import Output, TriagedEmail
from ..config import CategoryConfig


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


_NAME_EMAIL_RE = re.compile(r"^(.+?)\s*-\s*([\w.+-]+@[\w.-]+)$")


def _parse_sender(raw: str) -> Tuple[str, str]:
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
    if not snippet:
        return ""
    s = snippet.strip()
    s = re.sub(r"\s+", " ", s)
    if len(s) > 500:
        s = s[:497] + "..."
    return s


class ObsidianOutput(Output):
    def __init__(self, api_key, base_url, folder, filename_format, append=True):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.folder = folder.strip("/")
        self.filename_format = filename_format
        self.append = append

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "text/markdown",
        }

    def _url(self, path):
        return f"{self.base_url}/vault/{path}"

    def _file_exists(self, path):
        r = requests.get(self._url(path), headers=self._headers(), verify=False)
        return r.status_code == 200

    def _get_content(self, path):
        r = requests.get(self._url(path), headers=self._headers(), verify=False)
        return r.text if r.status_code == 200 else ""

    def _put_content(self, path, content):
        r = requests.put(
            self._url(path),
            headers=self._headers(),
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

        filename = self.filename_format.format(date=date_str, time=time_str)
        path = f"{self.folder}/{filename}"

        run_block = self._format_run(triaged, categories, time_str)

        if self.append and self._file_exists(path):
            existing = self._get_content(path)
            new_content = existing.rstrip() + "\n\n" + run_block
        else:
            header = self._format_header(date_str)
            new_content = header + "\n\n" + run_block

        self._put_content(path, new_content)

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
        lines.append(f"## 🕒 Run {time_str} · {total} {'email' if total == 1 else 'emails'}")
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

                lines.append(f"> [!{callout_type}] {subject_safe}")
                if name:
                    lines.append(f"> **De:** {name} · `{addr}`")
                else:
                    lines.append(f"> **De:** `{addr}`")
                if time_short:
                    lines.append(f"> **Recebido:** {time_short}")
                lines.append("> ")
                lines.append(f"> 💭 _{reasoning_safe}_")

                if snippet:
                    lines.append("> ")
                    lines.append("> > [!quote]- 📄 Ver conteúdo")
                    lines.append(f"> > {snippet}")

                if gmail:
                    lines.append("> ")
                    lines.append(f"> 🔗 [Abrir no Gmail]({gmail})")

                lines.append("")

        lines.append(f"^run-{time_str}")
        return "\n".join(lines)