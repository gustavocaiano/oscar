from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from personal_assistant_bot.storage import ChatMessage


logger = logging.getLogger(__name__)


class AIBackendError(RuntimeError):
    """Raised when the AI backend is unavailable or invalid."""


@dataclass(frozen=True)
class AIResponse:
    reply: str
    proposed_action: dict[str, Any] | None = None
    tool_plan: list[dict[str, Any]] | None = None
    proposal_error: str | None = None


class OpenAICompatibleAI:
    LEGACY_SUPPORTED_ACTIONS = {
        "create_task",
        "add_shopping_items",
        "create_note",
        "create_reminder",
        "create_calendar_event",
    }
    SUPPORTED_TOOLS = {"tasks", "shopping", "notes", "reminders", "calendar"}

    PROPOSAL_TOOLS: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "tasks",
                "description": "Plan task changes such as creating, renaming, or completing one or more tasks.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["create", "create_many", "rename", "complete"],
                        },
                        "title": {"type": "string"},
                        "titles": {"type": "array", "items": {"type": "string"}},
                        "id": {"type": "string"},
                    },
                    "required": ["operation"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shopping",
                "description": "Plan shopping-list changes such as adding, renaming, or completing items.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["create", "create_many", "rename", "complete"],
                        },
                        "title": {"type": "string"},
                        "titles": {"type": "array", "items": {"type": "string"}},
                        "id": {"type": "integer"},
                    },
                    "required": ["operation"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "notes",
                "description": "Manage notes and inbox items. Use create to add new notes/inbox items, use delete to remove existing items by ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["create", "delete"]},
                        "note_id": {"type": "integer", "description": "The note ID to delete. Required when operation is 'delete'."},
                        "kind": {"type": "string", "enum": ["note", "inbox"], "description": "Type of note. Required when operation is 'create'."},
                        "content": {"type": "string", "description": "Note content. Required when operation is 'create'."},
                    },
                    "required": ["operation"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "reminders",
                "description": "Plan reminder changes such as creating, completing, or cancelling reminders.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["create", "complete", "cancel"]},
                        "message": {"type": "string"},
                        "when_local": {
                            "type": "string",
                            "description": "Local date/time in exact format YYYY-MM-DD HH:MM when creating reminders.",
                        },
                        "id": {"type": "integer"},
                    },
                    "required": ["operation"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "calendar",
                "description": "Plan calendar event creation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["create"]},
                        "summary": {"type": "string"},
                        "start_local": {
                            "type": "string",
                            "description": "Local start date/time in exact format YYYY-MM-DD HH:MM.",
                        },
                        "end_local": {
                            "type": "string",
                            "description": "Local end date/time in exact format YYYY-MM-DD HH:MM.",
                        },
                        "description": {"type": "string"},
                    },
                    "required": ["operation", "summary", "start_local", "end_local"],
                    "additionalProperties": False,
                },
            },
        },
    ]

    def __init__(self, *, base_url: str | None, api_key: str | None, model: str | None, timeout_seconds: float):
        self.base_url = base_url.rstrip("/") if base_url else None
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    async def respond(
        self,
        *,
        user_message: str,
        history: list[ChatMessage],
        tool_snapshot: dict[str, Any],
    ) -> AIResponse:
        if not self.configured:
            raise AIBackendError("AI backend is not configured")

        prompt_messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "You are a Telegram personal assistant. Use the provided personal data snapshot to answer read/list questions directly. "
                    "If the user wants to create or change structured assistant data, use the provided function tools to propose the changes. "
                    "You may call multiple tools in one response. The app will ask the user to confirm before any write happens, so never say a write already happened. "
                    "For write intents, do exactly one of these: ask one short follow-up question if required fields are missing or ambiguous; OR call one or more tools. "
                    "Prefer the snapshot for read queries instead of function tools. "
                    "When creating reminders or calendar events, every local date/time must use exact format YYYY-MM-DD HH:MM. "
                    "Task ids in the snapshot may be opaque strings from KB+; when renaming or completing tasks, copy the task id exactly as shown."
                ),
            },
            {
                "role": "system",
                "content": f"PERSONAL_DATA_SNAPSHOT = {json.dumps(tool_snapshot, ensure_ascii=False)}",
            },
        ]

        for message in history:
            prompt_messages.append({"role": message.role, "content": message.content})

        if not history or history[-1].role != "user" or history[-1].content != user_message:
            prompt_messages.append({"role": "user", "content": user_message})

        payload = {
            "model": self.model,
            "messages": prompt_messages,
            "temperature": 0.2,
            "tools": self.PROPOSAL_TOOLS,
            "tool_choice": "auto",
            "parallel_tool_calls": True,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise AIBackendError("The AI backend timed out") from exc
        except httpx.HTTPError as exc:
            raise AIBackendError(f"The AI backend request failed: {exc}") from exc

        message_payload = self._extract_message(data)
        content = self._extract_content(message_payload)
        tool_plan, tool_error = self._extract_tool_plan(message_payload)
        if tool_plan is not None:
            reply = content.strip() or "I prepared a request for confirmation."
            return AIResponse(reply=reply, tool_plan=tool_plan, proposal_error=tool_error)

        parsed = self._parse_json(content)
        if parsed is None:
            return AIResponse(
                reply=content.strip() or "I could not generate a response.",
                proposal_error=tool_error,
            )

        reply = str(parsed.get("reply") or "").strip() or "I processed your message."
        proposed_action = parsed.get("proposed_action")
        if not isinstance(proposed_action, dict):
            return AIResponse(reply=reply, proposal_error=tool_error)

        action_type = proposed_action.get("action_type")
        if action_type not in self.LEGACY_SUPPORTED_ACTIONS:
            logger.warning("Ignoring unsupported AI action: %s", action_type)
            return AIResponse(reply=reply, proposal_error=f"unsupported_action:{action_type}")
        return AIResponse(reply=reply, proposed_action=proposed_action, proposal_error=tool_error)

    def _extract_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AIBackendError("The AI backend returned no choices")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise AIBackendError("The AI backend returned an invalid message payload")
        return message

    def _extract_content(self, message_payload: dict[str, Any]) -> str:
        content = message_payload.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return "\n".join(parts)
        return ""

    def _extract_tool_plan(self, message_payload: dict[str, Any]) -> tuple[list[dict[str, Any]] | None, str | None]:
        tool_calls = message_payload.get("tool_calls")
        if tool_calls is None:
            return None, None
        if not isinstance(tool_calls, list) or not tool_calls:
            return None, "invalid_tool_calls"

        steps: list[dict[str, Any]] = []
        for raw_call in tool_calls:
            if not isinstance(raw_call, dict):
                return None, "invalid_tool_call_entry"
            if raw_call.get("type") != "function":
                return None, "unsupported_tool_type"
            function_payload = raw_call.get("function")
            if not isinstance(function_payload, dict):
                return None, "invalid_tool_call_payload"
            name = str(function_payload.get("name") or "").strip()
            if name not in self.SUPPORTED_TOOLS:
                logger.warning("Ignoring unsupported AI tool: %s", name)
                return None, f"unsupported_tool:{name}"
            arguments_text = str(function_payload.get("arguments") or "{}").strip()
            try:
                arguments = json.loads(arguments_text)
            except json.JSONDecodeError:
                logger.warning("AI tool call arguments were not valid JSON: %s", arguments_text)
                return None, f"invalid_tool_arguments:{name}"
            if not isinstance(arguments, dict):
                return None, f"invalid_tool_arguments:{name}"
            operation = str(arguments.get("operation") or "").strip()
            if not operation:
                return None, f"missing_operation:{name}"
            step_args = dict(arguments)
            step_args.pop("operation", None)
            steps.append({"tool": name, "operation": operation, "args": step_args})
        return steps, None

    def _parse_json(self, content: str) -> dict[str, Any] | None:
        stripped = content.strip()
        if not stripped:
            return None
        try:
            loaded = json.loads(stripped)
            if isinstance(loaded, dict):
                return loaded
        except json.JSONDecodeError:
            pass

        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            loaded = json.loads(stripped[start : end + 1])
            return loaded if isinstance(loaded, dict) else None
        except json.JSONDecodeError:
            return None
