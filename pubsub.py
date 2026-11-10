"""
Rol docente y canal de votación.

  Lock  : SET lock:docente <token> NX EX 30   -> solo un docente a la vez
  Enviar: PUBLISH votacion:sala1 <json>        -> devuelve cuántos oyentes lo recibieron
  Oír   : SUBSCRIBE votacion:sala1             -> los mensajes llegan al navegador por SSE
"""
import json
from typing import Iterator

from conexiones import redis

LOCK = "lock:docente"
LOCK_TTL = 30
CANAL = "votacion:sala1"


def adquirir_lock(token: str) -> bool:
    if not token:
        return False
    return bool(redis.set(LOCK, token, nx=True, ex=LOCK_TTL)) or redis.get(LOCK) == token


def renovar_lock(token: str) -> int:
    if redis.get(LOCK) == token:
        redis.expire(LOCK, LOCK_TTL)
    return redis.ttl(LOCK)


def liberar_lock(token: str) -> None:
    if redis.get(LOCK) == token:
        redis.delete(LOCK)


def estado_lock() -> dict:
    return {"ocupado": redis.exists(LOCK) == 1, "ttl": redis.ttl(LOCK)}


def es_docente(token: str) -> bool:
    return bool(token) and redis.get(LOCK) == token


def publicar(mensaje: dict) -> int:
    return redis.publish(CANAL, json.dumps(mensaje, ensure_ascii=False))


def escuchar() -> Iterator[str]:
    """Generador SSE: cada mensaje de Redis se reenvía al navegador como un evento."""
    ps = redis.pubsub(ignore_subscribe_messages=True)
    ps.subscribe(CANAL)
    try:
        while True:
            m = ps.get_message(timeout=15)
            if m is None:
                yield ": ping\n\n"
            else:
                yield f"event: {m['channel']}\ndata: {m['data']}\n\n"
    finally:
        ps.close()
