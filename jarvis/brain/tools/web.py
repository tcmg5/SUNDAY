"""Web search and page reading.

DuckDuckGo's HTML endpoint is the default because it needs no key and no
account. If you have a Brave or Tavily key in the environment, set
web.engine accordingly and you'll get cleaner results.
"""
from __future__ import annotations

import html
import logging
import re
import urllib.parse

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def web_search(cfg: dict, **kwargs) -> str:
    query = kwargs.get("query", "").strip()
    if not query:
        return "I need something to search for."
    max_results = int(kwargs.get("max_results", cfg["web"]["max_results"]))
    engine = cfg["web"]["engine"]

    try:
        if engine == "brave" and cfg["secrets"]["brave_api_key"]:
            results = _search_brave(cfg, query, max_results)
        elif engine == "tavily" and cfg["secrets"]["tavily_api_key"]:
            results = _search_tavily(cfg, query, max_results)
        else:
            results = _search_duckduckgo(cfg, query, max_results)
    except Exception as exc:
        log.error("search failed: %s", exc)
        return f"The search failed: {exc}"

    if not results:
        return f"No results for '{query}'."
    lines = [f"Results for '{query}':"]
    for i, r in enumerate(results, 1):
        lines.append(f"\n{i}. {r['title']}\n   {r['url']}\n   {r['snippet']}")
    return "\n".join(lines)


def _search_duckduckgo(cfg: dict, query: str, max_results: int) -> list[dict]:
    import httpx

    resp = httpx.post(
        "https://html.duckduckgo.com/html/",
        data={"q": query},
        headers={"User-Agent": USER_AGENT},
        timeout=cfg["web"]["fetch_timeout_sec"],
        follow_redirects=True,
    )
    resp.raise_for_status()
    return _parse_ddg(resp.text, max_results)


def _parse_ddg(page: str, max_results: int) -> list[dict]:
    results: list[dict] = []
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(page, "html.parser")
        for block in soup.select(".result")[: max_results * 2]:
            link = block.select_one(".result__a")
            snippet = block.select_one(".result__snippet")
            if not link:
                continue
            results.append({
                "title": link.get_text(strip=True),
                "url": _clean_ddg_url(link.get("href", "")),
                "snippet": snippet.get_text(" ", strip=True) if snippet else "",
            })
            if len(results) >= max_results:
                break
        return results
    except ImportError:
        pass

    # Regex fallback so search still works without beautifulsoup4 installed.
    pattern = re.compile(
        r'result__a"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
        r'result__snippet"[^>]*>(?P<snippet>.*?)</a>',
        re.S,
    )
    for match in pattern.finditer(page):
        results.append({
            "title": _strip_tags(match.group("title")),
            "url": _clean_ddg_url(match.group("url")),
            "snippet": _strip_tags(match.group("snippet")),
        })
        if len(results) >= max_results:
            break
    return results


def _clean_ddg_url(href: str) -> str:
    """DDG wraps results in a redirect; pull the real URL back out."""
    if "duckduckgo.com/l/" in href or href.startswith("//duckduckgo.com/l/"):
        parsed = urllib.parse.urlparse(href if href.startswith("http") else "https:" + href)
        target = urllib.parse.parse_qs(parsed.query).get("uddg")
        if target:
            return urllib.parse.unquote(target[0])
    return href


def _search_brave(cfg: dict, query: str, max_results: int) -> list[dict]:
    import httpx

    resp = httpx.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": max_results},
        headers={
            "X-Subscription-Token": cfg["secrets"]["brave_api_key"],
            "Accept": "application/json",
        },
        timeout=cfg["web"]["fetch_timeout_sec"],
    )
    resp.raise_for_status()
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""),
         "snippet": _strip_tags(r.get("description", ""))}
        for r in resp.json().get("web", {}).get("results", [])[:max_results]
    ]


def _search_tavily(cfg: dict, query: str, max_results: int) -> list[dict]:
    import httpx

    resp = httpx.post(
        "https://api.tavily.com/search",
        json={
            "api_key": cfg["secrets"]["tavily_api_key"],
            "query": query,
            "max_results": max_results,
        },
        timeout=cfg["web"]["fetch_timeout_sec"],
    )
    resp.raise_for_status()
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
        for r in resp.json().get("results", [])[:max_results]
    ]


def fetch_page(cfg: dict, **kwargs) -> str:
    """Fetch a URL and return readable text with the chrome stripped out."""
    import httpx

    url = kwargs.get("url", "").strip()
    if not url:
        return "I need a URL to fetch."
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    max_chars = int(kwargs.get("max_chars", cfg["web"]["max_page_chars"]))
    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=cfg["web"]["fetch_timeout_sec"],
            follow_redirects=True,
        )
        resp.raise_for_status()
    except Exception as exc:
        return f"Couldn't fetch {url}: {exc}"

    text = _extract_readable(resp.text)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[truncated]"
    return f"Content of {url}:\n\n{text}"


def _extract_readable(page: str) -> str:
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(page, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "noscript"]):
            tag.decompose()
        main = soup.find("article") or soup.find("main") or soup.body or soup
        text = main.get_text("\n", strip=True)
    except ImportError:
        text = _strip_tags(re.sub(r"(?is)<(script|style).*?</\1>", " ", page))
    # Collapse the blank-line soup that stripping tags leaves behind.
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _strip_tags(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()
