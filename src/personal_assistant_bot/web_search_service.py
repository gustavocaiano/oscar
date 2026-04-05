"""Read-only web search helpers backed by a local Playwright browser."""

from __future__ import annotations

import asyncio
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, async_playwright


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


async def search_web(query: str, max_results: int = 5) -> dict[str, Any]:
    """Run a web search and return normalized results."""
    async with asyncio.timeout(20):
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                page = await _new_page(browser)
                await page.goto("https://duckduckgo.com/", wait_until="domcontentloaded", timeout=15000)
                await page.locator("#search_form_input_homepage").fill(query)
                await page.keyboard.press("Enter")
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(1200)

                results = await _extract_results(page=page, max_results=max_results)
                return {
                    "query": query,
                    "results": results,
                    "count": len(results),
                }
            finally:
                await browser.close()


def format_search_results(result: dict[str, Any]) -> str:
    """Convert search results into compact tool output for the model."""
    query = str(result.get("query") or "").strip()
    items = result.get("results") or []
    if not isinstance(items, list) or not items:
        return f"Search query: {query}\nNo results found."

    lines = [f"Search query: {query}", "Results:"]
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "Untitled result").strip()
        url = str(item.get("url") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        lines.append(f"{index}. {title}")
        if url:
            lines.append(f"   URL: {url}")
        if snippet:
            lines.append(f"   Snippet: {snippet}")
    return "\n".join(lines)


async def _new_page(browser: Browser) -> Page:
    context: BrowserContext = await browser.new_context(user_agent=DEFAULT_USER_AGENT)
    page = await context.new_page()
    return page


async def _extract_results(*, page: Page, max_results: int) -> list[dict[str, str]]:
    selectors = [
        "article[data-testid='result']",
        ".result",
    ]
    for selector in selectors:
        locator = page.locator(selector)
        count = await locator.count()
        if count:
            results: list[dict[str, str]] = []
            for index in range(min(count, max_results)):
                item = locator.nth(index)
                link = item.locator("a.result__a, h2 a").first
                if await link.count() == 0:
                    continue
                title = (await link.inner_text()).strip()
                url = (await link.get_attribute("href") or "").strip()
                snippet_locator = item.locator(".result__snippet").first
                snippet = ""
                if await snippet_locator.count() > 0:
                    snippet = (await snippet_locator.inner_text()).strip()
                results.append({"title": title, "url": url, "snippet": snippet})
            if results:
                return results
    return []
