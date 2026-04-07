from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .models import Listing


SYSTEM_PROMPT_DE = """
Du bist ein Wohnungs-Scout-Agent fuer Innsbruck.

Aufgabe:
Pruefe den folgenden Seitentext. Falls es sich NICHT um eine einzelne Wohnungsanzeige handelt
(z. B. Kategorieseite, Uebersichtsseite, Fehlerseite, Login-Seite), antworte sofort mit:
{"is_relevant": false, "title": "Keine Anzeige", "reason": "Keine einzelne Wohnungsanzeige", "rent_eur": null, "rooms": null, "size_m2": null, "has_balcony_or_garden": null, "district": null}

Falls es eine einzelne Wohnungsanzeige ist, pruefe sie streng nach diesen Kriterien:
- Nur Wohnungen in Innsbruck (wirklich nur Innsbruck, kein Umland).
- 2 oder 3 Zimmer.
- Miete unter 1300 Euro pro Monat.
- Muss Balkon ODER Garten haben.
- Mindestens 45 m2.

Gib NUR valides JSON zurueck (kein Markdown, keine Erklaerungen), exakt in diesem Schema:
{
  "is_relevant": true/false,
  "title": "...",
  "reason": "kurze Begruendung auf Deutsch warum passend oder nicht",
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
    line_callback: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> GeminiResult:
    user_prompt = (
        f"Website: {site}\n"
        f"Listing-URL: {listing_url}\n\n"
        "Pruefe diese Seite nach den Kriterien und liefere das JSON:\n\n"
        f"{listing_text[:12000]}"
    )

    raw = _run_gemini(
        gemini_cmd, SYSTEM_PROMPT_DE, user_prompt,
        line_callback=line_callback, stop_event=stop_event,
    )
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


def _deliver_lines(text: str, callback: Callable[[str], None] | None) -> None:
    if callback is None:
        return
    for line in text.splitlines():
        if line.strip():
            callback(line)


class _Timeout(Exception):
    """Internal: raised when the Gemini CLI exceeds its timeout."""


def _popen_with_poll(
    cmd: list[str],
    stdin_text: str | None,
    timeout: float,
    stop_event: threading.Event | None,
) -> str:
    """
    Run *cmd* and return its stdout.  Polls every 0.2 s so that both a
    stop_event (Ctrl+C) and a timeout can kill the child process promptly.
    Raises _Timeout on timeout, GeminiError on non-zero exit without output.
    """
    import os
    import signal

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if stdin_text is not None:
        try:
            proc.stdin.write(stdin_text)  # type: ignore[union-attr]
            proc.stdin.close()            # type: ignore[union-attr]
        except BrokenPipeError:
            pass

    deadline = time.monotonic() + timeout
    try:
        while True:
            # Check stop flag (Ctrl+C)
            if stop_event is not None and stop_event.is_set():
                proc.kill()
                proc.wait()
                raise GeminiError("Abgebrochen (Ctrl+C).")

            # Check timeout
            if time.monotonic() > deadline:
                proc.kill()
                proc.wait()
                raise _Timeout()

            rc = proc.poll()
            if rc is not None:
                stdout = (proc.stdout.read() if proc.stdout else "").strip()  # type: ignore
                stderr = (proc.stderr.read() if proc.stderr else "").strip()  # type: ignore
                if rc != 0 and not stdout:
                    raise GeminiError(
                        f"Gemini CLI Fehler (exit {rc}): {stderr[:500]}"
                    )
                return stdout

            time.sleep(0.2)
    except GeminiError:
        raise
    except _Timeout:
        raise
    except Exception as exc:
        try:
            proc.kill()
        except Exception:
            pass
        raise GeminiError(f"Fehler beim Ausfuehren des Gemini CLI: {exc}") from exc


def _run_gemini(
    gemini_cmd: str,
    system_prompt: str,
    user_prompt: str,
    line_callback: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> str:
    full_prompt = f"SYSTEM:\n{system_prompt}\n\nUSER:\n{user_prompt}"

    # Attempt 1: -p flag (used by @google/gemini-cli)
    try:
        output = _popen_with_poll(
            [gemini_cmd, "-p", full_prompt],
            stdin_text=None,
            timeout=90,
            stop_event=stop_event,
        )
        if output:
            _deliver_lines(output, line_callback)
            return output
    except FileNotFoundError as exc:
        raise GeminiError(
            f"Gemini CLI nicht gefunden: '{gemini_cmd}'. Bitte Installation/Path pruefen."
        ) from exc
    except _Timeout:
        pass  # fall through to stdin attempt
    except GeminiError:
        raise

    # Attempt 2: stdin piping
    try:
        output = _popen_with_poll(
            [gemini_cmd],
            stdin_text=full_prompt,
            timeout=90,
            stop_event=stop_event,
        )
        if output:
            _deliver_lines(output, line_callback)
            return output
    except _Timeout:
        raise GeminiError(
            "Gemini CLI Timeout (90s). Bitte API-Key und Netzwerkverbindung pruefen."
        )
    except GeminiError:
        raise
    except Exception as exc:
        raise GeminiError(f"Gemini CLI Fehler: {exc}") from exc

    raise GeminiError("Gemini CLI lieferte keine verwertbare Ausgabe.")


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

    raise GeminiError("Gemini-Antwort enthaelt kein parsebares JSON.")


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
