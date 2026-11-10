"""
Cliente de datos de la NBA.

Usa la API pública (no documentada oficialmente, pero de acceso libre y sin
API key) que ESPN expone para su propio sitio web (site.api.espn.com /
site.web.api.espn.com). Se probó en vivo que las APIs de stats.nba.com y
cdn.nba.com bloquean el trafico saliente de servidores en la nube (Akamai
bot-protection), por lo que ESPN es la fuente mas confiable para desplegar
en Render sin necesitar credenciales.
"""
from __future__ import annotations

import time

import httpx

from resilience import stale_on_error

SITE_API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
CORE_API = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba"

HEADERS = {
    # OJO: ESPN bloquea con 403 los User-Agent que fingen ser un navegador
    # (Chrome/Mozilla) pero deja pasar clientes que se identifican como lo
    # que son (curl, httpx) — probado en vivo. No agregar un UA de navegador
    # aquí, por contraintuitivo que parezca.
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


async def _get(url: str, **params) -> dict:
    resp = await client().get(url, params=params)
    resp.raise_for_status()
    return resp.json()


# --- Índice de jugadores (para la búsqueda) ------------------------------
# ESPN no expone un endpoint de búsqueda de jugadores por nombre directo y
# confiable, así que se arma un índice en memoria a partir de los planteles
# de los 30 equipos y se refresca cada pocas horas.

_player_index: list[dict] = []
_player_index_at = 0.0
_INDEX_TTL = 6 * 3600


async def _teams() -> list[dict]:
    data = await _get(f"{SITE_API}/teams")
    return data["sports"][0]["leagues"][0]["teams"]


async def _team_roster(team_id: str) -> list[dict]:
    data = await _get(f"{SITE_API}/teams/{team_id}/roster")
    return data.get("athletes", [])


async def _build_player_index() -> list[dict]:
    teams = await _teams()
    index: list[dict] = []
    for t in teams:
        team = t["team"]
        try:
            athletes = await _team_roster(team["id"])
        except httpx.HTTPError:
            continue
        for a in athletes:
            index.append(
                {
                    "id": a["id"],
                    "fullName": a.get("fullName") or a.get("displayName"),
                    "position": (a.get("position") or {}).get("abbreviation", "?"),
                    "team": team.get("displayName"),
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


# --- Perfil, stats, gamelog -----------------------------------------------


async def athlete_bio(player_id: str) -> dict:
    data = await _get(f"{CORE_API}/athletes/{player_id}")
    return data.get("athlete", {})


async def athlete_overview(player_id: str) -> dict:
    return await _get(f"{CORE_API}/athletes/{player_id}/overview")


def season_averages(overview: dict) -> dict:
    stats = overview.get("statistics") or {}
    names = stats.get("names") or []
    splits = stats.get("splits") or []
    if not names or not splits:
        return {}
    values = splits[0].get("stats") or []
    return dict(zip(names, values))


async def athlete_gamelog(player_id: str, limit: int = 12) -> list[dict]:
    data = await _get(f"{CORE_API}/athletes/{player_id}/gamelog")
    names = data.get("names") or []
    events_meta = data.get("events") or {}
    season_types = data.get("seasonTypes") or []

    rows: list[dict] = []
    for st in season_types:
        for cat in st.get("categories", []):
            for ev in cat.get("events", []):
                meta = events_meta.get(ev.get("eventId"), {})
                stat_map = dict(zip(names, ev.get("stats", [])))
                opponent = (meta.get("opponent") or {}).get("displayName")
                rows.append(
                    {
                        "date": (meta.get("gameDate") or "")[:10],
                        "opponent": opponent,
                        "atVs": meta.get("atVs"),
                        "result": meta.get("gameResult"),
                        "score": meta.get("score"),
                        **stat_map,
                    }
                )
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows[:limit]


# --- Marcador en vivo y roster de partido ---------------------------------


@stale_on_error
async def scoreboard() -> list[dict]:
    data = await _get(f"{SITE_API}/scoreboard")
    events = data.get("events", [])
    games = []
    for ev in events:
        comp = (ev.get("competitions") or [{}])[0]
        competitors = comp.get("competitors", [])
        home = next((c for c in competitors if c.get("homeAway") == "home"), {})
        away = next((c for c in competitors if c.get("homeAway") == "away"), {})
        status = (ev.get("status") or {}).get("type", {})
        games.append(
            {
                "id": ev.get("id"),
                "date": ev.get("date"),
                "state": status.get("state"),
                "detail": status.get("shortDetail"),
                "home": _team_summary(home),
                "away": _team_summary(away),
            }
        )
    return games


def _team_summary(competitor: dict) -> dict:
    team = competitor.get("team", {})
    record = ""
    records = competitor.get("records") or []
    if records:
        record = records[0].get("summary", "")
    return {
        "id": team.get("id"),
        "name": team.get("displayName"),
        "abbreviation": team.get("abbreviation"),
        "score": competitor.get("score"),
        "record": record,
        "winner": competitor.get("winner"),
    }


async def game_boxscore(game_id: str) -> dict:
    data = await _get(f"{SITE_API}/summary", event=game_id)
    box = data.get("boxscore", {})
    players_by_team = box.get("players", [])

    result = {
        "preGame": False,
        "away": {"teamName": None, "players": []},
        "home": {"teamName": None, "players": []},
    }
    header_competitors = (data.get("header", {}).get("competitions") or [{}])[0].get("competitors", [])
    side_by_team_id = {c["team"]["id"]: c.get("homeAway") for c in header_competitors}

    for team_block in players_by_team:
        team = team_block.get("team", {})
        side = side_by_team_id.get(team.get("id"), "home")
        stats_block = (team_block.get("statistics") or [{}])[0]
        labels = stats_block.get("names") or stats_block.get("labels") or []
        pts_index = labels.index("points") if "points" in labels else (
            labels.index("PTS") if "PTS" in labels else None
        )
        players = []
        for a in stats_block.get("athletes", []):
            athlete = a.get("athlete", {})
            stat_values = a.get("stats", [])
            pts = None
            if pts_index is not None and pts_index < len(stat_values):
                pts = stat_values[pts_index]
            players.append(
                {
                    "id": athlete.get("id"),
                    "fullName": athlete.get("displayName"),
                    "position": (athlete.get("position") or {}).get("abbreviation", ""),
                    "starter": a.get("starter", False),
                    "points": pts,
                }
            )
        result[side] = {"teamName": team.get("displayName"), "players": players}

    # Antes del salto inicial ESPN todavía no publica la alineación (boxscore.players
    # viene vacío). En ese caso se muestra el plantel de la temporada, con posición
    # y estado de lesión, y se marca preGame para que la interfaz lo explique.
    for c in header_competitors:
        side = c.get("homeAway")
        team = c.get("team", {})
        if side not in ("away", "home"):
            continue
        if not result[side]["teamName"]:
            result[side]["teamName"] = team.get("displayName")
        if result[side]["players"]:
            continue
        try:
            roster = await _team_roster(team.get("id"))
        except httpx.HTTPError:
            continue
        players = []
        for a in roster:
            injuries = a.get("injuries") or []
            players.append(
                {
                    "id": a.get("id"),
                    "fullName": a.get("fullName") or a.get("displayName"),
                    "position": (a.get("position") or {}).get("abbreviation", ""),
                    "starter": None,
                    "points": None,
                    "injury": injuries[0].get("status") if injuries else None,
                }
            )
        players.sort(key=lambda p: p["injury"] is not None)  # sanos primero, lesionados al final
        result[side]["players"] = players
        result["preGame"] = True
    return result


# --- Jugadores destacados (botones de sugerencia) ----------------------------
# Los 5 máximos anotadores actuales, para que los botones de ejemplo de la
# interfaz no queden desactualizados (retiros, traspasos, cambio de temporada).

_featured_cache: tuple[float, list[str]] | None = None
_FEATURED_TTL = 6 * 3600


async def featured_players(limit: int = 5) -> list[str]:
    global _featured_cache
    now = time.time()
    if _featured_cache and (now - _featured_cache[0]) < _FEATURED_TTL:
        return _featured_cache[1]
    data = await _get(f"{CORE_API}/statistics/byathlete", sort="offensive.avgPoints:desc", limit=limit)
    names = [
        a["athlete"]["displayName"]
        for a in data.get("athletes", [])
        if (a.get("athlete") or {}).get("displayName")
    ]
    if names:
        _featured_cache = (now, names)
    return names
