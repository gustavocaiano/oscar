from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ListItem:
    id: int | str
    kind: str
    title: str
    done: bool
    created_at: str
    updated_at: str
    column_name: str | None = None


@dataclass(frozen=True)
class NoteItem:
    id: int
    kind: str
    content: str
    created_at: str


@dataclass(frozen=True)
class ReminderItem:
    id: int
    user_id: int
    chat_id: int
    message: str
    due_at: str
    status: str
    created_at: str


@dataclass(frozen=True)
class ApprovalRecord:
    token: str
    action_type: str
    payload: dict[str, Any]
    prompt_text: str
    status: str
    expires_at: str


@dataclass(frozen=True)
class ChatMessage:
    id: int
    role: str
    content: str
    created_at: str


@dataclass(frozen=True)
class HourEntry:
    id: int
    entry_date: str
    hours: Decimal
    raw_text: str
    created_at: str


@dataclass(frozen=True)
class TaskSyncLink:
    list_item_id: int
    provider: str
    external_task_id: str
    external_board_id: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ChatPreferences:
    chat_id: int
    user_id: int
    timezone: str
    reminder_alerts_enabled: bool
    hour_reminder_enabled: bool
    morning_brief_enabled: bool
    evening_wrap_up_enabled: bool
    morning_brief_time: str
    hour_reminder_time: str
    evening_wrap_up_time: str
    last_morning_brief_on: str | None
    last_hour_reminder_on: str | None
    last_evening_wrap_up_on: str | None


