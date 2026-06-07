from __future__ import annotations

from html.parser import HTMLParser
from xml.etree import ElementTree
from urllib.parse import parse_qs, unquote, urlparse

import requests

from config import settings


FREE_SEARCH_TIMEOUT_SECONDS = 6
DUCKDUCKGO_ENDPOINTS = [
    "https://html.duckduckgo.com/html/",
    "https://duckduckgo.com/html/",
    "https://lite.duckduckgo.com/lite/",
]


def search_web(query: str, max_results: int = 5, freshness: str | None = None, summary: bool | None = None) -> dict:
    provider = settings.search_provider
    if provider == "auto":
        return _search_auto(query, max_results, freshness=freshness, summary=summary)
    if provider in {"duckduckgo", "ddg"}:
        try:
            return _search_duckduckgo(query, max_results)
        except requests.RequestException as exc:
            return _search_error("duckduckgo", query, exc)
    if provider in {"bing", "bing_rss"}:
        try:
            return _search_bing_rss(query, max_results)
        except (RuntimeError, requests.RequestException) as exc:
            return _search_error("bing", query, exc)
    if provider == "searchfree":
        try:
            return _search_searchfree(query, max_results)
        except requests.RequestException as exc:
            return _search_error("searchfree", query, exc)
    if provider in {"wikimedia", "wikipedia"}:
        try:
            return _search_wikimedia(query, max_results)
        except requests.RequestException as exc:
            return _search_error("wikimedia", query, exc)
    if provider == "bocha":
        try:
            return _search_bocha(query, max_results, freshness=freshness, summary=summary)
        except (RuntimeError, requests.RequestException) as exc:
            return _search_error("bocha", query, exc)
    return {
        "provider": "mock",
        "query": query,
        "results": [],
        "note": "SEARCH_PROVIDER=mock，未执行真实网页搜索",
    }


def _search_auto(query: str, max_results: int, freshness: str | None = None, summary: bool | None = None) -> dict:
    attempts = []
    try:
        result = _search_searchfree(query, max_results)
        if result.get("results"):
            result["attempts"] = attempts + [{"provider": "searchfree", "status": "success"}]
            return result
        attempts.append({"provider": "searchfree", "status": "empty"})
    except requests.RequestException as exc:
        attempts.append(_attempt_error("searchfree", exc))
    try:
        result = _search_bing_rss(query, max_results)
        if result.get("results"):
            result["attempts"] = attempts + [{"provider": "bing", "status": "success"}]
            return result
        attempts.append({"provider": "bing", "status": "empty"})
    except (RuntimeError, requests.RequestException) as exc:
        attempts.append(_attempt_error("bing", exc))
    try:
        result = _search_wikimedia(query, max_results)
        if result.get("results"):
            result["attempts"] = attempts + [{"provider": "wikimedia", "status": "success"}]
            return result
        attempts.append({"provider": "wikimedia", "status": "empty"})
    except requests.RequestException as exc:
        attempts.append(_attempt_error("wikimedia", exc))
    try:
        result = _search_duckduckgo(query, max_results)
        if result.get("results"):
            result["attempts"] = attempts + [{"provider": "duckduckgo", "status": "success"}]
            return result
        attempts.append({"provider": "duckduckgo", "status": "empty"})
    except requests.RequestException as exc:
        attempts.append(_attempt_error("duckduckgo", exc))
    return {
        "provider": "auto",
        "query": query,
        "results": [],
        "attempts": attempts,
        "note": "所有免费搜索后端均不可用或无结果",
    }


