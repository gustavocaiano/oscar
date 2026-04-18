from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from personal_assistant_bot.config import Settings
from personal_assistant_bot.kbplus_integration import KbplusColumn, KbplusIntegrationError, KbplusTask
from personal_assistant_bot.services import AssistantService
from personal_assistant_bot.storage import SQLiteStorage


@dataclass
class FakeCalendarService:
    configured: bool = False
    events: list[object] | None = None
    error_message: str | None = None

    def list_events(self, *, start, end):
        del start, end
        if self.error_message:
            from personal_assistant_bot.calendar_integration import CalendarIntegrationError

            raise CalendarIntegrationError(self.error_message)
        return list(self.events or [])

    def create_event(self, *, start, end, summary, description=None):
        return type("Event", (), {"summary": summary, "start": start, "end": end, "uid": "evt-1"})


def build_settings(tmp_path: Path) -> Settings:
    return Settings(
        telegram_bot_token="token",
        allowed_chat_ids=frozenset(),
        database_path=tmp_path / "assistant.sqlite3",
        backend_base_url=None,
        backend_api_key=None,
        backend_model=None,
        backend_timeout_seconds=60.0,
        chat_history_limit=12,
        approval_ttl_minutes=30,
        default_timezone="UTC",
        morning_brief_time="08:00",
        hour_reminder_time="18:00",
        evening_wrap_up_time="20:00",
        reminder_scan_seconds=60,
        caldav_url=None,
        caldav_username=None,
        caldav_password=None,
        caldav_calendar_name=None,
        log_level=20,
    )


def build_service(tmp_path: Path, calendar: FakeCalendarService | None = None) -> AssistantService:
    settings = build_settings(tmp_path)
    storage = SQLiteStorage(settings.database_path)
    return AssistantService(storage=storage, calendar=calendar or FakeCalendarService(), settings=settings)


class FakeKbplusClient:
    configured = True
    board_id = "board_1"
    todo_column_id = "todo"
    done_column_id = "done"

    def __init__(self) -> None:
        self.created_titles: list[str] = []
        self.renamed: list[tuple[str, str]] = []
        self.completed: list[str] = []
        self.columns = [
            KbplusColumn(id="todo", name="Todo", is_done=False, tasks=[]),
            KbplusColumn(id="doing", name="Doing", is_done=False, tasks=[]),
            KbplusColumn(id="done", name="Done", is_done=True, tasks=[]),
        ]

    def list_columns(self, *, include_done: bool = False) -> list[KbplusColumn]:
        columns = self.columns if include_done else [column for column in self.columns if not column.is_done]
        return [
            KbplusColumn(id=column.id, name=column.name, is_done=column.is_done, tasks=list(column.tasks))
            for column in columns
        ]

    def create_task(self, *, title: str, description: str | None = None):
        del description
        self.created_titles.append(title)
        task_id = f"remote-{len(self.created_titles)}"
        todo_index = next(index for index, column in enumerate(self.columns) if column.id == "todo")
        todo_column = self.columns[todo_index]
        new_tasks = list(todo_column.tasks) + [
            KbplusTask(
                id=task_id,
                title=title,
                description=None,
                column_id="todo",
                column_name="Todo",
            )
        ]
        self.columns[todo_index] = KbplusColumn(id="todo", name="Todo", is_done=False, tasks=new_tasks)
        return type("TaskLink", (), {"task_id": task_id})

    def rename_task(self, *, task_id: str, title: str) -> None:
        self.renamed.append((task_id, title))
        for index, column in enumerate(self.columns):
            updated = False
            new_tasks: list[KbplusTask] = []
            for task in column.tasks:
                if task.id == task_id:
                    new_tasks.append(
                        KbplusTask(
                            id=task.id,
                            title=title,
                            description=task.description,
                            column_id=task.column_id,
                            column_name=task.column_name,
                        )
                    )
                    updated = True
                else:
                    new_tasks.append(task)
            if updated:
                self.columns[index] = KbplusColumn(id=column.id, name=column.name, is_done=column.is_done, tasks=new_tasks)
                return
        raise KbplusIntegrationError("Task not found")

    def complete_task(self, *, task_id: str) -> None:
        self.completed.append(task_id)
        moved_task: KbplusTask | None = None
        for index, column in enumerate(self.columns):
            remaining = [task for task in column.tasks if task.id != task_id]
            if len(remaining) != len(column.tasks):
                moved_task = next(task for task in column.tasks if task.id == task_id)
                self.columns[index] = KbplusColumn(id=column.id, name=column.name, is_done=column.is_done, tasks=remaining)
                break
        if moved_task is None:
            raise KbplusIntegrationError("Task not found")
        done_index = next(index for index, column in enumerate(self.columns) if column.id == "done")
        done_column = self.columns[done_index]
        done_tasks = list(done_column.tasks) + [
            KbplusTask(
                id=moved_task.id,
                title=moved_task.title,
                description=moved_task.description,
                column_id="done",
                column_name="Done",
            )
        ]
        self.columns[done_index] = KbplusColumn(id="done", name="Done", is_done=True, tasks=done_tasks)


