"""
Utilidades compartidas por los agentes de análisis de cada deporte.

Los agentes son heurísticas estadísticas (no llamadas a un LLM) para que la
app funcione sin credenciales externas, con la misma forma de salida
(headline + bullets + rating + probability) que tendría un agente basado en
Vertex AI / Gemini, de modo que esa capa se pueda enchufar más adelante sin
tocar el resto de la app.
"""
from __future__ import annotations

import math


def to_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def semaphore_level(pct: float) -> str:
    if pct >= 55:
        return "verde"
    if pct >= 35:
        return "amarillo"
    return "rojo"


def poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def poisson_over_prob(line: float, lam: float) -> float:
    threshold = int(math.floor(line))
    cumulative = sum(poisson_pmf(k, lam) for k in range(0, threshold + 1))
    return clamp(1 - cumulative, 0.03, 0.97)


def nearest_line(rate: float) -> float:
    base = math.floor(rate - 0.5) + 0.5
    return max(0.5, base)


def prop_row(category: str, label: str, rate: float) -> dict:
    line = nearest_line(rate)
    pct = round(poisson_over_prob(line, rate) * 100)
    return {
        "category": category,
        "statLabel": label,
        "line": line,
        "pct": pct,
        "level": semaphore_level(pct),
    }


def win_probability(pct_home: float, pct_away: float, home_edge: float = 0.04) -> dict:
    """Probabilidad heurística de victoria local, a partir del % de puntos/juegos
    ganados de cada equipo en la temporada. Es una estimación propia del
    agente (no son cuotas de casas de apuestas)."""
    diff = (pct_home - pct_away) + home_edge
    prob_home = clamp(1 / (1 + math.exp(-6 * diff)), 0.05, 0.95)
    return {
        "home": round(prob_home * 100),
        "away": round((1 - prob_home) * 100),
    }
