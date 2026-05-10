from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class BibleIntegrationError(RuntimeError):
    """Raised when the Bible provider is unavailable or returns invalid data."""


@dataclass(frozen=True)
class BibleBook:
    abbrev: str
    name: str
    chapters: int


@dataclass(frozen=True)
class BibleVerse:
    number: int
    text: str


@dataclass(frozen=True)
class BibleChapter:
    book_abbrev: str
    book_name: str
    chapter: int
    translation: str
    verses: list[BibleVerse]


BIBLE_BOOKS: tuple[BibleBook, ...] = (
    BibleBook("gn", "Gênesis", 50),
    BibleBook("ex", "Êxodo", 40),
    BibleBook("lv", "Levítico", 27),
    BibleBook("nm", "Números", 36),
    BibleBook("dt", "Deuteronômio", 34),
    BibleBook("js", "Josué", 24),
    BibleBook("jz", "Juízes", 21),
    BibleBook("rt", "Rute", 4),
    BibleBook("1sm", "1 Samuel", 31),
    BibleBook("2sm", "2 Samuel", 24),
    BibleBook("1rs", "1 Reis", 22),
    BibleBook("2rs", "2 Reis", 25),
    BibleBook("1cr", "1 Crônicas", 29),
    BibleBook("2cr", "2 Crônicas", 36),
    BibleBook("ed", "Esdras", 10),
    BibleBook("ne", "Neemias", 13),
    BibleBook("et", "Ester", 10),
    BibleBook("jó", "Jó", 42),
    BibleBook("sl", "Salmos", 150),
    BibleBook("pv", "Provérbios", 31),
    BibleBook("ec", "Eclesiastes", 12),
    BibleBook("ct", "Cânticos", 8),
    BibleBook("is", "Isaías", 66),
    BibleBook("jr", "Jeremias", 52),
    BibleBook("lm", "Lamentações", 5),
    BibleBook("ez", "Ezequiel", 48),
    BibleBook("dn", "Daniel", 12),
    BibleBook("os", "Oseias", 14),
    BibleBook("jl", "Joel", 3),
    BibleBook("am", "Amós", 9),
    BibleBook("ob", "Obadias", 1),
    BibleBook("jn", "Jonas", 4),
    BibleBook("mq", "Miqueias", 7),
    BibleBook("na", "Naum", 3),
    BibleBook("hc", "Habacuque", 3),
    BibleBook("sf", "Sofonias", 3),
    BibleBook("ag", "Ageu", 2),
    BibleBook("zc", "Zacarias", 14),
    BibleBook("ml", "Malaquias", 4),
    BibleBook("mt", "Mateus", 28),
    BibleBook("mc", "Marcos", 16),
    BibleBook("lc", "Lucas", 24),
    BibleBook("jo", "João", 21),
    BibleBook("atos", "Atos", 28),
    BibleBook("rm", "Romanos", 16),
    BibleBook("1co", "1 Coríntios", 16),
    BibleBook("2co", "2 Coríntios", 13),
    BibleBook("gl", "Gálatas", 6),
    BibleBook("ef", "Efésios", 6),
    BibleBook("fp", "Filipenses", 4),
    BibleBook("cl", "Colossenses", 4),
    BibleBook("1ts", "1 Tessalonicenses", 5),
    BibleBook("2ts", "2 Tessalonicenses", 3),
    BibleBook("1tm", "1 Timóteo", 6),
    BibleBook("2tm", "2 Timóteo", 4),
    BibleBook("tt", "Tito", 3),
    BibleBook("fm", "Filemom", 1),
    BibleBook("hb", "Hebreus", 13),
    BibleBook("tg", "Tiago", 5),
    BibleBook("1pe", "1 Pedro", 5),
    BibleBook("2pe", "2 Pedro", 3),
    BibleBook("1jo", "1 João", 5),
    BibleBook("2jo", "2 João", 1),
    BibleBook("3jo", "3 João", 1),
    BibleBook("jd", "Judas", 1),
    BibleBook("ap", "Apocalipse", 22),
)

