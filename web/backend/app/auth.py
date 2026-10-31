"""Autenticación con Supabase Auth.

El navegador inicia sesión con Supabase (email + contraseña o enlace mágico) y manda el access token
en `Authorization: Bearer ...`. La API lo valida preguntándole a Supabase (/auth/v1/user), lo que
funciona igual con claves JWT simétricas o asimétricas. El usuario debe existir en la tabla `usuarios`;
los emails de ADMIN_EMAILS se dan de alta solos la primera vez (y crean el estudio si no existe).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
from fastapi import Header, HTTPException

from . import db
from .config import ajustes

_cache: dict[str, tuple[float, dict]] = {}


@dataclass
class Usuario:
    id: str
    email: str
    estudio_id: str
    rol: str

    @property
    def es_consultor(self) -> bool:
        return self.rol in ("admin", "consultor")


def _validar_token(token: str) -> dict:
    ahora = time.time()
    if token in _cache and _cache[token][0] > ahora:
        return _cache[token][1]
    r = httpx.get(f"{ajustes.supabase_url}/auth/v1/user", timeout=15,
                  headers={"Authorization": f"Bearer {token}", "apikey": ajustes.supabase_service_key})
    if r.status_code != 200:
        raise HTTPException(401, "Sesión vencida o inválida. Volvé a iniciar sesión.")
    datos = r.json()
    _cache[token] = (ahora + 60, datos)
    return datos


def _usuario_desde(uid: str, email: str) -> Usuario:
    fila = db.uno("select id::text, email, estudio_id::text, rol from usuarios where id = %s", (uid,))
    if fila:
        return Usuario(fila["id"], fila["email"], fila["estudio_id"], fila["rol"])
    if email.lower() in ajustes.admin_emails:
        est = db.uno("select id::text from estudios order by creado_en limit 1") or \
            db.uno("insert into estudios (nombre) values (%s) returning id::text", (ajustes.nombre_estudio,))
        db.ejecutar("insert into usuarios (id, estudio_id, email, rol) values (%s,%s,%s,'admin') "
                    "on conflict (id) do nothing", (uid, est["id"], email))
        return Usuario(uid, email, est["id"], "admin")
    raise HTTPException(403, f"{email} no tiene acceso. Pedile a un administrador del estudio que te invite.")


def usuario_actual(authorization: str | None = Header(None),
                   x_usuario_dev: str | None = Header(None)) -> Usuario:
    if ajustes.auth == "dev":
        # Desarrollo/tests: "uuid|email"
        if not x_usuario_dev:
            raise HTTPException(401, "Falta X-Usuario-Dev")
        uid, email = x_usuario_dev.split("|", 1)
        return _usuario_desde(uid, email)
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Iniciá sesión.")
    datos = _validar_token(authorization.split(" ", 1)[1])
    return _usuario_desde(datos["id"], datos.get("email", ""))
