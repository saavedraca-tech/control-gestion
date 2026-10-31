"""Lectores comunes a todos los clientes.

Cada lector devuelve un DataFrame con el esquema largo COLUMNAS: una fila por comprobante,
movimiento bancario, concepto del F.931, variable del parte diario, etc.
"""
from __future__ import annotations

import pandas as pd

COLUMNAS = [
    "fuente",          # emitidos | recibidos | f931 | banco | saldos | parte | pagos_personal | ventas_sc
    "clave",           # identificador único dentro de la fuente (para no duplicar)
    "archivo",         # nombre del archivo de origen
    "fecha",           # fecha del comprobante / movimiento / día
    "mes",             # AAAA-MM de la fecha (o período, en el F.931)
    "tipo_cbte",       # código ARCA del comprobante
    "letra",           # A, B, C, M, E o '' (tiques y otros)
    "signo",           # 1 o -1 (notas de crédito)
    "doc",             # CUIT/DNI de la contraparte
    "nombre",          # razón social de la contraparte / persona / detalle
    "concepto",        # concepto (F.931, banco, parte, ventas sin comprobante)
    "cuenta",          # cuenta bancaria o de caja
    "neto",            # neto sin IVA (gravado + no gravado + exento), en pesos y sin signo
    "iva",
    "otros_trib",
    "no_discriminado", # parte del total que no está en neto + IVA + otros (p. ej. impuestos en tiques)
    "total",
    "valor",           # importe o cantidad genérica (banco, F.931, parte, pagos)
    "saldo",           # saldo bancario luego del movimiento
]

NUMERICAS = ["neto", "iva", "otros_trib", "no_discriminado", "total", "valor", "saldo"]


def vacio() -> pd.DataFrame:
    return normalizar(pd.DataFrame(columns=COLUMNAS))


def normalizar(df: pd.DataFrame) -> pd.DataFrame:
    for c in COLUMNAS:
        if c not in df.columns:
            df[c] = None
    df = df[COLUMNAS].copy()
    for c in NUMERICAS:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
    df["signo"] = pd.to_numeric(df["signo"], errors="coerce").fillna(1).astype("int64")
    df["tipo_cbte"] = pd.to_numeric(df["tipo_cbte"], errors="coerce").astype("Int64")
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce").astype("datetime64[ns]")
    for c in ["fuente", "clave", "archivo", "mes", "letra", "doc", "nombre", "concepto", "cuenta"]:
        df[c] = df[c].astype("string")
    return df
