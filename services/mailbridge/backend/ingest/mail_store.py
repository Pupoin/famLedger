"""Mail cache and delivery metadata; famLedger remains the financial ledger."""
import json
import hashlib
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc).isoformat()


class MailStore:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=10)
        path.chmod(0o600)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS mail_folders (
                source_key TEXT NOT NULL, name TEXT NOT NULL, graph_id TEXT NOT NULL,
                last_scan_at TEXT, delta_link TEXT, PRIMARY KEY (source_key, name)
            );
            CREATE TABLE IF NOT EXISTS emails (
                source_key TEXT NOT NULL, graph_id TEXT NOT NULL,
                folder_name TEXT NOT NULL, mail_kind TEXT NOT NULL,
                internet_message_id TEXT, title TEXT NOT NULL,
                from_json TEXT NOT NULL, sender_json TEXT NOT NULL,
                to_json TEXT NOT NULL, cc_json TEXT NOT NULL, bcc_json TEXT NOT NULL,
                received_at TEXT NOT NULL, sent_at TEXT,
                body_content_type TEXT NOT NULL, body_content TEXT NOT NULL,
                message_json TEXT NOT NULL, cached_at TEXT NOT NULL,
                PRIMARY KEY (source_key, graph_id)
            );
            CREATE INDEX IF NOT EXISTS emails_received_idx ON emails(source_key, received_at);
            CREATE TABLE IF NOT EXISTS sync_state (
                source_key TEXT NOT NULL, state_key TEXT NOT NULL, value TEXT NOT NULL,
                PRIMARY KEY (source_key, state_key)
            );
            CREATE TABLE IF NOT EXISTS deliveries (
                source_key TEXT NOT NULL, graph_id TEXT NOT NULL, target_key TEXT NOT NULL,
                status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT, delivered_at TEXT,
                PRIMARY KEY (source_key, graph_id, target_key),
                FOREIGN KEY (source_key, graph_id) REFERENCES emails(source_key, graph_id)
            );
        ''')

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.conn.close()

    def folder(self, source, name):
        return self.conn.execute("SELECT * FROM mail_folders WHERE source_key=? AND name=?", (source, name)).fetchone()

    def set_folder(self, source, name, graph_id):
        with self.conn:
            self.conn.execute("INSERT INTO mail_folders(source_key,name,graph_id) VALUES(?,?,?) ON CONFLICT(source_key,name) DO UPDATE SET graph_id=excluded.graph_id", (source, name, graph_id))

    def contains(self, source, identifier):
        return self.conn.execute("SELECT 1 FROM emails WHERE source_key=? AND graph_id=?", (source, identifier)).fetchone() is not None

    def save_message(self, source, folder_name, kind, message):
        body = message.get("body")
        if not isinstance(body, dict) or "content" not in body:
            raise ValueError("A complete Graph message body is required before caching")
        encode = lambda value: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        with self.conn:
            self.conn.execute('''INSERT OR IGNORE INTO emails VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
                source, message["id"], folder_name, kind, message.get("internetMessageId"), message.get("subject", ""),
                encode(message.get("from", {})), encode(message.get("sender", {})),
                encode(message.get("toRecipients", [])), encode(message.get("ccRecipients", [])), encode(message.get("bccRecipients", [])),
                message["receivedDateTime"], message.get("sentDateTime"), body.get("contentType", "html"), body["content"],
                encode(message), _now(),
            ))

    def history_days(self, source, name):
        """Lookback setting used by the last completed scan of this folder."""
        row = self.conn.execute("SELECT value FROM sync_state WHERE source_key=? AND state_key=?", (source, f"lookback:{name}")).fetchone()
        return int(row[0]) if row else 0

    def scan_version(self, source, name):
        row = self.conn.execute("SELECT value FROM sync_state WHERE source_key=? AND state_key=?",
                                (source, f"scan_version:{name}")).fetchone()
        return row[0] if row else None

    def prepare_replay(self, source, target, replay_id):
        """Reset the current target once per user-supplied replay marker."""
        if not replay_id:
            return
        key = f"replay:{target}"
        with self.conn:
            row = self.conn.execute("SELECT value FROM sync_state WHERE source_key=? AND state_key=?", (source, key)).fetchone()
            if row and row[0] == replay_id:
                return
            self.conn.execute("UPDATE deliveries SET status='pending',delivered_at=NULL,last_error=NULL WHERE source_key=? AND target_key=?", (source, target))
            self.conn.execute("INSERT INTO sync_state VALUES(?,?,?) ON CONFLICT(source_key,state_key) DO UPDATE SET value=excluded.value", (source, key, replay_id))

    def complete_scan(self, source, name, started, delta_link, history_days, scan_version=None):
        """Apply a new lookback setting only after its scan completes."""
        with self.conn:
            self.conn.execute("UPDATE mail_folders SET last_scan_at=?,delta_link=? WHERE source_key=? AND name=?", (started.isoformat(), delta_link, source, name))

            self.conn.execute("INSERT INTO sync_state VALUES(?,?,?) ON CONFLICT(source_key,state_key) DO UPDATE SET value=excluded.value", (source, f"lookback:{name}", str(history_days)))
            if scan_version:
                self.conn.execute("INSERT INTO sync_state VALUES(?,?,?) ON CONFLICT(source_key,state_key) DO UPDATE SET value=excluded.value",
                                  (source, f"scan_version:{name}", scan_version))

    def prepare_ranged_replay(self, source, target, replay_id, days, now=None):
        """Persist a fixed transaction-time window and a separate delivery namespace."""
        if not replay_id:
            return None
        if not 1 <= days <= 36500:
            raise ValueError("Replay days must be between 1 and 36500")
        marker_key = f"replay:{target}"
        window_key = f"replay_window:{target}"
        with self.conn:
            previous = self.conn.execute("SELECT value FROM sync_state WHERE source_key=? AND state_key=?",
                                         (source, marker_key)).fetchone()
            if previous and previous[0] == replay_id:
                saved = self.conn.execute("SELECT value FROM sync_state WHERE source_key=? AND state_key=?",
                                          (source, window_key)).fetchone()
                window = json.loads(saved[0]) if saved else None
                return window if window and window["id"] == replay_id else None
            end = now or datetime.now(timezone.utc)
            if end.tzinfo is None:
                raise ValueError("Replay window must use timezone-aware timestamps")
            window = {
                "id": replay_id, "days": days,
                "start": (end - timedelta(days=days)).isoformat(), "end": end.isoformat(),
                "target": "replay:" + hashlib.sha256(json.dumps([target, replay_id]).encode()).hexdigest(),
            }
            for key, value in [(marker_key, replay_id), (window_key, json.dumps(window))]:
                self.conn.execute("INSERT INTO sync_state VALUES(?,?,?) ON CONFLICT(source_key,state_key) DO UPDATE SET value=excluded.value",
                                  (source, key, value))
        logger.info("Manual replay scheduled: past %s days, transaction window %s to %s", days, window["start"], window["end"])
        return window

    def pending(self, source, target):
        return self.conn.execute('''SELECT e.graph_id,e.mail_kind,e.message_json FROM emails e
            WHERE e.source_key=? AND NOT EXISTS (
                SELECT 1 FROM deliveries d WHERE d.source_key=e.source_key AND d.graph_id=e.graph_id
                AND d.target_key=? AND d.status='sent') ORDER BY e.received_at''', (source, target))

    def mark_delivery(self, source, identifier, target, error=None):
        with self.conn:
            self.conn.execute('''INSERT INTO deliveries VALUES(?,?,?,?,1,?,?)
                ON CONFLICT(source_key,graph_id,target_key) DO UPDATE SET
                status=excluded.status, attempts=deliveries.attempts+1,
                last_error=excluded.last_error,delivered_at=excluded.delivered_at''', (
                    source, identifier, target, "failed" if error else "sent", error,
                    None if error else _now(),
                ))
