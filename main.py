"""
Agentes de IA en la Nube — Deportes. Backend FastAPI.

Cobertura actual: baloncesto (NBA), hockey (NHL) y fútbol (principales ligas
+ Champions League + Mundial + Brasileirão), con datos reales desde APIs
públicas: ESPN para NBA y la API oficial de la NHL (ambas sin API key), y
football-data.org para fútbol (requiere una API key gratuita del usuario,
ver FOOTBALL_DATA_API_KEY en .env). La capa de "agente" (nba_agent.py /
nhl_agent.py / football_agent.py) es una heurística estadística con la
misma forma de salida (headline + bullets + rating + probability) que
tendría un agente basado en Vertex AI / Gemini, para poder conectarla más
adelante sin tocar el resto de la app. Tenis y tenis de mesa quedan
pendientes: no existe hoy una fuente gratuita y confiable con datos por
jugador para esos deportes.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

import football_agent
import football_client
import nba_agent
import nba_client
import nhl_agent
import nhl_client
from agent_common import win_probability

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Agentes de IA en la Nube — Deportes")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/")
async def index():
    return FileResponse(BASE_DIR / "templates" / "index.html")


def _parse_record(record: str) -> float | None:
    parts = record.split("-") if record else []
    if len(parts) < 2:
        return None
    try:
        wins = float(parts[0])
        losses = float(parts[1])
    except ValueError:
        return None
    total = wins + losses
    return wins / total if total else None


# ---------------------------------------------------------------------------
# NBA
# ---------------------------------------------------------------------------


@app.get("/api/nba/search")
async def nba_search(q: str = Query(..., min_length=2)):
    return {"results": await nba_client.search_players(q)}


@app.get("/api/nba/player/{player_id}")
async def nba_profile(player_id: str):
    try:
        bio = await nba_client.athlete_bio(player_id)
        overview = await nba_client.athlete_overview(player_id)
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=404, detail="Jugador no encontrado")
    season = nba_client.season_averages(overview)
    team = bio.get("team") or {}
    return {
        "id": bio.get("id"),
        "fullName": bio.get("displayName"),
        "position": (bio.get("position") or {}).get("displayName"),
        "team": {"name": team.get("displayName"), "abbreviation": team.get("abbreviation")},
        "age": bio.get("age"),
        "height": bio.get("displayHeight"),
        "weight": bio.get("displayWeight"),
        "headshot": (bio.get("headshot") or {}).get("href"),
        "jersey": bio.get("jersey"),
        "seasonStats": season,
    }


@app.get("/api/nba/player/{player_id}/gamelog")
async def nba_gamelog(player_id: str, limit: int = 12):
    games = await nba_client.athlete_gamelog(player_id, limit=limit)
    return {"games": games}


@app.get("/api/nba/player/{player_id}/insight")
async def nba_insight(player_id: str):
    profile = await nba_profile(player_id)
    bio = {"displayName": profile["fullName"]}
    gamelog = await nba_gamelog(player_id, limit=10)
    insight = nba_agent.analyze_player(bio, profile["seasonStats"], gamelog["games"])
    return {"playerId": player_id, "generatedAt": datetime.utcnow().isoformat() + "Z", **insight}


@app.get("/api/nba/player/{player_id}/prop-lines")
async def nba_prop_lines(player_id: str):
    profile = await nba_profile(player_id)
    lines = nba_agent.generate_prop_lines(profile["seasonStats"])
    return {"playerId": player_id, "lines": lines}


@app.get("/api/nba/live")
async def nba_live():
    games = await nba_client.scoreboard()
    for g in games:
        home_pct = _parse_record(g["home"]["record"])
        away_pct = _parse_record(g["away"]["record"])
        if home_pct is not None and away_pct is not None:
            g["winProbability"] = win_probability(home_pct, away_pct)
        else:
            g["winProbability"] = None
    return {"games": games}


@app.get("/api/nba/game/{game_id}/roster")
async def nba_roster(game_id: str):
    return await nba_client.game_boxscore(game_id)


# ---------------------------------------------------------------------------
# NHL
# ---------------------------------------------------------------------------


@app.get("/api/nhl/search")
async def nhl_search(q: str = Query(..., min_length=2)):
    return {"results": await nhl_client.search_players(q)}


def _nhl_season_stats(landing: dict) -> dict:
    featured = landing.get("featuredStats") or {}
    return (featured.get("regularSeason") or {}).get("subSeason") or {}


@app.get("/api/nhl/player/{player_id}")
async def nhl_profile(player_id: str):
    try:
        landing = await nhl_client.player_landing(player_id)
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=404, detail="Jugador no encontrado")
    full_name = f"{(landing.get('firstName') or {}).get('default', '')} {(landing.get('lastName') or {}).get('default', '')}".strip()
    return {
        "id": landing.get("playerId"),
        "fullName": full_name,
        "position": landing.get("position"),
        "team": {
            "name": (landing.get("fullTeamName") or {}).get("default"),
            "abbreviation": landing.get("currentTeamAbbrev"),
        },
        "sweaterNumber": landing.get("sweaterNumber"),
        "headshot": landing.get("headshot"),
        "shootsCatches": landing.get("shootsCatches"),
        "birthDate": landing.get("birthDate"),
        "isGoalie": nhl_agent.is_goalie(landing),
        "seasonStats": _nhl_season_stats(landing),
    }


@app.get("/api/nhl/player/{player_id}/gamelog")
async def nhl_gamelog(player_id: str, limit: int = 12):
    games = await nhl_client.player_gamelog(player_id, limit=limit)
    return {"games": games}


@app.get("/api/nhl/player/{player_id}/insight")
async def nhl_insight(player_id: str):
    profile = await nhl_profile(player_id)
    bio = {"fullName": profile["fullName"], "position": profile["position"]}
    gamelog = await nhl_gamelog(player_id, limit=10)
    if profile["isGoalie"]:
        insight = nhl_agent.analyze_goalie(bio, profile["seasonStats"], gamelog["games"])
    else:
        insight = nhl_agent.analyze_skater(bio, profile["seasonStats"], gamelog["games"])
    return {"playerId": player_id, "generatedAt": datetime.utcnow().isoformat() + "Z", **insight}


@app.get("/api/nhl/player/{player_id}/prop-lines")
async def nhl_prop_lines(player_id: str):
    profile = await nhl_profile(player_id)
    if profile["isGoalie"]:
        gamelog = await nhl_gamelog(player_id, limit=10)
        lines = nhl_agent.generate_goalie_prop_lines(profile["seasonStats"], gamelog["games"])
    else:
        lines = nhl_agent.generate_skater_prop_lines(profile["seasonStats"])
    return {"playerId": player_id, "lines": lines}


@app.get("/api/nhl/live")
async def nhl_live():
    games = await nhl_client.scoreboard()
    for g in games:
        home_pct = await nhl_client.team_point_pct(g["home"]["abbreviation"])
        away_pct = await nhl_client.team_point_pct(g["away"]["abbreviation"])
        if home_pct is not None and away_pct is not None:
            g["winProbability"] = win_probability(home_pct, away_pct)
        else:
            g["winProbability"] = None
    return {"games": games}


@app.get("/api/nhl/game/{game_id}/roster")
async def nhl_roster(game_id: str):
    return await nhl_client.game_boxscore(game_id)


# ---------------------------------------------------------------------------
# Fútbol
# ---------------------------------------------------------------------------


@app.get("/api/football/search")
async def football_search(q: str = Query(..., min_length=2)):
    return {"results": await football_client.search_players(q)}


@app.get("/api/football/player/{player_id}")
async def football_profile(player_id: int):
    player = await football_client.find_player(player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Jugador no encontrado")
    stats = player.get("stats", {})
    person = stats.get("player", {})
    team = stats.get("team", {})
    return {
        "id": player["id"],
        "fullName": player["fullName"],
        "position": player["position"],
        "nationality": person.get("nationality"),
        "birthDate": person.get("dateOfBirth"),
        "team": {"name": team.get("name")},
        "competition": player["competition"],
        "seasonStats": {
            "goals": stats.get("goals"),
            "assists": stats.get("assists"),
            "penalties": stats.get("penalties"),
            "playedMatches": stats.get("playedMatches"),
        },
    }


@app.get("/api/football/player/{player_id}/insight")
async def football_insight(player_id: int):
    player = await football_client.find_player(player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Jugador no encontrado")
    insight = football_agent.analyze_player(player)
    return {"playerId": player_id, "generatedAt": datetime.utcnow().isoformat() + "Z", **insight}


@app.get("/api/football/player/{player_id}/prop-lines")
async def football_prop_lines(player_id: int):
    player = await football_client.find_player(player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Jugador no encontrado")
    lines = football_agent.generate_prop_lines(player.get("stats", {}))
    return {"playerId": player_id, "lines": lines}


@app.get("/api/football/live")
async def football_live():
    today = datetime.utcnow().date()
    games = await football_client.scoreboard(
        (today - timedelta(days=1)).isoformat(), (today + timedelta(days=1)).isoformat()
    )
    for g in games:
        home_pct = await football_client.team_point_pct(g["competitionCode"], g["home"]["id"])
        away_pct = await football_client.team_point_pct(g["competitionCode"], g["away"]["id"])
        if home_pct is not None and away_pct is not None:
            g["winProbability"] = win_probability(home_pct, away_pct)
        else:
            g["winProbability"] = None
    return {"games": games}


@app.get("/api/football/match/{match_id}/preview")
async def football_match_preview(match_id: int):
    try:
        match = await football_client.match_detail(match_id)
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=404, detail="Partido no encontrado")

    code = (match.get("competition") or {}).get("code")
    home = match.get("homeTeam") or {}
    away = match.get("awayTeam") or {}
    home_name = home.get("shortName") or home.get("name")
    away_name = away.get("shortName") or away.get("name")

    home_row, home_group = await football_client.team_standing_row(code, home.get("id"))
    away_row, away_group = await football_client.team_standing_row(code, away.get("id"))

    win_prob = None
    if home_row and away_row:
        home_played = home_row.get("playedGames") or 0
        away_played = away_row.get("playedGames") or 0
        if home_played and away_played:
            home_pct = (home_row.get("points") or 0) / (home_played * 3)
            away_pct = (away_row.get("points") or 0) / (away_played * 3)
            win_prob = win_probability(home_pct, away_pct)

    preview = football_agent.preview_match(home_name, away_name, home_row, away_row, home_group, away_group, win_prob)

    return {
        "competition": (match.get("competition") or {}).get("name"),
        "status": match.get("status"),
        "date": match.get("utcDate"),
        "home": {"name": home_name, "crest": home.get("crest"), "standing": home_row},
        "away": {"name": away_name, "crest": away.get("crest"), "standing": away_row},
        **preview,
    }


@app.on_event("shutdown")
async def shutdown():
    await nba_client.close_client()
    await nhl_client.close_client()
    await football_client.close_client()
