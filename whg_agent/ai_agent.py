from __future__ import annotations

import json
import random
import re
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import requests

from .models import Listing

SYSTEM_PROMPT_DE = """
Du bist ein Wohnungs-Daten-Extraktor.

Aufgabe:
Lese den folgenden Seitentext und extrahiere die Eckdaten der Wohnungsanzeige.

Falls es sich NICHT um eine einzelne Wohnungsanzeige handelt
(z. B. Kategorie-/Uebersichtsseite, Fehlerseite, Login-Seite, Gesuchsanzeige von jemandem der eine Wohnung SUCHT),
setze "is_listing": false und alle anderen Felder auf null.

Falls es eine einzelne Wohnungsanzeige ist, setze "is_listing": true und extrahiere die Daten.

Gib NUR valides JSON zurueck (kein Markdown, keine Erklaerungen), exakt in diesem Schema:
{
  "is_listing": true/false,
  "title": "..."|null,
  "rent_eur": number|null,
  "rooms": number|null,
  "size_m2": number|null,
  "has_balcony_or_garden": true/false/null,
  "district": "..."|null,
  "listed_at": "TT.MM.JJJJ HH:MM"|null
}

Hinweise:
- "has_balcony_or_garden": true nur wenn explizit Balkon, Terrasse oder Garten erwaehnt wird, sonst false oder null.
- "rent_eur": Gesamtmiete/Warmmiete in Euro pro Monat als Zahl.
- "district": Stadt oder Stadtteil, z. B. "Innsbruck" oder "Pradl".
""".strip()

_COPILOT_API_URL = "https://api.githubcopilot.com/chat/completions"
_TOKEN_CACHE: dict[str, str] = {}
_TOKEN_LOCK = threading.Lock()
# Global rate limiter: enforces a minimum interval between any two API calls
_RATE_LOCK = threading.Lock()
_LAST_CALL_TIME: float = 0.0
_MIN_CALL_INTERVAL: float = 2.0  # seconds


@dataclass
class AiResult:
    is_listing: bool
    title: str | None
    rent_eur: float | None
    rooms: float | None
    size_m2: float | None
    has_balcony_or_garden: bool | None
    district: str | None
    listed_at: str | None


class AiError(RuntimeError):
    pass


def _get_copilot_token() -> str:
    """
    Get the Copilot OAuth token via gh CLI.
    Requires the 'copilot' scope: gh auth refresh -h github.com -s copilot
    Cached per process run.
    """
    with _TOKEN_LOCK:
        if "token" in _TOKEN_CACHE:
            return _TOKEN_CACHE["token"]

        try:
            result = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            oauth_token = result.stdout.strip()
        except FileNotFoundError:
            raise AiError(
                "gh CLI nicht gefunden. Bitte installieren: https://cli.github.com"
            )
        except subprocess.CalledProcessError as exc:
            raise AiError(
                f"gh auth token fehlgeschlagen: {exc.stderr.strip()}"
            ) from exc

        if not oauth_token:
            raise AiError(
                "gh auth token gab kein Token zurueck. Bitte 'gh auth login' ausfuehren."
            )

        _TOKEN_CACHE["token"] = oauth_token
        return oauth_token


