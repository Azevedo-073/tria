"""Gmail source — OAuth2 flow + email fetch + label management.

Scope `gmail.modify` permite:
  - Ler emails (idem readonly)
  - Aplicar labels (não deleta nem envia)

Use somente o que precisa: a Tria nunca chama send/trash.
"""
import os
import pickle
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .base import Source, Email


# Scope `gmail.modify` — lê emails E aplica labels.
# NUNCA deleta nem envia (esses requerem gmail.send / gmail.trash separadamente).
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


class GmailSource(Source):
    def __init__(self, credentials_path: str, token_path: str):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service = self._build_service()
        # Cache de label_name → label_id pra não bater na API toda hora
        self._label_cache: Dict[str, str] = {}

    def _build_service(self):
        creds = None

        # Reuse existing token if available
        if os.path.exists(self.token_path):
            with open(self.token_path, "rb") as f:
                creds = pickle.load(f)

        # Detecta se o token salvo tem scope antigo (readonly) — força re-auth
        if creds and not self._has_required_scopes(creds):
            creds = None

        # If no valid creds, run OAuth flow (opens browser on first run)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception:
                    creds = None

            if not creds or not creds.valid:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Persist token for next runs
            with open(self.token_path, "wb") as f:
                pickle.dump(creds, f)

        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    @staticmethod
    def _has_required_scopes(creds: Credentials) -> bool:
        granted = set(getattr(creds, "scopes", None) or [])
        return all(s in granted for s in SCOPES)

    def fetch(self, lookback_hours: int, max_results: int) -> List[Email]:
        """Fetch UNREAD emails received in the last N hours."""
        # Gmail search query — only unread, from inbox, after timestamp
        since = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        since_epoch = int(since.timestamp())
        query = f"is:unread in:inbox after:{since_epoch}"

        resp = (
            self.service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )

        messages = resp.get("messages", [])
        emails: List[Email] = []

        for msg_meta in messages:
            msg = (
                self.service.users()
                .messages()
                .get(
                    userId="me",
                    id=msg_meta["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                )
                .execute()
            )

            headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
            emails.append(
                Email(
                    message_id=msg["id"],
                    thread_id=msg["threadId"],
                    sender=headers.get("From", ""),
                    subject=headers.get("Subject", "(no subject)"),
                    snippet=msg.get("snippet", ""),
                    received_at=self._epoch_ms_to_iso(msg.get("internalDate", "0")),
                )
            )

        return emails

    # ───────────────────────── Label management ─────────────────────────

    def ensure_label(self, name: str) -> str:
        """Garante que a label existe (cria se necessário). Retorna label_id.

        Suporta nested labels via "/" (ex: "Tria/Importante"). O Gmail trata
        a barra como hierarquia automaticamente — não precisa criar pai antes.
        """
        if name in self._label_cache:
            return self._label_cache[name]

        # Lista labels existentes
        resp = self.service.users().labels().list(userId="me").execute()
        for lbl in resp.get("labels", []):
            self._label_cache[lbl["name"]] = lbl["id"]

        if name in self._label_cache:
            return self._label_cache[name]

        # Não existe — cria
        body = {
            "name": name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        }
        try:
            created = (
                self.service.users()
                .labels()
                .create(userId="me", body=body)
                .execute()
            )
            label_id = created["id"]
            self._label_cache[name] = label_id
            return label_id
        except HttpError as e:
            # Race condition: outra request criou enquanto a gente checava
            if e.resp.status == 409:
                resp = self.service.users().labels().list(userId="me").execute()
                for lbl in resp.get("labels", []):
                    if lbl["name"] == name:
                        self._label_cache[name] = lbl["id"]
                        return lbl["id"]
            raise

    def apply_label(self, message_id: str, label_name: str) -> None:
        """Aplica uma label a um email. Idempotente — não duplica."""
        label_id = self.ensure_label(label_name)
        body = {"addLabelIds": [label_id], "removeLabelIds": []}
        self.service.users().messages().modify(
            userId="me", id=message_id, body=body
        ).execute()

    @staticmethod
    def _epoch_ms_to_iso(epoch_ms: str) -> str:
        try:
            dt = datetime.fromtimestamp(int(epoch_ms) / 1000, tz=timezone.utc)
            return dt.isoformat()
        except (ValueError, TypeError):
            return ""
