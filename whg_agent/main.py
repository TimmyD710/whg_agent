from __future__ import annotations

import argparse
import dataclasses
import json
import os
import subprocess
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from .config import load_config
from .emailer import send_result_email
from .gemini_agent import GeminiError, evaluate_listing_with_gemini, to_listing
from .models import AgentResult, Listing
from .reporter import build_html_report, write_html_report
from .scraper import WebFetchError, extract_listing_links, fetch_html, listing_page_text
from .storage import load_seen_state, save_seen_state, state_file_for_site

_RESULTS_JSON = "output/results.json"

_PRINT_LOCK = threading.Lock()


def _save_results_json(listings: list[Listing], project_root: Path) -> Path:
    path = project_root / _RESULTS_JSON
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [dataclasses.asdict(l) for l in listings]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _load_results_json(project_root: Path) -> list[Listing]:
    path = project_root / _RESULTS_JSON
    if not path.exists():
        raise FileNotFoundError(f"Keine gespeicherten Ergebnisse gefunden unter: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    known_fields = {f.name for f in dataclasses.fields(Listing)}
    return [Listing(**{k: v for k, v in entry.items() if k in known_fields}) for entry in raw]


def _site_label(url: str) -> str:
    return (urlparse(url).netloc or url)[:35]


class AgentLogger:
    """Thread-safe logger that prefixes every line with the site domain."""

    def __init__(self, site: str) -> None:
        self._prefix = f"[{_site_label(site)}]"

    def log(self, msg: str) -> None:
        with _PRINT_LOCK:
            print(f"{self._prefix} {msg}", flush=True)

    def warn(self, msg: str) -> None:
        self.log(f"⚠️  {msg}")

    def error(self, msg: str) -> None:
        self.log(f"❌ {msg}")


def run_agent_for_site(
    site: str,
    project_root: Path,
    copilot_model: str,
    logger: AgentLogger | None = None,
    stop_event: threading.Event | None = None,
) -> AgentResult:
    log = logger or AgentLogger(site)
    started = datetime.now()
    processed_urls: list[str] = []
    relevant: list[Listing] = []

    seen_file = state_file_for_site(project_root / "data" / "seen", site)
    state = load_seen_state(seen_file)

    try:
        log.log("Lade Übersichtsseite …")
        overview_html = fetch_html(site)
        candidate_links = extract_listing_links(site, overview_html)
        unseen_links = [u for u in candidate_links if u not in state.seen_urls]
        log.log(
            f"{len(candidate_links)} Inserat(e) gefunden – "
            f"{len(unseen_links)} davon neu zu prüfen."
        )

        if not unseen_links:
            log.log("Keine neuen Inserate. Fertig.")

        for i, link in enumerate(unseen_links, 1):
            if stop_event and stop_event.is_set():
                log.log("Abgebrochen.")
                break
            log.log(f"[{i}/{len(unseen_links)}] → {link}")
            try:
                log.log(f"[{i}/{len(unseen_links)}] Lade Detailseite …")
                detail_text = listing_page_text(link)
                log.log(f"[{i}/{len(unseen_links)}] Frage Copilot …")
                result = evaluate_listing_with_gemini(
                    copilot_model=copilot_model,
                    site=site,
                    listing_url=link,
                    listing_text=detail_text,
                    line_callback=lambda line, _i=i, _n=len(unseen_links): (
                        log.log(f"[{_i}/{_n}]   copilot \u25b8 {line}") if line.strip() else None
                    ),
                    stop_event=stop_event,
                )

                processed_urls.append(link)
                state.seen_urls.add(link)

                verdict = "✅ PASSEND" if result.is_relevant else "❌ nicht passend"
                log.log(f"[{i}/{len(unseen_links)}] {verdict}: {result.title}")
                if result.is_relevant:
                    relevant.append(to_listing(site=site, url=link, result=result))

            except (WebFetchError, GeminiError) as listing_err:
                processed_urls.append(link)
                state.seen_urls.add(link)
                log.warn(f"Listing übersprungen: {listing_err}")
            except Exception as listing_err:
                processed_urls.append(link)
                state.seen_urls.add(link)
                log.warn(f"Unerwarteter Fehler: {listing_err}")

        save_seen_state(seen_file, state)
        log.log(
            f"✔ Abgeschlossen – {len(processed_urls)} geprüft, {len(relevant)} passend."
        )

        return AgentResult(
            site=site,
            processed_urls=processed_urls,
            relevant_listings=relevant,
            started_at=started,
            finished_at=datetime.now(),
        )

    except Exception as exc:
        save_seen_state(seen_file, state)
        log.error(f"Agentfehler: {exc}")
        return AgentResult(
            site=site,
            processed_urls=processed_urls,
            relevant_listings=relevant,
            started_at=started,
            finished_at=datetime.now(),
            error=f"{exc}\n{traceback.format_exc()}",
        )


def reset_seen_state(project_root: Path, sites: list[str]) -> None:
    """Delete all per-agent seen-state files so the next run starts from scratch."""
    seen_dir = project_root / "data" / "seen"
    deleted = 0
    for site in sites:
        path = state_file_for_site(seen_dir, site)
        if path.exists():
            path.unlink()
            deleted += 1
            print(f"  Gelöscht: {path.name}")
    print(f"Reset abgeschlossen: {deleted} Datei(en) gelöscht.")


def launch_tmux(sites: list[str], project_root: Path, extra_args: list[str]) -> int:
    """Open a tmux session with one pane per agent so you can watch them live."""
    python_exe = sys.executable
    session = "whg_agent"

    subprocess.run(["tmux", "kill-session", "-t", session], capture_output=True)

    extra = " ".join(extra_args)
    cmds = [
        (
            f"cd {project_root} && "
            f"{python_exe} -m whg_agent.main --site '{site}' {extra}; "
            "echo ''; echo '--- Agent fertig. Strg+C zum Schließen ---'; "
            "read _"
        )
        for site in sites
    ]

    subprocess.run(
        ["tmux", "new-session", "-d", "-s", session, "-x", "220", "-y", "50"],
        check=True,
    )
    subprocess.run(
        ["tmux", "send-keys", "-t", f"{session}:0.0", cmds[0], "Enter"],
        check=True,
    )
    for cmd in cmds[1:]:
        subprocess.run(["tmux", "split-window", "-t", f"{session}:0", "-h"], check=True)
        subprocess.run(["tmux", "send-keys", "-t", f"{session}:0", cmd, "Enter"], check=True)

    subprocess.run(["tmux", "select-layout", "-t", f"{session}:0", "tiled"], check=True)

    print(
        f"tmux-Session '{session}' gestartet mit {len(sites)} Pane(s).\n"
        "Strg+B, D  → Session verlassen (Agenten laufen weiter im Hintergrund)\n"
        "tmux attach -t whg_agent  → wieder anhängen\n"
        "\nHINWEIS: Im tmux-Modus wird KEIN E-Mail gesendet und KEINE HTML-Datei erzeugt.\n"
        "Führe danach 'python -m whg_agent.main --file' aus, um den Bericht zu erstellen."
    )

    os.execlp("tmux", "tmux", "attach-session", "-t", session)
    return 0  # unreachable


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m whg_agent.main",
        description="Wohnungsagent – sucht parallel nach passenden Mietwohnungen in Innsbruck.",
    )
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--email",
        action="store_true",
        default=False,
        help="Ergebnisse per E-Mail senden (Standard, wenn --file nicht gesetzt).",
    )
    output_group.add_argument(
        "--file",
        metavar="PATH",
        nargs="?",
        const="output/results.html",
        default=None,
        help="Ergebnisse als HTML-Datei mit klickbaren Links speichern (Standard: output/results.html).",
    )
    parser.add_argument(
        "--render",
        action="store_true",
        default=False,
        help="HTML/E-Mail aus den zuletzt gespeicherten Ergebnissen neu erstellen, ohne Agenten zu starten.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="E-Mail nicht wirklich senden – Inhalt nur auf der Konsole ausgeben.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        default=False,
        help="Alle Seen-State-Dateien löschen (Suche von vorn starten) und beenden.",
    )
    parser.add_argument(
        "--site",
        metavar="URL",
        default=None,
        help="Nur einen einzelnen Agenten für diese URL ausführen (intern für --tmux).",
    )
    parser.add_argument(
        "--tmux",
        action="store_true",
        default=False,
        help="Jeden Agenten in einem eigenen tmux-Pane starten und live beobachten.",
    )
    return parser.parse_args()


