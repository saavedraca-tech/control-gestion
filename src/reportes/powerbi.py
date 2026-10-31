"""Exportación para Power BI: tabla de hechos y dimensiones, MISMO esquema para todos los clientes.

Por cliente: clientes/<cliente>/powerbi/*.csv y *.parquet (historia completa, se pisa en cada cierre).
Estudio:     estudio/powerbi/*.csv y *.parquet = unión de todos los clientes (un solo modelo de Power BI).
Los CSV van con separador ';', coma decimal y UTF-8 con BOM (Power BI y Excel los abren sin configurar nada).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..biblioteca_kpis import BIBLIOTECA
from ..util import MESES, mes_sumar

TABLAS = {
    "hechos_movimientos": ["cliente_id", "fecha", "mes", "fuente", "tipo_cbte", "letra", "contraparte_id",
                           "rubro", "mes_imputado", "neto", "iva", "total", "importe", "concepto"],
    "hechos_kpis": ["cliente_id", "mes", "kpi_id", "valor", "meta_min", "meta_max", "semaforo", "estrella",
                    "temporada"],
    "dim_calendario": ["fecha", "mes", "anio", "mes_numero", "mes_nombre", "trimestre", "semana"],
    "dim_contrapartes": ["cliente_id", "contraparte_id", "doc", "nombre", "tipo", "rubro", "primera_fecha",
                         "ultima_fecha"],
    "dim_rubros": ["cliente_id", "rubro", "tipo", "devengamiento", "operativo", "personal"],
    "dim_kpis": ["cliente_id", "kpi_id", "nombre", "categoria", "unidad", "formula", "estrella"],
    "dim_empresa": ["cliente_id", "razon_social", "cuit", "rubro", "actividad", "jurisdiccion", "unidad"],
}


def _calendario(desde: str, hasta: str) -> pd.DataFrame:
    f = pd.date_range(desde + "-01", pd.Timestamp(mes_sumar(hasta, 1) + "-01") - pd.Timedelta(days=1), freq="D")
    return pd.DataFrame({"fecha": f, "mes": f.strftime("%Y-%m"), "anio": f.year, "mes_numero": f.month,
                         "mes_nombre": [MESES[m - 1] for m in f.month], "trimestre": f.quarter,
                         "semana": f.isocalendar().week.astype(int).values})


def tablas_cliente(ctx, kpis: pd.DataFrame) -> dict:
    c, cid = ctx.c, ctx.c.id
    em = ctx.emitidos.assign(rubro="Ventas", mes_imputado=ctx.emitidos["mes"])
    comp = ctx.compras
    gb = ctx.gastos_banco
    partes = []
    if len(em):
        partes.append(em.assign(contraparte_id="C-" + em["doc"].fillna("").replace("", "SD")))
    if len(comp):
        partes.append(comp.assign(contraparte_id="P-" + comp["doc"].fillna("")))
    if len(gb):
        partes.append(gb.assign(contraparte_id="B-" + gb["cuenta"].fillna(""), mes_imputado=gb["mes"],
                                neto=gb["importe"], total=gb["importe"]))
    mov = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=TABLAS["hechos_movimientos"])
    mov = mov.assign(cliente_id=cid)
    if "importe" not in mov:
        mov["importe"] = mov["neto"]
    hechos_mov = mov.reindex(columns=TABLAS["hechos_movimientos"])

    hk = kpis.rename(columns={"id": "kpi_id"}).assign(cliente_id=cid)
    hk["temporada"] = hk["mes"].map(c.temporada)
    hechos_kpis = hk.reindex(columns=TABLAS["hechos_kpis"])

    dims = []
    if len(em):
        g = em.assign(contraparte_id="C-" + em["doc"].fillna("").replace("", "SD")).groupby("contraparte_id")
        dims.append(pd.DataFrame({"doc": g["doc"].first(), "nombre": g["nombre"].last(), "tipo": "Cliente",
                                  "rubro": "Ventas", "primera_fecha": g["fecha"].min(),
                                  "ultima_fecha": g["fecha"].max()}).reset_index())
    if len(comp):
        g = comp.assign(contraparte_id="P-" + comp["doc"].fillna("")).groupby("contraparte_id")
        dims.append(pd.DataFrame({"doc": g["doc"].first(), "nombre": g["nombre"].last(), "tipo": "Proveedor",
                                  "rubro": g["rubro"].last(), "primera_fecha": g["fecha"].min(),
                                  "ultima_fecha": g["fecha"].max()}).reset_index())
    if len(gb):
        g = gb.assign(contraparte_id="B-" + gb["cuenta"].fillna("")).groupby("contraparte_id")
        dims.append(pd.DataFrame({"doc": "", "nombre": g["cuenta"].first(), "tipo": "Banco", "rubro": "",
                                  "primera_fecha": g["fecha"].min(), "ultima_fecha": g["fecha"].max()}).reset_index())
    dim_cp = (pd.concat(dims, ignore_index=True) if dims else pd.DataFrame()).assign(cliente_id=cid) \
        .reindex(columns=TABLAS["dim_contrapartes"])

    dim_rub = pd.DataFrame([{"cliente_id": cid, "rubro": r["nombre"], "tipo": r.get("tipo", "fijo"),
                             "devengamiento": r.get("devengamiento", "mes_factura"),
                             "operativo": bool(r.get("operativo", True)), "personal": bool(r.get("personal", False))}
                            for r in c.rubros.get("rubros", [])] +
                           [{"cliente_id": cid, "rubro": "Ventas", "tipo": "ingreso", "devengamiento": "mes_factura",
                             "operativo": True, "personal": False}]).reindex(columns=TABLAS["dim_rubros"])
    dk = kpis.drop_duplicates("id")
    dim_kpis = pd.DataFrame({"cliente_id": cid, "kpi_id": dk["id"], "nombre": dk["nombre"], "categoria": dk["categoria"],
                             "unidad": dk["unidad"], "formula": dk["formula"], "estrella": dk["estrella"]})
    e = c.empresa
    dim_emp = pd.DataFrame([{"cliente_id": cid, "razon_social": c.nombre, "cuit": c.cuit, "rubro": e.get("rubro"),
                             "actividad": e.get("actividad"), "jurisdiccion": e.get("jurisdiccion"),
                             "unidad": c.unidad}])
    return {"hechos_movimientos": hechos_mov, "hechos_kpis": hechos_kpis,
            "dim_calendario": _calendario(ctx.meses[0], ctx.mes).reindex(columns=TABLAS["dim_calendario"]),
            "dim_contrapartes": dim_cp, "dim_rubros": dim_rub, "dim_kpis": dim_kpis, "dim_empresa": dim_emp}


def _escribir(tablas: dict, carpeta: Path) -> None:
    carpeta.mkdir(parents=True, exist_ok=True)
    for nombre, df in tablas.items():
        df = df.reindex(columns=TABLAS[nombre])
        df.to_parquet(carpeta / f"{nombre}.parquet", index=False)
        df.to_csv(carpeta / f"{nombre}.csv", sep=";", decimal=",", index=False, encoding="utf-8-sig",
                  date_format="%Y-%m-%d")


def exportar_cliente(ctx, kpis) -> Path:
    carpeta = ctx.c.carpeta / "powerbi"
    _escribir(tablas_cliente(ctx, kpis), carpeta)
    return carpeta


def consolidar_estudio(base: Path) -> Path:
    destino = base / "estudio" / "powerbi"
    juntas = {}
    for carpeta in sorted((base / "clientes").glob("*/powerbi")):
        for nombre in TABLAS:
            f = carpeta / f"{nombre}.parquet"
            if f.exists():
                juntas.setdefault(nombre, []).append(pd.read_parquet(f))
    if not juntas:
        return destino
    tablas = {}
    for nombre, dfs in juntas.items():
        df = pd.concat([d for d in dfs if len(d)], ignore_index=True) if any(len(d) for d in dfs) else dfs[0]
        if nombre == "dim_calendario":
            df = df.drop_duplicates("fecha").sort_values("fecha")
        tablas[nombre] = df
    _escribir(tablas, destino)
    return destino