class SQLiteStorage:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS chat_preferences (
                    chat_id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    timezone TEXT NOT NULL,
                    reminder_alerts_enabled INTEGER NOT NULL DEFAULT 1,
                    hour_reminder_enabled INTEGER NOT NULL DEFAULT 1,
                    morning_brief_enabled INTEGER NOT NULL DEFAULT 1,
                    evening_wrap_up_enabled INTEGER NOT NULL DEFAULT 1,
                    morning_brief_time TEXT NOT NULL,
                    hour_reminder_time TEXT NOT NULL,
                    evening_wrap_up_time TEXT NOT NULL,
                    last_morning_brief_on TEXT,
                    last_hour_reminder_on TEXT,
                    last_evening_wrap_up_on TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS list_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('task', 'shopping')),
                    title TEXT NOT NULL,
                    done INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_list_items_scope
                ON list_items (chat_id, user_id, kind, done, id);

                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('note', 'inbox')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_notes_scope
                ON notes (chat_id, user_id, kind, id);

                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending', 'sending', 'sent', 'done', 'cancelled')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    notified_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_reminders_pending
                ON reminders (status, due_at, chat_id, user_id);

                CREATE TABLE IF NOT EXISTS approvals (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    action_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    prompt_text TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending', 'executing', 'approved', 'rejected', 'expired', 'executed')),
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_approvals_scope
                ON approvals (chat_id, user_id, status);

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('system', 'user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_chat_messages_scope
                ON chat_messages (chat_id, user_id, id DESC);

                CREATE TABLE IF NOT EXISTS scheduled_claims (
                    chat_id INTEGER NOT NULL,
                    notification_type TEXT NOT NULL CHECK(notification_type IN ('morning_brief', 'hour_reminder', 'evening_wrap_up')),
                    claim_date TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('claiming', 'sent')),
                    claimed_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (chat_id, notification_type, claim_date)
                );

                CREATE TABLE IF NOT EXISTS hour_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    entry_date TEXT NOT NULL,
                    hours TEXT NOT NULL,
                    raw_text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_hour_entries_scope
                ON hour_entries (chat_id, user_id, entry_date, id);

                CREATE TABLE IF NOT EXISTS task_sync_links (
                    list_item_id INTEGER NOT NULL,
                    provider TEXT NOT NULL,
                    external_task_id TEXT NOT NULL,
                    external_board_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (list_item_id, provider)
                );

                CREATE INDEX IF NOT EXISTS idx_task_sync_links_provider
                ON task_sync_links (provider, external_task_id);
                """
            )

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def ensure_chat_preferences(
        self,
        *,
        chat_id: int,
        user_id: int,
        timezone_name: str,
        morning_brief_time: str,
        hour_reminder_time: str,
        evening_wrap_up_time: str,
    ) -> ChatPreferences:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM chat_preferences WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
            if row is None:
                now = self._now()
                connection.execute(
                    """
                    INSERT INTO chat_preferences (
                        chat_id, user_id, timezone, reminder_alerts_enabled, hour_reminder_enabled,
                        morning_brief_enabled, evening_wrap_up_enabled, morning_brief_time,
                        hour_reminder_time, evening_wrap_up_time, created_at, updated_at
                    ) VALUES (?, ?, ?, 1, 1, 1, 1, ?, ?, ?, ?, ?)
                    """,
                    (
                        chat_id,
                        user_id,
                        timezone_name,
                        morning_brief_time,
                        hour_reminder_time,
                        evening_wrap_up_time,
                        now,
                        now,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM chat_preferences WHERE chat_id = ?",
                    (chat_id,),
                ).fetchone()
            if row is None:
                raise LookupError("Chat preferences not found")
            return ChatPreferences(
                chat_id=int(row["chat_id"]),
                user_id=int(row["user_id"]),
                timezone=str(row["timezone"]),
                reminder_alerts_enabled=bool(row["reminder_alerts_enabled"]),
                hour_reminder_enabled=bool(row["hour_reminder_enabled"]),
                morning_brief_enabled=bool(row["morning_brief_enabled"]),
                evening_wrap_up_enabled=bool(row["evening_wrap_up_enabled"]),
                morning_brief_time=str(row["morning_brief_time"]),
                hour_reminder_time=str(row["hour_reminder_time"]),
                evening_wrap_up_time=str(row["evening_wrap_up_time"]),
                last_morning_brief_on=row["last_morning_brief_on"],
                last_hour_reminder_on=row["last_hour_reminder_on"],
                last_evening_wrap_up_on=row["last_evening_wrap_up_on"],
            )

    def get_chat_preferences(self, chat_id: int) -> ChatPreferences:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM chat_preferences WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        if row is None:
            raise LookupError("Chat preferences not found")
        return ChatPreferences(
            chat_id=int(row["chat_id"]),
            user_id=int(row["user_id"]),
            timezone=str(row["timezone"]),
            reminder_alerts_enabled=bool(row["reminder_alerts_enabled"]),
            hour_reminder_enabled=bool(row["hour_reminder_enabled"]),
            morning_brief_enabled=bool(row["morning_brief_enabled"]),
            evening_wrap_up_enabled=bool(row["evening_wrap_up_enabled"]),
            morning_brief_time=str(row["morning_brief_time"]),
            hour_reminder_time=str(row["hour_reminder_time"]),
            evening_wrap_up_time=str(row["evening_wrap_up_time"]),
            last_morning_brief_on=row["last_morning_brief_on"],
            last_hour_reminder_on=row["last_hour_reminder_on"],
            last_evening_wrap_up_on=row["last_evening_wrap_up_on"],
        )

    def list_chat_preferences(self) -> list[ChatPreferences]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM chat_preferences ORDER BY chat_id ASC").fetchall()
        return [
            ChatPreferences(
                chat_id=int(row["chat_id"]),
                user_id=int(row["user_id"]),
                timezone=str(row["timezone"]),
                reminder_alerts_enabled=bool(row["reminder_alerts_enabled"]),
                hour_reminder_enabled=bool(row["hour_reminder_enabled"]),
                morning_brief_enabled=bool(row["morning_brief_enabled"]),
                evening_wrap_up_enabled=bool(row["evening_wrap_up_enabled"]),
                morning_brief_time=str(row["morning_brief_time"]),
                hour_reminder_time=str(row["hour_reminder_time"]),
                evening_wrap_up_time=str(row["evening_wrap_up_time"]),
                last_morning_brief_on=row["last_morning_brief_on"],
                last_hour_reminder_on=row["last_hour_reminder_on"],
                last_evening_wrap_up_on=row["last_evening_wrap_up_on"],
            )
            for row in rows
        ]

    def update_chat_preferences(self, chat_id: int, **updates: Any) -> ChatPreferences:
        if not updates:
            return self.get_chat_preferences(chat_id)
        allowed = {
            "timezone",
            "reminder_alerts_enabled",
            "hour_reminder_enabled",
            "morning_brief_enabled",
            "evening_wrap_up_enabled",
            "morning_brief_time",
            "hour_reminder_time",
            "evening_wrap_up_time",
            "last_morning_brief_on",
            "last_hour_reminder_on",
            "last_evening_wrap_up_on",
        }
        unknown = set(updates) - allowed
        if unknown:
            raise ValueError(f"Unsupported preference fields: {sorted(unknown)}")

        columns = [f"{key} = ?" for key in updates]
        values = list(updates.values())
        values.append(self._now())
        values.append(chat_id)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE chat_preferences SET {', '.join(columns)}, updated_at = ? WHERE chat_id = ?",
                values,
            )
        return self.get_chat_preferences(chat_id)

    def compare_and_set_chat_preference(self, *, chat_id: int, field: str, expected: Any, new_value: Any) -> bool:
        allowed = {
            "last_morning_brief_on",
            "last_hour_reminder_on",
            "last_evening_wrap_up_on",
        }
        if field not in allowed:
            raise ValueError(f"Unsupported compare-and-set field: {field}")
        with self._connect() as connection:
            if expected is None:
                cursor = connection.execute(
                    f"UPDATE chat_preferences SET {field} = ?, updated_at = ? WHERE chat_id = ? AND {field} IS NULL",
                    (new_value, self._now(), chat_id),
                )
            else:
                cursor = connection.execute(
                    f"UPDATE chat_preferences SET {field} = ?, updated_at = ? WHERE chat_id = ? AND {field} = ?",
                    (new_value, self._now(), chat_id, expected),
                )
            return cursor.rowcount > 0

    def create_list_item(self, *, user_id: int, chat_id: int, kind: str, title: str) -> int:
        now = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO list_items (user_id, chat_id, kind, title, done, created_at, updated_at)
                VALUES (?, ?, ?, ?, 0, ?, ?)
                """,
                (user_id, chat_id, kind, title.strip(), now, now),
            )
            return int(cursor.lastrowid)

    def list_items(self, *, user_id: int, chat_id: int, kind: str, include_done: bool = False) -> list[ListItem]:
        query = (
            "SELECT id, kind, title, done, created_at, updated_at FROM list_items "
            "WHERE user_id = ? AND chat_id = ? AND kind = ?"
        )
        params: list[Any] = [user_id, chat_id, kind]
        if not include_done:
            query += " AND done = 0"
        query += " ORDER BY done ASC, id ASC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            ListItem(
                id=int(row["id"]),
                kind=str(row["kind"]),
                title=str(row["title"]),
                done=bool(row["done"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )
            for row in rows
        ]

    def update_list_item(self, *, user_id: int, chat_id: int, kind: str, item_id: int, title: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE list_items
                SET title = ?, updated_at = ?
                WHERE id = ? AND user_id = ? AND chat_id = ? AND kind = ?
                """,
                (title.strip(), self._now(), item_id, user_id, chat_id, kind),
            )
            return cursor.rowcount > 0

    def mark_list_item_done(self, *, user_id: int, chat_id: int, kind: str, item_id: int) -> bool:
        now = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE list_items
                SET done = 1, completed_at = ?, updated_at = ?
                WHERE id = ? AND user_id = ? AND chat_id = ? AND kind = ?
                """,
                (now, now, item_id, user_id, chat_id, kind),
            )
            return cursor.rowcount > 0

    def get_list_item(self, *, user_id: int, chat_id: int, kind: str, item_id: int) -> ListItem | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, kind, title, done, created_at, updated_at
                FROM list_items
                WHERE id = ? AND user_id = ? AND chat_id = ? AND kind = ?
                """,
                (item_id, user_id, chat_id, kind),
            ).fetchone()
        if row is None:
            return None
        return ListItem(
            id=int(row["id"]),
            kind=str(row["kind"]),
            title=str(row["title"]),
            done=bool(row["done"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def create_note(self, *, user_id: int, chat_id: int, kind: str, content: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO notes (user_id, chat_id, kind, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, chat_id, kind, content.strip(), self._now()),
            )
            return int(cursor.lastrowid)

    def list_notes(
        self,
        *,
        user_id: int,
        chat_id: int,
        kind: str | None = None,
        limit: int = 10,
        query: str | None = None,
    ) -> list[NoteItem]:
        sql = "SELECT id, kind, content, created_at FROM notes WHERE user_id = ? AND chat_id = ?"
        params: list[Any] = [user_id, chat_id]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        if query:
            sql += " AND content LIKE ?"
            params.append(f"%{query}%")
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [
            NoteItem(
                id=int(row["id"]),
                kind=str(row["kind"]),
                content=str(row["content"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def delete_note(self, *, note_id: int, user_id: int, chat_id: int) -> bool:
        """Delete a note by ID. Returns True if deleted, False if not found."""
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM notes WHERE id = ? AND user_id = ? AND chat_id = ? RETURNING id",
                (note_id, user_id, chat_id),
            )
            return cursor.fetchone() is not None

    def create_reminder(self, *, user_id: int, chat_id: int, message: str, due_at: str) -> int:
        now = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO reminders (user_id, chat_id, message, due_at, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pending', ?, ?)
                """,
                (user_id, chat_id, message.strip(), due_at, now, now),
            )
            return int(cursor.lastrowid)

    def list_reminders(self, *, user_id: int, chat_id: int, pending_only: bool = False) -> list[ReminderItem]:
        sql = "SELECT id, user_id, chat_id, message, due_at, status, created_at FROM reminders WHERE user_id = ? AND chat_id = ?"
        params: list[Any] = [user_id, chat_id]
        if pending_only:
            sql += " AND status = 'pending'"
        sql += " ORDER BY due_at ASC, id ASC"
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [
            ReminderItem(
                id=int(row["id"]),
                user_id=int(row["user_id"]),
                chat_id=int(row["chat_id"]),
                message=str(row["message"]),
                due_at=str(row["due_at"]),
                status=str(row["status"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def update_reminder_status(self, *, user_id: int, chat_id: int, reminder_id: int, status: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE reminders
                SET status = ?, updated_at = ?
                WHERE id = ? AND user_id = ? AND chat_id = ?
                """,
                (status, self._now(), reminder_id, user_id, chat_id),
            )
            return cursor.rowcount > 0

    def list_due_reminders(self, *, due_before: str) -> list[ReminderItem]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, chat_id, message, due_at, status, created_at
                FROM reminders
                WHERE status = 'pending' AND due_at <= ?
                ORDER BY due_at ASC, id ASC
                """,
                (due_before,),
            ).fetchall()
        return [
            ReminderItem(
                id=int(row["id"]),
                user_id=int(row["user_id"]),
                chat_id=int(row["chat_id"]),
                message=str(row["message"]),
                due_at=str(row["due_at"]),
                status=str(row["status"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def claim_due_reminders(self, *, due_before: str, stale_after_seconds: int) -> list[ReminderItem]:
        claimed: list[ReminderItem] = []
        now = datetime.now(timezone.utc)
        stale_before = (now - timedelta(seconds=stale_after_seconds)).isoformat()
        with self._connect() as connection:
            connection.execute(
                "UPDATE reminders SET status = 'pending', updated_at = ? WHERE status = 'sending' AND updated_at <= ?",
                (now.isoformat(), stale_before),
            )
            rows = connection.execute(
                """
                SELECT id, user_id, chat_id, message, due_at, status, created_at
                FROM reminders
                WHERE status = 'pending' AND due_at <= ?
                ORDER BY due_at ASC, id ASC
                """,
                (due_before,),
            ).fetchall()
            for row in rows:
                cursor = connection.execute(
                    "UPDATE reminders SET status = 'sending', updated_at = ? WHERE id = ? AND status = 'pending'",
                    (now.isoformat(), row["id"]),
                )
                if cursor.rowcount > 0:
                    claimed.append(
                        ReminderItem(
                            id=int(row["id"]),
                            user_id=int(row["user_id"]),
                            chat_id=int(row["chat_id"]),
                            message=str(row["message"]),
                            due_at=str(row["due_at"]),
                            status="sending",
                            created_at=str(row["created_at"]),
                        )
                    )
        return claimed

    def mark_reminder_sent(self, reminder_id: int) -> None:
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE reminders SET status = 'sent', notified_at = ?, updated_at = ? WHERE id = ? AND status = 'sending'",
                (now, now, reminder_id),
            )

    def reset_reminder_pending(self, reminder_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE reminders SET status = 'pending', updated_at = ? WHERE id = ? AND status = 'sending'",
                (self._now(), reminder_id),
            )

    def add_chat_message(self, *, user_id: int, chat_id: int, role: str, content: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO chat_messages (user_id, chat_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, chat_id, role, content, self._now()),
            )
            return int(cursor.lastrowid)

    def get_recent_chat_messages(self, *, user_id: int, chat_id: int, limit: int) -> list[ChatMessage]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, role, content, created_at
                FROM (
                    SELECT id, role, content, created_at
                    FROM chat_messages
                    WHERE user_id = ? AND chat_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                ) recent
                ORDER BY id ASC
                """,
                (user_id, chat_id, limit),
            ).fetchall()
        return [
            ChatMessage(
                id=int(row["id"]),
                role=str(row["role"]),
                content=str(row["content"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def create_approval(
        self,
        *,
        token: str,
        user_id: int,
        chat_id: int,
        action_type: str,
        payload: dict[str, Any],
        prompt_text: str,
        expires_at: str,
    ) -> None:
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO approvals (
                    token, user_id, chat_id, action_type, payload_json, prompt_text, status, created_at, expires_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                """,
                (token, user_id, chat_id, action_type, json.dumps(payload), prompt_text, now, expires_at, now),
            )

    def get_approval(self, *, token: str, user_id: int, chat_id: int) -> ApprovalRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM approvals WHERE token = ? AND user_id = ? AND chat_id = ?",
                (token, user_id, chat_id),
            ).fetchone()
        if row is None:
            return None
        return ApprovalRecord(
            token=str(row["token"]),
            action_type=str(row["action_type"]),
            payload=json.loads(str(row["payload_json"])),
            prompt_text=str(row["prompt_text"]),
            status=str(row["status"]),
            expires_at=str(row["expires_at"]),
        )

    def upsert_task_sync_link(
        self,
        *,
        list_item_id: int,
        provider: str,
        external_task_id: str,
        external_board_id: str | None,
    ) -> None:
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO task_sync_links (
                    list_item_id, provider, external_task_id, external_board_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(list_item_id, provider) DO UPDATE SET
                    external_task_id = excluded.external_task_id,
                    external_board_id = excluded.external_board_id,
                    updated_at = excluded.updated_at
                """,
                (list_item_id, provider, external_task_id, external_board_id, now, now),
            )

    def get_task_sync_link(self, *, list_item_id: int, provider: str) -> TaskSyncLink | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM task_sync_links WHERE list_item_id = ? AND provider = ?",
                (list_item_id, provider),
            ).fetchone()
        if row is None:
            return None
        return TaskSyncLink(
            list_item_id=int(row["list_item_id"]),
            provider=str(row["provider"]),
            external_task_id=str(row["external_task_id"]),
            external_board_id=row["external_board_id"],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def update_approval_status(self, *, token: str, status: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE approvals SET status = ?, updated_at = ? WHERE token = ?",
                (status, self._now(), token),
            )

    def transition_approval_status(self, *, token: str, expected_status: str, new_status: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE approvals SET status = ?, updated_at = ? WHERE token = ? AND status = ?",
                (new_status, self._now(), token, expected_status),
            )
            return cursor.rowcount > 0

    def claim_scheduled_notification(
        self,
        *,
        chat_id: int,
        notification_type: str,
        claim_date: str,
        stale_after_seconds: int,
    ) -> bool:
        now = datetime.now(timezone.utc)
        stale_before = (now - timedelta(seconds=stale_after_seconds)).isoformat()
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM scheduled_claims WHERE chat_id = ? AND notification_type = ? AND claim_date = ? AND status = 'claiming' AND claimed_at <= ?",
                (chat_id, notification_type, claim_date, stale_before),
            )
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO scheduled_claims (
                    chat_id, notification_type, claim_date, status, claimed_at, updated_at
                ) VALUES (?, ?, ?, 'claiming', ?, ?)
                """,
                (chat_id, notification_type, claim_date, now.isoformat(), now.isoformat()),
            )
            return cursor.rowcount > 0

    def mark_scheduled_notification_sent(self, *, chat_id: int, notification_type: str, claim_date: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE scheduled_claims SET status = 'sent', updated_at = ? WHERE chat_id = ? AND notification_type = ? AND claim_date = ? AND status = 'claiming'",
                (self._now(), chat_id, notification_type, claim_date),
            )

    def release_scheduled_notification_claim(self, *, chat_id: int, notification_type: str, claim_date: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM scheduled_claims WHERE chat_id = ? AND notification_type = ? AND claim_date = ? AND status = 'claiming'",
                (chat_id, notification_type, claim_date),
            )

    def create_hour_entry(
        self,
        *,
        user_id: int,
        chat_id: int,
        entry_date: str,
        hours: Decimal,
        raw_text: str,
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO hour_entries (user_id, chat_id, entry_date, hours, raw_text, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, chat_id, entry_date, str(hours), raw_text, self._now()),
            )
            return int(cursor.lastrowid)

    def aggregate_month_hours(self, *, user_id: int, chat_id: int, year: int, month: int) -> Decimal:
        if month < 1 or month > 12:
            raise ValueError("month must be in range 1..12")
        month_prefix = f"{year:04d}-{month:02d}-"
        total = Decimal("0")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT hours FROM hour_entries WHERE user_id = ? AND chat_id = ? AND entry_date LIKE ?",
                (user_id, chat_id, f"{month_prefix}%"),
            )
            for (hours_value,) in rows:
                total += Decimal(hours_value)
        return total

    def get_day_hours(self, *, user_id: int, chat_id: int, entry_date: str) -> Decimal:
        total = Decimal("0")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT hours FROM hour_entries WHERE user_id = ? AND chat_id = ? AND entry_date = ?",
                (user_id, chat_id, entry_date),
            )
            for (hours_value,) in rows:
                total += Decimal(hours_value)
        return total