class FailingKbplusClient(FakeKbplusClient):
    def __init__(self, *, fail_on: str) -> None:
        super().__init__()
        self.fail_on = fail_on

    def create_task(self, *, title: str, description: str | None = None):
        if self.fail_on == "create":
            raise KbplusIntegrationError("create failed")
        return super().create_task(title=title, description=description)

    def rename_task(self, *, task_id: str, title: str) -> None:
        if self.fail_on == "rename":
            raise KbplusIntegrationError("rename failed")
        super().rename_task(task_id=task_id, title=title)

    def complete_task(self, *, task_id: str) -> None:
        if self.fail_on == "complete":
            raise KbplusIntegrationError("complete failed")
        super().complete_task(task_id=task_id)


def test_task_and_shopping_lifecycle(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    task_ids = service.create_items(chat_id=1, user_id=2, kind="task", titles=["Buy milk", "Call bank"])
    shop_ids = service.create_items(chat_id=1, user_id=2, kind="shopping", titles=["Eggs"])

    assert len(task_ids) == 2
    assert len(shop_ids) == 1

    service.rename_item(chat_id=1, user_id=2, kind="task", item_id=task_ids[0], title="Buy oat milk")
    tasks = service.list_items(chat_id=1, user_id=2, kind="task")
    assert [task.title for task in tasks] == ["Buy oat milk", "Call bank"]

    service.complete_item(chat_id=1, user_id=2, kind="shopping", item_id=shop_ids[0])
    shopping = service.list_items(chat_id=1, user_id=2, kind="shopping")
    assert shopping == []


def test_notes_reminders_and_briefing(tmp_path: Path) -> None:
    calendar = FakeCalendarService(
        configured=True,
        events=[
            type(
                "Event",
                (),
                {
                    "summary": "Dentist",
                    "start": datetime(2026, 4, 1, 14, 0, tzinfo=timezone.utc),
                    "end": datetime(2026, 4, 1, 15, 0, tzinfo=timezone.utc),
                    "uid": "evt-1",
                },
            )
        ],
    )
    service = build_service(tmp_path, calendar=calendar)

    service.create_items(chat_id=10, user_id=11, kind="task", titles=["Renew passport"])
    service.create_items(chat_id=10, user_id=11, kind="shopping", titles=["Coffee"])
    service.add_note(chat_id=10, user_id=11, kind="note", content="Gift idea for Ana")
    reminder_id = service.create_reminder(chat_id=10, user_id=11, due_text="2026-04-01 09:00", message="Call the bank")

    reminders = service.list_reminders(chat_id=10, user_id=11, pending_only=True)
    assert reminders[0].id == reminder_id

    briefing = service.build_briefing(chat_id=10, user_id=11, label="Morning briefing")
    assert "Renew passport" in briefing
    assert "Coffee" in briefing
    assert "Gift idea for Ana" in briefing
    assert "Dentist" in briefing


def test_tool_snapshot_distinguishes_empty_and_unavailable_calendar(tmp_path: Path) -> None:
    empty_service = build_service(tmp_path / "empty", calendar=FakeCalendarService(configured=True, events=[]))
    empty_snapshot = empty_service.get_tool_snapshot(chat_id=1, user_id=2)
    assert empty_snapshot["agenda_status"] == "empty"
    assert empty_snapshot["agenda_error"] is None
    assert "Upcoming calendar: none" in empty_service.build_briefing(chat_id=1, user_id=2)

    error_service = build_service(
        tmp_path / "error",
        calendar=FakeCalendarService(configured=True, error_message="Calendar 'Work' was not found"),
    )
    error_snapshot = error_service.get_tool_snapshot(chat_id=1, user_id=2)
    assert error_snapshot["agenda_status"] == "error"
    assert error_snapshot["agenda_error"] == "Calendar 'Work' was not found"
    assert "unavailable (Calendar 'Work' was not found)" in error_service.build_briefing(chat_id=1, user_id=2)


def test_resolve_calendar_window_supports_fixed_ai_windows(tmp_path: Path) -> None:
    service = build_service(tmp_path, calendar=FakeCalendarService(configured=True, events=[]))
    now_utc = datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc)  # Saturday

    today_title, today_start, today_end = service.resolve_calendar_window(
        chat_id=1,
        user_id=2,
        window="today",
        now_utc=now_utc,
    )
    assert today_title == "Today"
    assert today_start.isoformat() == "2026-04-18T12:00:00+00:00"
    assert today_end.isoformat() == "2026-04-19T00:00:00+00:00"

    tomorrow_title, tomorrow_start, tomorrow_end = service.resolve_calendar_window(
        chat_id=1,
        user_id=2,
        window="tomorrow",
        now_utc=now_utc,
    )
    assert tomorrow_title == "Tomorrow"
    assert tomorrow_start.isoformat() == "2026-04-19T00:00:00+00:00"
    assert tomorrow_end.isoformat() == "2026-04-20T00:00:00+00:00"

    next7_title, next7_start, next7_end = service.resolve_calendar_window(
        chat_id=1,
        user_id=2,
        window="next7",
        now_utc=now_utc,
    )
    assert next7_title == "Next 7 days"
    assert next7_start.isoformat() == "2026-04-18T12:00:00+00:00"
    assert next7_end.isoformat() == "2026-04-25T12:00:00+00:00"

    nextweek_title, nextweek_start, nextweek_end = service.resolve_calendar_window(
        chat_id=1,
        user_id=2,
        window="nextweek",
        now_utc=now_utc,
    )
    assert nextweek_title == "Next week"
    assert nextweek_start.isoformat() == "2026-04-20T00:00:00+00:00"
    assert nextweek_end.isoformat() == "2026-04-27T00:00:00+00:00"


