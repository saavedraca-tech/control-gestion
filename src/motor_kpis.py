"""Evalúa los KPIs activos de un cliente (kpis.yaml) para cada mes y calcula el semáforo.

Metas en kpis.yaml:
  meta: 0.40            + direccion: "≤"     -> verde si valor <= 40 %
  meta: [2, 4]                               -> verde entre 2 y 4
  meta: {alta: [2, 4], baja: [null, 2]}      -> meta distinta por temporada (empresa.yaml)
  solo_meses: [5, 6, 7, 8]                   -> la meta aplica sólo en esos meses
  tolerancia: 0.05                           -> amarillo si se desvía hasta 1 tolerancia; rojo si más
"""
from __future__ import annotations

import pandas as pd

from .biblioteca_kpis import BIBLIOTECA
from .util import fmt_valor, mes_sumar

VERDE, AMARILLO, ROJO, GRIS, SIN_META = "verde", "amarillo", "rojo", "gris", "sin meta"


def _rango(meta, direccion):
    if meta is None:
        return None
    if isinstance(meta, (list, tuple)):
        a = meta[0] if len(meta) > 0 else None
        b = meta[1] if len(meta) > 1 else None
        return (None if a is None else float(a), None if b is None else float(b))
    if direccion in ("≤", "<="):
        return (None, float(meta))
    return (float(meta), None)


def meta_del_mes(kcfg: dict, cliente, mes: str):
    meta = kcfg.get("meta")
    solo = kcfg.get("solo_meses")
    if solo and int(mes[5:7]) not in [int(x) for x in solo]:
        return None
    if isinstance(meta, dict):
        meta = meta.get(cliente.temporada(mes))
    return _rango(meta, kcfg.get("direccion", "≥"))


def texto_meta(rango, unidad: str) -> str:
    if rango is None:
        return "—"
    a, b = rango
    if a is not None and b is not None:
        return f"entre {fmt_valor(a, unidad)} y {fmt_valor(b, unidad)}"
    if a is not None:
        return f"≥ {fmt_valor(a, unidad)}"
    return f"≤ {fmt_valor(b, unidad)}"


def semaforo(valor, rango, tolerancia) -> tuple[str, float | None]:
    if valor is None:
        return GRIS, None
    if rango is None:
        return SIN_META, None
    a, b = rango
    desvio = 0.0
    if a is not None and valor < a:
        desvio = a - valor
    elif b is not None and valor > b:
        desvio = valor - b
    tol = float(tolerancia or 0)
    if desvio <= 1e-9:
        return VERDE, 0.0
    return (AMARILLO if desvio <= tol + 1e-9 else ROJO), desvio


def nombre_kpi(defi, kcfg: dict, cliente) -> str:
    if kcfg.get("nombre"):
        return kcfg["nombre"]
    u, us = cliente.unidad, cliente.unidad_plural
    return defi.nombre.format(unidad=u, unidades=us, Unidades=us.capitalize(),
                              rubro=(kcfg.get("params") or {}).get("rubro", ""))


def formula_kpi(defi, kcfg: dict, cliente) -> str:
    u, us = cliente.unidad, cliente.unidad_plural
    return defi.formula.format(unidad=u, unidades=us, Unidades=us.capitalize(),
                               rubro=(kcfg.get("params") or {}).get("rubro", ""))


def evaluar(ctx) -> pd.DataFrame:
    """Una fila por KPI activo y mes."""
    c = ctx.c
    filas = []
    for orden, kcfg in enumerate(c.kpis.get("kpis", [])):
        if kcfg.get("activo", True) is False:
            continue
        base_id = kcfg.get("base", kcfg["id"])
        defi = BIBLIOTECA[base_id]
        params = kcfg.get("params") or {}
        nombre = nombre_kpi(defi, kcfg, c)
        for mes in ctx.meses:
            try:
                valor = defi.fn(ctx, mes, **params)
            except (KeyError, ZeroDivisionError, TypeError):
                valor = None
            rango = meta_del_mes(kcfg, c, mes)
            sem, desvio = semaforo(valor, rango, kcfg.get("tolerancia"))
            filas.append({
                "id": kcfg["id"], "base": base_id, "nombre": nombre, "categoria": defi.categoria,
                "unidad": kcfg.get("unidad", defi.unidad), "estrella": bool(kcfg.get("estrella", False)),
                "orden": orden, "mes": mes, "valor": valor,
                "meta_min": rango[0] if rango else None, "meta_max": rango[1] if rango else None,
                "meta_txt": texto_meta(rango, kcfg.get("unidad", defi.unidad)),
                "tolerancia": kcfg.get("tolerancia"), "semaforo": sem, "desvio": desvio,
                "formula": formula_kpi(defi, kcfg, c), "sin_dato": defi.sin_dato,
                "nota": kcfg.get("nota", ""),
            })
    return pd.DataFrame(filas)


def tabla_mes(kpis: pd.DataFrame, mes: str) -> pd.DataFrame:
    """KPIs del mes con valor del mes anterior y del mismo mes del año anterior."""
    act = kpis[kpis["mes"] == mes].copy()
    idx = kpis.set_index(["id", "mes"])["valor"]
    act["mes_anterior"] = [idx.get((i, mes_sumar(mes, -1))) for i in act["id"]]
    act["anio_anterior"] = [idx.get((i, mes_sumar(mes, -12))) for i in act["id"]]
    return act.sort_values("orden").reset_index(drop=True)
