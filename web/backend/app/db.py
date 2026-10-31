"""Acceso a PostgreSQL (Supabase) con psycopg 3. Consultas simples, sin ORM."""
from __future__ import annotations

from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import ajustes


@contextmanager
def conexion():
    with psycopg.connect(ajustes.database_url, row_factory=dict_row, autocommit=False) as cx:
        yield cx


def uno(sql: str, params=()) -> dict | None:
    with conexion() as cx:
        r = cx.execute(sql, params).fetchone()
        cx.commit()
        return r


def varios(sql: str, params=()) -> list[dict]:
    with conexion() as cx:
        r = cx.execute(sql, params).fetchall()
        cx.commit()
        return r


def ejecutar(sql: str, params=()) -> None:
    with conexion() as cx:
        cx.execute(sql, params)
        cx.commit()


def auditar(estudio_id, usuario_id, accion: str, entidad: str, entidad_id=None, detalle: dict | None = None):
    ejecutar("insert into auditoria (estudio_id, usuario_id, accion, entidad, entidad_id, detalle) "
             "values (%s,%s,%s,%s,%s,%s)",
             (estudio_id, usuario_id, accion, entidad, str(entidad_id) if entidad_id else None, Jsonb(detalle or {})))


__all__ = ["conexion", "uno", "varios", "ejecutar", "auditar", "Jsonb"]
