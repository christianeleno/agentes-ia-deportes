"""
Cliente de datos de la NHL.

Usa la API pública oficial de la NHL (api-web.nhle.com), gratuita y sin
necesidad de API key. Confirmada en vivo durante el desarrollo de esta app.
"""
from __future__ import annotations

import time

import httpx

WEB_API = "https://api-web.nhle.com/v1"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
}

_client: httpx.AsyncClient | None = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=12.0, headers=HEADERS, follow_redirects=True)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def _get(url: str, **params) -> dict:
    resp = await client().get(url, params=params)
    resp.raise_for_status()
    return resp.json()


# --- Equipos, standings (también usados para la probabilidad de victoria) --

_standings_cache: list[dict] = []
_standings_at = 0.0
_STANDINGS_TTL = 3600


async def standings() -> list[dict]:
    global _standings_cache, _standings_at
    if not _standings_cache or (time.time() - _standings_at) > _STANDINGS_TTL:
        data = await _get(f"{WEB_API}/standings/now")
        _standings_cache = data.get("standings", [])
        _standings_at = time.time()
    return _standings_cache


async def team_point_pct(abbrev: str) -> float | None:
    for team in await standings():
        if (team.get("teamAbbrev") or {}).get("default") == abbrev:
            return team.get("pointPctg")
    return None


# --- Índice de jugadores (para la búsqueda) --------------------------------

_player_index: list[dict] = []
_player_index_at = 0.0
_INDEX_TTL = 6 * 3600


async def _team_abbrevs() -> list[str]:
    return [(t.get("teamAbbrev") or {}).get("default") for t in await standings()]


async def _team_roster(abbrev: str) -> dict:
    return await _get(f"{WEB_API}/roster/{abbrev}/current")


async def _build_player_index() -> list[dict]:
    index: list[dict] = []
    for abbrev in await _team_abbrevs():
        if not abbrev:
            continue
        try:
            roster = await _team_roster(abbrev)
        except httpx.HTTPError:
            continue
        for group, pos_fallback in (("forwards", None), ("defensemen", "D"), ("goalies", "G")):
            for p in roster.get(group, []):
                full_name = f"{(p.get('firstName') or {}).get('default', '')} {(p.get('lastName') or {}).get('default', '')}".strip()
                index.append(
                    {
                        "id": p.get("id"),
                        "fullName": full_name,
                        "position": p.get("positionCode") or pos_fallback or "?",
                        "team": abbrev,
                        "active": True,
                    }
                )
    return index


async def player_index() -> list[dict]:
    global _player_index, _player_index_at
    if not _player_index or (time.time() - _player_index_at) > _INDEX_TTL:
        _player_index = await _build_player_index()
        _player_index_at = time.time()
    return _player_index


async def search_players(query: str) -> list[dict]:
    q = query.strip().lower()
    index = await player_index()
    results = [p for p in index if q in (p["fullName"] or "").lower()]
    results.sort(key=lambda r: r["fullName"] or "")
    return results[:20]


# --- Perfil, stats, gamelog -------------------------------------------------


async def player_landing(player_id: str) -> dict:
    return await _get(f"{WEB_API}/player/{player_id}/landing")


async def player_gamelog(player_id: str, limit: int = 12) -> list[dict]:
    data = await _get(f"{WEB_API}/player/{player_id}/game-log/now")
    games = data.get("gameLog", [])
    return games[:limit]


# --- Marcador en vivo y roster de partido -----------------------------------


async def scoreboard() -> list[dict]:
    data = await _get(f"{WEB_API}/score/now")
    games_raw = data.get("games", [])
    games = []
    for g in games_raw:
        clock = g.get("clock") or {}
        period = g.get("periodDescriptor") or {}
        detail = g.get("gameState")
        if g.get("gameState") in ("LIVE", "CRIT"):
            detail = f"Periodo {period.get('number', '')} · {clock.get('timeRemaining', '')}"
        elif g.get("gameState") in ("OFF", "FINAL"):
            detail = "Final"
        else:
            detail = g.get("startTimeUTC")
        games.append(
            {
                "id": g.get("id"),
                "date": g.get("startTimeUTC"),
                "state": g.get("gameState"),
                "detail": detail,
                "home": _team_summary(g.get("homeTeam", {})),
                "away": _team_summary(g.get("awayTeam", {})),
            }
        )
    return games


def _team_summary(team: dict) -> dict:
    return {
        "id": team.get("id"),
        "name": (team.get("name") or {}).get("default"),
        "abbreviation": team.get("abbrev"),
        "score": team.get("score"),
        "record": "",
        "winner": None,
    }


async def game_boxscore(game_id: str) -> dict:
    data = await _get(f"{WEB_API}/gamecenter/{game_id}/boxscore")
    stats = data.get("playerByGameStats", {})

    def build_side(side: dict, team_meta: dict) -> dict:
        players = []
        for group in ("forwards", "defense", "goalies"):
            for p in side.get(group, []):
                name = (p.get("name") or {}).get("default")
                players.append(
                    {
                        "id": p.get("playerId"),
                        "fullName": name,
                        "position": p.get("position"),
                        "starter": None,
                        "points": p.get("points") if group != "goalies" else p.get("saveShotsAgainst"),
                    }
                )
        return {"teamName": (team_meta.get("name") or {}).get("default"), "players": players}

    return {
        "away": build_side(stats.get("awayTeam", {}), data.get("awayTeam", {})),
        "home": build_side(stats.get("homeTeam", {}), data.get("homeTeam", {})),
    }
