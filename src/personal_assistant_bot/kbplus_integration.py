from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class KbplusIntegrationError(RuntimeError):
    """Raised when KB+ integration requests fail."""


@dataclass(frozen=True)
class KbplusTask:
    id: str
    title: str
    description: str | None
    column_id: str
    column_name: str
    position: int | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class KbplusColumn:
    id: str
    name: str
    tasks: list[KbplusTask]
    is_done: bool = False


@dataclass(frozen=True)
class KbplusTaskLink:
    task_id: str


class KbplusTaskClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_token: str | None = None,
        board_id: str | None = None,
        todo_column_id: str | None = None,
        done_column_id: str | None = None,
        timeout_seconds: float = 10.0,
    ):
        self.base_url = base_url.rstrip("/") if base_url else None
        self.api_token = api_token
        self.board_id = board_id
        self.todo_column_id = todo_column_id
        self.done_column_id = done_column_id
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(
            self.base_url and self.api_token and self.board_id and self.todo_column_id and self.done_column_id
        )

    def list_columns(self, *, include_done: bool = False) -> list[KbplusColumn]:
        data = self._request("GET", f"/api/integrations/v1/boards/{self.board_id}/tasks")
        raw_columns = data.get("columns")
        if not isinstance(raw_columns, list):
            raise KbplusIntegrationError("KB+ task list response did not include columns")

        columns: list[KbplusColumn] = []
        for raw_column in raw_columns:
            if not isinstance(raw_column, dict):
                continue
            column_id = str(raw_column.get("id", "")).strip()
            column_name = str(raw_column.get("name", "")).strip() or column_id
            if not column_id:
                continue
            is_done = bool(raw_column.get("isDone")) or column_id == self.done_column_id
            if is_done and not include_done:
                continue
            raw_tasks = raw_column.get("tasks")
            tasks: list[KbplusTask] = []
            if isinstance(raw_tasks, list):
                for raw_task in raw_tasks:
                    if not isinstance(raw_task, dict):
                        continue
                    task_id = str(raw_task.get("id", "")).strip()
                    title = str(raw_task.get("title", "")).strip()
                    if not task_id or not title:
                        continue
                    tasks.append(
                        KbplusTask(
                            id=task_id,
                            title=title,
                            description=(
                                str(raw_task.get("description")).strip()
                                if raw_task.get("description") is not None
                                else None
                            ),
                            column_id=column_id,
                            column_name=column_name,
                            position=int(raw_task["position"]) if isinstance(raw_task.get("position"), int) else None,
                            created_at=(
                                str(raw_task.get("createdAt")).strip() if raw_task.get("createdAt") is not None else None
                            ),
                            updated_at=(
                                str(raw_task.get("updatedAt")).strip() if raw_task.get("updatedAt") is not None else None
                            ),
                        )
                    )
            columns.append(KbplusColumn(id=column_id, name=column_name, tasks=tasks, is_done=is_done))
        return columns

    def create_task(self, *, title: str, description: str | None = None) -> KbplusTaskLink:
        if not self.todo_column_id:
            raise KbplusIntegrationError("KB+ to-do column is not configured")
        data = self._request(
            "POST",
            f"/api/integrations/v1/boards/{self.board_id}/tasks",
            payload={
                "columnId": self.todo_column_id,
                "title": title,
                "description": description or "",
            },
        )
        task = data.get("task") if isinstance(data, dict) else None
        task_id = str(task.get("id", "")).strip() if isinstance(task, dict) else ""
        if not task_id:
            raise KbplusIntegrationError("KB+ create task response did not include task.id")
        return KbplusTaskLink(task_id=task_id)

    def rename_task(self, *, task_id: str, title: str) -> None:
        self._request(
            "PATCH",
            f"/api/integrations/v1/boards/{self.board_id}/tasks/{task_id}",
            payload={"title": title},
        )

    def complete_task(self, *, task_id: str) -> None:
        if not self.done_column_id:
            raise KbplusIntegrationError("KB+ done column is not configured")
        self._request(
            "POST",
            f"/api/integrations/v1/boards/{self.board_id}/tasks/{task_id}/complete",
            payload={"columnId": self.done_column_id},
        )

    def _request(self, method: str, path: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.configured:
            raise KbplusIntegrationError("KB+ integration is not configured")

        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}{path}"

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.request(method, url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise KbplusIntegrationError(f"KB+ request failed: {exc}") from exc

        try:
            data = response.json() if response.content else {}
        except ValueError:
            data = {}

        if response.is_error:
            error_message = ""
            if isinstance(data, dict):
                error_message = str(data.get("error", "")).strip()
            if not error_message:
                error_message = response.text.strip() or f"HTTP {response.status_code}"
            raise KbplusIntegrationError(error_message)

        return data if isinstance(data, dict) else {}
