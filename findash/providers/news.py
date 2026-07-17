"""News provider: ``news:SYM`` via a source waterfall (adapted from Fincept).

Order: publisher RSS feeds (Fincept's default-feed approach, free and
keyless) -> NewsAPI.org (if NEWSAPI_KEY is set) -> gnews package ->
yfinance Ticker.news as a last resort. RSS results are only accepted when
enough headlines match the symbol/query; otherwise the fetch falls through
to the next source, so thin RSS matches never mask the older sources.
"""

from __future__ import annotations

import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional
from xml.etree import ElementTree

import requests

from ..datahub import DataHub, Provider

MAX_ITEMS = 25

# Curated market-focused subset of Fincept Terminal's default RSS feeds
# (research/fincept-terminal .../NewsService_Feeds.cpp): free, no key.
RSS_FEEDS: list[tuple[str, str, str]] = [
    # (publisher, url, category)
    ("Bloomberg", "https://feeds.bloomberg.com/markets/news.rss", "markets"),
    ("WSJ", "https://feeds.a.dj.com/rss/RSSMarketsMain.xml", "markets"),
    ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/topstories/", "markets"),
    (
        "CNBC",
        "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
        "markets",
    ),
    ("Seeking Alpha", "https://seekingalpha.com/market_currents.xml", "markets"),
    ("BBC", "http://feeds.bbci.co.uk/news/business/rss.xml", "markets"),
    ("Investing.com", "https://www.investing.com/rss/news.rss", "markets"),
    ("Benzinga", "https://www.benzinga.com/feed", "markets"),
    ("OilPrice", "https://oilprice.com/rss/main", "energy"),
    ("FXStreet", "https://www.fxstreet.com/rss/news", "forex"),
]

RSS_CACHE_TTL = 180.0  # seconds; keeps feed polling polite across panels
RSS_FETCH_TIMEOUT = 6.0
RSS_MIN_MATCHES = 5  # fewer matches than this -> fall through to next source
_RSS_HEADERS = {"User-Agent": "Mozilla/5.0 (findash RSS reader)"}

_rss_lock = threading.Lock()
_rss_cache: dict[str, Any] = {"ts": 0.0, "items": []}


def _parse_feed_datetime(value: str) -> Optional[datetime]:
    """RSS pubDate is RFC-2822, Atom updated is ISO-8601; try both."""
    text = (value or "").strip()
    if not text:
        return None
    dt: Optional[datetime] = None
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt is not None and dt.tzinfo is None:  # keep sort keys comparable
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_feed_xml(xml_text: str, publisher: str, category: str) -> list[dict]:
    """Extract items from RSS 2.0 or Atom XML; malformed feeds yield []."""
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []
    items: list[dict] = []

    for item in root.iter("item"):  # RSS 2.0
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        items.append(
            {
                "title": title,
                "publisher": publisher,
                "url": (item.findtext("link") or "").strip(),
                "published": (item.findtext("pubDate") or "").strip(),
                "category": category,
            }
        )

    atom = "{http://www.w3.org/2005/Atom}"
    for entry in root.iter(f"{atom}entry"):  # Atom
        title = (entry.findtext(f"{atom}title") or "").strip()
        if not title:
            continue
        url = ""
        link = entry.find(f"{atom}link")
        if link is not None:
            url = (link.get("href") or "").strip()
        published = (
            entry.findtext(f"{atom}published") or entry.findtext(f"{atom}updated") or ""
        ).strip()
        items.append(
            {
                "title": title,
                "publisher": publisher,
                "url": url,
                "published": published,
                "category": category,
            }
        )
    return items


def _fetch_one_feed(feed: tuple[str, str, str]) -> list[dict]:
    publisher, url, category = feed
    try:
        resp = requests.get(url, headers=_RSS_HEADERS, timeout=RSS_FETCH_TIMEOUT)
        resp.raise_for_status()
        return _parse_feed_xml(resp.text, publisher, category)
    except Exception:
        return []  # dead/slow feeds must not break the rest


