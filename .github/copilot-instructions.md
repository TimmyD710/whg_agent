# Copilot Instructions – WHG Agent

## Projektziel
Dieses Python-Projekt durchsucht mehrere Wohnungs-Webseiten parallel nach neuen passenden Mietwohnungen in Innsbruck.

## Fachliche Regeln
- Nur Innsbruck (keine Umland-Orte).
- 2 oder 3 Zimmer.
- Miete < 1300 EUR/Monat.
- Balkon ODER Garten erforderlich.
- Mindestgröße 45 m².

## Architekturregeln
- Ein Agent pro Website.
- Agenten laufen parallel mit `ThreadPoolExecutor`.
- Jeder Agent hat eine eigene Seen-Liste im Dateisystem (`data/seen/*.json`).
- Bei Folgeläufen dürfen nur neue (unbekannte) Inserate geprüft werden.
- Agenten müssen Detailseiten von Inseraten öffnen und auswerten.
- Webseitenliste ist variabel lang und kommt aus `sites.json`.
- LLM-Auswertung erfolgt über GitHub Copilot API (`ai_agent.py`).

## Code-Stil
- Verwende Python 3.11+ Typannotationen.
- Schreibe kleine, testbare Funktionen.
- Behandle Netzwerk-/CLI-Fehler robust und logge Warnungen, ohne den gesamten Lauf abzubrechen.
- Vermeide Hardcoding von Credentials; nutze `.env`.

## E-Mail-Ausgabe
- Nach jedem Lauf eine E-Mail mit allen neuen passenden Inseraten versenden.
- Empfänger standardmäßig: `timmydueren@gmail.com`.

## Erwartete Dateien
- `whg_agent/main.py`: Orchestrierung und Parallelisierung.
- `whg_agent/scraper.py`: Übersicht + Detailseiten lesen.
- `whg_agent/ai_agent.py`: Prompting und JSON-Auswertung via Copilot API.
- `whg_agent/storage.py`: Persistenz bereits gesehener Inserate.
- `whg_agent/emailer.py`: SMTP-Versand.
- `sites.json`: konfigurierbare Website-Liste.
