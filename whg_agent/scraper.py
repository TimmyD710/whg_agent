from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class WebFetchError(RuntimeError):
    pass


def fetch_html(url: str, timeout: int = 30) -> str:
    headers = {"User-Agent": USER_AGENT}
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response.text
    except Exception as exc:  # pragma: no cover - external I/O
        raise WebFetchError(f"Fehler beim Laden von {url}: {exc}") from exc


def extract_listing_links(overview_url: str, html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    parsed_root = urlparse(overview_url)
    domain = parsed_root.netloc

    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith("#"):
            continue
        absolute = urljoin(overview_url, href)
        parsed = urlparse(absolute)

        if parsed.netloc != domain:
            continue
        if _looks_like_search_or_navigation(absolute):
            continue
        if not _looks_like_listing_url(absolute):
            continue

        links.append(absolute)

    deduped = []
    seen = set()
    for link in links:
        canonical = _canonicalize_url(link)
        if canonical in seen:
            continue
        seen.add(canonical)
        deduped.append(link)

    return deduped


def listing_page_text(url: str) -> str:
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")

    for node in soup(["script", "style", "noscript"]):
        node.extract()

    text = soup.get_text("\n", strip=True)
    return re.sub(r"\n{2,}", "\n", text)


def _looks_like_search_or_navigation(url: str) -> bool:
    lower = url.lower()
    blocked_patterns = [
        "erweiterte-suche",
        "/suche",
        "/search",
        "/filter",
        "/karte",
        "login",
        "register",
        "kontakt",
        "impressum",
        "datenschutz",
    ]
    return any(pattern in lower for pattern in blocked_patterns)


def _looks_like_listing_url(url: str) -> bool:
    lower = url.lower()
    positive_patterns = [
        "wohnung",
        "miet",
        "immobil",
        "objekt",
        "expose",
        "anzeige",
        "iad/object",
        "adId",
        "details",
    ]
    if any(pattern in lower for pattern in positive_patterns):
        return True

    path = urlparse(url).path
    return bool(re.search(r"\d{4,}", path))


def _canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
