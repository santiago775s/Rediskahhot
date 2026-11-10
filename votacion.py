
import json
import threading
import time

import pubsub
from conexiones import DB_REDIS, mongo, redis

TIEMPO = 30
PUNTOS = 10
RETENCION = 3600


def _json(valor) -> str:
    return json.dumps(valor, ensure_ascii=False)


def lanzar(texto: str, opciones: list, correcta) -> dict:
    texto = str(texto).strip()
    opciones = [str(o).strip() for o in opciones]
    if not texto:
        return {"error": "Escribe el texto de la pregunta."}
    if not 3 <= len(opciones) <= 5 or any(not o for o in opciones):
        return {"error": "Se necesitan entre 3 y 5 opciones, todas con texto."}
    if not isinstance(correcta, int) or not 0 <= correcta < len(opciones):
        return {"error": "Marca cuál es la opción correcta."}

    actual = redis.get("pregunta:actual")
    if actual and redis.exists(f"pregunta:{actual}:abierta"):
        return {"error": "Ya hay una pregunta abierta. Espera a que cierre."}

    n = redis.incr("pregunta:id")
    clave = f"pregunta:{n}"
    campos = {"texto": texto, "opciones": _json(opciones), "correcta": correcta}
    campos.update({str(i): 0 for i in range(len(opciones))})

    comandos = [("INCR pregunta:id", f"(integer) {n}")]
    redis.hset(clave, mapping=campos)
    comandos.append((f"HSET {clave} texto {_json(texto)} opciones '{_json(opciones)}' correcta {correcta} "
                     + " ".join(f"{i} 0" for i in range(len(opciones))), f"(integer) {len(campos)}"))
    redis.set(f"{clave}:abierta", "", ex=TIEMPO)
    comandos.append((f'SET {clave}:abierta "" EX {TIEMPO}', "OK"))
    redis.set("pregunta:actual", n)
    comandos.append((f"SET pregunta:actual {n}", "OK"))

    mensaje = {"tipo": "pregunta", "id": n, "texto": texto, "opciones": opciones, "duracion": TIEMPO}
    oyentes = pubsub.publicar(mensaje)
    comandos.append((f"PUBLISH {pubsub.CANAL} {_json(mensaje)}", f"(integer) {oyentes}"))

    respaldo = threading.Timer(TIEMPO + 2, cerrar, args=(n,))
    respaldo.daemon = True
    respaldo.start()

    return {"ok": True, "id": n, "restante": TIEMPO, "comandos": comandos}


def estado(nombre: str = "") -> dict:
    actual = redis.get("pregunta:actual")
    if not actual:
        return {"estado": "espera"}
    n = int(actual)
    ttl = redis.ttl(f"pregunta:{n}:abierta")
    if ttl >= 0:
        texto, opciones = redis.hmget(f"pregunta:{n}", "texto", "opciones")
        resp = {"estado": "abierta", "id": n, "texto": texto, "opciones": json.loads(opciones),
                "restante": ttl, "duracion": TIEMPO,
                "comandos": [(f"TTL pregunta:{n}:abierta", f"(integer) {ttl}")]}
        if nombre:
            ya = redis.sismember(f"votantes:{n}", nombre)
            resp["yaVoto"] = bool(ya)
            resp["comandos"].append((f"SISMEMBER votantes:{n} {nombre}", f"(integer) {int(ya)}"))
        return resp
    cierre = redis.get(f"cierre:{n}")
    if cierre:
        return {"estado": "cerrada", "cierre": json.loads(cierre)}
    return {"estado": "cerrando", "id": n}


def votar(nombre: str, n, opcion) -> dict:
    nombre = str(nombre).strip()[:30]
    if not nombre:
        return {"ok": False, "error": "Escribe tu nombre."}
    try:
        n, opcion = int(n), int(opcion)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Voto inválido."}

    clave = f"pregunta:{n}"
    comandos = []

    abierta = redis.exists(f"{clave}:abierta")
    comandos.append((f"EXISTS {clave}:abierta", f"(integer) {abierta}"))
    if not abierta:
        return {"ok": False, "error": "La votación ya cerró.", "comandos": comandos}

    opciones_json, correcta = redis.hmget(clave, "opciones", "correcta")
    comandos.append((f"HGET {clave} correcta", "(oculto hasta el cierre)"))
    if opciones_json is None or not 0 <= opcion < len(json.loads(opciones_json)):
        return {"ok": False, "error": "Voto inválido.", "comandos": comandos}

    nuevo = redis.sadd(f"votantes:{n}", nombre)
    comandos.append((f"SADD votantes:{n} {nombre}", f"(integer) {nuevo}"))
    if not nuevo:
        return {"ok": False, "error": "Ya votaste en esta pregunta.", "comandos": comandos}

    ttl = max(redis.ttl(f"{clave}:abierta"), 0)
    segundos = TIEMPO - ttl
    acerto = opcion == int(correcta)
    puntos = PUNTOS + ttl // 3 if acerto else 0

    redis.hincrby(clave, str(opcion), 1)
    comandos.append((f"HINCRBY {clave} {opcion} 1", "(integer) *"))
    if acerto:
        redis.zincrby("ranking", puntos, nombre)
    respuesta = {"nombre": nombre, "opcion": opcion, "acerto": acerto, "segundos": segundos, "puntos": puntos}
    redis.rpush(f"respuestas:{n}", _json(respuesta))
    comandos.append((f"RPUSH respuestas:{n} <respuesta>", "(integer) *"))

    return {"ok": True, "mensaje": "Voto registrado.", "comandos": comandos}


