from __future__ import annotations

from agent_common import clamp, prop_row, semaphore_level, to_float


def _recent_totals(games: list[dict], keys: list[str]) -> dict:
    totals = {k: 0.0 for k in keys}
    for g in games:
        for k in keys:
            totals[k] += to_float(g.get(k))
    return totals


def estimate_player_probability(season: dict, rating: str = "neutral") -> dict:
    pts = to_float(season.get("avgPoints"))
    fg_pct = to_float(season.get("fieldGoalPct"))

    base = 0.6 * clamp(pts / 28, 0, 1) + 0.4 * clamp(fg_pct / 55, 0, 1)
    adjust = {"caliente": 0.08, "frio": -0.08, "neutral": 0.0}.get(rating, 0.0)
    pct = round(clamp((base + adjust) * 100, 5, 95))

    return {
        "pct": pct,
        "level": semaphore_level(pct),
        "label": "Probabilidad de un partido destacado hoy",
    }


def generate_prop_lines(season: dict) -> list[dict]:
    games = to_float(season.get("gamesPlayed"))
    if not games:
        return []

    points = to_float(season.get("avgPoints"))
    rebounds = to_float(season.get("avgRebounds"))
    assists = to_float(season.get("avgAssists"))
    steals = to_float(season.get("avgSteals"))
    blocks = to_float(season.get("avgBlocks"))
    pra = points + rebounds + assists

    rows = [
        prop_row("Baloncesto", "Total de puntos", points),
        prop_row("Baloncesto", "Total de rebotes", rebounds),
        prop_row("Baloncesto", "Total de asistencias", assists),
        prop_row("Baloncesto", "Total de puntos + rebotes + asistencias", pra),
        prop_row("Baloncesto", "Total de robos", steals),
        prop_row("Baloncesto", "Total de bloqueos", blocks),
    ]
    return rows


def analyze_player(bio: dict, season: dict, games: list[dict]) -> dict:
    name = bio.get("displayName", "El jugador")
    recent = games[:7]
    recent_totals = _recent_totals(recent, ["points", "totalRebounds", "assists"])
    recent_games_played = len(recent)

    bullets = []
    rating = "neutral"

    if recent_games_played == 0:
        headline = f"No hay partidos recientes registrados para {name} en esta temporada."
        bullets.append("Aún no se han disputado partidos con estadísticas para este jugador.")
    else:
        avg_pts_recent = recent_totals["points"] / recent_games_played
        season_pts = to_float(season.get("avgPoints"))

        if season_pts and avg_pts_recent >= season_pts * 1.2:
            rating = "caliente"
            headline = f"{name} está en racha: promedia {avg_pts_recent:.1f} puntos en sus últimos {recent_games_played} partidos."
        elif season_pts and avg_pts_recent <= season_pts * 0.75:
            rating = "frio"
            headline = f"{name} atraviesa un bache: solo {avg_pts_recent:.1f} puntos de promedio en sus últimos {recent_games_played} partidos."
        else:
            headline = f"{name} mantiene un rendimiento estable en sus últimos {recent_games_played} partidos."

        bullets.append(
            f"Últimos {recent_games_played} partidos: {recent_totals['points']:.0f} puntos, "
            f"{recent_totals['totalRebounds']:.0f} rebotes, {recent_totals['assists']:.0f} asistencias en total."
        )
        if season_pts:
            diff = avg_pts_recent - season_pts
            if abs(diff) > 2:
                tendencia = "por encima" if diff > 0 else "por debajo"
                bullets.append(
                    f"Su promedio de puntos reciente está {tendencia} de su promedio de temporada ({season_pts:.1f})."
                )

    bullets.append(
        f"Temporada: {to_float(season.get('avgPoints')):.1f} PPG, "
        f"{to_float(season.get('avgRebounds')):.1f} RPG, {to_float(season.get('avgAssists')):.1f} APG, "
        f"FG {to_float(season.get('fieldGoalPct')):.1f}%."
    )

    return {
        "headline": headline,
        "rating": rating,
        "bullets": bullets,
        "probability": estimate_player_probability(season, rating),
        "keyStats": {
            "points": season.get("avgPoints"),
            "rebounds": season.get("avgRebounds"),
            "assists": season.get("avgAssists"),
            "steals": season.get("avgSteals"),
            "blocks": season.get("avgBlocks"),
            "fieldGoalPct": season.get("fieldGoalPct"),
        },
    }
