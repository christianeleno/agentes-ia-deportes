"""
Cliente de datos de fútbol vía football-data.org (API v4).

Requiere una API key gratuita del usuario (variable de entorno
FOOTBALL_DATA_API_KEY, cargada desde .env). El plan gratuito de
football-data.org es limitado (10 llamadas/minuto) y NO incluye planteles
de equipos ni eventos de partido (goles minuto a minuto, alineaciones), así
que a diferencia de nba_client/nhl_client no hay roster de partido ni
registro de partidos por jugador: el "perfil" del jugador se arma con la
lista de goleadores de cada competencia (la única fuente de estadísticas
por jugador disponible en este plan).

Nota de temporada: las ligas europeas (Premier League, La Liga, Serie A,
Bundesliga, Ligue 1) están en receso en julio, así que su lista de
goleadores puede aparecer vacía hasta que arranque la temporada siguiente.
Mientras tanto, Champions League, Mundial y Brasileirão sí suelen tener
datos en esa fecha.
"""
from __future__ import annotations

import os
import time

import httpx

BASE_URL = "https://api.football-data.org/v4"

# "Ligas top" + variedad global, tal como se le prometió al usuario.
COMPETITIONS = ["PL", "PD", "SA", "BL1", "FL1", "CL", "WC", "BSA"]

_client: httpx.AsyncClient | None = None


def _token() -> str:
    token = os.environ.get("FOOTBALL_DATA_API_KEY", "")
    if not token:
        raise RuntimeError(
            "Falta FOOTBALL_DATA_API_KEY. Configúrala en el archivo .env de deportes-ia-app."
        )
    return token


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=12.0, headers={"X-Auth-Token": _token()})
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def _get(path: str, **params) -> dict:
    resp = await client().get(f"{BASE_URL}{path}", params=params)
    resp.raise_for_status()
    return resp.json()


# --- Índice de jugadores (goleadores de cada competencia) ------------------

_player_index: list[dict] = []
_player_index_at = 0.0
_INDEX_TTL = 3 * 3600

_standings_cache: dict[str, list[dict]] = {}
_standings_at: dict[str, float] = {}
_STANDINGS_TTL = 3600


async def _competition_scorers(code: str) -> list[dict]:
    try:
        data = await _get(f"/competitions/{code}/scorers", limit=100)
    except httpx.HTTPStatusError:
        return []
    return data.get("scorers", [])


_SECTION_ES = {
    "Offence": "Delantero",
    "Midfield": "Mediocampista",
    "Defence": "Defensa",
    "Goalkeeper": "Portero",
}


def _position_label(player: dict) -> str:
    position = player.get("position")
    if position:
        return position
    section = player.get("section")
    return _SECTION_ES.get(section, section or "?")


async def _build_player_index() -> list[dict]:
    index: list[dict] = []
    for code in COMPETITIONS:
        for s in await _competition_scorers(code):
            player = s.get("player", {})
            team = s.get("team", {})
            index.append(
                {
                    "id": player.get("id"),
                    "fullName": player.get("name"),
                    "position": _position_label(player),
                    "team": team.get("name"),
                    "competition": code,
                    "stats": s,
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


async def find_player(player_id: int) -> dict | None:
    for p in await player_index():
        if p["id"] == player_id:
            return p
    return None


# --- Standings (para probabilidad de victoria) ------------------------------


async def competition_standings(code: str) -> list[dict]:
    now = time.time()
    if code not in _standings_cache or (now - _standings_at.get(code, 0)) > _STANDINGS_TTL:
        try:
            data = await _get(f"/competitions/{code}/standings")
        except httpx.HTTPStatusError:
            _standings_cache[code] = []
            _standings_at[code] = now
            return []
        table = []
        for group in data.get("standings", []):
            if group.get("type") == "TOTAL":
                table = group.get("table", [])
                break
        _standings_cache[code] = table
        _standings_at[code] = now
    return _standings_cache[code]


async def team_point_pct(code: str, team_id: int) -> float | None:
    for row in await competition_standings(code):
        if row.get("team", {}).get("id") == team_id:
            played = row.get("playedGames") or 0
            points = row.get("points") or 0
            return points / (played * 3) if played else None
    return None


# --- Marcador en vivo --------------------------------------------------------


async def scoreboard(date_from: str, date_to: str) -> list[dict]:
    data = await _get(
        "/matches",
        competitions=",".join(COMPETITIONS),
        dateFrom=date_from,
        dateTo=date_to,
    )
    matches = data.get("matches", [])
    games = []
    for m in matches:
        score = m.get("score", {}).get("fullTime", {})
        games.append(
            {
                "id": m.get("id"),
                "competition": (m.get("competition") or {}).get("name"),
                "competitionCode": (m.get("competition") or {}).get("code"),
                "date": m.get("utcDate"),
                "status": m.get("status"),
                "matchday": m.get("matchday"),
                "stage": m.get("stage"),
                "home": {
                    "id": (m.get("homeTeam") or {}).get("id"),
                    "name": (m.get("homeTeam") or {}).get("shortName") or (m.get("homeTeam") or {}).get("name"),
                    "score": score.get("home"),
                },
                "away": {
                    "id": (m.get("awayTeam") or {}).get("id"),
                    "name": (m.get("awayTeam") or {}).get("shortName") or (m.get("awayTeam") or {}).get("name"),
                    "score": score.get("away"),
                },
            }
        )
    return games
