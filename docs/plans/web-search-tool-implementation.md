# Plan: Web Search Tool para Assistente IA

## Objetivo
Adicionar capacidade de pesquisa web ao asistente IA do Telegram, usando solução 100% local (sem dependência de APIs externas third-party).

## Abordagem Escolhida: Playwright Local

**Justificação:**
- 100% local - nenhum dado sai da máquina
- Suporta qualquer página (incluindo JavaScript renderizado)
- Integrado no ecossistema Python existente
- Alternativa mais prática vs SearXNG (que requer servidor separado)

---

## Arquitetura Atual

```
src/personal_assistant_bot/
├── ai.py                    # Define tools (PROPOSAL_TOOLS, SUPPORTED_TOOLS)
└── services.py             # Executa tool_plans (_execute_tool_plan)
```

**Fluxo atual:**
1. Modelo retorna chamada de função (tool_call)
2. `ai.py:_extract_tool_plan()` valida e extrai parâmetros
3. `service.py:_execute_tool_plan()` executa a ação
4. Retorna resultado para o utilizador

---

## Alterações Necessárias

### Fase 1: Adicionar Dependência

**Ficheiro:** `pyproject.toml` (ou `requirements.txt`)

```toml
[dependencies]
playwright = "^1.40.0"
```

**Instalação:**
```bash
pip install playwright
playwright install chromium
```

---

### Fase 2: Definir Nova Tool

**Ficheiro:** `src/personal_assistant_bot/ai.py`

**Alterações:**
1. Adicionar `"web_search"` a `SUPPORTED_TOOLS` (linha ~36)
2. Adicionar definição da tool a `PROPOSAL_TOOLS` (depois da linha ~145):

```python
{
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the internet for current information on any topic. Use this when you need factual information, news, or up-to-date data that the user is asking about.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query to find information on the web"},
            },
            "required": ["query"],
        },
    },
}
```

---

### Fase 3: Criar Serviço de Pesquisa Web

**Novo ficheiro:** `src/personal_assistant_bot/web_search_service.py`

```python
"""Web search service using Playwright for local browser automation."""

import asyncio
from typing import Any

from playwright.async_api import async_playwright


async def search_web(query: str, max_results: int = 5) -> dict[str, Any]:
    """
    Perform a web search using a local browser.
    
    Args:
        query: The search query
        max_results: Maximum number of results to return
    
    Returns:
        Dictionary with results and metadata
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Navigate to DuckDuckGo (no tracking, no login needed)
        await page.goto("https://duckduckgo.com/")
        await page.fill("#search_form_input_homepage", query)
        await page.click("#search_button_homepage")
        
        # Wait for results
        await page.wait_for_selector(".result__snippet")
        
        # Extract results
        results = await page.evaluate("""() => {
            const elements = document.querySelectorAll('.result__a');
            return Array.from(elements).slice(0, 5).map(el => ({
                title: el.textContent,
                url: el.href
            }));
        }""")
        
        await browser.close()
        
        return {
            "query": query,
            "results": results,
            "count": len(results)
        }


async def extract_page_content(url: str) -> str:
    """
    Extract the main content from a specific URL.
    
    Useful for getting more details from a search result.
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        
        try:
            await page.goto(url, timeout=10000)
            await page.wait_for_load_state("domcontentloaded")
            
            # Extract readable text
            content = await page.evaluate("""() => {
                // Remove scripts, styles, navigation
                const toRemove = document.querySelectorAll('script, style, nav, footer, header');
                toRemove.forEach(el => el.remove());
                
                // Get main content
                const article = document.querySelector('article') || 
                               document.querySelector('main') ||
                               document.body;
                return article?.innerText || '';
            }""")
        except Exception as e:
            content = f"Erro ao extraer: {str(e)}"
        
        await browser.close()
        return content[:5000]  # Limit to 5000 chars
```

---

### Fase 4: Integrar no Execution Flow

**Ficheiro:** `src/personal_assistant_bot/service.py`

No método `_execute_tool_plan()`, adicionar handler para `"web_search"`:

```python
if tool_name == "web_search":
    from personal_assistant_bot.web_search_service import search_web, extract_page_content
    
    operation = step.get("operation") or "search"
    args = step.get("args", {})
    
    if operation == "search":
        query = args.get("query", "")
        result = await search_web(query)
        return f"Pesquisa: {result['query']}\n\n" + "\n".join(
            f"- {r['title']}: {r['url']}" for r in result.get("results", [])
        )
    elif operation == "fetch":
        url = args.get("url", "")
        content = await extract_page_content(url)
        return f"Contenido de {url}:\n\n{content[:1000]}..."
    
    return f"Operação desconhecida: {operation}"
```

---

### Fase 5: Atualizar System Prompt

**Ficheiro:** `src/personal_assistant_bot/ai.py` (linhas ~170-178)

Adicionar guideline ao system prompt:

```
"If the user asks for current information, news, or facts you don't have, use the web_search tool to find the answer."
```

---

## Testes

**Ficheiros a criar/alterar:**
- `tests/test_web_search_service.py` - Unit tests para o serviço
- `tests/test_ai_web_search_tool.py` - Integration test com o AI

---

## Riscos e Mitigações

| Risco | Mitigação |
|-------|-----------|
| Tempo de resposta lento | Cache resultados recentes |
| Páginas bloqueiam bots | Usar user-agent realista |
| Erros de rede | Timeout configurável, retry logic |
| Conteúdo JS complexo | Playwright lida automaticamente |

---

## alternatives Consideradas

1. **httpx + BeautifulSoup** - Mais leve, mas não lida com JS
2. **SearXNG** - Requer servidor separado para hospedar
3. **Tavily API** - API externa (viola requisito de local)

A escolha de Playwright justifica-se por ser 100% local e suprtar todo tipo de conteúdo.

---

## Estimativa de Esforço

- Fase 1-2: ~30 min (dependências + configuração tool)
- Fase 3: ~1 hora (serviço + lógica extração)
- Fase 4: ~30 min (integração no fluxo existente)
- Fase 5: ~15 min (prompt)
-Testes: ~1 hora

**Total estimado:** ~3-4 horas

---

## Próximos Passos

1. Confirmação deste plano
2. Iniciar implementação pela Fase 1