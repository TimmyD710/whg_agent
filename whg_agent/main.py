from __future__ import annotations

import argparse
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from .config import load_config
from .emailer import send_result_email
from .gemini_agent import GeminiError, evaluate_listing_with_gemini, to_listing
from .models import AgentResult, Listing
from .reporter import write_html_report
from .scraper import WebFetchError, extract_listing_links, fetch_html, listing_page_text
from .storage import SeenState, load_seen_state, save_seen_state, state_file_for_site


def run_agent_for_site(site: str, project_root: Path, gemini_cmd: str) -> AgentResult:
    started = datetime.now()
    processed_urls: list[str] = []
    relevant: list[Listing] = []

    seen_file = state_file_for_site(project_root / "data" / "seen", site)
    state = load_seen_state(seen_file)

    try:
        overview_html = fetch_html(site)
        candidate_links = extract_listing_links(site, overview_html)
        unseen_links = [u for u in candidate_links if u not in state.seen_urls]

        for link in unseen_links:
            try:
                detail_text = listing_page_text(link)
                result = evaluate_listing_with_gemini(
                    gemini_cmd=gemini_cmd,
                    site=site,
                    listing_url=link,
                    listing_text=detail_text,
                )

                processed_urls.append(link)
                state.seen_urls.add(link)

                if result.is_relevant:
                    relevant.append(to_listing(site=site, url=link, result=result))
            except (WebFetchError, GeminiError) as listing_err:
                processed_urls.append(link)
                state.seen_urls.add(link)
                print(f"[WARN] Listing übersprungen ({link}): {listing_err}")
            except Exception as listing_err:  # pragma: no cover
                processed_urls.append(link)
                state.seen_urls.add(link)
                print(f"[WARN] Unerwarteter Fehler im Listing ({link}): {listing_err}")

        save_seen_state(seen_file, state)

        return AgentResult(
            site=site,
            processed_urls=processed_urls,
            relevant_listings=relevant,
            started_at=started,
            finished_at=datetime.now(),
        )

    except Exception as exc:
        save_seen_state(seen_file, state)
        return AgentResult(
            site=site,
            processed_urls=processed_urls,
            relevant_listings=relevant,
            started_at=started,
            finished_at=datetime.now(),
            error=f"{exc}\n{traceback.format_exc()}",
        )


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
        help=(
            "Ergebnisse als HTML-Datei mit klickbaren Links speichern statt E-Mail zu senden. "
            "Optionaler Pfad (Standard: output/results.html)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="E-Mail nicht wirklich senden – Inhalt nur auf der Konsole ausgeben.",
    )
    return parser.parse_args()


def run() -> int:
    args = _parse_args()
    project_root = Path(__file__).resolve().parents[1]
    config = load_config(project_root)

    # CLI flags override .env settings
    use_file_output = args.file is not None
    dry_run = args.dry_run or config.dry_run

    if not config.sites:
        print("Keine Websites konfiguriert (sites.json ist leer).")
        return 1

    print(f"Starte {len(config.sites)} Agenten parallel...")

    all_relevant: list[Listing] = []
    results: list[AgentResult] = []

    max_workers = min(16, max(1, len(config.sites)))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
            pool.submit(run_agent_for_site, site, project_root, config.gemini_cmd): site
            for site in config.sites
        }
        for future in as_completed(future_map):
            result = future.result()
            results.append(result)

            status = "OK" if not result.error else "FEHLER"
            print(
                f"[{status}] {result.site} | "
                f"neu geprüft: {len(result.processed_urls)} | "
                f"passend: {len(result.relevant_listings)}"
            )
            if result.error:
                print(result.error)

            all_relevant.extend(result.relevant_listings)

    if use_file_output:
        output_path = project_root / args.file
        write_html_report(all_relevant, output_path)
        print(
            f"Fertig. Gesamt passende neue Listings: {len(all_relevant)}. "
            f"HTML-Bericht gespeichert: {output_path}"
        )
    else:
        send_result_email(config.mail, all_relevant, dry_run=dry_run)
        print(
            f"Fertig. Gesamt passende neue Listings: {len(all_relevant)}. "
            f"E-Mail gesendet an {config.mail.recipient}."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