BIBLE_BOOK_BY_ABBREV = {book.abbrev: book for book in BIBLE_BOOKS}
FIRST_BIBLE_BOOK = BIBLE_BOOKS[0]


def get_bible_book(abbrev: str) -> BibleBook:
    book = BIBLE_BOOK_BY_ABBREV.get(abbrev)
    if book is None:
        raise BibleIntegrationError(f"Livro bíblico desconhecido: {abbrev}")
    return book


def next_bible_position(book_abbrev: str, chapter: int) -> tuple[str, int] | None:
    for index, book in enumerate(BIBLE_BOOKS):
        if book.abbrev != book_abbrev:
            continue
        if chapter < book.chapters:
            return book.abbrev, chapter + 1
        if index + 1 < len(BIBLE_BOOKS):
            return BIBLE_BOOKS[index + 1].abbrev, 1
        return None
    raise BibleIntegrationError(f"Livro bíblico desconhecido: {book_abbrev}")


class ABibliaDigitalClient:
    def __init__(
        self,
        *,
        base_url: str | None,
        api_token: str | None = None,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/") if base_url else None
        self.api_token = api_token
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    async def fetch_chapter(self, *, translation: str, book_abbrev: str, chapter: int) -> BibleChapter:
        if not self.configured:
            raise BibleIntegrationError("Leitura bíblica não configurada")
        if chapter <= 0:
            raise BibleIntegrationError("Capítulo bíblico inválido")

        book = get_bible_book(book_abbrev)
        if chapter > book.chapters:
            raise BibleIntegrationError("Capítulo bíblico fora do intervalo do livro")

        assert self.base_url is not None
        headers = {"Authorization": f"Bearer {self.api_token}"} if self.api_token else None
        url = f"{self.base_url}/verses/{translation}/{book.abbrev}/{chapter}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, transport=self.transport) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise BibleIntegrationError("Não consegui consultar a Bíblia agora") from exc
        except ValueError as exc:
            raise BibleIntegrationError("A resposta da Bíblia não está em JSON válido") from exc

        return self._parse_chapter_payload(payload, fallback_book=book, translation=translation, chapter=chapter)

    def _parse_chapter_payload(
        self,
        payload: Any,
        *,
        fallback_book: BibleBook,
        translation: str,
        chapter: int,
    ) -> BibleChapter:
        if not isinstance(payload, dict):
            raise BibleIntegrationError("Resposta inválida da Bíblia")

        book_payload = payload.get("book")
        chapter_payload = payload.get("chapter")
        verses_payload = payload.get("verses")
        if (
            not isinstance(book_payload, dict)
            or not isinstance(chapter_payload, dict)
            or not isinstance(verses_payload, list)
        ):
            raise BibleIntegrationError("Resposta incompleta da Bíblia")

        try:
            payload_chapter = int(chapter_payload.get("number") or 0)
        except (TypeError, ValueError) as exc:
            raise BibleIntegrationError("Número de capítulo inválido na resposta da Bíblia") from exc
        if payload_chapter != chapter:
            raise BibleIntegrationError("A Bíblia retornou um capítulo diferente do solicitado")

        verses: list[BibleVerse] = []
        for raw_verse in verses_payload:
            if not isinstance(raw_verse, dict):
                continue
            try:
                number = int(raw_verse.get("number") or 0)
            except (TypeError, ValueError):
                continue
            text = str(raw_verse.get("text") or "").strip()
            if number > 0 and text:
                verses.append(BibleVerse(number=number, text=text))

        if not verses:
            raise BibleIntegrationError("A Bíblia não retornou versículos utilizáveis")

        book_name = str(book_payload.get("name") or fallback_book.name).strip() or fallback_book.name
        return BibleChapter(
            book_abbrev=fallback_book.abbrev,
            book_name=book_name,
            chapter=chapter,
            translation=translation,
            verses=verses,
        )
