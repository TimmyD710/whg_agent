# WHG Agent (Python)

Multi-Agent-Wohnungssuche für Innsbruck mit paralleler Ausführung.

## Was das Programm macht

- Startet **pro Website einen Agenten parallel**.
- Jeder Agent bekommt die **gleichen Kriterien (deutscher Prompt)**.
- Jeder Agent verarbeitet nur seine **eigene Website**.
- Jeder Agent speichert separat, welche Inserate bereits geprüft wurden (`data/seen/*.json`).
- Bei späteren Läufen werden nur **neue, bisher nicht geprüfte Inserate** geöffnet.
- Die Agenten öffnen und prüfen **Detailseiten einzelner Inserate**, nicht nur Übersichtsseiten.
- Nach Abschluss wird eine E-Mail an `timmydueren@gmail.com` gesendet (oder in `DRY_RUN` nur ausgegeben).

## Kriterien (im Agenten-Prompt, Deutsch)

- Nur Wohnungen in Innsbruck.
- 2 oder 3 Zimmer.
- Unter 1300 € Miete / Monat.
- Balkon oder Garten.
- Mindestens 45 m².

## Setup

1. Abhängigkeiten installieren:
   - `python -m venv .venv`
   - `source .venv/bin/activate`
   - `pip install -r requirements.txt`
2. `.env.example` nach `.env` kopieren und Werte eintragen.
3. `sites.json` anpassen (variable Länge möglich).
4. Sicherstellen, dass `gh` CLI im PATH verfügbar und eingeloggt ist (`gh auth login`).

## Start

- `python -m whg_agent.main`

## Datenablage

- Pro Website wird ein eigener Seen-State gespeichert in:
  - `data/seen/<site-slug>.json`

Dadurch werden beim nächsten Lauf nur neue Inserate geprüft.

## Hinweis zu Robustheit

Die Webseiten können ihr HTML ändern oder Bot-Schutz aktivieren. Die Link-Erkennung ist generisch gehalten, kann aber je Website bei Bedarf nachgeschärft werden.
