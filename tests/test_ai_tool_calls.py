from __future__ import annotations

import asyncio

from personal_assistant_bot.ai import OpenAICompatibleAI


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class FakeStreamResponse:
    def __init__(self, lines):
        self._lines = list(lines)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class FakeAsyncClient:
    responses = []
    stream_lines = []
    seen_payloads = []
    seen_stream_payloads = []

    def __init__(self, *, timeout: float):
        self.timeout = timeout

    async def __aenter__(self):
        type(self).seen_payloads = []
        type(self).seen_stream_payloads = []
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url: str, *, json, headers):
        assert url.endswith("/chat/completions")
        if "tools" in json:
            assert json["parallel_tool_calls"] is True
            assert json["tool_choice"] == "auto"
            assert json["tools"]
        else:
            assert json["tool_choice"] == "none"
        assert headers["Authorization"].startswith("Bearer ")
        type(self).seen_payloads.append(json)
        return FakeResponse(type(self).responses.pop(0))

    def stream(self, method: str, url: str, *, json, headers):
        assert method == "POST"
        assert url.endswith("/chat/completions")
        assert json["stream"] is True
        assert headers["Authorization"].startswith("Bearer ")
        type(self).seen_stream_payloads.append(json)
        return FakeStreamResponse(type(self).stream_lines.pop(0))


def test_ai_client_parses_multi_tool_plan(monkeypatch) -> None:
    monkeypatch.setattr("personal_assistant_bot.ai.httpx.AsyncClient", FakeAsyncClient)
    FakeAsyncClient.responses = [
        {
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
    ]

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


def test_ai_client_executes_web_search_then_answers(monkeypatch) -> None:
    monkeypatch.setattr("personal_assistant_bot.ai.httpx.AsyncClient", FakeAsyncClient)

    async def fake_execute_read_only_tool_call(self, tool_call):
        assert tool_call["name"] == "web_search"
        assert tool_call["arguments"] == {
            "operation": "search",
            "query": "latest Portugal inflation",
        }
        return (
            "Search query: latest Portugal inflation\n"
            "Results:\n"
            "1. Portugal inflation slows\n"
            "   URL: https://example.test/news\n"
            "   Snippet: Inflation slowed this month."
        )

    monkeypatch.setattr(
        OpenAICompatibleAI,
        "_execute_read_only_tool_call",
        fake_execute_read_only_tool_call,
    )

    FakeAsyncClient.responses = [
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_web_1",
                                "type": "function",
                                "function": {
                                    "name": "web_search",
                                    "arguments": '{"operation":"search","query":"latest Portugal inflation"}',
                                },
                            }
                        ],
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "message": {
                        "content": "Portugal inflation slowed this month according to recent reporting.",
                    }
                }
            ]
        },
    ]

    client = OpenAICompatibleAI(
        base_url="https://example.test/v1",
        api_key="secret",
        model="gpt-test",
        timeout_seconds=5.0,
    )

    result = asyncio.run(client.respond(user_message="what is the latest Portugal inflation", history=[], tool_snapshot={}))

    assert result.reply == "Portugal inflation slowed this month according to recent reporting."
    assert result.tool_plan is None
    assert len(FakeAsyncClient.seen_payloads) == 2
    second_messages = FakeAsyncClient.seen_payloads[1]["messages"]
    assert "tools" not in FakeAsyncClient.seen_payloads[1]
    assert second_messages[-2]["role"] == "assistant"
    assert second_messages[-2]["tool_calls"][0]["function"]["name"] == "web_search"
    assert second_messages[-1]["role"] == "tool"
    assert "Portugal inflation slows" in second_messages[-1]["content"]


def test_ai_client_falls_back_to_streamed_text_when_non_stream_empty(monkeypatch) -> None:
    monkeypatch.setattr("personal_assistant_bot.ai.httpx.AsyncClient", FakeAsyncClient)
    FakeAsyncClient.responses = [
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": None,
                    }
                }
            ]
        }
    ]
    FakeAsyncClient.stream_lines = [
        [
            'data: {"choices":[{"delta":{"role":"assistant"}}]}',
            'data: {"choices":[{"delta":{"content":"Hello"}}]}',
            'data: {"choices":[{"delta":{"content":" from stream"}}]}',
            "data: [DONE]",
        ]
    ]

    client = OpenAICompatibleAI(
        base_url="https://example.test/v1",
        api_key="secret",
        model="gpt-test",
        timeout_seconds=5.0,
    )

    result = asyncio.run(client.respond(user_message="hi", history=[], tool_snapshot={}))

    assert result.reply == "Hello from stream"
    assert result.tool_plan is None
    assert len(FakeAsyncClient.seen_payloads) == 1
    assert len(FakeAsyncClient.seen_stream_payloads) == 1
    assert FakeAsyncClient.seen_stream_payloads[0]["stream"] is True


def test_ai_client_falls_back_to_streamed_tool_calls_when_non_stream_empty(monkeypatch) -> None:
    monkeypatch.setattr("personal_assistant_bot.ai.httpx.AsyncClient", FakeAsyncClient)
    FakeAsyncClient.responses = [
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": None,
                    }
                }
            ]
        }
    ]
    FakeAsyncClient.stream_lines = [
        [
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"tasks","arguments":"{\\"operation\\":\\"create\\",\\"title\\":\\""}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"Pay rent\\"}"}}]}}]}',
            "data: [DONE]",
        ]
    ]

    client = OpenAICompatibleAI(
        base_url="https://example.test/v1",
        api_key="secret",
        model="gpt-test",
        timeout_seconds=5.0,
    )

    result = asyncio.run(client.respond(user_message="create task", history=[], tool_snapshot={}))

    assert result.reply == "I prepared a request for confirmation."
    assert result.tool_plan == [{"tool": "tasks", "operation": "create", "args": {"title": "Pay rent"}}]
    assert len(FakeAsyncClient.seen_payloads) == 1
    assert len(FakeAsyncClient.seen_stream_payloads) == 1
