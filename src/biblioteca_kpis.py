"""Biblioteca de KPIs. Cada KPI se define UNA vez y cada cliente activa los que usa en kpis.yaml.

Cada definición tiene: nombre (puede usar {unidad}, {unidades} y {rubro}), categoría, unidad de
medida (pesos, pct, dias, numero, unidades, decimal, horas), fuentes que necesita, fórmula en
castellano, frecuencia, qué pasa si no hay dato y la función de cálculo f(ctx, mes, **params).
La función devuelve None cuando no hay dato (el tablero muestra "sin dato" y semáforo gris).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from .util import mes_fin, mes_sumar


@dataclass
class KPIDef:
    id: str
    nombre: str
    categoria: str
    unidad: str
    fuentes: list
    formula: str
    fn: Callable
    frecuencia: str = "mensual"
    sin_dato: str = "Sin dato: falta la fuente."
    params: list = field(default_factory=list)


def _div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


# ----------------------------------------------------------------- clientes (se calcula una vez)

def _clientes(ctx):
    if getattr(ctx, "_cli", None) is not None:
        return ctx._cli
    em = ctx.emitidos
    em = em[em["doc"].fillna("") != ""]
    compras = em[em["signo"] == 1]
    por_mes = compras.groupby("mes")["doc"].apply(set).to_dict()
    primera = compras.groupby("doc")["mes"].min().to_dict()
    ctx._cli = {"por_mes": por_mes, "primera": primera, "em": em, "primer_mes": min(por_mes) if por_mes else None}
    return ctx._cli


def clientes_perdidos(ctx, mes):
    """Clientes cuya última compra quedó a más de N días del cierre del mes, y que cruzaron ese umbral
    este mes (para no contar dos veces al mismo cliente en meses sucesivos)."""
    dias = int((ctx.c.kpis.get("clientes") or {}).get("dias_perdido", 60))
    cli = _clientes(ctx)
    em = cli["em"]
    if em.empty:
        return None
    fin = pd.Timestamp(mes_fin(mes))
    fin_ant = pd.Timestamp(mes_fin(mes_sumar(mes, -1)))
    hasta = em[em["fecha"] <= fin].groupby("doc")["fecha"].max()
    lim, lim_ant = fin - pd.Timedelta(days=dias), fin_ant - pd.Timedelta(days=dias)
    if cli["primer_mes"] is None or pd.Timestamp(cli["primer_mes"] + "-01") > lim:
        return None  # todavía no hay historia suficiente
    return hasta[(hasta <= lim) & (hasta > lim_ant)].index.tolist()


def _activos(ctx, mes):
    return _clientes(ctx)["por_mes"].get(mes, set())


def k_clientes_activos(ctx, mes):
    if not ctx.tiene("emitidos"):
        return None
    return float(len(_activos(ctx, mes)))


def k_pct_recurrentes(ctx, mes):
    cli = _clientes(ctx)
    if not ctx.tiene("emitidos") or cli["primer_mes"] is None or mes <= cli["primer_mes"]:
        return None
    act = _activos(ctx, mes)
    prev = cli["por_mes"].get(mes_sumar(mes, -1), set()) | cli["por_mes"].get(mes_sumar(mes, -2), set())
    return _div(len(act & prev), len(act))


def k_clientes_nuevos(ctx, mes):
    cli = _clientes(ctx)
    if not ctx.tiene("emitidos") or cli["primer_mes"] is None or mes <= cli["primer_mes"]:
        return None
    return float(sum(1 for d in _activos(ctx, mes) if cli["primera"].get(d) == mes))


def k_clientes_perdidos(ctx, mes):
    p = clientes_perdidos(ctx, mes)
    return None if p is None else float(len(p))


def k_concentracion(ctx, mes):
    em = _clientes(ctx)["em"]
    em = em[em["mes"] == mes]
    total = ctx.v("ventas_fact", mes)
    if em.empty or not total:
        return None
    top = em.groupby("doc")["importe"].sum().nlargest(10).sum()
    return _div(top, total)


# ----------------------------------------------------------------- ventas

def k_ventas_fact(ctx, mes):
    return ctx.v("ventas_fact", mes) if ctx.tiene("emitidos") else None


def k_ventas_tot(ctx, mes):
    if not ctx.tiene("ventas_sc") or ctx.v("ventas_sc", mes) is None:
        return None
    return ctx.v("ventas_tot", mes)


def k_unidades(ctx, mes):
    return ctx.v("unidades_vendidas", mes)


def k_precio_unidad(ctx, mes):
    return _div(ctx.v("ventas_tot", mes), ctx.v("unidades_vendidas", mes))


def k_ticket(ctx, mes):
    return _div(ctx.v("ventas_fact", mes), ctx.v("n_facturas", mes))


def k_vs_anio_ant(ctx, mes):
    a, b = ctx.v("ventas_fact", mes), ctx.v("ventas_fact", mes_sumar(mes, -12))
    return None if (a is None or not b) else a / b - 1


# ----------------------------------------------------------------- finanzas

def k_resultado(ctx, mes):
    return ctx.v("resultado", mes) if ctx.tiene("emitidos") else None


def k_resultado_pct(ctx, mes):
    return _div(k_resultado(ctx, mes), ctx.v("ventas_tot", mes))


def k_mc_unidad(ctx, mes):
    v, cv, u = ctx.v("ventas_tot", mes), ctx.v("costos_variables", mes), ctx.v("unidades_vendidas", mes)
    return None if v is None or cv is None else _div(v - cv, u)


def k_mc_pct(ctx, mes):
    v, cv = ctx.v("ventas_tot", mes), ctx.v("costos_variables", mes)
    return None if v is None or cv is None else _div(v - cv, v)


def k_pe_pesos(ctx, mes):
    mc = k_mc_pct(ctx, mes)
    cf = ctx.v("costos_fijos", mes)
    return None if not mc or mc <= 0 or cf is None else cf / mc


def k_pe_unidades(ctx, mes):
    mcu = k_mc_unidad(ctx, mes)
    cf = ctx.v("costos_fijos", mes)
    return None if not mcu or mcu <= 0 or cf is None else cf / mcu


def k_caja_dias(ctx, mes):
    return _div(ctx.v("caja", mes), ctx.v("gasto_fijo_diario", mes))


def k_iibb_cargas(ctx, mes):
    i, cs = ctx.v("iibb", mes), ctx.v("contrib_931", mes)
    if i is None and cs is None:
        return None
    return _div((i or 0) + (cs or 0), ctx.v("ventas_tot", mes))


def k_revisar(ctx, mes):
    return ctx.v("revisar", mes) if ctx.tiene("recibidos") else None


def k_lab_ventas(ctx, mes):
    return _div(ctx.v("lab_total", mes), ctx.v("ventas_tot", mes))


def k_nr_cant(ctx, mes):
    return float(ctx.personal["n_no_registrados"]) if ctx.personal else None


def k_nr_pct(ctx, mes):
    if not ctx.personal or ctx.personal["n_no_registrados"] == 0:
        return 0.0 if ctx.personal else None
    return _div(ctx.v("pagos_nr", mes), ctx.v("lab_total", mes))


# ----------------------------------------------------------------- inventario

def k_cobertura(ctx, mes):
    return _div(ctx.v("stock_unidades", mes), ctx.v("venta_diaria_7d", mes))


def k_merma(ctx, mes):
    return _div(ctx.v("unidades_descartadas", mes), ctx.v("unidades_producidas", mes))


def k_stock_insumo(ctx, mes):
    return _div(ctx.v("stock_insumo", mes), ctx.v("produccion_diaria_7d", mes))


# ----------------------------------------------------------------- operaciones

def k_rubro_ventas(ctx, mes, rubro=None, vista="devengado"):
    col = ("costo:" if vista == "devengado" else "factura:") + str(rubro)
    if col not in ctx.serie.columns:
        return None
    valor = ctx.v(col, mes)
    if not ctx.serie.loc[:mes, col].fillna(0).abs().sum():
        return None  # el cliente nunca tuvo gastos en este rubro: no es "0 %", es "sin dato"
    if mes == ctx.mes and ctx.mes_incompleto and not valor and ctx.v(col, mes_sumar(mes, -1)):
        return None  # el mes no terminó y todavía no llegaron los comprobantes de este rubro
    return _div(valor, ctx.v("ventas_tot", mes))


def k_consumo_unitario(ctx, mes):
    return _div(ctx.v("kwh", mes), ctx.v("prod_para_kwh", mes))


def k_horas_parada(ctx, mes):
    return ctx.v("horas_parada", mes)


# ----------------------------------------------------------------- catálogo

_D = [
    # Ventas
    KPIDef("ventas_facturadas", "Ventas netas facturadas", "Ventas", "pesos", ["emitidos"],
           "Suma del neto (gravado + no gravado + exento) de los comprobantes emitidos; las notas de crédito restan.",
           k_ventas_fact),
    KPIDef("ventas_totales", "Ventas totales (con y sin comprobante)", "Ventas", "pesos", ["emitidos", "ventas_sc"],
           "Ventas facturadas + ventas sin comprobante cargadas.", k_ventas_tot,
           sin_dato="Sin dato: no se cargó ventas_sin_comprobante.csv."),
    KPIDef("unidades_vendidas", "{Unidades} vendidas", "Ventas", "unidades", ["parte"],
           "Suma de {unidades} vendidas del parte diario.", k_unidades, sin_dato="Sin dato: falta el parte diario."),
    KPIDef("precio_promedio_unidad", "Precio promedio por {unidad}", "Ventas", "pesos", ["emitidos", "parte"],
           "Ventas / {unidades} vendidas.", k_precio_unidad, sin_dato="Sin dato: falta el parte diario."),
    KPIDef("ticket_promedio", "Ticket promedio", "Ventas", "pesos", ["emitidos"],
           "Ventas facturadas / cantidad de facturas (sin notas de crédito).", k_ticket),
    KPIDef("clientes_activos", "Clientes activos", "Ventas", "numero", ["emitidos"],
           "Clientes distintos (por CUIT/DNI) que compraron en el mes. No cuenta consumidores finales anónimos.",
           k_clientes_activos),
    KPIDef("pct_recurrentes", "% de clientes recurrentes", "Ventas", "pct", ["emitidos"],
           "Clientes del mes que también compraron en alguno de los 2 meses anteriores / clientes activos.",
           k_pct_recurrentes, sin_dato="Sin dato: hace falta al menos un mes anterior."),
    KPIDef("clientes_nuevos", "Clientes nuevos", "Ventas", "numero", ["emitidos"],
           "Clientes cuya primera compra registrada es de este mes.", k_clientes_nuevos,
           sin_dato="Sin dato: es el primer mes con datos."),
    KPIDef("clientes_perdidos", "Clientes perdidos", "Ventas", "numero", ["emitidos"],
           "Clientes cuya última compra pasó a tener más de 60 días durante este mes.", k_clientes_perdidos,
           sin_dato="Sin dato: todavía no hay 60 días de historia."),
    KPIDef("concentracion_top10", "Concentración: 10 primeros clientes", "Ventas", "pct", ["emitidos"],
           "Ventas de los 10 clientes que más compraron en el mes / ventas facturadas.", k_concentracion),
    KPIDef("ventas_vs_anio_anterior", "Ventas vs. mismo mes del año anterior", "Ventas", "pct", ["emitidos"],
           "Ventas del mes / ventas del mismo mes del año anterior − 1.", k_vs_anio_ant,
           sin_dato="Sin dato: no hay datos del año anterior."),
    # Finanzas
    KPIDef("resultado_operativo", "Resultado operativo", "Finanzas", "pesos", ["emitidos", "recibidos", "f931"],
           "Ventas − costos operativos por rubro − costo laboral total − IIBB. No incluye gastos A REVISAR.",
           k_resultado),
    KPIDef("resultado_operativo_pct", "Resultado operativo %", "Finanzas", "pct", ["emitidos", "recibidos", "f931"],
           "Resultado operativo / ventas.", k_resultado_pct),
    KPIDef("margen_contribucion_unidad", "Margen de contribución por {unidad}", "Finanzas", "pesos",
           ["emitidos", "recibidos", "parte"],
           "(Ventas − costos variables − IIBB) / {unidades} vendidas.", k_mc_unidad,
           sin_dato="Sin dato: falta el parte diario."),
    KPIDef("margen_contribucion_pct", "Margen de contribución %", "Finanzas", "pct", ["emitidos", "recibidos"],
           "(Ventas − costos variables − IIBB) / ventas.", k_mc_pct),
    KPIDef("punto_equilibrio_pesos", "Punto de equilibrio mensual ($)", "Finanzas", "pesos", ["emitidos", "recibidos"],
           "Costos fijos (rubros fijos + costo laboral) / margen de contribución %.", k_pe_pesos,
           sin_dato="Sin dato: el margen de contribución es negativo o no hay datos."),
    KPIDef("punto_equilibrio_unidades", "Punto de equilibrio mensual ({unidades})", "Finanzas", "unidades",
           ["emitidos", "recibidos", "parte"],
           "Costos fijos / margen de contribución por {unidad}.", k_pe_unidades,
           sin_dato="Sin dato: falta el parte diario o el margen es negativo."),
    KPIDef("caja_dias", "Caja en días de gastos fijos", "Finanzas", "dias", ["banco|saldos|parte"],
           "Saldo de bancos + efectivo a fin de mes (sin inversiones) / gasto fijo diario promedio de 3 meses.",
           k_caja_dias, sin_dato="Sin dato: falta el extracto o saldos.csv del mes."),
    KPIDef("iibb_cargas_ventas", "(IIBB + cargas sociales) / ventas", "Finanzas", "pct", ["emitidos", "f931"],
           "(IIBB estimado + contribuciones patronales, ART y seguro de vida del F.931) / ventas.", k_iibb_cargas),
    KPIDef("gastos_a_revisar", "Gastos A REVISAR", "Finanzas", "pesos", ["recibidos"],
           "Neto de compras sin regla o con patrón de gasto personal. Quedan fuera del resultado.", k_revisar),
    KPIDef("costo_laboral_ventas", "Costo laboral total / ventas", "Finanzas", "pct", ["emitidos", "f931"],
           "(Costo F.931 + pagos a personal no registrado) / ventas.", k_lab_ventas),
    KPIDef("personal_no_registrado_cant", "Personas no registradas", "Finanzas", "numero", ["personal.yaml"],
           "Cantidad de personas marcadas como no registradas en personal.yaml.", k_nr_cant),
    KPIDef("personal_no_registrado_pct", "% del costo laboral no registrado", "Finanzas", "pct",
           ["pagos_personal", "f931"],
           "Pagos a personal no registrado / costo laboral total.", k_nr_pct,
           sin_dato="Sin dato: falta pagos_personal.csv del mes."),
    # Inventario
    KPIDef("dias_cobertura", "Días de cobertura de stock", "Inventario", "dias", ["parte"],
           "{Unidades} en stock al último día / venta diaria promedio de los últimos 7 días.", k_cobertura,
           sin_dato="Sin dato: falta el parte diario."),
    KPIDef("merma_pct", "Merma %", "Inventario", "pct", ["parte"],
           "{Unidades} descartadas / {unidades} producidas.", k_merma, sin_dato="Sin dato: falta el parte diario."),
    KPIDef("dias_stock_insumo", "Días de stock de insumo clave", "Inventario", "dias", ["parte"],
           "Stock del insumo al último día / producción diaria promedio de los últimos 7 días.", k_stock_insumo,
           sin_dato="Sin dato: falta el parte diario."),
    # Operaciones
    KPIDef("rubro_sobre_ventas", "{rubro} / ventas", "Operaciones", "pct", ["emitidos", "recibidos"],
           "Gasto del rubro {rubro} (imputado al mes de consumo) / ventas.", k_rubro_ventas, params=["rubro", "vista"]),
    KPIDef("consumo_unitario", "Consumo por {unidad}", "Operaciones", "decimal", ["parte"],
           "Diferencia de lecturas del medidor / {unidades} producidas.", k_consumo_unitario,
           sin_dato="Sin dato: falta el parte diario con lecturas del medidor."),
    KPIDef("horas_parada", "Horas de parada", "Operaciones", "horas", ["parte"],
           "Suma de horas de parada del parte diario.", k_horas_parada, sin_dato="Sin dato: falta el parte diario."),
]

BIBLIOTECA = {k.id: k for k in _D}
