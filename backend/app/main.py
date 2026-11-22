"""Punto de entrada: `uvicorn backend.app.main:app`."""
import os
import traceback

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from . import api, config, db, services

FRONTEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))


class CabecerasSeguridad:
    """Middleware ASGI puro: cabeceras de seguridad y tope de tamaño por Content-Length."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        for k, v in scope["headers"]:
            if k == b"content-length" and v.isdigit() and int(v) > config.MAX_BODY_BYTES:
                resp = JSONResponse({"error": "El cuerpo de la solicitud es demasiado grande"}, status_code=413)
                return await resp(scope, receive, send)

        async def enviar(msg):
            if msg["type"] == "http.response.start":
                h = list(msg.get("headers", []))
                h += [(b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"),
                      (b"referrer-policy", b"no-referrer"),
                      (b"content-security-policy",
                       b"default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'")]
                if config.ENV == "prod":
                    h.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                if scope["path"].startswith("/api/"):
                    h.append((b"cache-control", b"no-store"))
                msg["headers"] = h
            await send(msg)

        await self.app(scope, receive, enviar)


def _error_500(request, exc):
    traceback.print_exc()  # el detalle va al log, nunca al cliente
    return JSONResponse({"error": "Error interno del servidor"}, status_code=500)


def _404_api(request, exc):
    return JSONResponse({"error": "Recurso no encontrado"}, status_code=404)


def _405(request, exc):
    return JSONResponse({"error": "Método no permitido"}, status_code=405)


def crear_app():
    db.init_db()
    services.iniciar_respaldo_diario()
    services.iniciar_monitor_conexion()
    middleware = [Middleware(CabecerasSeguridad)]
    if config.CORS_ORIGINS:
        middleware.insert(0, Middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS,
                                        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                                        allow_headers=["Authorization", "Content-Type", "X-API-Key"]))
    rutas = list(api.routes)
    if os.path.isdir(FRONTEND):
        rutas.append(Mount("/", app=StaticFiles(directory=FRONTEND, html=True), name="web"))
    return Starlette(routes=rutas, middleware=middleware,
                     exception_handlers={500: _error_500, 405: _405})


app = crear_app()
