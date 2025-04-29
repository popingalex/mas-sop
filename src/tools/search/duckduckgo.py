from duckduckgo_search import DDGS, AsyncDDGS
from typing import List, Dict, Any, Optional, Annotated
from loguru import logger
import asyncio

# 注意：这里不直接使用旧的 ResponseType，因为 Agent 调用工具时期望直接返回结果或抛出异常
# 返回值直接为搜索结果列表或包含错误信息的字典

async def duckduckgo_search(
    query: Annotated[str, "The search query string."],
    max_results: Annotated[int, "The maximum number of results to return."] = 3
) -> List[Dict[str, str]]:
    """Performs a web search using DuckDuckGo and returns the results.

    Args:
        query: The search query.
        max_results: The maximum number of results desired.

    Returns:
        A list of dictionaries, where each dictionary contains 'title', 'link', and 'snippet' of a search result.
        Returns an empty list if the search fails.
    """
    logger.info(f"Performing DuckDuckGo web search for: '{query}' (max_results={max_results})")
    try:
        # Use AsyncDDGS for non-blocking search
        async with AsyncDDGS() as ddgs:
            results_gen = ddgs.text(query, max_results=max_results)
            results = [r async for r in results_gen]

        # Format results consistently
        formatted_results = []
        if results:
            for r in results:
                if isinstance(r, dict):
                    formatted_results.append({
                        "title": r.get('title', ''),
                        "link": r.get('href', ''), # 'href' is the standard key
                        "snippet": r.get('body', '') # 'body' is the standard key
                    })
                else:
                    logger.warning(f"Skipping unexpected result format: {type(r)}")
        logger.info(f"Found {len(formatted_results)} results for query: '{query}'")
        return formatted_results
    except Exception as e:
        logger.error(f"DuckDuckGo web search failed for query '{query}': {e}")
        # Return empty list on failure, Agent can decide how to handle
        return []

async def duckduckgo_news(
    query: Annotated[str, "The search query string for news."],
    max_results: Annotated[int, "The maximum number of news results to return."] = 5
) -> List[Dict[str, str]]:
    """Searches for news articles using DuckDuckGo.

    Args:
        query: The news search query.
        max_results: The maximum number of news articles.

    Returns:
        A list of dictionaries, each containing 'title', 'link', 'snippet', and optionally 'date'.
        Returns an empty list if the search fails.
    """
    logger.info(f"Performing DuckDuckGo news search for: '{query}' (max_results={max_results})")
    try:
        async with AsyncDDGS() as ddgs:
            results_gen = ddgs.news(query, max_results=max_results)
            results = [r async for r in results_gen]

        formatted_results = []
        if results:
            for r in results:
                 if isinstance(r, dict):
                     # Extract date safely
                     date_str = r.get('date')
                     formatted_results.append({
                         "title": r.get('title', ''),
                         "link": r.get('url', ''), # News uses 'url'
                         "snippet": r.get('body', ''),
                         "date": date_str # Keep date as string
                     })
                 else:
                     logger.warning(f"Skipping unexpected news result format: {type(r)}")
        logger.info(f"Found {len(formatted_results)} news results for query: '{query}'")
        return formatted_results
    except Exception as e:
        logger.error(f"DuckDuckGo news search failed for query '{query}': {e}")
        return []

# Example Usage (for testing)
async def main():
    print("--- Web Search ---")
    web_results = await duckduckgo_search(query="AutoGen framework", max_results=2)
    print(json.dumps(web_results, indent=2, ensure_ascii=False))

    print("\n--- News Search ---")
    news_results = await duckduckgo_news(query="AI safety", max_results=2)
    print(json.dumps(news_results, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    # Need to install nest_asyncio if running in a Jupyter env or similar
    # import nest_asyncio
    # nest_asyncio.apply()
    asyncio.run(main())
