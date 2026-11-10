"""Servidor web (Flask): única puerta de entrada a Redis y MongoDB."""
import os
import threading

from flask import Flask, Response, jsonify, redirect, request

import pubsub
import votacion

app = Flask(__name__)


def datos() -> dict:
    return request.get_json(silent=True) or {}


@app.get("/")
def inicio():
    return redirect("/alumno")


@app.get("/docente")
def pagina_docente():
    return app.send_static_file("docente.html")


@app.get("/alumno")
def pagina_alumno():
    return app.send_static_file("alumno.html")


@app.get("/api/docente")
def estado_docente():
    return jsonify(pubsub.estado_lock())


@app.post("/api/docente/tomar")
def tomar_docente():
    if pubsub.adquirir_lock(datos().get("token", "")):
        return jsonify({"ok": True, "ttl": pubsub.LOCK_TTL})
    return jsonify({"ok": False, "error": "Ya hay un docente activo."}), 409


@app.post("/api/docente/heartbeat")
def heartbeat_docente():
    return jsonify({"ttl": pubsub.renovar_lock(datos().get("token", ""))})


@app.post("/api/docente/soltar")
def soltar_docente():
    pubsub.liberar_lock(datos().get("token", ""))
    return jsonify({"ok": True})


@app.post("/api/pregunta")
def lanzar_pregunta():
    d = datos()
    if not pubsub.es_docente(d.get("token", "")):
        return jsonify({"error": "No eres el docente activo."}), 403
    resultado = votacion.lanzar(d.get("texto", ""), d.get("opciones", []), d.get("correcta"))
    return jsonify(resultado), 400 if "error" in resultado else 200


@app.get("/api/stream")
def stream():
    return Response(pubsub.escuchar(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/estado")
def estado():
    return jsonify(votacion.estado(request.args.get("nombre", "").strip()[:30]))


@app.post("/api/votar")
def votar():
    d = datos()
    resultado = votacion.votar(d.get("nombre", ""), d.get("id"), d.get("opcion"))
    return jsonify(resultado), 200 if resultado["ok"] else 409


@app.get("/api/stats")
def stats():
    resultado = votacion.estadisticas()
    return jsonify(resultado), 503 if "error" in resultado else 200


def iniciar_vigilante() -> None:
    threading.Thread(target=votacion.vigilar_expiraciones, daemon=True).start()


if __name__ == "__main__":
    iniciar_vigilante()
    app.run(host="0.0.0.0", port=int(os.getenv("APP_PORT", 8078)), threaded=True)
