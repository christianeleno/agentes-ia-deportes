"""
Agente de análisis para tenis.

Sin ranking ATP/WTA ni estadísticas de temporada disponibles (ver
tennis_client.py), este agente no calcula una probabilidad numérica —
sería inventar señal que no existe. En su lugar resume el camino real de
cada jugador dentro del mismo torneo (contra quién jugó, resultado, sets).
"""
from __future__ import annotations


def _fmt_score(sets_for: list, sets_against: list) -> str:
    pairs = []
    for a, b in zip(sets_for, sets_against):
        try:
            pairs.append(f"{int(a)}-{int(b)}")
        except (TypeError, ValueError):
            continue
    return ", ".join(pairs)


def _summarize_path(name: str, path: list[dict]) -> str:
    if not path:
        return f"{name}: este es su debut en el torneo (no hay partidos previos registrados en el cuadro)."
    wins = sum(1 for r in path if r["won"])
    losses = len(path) - wins
    last = path[-1]
    last_score = _fmt_score(last["setsFor"], last["setsAgainst"])
    return (
        f"{name}: llega con marca {wins}-{losses} en el torneo. "
        f"Último partido ({last['round'] or '—'}) vs {last['opponent'] or '—'}: "
        f"{'ganó' if last['won'] else 'perdió'} {last_score or 'sin marcador registrado'}."
    )


def preview_match(data: dict) -> dict:
    home = data["home"]
    away = data["away"]
    bullets = [
        _summarize_path(home.get("name") or "Jugador local", home.get("path", [])),
        _summarize_path(away.get("name") or "Jugador visitante", away.get("path", [])),
        "No hay ranking ATP/WTA ni estadísticas de temporada disponibles gratis para calcular una "
        "probabilidad numérica; esto es solo el camino de cada jugador dentro de este torneo.",
    ]
    headline = f"{data.get('tournament', 'Torneo')} · {data.get('category', '')} · {data.get('round', '')}"
    return {"headline": headline, "bullets": bullets}