def cerrar(n: int) -> None:
    if not redis.set(f"cerrada:{n}", 1, nx=True, ex=RETENCION):
        return
    time.sleep(0.5)

    clave = f"pregunta:{n}"
    datos = redis.hgetall(clave)
    opciones = json.loads(datos["opciones"])
    correcta = int(datos["correcta"])
    votos = [int(datos.get(str(i), 0)) for i in range(len(opciones))]
    top = redis.zrevrange("ranking", 0, 4, withscores=True)
    ranking = [{"nombre": a, "puntos": int(p)} for a, p in top]
    respuestas = [json.loads(r) for r in redis.lrange(f"respuestas:{n}", 0, -1)]

    comandos = [
        (f"HGETALL {clave}", _json(datos)),
        ("ZREVRANGE ranking 0 4 WITHSCORES", _json([[r["nombre"], r["puntos"]] for r in ranking])),
        (f"LRANGE respuestas:{n} 0 -1", f"{len(respuestas)} respuesta(s)"),
    ]

    try:
        mongo.preguntas.insert_one({
            "pregunta_id": n, "texto": datos["texto"], "opciones": opciones, "correcta": correcta,
            "votos": votos, "respuestas": respuestas, "cerrada_en": time.time(),
        })
        comandos.append((f"db.preguntas.insert_one({{pregunta_id: {n}, texto, opciones, correcta, votos, respuestas}})", "OK"))
        for r in respuestas:
            mongo.alumnos.update_one({"nombre": r["nombre"]}, {"$inc": {"puntos": r["puntos"]}}, upsert=True)
        comandos.append((f"db.alumnos.update_one({{nombre}}, {{$inc: {{puntos}}}}, upsert) x {len(respuestas)}", "OK"))
    except Exception as e:
        comandos.append(("MongoDB", f"ERROR {type(e).__name__}"))

    mensaje = {"tipo": "cierre", "id": n, "texto": datos["texto"], "opciones": opciones,
               "correcta": correcta, "votos": votos, "ranking": ranking, "comandos": comandos}
    redis.set(f"cierre:{n}", _json(mensaje), ex=RETENCION)
    pubsub.publicar(mensaje)
    redis.delete(f"votantes:{n}", f"respuestas:{n}")
    redis.expire(clave, RETENCION)


def vigilar_expiraciones() -> None:
    """Escucha __keyevent@db__:expired y cierra la pregunta cuando expira pregunta:N:abierta."""
    while True:
        try:
            try:
                redis.config_set("notify-keyspace-events", "Ex")
            except Exception:
                pass
            ps = redis.pubsub(ignore_subscribe_messages=True)
            ps.subscribe(f"__keyevent@{DB_REDIS}__:expired")
            for m in ps.listen():
                clave = m["data"]
                if clave.startswith("pregunta:") and clave.endswith(":abierta"):
                    cerrar(int(clave.split(":")[1]))
        except Exception:
            time.sleep(2)


ACIERTO_POR_ALUMNO = [
    {"$unwind": "$respuestas"},
    {"$group": {"_id": "$respuestas.nombre", "respondidas": {"$sum": 1},
                "aciertos": {"$sum": {"$cond": ["$respuestas.acerto", 1, 0]}},
                "porcentaje": {"$avg": {"$cond": ["$respuestas.acerto", 100, 0]}}}},
    {"$sort": {"porcentaje": -1, "_id": 1}},
    {"$project": {"_id": 0, "nombre": "$_id", "respondidas": 1, "aciertos": 1, "porcentaje": {"$round": ["$porcentaje", 1]}}},
]

PREGUNTA_MAS_FALLADA = [
    {"$unwind": "$respuestas"},
    {"$group": {"_id": "$pregunta_id", "texto": {"$first": "$texto"}, "respuestas": {"$sum": 1},
                "porcentaje_acierto": {"$avg": {"$cond": ["$respuestas.acerto", 100, 0]}}}},
    {"$sort": {"porcentaje_acierto": 1}},
    {"$limit": 1},
    {"$project": {"_id": 0, "pregunta_id": "$_id", "texto": 1, "respuestas": 1,
                  "porcentaje_acierto": {"$round": ["$porcentaje_acierto", 1]}}},
]


def estadisticas() -> dict:
    try:
        por_alumno = list(mongo.preguntas.aggregate(ACIERTO_POR_ALUMNO))
        fallada = next(iter(mongo.preguntas.aggregate(PREGUNTA_MAS_FALLADA)), None)
    except Exception as e:
        return {"error": f"MongoDB no respondió ({type(e).__name__})."}
    return {"acierto_por_alumno": por_alumno, "pregunta_mas_fallada": fallada,
            "comandos": [("db.preguntas.aggregate([$unwind respuestas, $group por nombre ($avg acerto), $sort])", f"{len(por_alumno)} alumno(s)"),
                         ("db.preguntas.aggregate([$unwind respuestas, $group por pregunta, $sort asc, $limit 1])", "1 documento" if fallada else "(vacío)")]}
