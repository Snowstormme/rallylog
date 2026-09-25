from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
from urllib.parse import quote_plus
from xml.etree import ElementTree

import requests


NEWS_SOURCES = (
    {
        "key": "atp",
        "name": "ATP Tour",
        "url": "https://www.atptour.com/en/news",
        "search": "site:atptour.com/en/news",
        "description": "Men's tour reports, interviews and tournament updates.",
    },
    {
        "key": "wta",
        "name": "WTA",
        "url": "https://www.wtatennis.com/news",
        "search": "site:wtatennis.com/news",
        "description": "Women's tour news, match reactions and player stories.",
    },
    {
        "key": "itf",
        "name": "ITF",
        "url": "https://www.itftennis.com/en/news-and-media/articles/",
        "search": "site:itftennis.com/en/news-and-media/articles",
        "description": "Grand Slam, team competition and world tennis news.",
    },
    {
        "key": "wimbledon",
        "name": "Wimbledon",
        "url": "https://www.wimbledon.com/en_GB/news/index.html",
        "search": "site:wimbledon.com/en_GB/news",
        "description": "Official Championships news and features.",
    },
)


def _published_at(value):
    try:
        parsed = parsedate_to_datetime(value or "")
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)


@lru_cache(maxsize=32)
def _source_items(source_key, cache_window):
    source = next(item for item in NEWS_SOURCES if item["key"] == source_key)
    query = quote_plus(source["search"])
    response = requests.get(
        f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en",
        headers={"Accept": "application/rss+xml", "User-Agent": "Tennisd/1.0 (news reader)"},
        timeout=5,
    )
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)
    stories = []
    for item in root.findall(".//item")[:8]:
        title = (item.findtext("title") or "").strip()
        publisher = (item.findtext("source") or "").strip()
        for publisher_name in (publisher, source["name"]):
            suffix = f" - {publisher_name}"
            if publisher_name and title.endswith(suffix):
                title = title[:-len(suffix)].strip()
                break
        link = (item.findtext("link") or "").strip()
        if not title or not link.startswith("https://news.google.com/"):
            continue
        published_at = _published_at(item.findtext("pubDate"))
        stories.append({
            "title": title,
            "url": link,
            "source_key": source["key"],
            "source": source["name"],
            "published_at": published_at,
        })
    return stories


def fetch_news_items(source_key="all", now=None):
    """Load official publisher headlines through Google News RSS for discovery."""
    now = now or datetime.now(timezone.utc)
    cache_window = int(now.timestamp() // 900)
    keys = [source_key] if source_key != "all" else [source["key"] for source in NEWS_SOURCES]

    def load(key):
        try:
            return _source_items(key, cache_window)
        except (ElementTree.ParseError, StopIteration, requests.RequestException):
            return []

    with ThreadPoolExecutor(max_workers=len(keys)) as executor:
        groups = executor.map(load, keys)
    stories = [story for group in groups for story in group]
    stories.sort(key=lambda story: story["published_at"], reverse=True)
    return stories[:24]
