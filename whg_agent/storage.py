from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class SeenState:
    seen_urls: set[str]
    last_run: str | None


def slugify_site(site_url: str) -> str:
    cleaned = re.sub(r"^https?://", "", site_url.lower())
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-")
    return cleaned[:120] or "site"


def state_file_for_site(seen_dir: Path, site_url: str) -> Path:
    return seen_dir / f"{slugify_site(site_url)}.json"


def load_seen_state(path: Path) -> SeenState:
    if not path.exists():
        return SeenState(seen_urls=set(), last_run=None)

    payload = json.loads(path.read_text(encoding="utf-8"))
    urls = payload.get("seen_urls", [])
    last_run = payload.get("last_run")

    if not isinstance(urls, list):
        urls = []
    return SeenState(seen_urls=set(str(u) for u in urls), last_run=last_run)


def save_seen_state(path: Path, state: SeenState) -> None:
    payload = {
        "last_run": datetime.now(timezone.utc).isoformat(),
        "seen_urls": sorted(state.seen_urls),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