def run() -> int:
    args = _parse_args()
    project_root = Path(__file__).resolve().parents[1]
    config = load_config(project_root)

    # --reset: wipe seen state and exit
    if args.reset:
        reset_seen_state(project_root, config.sites)
        return 0

    if not config.sites:
        print("Keine Websites konfiguriert (sites.json ist leer).")
        return 1

    use_file_output = args.file is not None
    dry_run = args.dry_run or config.dry_run

    # --render: skip agents, load last saved results
    if args.render:
        try:
            all_relevant = _load_results_json(project_root)
        except FileNotFoundError as exc:
            print(f"❌ {exc}")
            return 1
        print(f"✔ {len(all_relevant)} Ergebnis(se) aus gespeicherter JSON geladen.")
        html_report = build_html_report(all_relevant, sites=config.sites)
        fallback_path = project_root / (args.file if use_file_output else "output/results.html")
        write_html_report(all_relevant, fallback_path, prebuilt_html=html_report)
        print(f"✔ HTML-Bericht gespeichert: {fallback_path}")
        if not use_file_output:
            send_result_email(config.mail, all_relevant, html_body=html_report, dry_run=dry_run)
            print(f"✔ E-Mail gesendet an {config.mail.recipient}.")
        return 0

    # --tmux: each agent gets its own terminal pane
    if args.tmux:
        extra: list[str] = []
        if use_file_output:
            extra += ["--file", args.file or "output/results.html"]
        if dry_run:
            extra += ["--dry-run"]
        try:
            return launch_tmux(config.sites, project_root, extra)
        except FileNotFoundError:
            print("❌ tmux nicht gefunden. Bitte installieren: sudo apt install tmux")
            return 1
        except Exception as exc:
            print(f"❌ tmux-Fehler: {exc}")
            return 1

    # --site: run a single agent (called by each tmux pane)
    sites_to_run = [args.site] if args.site else config.sites
    all_relevant: list[Listing] = []
    stop_event = threading.Event()

    if len(sites_to_run) == 1:
        log = AgentLogger(sites_to_run[0])
        try:
            result = run_agent_for_site(
                sites_to_run[0], project_root, config.copilot_model, log, stop_event
            )
        except KeyboardInterrupt:
            print("\n⛔ Abbruch durch Ctrl+C.")
            stop_event.set()
            return 130
        all_relevant = result.relevant_listings
        if result.error:
            print(result.error)
    else:
        print(f"Starte {len(sites_to_run)} Agenten parallel …")
        print("  Strg+C zum Abbrechen.")
        max_workers = min(16, max(1, len(sites_to_run)))
        executor = ThreadPoolExecutor(max_workers=max_workers)
        future_map = {
            executor.submit(
                run_agent_for_site,
                site,
                project_root,
                config.copilot_model,
                AgentLogger(site),
                stop_event,
            ): site
            for site in sites_to_run
        }
        try:
            for future in as_completed(future_map):
                result = future.result()
                if result.error:
                    with _PRINT_LOCK:
                        print(f"[FEHLER] {result.site}:\n{result.error}")
                all_relevant.extend(result.relevant_listings)
        except KeyboardInterrupt:
            print("\n⛔ Abbruch durch Ctrl+C – warte auf laufende Threads …")
            stop_event.set()
            executor.shutdown(wait=True, cancel_futures=True)
            print("Alle Threads beendet.")
            return 130  # standard SIGINT exit code
        finally:
            executor.shutdown(wait=False)

    # Always build the HTML report
    html_report = ""
    try:
        html_report = build_html_report(all_relevant, sites=config.sites)
    except Exception:
        pass  # HTML build failure should not block further steps

    # Save raw results to JSON for later re-rendering
    try:
        json_path = _save_results_json(all_relevant, project_root)
        print(f"\n✔ Ergebnisse als JSON gespeichert: {json_path}")
    except Exception as exc:
        print(f"⚠️  JSON-Speicherung fehlgeschlagen: {exc}")

    # Always save the HTML file first, regardless of --email or --file
    fallback_path = project_root / (args.file if use_file_output else "output/results.html")
    write_html_report(all_relevant, fallback_path, prebuilt_html=html_report)
    print(
        f"\n✔ HTML-Bericht gespeichert: {fallback_path}"
    )

    if use_file_output:
        print(
            f"✔ Fertig. {len(all_relevant)} passende neue Listing(s)."
        )
    else:
        try:
            send_result_email(config.mail, all_relevant, html_body=html_report, dry_run=dry_run)
            print(
                f"✔ Fertig. {len(all_relevant)} passende neue Listing(s). "
                f"E-Mail gesendet an {config.mail.recipient}."
            )
        except Exception as mail_exc:
            print(f"⚠️  E-Mail konnte nicht gesendet werden: {mail_exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
