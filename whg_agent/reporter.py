from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .models import Listing


def build_html_report(listings: list[Listing], sites: list[str] | None = None) -> str:
    """Build and return the full HTML report string."""
    generated_at = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    site_index = {url: i + 1 for i, url in enumerate(sites)} if sites else {}

    rows = ""
    if listings:
        for i, listing in enumerate(listings, start=1):
            balcony = (
                "✅" if listing.has_balcony_or_garden is True
                else "❌" if listing.has_balcony_or_garden is False
                else "❓"
            )
            rent = f"{listing.rent_eur:.0f} €" if listing.rent_eur is not None else "–"
            rooms = str(listing.rooms) if listing.rooms is not None else "–"
            size = f"{listing.size_m2:.0f} m²" if listing.size_m2 is not None else "–"
            district = listing.district or "–"
            listed_at = listing.listed_at or "–"

            rows += f"""
            <tr>
                <td><a href="{listing.url}" target="_blank" rel="noopener">{listing.title}</a></td>
                <td>{rent}</td>
                <td>{rooms}</td>
                <td>{size}</td>
                <td class="center">{balcony}</td>
                <td>{district}</td>
                <td>{listed_at}</td>
                <td class="source"><a href="{listing.url}" target="_blank" rel="noopener">Quelle {site_index.get(listing.source_site, i)}</a></td>
            </tr>"""
    else:
        rows = '<tr><td colspan="8" class="center">Keine neuen passenden Wohnungen gefunden.</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Wohnungsagent – Ergebnisse</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #f5f5f5;
      color: #222;
      margin: 0;
      padding: 24px;
    }}
    h1 {{ color: #1a237e; margin-bottom: 4px; }}
    .meta {{ color: #666; font-size: 0.9em; margin-bottom: 24px; }}
    .count {{ font-weight: bold; color: #1a237e; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: #fff;
      box-shadow: 0 1px 4px rgba(0,0,0,.12);
      border-radius: 8px;
      overflow: hidden;
    }}
    thead tr {{ background: #1a237e; color: #fff; }}
    th, td {{ padding: 10px 14px; text-align: left; font-size: 0.9em; }}
    th {{ font-weight: 600; letter-spacing: .03em; }}
    tbody tr:nth-child(even) {{ background: #f9f9ff; }}
    tbody tr:hover {{ background: #e8eaf6; }}
    a {{ color: #1a237e; text-decoration: none; font-weight: 500; }}
    a:hover {{ text-decoration: underline; }}
    .center {{ text-align: center; }}
    .source {{ color: #555; font-size: 0.8em; word-break: break-all; }}
  </style>
</head>
<body>
  <h1>🏠 Wohnungsagent – Ergebnisse</h1>
  <p class="meta">
    Generiert am <strong>{generated_at}</strong> &nbsp;|&nbsp;
    <span class="count">{len(listings)}</span> neue passende Wohnung(en) gefunden
  </p>
  <p>Hallo Timmy,</p>
  <p>folgende neue passende Wohnungen wurden gefunden:</p>
  <table>
    <thead>
      <tr>
        <th>Inserat</th>
        <th>Miete</th>
        <th>Zimmer</th>
        <th>Fläche</th>
        <th>Balkon/Garten</th>
        <th>Bezirk</th>
        <th>Inseriert am</th>
        <th>Quelle</th>
      </tr>
    </thead>
    <tbody>{rows}
    </tbody>
  </table>
  <p>Viele Grüße<br>Wohnungsagent</p>
</body>
</html>
"""


def write_html_report(
    listings: list[Listing],
    output_path: Path,
    prebuilt_html: str = "",
) -> None:
    """Write the HTML report to *output_path*. Uses *prebuilt_html* if provided."""
    html = prebuilt_html or build_html_report(listings)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
