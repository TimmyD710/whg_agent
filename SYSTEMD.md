# WHG Agent – systemd Timer Cheatsheet

## Einmalige Einrichtung (nur beim ersten Mal)

```bash
systemctl --user daemon-reload
systemctl --user enable --now whg_agent.timer
```

---

## Start / Stop / Status

| Aktion | Befehl |
|---|---|
| Timer starten | `systemctl --user start whg_agent.timer` |
| Timer stoppen | `systemctl --user stop whg_agent.timer` |
| Timer dauerhaft deaktivieren | `systemctl --user disable whg_agent.timer` |
| Timer wieder aktivieren | `systemctl --user enable --now whg_agent.timer` |
| Status des Timers | `systemctl --user status whg_agent.timer` |
| Nächste Ausführungszeit anzeigen | `systemctl --user list-timers whg_agent.timer` |

> **Hinweis:** `stop` pausiert den Timer nur bis zum nächsten Reboot.
> `disable` schaltet ihn dauerhaft aus (bleibt auch nach Neustart deaktiviert).

---

## Logs

| Aktion | Befehl |
|---|---|
| Letzte Logs anzeigen | `journalctl --user -u whg_agent.service --no-pager -n 50` |
| Logs live verfolgen | `journalctl --user -u whg_agent.service -f` |
| Logs des letzten Laufs | `journalctl --user -u whg_agent.service --no-pager -n 100` |

---

## Einmalig manuell ausführen (ohne auf den Timer zu warten)

```bash
systemctl --user start whg_agent.service
```

---

## Zeitplan ändern

Die Datei `~/.config/systemd/user/whg_agent.timer` bearbeiten:

**Stündlich (zum Testen):**
```ini
OnCalendar=hourly
```

**3× täglich (Produktivbetrieb):**
```ini
OnCalendar=*-*-* 07:00:00
OnCalendar=*-*-* 13:00:00
OnCalendar=*-*-* 19:00:00
```

Nach jeder Änderung der Timer-Datei:
```bash
systemctl --user daemon-reload
systemctl --user restart whg_agent.timer
```

---

## Seen-State zurücksetzen (alle Inserate erneut prüfen)

```bash
cd /home/timmy/Documents/whg_agent
python -m whg_agent.main --reset
```
