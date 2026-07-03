"""
Cliente de datos de tenis (ATP / WTA) vía la misma API no-oficial de ESPN
que usa nba_client.py (sin API key).

A diferencia de básquetbol, el endpoint de estadísticas por jugador de
ESPN para tenis viene vacío (probado en vivo: ni temporada, ni ranking, ni
registro de partidos) — solo el marcador de torneos funciona de verdad.
Por eso este cliente NO expone búsqueda de jugador ni perfil: únicamente
el marcador de partidos de los torneos ATP/WTA en curso.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

SITE_API = "https://site.api.espn.com/apis/site/v2/sports/tennis"
TOURS = ["atp", "wta"]
SINGLES_GROUPINGS = {"Men's Singles", "Women's Singles"}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
}

_client: httpx.AsyncClient | None = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=12.0, headers=HEADERS)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def _tour_scoreboard(tour: str) -> dict:
    resp = await client().get(f"{SITE_API}/{tour}/scoreboard")
    resp.raise_for_status()
    return resp.json()


def _competitor_summary(c: dict) -> dict:
    athlete = c.get("athlete", {})
    return {
        "id": c.get("id"),
        "name": athlete.get("displayName"),
        "country": (athlete.get("flag") or {}).get("alt"),
        "sets": [ls.get("value") for ls in c.get("linescores", [])],
        "winner": c.get("winner", False),
    }


async def scoreboard() -> list[dict]:
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=1)
    window_end = now + timedelta(days=2)

    matches: list[dict] = []
    for tour in TOURS:
        try:
            data = await _tour_scoreboard(tour)
        except httpx.HTTPError:
            continue
        for ev in data.get("events", []):
            tournament = ev.get("shortName") or ev.get("name")
            for g in ev.get("groupings", []):
                grouping_name = (g.get("grouping") or {}).get("displayName")
                if grouping_name not in SINGLES_GROUPINGS:
                    continue
                for comp in g.get("competitions", []):
                    date_str = comp.get("date")
                    try:
                        comp_date = datetime.fromisoformat((date_str or "").replace("Z", "+00:00"))
                    except ValueError:
                        comp_date = None
                    status = comp.get("status", {}).get("type", {})
                    is_live = status.get("state") == "in"
                    if comp_date and not is_live and not (window_start <= comp_date <= window_end):
                        continue

                    competitors = comp.get("competitors", [])
                    if len(competitors) != 2:
                        continue
                    home = next((c for c in competitors if c.get("order") == 1), competitors[0])
                    away = next((c for c in competitors if c.get("order") == 2), competitors[-1])

                    matches.append(
                        {
                            "id": comp.get("id"),
                            "tour": tour.upper(),
                            "tournament": tournament,
                            "round": grouping_name,
                            "date": date_str,
                            "state": status.get("state"),
                            "detail": status.get("shortDetail") or status.get("detail"),
                            "home": _competitor_summary(home),
                            "away": _competitor_summary(away),
                        }
                    )

    matches.sort(key=lambda m: (m["state"] != "in", m["date"] or ""))
    return matches[:40]
