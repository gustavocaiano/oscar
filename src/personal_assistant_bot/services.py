from __future__ import annotations

import logging
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from personal_assistant_bot.calendar_integration import CalendarEvent, CalendarIntegrationError, CalendarService
from personal_assistant_bot.config import Settings
from personal_assistant_bot.hours import format_hours_total, format_subtotals, parse_hours
from personal_assistant_bot.kbplus_integration import KbplusColumn, KbplusIntegrationError, KbplusTask, KbplusTaskClient
from personal_assistant_bot.storage import (
    ChatMessage,
    ChatPreferences,
    ListItem,
    NoteItem,
    ReminderItem,
    SQLiteStorage,
)

logger = logging.getLogger(__name__)


class AssistantError(ValueError):
    """Raised for user-facing assistant errors."""


@dataclass(frozen=True)
class ScheduledNotification:
    chat_id: int
    text: str
    notification_type: str
    reminder_id: int | None = None
    claim_date: str | None = None
    preference_updates: dict[str, Any] | None = None


@dataclass(frozen=True)
class PendingApproval:
    token: str
    prompt_text: str
    expires_at: str


@dataclass(frozen=True)
class PreparedAction:
    action_type: str
    payload: dict[str, Any]
    prompt_text: str


@dataclass(frozen=True)
class AgendaSnapshot:
    status: str
    events: list[CalendarEvent]
    error: str | None = None