def _search_bocha(query: str, max_results: int, freshness: str | None = None, summary: bool | None = None) -> dict:
    if not settings.bocha_api_key:
        raise RuntimeError("BOCHA_API_KEY is required when SEARCH_PROVIDER=bocha")
    payload = {
        "query": query,
        "freshness": freshness or settings.search_freshness,
        "summary": settings.search_summary if summary is None else summary,
        "count": max_results or settings.search_count,
    }
    if settings.search_include:
        payload["include"] = settings.search_include
    if settings.search_exclude:
        payload["exclude"] = settings.search_exclude
    response = requests.post(
        "https://api.bochaai.com/v1/web-search",
        headers={
            "Authorization": f"Bearer {settings.bocha_api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=FREE_SEARCH_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    results = _normalize_results(data)
    return {
        "provider": "bocha",
        "query": query,
        "answer": _extract_answer(data),
        "results": results,
        "raw": data,
    }


def _search_searchfree(query: str, max_results: int) -> dict:
    response = requests.post(
        "https://searchfree.site/api/search",
        json={
            "query": query,
            "search_depth": "basic",
            "topic": "general",
            "max_results": max_results or settings.search_count,
            "include_answer": True,
            "include_raw_content": False,
            "country": "cn",
        },
        headers={"Content-Type": "application/json", "User-Agent": "LifeOpsAgent/0.1"},
        timeout=FREE_SEARCH_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    return {
        "provider": "searchfree",
        "query": query,
        "answer": _extract_answer(data),
        "results": _normalize_results(data),
        "raw": data,
    }


def _search_duckduckgo(query: str, max_results: int) -> dict:
    errors = []
    for endpoint in DUCKDUCKGO_ENDPOINTS:
        try:
            response = requests.get(
                endpoint,
                params={"q": query},
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 LifeOpsAgent/0.1",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
                timeout=(2, FREE_SEARCH_TIMEOUT_SECONDS),
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            errors.append(f"{_endpoint_name(endpoint)}: {exc}")
            continue
        parser = _DuckDuckGoHTMLParser(max_results=max_results)
        parser.feed(response.text)
        results = parser.results
        if results:
            return {
                "provider": "duckduckgo",
                "query": query,
                "answer": None,
                "results": results,
                "endpoint": endpoint,
            }
    if errors:
        raise requests.RequestException("; ".join(errors))
    return {
        "provider": "duckduckgo",
        "query": query,
        "answer": None,
        "results": [],
    }


def _search_bing_rss(query: str, max_results: int) -> dict:
    response = requests.get(
        "https://www.bing.com/search",
        params={"q": query, "format": "rss"},
        headers={
            "User-Agent": "LifeOpsAgent/0.1 (+https://www.bing.com)",
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
        },
        timeout=(2, FREE_SEARCH_TIMEOUT_SECONDS),
    )
    response.raise_for_status()
    try:
        root = ElementTree.fromstring(response.content)
    except ElementTree.ParseError as exc:
        raise RuntimeError("bing rss response is not valid xml") from exc
    results = []
    for item in root.findall("./channel/item")[:max_results]:
        title = _clean_text(item.findtext("title") or "")
        url = (item.findtext("link") or "").strip()
        snippet = _clean_text(item.findtext("description") or "")
        if not title or not url:
            continue
        results.append(
            {
                "name": title,
                "url": url,
                "snippet": snippet,
                "summary": snippet,
                "siteName": _site_name(url),
                "siteIcon": None,
                "datePublished": item.findtext("pubDate"),
                "raw": {"title": title, "link": url, "description": snippet},
            }
        )
    return {
        "provider": "bing",
        "query": query,
        "answer": None,
        "results": results,
    }


def _search_wikimedia(query: str, max_results: int) -> dict:
    response = requests.get(
        "https://zh.wikipedia.org/w/api.php",
        params={
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": max_results,
            "format": "json",
            "origin": "*",
            "utf8": 1,
        },
        headers={
            "User-Agent": "LifeOpsAgent/0.1",
        },
        timeout=FREE_SEARCH_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    results = []
    for item in data.get("query", {}).get("search", []):
        title = item.get("title", "")
        url = f"https://zh.wikipedia.org/wiki/{title.replace(' ', '_')}"
        results.append(
            {
                "name": title,
                "url": url,
                "snippet": item.get("snippet", ""),
                "summary": item.get("snippet", ""),
                "siteName": "zh.wikipedia.org",
                "siteIcon": None,
                "datePublished": None,
                "raw": item,
            }
        )
    return {
        "provider": "wikimedia",
        "query": query,
        "answer": None,
        "results": results,
        "raw": data,
    }


def _normalize_results(data: dict) -> list[dict]:
    items = data.get("webPages", {}).get("value") or data.get("results") or data.get("data") or []
    normalized = []
    for item in items:
        normalized.append(
            {
                "name": item.get("name") or item.get("title") or item.get("siteName") or "搜索结果",
                "url": item.get("url") or item.get("link"),
                "snippet": item.get("snippet") or item.get("summary") or item.get("content") or "",
                "summary": item.get("summary") or item.get("snippet") or "",
                "siteName": item.get("siteName"),
                "siteIcon": item.get("siteIcon"),
                "datePublished": item.get("datePublished") or item.get("date"),
                "raw": item,
            }
        )
    return [item for item in normalized if item.get("url")]


class _DuckDuckGoHTMLParser(HTMLParser):
    def __init__(self, max_results: int) -> None:
        super().__init__()
        self.max_results = max_results
        self.results: list[dict] = []
        self._current: dict | None = None
        self._capture: str | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        classes = set((attr.get("class") or "").split())
        if tag == "a" and "result__a" in classes and len(self.results) < self.max_results:
            self._current = {"url": _normalize_duckduckgo_url(attr.get("href") or "")}
            self._capture = "name"
            self._buffer = []
        elif self._current is not None and "result__snippet" in classes:
            self._capture = "snippet"
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._current is None or self._capture is None:
            return
        if self._capture == "name" and tag == "a":
            self._current["name"] = _clean_text("".join(self._buffer))
            self._capture = None
            self._buffer = []
        elif self._capture == "snippet" and tag in {"a", "div"}:
            self._current["snippet"] = _clean_text("".join(self._buffer))
            self._current["summary"] = self._current["snippet"]
            self._current["siteName"] = _site_name(self._current.get("url", ""))
            if self._current.get("url") and self._current.get("name"):
                self.results.append(self._current)
            self._current = None
            self._capture = None
            self._buffer = []


def _normalize_duckduckgo_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        return unquote(query["uddg"][0])
    return url


def _clean_text(text: str) -> str:
    return " ".join(text.split())


def _site_name(url: str) -> str | None:
    host = urlparse(url).netloc
    return host or None


def _endpoint_name(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.netloc + parsed.path).strip("/") or url


def _extract_answer(data: dict) -> str | None:
    for key in ["summary", "answer", "text"]:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if isinstance(data.get("webPages"), dict):
        value = data["webPages"].get("answer")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _search_error(provider: str, query: str, exc: Exception) -> dict:
    response = getattr(exc, "response", None)
    status_code = response.status_code if response is not None else None
    text = response.text if response is not None else str(exc)
    return {
        "provider": provider,
        "query": query,
        "results": [],
        "error": {
            "status_code": status_code,
            "message": text[:500],
        },
        "note": f"{provider} 搜索失败，已跳过网页搜索结果",
    }


def _attempt_error(provider: str, exc: Exception) -> dict:
    response = getattr(exc, "response", None)
    return {
        "provider": provider,
        "status": "error",
        "status_code": response.status_code if response is not None else None,
        "message": (response.text if response is not None else str(exc))[:300],
    }
