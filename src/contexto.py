"""Arma, para un cliente y un mes de cierre, todas las series mensuales que usan los KPIs.

La tabla `serie` tiene una fila por mes (desde el primer mes con datos hasta el mes de cierre) y
columnas como ventas_fact, costo:<rubro>, lab_931, iibb, resultado, caja, unidades_vendidas...
Un valor NaN significa "sin dato".
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import personal as mod_personal
from .clasificador import clasificar_banco, clasificar_compras
from .config import Cliente
from .util import mes_fin, mes_sumar, normalizar, rango_meses

ROLES_SUMA = ["unidades_producidas", "unidades_vendidas", "unidades_descartadas", "horas_parada"]


@dataclass
class Contexto:
    c: Cliente
    mes: str
    base: pd.DataFrame
    meses: list = field(default_factory=list)
    serie: pd.DataFrame = None
    emitidos: pd.DataFrame = None
    compras: pd.DataFrame = None          # recibidos clasificados
    gastos_banco: pd.DataFrame = None
    banco: pd.DataFrame = None
    parte: pd.DataFrame = None            # diario, una columna por rol
    semanal: pd.DataFrame = None
    estimados: list = field(default_factory=list)   # dicts: mes, concepto, valor, motivo
    personal: dict = None
    rubros_operativos: list = field(default_factory=list)
    fuentes: set = field(default_factory=set)
    caja_detalle: list = field(default_factory=list)
    datos_hasta: object = None            # última fecha de comprobantes cargados
    mes_incompleto: bool = False          # los comprobantes no llegan al fin del mes de cierre

    # --- helpers para la biblioteca de KPIs
    def v(self, col: str, mes: str | None = None):
        mes = mes or self.mes
        if col not in self.serie.columns or mes not in self.serie.index:
            return None
        x = self.serie.at[mes, col]
        return None if pd.isna(x) else float(x)

    def tiene(self, fuente: str) -> bool:
        return fuente in self.fuentes


def _por_mes(df: pd.DataFrame, col_mes: str, col_valor: str, meses: list) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(np.nan, index=meses)
    return df.groupby(col_mes)[col_valor].sum().reindex(meses)


def construir(c: Cliente, base: pd.DataFrame, mes: str) -> Contexto:
    ctx = Contexto(c=c, mes=mes, base=base)
    ctx.fuentes = set(base["fuente"].dropna().unique())

    em = base[base["fuente"] == "emitidos"].copy()
    em["importe"] = em["neto"] * em["signo"]
    ctx.emitidos = em
    ctx.compras = clasificar_compras(c, base[base["fuente"] == "recibidos"])
    ctx.banco = base[base["fuente"] == "banco"].copy()
    ctx.gastos_banco = clasificar_banco(c, ctx.banco)

    meses_datos = [m for m in base["mes"].dropna().unique() if m <= mes]
    primero = min(meses_datos) if meses_datos else mes
    # El histórico de ventas/compras define desde cuándo mostrar.
    m_ventas = em["mes"].dropna()
    if len(m_ventas):
        primero = min(m_ventas.min(), mes)
    ctx.meses = rango_meses(primero, mes)
    M = ctx.meses
    s = pd.DataFrame(index=pd.Index(M, name="mes"))

    # ------------------------------------------------ ventas
    s["ventas_fact"] = _por_mes(em, "mes", "importe", M)
    s["n_facturas"] = em[em["signo"] == 1].groupby("mes").size().reindex(M)
    if len(em):
        s["ventas_fact"] = s["ventas_fact"].fillna(0.0)
        s["n_facturas"] = s["n_facturas"].fillna(0)
    sc = base[base["fuente"] == "ventas_sc"]
    s["ventas_sc"] = _por_mes(sc, "mes", "valor", M)
    s["ventas_tot"] = s["ventas_fact"] + s["ventas_sc"].fillna(0)

    # ------------------------------------------------ compras por rubro
    rubros = c.rubros.get("rubros", [])
    rubro_personal = [r["nombre"] for r in rubros if r.get("personal")]
    ctx.rubros_operativos = [r["nombre"] for r in rubros
                             if r.get("operativo", True) and not r.get("personal")
                             and r["nombre"] != c.rubro_revisar]
    gb = ctx.gastos_banco.assign(mes_imputado=ctx.gastos_banco["mes"]) if len(ctx.gastos_banco) else None
    todos = pd.concat([x for x in [ctx.compras[["mes", "mes_imputado", "rubro", "importe"]] if len(ctx.compras) else None,
                                   gb[["mes", "mes_imputado", "rubro", "importe"]] if gb is not None else None]
                       if x is not None], ignore_index=True) if (len(ctx.compras) or gb is not None) else \
        pd.DataFrame(columns=["mes", "mes_imputado", "rubro", "importe"])
    hay_compras = "recibidos" in ctx.fuentes
    for r in [x["nombre"] for x in rubros]:
        sub = todos[todos["rubro"] == r]
        dev = _por_mes(sub, "mes_imputado", "importe", M)
        fac = _por_mes(sub, "mes", "importe", M)
        s["costo:" + r] = dev.fillna(0.0) if hay_compras else dev
        s["factura:" + r] = fac.fillna(0.0) if hay_compras else fac
    s["no_discriminado"] = _por_mes(ctx.compras, "mes", "no_discriminado", M)

    # Rubros a mes vencido: si la factura del mes siguiente todavía no llegó, se estima.
    fecha_max = ctx.compras["fecha"].max() if len(ctx.compras) else None
    estimar = c.empresa.get("estimar_faltantes", True)
    for r in [x for x in rubros if x.get("devengamiento") == "mes_anterior"]:
        nombre = r["nombre"]
        llegaron = set(ctx.compras.loc[ctx.compras["rubro"] == nombre, "mes"])
        if not llegaron:
            continue
        for m in M:
            if mes_sumar(m, 1) in llegaron:
                continue
            if fecha_max is not None and pd.Timestamp(mes_fin(mes_sumar(m, 1))) <= fecha_max:
                continue  # el mes siguiente ya está completo y no hubo factura: queda en 0
            ant = s.at[mes_sumar(m, -1), "costo:" + nombre] if mes_sumar(m, -1) in s.index else np.nan
            if estimar and pd.notna(ant) and ant != 0:
                s.at[m, "costo:" + nombre] = ant
                ctx.estimados.append({"mes": m, "concepto": nombre, "valor": float(ant),
                                      "motivo": f"la factura de {nombre} de este mes llega a principio del mes "
                                                "siguiente; se usa el valor del mes anterior"})
            else:
                s.at[m, "costo:" + nombre] = np.nan

    s["revisar"] = s["factura:" + c.rubro_revisar] if "factura:" + c.rubro_revisar in s else np.nan
    s["costos_operativos"] = s[["costo:" + r for r in ctx.rubros_operativos]].sum(axis=1, min_count=1)

    # ------------------------------------------------ F.931
    f = base[base["fuente"] == "f931"]
    f9 = f.pivot_table(index="mes", columns="concepto", values="valor", aggfunc="last") if len(f) else pd.DataFrame()
    for col, origen in [("lab_931", "costo_laboral"), ("contrib_931", "contribuciones"),
                        ("empleados_931", "empleados"), ("rem1_931", "rem1")]:
        s[col] = f9[origen].reindex(M) if origen in f9 else np.nan
    s["f931_estimado"] = False
    if len(f9):
        ultimo = max(f9.index)
        for m in M:
            if m > ultimo and pd.isna(s.at[m, "lab_931"]) and estimar:
                for col, origen in [("lab_931", "costo_laboral"), ("contrib_931", "contribuciones"),
                                    ("empleados_931", "empleados"), ("rem1_931", "rem1")]:
                    s.at[m, col] = f9.at[ultimo, origen]
                s.at[m, "f931_estimado"] = True
                ctx.estimados.append({"mes": m, "concepto": "Costo laboral F.931", "valor": float(s.at[m, "lab_931"]),
                                      "motivo": f"todavía no está el F.931 de este mes; se usa el último ({ultimo})"})

    # ------------------------------------------------ personal no registrado
    ctx.personal = mod_personal.calcular(c, base, ctx.compras, rubro_personal, M, s)
    s["pagos_nr"] = ctx.personal["pagos_nr"].reindex(M)
    s["lab_total"] = s["lab_931"].fillna(0) + s["pagos_nr"].fillna(0)
    s.loc[s["lab_931"].isna() & s["pagos_nr"].isna(), "lab_total"] = np.nan

    # ------------------------------------------------ IIBB
    iibb = _iibb(c, em, M)
    for k in ["iibb_min", "iibb_max", "iibb"]:
        s[k] = iibb[k]

    # ------------------------------------------------ resultado
    s["resultado"] = s["ventas_tot"] - s["costos_operativos"].fillna(0) - s["lab_total"].fillna(0) - s["iibb"].fillna(0)
    tipo = {r["nombre"]: r.get("tipo", "fijo") for r in rubros}
    var = ["costo:" + r for r in ctx.rubros_operativos if tipo.get(r) == "variable"]
    fij = ["costo:" + r for r in ctx.rubros_operativos if tipo.get(r) != "variable"]
    s["costos_variables"] = s[var].sum(axis=1).fillna(0) + s["iibb"].fillna(0) if var else s["iibb"].fillna(0)
    s["costos_fijos"] = (s[fij].sum(axis=1) if fij else 0) + s["lab_total"].fillna(0)

    # ------------------------------------------------ caja
    _caja(ctx, s)

    # ------------------------------------------------ parte operativo
    _parte(ctx, s)

    # ------------------------------------------------ señales del banco
    for col, clave in [("dep_efectivo", "efectivo"), ("haberes", "haberes")]:
        pats = [normalizar(p) for p in (c.empresa.get("banco") or {}).get(clave, [])]
        b = ctx.banco[(ctx.banco["concepto"] != "SALDO_FINAL")]
        if pats and len(b):
            mask = b["concepto"].map(lambda t: any(p in normalizar(t) for p in pats))
            s[col] = b[mask].groupby("mes")["valor"].sum().abs().reindex(M)
        else:
            s[col] = np.nan
    fechas = base.loc[base["fuente"].isin(["emitidos", "recibidos"]), "fecha"]
    ctx.datos_hasta = fechas.max() if len(fechas) else None
    ctx.mes_incompleto = ctx.datos_hasta is not None and ctx.datos_hasta < pd.Timestamp(mes_fin(mes))
    ctx.serie = s
    return ctx


def _iibb(c: Cliente, em: pd.DataFrame, M: list) -> pd.DataFrame:
    cfg = c.impuestos.get("iibb") or {}
    acts = {a["nombre"]: float(a["alicuota"]) for a in cfg.get("actividades", [])}
    out = pd.DataFrame(index=M, columns=["iibb_min", "iibb_max", "iibb"], dtype="float64")
    if not acts or em.empty:
        return out
    base = em.groupby("mes")["importe"].sum().reindex(M).fillna(0.0)
    crit = cfg.get("criterio", "pendiente")
    if crit == "pendiente":
        mn, mx = base * min(acts.values()), base * max(acts.values())
        uso = cfg.get("usar_en_resultado", "maximo")
        val = {"maximo": mx, "minimo": mn}.get(uso, (mn + mx) / 2)
        return pd.DataFrame({"iibb_min": mn, "iibb_max": mx, "iibb": val})
    if crit == "porcentaje":
        pct = cfg.get("porcentaje") or {}
        tasa = sum(float(pct.get(a, 0)) * t for a, t in acts.items())
        val = base * tasa
    else:
        if crit == "tipo_comprobante":
            mapa = {str(k): v for k, v in (cfg.get("tipo_comprobante") or {}).items()}
            act = [mapa.get(str(t), mapa.get(l, cfg.get("actividad_por_defecto"))) for t, l in
                   zip(em["tipo_cbte"].astype(str), em["letra"].astype(str))]
        else:  # lista_cuit
            lc = cfg.get("lista_cuit") or {}
            cuits = {str(x).replace("-", "") for x in lc.get("cuits", [])}
            act = [lc.get("actividad") if d in cuits else lc.get("resto") for d in em["doc"].astype(str)]
        t = pd.Series([acts.get(a, max(acts.values())) for a in act], index=em.index)
        val = (em["importe"] * t).groupby(em["mes"]).sum().reindex(M).fillna(0.0)
    return pd.DataFrame({"iibb_min": val, "iibb_max": val, "iibb": val})


def _es_inversion(c: Cliente, texto: str) -> bool:
    pats = (c.empresa.get("caja") or {}).get("cuentas_inversion", [])
    t = normalizar(texto)
    return any(normalizar(p) in t for p in pats if p)


def _caja(ctx: Contexto, s: pd.DataFrame) -> None:
    c, M = ctx.c, ctx.meses
    filas = []
    b = ctx.banco[ctx.banco["concepto"] == "SALDO_FINAL"]
    for r in b.itertuples():
        filas.append((r.mes, r.fecha, r.cuenta, r.valor))
    sal = ctx.base[ctx.base["fuente"] == "saldos"]
    for r in sal.itertuples():
        filas.append((r.mes, r.fecha, r.cuenta, r.valor))
    caja = pd.Series(np.nan, index=M)
    inv = pd.Series(np.nan, index=M)
    detalle = []
    if filas:
        d = pd.DataFrame(filas, columns=["mes", "fecha", "cuenta", "saldo"]).sort_values("fecha")
        d = d.groupby(["mes", "cuenta"]).last().reset_index()
        d["inversion"] = d["cuenta"].map(lambda x: _es_inversion(c, x))
        caja = d[~d["inversion"]].groupby("mes")["saldo"].sum().reindex(M)
        inv = d[d["inversion"]].groupby("mes")["saldo"].sum().reindex(M)
        detalle = d.to_dict("records")
    s["caja_bancos"] = caja
    s["inversiones"] = inv
    ctx.caja_detalle = detalle
    # Fondos de inversión: movimiento neto del mes (suscripciones - rescates), informativo.
    bm = ctx.banco[ctx.banco["concepto"] != "SALDO_FINAL"]
    if len(bm):
        mask = bm["concepto"].map(lambda x: _es_inversion(c, x))
        s["inversion_neta"] = (-bm[mask].groupby("mes")["valor"].sum()).reindex(M)
    else:
        s["inversion_neta"] = np.nan
    meses_prom = int((c.empresa.get("caja") or {}).get("meses_promedio_gasto_fijo", 3))
    s["gasto_fijo_diario"] = s["costos_fijos"].where(s["costos_fijos"] > 0).rolling(meses_prom, min_periods=1).mean() / 30


def _parte(ctx: Contexto, s: pd.DataFrame) -> None:
    p = ctx.base[ctx.base["fuente"] == "parte"]
    cols = ["unidades_vendidas", "unidades_producidas", "unidades_descartadas", "horas_parada", "stock_unidades",
            "stock_insumo", "kwh", "venta_diaria_7d", "produccion_diaria_7d", "caja_efectivo", "dias_parte"]
    for col in cols:
        s[col] = np.nan
    if p.empty:
        ctx.parte = pd.DataFrame()
        ctx.semanal = pd.DataFrame()
        s["caja"] = s["caja_bancos"]
        return
    d = p.pivot_table(index="fecha", columns="concepto", values="valor", aggfunc="last").sort_index()
    ctx.parte = d
    d = d.assign(mes=d.index.strftime("%Y-%m"))
    for m in ctx.meses:
        dm = d[d["mes"] == m]
        if dm.empty:
            continue
        s.at[m, "dias_parte"] = len(dm)
        for rol in ROLES_SUMA:
            if rol in dm:
                s.at[m, rol] = dm[rol].sum()
        for rol in ["stock_unidades", "stock_insumo", "caja_efectivo"]:
            if rol in dm and dm[rol].notna().any():
                s.at[m, rol] = dm[rol].dropna().iloc[-1]
        if "unidades_vendidas" in dm:
            s.at[m, "venta_diaria_7d"] = dm["unidades_vendidas"].dropna().tail(7).mean()
        if "unidades_producidas" in dm:
            s.at[m, "produccion_diaria_7d"] = dm["unidades_producidas"].dropna().tail(7).mean()
        if "lectura_medidor" in dm and dm["lectura_medidor"].notna().any():
            lect = dm["lectura_medidor"].dropna()
            previo = d[(d.index < dm.index[0])]["lectura_medidor"].dropna() if "lectura_medidor" in d else []
            if len(previo):
                s.at[m, "kwh"] = lect.iloc[-1] - previo.iloc[-1]
                s.at[m, "prod_para_kwh"] = dm["unidades_producidas"].sum() if "unidades_producidas" in dm else np.nan
            elif len(lect) > 1:
                s.at[m, "kwh"] = lect.iloc[-1] - lect.iloc[0]
                s.at[m, "prod_para_kwh"] = (dm.loc[dm.index > lect.index[0], "unidades_producidas"].sum()
                                            if "unidades_producidas" in dm else np.nan)
    s["caja"] = s["caja_bancos"].fillna(0) + s["caja_efectivo"].fillna(0)
    s.loc[s["caja_bancos"].isna() & s["caja_efectivo"].isna(), "caja"] = np.nan
    # Semanal
    w = ctx.parte.copy()
    w["semana"] = w.index.to_period("W-SUN").start_time
    agg = {k: "sum" for k in ROLES_SUMA if k in w}
    sem = w.groupby("semana").agg(agg)
    if "lectura_medidor" in w:
        lm = w.groupby("semana")["lectura_medidor"].agg(["first", "last"])
        sem["kwh"] = lm["last"] - lm["first"]
    ctx.semanal = sem
