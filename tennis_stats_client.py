"""
Cliente de estadísticas de tenis vía "Tennis API - ATP WTA ITF" (RapidAPI).

Requiere una API key propia del usuario (variable de entorno
TENNIS_STATS_API_KEY, cargada desde .env). A diferencia de ESPN (usado en
tennis_client.py solo para el marcador en vivo), esta API sí tiene ranking,
estadísticas de carrera y registro de partidos reales por jugador.

OJO: el plan gratuito (Basic) de esta API está limitado a ~50 peticiones
POR DÍA (no por minuto) — mucho más estricto que football-data.org. Por
eso todo se cachea agresivamente: 24h por jugador (perfil + estadísticas +
resumen por superficie + partidos jugados se piden juntos y se guardan
como un solo "bundle"), y 1h para las búsquedas por nombre. Aun así, con
tráfico real la cuota diaria se puede agotar — si eso pasa, los endpoints
devuelven un error controlado en vez de romper la app.
"""
from __future__ import annotations

import os
import time
from urllib.parse import quote

import httpx

BASE_URL = "https://tennis-api-atp-wta-itf.p.rapidapi.com/tennis/v2"
API_HOST = "tennis-api-atp-wta-itf.p.rapidapi.com"
TOURS = ["atp", "wta"]

_client: httpx.AsyncClient | None = None


def _key() -> str:
    key = os.environ.get("TENNIS_STATS_API_KEY", "")
    if not key:
        raise RuntimeError(
            "Falta TENNIS_STATS_API_KEY. Configúrala en el archivo .env de deportes-ia-app."
        )
    return key


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=15.0, headers={"x-rapidapi-host": API_HOST, "x-rapidapi-key": _key()}
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


class QuotaExceeded(Exception):
    """El plan gratuito (50 peticiones/día) se agotó por hoy."""


async def _get(path: str, **params) -> dict:
    resp = await client().get(f"{BASE_URL}{path}", params=params)
    if resp.status_code == 429:
        raise QuotaExceeded("Se agotó la cuota diaria gratuita de la API de estadísticas de tenis.")
    resp.raise_for_status()
    return resp.json()


# --- Búsqueda ---------------------------------------------------------------

_search_cache: dict[str, tuple[float, list[dict]]] = {}
_SEARCH_TTL = 3600


async def search_players(query: str) -> list[dict]:
    q = query.strip().lower()
    now = time.time()
    cached = _search_cache.get(q)
    if cached and (now - cached[0]) < _SEARCH_TTL:
        return cached[1]

    results: list[dict] = []
    seen = set()
    for tour in TOURS:
        try:
            names = await _get(f"/ms-api/profile/search/{quote(query)}/{tour}")
        except (httpx.HTTPStatusError, QuotaExceeded):
            names = []
        for n in names[:8] if isinstance(names, list) else []:
            if n in seen:
                continue
            seen.add(n)
            results.append({"id": n, "fullName": n, "position": tour.upper(), "team": None})

    _search_cache[q] = (now, results)
    return results


# --- Perfil + estadísticas (un solo "bundle" cacheado 24h) ------------------

_bundle_cache: dict[str, tuple[float, dict]] = {}
_BUNDLE_TTL = 24 * 3600


async def player_bundle(name: str) -> dict:
    now = time.time()
    cached = _bundle_cache.get(name)
    if cached and (now - cached[0]) < _BUNDLE_TTL:
        return cached[1]

    encoded = quote(name)
    profile = await _get(f"/ms-api/profile/{encoded}")

    statistics: dict = {}
    surface_summary: list = []
    matches_played: dict = {}
    try:
        statistics = await _get(f"/ms-api/profile/{encoded}/statistics")
    except (httpx.HTTPStatusError, QuotaExceeded):
        pass
    try:
        surface_summary = await _get(f"/ms-api/profile/{encoded}/surface-summary")
    except (httpx.HTTPStatusError, QuotaExceeded):
        pass
    try:
        matches_played = await _get(f"/ms-api/profile/{encoded}/matches-played")
    except (httpx.HTTPStatusError, QuotaExceeded):
        pass

    bundle = {
        "profile": profile,
        "statistics": statistics,
        "surfaceSummary": surface_summary,
        "matchesPlayed": matches_played,
    }
    _bundle_cache[name] = (now, bundle)
    return bundle