def test_render_calendar_window_for_ai_returns_compact_text(tmp_path: Path) -> None:
    calendar = FakeCalendarService(
        configured=True,
        events=[
            type(
                "Event",
                (),
                {
                    "summary": "Standup",
                    "start": datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
                    "end": datetime(2026, 4, 19, 10, 30, tzinfo=timezone.utc),
                    "uid": "evt-standup",
                },
            )
        ],
    )
    service = build_service(tmp_path, calendar=calendar)

    text = service.render_calendar_window_for_ai(chat_id=1, user_id=2, window="tomorrow")

    assert "Calendar window: Tomorrow (tomorrow)" in text
    assert "Timezone: UTC" in text
    assert "2026-04-19 10:00" in text
    assert "Standup" in text


def test_task_syncs_to_kbplus_when_configured(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    storage = SQLiteStorage(settings.database_path)
    kbplus = FakeKbplusClient()
    service = AssistantService(
        storage=storage,
        calendar=FakeCalendarService(),
        settings=settings,
        kbplus=kbplus,
    )

    task_id = service.create_items(chat_id=10, user_id=11, kind="task", titles=["Ship roadmap"])[0]
    service.rename_item(chat_id=10, user_id=11, kind="task", item_id=task_id, title="Ship roadmap v2")
    service.complete_item(chat_id=10, user_id=11, kind="task", item_id=task_id)

    assert kbplus.created_titles == ["Ship roadmap"]
    assert kbplus.renamed == [("remote-1", "Ship roadmap v2")]
    assert kbplus.completed == ["remote-1"]
    assert service.storage.list_items(user_id=11, chat_id=10, kind="task") == []

    open_tasks = service.list_items(chat_id=10, user_id=11, kind="task")
    assert open_tasks == []

    all_columns = service.list_task_columns(chat_id=10, user_id=11, include_done=True)
    assert [column.name for column in all_columns] == ["Todo", "Doing", "Done"]
    assert [task.title for task in all_columns[-1].tasks] == ["Ship roadmap v2"]


def test_kbplus_failure_does_not_apply_local_task_update_first(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    storage = SQLiteStorage(settings.database_path)
    kbplus = FailingKbplusClient(fail_on="rename")
    service = AssistantService(
        storage=storage,
        calendar=FakeCalendarService(),
        settings=settings,
        kbplus=kbplus,
    )

    task_id = service.create_items(chat_id=10, user_id=11, kind="task", titles=["Ship roadmap"])[0]

    try:
        service.rename_item(chat_id=10, user_id=11, kind="task", item_id=task_id, title="Ship roadmap v2")
    except Exception as exc:
        assert "rename failed" in str(exc)
    else:
        raise AssertionError("Expected rename to fail")

    tasks = service.list_items(chat_id=10, user_id=11, kind="task")
    assert [task.title for task in tasks] == ["Ship roadmap"]


def test_kbplus_task_list_is_grouped_by_columns_in_snapshot(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    storage = SQLiteStorage(settings.database_path)
    kbplus = FakeKbplusClient()
    kbplus.create_task(title="Alpha")
    doing_index = next(index for index, column in enumerate(kbplus.columns) if column.id == "doing")
    kbplus.columns[doing_index] = KbplusColumn(
        id="doing",
        name="Doing",
        is_done=False,
        tasks=[KbplusTask(id="remote-9", title="Beta", description=None, column_id="doing", column_name="Doing")],
    )
    service = AssistantService(
        storage=storage,
        calendar=FakeCalendarService(),
        settings=settings,
        kbplus=kbplus,
    )

    snapshot = service.get_tool_snapshot(chat_id=10, user_id=11)

    assert [column["name"] for column in snapshot["task_columns"]] == ["Todo", "Doing"]
    assert [task["title"] for task in snapshot["tasks"]] == ["Alpha", "Beta"]
