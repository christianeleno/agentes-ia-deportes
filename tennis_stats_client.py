"""
Cliente de estadísticas de tenis vía "Tennis API - ATP WTA ITF" (RapidAPI).

Requiere una API key propia del usuario (variable de entorno
TENNIS_STATS_API_KEY, cargada desde .env). A diferencia de ESPN (usado en
tennis_client.py solo para el marcador en vivo), esta API sí tiene ranking,
estadísticas de carrera y registro de partidos reales por jugador.

OJO: el plan gratuito (Basic) de esta API tiene dos límites: ~50 peticiones
POR DÍA y además un límite por segundo (ráfaga). Por eso las peticiones se
hacen de una en una (ver _get) y todo se cachea agresivamente: 24h por
jugador (perfil + estadísticas + partidos jugados, 3 peticiones, guardados
como un solo "bundle") y 1h para las búsquedas por nombre. Aun así, con
tráfico real la cuota diaria se puede agotar — si eso pasa, los endpoints
devuelven un error controlado en vez de romper la app.
"""
from __future__ import annotations

import asyncio
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


# La fuente tiene DOS límites distintos y los dos responden 429:
#   - por segundo (ráfaga): "You have exceeded the rate limit per second..."
#   - por día (~50 peticiones): la cuota diaria del plan gratuito.
# Antes se trataban igual, y como la ficha de prepartido pide dos jugadores a
# la vez, el límite por segundo hacía que se perdieran datos "por cuota".
# Ahora las peticiones salen de una en una, espaciadas, y el 429 por segundo
# se reintenta; solo el 429 diario se reporta como QuotaExceeded.

_request_lock = asyncio.Lock()
_last_request_at = 0.0
_MIN_INTERVAL = 0.4
_BURST_RETRIES = 3


async def _get(path: str, **params) -> dict:
    global _last_request_at
    async with _request_lock:
        for attempt in range(_BURST_RETRIES + 1):
            wait = _MIN_INTERVAL - (time.monotonic() - _last_request_at)
            if wait > 0:
                await asyncio.sleep(wait)
            resp = await client().get(f"{BASE_URL}{path}", params=params)
            _last_request_at = time.monotonic()
            if resp.status_code != 429:
                break
            if "per second" not in resp.text.lower():
                raise QuotaExceeded("Se agotó la cuota diaria gratuita de la API de estadísticas de tenis.")
            if attempt < _BURST_RETRIES:
                await asyncio.sleep(1.1)
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
    failed = False
    for tour in TOURS:
        try:
            names = await _get(f"/ms-api/profile/search/{quote(query)}/{tour}")
        except (httpx.HTTPError, QuotaExceeded):
            names = []
            failed = True
        for n in names[:8] if isinstance(names, list) else []:
            if n in seen:
                continue
            seen.add(n)
            results.append({"id": n, "fullName": n, "position": tour.upper(), "team": None})

    if not failed:  # un fallo no debe quedar guardado 1 h como "sin resultados"
        _search_cache[q] = (now, results)
    return results


# --- Perfil + estadísticas (un solo "bundle" cacheado 24h) ------------------
# Tres peticiones por jugador: perfil, estadísticas y partidos jugados. (Antes
# se pedía también el resumen por superficie, que la app no muestra: era 1 de
# cada 4 peticiones de la cuota diaria gastada sin uso.)
# Si alguna parte falla, el bundle se devuelve igual pero queda marcado como
# incompleto y las partes que faltan se reintentan pasados unos minutos, en
# vez de quedar guardado sin esos datos durante 24 h.

_bundle_cache: dict[str, dict] = {}
_BUNDLE_TTL = 24 * 3600
_INCOMPLETE_RETRY = 300
_BUNDLE_PARTS = (("statistics", "/statistics"), ("matchesPlayed", "/matches-played"))


_bundle_locks: dict[str, asyncio.Lock] = {}


async def player_bundle(name: str) -> dict:
    # La página de un jugador pide perfil, análisis y partidos al mismo tiempo:
    # son tres llamadas simultáneas a esta función para el mismo nombre. Sin
    # este candado cada una descargaba el bundle por su cuenta (el triple de
    # peticiones de la cuota diaria). Con él, la primera descarga y las otras
    # dos esperan y reutilizan el resultado.
    lock = _bundle_locks.setdefault(name, asyncio.Lock())
    async with lock:
        return await _load_bundle(name)


async def _load_bundle(name: str) -> dict:
    now = time.time()
    entry = _bundle_cache.get(name)
    if entry and (now - entry["fetched_at"]) >= _BUNDLE_TTL:
        entry = None
    if entry and (not entry["missing"] or (now - entry["tried_at"]) < _INCOMPLETE_RETRY):
        return entry["bundle"]

    encoded = quote(name)
    if entry is None:
        profile = await _get(f"/ms-api/profile/{encoded}")
        entry = {
            "fetched_at": now,
            "tried_at": now,
            "missing": {key for key, _ in _BUNDLE_PARTS},
            "bundle": {"profile": profile, "statistics": {}, "matchesPlayed": {}},
        }
        _bundle_cache[name] = entry

    entry["tried_at"] = now
    for key, suffix in _BUNDLE_PARTS:
        if key not in entry["missing"]:
            continue
        try:
            entry["bundle"][key] = await _get(f"/ms-api/profile/{encoded}{suffix}")
            entry["missing"].discard(key)
        except (httpx.HTTPError, QuotaExceeded):
            pass
    return entry["bundle"]


# --- Jugadores destacados (botones de sugerencia) ----------------------------
# Top 3 del ranking ATP + top 2 del ranking WTA. Cuesta 2 peticiones de la
# cuota diaria (~50), por eso se cachea 24 h; si falla o no hay cuota, la
# interfaz usa su lista fija de respaldo.

_featured_cache: tuple[float, list[str]] | None = None
_FEATURED_TTL = 24 * 3600


async def featured_players() -> list[str]:
    global _featured_cache
    now = time.time()
    if _featured_cache and now < _featured_cache[0]:
        return _featured_cache[1]
    names: list[str] = []
    failed = False
    for tour, count in (("atp", 3), ("wta", 2)):
        try:
            data = await _get(f"/{tour}/ranking/singles", pageSize=count)
        except (httpx.HTTPError, QuotaExceeded):
            failed = True
            continue
        for row in (data.get("data") or [])[:count]:
            name = (row.get("player") or {}).get("name")
            if name:
                names.append(name)
    # Lista completa: 24 h. Si falló algún ranking: reintentar en 10 min.
    _featured_cache = (now + (600 if failed else _FEATURED_TTL), names)
    return names
