from __future__ import annotations

import smtplib
from email.message import EmailMessage

from .config import MailConfig
from .models import Listing


class EmailError(RuntimeError):
    pass


def send_result_email(
    mail: MailConfig,
    listings: list[Listing],
    dry_run: bool = False,
) -> None:
    subject = "Wohnungsagent: Neue passende Inserate"
    body = _build_mail_body(listings)

    if dry_run:
        print("[DRY_RUN] E-Mail Versand übersprungen.")
        print("Betreff:", subject)
        print(body)
        return

    required = [mail.host, str(mail.port), mail.user, mail.password, mail.sender, mail.recipient]
    if not all(required):
        raise EmailError("SMTP-Konfiguration unvollständig. Bitte .env prüfen.")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mail.sender
    msg["To"] = mail.recipient
    msg.set_content(body)

    try:
        with smtplib.SMTP(mail.host, mail.port, timeout=30) as server:
            server.starttls()
            server.login(mail.user, mail.password)
            server.send_message(msg)
    except Exception as exc:  # pragma: no cover - external I/O
        raise EmailError(f"E-Mail konnte nicht gesendet werden: {exc}") from exc


def _build_mail_body(listings: list[Listing]) -> str:
    if not listings:
        return (
            "Hallo Timmy,\n\n"
            "es wurden bei diesem Lauf keine neuen passenden Wohnungen gefunden.\n\n"
            "Viele Grüße\n"
            "Wohnungsagent"
        )

    lines = [
        "Hallo Timmy,",
        "",
        "folgende neue passende Wohnungen wurden gefunden:",
        "",
    ]

    for idx, listing in enumerate(listings, start=1):
        lines.extend(
            [
                f"{idx}. {listing.title}",
                f"   URL: {listing.url}",
                f"   Quelle: {listing.source_site}",
                f"   Miete: {listing.rent_eur if listing.rent_eur is not None else 'unbekannt'} €",
                f"   Zimmer: {listing.rooms if listing.rooms is not None else 'unbekannt'}",
                f"   Fläche: {listing.size_m2 if listing.size_m2 is not None else 'unbekannt'} m²",
                (
                    "   Balkon/Garten: "
                    + (
                        "ja"
                        if listing.has_balcony_or_garden is True
                        else "nein"
                        if listing.has_balcony_or_garden is False
                        else "unbekannt"
                    )
                ),
                f"   Grund: {listing.reason or 'Erfüllt Kriterien laut Agent'}",
                "",
            ]
        )

    lines.extend(["Viele Grüße", "Wohnungsagent"])
    return "\n".join(lines)
