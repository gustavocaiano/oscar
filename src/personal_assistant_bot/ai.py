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


class OpenAICompatibleAI:
    SUPPORTED_ACTIONS = {"create_task", "add_shopping_items", "create_note", "create_reminder"}

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
                    "You are a Telegram personal assistant. You may read the provided personal data snapshot to help the user. "
                    "If the user is asking to create or change structured assistant data, you may propose one supported action but you must not assume it has already happened. "
                    "Supported actions: create_task, add_shopping_items, create_note, create_reminder. "
                    "When proposing create_reminder, payload.when_local must use exact format YYYY-MM-DD HH:MM. "
                    "Return strict JSON only with this shape: {\"reply\": string, \"proposed_action\": null|object}."
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

        content = self._extract_content(data)
        parsed = self._parse_json(content)
        if parsed is None:
            return AIResponse(reply=content.strip() or "I could not generate a response.")

        reply = str(parsed.get("reply") or "").strip() or "I processed your message."
        proposed_action = parsed.get("proposed_action")
        if not isinstance(proposed_action, dict):
            return AIResponse(reply=reply)

        action_type = proposed_action.get("action_type")
        if action_type not in self.SUPPORTED_ACTIONS:
            logger.warning("Ignoring unsupported AI action: %s", action_type)
            return AIResponse(reply=reply)
        return AIResponse(reply=reply, proposed_action=proposed_action)

    def _extract_content(self, payload: dict[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AIBackendError("The AI backend returned no choices")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise AIBackendError("The AI backend returned an invalid message payload")
        content = message.get("content")
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
        raise AIBackendError("The AI backend returned unsupported content")

    def _parse_json(self, content: str) -> dict[str, Any] | None:
        stripped = content.strip()
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
