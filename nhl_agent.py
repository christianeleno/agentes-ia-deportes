from __future__ import annotations

from agent_common import clamp, prop_row, semaphore_level, to_float


def is_goalie(bio: dict) -> bool:
    return bio.get("position") == "G"


def _recent_totals(games: list[dict], keys: list[str]) -> dict:
    totals = {k: 0.0 for k in keys}
    for g in games:
        for k in keys:
            totals[k] += to_float(g.get(k))
    return totals


def estimate_skater_probability(season: dict, rating: str = "neutral") -> dict:
    gp = to_float(season.get("gamesPlayed"))
    points = to_float(season.get("points"))
    ppg = points / gp if gp else 0

    base = clamp(ppg / 1.2, 0, 1)
    adjust = {"caliente": 0.08, "frio": -0.08, "neutral": 0.0}.get(rating, 0.0)
    pct = round(clamp((base + adjust) * 100, 5, 95))
    return {
        "pct": pct,
        "level": semaphore_level(pct),
        "label": "Probabilidad de anotar punto (gol o asistencia) hoy",
    }


def estimate_goalie_probability(season: dict, rating: str = "neutral") -> dict:
    save_pct = to_float(season.get("savePctg"), default=0.9)
    gaa = to_float(season.get("goalsAgainstAvg"), default=3.0)

    base = 0.6 * clamp((save_pct - 0.88) / 0.07, 0, 1) + 0.4 * clamp((3.3 - gaa) / 1.5, 0, 1)
    adjust = {"caliente": 0.08, "frio": -0.08, "neutral": 0.0}.get(rating, 0.0)
    pct = round(clamp((base + adjust) * 100, 5, 95))
    return {
        "pct": pct,
        "level": semaphore_level(pct),
        "label": "Probabilidad de una salida de calidad hoy",
    }


def generate_skater_prop_lines(season: dict) -> list[dict]:
    gp = to_float(season.get("gamesPlayed"))
    if not gp:
        return []
    goals = to_float(season.get("goals")) / gp
    assists = to_float(season.get("assists")) / gp
    points = to_float(season.get("points")) / gp
    shots = to_float(season.get("shots")) / gp
    return [
        prop_row("Hockey", "Total de goles", goals),
        prop_row("Hockey", "Total de asistencias", assists),
        prop_row("Hockey", "Total de puntos", points),
        prop_row("Hockey", "Total de tiros al arco", shots),
    ]


def generate_goalie_prop_lines(season: dict, recent_games: list[dict]) -> list[dict]:
    rows = [prop_row("Hockey", "Total de goles recibidos", to_float(season.get("goalsAgainstAvg")))]
    played = [g for g in recent_games if to_float(g.get("gamesStarted"))]
    if played:
        totals = _recent_totals(played, ["shotsAgainst", "goalsAgainst"])
        saves_rate = (totals["shotsAgainst"] - totals["goalsAgainst"]) / len(played)
        if saves_rate > 0:
            rows.append(prop_row("Hockey", "Total de atajadas", saves_rate))
    return rows


def analyze_skater(bio: dict, season: dict, games: list[dict]) -> dict:
    name = bio.get("fullName", "El jugador")
    recent = games[:7]
    recent_totals = _recent_totals(recent, ["goals", "assists", "points"])
    recent_games_played = len(recent)

    bullets = []
    rating = "neutral"

    if recent_games_played == 0:
        headline = f"No hay partidos recientes registrados para {name} en esta temporada."
        bullets.append("Aún no se han disputado partidos con estadísticas para este jugador.")
    else:
        ppg_recent = recent_totals["points"] / recent_games_played
        gp = to_float(season.get("gamesPlayed"))
        season_ppg = to_float(season.get("points")) / gp if gp else 0

        if season_ppg and ppg_recent >= season_ppg * 1.3:
            rating = "caliente"
            headline = f"{name} está en racha: promedia {ppg_recent:.1f} puntos en sus últimos {recent_games_played} partidos."
        elif season_ppg and ppg_recent <= season_ppg * 0.6:
            rating = "frio"
            headline = f"{name} atraviesa un bache: solo {recent_totals['points']:.0f} puntos en los últimos {recent_games_played} partidos."
        else:
            headline = f"{name} mantiene un rendimiento estable en sus últimos {recent_games_played} partidos."

        bullets.append(
            f"Últimos {recent_games_played} partidos: {recent_totals['goals']:.0f} goles, "
            f"{recent_totals['assists']:.0f} asistencias, {recent_totals['points']:.0f} puntos en total."
        )

    bullets.append(
        f"Temporada: {season.get('goals', 0)} goles, {season.get('assists', 0)} asistencias, "
        f"{season.get('points', 0)} puntos en {season.get('gamesPlayed', 0)} partidos."
    )

    return {
        "headline": headline,
        "rating": rating,
        "bullets": bullets,
        "probability": estimate_skater_probability(season, rating),
        "keyStats": {
            "goals": season.get("goals"),
            "assists": season.get("assists"),
            "points": season.get("points"),
            "plusMinus": season.get("plusMinus"),
            "shots": season.get("shots"),
            "gamesPlayed": season.get("gamesPlayed"),
        },
    }


def analyze_goalie(bio: dict, season: dict, games: list[dict]) -> dict:
    name = bio.get("fullName", "El portero")
    recent = [g for g in games[:7] if to_float(g.get("gamesStarted"))]
    recent_totals = _recent_totals(recent, ["goalsAgainst", "shotsAgainst"])
    recent_games_played = len(recent)

    bullets = []
    rating = "neutral"

    if recent_games_played == 0:
        headline = f"No hay salidas recientes registradas para {name} en esta temporada."
        bullets.append("Aún no se han disputado partidos con estadísticas para este portero.")
    else:
        avg_ga = recent_totals["goalsAgainst"] / recent_games_played
        if avg_ga <= 2.0:
            rating = "caliente"
            headline = f"{name} está dominante: promedia {avg_ga:.1f} goles recibidos en sus últimas {recent_games_played} salidas."
        elif avg_ga >= 3.5:
            rating = "frio"
            headline = f"{name} ha tenido dificultades: {recent_totals['goalsAgainst']:.0f} goles recibidos en {recent_games_played} salidas."
        else:
            headline = f"{name} mantiene un rendimiento parejo en sus últimas {recent_games_played} salidas."

        bullets.append(
            f"Últimas {recent_games_played} salidas: {recent_totals['goalsAgainst']:.0f} goles recibidos, "
            f"{recent_totals['shotsAgainst']:.0f} tiros enfrentados."
        )

    bullets.append(
        f"Temporada: {to_float(season.get('wins')):.0f}-{to_float(season.get('losses')):.0f}, "
        f"GAA {to_float(season.get('goalsAgainstAvg')):.2f}, "
        f"efectividad {to_float(season.get('savePctg')) * 100:.1f}%."
    )

    return {
        "headline": headline,
        "rating": rating,
        "bullets": bullets,
        "probability": estimate_goalie_probability(season, rating),
        "keyStats": {
            "wins": season.get("wins"),
            "losses": season.get("losses"),
            "goalsAgainstAvg": season.get("goalsAgainstAvg"),
            "savePctg": season.get("savePctg"),
            "shutouts": season.get("shutouts"),
            "gamesPlayed": season.get("gamesPlayed"),
        },
    }
