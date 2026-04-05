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
    READ_ONLY_TOOLS = {"web_search"}
    MAX_TOOL_ROUNDS = 3
    SUPPORTED_TOOLS = {"tasks", "shopping", "notes", "reminders", "calendar", "web_search"}

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
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the internet for current information on any topic. This is read-only and runs immediately without confirmation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["search"]},
                        "query": {"type": "string", "description": "The search query to find information on the web"},
                    },
                    "required": ["operation", "query"],
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
                    "The web_search tool is read-only, runs immediately without confirmation, and must use operation='search'. Do not mix web_search with write tools in the same response. After receiving web_search results, answer the user directly. "
                    "When creating reminders or calendar events, every local date/time must use exact format YYYY-MM-DD HH:MM. "
                    "Task ids in the snapshot may be opaque strings from KB+; when renaming or completing tasks, copy the task id exactly as shown. "
                    "If the user asks for current information, news, or facts you don't have, use the web_search tool to find the answer."
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

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                allow_tools = True
                for _ in range(self.MAX_TOOL_ROUNDS):
                    data = await self._request_completion(
                        client=client,
                        messages=prompt_messages,
                        headers=headers,
                        allow_tools=allow_tools,
                    )
                    message_payload = self._extract_message(data)
                    content = self._extract_content(message_payload)
                    tool_calls, tool_error = self._extract_tool_calls(message_payload)
                    if tool_calls is None:
                        return self._build_standard_response(content=content, tool_error=tool_error)

                    if any(not self._is_read_only_tool_call(call) for call in tool_calls):
                        tool_plan, tool_error = self._tool_calls_to_plan(tool_calls)
                        if tool_plan is not None:
                            reply = content.strip() or "I prepared a request for confirmation."
                            return AIResponse(reply=reply, tool_plan=tool_plan, proposal_error=tool_error)
                        return AIResponse(
                            reply=content.strip() or "I could not generate a response.",
                            proposal_error=tool_error,
                        )

                    prompt_messages.extend(
                        await self._build_read_only_followup_messages(
                            message_payload=message_payload,
                            tool_calls=tool_calls,
                        )
                    )
                    allow_tools = False
                return AIResponse(
                    reply="I could not complete the web search flow.",
                    proposal_error="tool_round_limit",
                )
        except httpx.TimeoutException as exc:
            raise AIBackendError("The AI backend timed out") from exc
        except httpx.HTTPError as exc:
            raise AIBackendError(f"The AI backend request failed: {exc}") from exc

    async def _request_completion(
        self,
        *,
        client: httpx.AsyncClient,
        messages: list[dict[str, Any]],
        headers: dict[str, str],
        allow_tools: bool,
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
        }
        if allow_tools:
            payload["tools"] = self.PROPOSAL_TOOLS
            payload["tool_choice"] = "auto"
            payload["parallel_tool_calls"] = True
        else:
            payload["tool_choice"] = "none"
        response = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
        response.raise_for_status()
        return response.json()

    def _build_standard_response(self, *, content: str, tool_error: str | None) -> AIResponse:
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

    def _extract_tool_calls(self, message_payload: dict[str, Any]) -> tuple[list[dict[str, Any]] | None, str | None]:
        tool_calls = message_payload.get("tool_calls")
        if tool_calls is None:
            return None, None
        if not isinstance(tool_calls, list) or not tool_calls:
            return None, "invalid_tool_calls"

        normalized_calls: list[dict[str, Any]] = []
        for index, raw_call in enumerate(tool_calls, start=1):
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
            normalized_calls.append(
                {
                    "id": str(raw_call.get("id") or f"call_{index}"),
                    "name": name,
                    "arguments": arguments,
                }
            )
        return normalized_calls, None

    def _tool_calls_to_plan(self, tool_calls: list[dict[str, Any]]) -> tuple[list[dict[str, Any]] | None, str | None]:
        if any(self._is_read_only_tool_call(call) for call in tool_calls):
            return None, "mixed_read_write_tools"

        steps: list[dict[str, Any]] = []
        for call in tool_calls:
            name = str(call.get("name") or "").strip()
            arguments = dict(call.get("arguments") or {})
            operation = str(arguments.get("operation") or "").strip()
            if not operation:
                return None, f"missing_operation:{name}"
            step_args = dict(arguments)
            step_args.pop("operation", None)
            steps.append({"tool": name, "operation": operation, "args": step_args})
        return steps, None

    def _is_read_only_tool_call(self, tool_call: dict[str, Any]) -> bool:
        return str(tool_call.get("name") or "").strip() in self.READ_ONLY_TOOLS

    async def _build_read_only_followup_messages(
        self,
        *,
        message_payload: dict[str, Any],
        tool_calls: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        assistant_message = {
            "role": "assistant",
            "content": self._extract_content(message_payload),
            "tool_calls": [
                {
                    "id": str(call["id"]),
                    "type": "function",
                    "function": {
                        "name": str(call["name"]),
                        "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                    },
                }
                for call in tool_calls
            ],
        }
        messages: list[dict[str, Any]] = [assistant_message]
        for call in tool_calls:
            tool_output = await self._execute_read_only_tool_call(call)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(call["id"]),
                    "content": tool_output,
                }
            )
        return messages

    async def _execute_read_only_tool_call(self, tool_call: dict[str, Any]) -> str:
        name = str(tool_call.get("name") or "").strip()
        arguments = dict(tool_call.get("arguments") or {})
        if name == "web_search":
            from personal_assistant_bot.web_search_service import format_search_results, search_web

            operation = str(arguments.get("operation") or "").strip()
            query = str(arguments.get("query") or "").strip()
            if operation != "search":
                return f"Web search failed: unsupported operation '{operation}'."
            if not query:
                return "Web search failed: missing query."
            try:
                result = await search_web(query)
            except Exception as exc:
                logger.warning("Web search failed for %r: %s", query, exc)
                return f"Web search failed: {exc}"
            return format_search_results(result)
        return f"Unsupported read-only tool: {name}"

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