class AssistantService:
    def __init__(
        self,
        *,
        storage: SQLiteStorage,
        calendar: CalendarService,
        settings: Settings,
        kbplus: KbplusTaskClient | None = None,
    ):
        self.storage = storage
        self.calendar = calendar
        self.settings = settings
        self.kbplus = kbplus

    def ensure_chat(self, *, chat_id: int, user_id: int) -> ChatPreferences:
        return self.storage.ensure_chat_preferences(
            chat_id=chat_id,
            user_id=user_id,
            timezone_name=self.settings.default_timezone,
            morning_brief_time=self.settings.morning_brief_time,
            hour_reminder_time=self.settings.hour_reminder_time,
            evening_wrap_up_time=self.settings.evening_wrap_up_time,
        )

    def _preferences(self, *, chat_id: int, user_id: int) -> ChatPreferences:
        return self.ensure_chat(chat_id=chat_id, user_id=user_id)

    def _local_now(self, preferences: ChatPreferences, now_utc: datetime | None = None) -> datetime:
        reference = now_utc or datetime.now(UTC)
        return reference.astimezone(ZoneInfo(preferences.timezone))

    def parse_local_datetime(self, *, chat_id: int, user_id: int, raw_text: str) -> datetime:
        preferences = self._preferences(chat_id=chat_id, user_id=user_id)
        try:
            naive = datetime.strptime(raw_text.strip(), "%Y-%m-%d %H:%M")
        except ValueError as exc:
            raise AssistantError("Format: YYYY-MM-DD HH:MM") from exc
        return naive.replace(tzinfo=ZoneInfo(preferences.timezone))

    def parse_flexible_local_datetime(
        self,
        *,
        chat_id: int,
        user_id: int,
        raw_text: str,
        reference_local: datetime | None = None,
    ) -> datetime:
        stripped = " ".join(raw_text.strip().split())
        if not stripped:
            raise AssistantError("Provide a date and time")

        try:
            return self.parse_local_datetime(chat_id=chat_id, user_id=user_id, raw_text=stripped)
        except AssistantError:
            pass

        preferences = self._preferences(chat_id=chat_id, user_id=user_id)
        timezone_info = ZoneInfo(preferences.timezone)
        reference = reference_local.astimezone(timezone_info) if reference_local else self._local_now(preferences)
        lower = stripped.lower()

        relative_match = re.fullmatch(r"(today|tomorrow)(?:\s+at)?\s+([01]?\d|2[0-3])(?::([0-5]\d))?", lower)
        if relative_match is not None:
            day_offset = 0 if relative_match.group(1) == "today" else 1
            hour = int(relative_match.group(2))
            minute = int(relative_match.group(3) or "0")
            target_date = reference.date() + timedelta(days=day_offset)
            return datetime(
                target_date.year,
                target_date.month,
                target_date.day,
                hour,
                minute,
                tzinfo=timezone_info,
            )

        dated_match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:\s+at)?\s+([01]?\d|2[0-3])(?::([0-5]\d))?", lower)
        if dated_match is not None:
            try:
                target_date = datetime.strptime(dated_match.group(1), "%Y-%m-%d").date()
            except ValueError as exc:
                raise AssistantError("Format: YYYY-MM-DD") from exc
            hour = int(dated_match.group(2))
            minute = int(dated_match.group(3) or "0")
            return datetime(
                target_date.year,
                target_date.month,
                target_date.day,
                hour,
                minute,
                tzinfo=timezone_info,
            )

        raise AssistantError("Format: 'tomorrow 20:00' or 'YYYY-MM-DD HH:MM'")

    def parse_time_or_local_datetime(
        self,
        *,
        chat_id: int,
        user_id: int,
        raw_text: str,
        anchor_local: datetime,
    ) -> datetime:
        stripped = " ".join(raw_text.strip().split())
        if not stripped:
            raise AssistantError("Provide an end time")

        time_only_match = re.fullmatch(r"([01]?\d|2[0-3])(?::([0-5]\d))?", stripped)
        if time_only_match is not None:
            candidate = anchor_local.replace(
                hour=int(time_only_match.group(1)),
                minute=int(time_only_match.group(2) or "0"),
                second=0,
                microsecond=0,
            )
        else:
            candidate = self.parse_local_datetime(chat_id=chat_id, user_id=user_id, raw_text=stripped)

        if candidate <= anchor_local:
            raise AssistantError("End time must be after start time")
        return candidate

    def create_items(self, *, chat_id: int, user_id: int, kind: str, titles: list[str]) -> list[int | str]:
        self.ensure_chat(chat_id=chat_id, user_id=user_id)
        cleaned = [title.strip() for title in titles if title.strip()]
        if not cleaned:
            raise AssistantError("Provide at least one item")
        if kind == "task" and self._kbplus_enabled():
            return [self._create_kbplus_task(title=title) for title in cleaned]
        return [
            self.storage.create_list_item(user_id=user_id, chat_id=chat_id, kind=kind, title=title) for title in cleaned
        ]

    def list_items(self, *, chat_id: int, user_id: int, kind: str, include_done: bool = False) -> list[ListItem]:
        self.ensure_chat(chat_id=chat_id, user_id=user_id)
        if kind == "task" and self._kbplus_enabled():
            items: list[ListItem] = []
            for column in self.list_task_columns(chat_id=chat_id, user_id=user_id, include_done=include_done):
                for task in column.tasks:
                    items.append(
                        ListItem(
                            id=task.id,
                            kind="task",
                            title=task.title,
                            done=column.is_done,
                            created_at=task.created_at or "",
                            updated_at=task.updated_at or "",
                            column_name=column.name,
                        )
                    )
            return items
        return self.storage.list_items(user_id=user_id, chat_id=chat_id, kind=kind, include_done=include_done)

    def list_task_columns(self, *, chat_id: int, user_id: int, include_done: bool = False) -> list[KbplusColumn]:
        self.ensure_chat(chat_id=chat_id, user_id=user_id)
        if self._kbplus_enabled() and self.kbplus is not None:
            try:
                return self.kbplus.list_columns(include_done=include_done)
            except KbplusIntegrationError as exc:
                raise AssistantError(str(exc)) from exc

        tasks = self.storage.list_items(user_id=user_id, chat_id=chat_id, kind="task", include_done=include_done)
        open_tasks = [
            KbplusTask(
                id=str(task.id),
                title=task.title,
                description=None,
                column_id="local-open",
                column_name="Open tasks",
                created_at=task.created_at,
                updated_at=task.updated_at,
            )
            for task in tasks
            if not task.done
        ]
        columns = [KbplusColumn(id="local-open", name="Open tasks", is_done=False, tasks=open_tasks)]
        if include_done:
            done_items = self.storage.list_items(user_id=user_id, chat_id=chat_id, kind="task", include_done=True)
            done_tasks = [
                KbplusTask(
                    id=str(task.id),
                    title=task.title,
                    description=None,
                    column_id="local-done",
                    column_name="Done",
                    created_at=task.created_at,
                    updated_at=task.updated_at,
                )
                for task in done_items
                if task.done
            ]
            columns.append(KbplusColumn(id="local-done", name="Done", is_done=True, tasks=done_tasks))
        return [column for column in columns if column.tasks or include_done]

    def rename_item(self, *, chat_id: int, user_id: int, kind: str, item_id: int | str, title: str) -> None:
        if not title.strip():
            raise AssistantError("Provide a new title")
        if kind == "task" and self._kbplus_enabled():
            self._rename_kbplus_task(task_id=str(item_id).strip(), title=title)
            return
        if kind == "task":
            existing_task = self.storage.get_list_item(
                user_id=user_id, chat_id=chat_id, kind=kind, item_id=int(item_id)
            )
            if existing_task is None:
                raise AssistantError(f"{kind.title()} #{item_id} not found")
        updated = self.storage.update_list_item(
            user_id=user_id, chat_id=chat_id, kind=kind, item_id=int(item_id), title=title
        )
        if not updated:
            raise AssistantError(f"{kind.title()} #{item_id} not found")

    def complete_item(self, *, chat_id: int, user_id: int, kind: str, item_id: int | str) -> None:
        if kind == "task" and self._kbplus_enabled():
            self._complete_kbplus_task(task_id=str(item_id).strip())
            return
        if kind == "task":
            existing_task = self.storage.get_list_item(
                user_id=user_id, chat_id=chat_id, kind=kind, item_id=int(item_id)
            )
            if existing_task is None:
                raise AssistantError(f"{kind.title()} #{item_id} not found")
        updated = self.storage.mark_list_item_done(user_id=user_id, chat_id=chat_id, kind=kind, item_id=int(item_id))
        if not updated:
            raise AssistantError(f"{kind.title()} #{item_id} not found")

    def add_note(self, *, chat_id: int, user_id: int, kind: str, content: str) -> int:
        self.ensure_chat(chat_id=chat_id, user_id=user_id)
        if not content.strip():
            raise AssistantError("Note content required")
        return self.storage.create_note(user_id=user_id, chat_id=chat_id, kind=kind, content=content)

    def list_notes(
        self, *, chat_id: int, user_id: int, kind: str | None = None, limit: int = 10, query: str | None = None
    ) -> list[NoteItem]:
        self.ensure_chat(chat_id=chat_id, user_id=user_id)
        return self.storage.list_notes(user_id=user_id, chat_id=chat_id, kind=kind, limit=limit, query=query)

    def remove_note(self, *, chat_id: int, user_id: int, note_id: int) -> bool:
        """Remove a note by ID. Returns True if deleted, False if not found."""
        self.ensure_chat(chat_id=chat_id, user_id=user_id)
        return self.storage.delete_note(note_id=note_id, user_id=user_id, chat_id=chat_id)

    def create_reminder(self, *, chat_id: int, user_id: int, due_text: str, message: str) -> int:
        if not message.strip():
            raise AssistantError("Reminder text required")
        due_local = self.parse_local_datetime(chat_id=chat_id, user_id=user_id, raw_text=due_text)
        due_utc = due_local.astimezone(UTC).isoformat()
        return self.storage.create_reminder(user_id=user_id, chat_id=chat_id, message=message, due_at=due_utc)

    def list_reminders(self, *, chat_id: int, user_id: int, pending_only: bool = False) -> list[ReminderItem]:
        self.ensure_chat(chat_id=chat_id, user_id=user_id)
        return self.storage.list_reminders(user_id=user_id, chat_id=chat_id, pending_only=pending_only)

    def update_reminder(self, *, chat_id: int, user_id: int, reminder_id: int, status: str) -> None:
        updated = self.storage.update_reminder_status(
            user_id=user_id, chat_id=chat_id, reminder_id=reminder_id, status=status
        )
        if not updated:
            raise AssistantError(f"Reminder #{reminder_id} not found")

    def add_hours(self, *, chat_id: int, user_id: int, raw_text: str) -> str:
        preferences = self.ensure_chat(chat_id=chat_id, user_id=user_id)
        hours = parse_hours(raw_text)
        local_today = self._local_now(preferences).date().isoformat()
        self.storage.create_hour_entry(
            user_id=user_id,
            chat_id=chat_id,
            entry_date=local_today,
            hours=hours,
            raw_text=raw_text,
        )
        day_total = self.storage.get_day_hours(user_id=user_id, chat_id=chat_id, entry_date=local_today)
        now_local = self._local_now(preferences)
        month_total = self.storage.aggregate_month_hours(
            user_id=user_id,
            chat_id=chat_id,
            year=now_local.year,
            month=now_local.month,
        )
        return format_subtotals(day_total, month_total)

    def get_month_hours(self, *, chat_id: int, user_id: int, month: int | None = None) -> str:
        preferences = self.ensure_chat(chat_id=chat_id, user_id=user_id)
        now_local = self._local_now(preferences)
        target_month = month or now_local.month
        total = self.storage.aggregate_month_hours(
            user_id=user_id,
            chat_id=chat_id,
            year=now_local.year,
            month=target_month,
        )
        return f"Month {target_month:02d}: {format_hours_total(total)}"

    DEFAULT_HOURLY_RATE: float = 30.0

    def get_month_euro(self, *, chat_id: int, user_id: int, month: int | None = None) -> str:
        preferences = self.ensure_chat(chat_id=chat_id, user_id=user_id)
        now_local = self._local_now(preferences)
        target_month = month or now_local.month
        total_hours = self.storage.aggregate_month_hours(
            user_id=user_id,
            chat_id=chat_id,
            year=now_local.year,
            month=target_month,
        )
        rate = preferences.hourly_rate if preferences.hourly_rate is not None else self.DEFAULT_HOURLY_RATE
        earnings = float(total_hours) * rate
        rate_label = f"{rate:.0f}€/h" if rate == int(rate) else f"{rate}€/h"
        return f"Month {target_month:02d}: {format_hours_total(total_hours)} × {rate_label} = {earnings:.0f}€"

    def set_hourly_rate(self, *, chat_id: int, user_id: int, rate: float) -> str:
        self.ensure_chat(chat_id=chat_id, user_id=user_id)
        self.storage.update_chat_preferences(chat_id, hourly_rate=rate)
        rate_label = f"{rate:.0f}€/h" if rate == int(rate) else f"{rate}€/h"
        return f"Hourly rate → {rate_label}"

    def list_calendar_events(self, *, chat_id: int, user_id: int, days: int = 7) -> list[CalendarEvent]:
        preferences = self.ensure_chat(chat_id=chat_id, user_id=user_id)
        local_now = self._local_now(preferences)
        local_end = local_now + timedelta(days=max(1, days))
        return self.list_calendar_events_between(
            chat_id=chat_id,
            user_id=user_id,
            start_local=local_now,
            end_local=local_end,
        )

    def resolve_calendar_window(
        self,
        *,
        chat_id: int,
        user_id: int,
        window: str,
        now_utc: datetime | None = None,
    ) -> tuple[str, datetime, datetime]:
        preferences = self.ensure_chat(chat_id=chat_id, user_id=user_id)
        timezone_info = ZoneInfo(preferences.timezone)
        local_now = (now_utc or datetime.now(UTC)).astimezone(timezone_info)
        today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        normalized_window = window.strip().lower()

        if normalized_window == "today":
            return "Today", local_now, today_start + timedelta(days=1)
        if normalized_window == "tomorrow":
            start_local = today_start + timedelta(days=1)
            return "Tomorrow", start_local, start_local + timedelta(days=1)
        if normalized_window == "next7":
            return "Next 7 days", local_now, local_now + timedelta(days=7)
        if normalized_window == "nextweek":
            days_until_next_monday = 7 - today_start.weekday()
            start_local = today_start + timedelta(days=days_until_next_monday)
            return "Next week", start_local, start_local + timedelta(days=7)
        raise AssistantError("Invalid window. Use: today, tomorrow, next7, nextweek")

    def render_calendar_window_for_ai(self, *, chat_id: int, user_id: int, window: str) -> str:
        title, start_local, end_local = self.resolve_calendar_window(
            chat_id=chat_id,
            user_id=user_id,
            window=window,
        )
        events = self.list_calendar_events_between(
            chat_id=chat_id,
            user_id=user_id,
            start_local=start_local,
            end_local=end_local,
        )
        preferences = self.ensure_chat(chat_id=chat_id, user_id=user_id)
        timezone_info = ZoneInfo(preferences.timezone)
        lines = [f"Calendar window: {title} ({window.strip().lower()})", f"Timezone: {preferences.timezone}"]
        if not events:
            lines.append("Events: none")
            return "\n".join(lines)

        lines.append("Events:")
        for event in events[:12]:
            if getattr(event, "all_day", False):
                start_date = getattr(event, "start_date", None)
                if start_date is not None:
                    day_label = start_date.isoformat()
                else:
                    start_value = event.start
                    if start_value.tzinfo is None:
                        start_value = start_value.replace(tzinfo=timezone_info)
                    day_label = start_value.astimezone(timezone_info).date().isoformat()
                lines.append(f"- {day_label} all-day — {event.summary}")
                continue

            start_value = event.start
            end_value = event.end
            if start_value.tzinfo is None:
                start_value = start_value.replace(tzinfo=timezone_info)
            if end_value.tzinfo is None:
                end_value = end_value.replace(tzinfo=timezone_info)
            start_value = start_value.astimezone(timezone_info)
            end_value = end_value.astimezone(timezone_info)
            lines.append(f"- {start_value.strftime('%Y-%m-%d %H:%M')}–{end_value.strftime('%H:%M')} — {event.summary}")

        return "\n".join(lines)

    def list_calendar_events_between(
        self,
        *,
        chat_id: int,
        user_id: int,
        start_local: datetime,
        end_local: datetime,
    ) -> list[CalendarEvent]:
        self.ensure_chat(chat_id=chat_id, user_id=user_id)
        if not self.calendar.configured:
            raise AssistantError("Calendar not configured")
        try:
            return self.calendar.list_events(start=start_local, end=end_local)
        except CalendarIntegrationError as exc:
            raise AssistantError(str(exc)) from exc

    def get_agenda_snapshot(self, *, chat_id: int, user_id: int, days: int = 2) -> AgendaSnapshot:
        preferences = self.ensure_chat(chat_id=chat_id, user_id=user_id)
        local_now = self._local_now(preferences)
        if not self.calendar.configured:
            return AgendaSnapshot(
                status="unavailable",
                events=[],
                error="calendar integration is not configured",
            )
        try:
            events = self.calendar.list_events(start=local_now, end=local_now + timedelta(days=max(1, days)))[:8]
        except CalendarIntegrationError as exc:
            logger.warning("Calendar agenda read failed for chat %s: %s", chat_id, exc)
            return AgendaSnapshot(status="error", events=[], error=str(exc))
        return AgendaSnapshot(status="ok" if events else "empty", events=events)

    def create_calendar_event(
        self,
        *,
        chat_id: int,
        user_id: int,
        start_text: str,
        end_text: str,
        summary: str,
        description: str | None = None,
    ) -> CalendarEvent:
        self.ensure_chat(chat_id=chat_id, user_id=user_id)
        if not self.calendar.configured:
            raise AssistantError("Calendar not configured")
        if not summary.strip():
            raise AssistantError("Provide a calendar event title")
        start = self.parse_local_datetime(chat_id=chat_id, user_id=user_id, raw_text=start_text)
        end = self.parse_local_datetime(chat_id=chat_id, user_id=user_id, raw_text=end_text)
        if end <= start:
            raise AssistantError("End time must be after start time")
        try:
            return self.calendar.create_event(start=start, end=end, summary=summary.strip(), description=description)
        except CalendarIntegrationError as exc:
            raise AssistantError(str(exc)) from exc

    def _kbplus_enabled(self) -> bool:
        return bool(self.kbplus and self.kbplus.configured)

    def _create_kbplus_task(self, *, title: str) -> str:
        if not self._kbplus_enabled() or self.kbplus is None:
            raise AssistantError("KB+ not configured")
        try:
            task_link = self.kbplus.create_task(title=title)
        except KbplusIntegrationError as exc:
            raise AssistantError(str(exc)) from exc
        return task_link.task_id

    def _rename_kbplus_task(self, *, task_id: str, title: str) -> None:
        if not self._kbplus_enabled() or self.kbplus is None:
            raise AssistantError("KB+ not configured")
        if not task_id:
            raise AssistantError("Provide a KB+ task id")
        try:
            self.kbplus.rename_task(task_id=task_id, title=title.strip())
        except KbplusIntegrationError as exc:
            raise AssistantError(str(exc)) from exc

    def _complete_kbplus_task(self, *, task_id: str) -> None:
        if not self._kbplus_enabled() or self.kbplus is None:
            raise AssistantError("KB+ not configured")
        if not task_id:
            raise AssistantError("Provide a KB+ task id")
        try:
            self.kbplus.complete_task(task_id=task_id)
        except KbplusIntegrationError as exc:
            raise AssistantError(str(exc)) from exc

    def get_tool_snapshot(self, *, chat_id: int, user_id: int) -> dict[str, Any]:
        preferences = self.ensure_chat(chat_id=chat_id, user_id=user_id)
        local_now = self._local_now(preferences)
        task_columns = self.list_task_columns(chat_id=chat_id, user_id=user_id, include_done=False)
        limited_task_columns: list[dict[str, Any]] = []
        tasks: list[dict[str, Any]] = []
        for column in task_columns:
            if len(limited_task_columns) >= 8 or len(tasks) >= 20:
                break
            limited_tasks: list[dict[str, Any]] = []
            for task in column.tasks:
                if len(tasks) >= 20:
                    break
                task_entry = {
                    "id": task.id,
                    "title": task.title,
                    "description": task.description,
                    "column": column.name,
                    "done": column.is_done,
                }
                tasks.append(task_entry)
                limited_tasks.append({"id": task.id, "title": task.title, "description": task.description})
            if limited_tasks:
                limited_task_columns.append(
                    {
                        "id": column.id,
                        "name": column.name,
                        "is_done": column.is_done,
                        "tasks": limited_tasks,
                    }
                )
        shopping = self.list_items(chat_id=chat_id, user_id=user_id, kind="shopping")[:20]
        reminders = self.list_reminders(chat_id=chat_id, user_id=user_id, pending_only=True)[:10]
        notes = self.list_notes(chat_id=chat_id, user_id=user_id, limit=8)
        month_total = self.storage.aggregate_month_hours(
            user_id=user_id,
            chat_id=chat_id,
            year=local_now.year,
            month=local_now.month,
        )
        agenda_snapshot = self.get_agenda_snapshot(chat_id=chat_id, user_id=user_id, days=2)
        agenda_entries = agenda_snapshot.events

        return {
            "now_local": local_now.isoformat(),
            "timezone": preferences.timezone,
            "tasks": tasks,
            "task_columns": limited_task_columns,
            "shopping": [{"id": item.id, "title": item.title, "done": item.done} for item in shopping],
            "reminders": [
                {
                    "id": item.id,
                    "message": item.message,
                    "due_at": item.due_at,
                    "due_at_local": self._format_utc_iso_for_chat(item.due_at, preferences),
                    "status": item.status,
                }
                for item in reminders
            ],
            "notes": [{"id": item.id, "kind": item.kind, "content": item.content} for item in notes],
            "hours": {
                "month_total": format_hours_total(month_total),
                "month_total_raw": str(month_total),
                "hourly_rate": preferences.hourly_rate
                if preferences.hourly_rate is not None
                else self.DEFAULT_HOURLY_RATE,
            },
            "agenda_status": agenda_snapshot.status,
            "agenda_error": agenda_snapshot.error,
            "agenda": [
                {
                    "summary": event.summary,
                    "start": event.start.isoformat(),
                    "end": event.end.isoformat(),
                    "start_local": event.start_date.isoformat()
                    if event.all_day and event.start_date is not None
                    else self._format_datetime_for_chat(event.start, preferences, all_day=event.all_day),
                    "end_local": event.end_date.isoformat()
                    if event.all_day and event.end_date is not None
                    else self._format_datetime_for_chat(event.end, preferences, all_day=event.all_day),
                    "all_day": event.all_day,
                }
                for event in agenda_entries
            ],
        }

    def create_pending_approval(
        self,
        *,
        chat_id: int,
        user_id: int,
        action_type: str,
        payload: dict[str, Any],
        prompt_text: str,
    ) -> PendingApproval:
        prepared = self._prepare_action(
            chat_id=chat_id,
            user_id=user_id,
            action_type=action_type,
            payload=payload,
            prompt_text=prompt_text,
        )
        token = secrets.token_hex(3)
        expires_at = (datetime.now(UTC) + timedelta(minutes=self.settings.approval_ttl_minutes)).isoformat()
        self.storage.create_approval(
            token=token,
            user_id=user_id,
            chat_id=chat_id,
            action_type=prepared.action_type,
            payload=prepared.payload,
            prompt_text=prepared.prompt_text,
            expires_at=expires_at,
        )
        return PendingApproval(token=token, prompt_text=prepared.prompt_text, expires_at=expires_at)

    def create_pending_tool_plan(
        self,
        *,
        chat_id: int,
        user_id: int,
        steps: list[dict[str, Any]],
        prompt_text: str = "",
    ) -> PendingApproval:
        prepared = self._prepare_tool_plan(
            chat_id=chat_id,
            user_id=user_id,
            steps=steps,
            prompt_text=prompt_text,
        )
        token = secrets.token_hex(3)
        expires_at = (datetime.now(UTC) + timedelta(minutes=self.settings.approval_ttl_minutes)).isoformat()
        self.storage.create_approval(
            token=token,
            user_id=user_id,
            chat_id=chat_id,
            action_type=prepared.action_type,
            payload=prepared.payload,
            prompt_text=prepared.prompt_text,
            expires_at=expires_at,
        )
        return PendingApproval(token=token, prompt_text=prepared.prompt_text, expires_at=expires_at)

    def _prepare_tool_plan(
        self,
        *,
        chat_id: int,
        user_id: int,
        steps: list[dict[str, Any]],
        prompt_text: str,
    ) -> PreparedAction:
        if not steps:
            raise AssistantError("Empty tool plan")
        preferences = self.ensure_chat(chat_id=chat_id, user_id=user_id)
        normalized_actions: list[dict[str, Any]] = []
        for step in steps:
            normalized_actions.extend(
                self._expand_tool_step(
                    chat_id=chat_id,
                    user_id=user_id,
                    tool=str(step.get("tool", "")).strip(),
                    operation=str(step.get("operation", "")).strip(),
                    args=dict(step.get("args") or {}),
                )
            )
        if not normalized_actions:
            raise AssistantError("Tool plan has no executable actions")
        custom_prompt = prompt_text.strip()
        if custom_prompt:
            summary = custom_prompt
        elif len(normalized_actions) == 1:
            only_action = normalized_actions[0]
            summary = self._build_action_prompt(
                action_type=str(only_action["action_type"]),
                payload=dict(only_action.get("payload") or {}),
                preferences=preferences,
                prompt_text="",
            )
        else:
            lines = [f"{len(normalized_actions)} planned actions:"]
            for action in normalized_actions[:12]:
                lines.append(
                    f"- {self._build_action_prompt(action_type=str(action['action_type']), payload=dict(action.get('payload') or {}), preferences=preferences, prompt_text='')}"
                )
            if len(normalized_actions) > 12:
                lines.append(f"- ...and {len(normalized_actions) - 12} more")
            summary = "\n".join(lines)
        return PreparedAction(
            action_type="tool_plan",
            payload={"actions": normalized_actions},
            prompt_text=summary,
        )

    def _expand_tool_step(
        self,
        *,
        chat_id: int,
        user_id: int,
        tool: str,
        operation: str,
        args: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if tool == "tasks":
            if operation == "create":
                title = str(args.get("title", "")).strip()
                if not title:
                    raise AssistantError("Task create: missing title")
                prepared = self._prepare_action(
                    chat_id=chat_id,
                    user_id=user_id,
                    action_type="create_task",
                    payload={"title": title},
                    prompt_text="",
                )
                return [{"action_type": prepared.action_type, "payload": prepared.payload}]
            if operation == "create_many":
                titles = [str(item).strip() for item in args.get("titles", []) if str(item).strip()]
                if not titles:
                    raise AssistantError("Task create_many: missing titles")
                return [
                    {
                        "action_type": prepared.action_type,
                        "payload": prepared.payload,
                    }
                    for prepared in (
                        self._prepare_action(
                            chat_id=chat_id,
                            user_id=user_id,
                            action_type="create_task",
                            payload={"title": title},
                            prompt_text="",
                        )
                        for title in titles
                    )
                ]
            if operation == "rename":
                prepared = self._prepare_action(
                    chat_id=chat_id,
                    user_id=user_id,
                    action_type="rename_list_item",
                    payload={"kind": "task", "item_id": args.get("id"), "title": args.get("title")},
                    prompt_text="",
                )
                return [{"action_type": prepared.action_type, "payload": prepared.payload}]
            if operation == "complete":
                prepared = self._prepare_action(
                    chat_id=chat_id,
                    user_id=user_id,
                    action_type="complete_list_item",
                    payload={"kind": "task", "item_id": args.get("id")},
                    prompt_text="",
                )
                return [{"action_type": prepared.action_type, "payload": prepared.payload}]

        if tool == "shopping":
            if operation == "create":
                item = str(args.get("title") or args.get("item") or "").strip()
                if not item:
                    raise AssistantError("Shopping create: missing item title")
                prepared = self._prepare_action(
                    chat_id=chat_id,
                    user_id=user_id,
                    action_type="add_shopping_items",
                    payload={"items": [item]},
                    prompt_text="",
                )
                return [{"action_type": prepared.action_type, "payload": prepared.payload}]
            if operation == "create_many":
                items = [str(item).strip() for item in args.get("titles", []) if str(item).strip()]
                if not items:
                    raise AssistantError("Shopping create_many: missing titles")
                prepared = self._prepare_action(
                    chat_id=chat_id,
                    user_id=user_id,
                    action_type="add_shopping_items",
                    payload={"items": items},
                    prompt_text="",
                )
                return [{"action_type": prepared.action_type, "payload": prepared.payload}]
            if operation == "rename":
                prepared = self._prepare_action(
                    chat_id=chat_id,
                    user_id=user_id,
                    action_type="rename_list_item",
                    payload={"kind": "shopping", "item_id": args.get("id"), "title": args.get("title")},
                    prompt_text="",
                )
                return [{"action_type": prepared.action_type, "payload": prepared.payload}]
            if operation == "complete":
                prepared = self._prepare_action(
                    chat_id=chat_id,
                    user_id=user_id,
                    action_type="complete_list_item",
                    payload={"kind": "shopping", "item_id": args.get("id")},
                    prompt_text="",
                )
                return [{"action_type": prepared.action_type, "payload": prepared.payload}]

        if tool == "notes" and operation == "create":
            prepared = self._prepare_action(
                chat_id=chat_id,
                user_id=user_id,
                action_type="create_note",
                payload={"kind": args.get("kind"), "content": args.get("content")},
                prompt_text="",
            )
            return [{"action_type": prepared.action_type, "payload": prepared.payload}]

        if tool == "notes" and operation == "delete":
            note_id = args.get("note_id")
            if not note_id:
                raise AssistantError("Note delete: missing note_id")
            prepared = self._prepare_action(
                chat_id=chat_id,
                user_id=user_id,
                action_type="delete_note",
                payload={"note_id": note_id},
                prompt_text="",
            )
            return [{"action_type": prepared.action_type, "payload": prepared.payload}]

        if tool == "reminders":
            if operation == "create":
                prepared = self._prepare_action(
                    chat_id=chat_id,
                    user_id=user_id,
                    action_type="create_reminder",
                    payload={"when_local": args.get("when_local"), "message": args.get("message")},
                    prompt_text="",
                )
                return [{"action_type": prepared.action_type, "payload": prepared.payload}]
            if operation in {"complete", "cancel"}:
                prepared = self._prepare_action(
                    chat_id=chat_id,
                    user_id=user_id,
                    action_type="update_reminder_status",
                    payload={
                        "reminder_id": args.get("id"),
                        "status": "done" if operation == "complete" else "cancelled",
                    },
                    prompt_text="",
                )
                return [{"action_type": prepared.action_type, "payload": prepared.payload}]

        if tool == "calendar" and operation == "create":
            prepared = self._prepare_action(
                chat_id=chat_id,
                user_id=user_id,
                action_type="create_calendar_event",
                payload={
                    "summary": args.get("summary") or args.get("title"),
                    "start_local": args.get("start_local"),
                    "end_local": args.get("end_local"),
                    "description": args.get("description"),
                },
                prompt_text="",
            )
            return [{"action_type": prepared.action_type, "payload": prepared.payload}]

        raise AssistantError(f"Unsupported tool: {tool}.{operation}")

    def _execute_tool_plan(self, *, chat_id: int, user_id: int, payload: dict[str, Any]) -> str:
        actions = payload.get("actions")
        if not isinstance(actions, list) or not actions:
            raise AssistantError("Tool plan missing actions")

        executed: list[str] = []
        failed: list[str] = []
        preferences = self.ensure_chat(chat_id=chat_id, user_id=user_id)
        for raw_action in actions:
            action_type = str((raw_action or {}).get("action_type", "")).strip()
            action_payload = dict((raw_action or {}).get("payload") or {})
            label = self._build_action_prompt(
                action_type=action_type,
                payload=action_payload,
                preferences=preferences,
                prompt_text="",
            )
            try:
                executed.append(
                    self._execute_action(
                        chat_id=chat_id,
                        user_id=user_id,
                        action_type=action_type,
                        payload=action_payload,
                    )
                )
            except AssistantError as exc:
                failed.append(f"{label} — {exc}")

        if failed and executed:
            lines = [f"Partial: {len(executed)}/{len(actions)} actions done."]
            lines.extend(f"- {entry}" for entry in executed)
            lines.append("Failed:")
            lines.extend(f"- {entry}" for entry in failed)
            return "\n".join(lines)
        if failed:
            lines = ["All actions failed.", "Failed:"]
            lines.extend(f"- {entry}" for entry in failed)
            raise AssistantError("\n".join(lines))
        if len(executed) == 1:
            return executed[0]
        return "\n".join([f"Done: {len(executed)} action(s).", *[f"- {entry}" for entry in executed]])

    def _execute_action(self, *, chat_id: int, user_id: int, action_type: str, payload: dict[str, Any]) -> str:
        payload = self._validate_action_payload(
            chat_id=chat_id,
            user_id=user_id,
            action_type=action_type,
            payload=payload,
        )
        if action_type == "create_task":
            title = str(payload.get("title", "")).strip()
            item_ids = self.create_items(chat_id=chat_id, user_id=user_id, kind="task", titles=[title])
            if self._kbplus_enabled():
                return "Task created."
            return f"Task #{item_ids[0]} created"
        if action_type == "add_shopping_items":
            items = [str(item).strip() for item in payload.get("items", []) if str(item).strip()]
            item_ids = self.create_items(chat_id=chat_id, user_id=user_id, kind="shopping", titles=items)
            return f"Added {len(item_ids)} shopping item(s)"
        if action_type == "create_note":
            content = str(payload.get("content", "")).strip()
            note_id = self.add_note(
                chat_id=chat_id,
                user_id=user_id,
                kind=payload.get("kind", "note"),
                content=content,
            )
            return f"Note #{note_id} saved"
        if action_type == "delete_note":
            note_id = int(payload.get("note_id", 0))
            deleted = self.remove_note(chat_id=chat_id, user_id=user_id, note_id=note_id)
            if deleted:
                return f"Note #{note_id} deleted"
            return f"Note #{note_id} not found"
        if action_type == "create_reminder":
            when_local = str(payload.get("when_local", "")).strip()
            message = str(payload.get("message", "")).strip()
            reminder_id = self.create_reminder(
                chat_id=chat_id,
                user_id=user_id,
                due_text=when_local,
                message=message,
            )
            return f"Reminder #{reminder_id} created"
        if action_type == "create_calendar_event":
            event = self.create_calendar_event(
                chat_id=chat_id,
                user_id=user_id,
                start_text=str(payload.get("start_local", "")).strip(),
                end_text=str(payload.get("end_local", "")).strip(),
                summary=str(payload.get("summary", "")).strip(),
                description=(
                    str(payload.get("description")).strip()
                    if payload.get("description") is not None and str(payload.get("description")).strip()
                    else None
                ),
            )
            return f"Event created: {event.summary}"
        if action_type == "rename_list_item":
            item_id = payload.get("item_id")
            if item_id is None:
                raise AssistantError("Item ID missing")
            self.rename_item(
                chat_id=chat_id,
                user_id=user_id,
                kind=str(payload.get("kind", "")).strip(),
                item_id=item_id,
                title=str(payload.get("title", "")).strip(),
            )
            label = "shopping item" if payload["kind"] == "shopping" else "task"
            if payload["kind"] == "task":
                return "Task renamed."
            return f"{label.capitalize()} {payload['item_id']} renamed"
        if action_type == "complete_list_item":
            item_id = payload.get("item_id")
            if item_id is None:
                raise AssistantError("Item ID missing")
            self.complete_item(
                chat_id=chat_id,
                user_id=user_id,
                kind=str(payload.get("kind", "")).strip(),
                item_id=item_id,
            )
            label = "shopping item" if payload["kind"] == "shopping" else "task"
            if payload["kind"] == "task":
                return "Task done."
            return f"{label.capitalize()} {payload['item_id']} done"
        if action_type == "update_reminder_status":
            self.update_reminder(
                chat_id=chat_id,
                user_id=user_id,
                reminder_id=int(payload.get("reminder_id", 0)),
                status=str(payload.get("status", "")).strip(),
            )
            return f"Reminder #{payload['reminder_id']} → {payload['status']}"

        raise AssistantError(f"Unsupported action: {action_type}")

    def confirm_approval(self, *, chat_id: int, user_id: int, token: str) -> str:
        approval = self.storage.get_approval(token=token, user_id=user_id, chat_id=chat_id)
        if approval is None:
            raise AssistantError("Token not found")
        if approval.status != "pending":
            raise AssistantError(f"Token already {approval.status}")
        if datetime.fromisoformat(approval.expires_at) < datetime.now(UTC):
            self.storage.transition_approval_status(token=token, expected_status="pending", new_status="expired")
            raise AssistantError("Token expired")
        try:
            if not self.storage.transition_approval_status(
                token=token, expected_status="pending", new_status="executing"
            ):
                approval = self.storage.get_approval(token=token, user_id=user_id, chat_id=chat_id)
                current_status = approval.status if approval else "missing"
                raise AssistantError(f"Token already {current_status}")
            if approval.action_type == "tool_plan":
                result = self._execute_tool_plan(chat_id=chat_id, user_id=user_id, payload=approval.payload)
            else:
                result = self._execute_action(
                    chat_id=chat_id,
                    user_id=user_id,
                    action_type=approval.action_type,
                    payload=approval.payload,
                )
        except Exception as exc:
            self.storage.transition_approval_status(token=token, expected_status="executing", new_status="pending")
            if isinstance(exc, AssistantError):
                raise
            raise AssistantError(str(exc)) from exc
        self.storage.transition_approval_status(token=token, expected_status="executing", new_status="executed")
        return result

    def reject_approval(self, *, chat_id: int, user_id: int, token: str) -> str:
        approval = self.storage.get_approval(token=token, user_id=user_id, chat_id=chat_id)
        if approval is None:
            raise AssistantError("Token not found")
        if not self.storage.transition_approval_status(token=token, expected_status="pending", new_status="rejected"):
            latest = self.storage.get_approval(token=token, user_id=user_id, chat_id=chat_id)
            current_status = latest.status if latest else "missing"
            raise AssistantError(f"Token already {current_status}")
        return f"Rejected {token}"

    def add_chat_history(self, *, chat_id: int, user_id: int, role: str, content: str) -> None:
        self.storage.add_chat_message(user_id=user_id, chat_id=chat_id, role=role, content=content)

    def get_chat_history(self, *, chat_id: int, user_id: int) -> list[ChatMessage]:
        return self.storage.get_recent_chat_messages(
            user_id=user_id,
            chat_id=chat_id,
            limit=self.settings.chat_history_limit,
        )

    def build_briefing(
        self, *, chat_id: int, user_id: int, now_utc: datetime | None = None, label: str = "Briefing"
    ) -> str:
        del now_utc
        snapshot = self.get_tool_snapshot(chat_id=chat_id, user_id=user_id)
        lines = [f"{label} ({snapshot['now_local'][:16].replace('T', ' ')})"]

        tasks = snapshot["tasks"]
        task_columns = snapshot.get("task_columns") or []
        shopping = snapshot["shopping"]
        reminders = snapshot["reminders"]
        notes = snapshot["notes"]
        agenda = snapshot["agenda"]
        agenda_status = str(snapshot.get("agenda_status") or ("ok" if agenda else "empty"))
        agenda_error = str(snapshot.get("agenda_error") or "").strip() or None

        lines.append(f"- Open tasks: {len(tasks)}")
        if tasks:
            if task_columns:
                shown = 0
                for column in task_columns:
                    column_tasks = column.get("tasks") or []
                    if not column_tasks:
                        continue
                    for task in column_tasks:
                        lines.append(f"  • [{column['name']}] {task['title']}")
                        shown += 1
                        if shown >= 5:
                            break
                    if shown >= 5:
                        break
            else:
                for item in tasks[:5]:
                    prefix = f"[{item['column']}] " if item.get("column") else ""
                    lines.append(f"  • {prefix}{item['title']}")

        lines.append(f"- Shopping items: {len(shopping)}")
        if shopping:
            for item in shopping[:5]:
                lines.append(f"  • {item['title']}")

        lines.append(f"- Pending reminders: {len(reminders)}")
        if reminders:
            for item in reminders[:5]:
                lines.append(f"  • {item['message']} @ {item['due_at_local']}")

        lines.append(f"- Notes/inbox items: {len(notes)}")
        if notes:
            for item in notes[:3]:
                lines.append(f"  • [{item['kind']}] {item['content'][:70]}")

        hours_info = snapshot["hours"]
        hours_rate = hours_info.get("hourly_rate", self.DEFAULT_HOURLY_RATE)
        month_hours_str = hours_info["month_total"]
        month_hours_raw = Decimal(hours_info.get("month_total_raw", "0"))
        month_euro = float(month_hours_raw) * hours_rate
        lines.append(f"- Month: {month_hours_str} (~{month_euro:.0f}€)")

        if agenda:
            lines.append("- Upcoming calendar:")
            for event in agenda[:5]:
                if event["all_day"]:
                    lines.append(f"  • {event['start_local']} — {event['summary']} (all day)")
                else:
                    lines.append(f"  • {event['start_local']} — {event['summary']}")
        elif agenda_status == "empty":
            lines.append("- Upcoming calendar: none")
        elif agenda_status == "unavailable":
            if agenda_error:
                lines.append(f"- Upcoming calendar: unavailable ({agenda_error})")
            else:
                lines.append("- Upcoming calendar: unavailable")
        else:
            if agenda_error:
                lines.append(f"- Upcoming calendar: unavailable ({agenda_error})")
            else:
                lines.append("- Upcoming calendar: unavailable")

        return "\n".join(lines)

    def get_due_notifications(self, *, now_utc: datetime | None = None) -> list[ScheduledNotification]:
        reference = now_utc or datetime.now(UTC)
        due_notifications: list[ScheduledNotification] = []

        for reminder in self.storage.claim_due_reminders(
            due_before=reference.isoformat(),
            stale_after_seconds=max(60, self.settings.reminder_scan_seconds * 5),
        ):
            preferences = self.storage.get_chat_preferences(reminder.chat_id)
            if not preferences.reminder_alerts_enabled:
                self.storage.reset_reminder_pending(reminder.id)
                continue
            local_due = datetime.fromisoformat(reminder.due_at).astimezone(ZoneInfo(preferences.timezone))
            due_notifications.append(
                ScheduledNotification(
                    chat_id=reminder.chat_id,
                    text=f"Reminder: {reminder.message}\nDue: {local_due.strftime('%Y-%m-%d %H:%M')}",
                    notification_type="reminder",
                    reminder_id=reminder.id,
                )
            )

        for preferences in self.storage.list_chat_preferences():
            local_now = self._local_now(preferences, reference)
            local_date = local_now.date().isoformat()

            if self._should_send_daily(
                enabled=preferences.morning_brief_enabled,
                local_now=local_now,
                target_time=preferences.morning_brief_time,
                last_sent_on=preferences.last_morning_brief_on,
            ) and self.storage.claim_scheduled_notification(
                chat_id=preferences.chat_id,
                notification_type="morning_brief",
                claim_date=local_date,
                stale_after_seconds=max(60, self.settings.reminder_scan_seconds * 5),
            ):
                due_notifications.append(
                    ScheduledNotification(
                        chat_id=preferences.chat_id,
                        text=self.build_briefing(
                            chat_id=preferences.chat_id,
                            user_id=preferences.user_id,
                            label="Morning briefing",
                        ),
                        notification_type="morning_brief",
                        claim_date=local_date,
                        preference_updates={"last_morning_brief_on": local_date},
                    )
                )

            if self._should_send_daily(
                enabled=preferences.hour_reminder_enabled,
                local_now=local_now,
                target_time=preferences.hour_reminder_time,
                last_sent_on=preferences.last_hour_reminder_on,
            ) and self.storage.claim_scheduled_notification(
                chat_id=preferences.chat_id,
                notification_type="hour_reminder",
                claim_date=local_date,
                stale_after_seconds=max(60, self.settings.reminder_scan_seconds * 5),
            ):
                due_notifications.append(
                    ScheduledNotification(
                        chat_id=preferences.chat_id,
                        text="Log your hours: /h add <hours>",
                        notification_type="hour_reminder",
                        claim_date=local_date,
                        preference_updates={"last_hour_reminder_on": local_date},
                    )
                )

            if self._should_send_daily(
                enabled=preferences.evening_wrap_up_enabled,
                local_now=local_now,
                target_time=preferences.evening_wrap_up_time,
                last_sent_on=preferences.last_evening_wrap_up_on,
            ) and self.storage.claim_scheduled_notification(
                chat_id=preferences.chat_id,
                notification_type="evening_wrap_up",
                claim_date=local_date,
                stale_after_seconds=max(60, self.settings.reminder_scan_seconds * 5),
            ):
                due_notifications.append(
                    ScheduledNotification(
                        chat_id=preferences.chat_id,
                        text=self.build_briefing(
                            chat_id=preferences.chat_id,
                            user_id=preferences.user_id,
                            label="Evening wrap-up",
                        ),
                        notification_type="evening_wrap_up",
                        claim_date=local_date,
                        preference_updates={"last_evening_wrap_up_on": local_date},
                    )
                )

        return due_notifications

    def mark_notification_delivered(self, notification: ScheduledNotification) -> None:
        if notification.reminder_id is not None:
            self.storage.mark_reminder_sent(notification.reminder_id)
        if notification.claim_date is not None:
            self.storage.mark_scheduled_notification_sent(
                chat_id=notification.chat_id,
                notification_type=notification.notification_type,
                claim_date=notification.claim_date,
            )
        if notification.preference_updates:
            self.storage.update_chat_preferences(notification.chat_id, **notification.preference_updates)

    def revert_notification_claim(self, notification: ScheduledNotification) -> None:
        if notification.reminder_id is not None:
            self.storage.reset_reminder_pending(notification.reminder_id)
        if notification.claim_date is not None:
            self.storage.release_scheduled_notification_claim(
                chat_id=notification.chat_id,
                notification_type=notification.notification_type,
                claim_date=notification.claim_date,
            )

    def _should_send_daily(
        self,
        *,
        enabled: bool,
        local_now: datetime,
        target_time: str,
        last_sent_on: str | None,
    ) -> bool:
        if not enabled:
            return False
        try:
            scheduled_time = time.fromisoformat(target_time)
        except ValueError:
            return False
        if local_now.date().isoformat() == last_sent_on:
            return False
        return local_now.time().replace(second=0, microsecond=0) >= scheduled_time

    def get_preferences_summary(self, *, chat_id: int, user_id: int) -> str:
        preferences = self.ensure_chat(chat_id=chat_id, user_id=user_id)
        rate = preferences.hourly_rate if preferences.hourly_rate is not None else self.DEFAULT_HOURLY_RATE
        rate_label = f"{rate:.0f}€/h" if rate == int(rate) else f"{rate}€/h"
        return (
            f"Timezone: {preferences.timezone}\n"
            f"Morning brief: {'on' if preferences.morning_brief_enabled else 'off'} @ {preferences.morning_brief_time}\n"
            f"Hour reminder: {'on' if preferences.hour_reminder_enabled else 'off'} @ {preferences.hour_reminder_time}\n"
            f"Evening wrap-up: {'on' if preferences.evening_wrap_up_enabled else 'off'} @ {preferences.evening_wrap_up_time}\n"
            f"Reminder alerts: {'on' if preferences.reminder_alerts_enabled else 'off'}\n"
            f"Hourly rate: {rate_label}"
        )

    def update_preference_toggle(self, *, chat_id: int, user_id: int, key: str, enabled: bool) -> str:
        self.ensure_chat(chat_id=chat_id, user_id=user_id)
        mapping = {
            "morning": "morning_brief_enabled",
            "hours": "hour_reminder_enabled",
            "evening": "evening_wrap_up_enabled",
            "reminders": "reminder_alerts_enabled",
        }
        if key not in mapping:
            raise AssistantError("Choose: morning, hours, evening, reminders")
        self.storage.update_chat_preferences(chat_id, **{mapping[key]: 1 if enabled else 0})
        return f"{key} → {'on' if enabled else 'off'}"

    def update_preference_time(self, *, chat_id: int, user_id: int, key: str, time_value: str) -> str:
        self.ensure_chat(chat_id=chat_id, user_id=user_id)
        try:
            time.fromisoformat(time_value)
        except ValueError as exc:
            raise AssistantError("Format: HH:MM") from exc
        mapping = {
            "morning": "morning_brief_time",
            "hours": "hour_reminder_time",
            "evening": "evening_wrap_up_time",
        }
        if key not in mapping:
            raise AssistantError("Choose: morning, hours, evening")
        self.storage.update_chat_preferences(chat_id, **{mapping[key]: time_value})
        return f"{key} time → {time_value}"

    def update_timezone(self, *, chat_id: int, user_id: int, timezone_name: str) -> str:
        self.ensure_chat(chat_id=chat_id, user_id=user_id)
        try:
            ZoneInfo(timezone_name)
        except Exception as exc:  # pragma: no cover - depends on system tz database
            raise AssistantError("Invalid timezone") from exc
        self.storage.update_chat_preferences(chat_id, timezone=timezone_name)
        return f"Timezone → {timezone_name}"

    def _format_utc_iso_for_chat(self, iso_value: str, preferences: ChatPreferences) -> str:
        return self._format_datetime_for_chat(datetime.fromisoformat(iso_value), preferences)

    def _format_datetime_for_chat(self, value: datetime, preferences: ChatPreferences, *, all_day: bool = False) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=ZoneInfo(preferences.timezone))
        local_value = value.astimezone(ZoneInfo(preferences.timezone))
        if all_day:
            return local_value.strftime("%Y-%m-%d")
        return local_value.strftime("%Y-%m-%d %H:%M")

    def _prepare_action(
        self,
        *,
        chat_id: int,
        user_id: int,
        action_type: str,
        payload: dict[str, Any],
        prompt_text: str,
    ) -> PreparedAction:
        preferences = self.ensure_chat(chat_id=chat_id, user_id=user_id)
        normalized_payload = self._validate_action_payload(
            chat_id=chat_id,
            user_id=user_id,
            action_type=action_type,
            payload=payload,
        )
        normalized_prompt = self._build_action_prompt(
            action_type=action_type,
            payload=normalized_payload,
            preferences=preferences,
            prompt_text=prompt_text,
        )
        return PreparedAction(
            action_type=action_type,
            payload=normalized_payload,
            prompt_text=normalized_prompt,
        )

    def _validate_action_payload(
        self,
        *,
        chat_id: int,
        user_id: int,
        action_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if action_type == "create_task":
            title = str(payload.get("title", "")).strip()
            if not title:
                raise AssistantError("Task title missing")
            return {"title": title}

        if action_type == "add_shopping_items":
            raw_items = payload.get("items")
            if isinstance(raw_items, str):
                items = [raw_items]
            elif isinstance(raw_items, list):
                items = [str(item).strip() for item in raw_items if str(item).strip()]
            else:
                items = []
            if not items:
                raise AssistantError("Shopping items missing")
            return {"items": items}

        if action_type == "create_note":
            content = str(payload.get("content", "")).strip()
            if not content:
                raise AssistantError("Note content missing")
            kind = str(payload.get("kind", "note")).strip() or "note"
            if kind not in {"note", "inbox"}:
                raise AssistantError("Invalid note kind")
            return {"kind": kind, "content": content}

        if action_type == "delete_note":
            try:
                note_id = int(payload.get("note_id", 0))
            except (TypeError, ValueError) as exc:
                raise AssistantError("Note ID missing") from exc
            if note_id <= 0:
                raise AssistantError("Note ID missing")
            return {"note_id": note_id}

        if action_type == "create_reminder":
            when_local = str(payload.get("when_local", "")).strip()
            message = str(payload.get("message", "")).strip()
            if not when_local or not message:
                raise AssistantError("Reminder time or message missing")
            due_local = self.parse_local_datetime(chat_id=chat_id, user_id=user_id, raw_text=when_local)
            return {
                "when_local": due_local.strftime("%Y-%m-%d %H:%M"),
                "message": message,
            }

        if action_type == "create_calendar_event":
            if not self.calendar.configured:
                raise AssistantError("Calendar not configured")
            summary = str(payload.get("summary") or payload.get("title") or "").strip()
            start_text = str(payload.get("start_local", "")).strip()
            end_text = str(payload.get("end_local", "")).strip()
            if not summary or not start_text or not end_text:
                raise AssistantError("Calendar action missing title, start, or end time")
            start_local = self.parse_local_datetime(chat_id=chat_id, user_id=user_id, raw_text=start_text)
            end_local = self.parse_local_datetime(chat_id=chat_id, user_id=user_id, raw_text=end_text)
            if end_local <= start_local:
                raise AssistantError("End time must be after start time")
            raw_description = payload.get("description")
            description = str(raw_description).strip() if raw_description is not None else None
            if description == "":
                description = None
            return {
                "summary": summary,
                "start_local": start_local.strftime("%Y-%m-%d %H:%M"),
                "end_local": end_local.strftime("%Y-%m-%d %H:%M"),
                "description": description,
            }

        if action_type == "rename_list_item":
            kind = str(payload.get("kind", "")).strip()
            if kind not in {"task", "shopping"}:
                raise AssistantError("Invalid item kind")
            raw_item_id = payload.get("item_id")
            if kind == "task":
                item_id: int | str = str(raw_item_id or "").strip()
                if not item_id:
                    raise AssistantError("Item ID missing")
            else:
                try:
                    item_id = int(raw_item_id or 0)
                except (TypeError, ValueError) as exc:
                    raise AssistantError("Item ID missing") from exc
                if item_id <= 0:
                    raise AssistantError("Item ID missing")
            title = str(payload.get("title", "")).strip()
            if not title:
                raise AssistantError("Item ID or title missing")
            return {"kind": kind, "item_id": item_id, "title": title}

        if action_type == "complete_list_item":
            kind = str(payload.get("kind", "")).strip()
            if kind not in {"task", "shopping"}:
                raise AssistantError("Invalid item kind")
            raw_item_id = payload.get("item_id")
            if kind == "task":
                item_id = str(raw_item_id or "").strip()
                if not item_id:
                    raise AssistantError("Item ID missing")
            else:
                try:
                    item_id = int(raw_item_id or 0)
                except (TypeError, ValueError) as exc:
                    raise AssistantError("Item ID missing") from exc
                if item_id <= 0:
                    raise AssistantError("Item ID missing")
            return {"kind": kind, "item_id": item_id}

        if action_type == "update_reminder_status":
            try:
                reminder_id = int(payload.get("reminder_id", 0))
            except (TypeError, ValueError) as exc:
                raise AssistantError("Reminder ID missing") from exc
            status = str(payload.get("status", "")).strip()
            if reminder_id <= 0 or status not in {"done", "cancelled"}:
                raise AssistantError("Reminder ID or status missing")
            return {"reminder_id": reminder_id, "status": status}

        raise AssistantError(f"Unsupported action: {action_type}")

    def _build_action_prompt(
        self,
        *,
        action_type: str,
        payload: dict[str, Any],
        preferences: ChatPreferences,
        prompt_text: str,
    ) -> str:
        custom_prompt = prompt_text.strip()
        if action_type in {"create_reminder", "create_calendar_event"}:
            custom_prompt = ""
        if custom_prompt:
            return custom_prompt

        if action_type == "create_task":
            return f"Create task: {payload['title']}"
        if action_type == "add_shopping_items":
            return f"Add to shopping: {', '.join(payload['items'])}"
        if action_type == "create_note":
            return f"Save {payload['kind']}: {payload['content']}"
        if action_type == "delete_note":
            return f"Delete note #{payload['note_id']}"
        if action_type == "create_reminder":
            return f'Reminder: "{payload["message"]}" @ {payload["when_local"]} ({preferences.timezone})'
        if action_type == "create_calendar_event":
            start_label = payload["start_local"]
            end_label = payload["end_local"]
            return f'Event: "{payload["summary"]}" @ {start_label} to {end_label} ({preferences.timezone})'
        if action_type == "rename_list_item":
            label = "shopping item" if payload["kind"] == "shopping" else "task"
            return f"Rename {label} {payload['item_id']} → {payload['title']}"
        if action_type == "complete_list_item":
            label = "shopping item" if payload["kind"] == "shopping" else "task"
            return f"Complete {label} {payload['item_id']}"
        if action_type == "update_reminder_status":
            return f"Reminder #{payload['reminder_id']} → {payload['status']}"
        return custom_prompt or action_type
