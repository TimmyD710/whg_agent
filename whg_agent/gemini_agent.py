from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass

from .models import Listing


SYSTEM_PROMPT_DE = """
Du bist ein Wohnungs-Scout-Agent für Innsbruck.
Aufgabe:
- Prüfe eine einzelne Wohnungsanzeige (Detailseite) streng nach diesen Regeln.
- Nur Wohnungen in Innsbruck (und wirklich nur Innsbruck).
- 2 oder 3 Zimmer.
- Miete unter 1300 Euro pro Monat.
- Muss Balkon ODER Garten haben.
- Mindestens 45 m².

Gib NUR valides JSON zurück (ohne Markdown), exakt in diesem Schema:
{
  "is_relevant": true/false,
  "title": "...",
  "reason": "kurze Begründung auf Deutsch",
  "rent_eur": number|null,
  "rooms": number|null,
  "size_m2": number|null,
  "has_balcony_or_garden": true/false/null,
  "district": "..."|null
}
""".strip()


@dataclass
class GeminiResult:
    is_relevant: bool
    title: str
    reason: str
    rent_eur: float | None
    rooms: float | None
    size_m2: float | None
    has_balcony_or_garden: bool | None
    district: str | None


class GeminiError(RuntimeError):
    pass


def evaluate_listing_with_gemini(
    gemini_cmd: str,
    site: str,
    listing_url: str,
    listing_text: str,
) -> GeminiResult:
    user_prompt = (
        f"Website: {site}\n"
        f"Listing-URL: {listing_url}\n\n"
        "Prüfe diese Anzeige nach den Kriterien und liefere das JSON:\n\n"
        f"{listing_text[:12000]}"
    )

    raw = _run_gemini(gemini_cmd, SYSTEM_PROMPT_DE, user_prompt)
    payload = _extract_json(raw)

    return GeminiResult(
        is_relevant=bool(payload.get("is_relevant", False)),
        title=str(payload.get("title", "(ohne Titel)")),
        reason=str(payload.get("reason", "")),
        rent_eur=_to_float(payload.get("rent_eur")),
        rooms=_to_float(payload.get("rooms")),
        size_m2=_to_float(payload.get("size_m2")),
        has_balcony_or_garden=_to_bool_or_none(payload.get("has_balcony_or_garden")),
        district=_to_str_or_none(payload.get("district")),
    )


def to_listing(site: str, url: str, result: GeminiResult) -> Listing:
    return Listing(
        title=result.title,
        url=url,
        source_site=site,
        reason=result.reason,
        rent_eur=result.rent_eur,
        rooms=result.rooms,
        size_m2=result.size_m2,
        has_balcony_or_garden=result.has_balcony_or_garden,
        district=result.district,
    )


def _run_gemini(gemini_cmd: str, system_prompt: str, user_prompt: str) -> str:
    full_prompt = f"SYSTEM:\n{system_prompt}\n\nUSER:\n{user_prompt}"

    attempts = [
        [gemini_cmd, "-p", full_prompt],
        [gemini_cmd, "--prompt", full_prompt],
        [gemini_cmd],
    ]

    for command in attempts:
        try:
            use_stdin = len(command) == 1
            proc = subprocess.run(
                command,
                input=full_prompt if use_stdin else None,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            output = (proc.stdout or "").strip() or (proc.stderr or "").strip()
            if proc.returncode == 0 and output:
                return output
        except FileNotFoundError as exc:
            raise GeminiError(
                f"Gemini CLI nicht gefunden: '{gemini_cmd}'. Bitte Installation/Path prüfen."
            ) from exc
        except Exception:
            continue

    raise GeminiError("Gemini CLI konnte keine verwertbare Antwort liefern.")


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

    raise GeminiError("Gemini-Antwort enthält kein parsebares JSON.")


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
