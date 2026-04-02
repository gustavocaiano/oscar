from __future__ import annotations

import asyncio

from personal_assistant_bot.ai import OpenAICompatibleAI


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {
            "choices": [
                {
                    "message": {
                        "content": "I'll prepare that for confirmation.",
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "tasks",
                                    "arguments": '{"operation":"create_many","titles":["Pay rent","Send invoice"]}',
                                },
                            },
                            {
                                "type": "function",
                                "function": {
                                    "name": "reminders",
                                    "arguments": '{"operation":"create","when_local":"2026-04-02 09:00","message":"Call Alice"}',
                                },
                            },
                        ],
                    }
                }
            ]
        }


class FakeAsyncClient:
    def __init__(self, *, timeout: float):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url: str, *, json, headers):
        assert url.endswith("/chat/completions")
        assert json["parallel_tool_calls"] is True
        assert json["tool_choice"] == "auto"
        assert json["tools"]
        assert headers["Authorization"].startswith("Bearer ")
        return FakeResponse()


def test_ai_client_parses_multi_tool_plan(monkeypatch) -> None:
    monkeypatch.setattr("personal_assistant_bot.ai.httpx.AsyncClient", FakeAsyncClient)

    client = OpenAICompatibleAI(
        base_url="https://example.test/v1",
        api_key="secret",
        model="gpt-test",
        timeout_seconds=5.0,
    )

    result = asyncio.run(client.respond(user_message="add tasks and a reminder", history=[], tool_snapshot={}))

    assert result.tool_plan == [
        {"tool": "tasks", "operation": "create_many", "args": {"titles": ["Pay rent", "Send invoice"]}},
        {
            "tool": "reminders",
            "operation": "create",
            "args": {"when_local": "2026-04-02 09:00", "message": "Call Alice"},
        },
    ]
    assert result.reply == "I'll prepare that for confirmation."