def evaluate_listing(
    copilot_model: str,
    site: str,
    listing_url: str,
    listing_text: str,
    line_callback: Callable[[str], None] | None = None,
    warn_callback: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> AiResult:
    if stop_event and stop_event.is_set():
        raise AiError("Abgebrochen (Ctrl+C).")

    user_prompt = (
        f"Website: {site}\n"
        f"Listing-URL: {listing_url}\n\n"
        "Extrahiere die Wohnungsdaten aus diesem Seitentext:\n\n"
        f"{listing_text[:12000]}"
    )

    raw = _call_copilot_api(
        copilot_model, SYSTEM_PROMPT_DE, user_prompt, stop_event, warn_callback
    )

    payload = _extract_json(raw)

    if line_callback:
        line_callback(json.dumps(payload, ensure_ascii=False))

    return AiResult(
        is_listing=bool(payload.get("is_listing", False)),
        title=_to_str_or_none(payload.get("title")),
        rent_eur=_to_float(payload.get("rent_eur")),
        rooms=_to_float(payload.get("rooms")),
        size_m2=_to_float(payload.get("size_m2")),
        has_balcony_or_garden=_to_bool_or_none(payload.get("has_balcony_or_garden")),
        district=_to_str_or_none(payload.get("district")),
        listed_at=_to_str_or_none(payload.get("listed_at")),
    )


def to_listing(site: str, url: str, result: AiResult) -> Listing:
    return Listing(
        title=result.title or "(ohne Titel)",
        url=url,
        source_site=site,
        rent_eur=result.rent_eur,
        rooms=result.rooms,
        size_m2=result.size_m2,
        has_balcony_or_garden=result.has_balcony_or_garden,
        district=result.district,
        listed_at=result.listed_at,
    )


def _call_copilot_api(
    model: str,
    system_prompt: str,
    user_prompt: str,
    stop_event: threading.Event | None,
    warn_callback: Callable[[str], None] | None = None,
) -> str:
    token = _get_copilot_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Copilot-Integration-Id": "vscode-chat",
        "Editor-Version": "vscode/1.95.0",
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
    }

    max_retries = 10
    backoff = 2  # seconds, doubled on each retry

    for attempt in range(max_retries):
        if stop_event and stop_event.is_set():
            raise AiError("Abgebrochen (Ctrl+C).")

        # Enforce minimum interval between any two Copilot API calls globally
        global _LAST_CALL_TIME
        with _RATE_LOCK:
            now = time.time()
            wait_needed = _LAST_CALL_TIME + _MIN_CALL_INTERVAL - now
            if wait_needed > 0:
                time.sleep(wait_needed)
            _LAST_CALL_TIME = time.time()

        try:
            resp = requests.post(
                _COPILOT_API_URL,
                headers=headers,
                json=body,
                timeout=90,
            )
        except requests.Timeout:
            raise AiError("Copilot API Timeout (90s).")
        except requests.RequestException as exc:
            raise AiError(f"Copilot API Netzwerkfehler: {exc}") from exc

        if stop_event and stop_event.is_set():
            raise AiError("Abgebrochen (Ctrl+C).")

        if resp.status_code == 401:
            with _TOKEN_LOCK:
                _TOKEN_CACHE.clear()
            raise AiError(
                "Copilot API: 401 Unauthorized. Bitte 'gh auth login' erneut ausfuehren."
            )

        if resp.status_code in (403, 429):
            if attempt < max_retries - 1:
                wait = (backoff * (2**attempt)) + random.uniform(0, 2)
                if warn_callback:
                    warn_callback(
                        f"Retry {attempt + 1}/{max_retries} nach {resp.status_code} "
                        f"– warte {wait:.1f}s …"
                    )
                time.sleep(wait)
                continue
            raise AiError(
                f"Copilot API: {resp.status_code} nach {max_retries} Versuchen. "
                "Kein aktives Copilot-Abonnement oder Rate-Limit erreicht."
            )

        if not resp.ok:
            raise AiError(f"Copilot API Fehler {resp.status_code}: {resp.text[:300]}")

        try:
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise AiError(
                f"Copilot API: unerwartetes Antwortformat: {resp.text[:300]}"
            ) from exc

    raise AiError("Copilot API: Maximale Wiederholungsversuche erreicht.")


def _extract_json(raw: str) -> dict:
    raw = raw.strip()

    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.DOTALL)
    if fenced_match:
        raw = fenced_match.group(1).strip()

    if raw.startswith("{") and raw.endswith("}"):
        return json.loads(raw)

    brace_match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if brace_match:
        return json.loads(brace_match.group(0))

    raise AiError("Copilot-Antwort enthaelt kein parsebares JSON.")


def _to_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_bool_or_none(value) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "1", "yes", "ja"}:
            return True
        if v in {"false", "0", "no", "nein"}:
            return False
    return None


def _to_str_or_none(value) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None
