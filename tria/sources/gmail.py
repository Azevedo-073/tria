"""Gmail source — OAuth2 flow + email fetch with snippet-only mode."""
import os
import pickle
from datetime import datetime, timedelta, timezone
from typing import List

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .base import Source, Email


# Read-only scope — agent NEVER writes to or deletes from Gmail
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailSource(Source):
    def __init__(self, credentials_path: str, token_path: str):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service = self._build_service()

    def _build_service(self):
        creds = None

        # Reuse existing token if available
        if os.path.exists(self.token_path):
            with open(self.token_path, "rb") as f:
                creds = pickle.load(f)

        # If no valid creds, run OAuth flow (opens browser on first run)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Persist token for next runs
            with open(self.token_path, "wb") as f:
                pickle.dump(creds, f)

        return build("gmail", "v1", credentials=creds, cache_discovery=False)

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

    @staticmethod
    def _epoch_ms_to_iso(epoch_ms: str) -> str:
        try:
            dt = datetime.fromtimestamp(int(epoch_ms) / 1000, tz=timezone.utc)
            return dt.isoformat()
        except (ValueError, TypeError):
            return ""
