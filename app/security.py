"""Autenticación y autorización.

- Usuarios: contraseña con hash (bcrypt; scrypt de la biblioteca estándar si bcrypt
  no está instalado) y sesión con JWT de 60 minutos.
- Dispositivos: API Key aleatoria de 256 bits; en la BD solo se guarda su SHA-256.
- Autorización por rol validada en cada endpoint (decorador `requiere`).
"""
import base64
import functools
import hashlib
import hmac
import os
import re
import secrets
import time
from datetime import timedelta

import jwt
from starlette.responses import JSONResponse

from . import config, db

try:  # bcrypt es lo definido en la ES2; scrypt es respaldo para entornos sin bcrypt
    import bcrypt as _bcrypt
except Exception:  # pragma: no cover
    _bcrypt = None


# ---------------------------------------------------------------- contraseñas
def validar_politica(clave: str):
    """Devuelve None si cumple o el texto del requisito incumplido."""
    if len(clave) < config.MIN_CLAVE:
        return f"La contraseña debe tener al menos {config.MIN_CLAVE} caracteres."
    if not re.search(r"[A-Za-z]", clave) or not re.search(r"\d", clave):
        return "La contraseña debe combinar letras y números."
    return None


def hash_clave(clave: str) -> str:
    if _bcrypt:
        return "bcrypt$" + _bcrypt.hashpw(clave.encode()[:72], _bcrypt.gensalt(12)).decode()
    salt = os.urandom(16)
    h = hashlib.scrypt(clave.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()


def verificar_clave(clave: str, almacenado: str) -> bool:
    try:
        esquema, resto = almacenado.split("$", 1)
        if esquema == "bcrypt":
            return bool(_bcrypt) and _bcrypt.checkpw(clave.encode()[:72], resto.encode())
        if esquema == "scrypt":
            s, h = resto.split("$")
            calc = hashlib.scrypt(clave.encode(), salt=base64.b64decode(s), n=2**14, r=8, p=1, dklen=32)
            return hmac.compare_digest(calc, base64.b64decode(h))
    except Exception:
        pass
    return False


# ---------------------------------------------------------------- JWT
def crear_token(usuario: dict, rol: str) -> str:
    ahora = db.utcnow()
    payload = {
        "sub": str(usuario["id"]),
        "rol": rol,
        "iat": int(ahora.timestamp()),
        "exp": int((ahora + timedelta(minutes=config.JWT_MINUTOS)).timestamp()),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALG)


def leer_token(token: str):
    return jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALG])


# ---------------------------------------------------------------- API Key
def generar_api_key(id_dispositivo: int) -> str:
    return f"aq_{id_dispositivo}_{secrets.token_urlsafe(32)}"


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def id_desde_api_key(key: str):
    m = re.fullmatch(r"aq_(\d+)_[A-Za-z0-9_\-]{20,}", key or "")
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- límite de tasa
_ventanas: dict = {}


def excede_tasa(clave: str) -> bool:
    ahora = time.time()
    desde = ahora - 60
    marcas = [t for t in _ventanas.get(clave, []) if t > desde]
    marcas.append(ahora)
    _ventanas[clave] = marcas
    return len(marcas) > config.RATE_LIMIT_POR_MIN


# ---------------------------------------------------------------- respuestas
def error(status: int, mensaje: str, **extra):
    return JSONResponse({"error": mensaje, **extra}, status_code=status)


# ---------------------------------------------------------------- decoradores
def requiere(*roles, dispositivo=False):
    """Protege un endpoint. `roles` = roles de usuario permitidos (vacío = cualquier
    usuario autenticado). `dispositivo=True` exige API Key en lugar de JWT."""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(request):
            if dispositivo:
                key = request.headers.get("x-api-key", "")
                did = id_desde_api_key(key)
                if did is None:
                    return error(401, "API Key ausente o con formato inválido")
                if excede_tasa(f"dev{did}"):
                    return error(429, "Demasiadas solicitudes; reintente en un minuto")
                with db.connect() as c:
                    d = c.one("SELECT * FROM dispositivo WHERE id = ?", (did,))
                if not d or not hmac.compare_digest(d["hash_api_key"], hash_api_key(key)):
                    return error(401, "API Key inválida")
                if not d["activo"]:
                    return error(403, "Dispositivo desactivado")
                request.state.dispositivo = d
                return fn(request)

            auth = request.headers.get("authorization", "")
            if not auth.lower().startswith("bearer "):
                return error(401, "Falta el token de sesión")
            try:
                datos = leer_token(auth[7:].strip())
            except jwt.ExpiredSignatureError:
                return error(401, "La sesión expiró; inicie sesión nuevamente")
            except jwt.PyJWTError:
                return error(401, "Token inválido")
            with db.connect() as c:
                u = c.one(
                    "SELECT u.*, r.nombre AS rol FROM usuario u JOIN rol r ON r.id = u.id_rol WHERE u.id = ?",
                    (int(datos["sub"]),),
                )
            if not u or not u["activo"]:
                return error(401, "Usuario inexistente o desactivado")
            if roles and u["rol"] not in roles:
                return error(403, "Su rol no tiene permiso para esta acción")
            request.state.usuario = u
            return fn(request)

        return wrapper

    return deco
