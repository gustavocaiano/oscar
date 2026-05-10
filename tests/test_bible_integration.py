from __future__ import annotations

import asyncio

import httpx
import pytest

from personal_assistant_bot.bible_integration import ABibliaDigitalClient, BibleIntegrationError, next_bible_position


def _chapter_payload() -> dict:
    return {
        "book": {"name": "Gênesis", "abbrev": {"pt": "gn"}},
        "chapter": {"number": 1, "verses": 2},
        "verses": [
            {"number": 1, "text": "No princípio Deus criou os céus e a terra."},
            {"number": 2, "text": "Era a terra sem forma e vazia."},
        ],
    }


def test_abiblia_digital_client_fetches_chapter_with_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://example.test/api/verses/nvi/gn/1"
        assert request.headers["Authorization"] == "Bearer secret"
        return httpx.Response(200, json=_chapter_payload(), request=request)

    client = ABibliaDigitalClient(
        base_url="https://example.test/api/",
        api_token="secret",
        transport=httpx.MockTransport(handler),
    )

    chapter = asyncio.run(client.fetch_chapter(translation="nvi", book_abbrev="gn", chapter=1))

    assert chapter.book_name == "Gênesis"
    assert chapter.translation == "nvi"
    assert [verse.number for verse in chapter.verses] == [1, 2]
    assert "No princípio" in chapter.verses[0].text


def test_abiblia_digital_client_allows_missing_token_for_limited_mode() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "Authorization" not in request.headers
        return httpx.Response(200, json=_chapter_payload(), request=request)

    client = ABibliaDigitalClient(base_url="https://example.test/api", transport=httpx.MockTransport(handler))

    chapter = asyncio.run(client.fetch_chapter(translation="nvi", book_abbrev="gn", chapter=1))

    assert chapter.verses[1].text == "Era a terra sem forma e vazia."


def test_abiblia_digital_client_raises_on_http_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "down"}, request=request)

    client = ABibliaDigitalClient(base_url="https://example.test/api", transport=httpx.MockTransport(handler))

    with pytest.raises(BibleIntegrationError):
        asyncio.run(client.fetch_chapter(translation="nvi", book_abbrev="gn", chapter=1))


def test_abiblia_digital_client_raises_on_invalid_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"book": {}, "chapter": {"number": 1}, "verses": []}, request=request)

    client = ABibliaDigitalClient(base_url="https://example.test/api", transport=httpx.MockTransport(handler))

    with pytest.raises(BibleIntegrationError):
        asyncio.run(client.fetch_chapter(translation="nvi", book_abbrev="gn", chapter=1))


def test_next_bible_position_handles_book_boundaries_and_completion() -> None:
    assert next_bible_position("gn", 1) == ("gn", 2)
    assert next_bible_position("gn", 50) == ("ex", 1)
    assert next_bible_position("ob", 1) == ("jn", 1)
    assert next_bible_position("ap", 22) is None
