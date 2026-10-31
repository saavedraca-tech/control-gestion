"""Ranking de clientes, nuevos, perdidos y lista para llamar."""
from __future__ import annotations

import pandas as pd

from .util import mes_fin, mes_sumar


def ranking(ctx) -> pd.DataFrame:
    mes = ctx.mes
    dias_perdido = int((ctx.c.kpis.get("clientes") or {}).get("dias_perdido", 60))
    em = ctx.emitidos
    em = em[(em["mes"] <= mes)]
    if em.empty:
        return pd.DataFrame(columns=["doc", "nombre", "ventas_mes", "ventas_12m", "ventas_anio", "meses_con_compra",
                                     "primera_compra", "ultima_compra", "dias_sin_comprar", "estado"])
    em = em.assign(doc=em["doc"].fillna("").replace("", "SIN_IDENTIFICAR"))
    fin = pd.Timestamp(mes_fin(mes))
    desde12 = mes_sumar(mes, -11)
    nombres = em.sort_values("fecha").groupby("doc")["nombre"].last()
    g = em.groupby("doc")
    df = pd.DataFrame({
        "nombre": nombres,
        "ventas_mes": em[em["mes"] == mes].groupby("doc")["importe"].sum(),
        "ventas_12m": em[em["mes"] >= desde12].groupby("doc")["importe"].sum(),
        "ventas_anio": em[em["mes"].str[:4] == mes[:4]].groupby("doc")["importe"].sum(),
        "meses_con_compra": em[em["signo"] == 1].groupby("doc")["mes"].nunique(),
        "primera_compra": g["fecha"].min(),
        "ultima_compra": em[em["signo"] == 1].groupby("doc")["fecha"].max(),
    }).fillna({"ventas_mes": 0.0, "ventas_12m": 0.0, "ventas_anio": 0.0, "meses_con_compra": 0})
    df["dias_sin_comprar"] = (fin - df["ultima_compra"]).dt.days
    primer_mes = em["mes"].min()

    def estado(r):
        if r.name == "SIN_IDENTIFICAR":
            return "Consumidor final"
        if r["primera_compra"].strftime("%Y-%m") == mes and mes != primer_mes:
            return "Nuevo"
        if r["ventas_mes"] > 0:
            return "Activo"
        if r["dias_sin_comprar"] > dias_perdido:
            return "Perdido"
        return "En riesgo"
    df["estado"] = df.apply(estado, axis=1)
    df.loc["SIN_IDENTIFICAR", "nombre"] = "Consumidor final sin identificar" if "SIN_IDENTIFICAR" in df.index else None
    df = df.dropna(subset=["nombre"])
    return df.reset_index().rename(columns={"index": "doc"}).sort_values(
        ["ventas_mes", "ventas_12m"], ascending=False).reset_index(drop=True)


def para_llamar(ctx, rk: pd.DataFrame, maximo: int = 30) -> pd.DataFrame:
    mes = ctx.mes
    dias_perdido = int((ctx.c.kpis.get("clientes") or {}).get("dias_perdido", 60))
    activos_prev = set(ctx.emitidos.loc[ctx.emitidos["mes"].isin([mes_sumar(mes, -1), mes_sumar(mes, -2)]), "doc"])
    rk = rk[rk["doc"] != "SIN_IDENTIFICAR"]
    perdidos = rk[(rk["estado"] == "Perdido") & (rk["meses_con_compra"] >= 2)].assign(
        motivo=lambda x: "Perdido: " + x["dias_sin_comprar"].astype(int).astype(str) + " días sin comprar")
    dejaron = rk[(rk["ventas_mes"] <= 0) & rk["doc"].isin(activos_prev) & (rk["meses_con_compra"] >= 3)
                 & (rk["dias_sin_comprar"] <= dias_perdido)].assign(
        motivo="Recurrente que no compró este mes")
    out = pd.concat([dejaron, perdidos]).sort_values("ventas_12m", ascending=False).head(maximo)
    return out.reset_index(drop=True)