def _rss_items() -> list[dict]:
    """All items across RSS_FEEDS, newest first, cached for RSS_CACHE_TTL."""
    with _rss_lock:
        if time.monotonic() - _rss_cache["ts"] < RSS_CACHE_TTL:
            return _rss_cache["items"]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(_fetch_one_feed, RSS_FEEDS))
    items = [item for feed_items in results for item in feed_items]
    epoch = datetime.fromtimestamp(0, tz=timezone.utc)
    items.sort(
        key=lambda i: _parse_feed_datetime(i["published"]) or epoch, reverse=True
    )
    with _rss_lock:
        _rss_cache["ts"] = time.monotonic()
        _rss_cache["items"] = items
    return items


class NewsProvider(Provider):
    """Serves ``news:*`` topics."""

    def topic_patterns(self) -> list[str]:
        return ["news:*", "newsq:*"]

    def refresh(self, topics: list[str]) -> None:
        hub = DataHub.instance()
        for topic in topics:
            if topic.startswith("newsq:"):
                query = topic.split(":", 1)[1]
                hub.run_async(lambda t=topic, q=query: self._fetch_query(t, q))
                continue
            parts = topic.split(":")
            if len(parts) != 2:
                hub.publish_error(topic, f"malformed news topic: {topic}")
                continue
            symbol = parts[1]
            hub.run_async(lambda t=topic, s=symbol: self._fetch(t, s))

    def _fetch(self, topic: str, symbol: str) -> None:
        hub = DataHub.instance()
        try:
            items = self._from_rss_symbol(symbol)
            if items is None:
                items = self._from_newsapi(symbol)
            if items is None:
                items = self._from_gnews(symbol)
            if items is None:
                items = self._from_yfinance(symbol)
            if items is None:
                items = []
            hub.publish(topic, items[:MAX_ITEMS])
        except Exception as exc:
            hub.publish_error(topic, f"news fetch failed: {exc}")

    def _fetch_query(self, topic: str, query: str) -> None:
        """Free-text query waterfall: NewsAPI -> gnews, no yfinance fallback
        (yfinance's ``Ticker.news`` is symbol-only, not a text search)."""
        hub = DataHub.instance()
        try:
            items = self._from_rss_query(query)
            if items is None:
                items = self._from_newsapi(query)
            if items is None:
                items = self._from_gnews_query(query)
            if items is None:
                items = []
            hub.publish(topic, items[:MAX_ITEMS])
        except Exception as exc:
            hub.publish_error(topic, f"news query fetch failed: {exc}")

    # -- sources -------------------------------------------------------

    @staticmethod
    def _strip_category(items: list[dict]) -> list[dict]:
        """Drop the internal 'category' key so published payloads keep the
        same shape as the other sources (title/publisher/url/published)."""
        return [{k: v for k, v in i.items() if k != "category"} for i in items]

    def _from_rss_symbol(self, symbol: str) -> Optional[list[dict]]:
        """Headlines mentioning the ticker as a standalone word (case-
        sensitive: 'AAPL' matches, 'aapl' inside a word doesn't). Recall is
        deliberately conservative — most symbols fall through to the
        broader sources below."""
        try:
            pattern = re.compile(rf"\b{re.escape(symbol)}\b")
            matches = [i for i in _rss_items() if pattern.search(i["title"])]
            if len(matches) < RSS_MIN_MATCHES:
                return None
            return self._strip_category(matches)
        except Exception:
            return None

    def _from_rss_query(self, query: str) -> Optional[list[dict]]:
        """Headlines where every query word appears in the title, or where
        the query names a feed category (e.g. the Topic News default
        'markets' pulls the whole markets feed set)."""
        try:
            tokens = [t for t in query.lower().split() if t]
            if not tokens:
                return None
            matches = []
            for item in _rss_items():
                title = item["title"].lower()
                if all(t in title for t in tokens) or query.lower() == item["category"]:
                    matches.append(item)
            if len(matches) < RSS_MIN_MATCHES:
                return None
            return self._strip_category(matches)
        except Exception:
            return None

    def _from_newsapi(self, symbol: str) -> Optional[list[dict]]:
        api_key = os.environ.get("NEWSAPI_KEY")
        if not api_key:
            return None
        try:
            resp = requests.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": symbol,
                    "sortBy": "publishedAt",
                    "pageSize": MAX_ITEMS,
                },
                headers={"X-Api-Key": api_key},
                timeout=10,
            )
            resp.raise_for_status()
            articles = resp.json().get("articles", [])
            items = []
            for a in articles[:MAX_ITEMS]:
                source = a.get("source") or {}
                items.append(
                    {
                        "title": a.get("title") or "",
                        "publisher": source.get("name") or "",
                        "url": a.get("url") or "",
                        "published": a.get("publishedAt") or "",
                    }
                )
            return items
        except Exception:
            return None  # fall through to gnews

    def _from_gnews(self, symbol: str) -> Optional[list[dict]]:
        try:
            from gnews import GNews
        except Exception:
            return None
        try:
            gn = GNews(max_results=MAX_ITEMS)
            results = gn.get_news(f'"{symbol}" stock') or []
            items = []
            for r in results[:MAX_ITEMS]:
                publisher = r.get("publisher")
                if isinstance(publisher, dict):
                    publisher = publisher.get("title", "")
                items.append(
                    {
                        "title": r.get("title") or "",
                        "publisher": publisher or "",
                        "url": r.get("url") or "",
                        "published": r.get("published date") or "",
                    }
                )
            return items
        except Exception:
            return None  # fall through to yfinance

    def _from_gnews_query(self, query: str) -> Optional[list[dict]]:
        """Like ``_from_gnews`` but for free-text queries: no stock-ticker
        decoration around the search string."""
        try:
            from gnews import GNews
        except Exception:
            return None
        try:
            gn = GNews(max_results=MAX_ITEMS)
            results = gn.get_news(query) or []
            items = []
            for r in results[:MAX_ITEMS]:
                publisher = r.get("publisher")
                if isinstance(publisher, dict):
                    publisher = publisher.get("title", "")
                items.append(
                    {
                        "title": r.get("title") or "",
                        "publisher": publisher or "",
                        "url": r.get("url") or "",
                        "published": r.get("published date") or "",
                    }
                )
            return items
        except Exception:
            return None

    def _from_yfinance(self, symbol: str) -> Optional[list[dict]]:
        try:
            import yfinance as yf
        except Exception:
            return None
        try:
            tkr = yf.Ticker(symbol)
            raw = tkr.news or []
            items = []
            for item in raw[:MAX_ITEMS]:
                items.append(self._parse_yf_news_item(item))
            return items
        except Exception:
            return None

    @staticmethod
    def _parse_yf_news_item(item: dict) -> dict:
        """yfinance's news dict shape has varied across versions: newer
        releases nest fields under item["content"], older ones are flat."""
        content = item.get("content") if isinstance(item, dict) else None
        if isinstance(content, dict):
            title = content.get("title") or ""
            provider = content.get("provider") or {}
            publisher = provider.get("displayName", "") if isinstance(provider, dict) else ""
            url = ""
            canonical = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
            if isinstance(canonical, dict):
                url = canonical.get("url", "") or ""
            published = content.get("pubDate") or content.get("displayTime") or ""
            return {"title": title, "publisher": publisher, "url": url, "published": published}

        title = item.get("title") or ""
        publisher = item.get("publisher") or ""
        url = item.get("link") or ""
        published = ""
        ts = item.get("providerPublishTime")
        if ts:
            try:
                published = datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
            except Exception:
                published = ""
        return {"title": title, "publisher": publisher, "url": url, "published": published}
