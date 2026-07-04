"""
Agente de análisis para fútbol.

A diferencia de nba_agent/nhl_agent, football-data.org (plan gratuito) no
entrega un registro de partidos por jugador, así que este agente no puede
hablar de "racha reciente": trabaja solo con el acumulado de la temporada
(goles, asistencias, partidos jugados) que da el endpoint de goleadores.
"""
from __future__ import annotations

from agent_common import clamp, prop_row, semaphore_level, to_float

# No hay datos de tiros de esquina ni tarjetas en football-data.org (plan
# gratuito) en ningún endpoint — solo goles. Por eso las líneas de partido
# se limitan a goles.


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


def _team_form_line(name: str, row: dict, group: str | None) -> str:
    played = row.get("playedGames") or 0
    diff = row.get("goalDifference")
    diff_txt = f"{diff:+d}" if isinstance(diff, int) else "—"
    group_txt = f" ({group})" if group else ""
    return (
        f"{name}{group_txt}: {row.get('position')}° lugar, {row.get('points')} pts en {played} PJ "
        f"({row.get('won')}G-{row.get('draw')}E-{row.get('lost')}P), diferencia de gol {diff_txt}."
    )


def preview_match(
    home_name: str,
    away_name: str,
    home_row: dict | None,
    away_row: dict | None,
    home_group: str | None,
    away_group: str | None,
    win_prob: dict | None,
) -> dict:
    """Ficha de prepartido a nivel de equipo: football-data.org (plan gratuito)
    no da alineaciones, así que esto compara la posición y forma en la tabla
    de cada equipo, no jugadores confirmados."""
    bullets = []
    if home_row:
        bullets.append(_team_form_line(home_name, home_row, home_group))
    if away_row:
        bullets.append(_team_form_line(away_name, away_row, away_group))

    if not home_row or not away_row:
        headline = "Todavía no hay suficientes datos de tabla para comparar a estos dos equipos."
    elif win_prob:
        if win_prob["home"] >= win_prob["away"] + 10:
            headline = f"{home_name} llega como favorito de local según su posición en la tabla ({win_prob['home']}% probabilidad de victoria estimada)."
        elif win_prob["away"] >= win_prob["home"] + 10:
            headline = f"{away_name} llega como favorito de visita según su posición en la tabla ({win_prob['away']}% probabilidad de victoria estimada)."
        else:
            headline = "Partido parejo: ambos equipos llegan con opciones similares según su posición en la tabla."
    else:
        headline = f"{home_name} y {away_name} tienen datos de tabla, pero no fue posible estimar una probabilidad."

    bullets.append(
        "Comparación a nivel de equipo (posición y forma en la tabla): football-data.org (plan gratuito) "
        "no entrega la alineación confirmada de cada equipo, ni tiros de esquina o tarjetas."
    )

    return {"headline": headline, "bullets": bullets, "winProbability": win_prob}


def match_goal_lines(home_name: str, away_name: str, home_row: dict | None, away_row: dict | None) -> list[dict]:
    """Proyección de goles del partido a partir del promedio real de goles a
    favor/en contra de cada equipo en la tabla (método Poisson, igual que las
    líneas de jugador). No hay datos de corners ni tarjetas disponibles."""
    if not home_row or not away_row:
        return []
    home_played = home_row.get("playedGames") or 0
    away_played = away_row.get("playedGames") or 0
    if not home_played or not away_played:
        return []

    home_gf = to_float(home_row.get("goalsFor")) / home_played
    home_ga = to_float(home_row.get("goalsAgainst")) / home_played
    away_gf = to_float(away_row.get("goalsFor")) / away_played
    away_ga = to_float(away_row.get("goalsAgainst")) / away_played

    expected_home = (home_gf + away_ga) / 2
    expected_away = (away_gf + home_ga) / 2

    return [
        prop_row("Partido", f"Total de goles de {home_name}", expected_home),
        prop_row("Partido", f"Total de goles de {away_name}", expected_away),
        prop_row("Partido", "Total de goles del partido (ambos equipos)", expected_home + expected_away),
    ]
