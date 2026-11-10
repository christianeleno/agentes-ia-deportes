"""
Utilidades de resiliencia para las llamadas a fuentes de datos externas.

Las fuentes gratuitas (ESPN, NHL, etc.) fallan de forma transitoria de vez en
cuando (por ejemplo un error TLS o un timeout). En vez de devolver un 500, los
marcadores en vivo devuelven el último resultado bueno que se obtuvo.
"""
from __future__ import annotations

import functools

import httpx


def stale_on_error(fn):
    """Para funciones async sin argumentos que consultan una API externa.

    Si la llamada falla con un error de red/HTTP y ya hubo una respuesta buena
    antes, devuelve esa última respuesta. Si nunca hubo una (instancia recién
    arrancada), deja pasar el error para que el manejador global responda 503.
    """
    last: dict = {"has": False, "value": None}

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            result = await fn(*args, **kwargs)
        except httpx.HTTPError:
            if last["has"]:
                return last["value"]
            raise
        last["value"] = result
        last["has"] = True
        return result

    return wrapper
