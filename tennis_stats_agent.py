"""
Agente de análisis de estadísticas de tenis (a partir de tennis_stats_client).

No hay líneas de proyección (prop lines) para tenis: los datos disponibles
son resultados de partidos (sets), no una estadística por partido con una
tasa clara tipo Poisson (goles, puntos, etc.), así que inventar una línea
sería fabricar señal que no existe.
"""
from __future__ import annotations

from agent_common import clamp, semaphore_level, to_float


def _parse_record(record: str | None) -> tuple[int, int]:
    if not record or "-" not in record:
        return 0, 0
    try:
        wins, losses = record.split("-", 1)
        return int(wins), int(losses)
    except ValueError:
        return 0, 0


def season_stats(bundle: dict) -> dict:
    stats = bundle.get("statistics") or {}
    best_rank = stats.get("bestRank") or {}
    fav_court = stats.get("favouriteCourt") or {}
    return {
        "currentRank": stats.get("currentRank"),
        "bestRank": f"#{best_rank['position']} ({str(best_rank.get('date'))[:4]})" if best_rank.get("position") else None,
        "total": stats.get("total"),
        "grandSlam": stats.get("grandSlam"),
        "master": stats.get("master"),
        "totalTitlesWon": stats.get("totalTitlesWon"),
        "favouriteCourt": f"{fav_court['surface']} ({fav_court['wins']}-{fav_court['losses']})" if fav_court.get("surface") else None,
    }


def estimate_probability(stats: dict) -> dict:
    recent = stats.get("recentGames") or []
    recent_winrate = (recent.count("w") / len(recent)) if recent else 0.5
    total_wins, total_losses = _parse_record(stats.get("total"))
    career_winrate = total_wins / (total_wins + total_losses) if (total_wins + total_losses) else 0.5

    base = 0.6 * recent_winrate + 0.4 * career_winrate
    pct = round(clamp(base * 100, 5, 95))
    return {
        "pct": pct,
        "level": semaphore_level(pct),
        "label": "Probabilidad de ganar su próximo partido (forma reciente + récord de carrera)",
    }


def build_gamelog(bundle: dict, player_name: str, limit: int = 15) -> list[dict]:
    matches = (bundle.get("matchesPlayed") or {}).get("singles") or []
    rows = []
    for m in matches:
        p1 = m.get("player1") or {}
        is_p1 = p1.get("name") == player_name
        opponent = (m.get("player2") if is_p1 else m.get("player1")) or {}
        tournament = m.get("tournament") or {}
        rows.append(
            {
                "date": m.get("date"),
                "opponent": opponent.get("name"),
                "tournament": tournament.get("name"),
                "tier": tournament.get("tier"),
                "surface": (tournament.get("court") or {}).get("name"),
                "result": "Ganó" if is_p1 else "Perdió",
                "score": m.get("result"),
            }
        )
    return rows[:limit]


def analyze_player(name: str, bundle: dict) -> dict:
    stats = bundle.get("statistics") or {}
    recent = stats.get("recentGames") or []
    recent_wins = recent.count("w")
    recent_played = len(recent)

    bullets = []
    rating = "neutral"

    if not recent_played:
        headline = f"No hay partidos recientes registrados para {name}."
    else:
        win_rate = recent_wins / recent_played
        if win_rate >= 0.8:
            rating = "caliente"
            headline = f"{name} está en gran forma: {recent_wins}-{recent_played - recent_wins} en sus últimos {recent_played} partidos."
        elif win_rate <= 0.3:
            rating = "frio"
            headline = f"{name} atraviesa un mal momento: {recent_wins}-{recent_played - recent_wins} en sus últimos {recent_played} partidos."
        else:
            headline = f"{name} mantiene un nivel parejo: {recent_wins}-{recent_played - recent_wins} en sus últimos {recent_played} partidos."

        bullets.append(f"Últimos {recent_played} partidos: {recent_wins} victorias, {recent_played - recent_wins} derrotas.")

    total = stats.get("total")
    if total:
        bullets.append(f"Récord de carrera: {total}.")
    best_rank = stats.get("bestRank") or {}
    if best_rank.get("position"):
        bullets.append(f"Mejor ranking histórico: #{best_rank['position']} (alcanzado en {str(best_rank.get('date'))[:4]}).")
    fav_court = stats.get("favouriteCourt") or {}
    if fav_court.get("surface"):
        bullets.append(f"Superficie favorita: {fav_court['surface']} ({fav_court['wins']}-{fav_court['losses']}).")
    if stats.get("totalTitlesWon"):
        bullets.append(f"{stats.get('totalTitlesWon')} título(s) ganado(s) de {stats.get('totalTitles')} finales disputadas.")

    return {
        "headline": headline,
        "rating": rating,
        "bullets": bullets,
        "probability": estimate_probability(stats),
        "keyStats": season_stats(bundle),
    }
