"""
Agente de análisis para fútbol.

A diferencia de nba_agent/nhl_agent, football-data.org (plan gratuito) no
entrega un registro de partidos por jugador, así que este agente no puede
hablar de "racha reciente": trabaja solo con el acumulado de la temporada
(goles, asistencias, partidos jugados) que da el endpoint de goleadores.
"""
from __future__ import annotations

from agent_common import clamp, prop_row, semaphore_level, to_float


def estimate_player_probability(stats: dict) -> dict:
    played = to_float(stats.get("playedMatches"))
    goals = to_float(stats.get("goals"))
    gpm = goals / played if played else 0

    pct = round(clamp((gpm / 0.75) * 100, 5, 95))
    return {
        "pct": pct,
        "level": semaphore_level(pct),
        "label": "Probabilidad de marcar gol en su próximo partido",
    }


def generate_prop_lines(stats: dict) -> list[dict]:
    played = to_float(stats.get("playedMatches"))
    if not played:
        return []
    goals = to_float(stats.get("goals")) / played
    assists = to_float(stats.get("assists")) / played
    involvement = goals + assists

    rows = [prop_row("Fútbol", "Total de goles", goals)]
    if assists > 0:
        rows.append(prop_row("Fútbol", "Total de asistencias", assists))
    rows.append(prop_row("Fútbol", "Total de goles + asistencias", involvement))
    return rows


def analyze_player(player: dict) -> dict:
    name = player.get("fullName", "El jugador")
    stats = player.get("stats", {})
    team = (stats.get("team") or {}).get("name") or player.get("team")
    played = to_float(stats.get("playedMatches"))
    goals = to_float(stats.get("goals"))
    assists = to_float(stats.get("assists"))
    gpm = goals / played if played else 0

    bullets = []
    if not played:
        headline = f"No hay estadísticas de la temporada actual para {name} todavía."
        rating = "neutral"
    else:
        if gpm >= 0.7:
            rating = "caliente"
            headline = f"{name} es uno de los goleadores destacados de {player.get('competition')}: {goals:.0f} goles en {played:.0f} partidos con {team}."
        elif gpm <= 0.25:
            rating = "frio"
            headline = f"{name} tiene un ritmo goleador bajo esta temporada: {goals:.0f} goles en {played:.0f} partidos con {team}."
        else:
            rating = "neutral"
            headline = f"{name} mantiene un ritmo goleador parejo esta temporada: {goals:.0f} goles en {played:.0f} partidos con {team}."

        bullets.append(f"Temporada: {goals:.0f} goles y {assists:.0f} asistencias en {played:.0f} partidos jugados.")
        bullets.append(f"Promedio de {gpm:.2f} goles por partido.")
        penalties = stats.get("penalties")
        if penalties:
            bullets.append(f"Incluye {penalties} gol(es) de penal.")

    bullets.append(
        "football-data.org (plan gratuito) no entrega el registro partido a partido de cada jugador, "
        "así que este análisis se basa en el acumulado de la temporada, no en su forma reciente."
    )

    return {
        "headline": headline,
        "rating": rating,
        "bullets": bullets,
        "probability": estimate_player_probability(stats),
        "keyStats": {
            "goals": stats.get("goals"),
            "assists": stats.get("assists"),
            "penalties": stats.get("penalties"),
            "playedMatches": stats.get("playedMatches"),
        },
    }
