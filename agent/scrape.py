"""HTTP fetcher + parser for bold.org blogs and SGP/detail pages.

Disk-cached so reruns are deterministic and offline-friendly, and so we don't
hammer bold.org while iterating. Falls back to inline seed copy if a live fetch
fails so the demo never breaks.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from agent import config

logger = logging.getLogger(__name__)

_last_request_ts = 0.0


def _polite_get(url: str) -> str | None:
    """Single GET with UA, timeout, and a process-wide 1 req/sec floor."""
    global _last_request_ts
    elapsed = time.monotonic() - _last_request_ts
    if elapsed < config.SCRAPE_RATE_LIMIT_SECONDS:
        time.sleep(config.SCRAPE_RATE_LIMIT_SECONDS - elapsed)
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": config.SCRAPE_USER_AGENT},
            timeout=config.SCRAPE_TIMEOUT_SECONDS,
        )
        _last_request_ts = time.monotonic()
        if resp.status_code >= 400:
            logger.warning("fetch %s -> %s", url, resp.status_code)
            return None
        return resp.text
    except requests.RequestException as exc:
        logger.warning("fetch %s failed: %s", url, exc)
        return None


def _cache_path(url: str) -> Path:
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return config.CACHE_DIR / f"{hashlib.sha1(url.encode()).hexdigest()}.html"


def fetch_html(url: str, *, use_cache: bool = True) -> str | None:
    """Return raw HTML for `url`, populating the disk cache on the way through."""
    cache_file = _cache_path(url)
    if use_cache and cache_file.exists():
        return cache_file.read_text(encoding="utf-8")
    html = _polite_get(url)
    if html is not None:
        cache_file.write_text(html, encoding="utf-8")
    return html


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


@dataclass
class BlogPage:
    url: str
    title: str
    h1: str
    full_text_excerpt: str  # first ~3000 chars, what we hand the LLM
    content_hash: str


@dataclass
class SgpEntry:
    url: str
    title: str
    one_line_summary: str


def _parse_blog(url: str, html: str) -> BlogPage:
    soup = BeautifulSoup(html, "html.parser")
    title = _clean_text(soup.title.string if soup.title and soup.title.string else "")
    h1_tag = soup.find("h1")
    h1 = _clean_text(h1_tag.get_text() if h1_tag else title)
    paragraphs = [_clean_text(p.get_text()) for p in soup.find_all("p")]
    paragraphs = [p for p in paragraphs if len(p) > 40]
    full_text = " ".join(paragraphs)[:3000]
    content_hash = "sha256:" + hashlib.sha256(full_text.encode("utf-8")).hexdigest()
    return BlogPage(
        url=url,
        title=title,
        h1=h1,
        full_text_excerpt=full_text,
        content_hash=content_hash,
    )


def _parse_sgp(url: str, html: str) -> SgpEntry:
    soup = BeautifulSoup(html, "html.parser")
    title = _clean_text(soup.title.string if soup.title and soup.title.string else "")
    h1_tag = soup.find("h1")
    h1 = _clean_text(h1_tag.get_text() if h1_tag else title)
    meta = soup.find("meta", attrs={"name": "description"})
    description = _clean_text(meta["content"]) if meta and meta.get("content") else ""
    if not description:
        first_p = soup.find("p")
        description = _clean_text(first_p.get_text()) if first_p else ""
    description = description[:240]
    return SgpEntry(
        url=url,
        title=title or h1,
        one_line_summary=description,
    )


def _fallback_blog(url: str, fallback: dict[str, Any]) -> BlogPage:
    """Build a BlogPage from inline seed copy when the live fetch fails."""
    full_text = fallback.get("fallback_excerpt") or fallback.get("title", "")
    content_hash = "sha256:" + hashlib.sha256(full_text.encode("utf-8")).hexdigest()
    return BlogPage(
        url=url,
        title=fallback.get("title", url),
        h1=fallback.get("title", url),
        full_text_excerpt=full_text[:3000],
        content_hash=content_hash,
    )


def _fallback_sgp(url: str, fallback: dict[str, Any]) -> SgpEntry:
    return SgpEntry(
        url=url,
        title=fallback.get("title", url),
        one_line_summary=fallback.get("one_line_summary", ""),
    )


def fetch_blog(url: str, fallback: dict[str, Any] | None = None) -> BlogPage:
    html = fetch_html(url)
    if html is None:
        if fallback is None:
            raise RuntimeError(f"fetch failed and no fallback provided for {url}")
        logger.warning("using fallback for %s", url)
        return _fallback_blog(url, fallback)
    return _parse_blog(url, html)


def fetch_sgp(url: str, fallback: dict[str, Any] | None = None) -> SgpEntry:
    html = fetch_html(url)
    if html is None:
        if fallback is None:
            raise RuntimeError(f"fetch failed and no fallback provided for {url}")
        logger.warning("using fallback for %s", url)
        return _fallback_sgp(url, fallback)
    return _parse_sgp(url, html)


def load_seed_blogs() -> list[dict[str, Any]]:
    return json.loads(config.SEED_BLOGS_FILE.read_text(encoding="utf-8"))


def load_seed_catalog() -> list[dict[str, Any]]:
    return json.loads(config.SEED_CATALOG_FILE.read_text(encoding="utf-8"))


def build_catalog() -> list[SgpEntry]:
    """Resolve every seed catalog URL to a compact SgpEntry the LLM can read in one prompt."""
    seeds = load_seed_catalog()
    entries: list[SgpEntry] = []
    for seed in seeds:
        entry = fetch_sgp(seed["url"], fallback=seed)
        entries.append(entry)
    return entries


def fetch_all_blogs() -> list[BlogPage]:
    seeds = load_seed_blogs()
    return [fetch_blog(seed["url"], fallback=seed) for seed in seeds]
