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

    # If we have a strict portal-specific pattern, use ONLY that – bypass all
    # heuristic blocklists (which can accidentally reject valid listing URLs).
    known_portal_pattern: re.Pattern[str] | None = None
    for portal_domain, pattern in _PORTAL_LISTING_PATTERNS.items():
        if portal_domain in domain:
            known_portal_pattern = pattern
            break

    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith("#"):
            continue
        absolute = urljoin(overview_url, href)
        parsed = urlparse(absolute)

        if parsed.netloc != domain:
            continue

        if known_portal_pattern is not None:
            # Known portal: only accept URLs that match the precise pattern.
            if known_portal_pattern.search(absolute):
                links.append(absolute)
        else:
            # Unknown portal: fall back to heuristics.
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

    for node in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        node.extract()

    text = soup.get_text("\n", strip=True)
    return re.sub(r"\n{2,}", "\n", text)


# ---------------------------------------------------------------------------
# Per-portal positive URL patterns: a URL must match one of these to be
# considered a real listing page (not navigation/category/search).
# ---------------------------------------------------------------------------
_PORTAL_LISTING_PATTERNS: dict[str, re.Pattern[str]] = {
    # wohnen.oehweb.at – listing detail pages sit under /wohnung/<slug>/
    # e.g. /wohnung/2-zimmer-wohnung-mit-grosszuegigem-bakon/
    "wohnen.oehweb.at": re.compile(r"/wohnung/[a-z0-9][a-z0-9-]{4,}/"),
    # immo.tt.com – listing paths: /immobilien/wohnung/<type>/tirol/<district>/<alphanumericID>
    # e.g. /immobilien/wohnung/wohnung/tirol/innsbruck-stadt/1FU64mI0kqX
    "immo.tt.com": re.compile(r"/immobilien/wohnung/[^/]+/tirol/[^/]+/[A-Za-z0-9]{5,}$"),
    # immobilienscout24.at – expose pages use hex IDs (not decimal)
    # e.g. /expose/69adad71243b7d52de46eae3
    "immobilienscout24.at": re.compile(r"/expose/[a-fA-F0-9]{10,}"),
    # willhaben.at – listing paths: /iad/immobilien/d/<category>/tirol/innsbruck/<slug>-<10-digit-id>/
    # e.g. /iad/immobilien/d/mietwohnungen/tirol/innsbruck/perfekte-2-zimmer-wohnung-...-1074162054/
    "willhaben.at": re.compile(r"/iad/immobilien/d/[^?#]+-\d{7,}/"),
}

# Paths that look like keyword-category slugs (e.g. /3-zimmer-wohnung-mieten)
# are NOT individual listings even if they contain apartment keywords.
_CATEGORY_SLUG_RE = re.compile(
    r"/(\d+-zimmer|wohnung|miet|neubauwohnung|appartement)"
    r"(-bis-\d+|-ab-\d+|-mieten|-kaufen|-m2|-qm)?",
    re.IGNORECASE,
)

_BLOCKED_FRAGMENTS = [
    "erweiterte-suche", "/suche", "/search", "/filter", "/karte",
    "login", "register", "kontakt", "impressum", "datenschutz",
    "/merkliste", "/favorit", "/agent", "/abo", "/newsletter",
    "/ratgeber", "/news", "/blog", "/hilfe", "/faq",
    "?page=", "?sort=",
]


def _looks_like_search_or_navigation(url: str) -> bool:
    lower = url.lower()
    if any(pattern in lower for pattern in _BLOCKED_FRAGMENTS):
        return True
    # Block pure category slugs (no numeric ID in the path)
    path = urlparse(url).path
    if _CATEGORY_SLUG_RE.search(path) and not re.search(r"\d{5,}", path):
        return True
    return False


def _looks_like_listing_url(url: str) -> bool:
    parsed = urlparse(url)
    domain = parsed.netloc

    # Try portal-specific patterns first (most reliable)
    for portal_domain, pattern in _PORTAL_LISTING_PATTERNS.items():
        if portal_domain in domain:
            return bool(pattern.search(url))

    # Fallback for unknown portals: require a numeric ID of >=5 digits
    path = parsed.path
    return bool(re.search(r"\d{5,}", path))


def _canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
