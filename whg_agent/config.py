from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List

from dotenv import load_dotenv


@dataclass(frozen=True)
class MailConfig:
    host: str
    port: int
    user: str
    password: str
    sender: str
    recipient: str


@dataclass(frozen=True)
class AppConfig:
    sites: List[str]
    data_dir: Path
    seen_dir: Path
    gemini_cmd: str
    dry_run: bool
    mail: MailConfig


def _to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_config(project_root: Path) -> AppConfig:
    load_dotenv(project_root / ".env")

    sites_path = project_root / "sites.json"
    if not sites_path.exists():
        raise FileNotFoundError(f"sites.json fehlt: {sites_path}")

    sites = json.loads(sites_path.read_text(encoding="utf-8"))
    if not isinstance(sites, list) or not all(isinstance(s, str) for s in sites):
        raise ValueError("sites.json muss eine Liste aus URLs (Strings) enthalten.")

    data_dir = project_root / "data"
    seen_dir = data_dir / "seen"
    seen_dir.mkdir(parents=True, exist_ok=True)

    mail = MailConfig(
        host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
        port=int(os.getenv("SMTP_PORT", "587")),
        user=os.getenv("SMTP_USER", ""),
        password=os.getenv("SMTP_PASSWORD", ""),
        sender=os.getenv("EMAIL_FROM", os.getenv("SMTP_USER", "")),
        recipient=os.getenv("EMAIL_TO", "timmydueren@gmail.com"),
    )

    return AppConfig(
        sites=sites,
        data_dir=data_dir,
        seen_dir=seen_dir,
        gemini_cmd=os.getenv("GEMINI_CMD", "gemini"),
        dry_run=_to_bool(os.getenv("DRY_RUN"), False),
        mail=mail,
    )
