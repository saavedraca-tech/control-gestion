"""Tablero_<cliente>_AAAA-MM.xlsx (openpyxl).

Convención de colores (tomada de la planilla modelo del estudio):
  texto azul = dato que se carga a mano · fondo gris = cálculo/fórmula · fondo amarillo = supuesto o
  dato estimado a revisar · encabezados gris oscuro · secciones celeste.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .. import clientes_analisis
from ..util import (FORMATO_EXCEL, FORMATO_FECHA_EXCEL, ErrorUsuario, fmt_pesos, fmt_valor, mes_nombre,
                    mes_sumar)
from ..alertas import _USO
from . import decisiones as mod_dec

# ------------------------------------------------------------------ estilos
C_ENCAB, C_SECCION, C_META, C_CALC, C_SUPUESTO = "595959", "D9E1F2", "1F4E78", "F2F2F2", "FFF2CC"
AZUL_CARGA = "0000FF"
SEM = {  # fondo, texto, etiqueta
    "verde": ("C6EFCE", "006100", "● EN META"),
    "amarillo": ("FFEB9C", "9C5700", "● ATENCIÓN"),
    "rojo": ("FFC7CE", "9C0006", "● FUERA DE META"),
    "gris": ("D9D9D9", "595959", "○ SIN DATO"),
    "sin meta": ("FFFFFF", "7F7F7F", "— sin meta"),
}
GRAV = {"Alta": ("FFC7CE", "9C0006"), "Media": ("FFEB9C", "9C5700"), "Info": ("DDEBF7", "1F4E78")}
FINO = Side(style="thin", color="BFBFBF")
BORDE = Border(left=FINO, right=FINO, top=FINO, bottom=FINO)


def _fill(color):
    return PatternFill("solid", fgColor=color)


def _titulo(ws, texto, sub=None, ancho=10):
    ws["A1"] = texto
    ws["A1"].font = Font(bold=True, size=15, color=C_META)
    if sub:
        ws["A2"] = sub
        ws["A2"].font = Font(italic=True, size=9, color="595959")
    ws.sheet_view.showGridLines = False


def _encabezado(ws, fila, col, textos, color=C_ENCAB):
    for i, t in enumerate(textos):
        cel = ws.cell(row=fila, column=col + i, value=t)
        cel.font = Font(bold=True, color="FFFFFF")
        cel.fill = _fill(color)
        cel.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cel.border = BORDE


def _seccion(ws, fila, texto, hasta_col=8):
    cel = ws.cell(row=fila, column=1, value=texto)
    cel.font = Font(bold=True, color=C_META, size=11)
    for c in range(1, hasta_col + 1):
        ws.cell(row=fila, column=c).fill = _fill(C_SECCION)


def _num(cel, valor, unidad="pesos"):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        cel.value = "sin dato"
        cel.font = Font(italic=True, color="7F7F7F")
        cel.alignment = Alignment(horizontal="right")
    else:
        cel.value = float(valor)
        cel.number_format = FORMATO_EXCEL.get(unidad, "#,##0")
    cel.border = BORDE


def _sem(cel, semaforo):
    bg, fg, txt = SEM.get(semaforo, SEM["gris"])
    cel.value = txt
    cel.fill = _fill(bg)
    cel.font = Font(bold=True, color=fg)
    cel.alignment = Alignment(horizontal="center", vertical="center")
    cel.border = BORDE


def _anchos(ws, anchos: dict):
    for col, w in anchos.items():
        ws.column_dimensions[col].width = w


# ------------------------------------------------------------------ hojas

def hoja_tablero(wb, ctx, tabla, alertas, escenario):
    c, mes, s = ctx.c, ctx.mes, ctx.serie
    ws = wb.active
    ws.title = "Tablero"
    fecha_datos = ctx.base["fecha"].max()
    _titulo(ws, f"Tablero de control · {c.nombre} · {mes_nombre(mes)}",
            f"CUIT {c.empresa.get('cuit')} · {c.empresa.get('actividad', '')} · temporada {c.temporada(mes)} · "
            f"datos hasta {fecha_datos.strftime('%d/%m/%Y') if pd.notna(fecha_datos) else '—'} · "
            f"generado el {date.today().strftime('%d/%m/%Y')}")
    for i in range(1, 17):
        ws.column_dimensions[get_column_letter(i)].width = 12.5

    # Avisos permanentes
    fila = 3
    avisos = []
    if ctx.personal and ctx.personal["n_no_registrados"]:
        avisos.append(("rojo", f"⚠ Hay {ctx.personal['n_no_registrados']} persona(s) trabajando sin registrar. "
                               "Ver hoja Personal (escenario de regularización)."))
    iibb = c.impuestos.get("iibb") or {}
    if iibb.get("criterio", "pendiente") == "pendiente" and pd.notna(s.at[mes, "iibb_max"]):
        avisos.append(("amarillo", f"IIBB: criterio sin definir. Rango del mes {fmt_pesos(s.at[mes, 'iibb_min'])} a "
                                   f"{fmt_pesos(s.at[mes, 'iibb_max'])} (el resultado usa el "
                                   f"{_USO.get(iibb.get('usar_en_resultado', 'maximo'), 'máximo')})."))
    if ctx.mes_incompleto:
        avisos.append(("amarillo", f"Mes incompleto: los comprobantes llegan hasta el "
                                   f"{ctx.datos_hasta.strftime('%d/%m/%Y')}. Cifras provisorias."))
    est = [e for e in ctx.estimados if e["mes"] == mes]
    if est:
        avisos.append(("amarillo", "Datos estimados este mes: " + "; ".join(
            f"{e['concepto']} ({fmt_pesos(e['valor'])})" for e in est) + ". El resultado es provisorio."))
    n_alta = int((alertas["gravedad"] == "Alta").sum())
    if n_alta:
        avisos.append(("rojo", f"{n_alta} alerta(s) de prioridad alta. Ver hoja Alertas."))
    for color, texto in avisos:
        ws.merge_cells(start_row=fila, start_column=1, end_row=fila, end_column=16)
        cel = ws.cell(row=fila, column=1, value=texto)
        bg, fg, _ = SEM[color]
        cel.fill, cel.font = _fill(bg), Font(bold=True, color=fg)
        cel.alignment = Alignment(vertical="center", wrap_text=True)
        ws.row_dimensions[fila].height = 20
        fila += 1

    # Tarjetas ★
    fila += 1
    est_rows = tabla[tabla["estrella"]].head(8)
    for i, r in enumerate(est_rows.itertuples()):
        f0 = fila + (i // 4) * 7
        c0 = 1 + (i % 4) * 4
        bg, fg, etiqueta = SEM.get(r.semaforo, SEM["gris"])
        ws.merge_cells(start_row=f0, start_column=c0, end_row=f0, end_column=c0 + 3)
        t = ws.cell(row=f0, column=c0, value="★ " + r.nombre)
        t.font, t.fill = Font(bold=True, color="FFFFFF"), _fill(C_META)
        t.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.row_dimensions[f0].height = 30
        ws.merge_cells(start_row=f0 + 1, start_column=c0, end_row=f0 + 1, end_column=c0 + 3)
        v = ws.cell(row=f0 + 1, column=c0)
        _num(v, r.valor, r.unidad)
        v.font = Font(bold=True, size=20, color=fg if r.semaforo in ("rojo", "verde", "amarillo") else "000000")
        v.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[f0 + 1].height = 34
        lineas = [("Meta", r.meta_txt), ("Mes anterior", fmt_valor(r.mes_anterior, r.unidad)),
                  ("Mismo mes año ant.", fmt_valor(r.anio_anterior, r.unidad))]
        for j, (k, val) in enumerate(lineas):
            ws.merge_cells(start_row=f0 + 2 + j, start_column=c0, end_row=f0 + 2 + j, end_column=c0 + 1)
            ws.merge_cells(start_row=f0 + 2 + j, start_column=c0 + 2, end_row=f0 + 2 + j, end_column=c0 + 3)
            a = ws.cell(row=f0 + 2 + j, column=c0, value=k)
            b = ws.cell(row=f0 + 2 + j, column=c0 + 2, value=val)
            a.font, b.font = Font(size=9, color="595959"), Font(size=9, bold=True)
            b.alignment = Alignment(horizontal="right")
        ws.merge_cells(start_row=f0 + 5, start_column=c0, end_row=f0 + 5, end_column=c0 + 3)
        _sem(ws.cell(row=f0 + 5, column=c0), r.semaforo)
        for rr in range(f0, f0 + 6):
            for cc in range(c0, c0 + 4):
                ws.cell(row=rr, column=cc).border = BORDE
                if rr in (f0 + 1, f0 + 2, f0 + 3, f0 + 4):
                    ws.cell(row=rr, column=cc).fill = _fill("FFFFFF" if rr > f0 + 1 else bg)
    fila += ((len(est_rows) + 3) // 4) * 7 + 1

    # Resto de los KPIs
    _seccion(ws, fila, "Otros indicadores", 16)
    fila += 1
    cab = ["Indicador", "", "", "Categoría", "Valor", "", "Meta", "", "Mes anterior", "", "Año anterior", "",
           "Semáforo", "", "Cómo se calcula", ""]
    _encabezado(ws, fila, 1, cab)
    for a, b in [(1, 3), (5, 6), (7, 8), (9, 10), (11, 12), (13, 14), (15, 16)]:
        ws.merge_cells(start_row=fila, start_column=a, end_row=fila, end_column=b)
    fila += 1
    for r in tabla[~tabla["estrella"]].itertuples():
        for a, b in [(1, 3), (5, 6), (7, 8), (9, 10), (11, 12), (13, 14), (15, 16)]:
            ws.merge_cells(start_row=fila, start_column=a, end_row=fila, end_column=b)
        ws.cell(row=fila, column=1, value=r.nombre).border = BORDE
        ws.cell(row=fila, column=4, value=r.categoria).border = BORDE
        _num(ws.cell(row=fila, column=5), r.valor, r.unidad)
        ws.cell(row=fila, column=7, value=r.meta_txt).alignment = Alignment(horizontal="center")
        _num(ws.cell(row=fila, column=9), r.mes_anterior, r.unidad)
        _num(ws.cell(row=fila, column=11), r.anio_anterior, r.unidad)
        _sem(ws.cell(row=fila, column=13), r.semaforo)
        f = ws.cell(row=fila, column=15, value=r.formula if r.valor is not None else r.sin_dato)
        f.font = Font(size=8, color="595959")
        f.alignment = Alignment(wrap_text=True, vertical="center")
        ws.row_dimensions[fila].height = 24
        fila += 1

    # Caja
    fila += 1
    _seccion(ws, fila, "Caja a fin de mes", 16)
    fila += 1
    det = [x for x in ctx.caja_detalle if x["mes"] == mes]
    if not det:
        ws.cell(row=fila, column=1, value="Sin extracto ni saldos.csv para este mes.").font = Font(italic=True)
        fila += 1
    for x in det:
        ws.cell(row=fila, column=1, value=x["cuenta"] + (" (inversión, no cuenta como caja)" if x["inversion"] else ""))
        _num(ws.cell(row=fila, column=7), x["saldo"])
        fila += 1
    if pd.notna(s.at[mes, "caja_efectivo"]) if "caja_efectivo" in s else False:
        ws.cell(row=fila, column=1, value="Efectivo (parte diario)")
        _num(ws.cell(row=fila, column=7), s.at[mes, "caja_efectivo"])
        fila += 1
    ws.cell(row=fila, column=1, value="Gasto fijo diario (promedio 3 meses)")
    _num(ws.cell(row=fila, column=7), s.at[mes, "gasto_fijo_diario"])
    ws.freeze_panes = "A3"
    ws.sheet_properties.tabColor = C_META


def hoja_resultado(wb, ctx):
    c, s = ctx.c, ctx.serie
    ws = wb.create_sheet("Resultado mensual")
    M = ctx.meses
    _titulo(ws, f"Resultado operativo mensual · {c.nombre}",
            "Costos imputados al mes de consumo (devengado). Celdas amarillas = dato estimado. "
            "Totales, resultado y % son fórmulas.")
    n = len(M)
    col_acum = 2 + n
    col_pct = 3 + n
    _encabezado(ws, 4, 1, ["Concepto"] + [mes_nombre(m, True) for m in M] + ["Acumulado", "% s/ventas"])
    est = {(e["mes"], e["concepto"]) for e in ctx.estimados}
    fila = 5
    filas_ref = {}

    def L(col):
        return get_column_letter(col)

    def fila_valores(etiqueta, serie, clave=None, negrita=False, est_concepto=None, unidad="pesos"):
        nonlocal fila
        ws.cell(row=fila, column=1, value=etiqueta).font = Font(bold=negrita)
        for j, m in enumerate(M):
            cel = ws.cell(row=fila, column=2 + j)
            v = serie.get(m) if hasattr(serie, "get") else None
            if v is None or pd.isna(v):
                cel.value = None
            else:
                cel.value = float(v)
            cel.number_format = FORMATO_EXCEL[unidad]
            cel.border = BORDE
            if est_concepto and (m, est_concepto) in est:
                cel.fill = _fill(C_SUPUESTO)
                cel.comment = Comment("Dato estimado: todavía no llegó el comprobante de este mes.", "Sistema")
        ac = ws.cell(row=fila, column=col_acum, value=f"=SUM({L(2)}{fila}:{L(1 + n)}{fila})")
        ac.number_format, ac.fill, ac.font, ac.border = FORMATO_EXCEL[unidad], _fill(C_CALC), Font(bold=True), BORDE
        if clave:
            filas_ref[clave] = fila
        fila += 1

    def fila_formula(etiqueta, formula_col, clave=None, unidad="pesos", negrita=True, color=None):
        nonlocal fila
        cel0 = ws.cell(row=fila, column=1, value=etiqueta)
        cel0.font = Font(bold=negrita)
        for j in range(n + 1):
            col = 2 + j
            cel = ws.cell(row=fila, column=col, value=formula_col(L(col)))
            cel.number_format, cel.fill, cel.border = FORMATO_EXCEL[unidad], _fill(color or C_CALC), BORDE
            cel.font = Font(bold=negrita)
        if clave:
            filas_ref[clave] = fila
        fila += 1

    _seccion(ws, fila, "VENTAS", col_pct); fila += 1
    fila_valores("Ventas facturadas", s["ventas_fact"], "vf")
    fila_valores("Ventas sin comprobante", s["ventas_sc"], "vsc")
    fila_formula("VENTAS TOTALES", lambda col: f"={col}{filas_ref['vf']}+{col}{filas_ref['vsc']}", "vt")
    ws.cell(row=filas_ref["vt"], column=col_pct, value=1).number_format = "0.0%"

    _seccion(ws, fila, "COSTOS OPERATIVOS (imputados al mes de consumo)", col_pct); fila += 1
    costos = []
    for r in ctx.rubros_operativos:
        sr = s["costo:" + r]
        if sr.fillna(0).abs().sum() == 0 and not any(e["concepto"] == r for e in ctx.estimados):
            continue
        dev = c.rubro(r).get("devengamiento") == "mes_anterior"
        fila_valores(r + (" (mes de consumo)" if dev else ""), sr, "r:" + r, est_concepto=r)
        costos.append(filas_ref["r:" + r])
    fila_valores("Costo laboral registrado (F.931)", s["lab_931"], "f931", est_concepto="Costo laboral F.931")
    costos.append(filas_ref["f931"])
    fila_valores("Personal no registrado", s["pagos_nr"], "nr")
    costos.append(filas_ref["nr"])
    iibb_cfg = c.impuestos.get("iibb") or {}
    etq = "Ingresos Brutos" + (" (estimado, criterio pendiente)" if iibb_cfg.get("criterio", "pendiente") == "pendiente"
                               else "")
    fila_valores(etq, s["iibb"], "iibb")
    costos.append(filas_ref["iibb"])
    fila_formula("TOTAL COSTOS", lambda col: "=" + "+".join(f"{col}{x}" for x in costos), "tc")
    fila_formula("RESULTADO OPERATIVO", lambda col: f"={col}{filas_ref['vt']}-{col}{filas_ref['tc']}", "res",
                 color="DDEBF7")
    fila_formula("Resultado %", lambda col: f"=IFERROR({col}{filas_ref['res']}/{col}{filas_ref['vt']},\"\")",
                 "resp", unidad="pct", negrita=False)
    # % sobre ventas en la columna final
    for clave, fr in list(filas_ref.items()):
        if clave in ("vt", "resp"):
            continue
        cel = ws.cell(row=fr, column=col_pct,
                      value=f"=IFERROR({L(col_acum)}{fr}/{L(col_acum)}{filas_ref['vt']},\"\")")
        cel.number_format, cel.fill, cel.border = "0.0%", _fill(C_CALC), BORDE

    fila += 1
    _seccion(ws, fila, "% SOBRE VENTAS (mes a mes)", col_pct); fila += 1
    for fr in costos + [filas_ref["res"]]:
        etiqueta = ws.cell(row=fr, column=1).value
        fila_formula(etiqueta, lambda col, fr=fr: f"=IFERROR({col}{fr}/{col}{filas_ref['vt']},\"\")",
                     unidad="pct", negrita=False)

    fila += 1
    _seccion(ws, fila, "FUERA DEL RESULTADO (informativo)", col_pct); fila += 1
    fila_valores(f"Gastos {c.rubro_revisar} (por fecha de factura)", s["revisar"])
    fila_valores("Impuestos no discriminados en tiques (combustible)", s["no_discriminado"])
    if iibb_cfg.get("criterio", "pendiente") == "pendiente":
        fila_valores("IIBB mínimo posible", s["iibb_min"])
        fila_valores("IIBB máximo posible", s["iibb_max"])
    for r in c.rubros.get("rubros", []):
        if r.get("devengamiento") == "mes_anterior":
            fila_valores(f"{r['nombre']} por fecha de factura", s["factura:" + r["nombre"]], "fac:" + r["nombre"])
            fila_formula(f"{r['nombre']} por fecha de factura / ventas",
                         lambda col, fr=filas_ref["fac:" + r["nombre"]]:
                         f"=IFERROR({col}{fr}/{col}{filas_ref['vt']},\"\")", unidad="pct", negrita=False)

    fila += 1
    _seccion(ws, fila, "CAJA Y BANCO", col_pct); fila += 1
    fila_valores("Saldo bancos a fin de mes (sin inversiones)", s["caja_bancos"])
    fila_valores("Saldo inversiones cargado (saldos.csv)", s["inversiones"])
    fila_valores("Movimiento neto a inversiones (FCI: suscripciones − rescates)", s["inversion_neta"])
    fila_valores("Depósitos en efectivo", s["dep_efectivo"])
    fila_valores("Pagos de haberes por banco", s["haberes"])
    # Las sumas de saldos no tienen sentido: se borran
    for fr in range(fila - 5, fila - 3):
        ws.cell(row=fr, column=col_acum).value = None
        ws.cell(row=fr, column=col_acum).fill = PatternFill()

    ws.column_dimensions["A"].width = 52
    for j in range(n + 2):
        ws.column_dimensions[get_column_letter(2 + j)].width = 13.5
    ws.freeze_panes = "B5"
    return filas_ref


def hoja_graficos(wb, ctx):
    c, s = ctx.c, ctx.serie
    ws = wb.create_sheet("Gráficos")
    _titulo(ws, f"Ventas contra costos · {c.nombre}", "Columnas: costos por rubro (apilados). Línea: ventas.")
    M = ctx.meses
    principal = c.empresa.get("rubro_principal")
    rubros = [r for r in ctx.rubros_operativos if s["costo:" + r].fillna(0).abs().sum() > 0]
    if principal in rubros:
        rubros.remove(principal)
        rubros = [principal] + rubros
    series = [(r, s["costo:" + r]) for r in rubros] + [("Costo laboral total", s["lab_total"]), ("IIBB", s["iibb"])]
    f0 = 40
    cab = ["Mes", "Ventas"] + [x[0] for x in series] + [f"% {principal} s/ventas" if principal else "% resultado"]
    _encabezado(ws, f0, 1, cab)
    for i, m in enumerate(M):
        ws.cell(row=f0 + 1 + i, column=1, value=mes_nombre(m, True))
        ws.cell(row=f0 + 1 + i, column=2, value=float(s.at[m, "ventas_tot"] or 0)).number_format = FORMATO_EXCEL["pesos"]
        for j, (_, ser) in enumerate(series):
            v = ser.get(m)
            ws.cell(row=f0 + 1 + i, column=3 + j, value=0 if pd.isna(v) else float(v)).number_format = FORMATO_EXCEL["pesos"]
        col_pct = 3 + len(series)
        if principal:
            num = f"{get_column_letter(3)}{f0 + 1 + i}"
        else:
            num = "0"
        ws.cell(row=f0 + 1 + i, column=col_pct, value=f"=IFERROR({num}/B{f0 + 1 + i},0)").number_format = "0%"
    n = len(M)
    bar = BarChart()
    bar.type, bar.grouping, bar.overlap = "col", "stacked", 100
    bar.title = "Ventas vs. costos por mes"
    bar.y_axis.title = "$"
    bar.y_axis.numFmt = '#,##0'
    bar.height, bar.width = 11, 26
    data = Reference(ws, min_col=3, max_col=2 + len(series), min_row=f0, max_row=f0 + n)
    cats = Reference(ws, min_col=1, min_row=f0 + 1, max_row=f0 + n)
    bar.add_data(data, titles_from_data=True)
    bar.set_categories(cats)
    grises = ["A6A6A6", "BFBFBF", "8EA9DB", "B4C6E7", "D9D9D9", "C9C9C9", "9BC2E6", "DDEBF7", "7F7F7F", "ACB9CA"]
    for k, ser in enumerate(bar.series):
        color = "C00000" if (k == 0 and principal in rubros) else grises[k % len(grises)]
        ser.graphicalProperties.solidFill = color
        ser.graphicalProperties.line.solidFill = color
    line = LineChart()
    line.add_data(Reference(ws, min_col=2, min_row=f0, max_row=f0 + n), titles_from_data=True)
    line.series[0].graphicalProperties.line.solidFill = "1F4E78"
    line.series[0].graphicalProperties.line.width = 38000
    line.series[0].smooth = False
    bar += line
    bar.legend.position = "b"
    ws.add_chart(bar, "A4")
    if principal:
        l2 = LineChart()
        l2.title = f"{principal} sobre ventas (%)"
        l2.add_data(Reference(ws, min_col=3 + len(series), min_row=f0, max_row=f0 + n), titles_from_data=True)
        l2.set_categories(cats)
        l2.y_axis.numFmt = "0%"
        l2.height, l2.width = 7.5, 26
        l2.series[0].graphicalProperties.line.solidFill = "C00000"
        l2.series[0].smooth = False
        l2.legend = None
        ws.add_chart(l2, "A27")
    ws.column_dimensions["A"].width = 10


def hoja_clientes(wb, ctx):
    ws = wb.create_sheet("Clientes")
    _titulo(ws, f"Clientes · {mes_nombre(ctx.mes)}",
            f"Perdido = más de {(ctx.c.kpis.get('clientes') or {}).get('dias_perdido', 60)} días sin comprar. "
            "Consumidores finales sin CUIT/DNI se muestran juntos.")
    rk = clientes_analisis.ranking(ctx)
    llamar = clientes_analisis.para_llamar(ctx, rk)
    fila = 4

    def tabla(titulo, df, columnas):
        nonlocal fila
        _seccion(ws, fila, f"{titulo} ({len(df)})", len(columnas)); fila += 1
        _encabezado(ws, fila, 1, [x[0] for x in columnas]); fila += 1
        if df.empty:
            ws.cell(row=fila, column=1, value="(ninguno)").font = Font(italic=True, color="7F7F7F")
            fila += 1
        for r in df.to_dict("records"):
            for j, (_, campo, unidad) in enumerate(columnas):
                cel = ws.cell(row=fila, column=1 + j)
                v = r.get(campo) if campo != "#" else None
                if campo == "#":
                    cel.value = fila
                if unidad == "fecha":
                    cel.value = v.date() if pd.notna(v) else None
                    cel.number_format = FORMATO_FECHA_EXCEL
                elif unidad in FORMATO_EXCEL:
                    _num(cel, v, unidad)
                else:
                    cel.value = v
                cel.border = BORDE
            fila += 1
        fila += 1

    tabla("Lista para llamar", llamar, [("Cliente", "nombre", None), ("CUIT/DNI", "doc", None),
                                        ("Motivo", "motivo", None), ("Última compra", "ultima_compra", "fecha"),
                                        ("Compras últimos 12 meses", "ventas_12m", "pesos"),
                                        ("Meses con compra", "meses_con_compra", "numero"),
                                        ("Resultado de la llamada", "_", None)])
    for r in range(fila - len(llamar) - 1, fila - 1):
        ws.cell(row=r, column=7).font = Font(color=AZUL_CARGA)
    tabla("Clientes nuevos del mes", rk[rk["estado"] == "Nuevo"],
          [("Cliente", "nombre", None), ("CUIT/DNI", "doc", None), ("Compras del mes", "ventas_mes", "pesos"),
           ("Primera compra", "primera_compra", "fecha")])
    perd = rk[rk["estado"] == "Perdido"].sort_values("ventas_12m", ascending=False)
    tabla("Clientes perdidos", perd,
          [("Cliente", "nombre", None), ("CUIT/DNI", "doc", None), ("Última compra", "ultima_compra", "fecha"),
           ("Días sin comprar", "dias_sin_comprar", "numero"), ("Compras últimos 12 meses", "ventas_12m", "pesos"),
           ("Meses con compra", "meses_con_compra", "numero")])
    total = rk["ventas_mes"].sum()
    rk = rk.assign(part=rk["ventas_mes"] / total if total else None)
    tabla("Ranking de clientes", rk,
          [("Cliente", "nombre", None), ("CUIT/DNI", "doc", None), ("Ventas del mes", "ventas_mes", "pesos"),
           ("% del mes", "part", "pct"), ("Ventas del año", "ventas_anio", "pesos"),
           ("Meses con compra", "meses_con_compra", "numero"), ("Última compra", "ultima_compra", "fecha"),
           ("Estado", "estado", None)])
    _anchos(ws, {"A": 44, "B": 14, "C": 30, "D": 15, "E": 18, "F": 12, "G": 22, "H": 14})
    ws.freeze_panes = "A4"


def hoja_compras(wb, ctx):
    c, mes = ctx.c, ctx.mes
    ws = wb.create_sheet("Compras")
    _titulo(ws, f"Compras por rubro y proveedor · {c.nombre}",
            "Por fecha de factura, neto sin IVA (las notas de crédito restan). Incluye gastos tomados del extracto.")
    comp = ctx.compras
    comp = comp[comp["mes"] <= mes] if len(comp) else comp
    gb = ctx.gastos_banco
    gb = gb[gb["mes"] <= mes] if len(gb) else gb
    filas = []
    if len(comp):
        filas.append(comp[["mes", "fecha", "rubro", "motivo", "doc", "nombre", "importe"]])
    if len(gb):
        filas.append(gb.assign(motivo="extracto bancario", doc="", nombre="Banco: " + gb["concepto"])[
            ["mes", "fecha", "rubro", "motivo", "doc", "nombre", "importe"]])
    if not filas:
        ws["A4"] = "Sin compras cargadas."
        return
    d = pd.concat(filas, ignore_index=True)
    M = ctx.meses
    piv = d.pivot_table(index="rubro", columns="mes", values="importe", aggfunc="sum").reindex(columns=M).fillna(0)
    orden = [r["nombre"] for r in c.rubros.get("rubros", []) if r["nombre"] in piv.index]
    piv = piv.reindex(orden)
    fila = 4
    _seccion(ws, fila, "Compras por rubro y mes", len(M) + 2); fila += 1
    _encabezado(ws, fila, 1, ["Rubro"] + [mes_nombre(m, True) for m in M] + ["Total"]); fila += 1
    f_ini = fila
    for rubro, row in piv.iterrows():
        ws.cell(row=fila, column=1, value=rubro).border = BORDE
        if rubro == c.rubro_revisar:
            ws.cell(row=fila, column=1).font = Font(bold=True, color="9C0006")
        for j, m in enumerate(M):
            _num(ws.cell(row=fila, column=2 + j), row[m])
        t = ws.cell(row=fila, column=2 + len(M), value=f"=SUM(B{fila}:{get_column_letter(1 + len(M))}{fila})")
        t.number_format, t.fill, t.border = FORMATO_EXCEL["pesos"], _fill(C_CALC), BORDE
        fila += 1
    ws.cell(row=fila, column=1, value="TOTAL").font = Font(bold=True)
    for j in range(len(M) + 1):
        L = get_column_letter(2 + j)
        t = ws.cell(row=fila, column=2 + j, value=f"=SUM({L}{f_ini}:{L}{fila - 1})")
        t.number_format, t.fill, t.font, t.border = FORMATO_EXCEL["pesos"], _fill(C_CALC), Font(bold=True), BORDE
    fila += 2

    _seccion(ws, fila, "Detalle por proveedor", 8); fila += 1
    _encabezado(ws, fila, 1, ["Rubro", "Proveedor", "CUIT", "Cómo se clasificó", "Comprobantes",
                              f"Neto {mes_nombre(mes, True)}", f"Neto {mes[:4]}", "Último comprobante"]); fila += 1
    anio = d[d["mes"].str[:4] == mes[:4]]
    g = anio.groupby(["rubro", "nombre", "doc", "motivo"]).agg(
        n=("importe", "size"), anio=("importe", "sum"), ultimo=("fecha", "max")).reset_index()
    g["mes"] = [anio[(anio["nombre"] == n) & (anio["mes"] == mes)]["importe"].sum() for n in g["nombre"]]
    g["_o"] = g["rubro"].map({r: i for i, r in enumerate(orden)})
    for r in g.sort_values(["_o", "anio"], ascending=[True, False]).to_dict("records"):
        vals = [r["rubro"], r["nombre"], r["doc"], r["motivo"], r["n"]]
        for j, v in enumerate(vals):
            ws.cell(row=fila, column=1 + j, value=v).border = BORDE
        _num(ws.cell(row=fila, column=6), r["mes"])
        _num(ws.cell(row=fila, column=7), r["anio"])
        u = ws.cell(row=fila, column=8, value=r["ultimo"].date() if pd.notna(r["ultimo"]) else None)
        u.number_format, u.border = FORMATO_FECHA_EXCEL, BORDE
        if r["rubro"] == c.rubro_revisar:
            for j in range(1, 9):
                ws.cell(row=fila, column=j).fill = _fill("FFC7CE")
        fila += 1
    _anchos(ws, {"A": 30, "B": 46, "C": 14, "D": 26, "E": 13, "F": 15, "G": 15, "H": 15})
    for j in range(len(M) + 1):
        col = get_column_letter(2 + j)
        if ws.column_dimensions[col].width < 13:
            ws.column_dimensions[col].width = 13
    ws.freeze_panes = "B4"


def hoja_personal(wb, ctx, escenario):
    c, mes, s = ctx.c, ctx.mes, ctx.serie
    ws = wb.create_sheet("Personal")
    _titulo(ws, f"Personal y escenario de regularización · {mes_nombre(mes)}",
            "Costo laboral total = costo F.931 + pagos a personal no registrado. Celdas con texto azul se pueden "
            "cambiar para simular.")
    p = ctx.personal
    fila = 4
    _seccion(ws, fila, "Nómina (personal.yaml)", 6); fila += 1
    _encabezado(ws, fila, 1, ["Persona", "Situación", f"Costo {mes_nombre(mes, True)}", "Origen del dato"]); fila += 1
    det = p["detalle"]
    for per in p["personas"]:
        ws.cell(row=fila, column=1, value=per["nombre"]).border = BORDE
        sit = ws.cell(row=fila, column=2, value="Registrado" if per["registrado"] else "NO registrado")
        sit.border = BORDE
        if not per["registrado"]:
            sit.fill, sit.font = _fill("FFC7CE"), Font(bold=True, color="9C0006")
            dm = det[(det["persona"] == per["nombre"]) & (det["mes"] == mes)]
            _num(ws.cell(row=fila, column=3), dm["monto"].sum() if len(dm) else None)
            ws.cell(row=fila, column=4, value=", ".join(sorted(set(dm["origen"]))) or "sin pagos cargados")
        else:
            ws.cell(row=fila, column=3, value="en F.931").alignment = Alignment(horizontal="right")
            ws.cell(row=fila, column=4, value="F.931")
        fila += 1
    fila += 1

    _seccion(ws, fila, "F.931 por mes", 9); fila += 1
    _encabezado(ws, fila, 1, ["Mes", "Empleados", "Rem. 1", "Contribuciones (351+352+312+028)", "Costo laboral F.931",
                              "Pagos no registrados", "Costo laboral total", "Estimado"]); fila += 1
    for m in ctx.meses:
        ws.cell(row=fila, column=1, value=mes_nombre(m, True)).border = BORDE
        _num(ws.cell(row=fila, column=2), s.at[m, "empleados_931"], "numero")
        _num(ws.cell(row=fila, column=3), s.at[m, "rem1_931"])
        _num(ws.cell(row=fila, column=4), s.at[m, "contrib_931"])
        _num(ws.cell(row=fila, column=5), s.at[m, "lab_931"])
        _num(ws.cell(row=fila, column=6), s.at[m, "pagos_nr"])
        _num(ws.cell(row=fila, column=7), s.at[m, "lab_total"])
        e = ws.cell(row=fila, column=8, value="sí (último F.931)" if s.at[m, "f931_estimado"] else "")
        if s.at[m, "f931_estimado"]:
            for j in range(1, 9):
                ws.cell(row=fila, column=j).fill = _fill(C_SUPUESTO)
        e.border = BORDE
        fila += 1
    fila += 1

    _seccion(ws, fila, "Escenario de regularización (por mes)", 8); fila += 1
    tasa = escenario.get("tasa_contribuciones")
    ws.cell(row=fila, column=1, value=f"Contribuciones efectivas del último F.931 ({escenario.get('mes_referencia') or '—'})")
    ct = ws.cell(row=fila, column=3, value=tasa)
    ct.number_format, ct.font = "0.0%", Font(color=AZUL_CARGA, bold=True)
    fila_tasa = fila
    fila += 1
    ws.cell(row=fila, column=1, value="Aguinaldo prorrateado (13 sueldos / 12)")
    sc = ws.cell(row=fila, column=3, value=13 / 12 if escenario.get("incluye_sac") else 1)
    sc.number_format, sc.font = "0.0000", Font(color=AZUL_CARGA, bold=True)
    fila_sac = fila
    fila += 2
    _encabezado(ws, fila, 1, ["Persona", "Sueldo bruto", "Origen del sueldo", "Costo mensual registrado",
                              "Pago actual (prom. 3 meses)", "Diferencia por mes"]); fila += 1
    f_ini = fila
    for r in escenario["filas"]:
        ws.cell(row=fila, column=1, value=r["persona"]).border = BORDE
        b = ws.cell(row=fila, column=2, value=r["sueldo_bruto"])
        b.number_format, b.font, b.border = FORMATO_EXCEL["pesos"], Font(color=AZUL_CARGA, bold=True), BORDE
        ws.cell(row=fila, column=3, value=r["origen_bruto"]).border = BORDE
        f = ws.cell(row=fila, column=4, value=f"=IFERROR(B{fila}*(1+$C${fila_tasa})*$C${fila_sac},\"\")")
        f.number_format, f.fill, f.border = FORMATO_EXCEL["pesos"], _fill(C_CALC), BORDE
        pa = ws.cell(row=fila, column=5, value=r["pago_actual_promedio"] if r["pago_actual_promedio"] is not None else 0)
        pa.number_format, pa.font, pa.border = FORMATO_EXCEL["pesos"], Font(color=AZUL_CARGA), BORDE
        if r["pago_actual_promedio"] is None:
            pa.comment = Comment("No hay pagos cargados: se toma 0. Cargá pagos_personal.csv.", "Sistema")
            pa.fill = _fill(C_SUPUESTO)
        d = ws.cell(row=fila, column=6, value=f"=IFERROR(D{fila}-E{fila},\"\")")
        d.number_format, d.fill, d.border = FORMATO_EXCEL["pesos"], _fill(C_CALC), BORDE
        fila += 1
    ws.cell(row=fila, column=1, value="TOTAL").font = Font(bold=True)
    for col in (4, 5, 6):
        L = get_column_letter(col)
        t = ws.cell(row=fila, column=col, value=f"=SUM({L}{f_ini}:{L}{fila - 1})")
        t.number_format, t.fill, t.font = FORMATO_EXCEL["pesos"], _fill(C_CALC), Font(bold=True)
    fila_tot = fila
    fila += 2
    ws.cell(row=fila, column=1, value=f"Resultado operativo de {mes_nombre(mes)} (actual)")
    _num(ws.cell(row=fila, column=4), escenario.get("resultado_actual"))
    fila += 1
    ws.cell(row=fila, column=1, value="Resultado operativo con el personal regularizado").font = Font(bold=True)
    r2 = ws.cell(row=fila, column=4, value=f"=IFERROR(D{fila - 1}-F{fila_tot},\"\")")
    r2.number_format, r2.fill, r2.font = FORMATO_EXCEL["pesos"], _fill("DDEBF7"), Font(bold=True)
    fila += 2
    ws.cell(row=fila, column=1, value="Supuestos: el sueldo bruto sale de personal.yaml o, si no está, del Rem. 1 "
            "promedio por empleado del último F.931; las contribuciones usan el mismo % efectivo de ese F.931 "
            "(incluye ART y seguro de vida). No incluye indemnizaciones ni deuda por períodos anteriores.").font = \
        Font(italic=True, size=9, color="595959")
    _anchos(ws, {"A": 48, "B": 16, "C": 30, "D": 22, "E": 22, "F": 20, "G": 18, "H": 16})


def hoja_alertas(wb, alertas):
    ws = wb.create_sheet("Alertas")
    _titulo(ws, "Alertas del cierre", "Alta = resolver antes de la reunión · Media = revisar · Info = para saber.")
    _encabezado(ws, 4, 1, ["Prioridad", "Tipo", "Mes", "Detalle", "Monto", "Qué hacer"])
    for i, r in enumerate(alertas.to_dict("records")):
        f = 5 + i
        bg, fg = GRAV.get(r["gravedad"], ("FFFFFF", "000000"))
        c = ws.cell(row=f, column=1, value=r["gravedad"])
        c.fill, c.font = _fill(bg), Font(bold=True, color=fg)
        ws.cell(row=f, column=2, value=r["tipo"])
        ws.cell(row=f, column=3, value=mes_nombre(r["mes"], True) if r["mes"] and len(str(r["mes"])) == 7 else r["mes"])
        ws.cell(row=f, column=4, value=r["detalle"]).alignment = Alignment(wrap_text=True, vertical="top")
        m = ws.cell(row=f, column=5)
        if r["monto"] is not None and not pd.isna(r["monto"]):
            m.value, m.number_format = float(r["monto"]), FORMATO_EXCEL["pesos"]
        ws.cell(row=f, column=6, value=r["que_hacer"]).alignment = Alignment(wrap_text=True, vertical="top")
        for j in range(1, 7):
            ws.cell(row=f, column=j).border = BORDE
    if alertas.empty:
        ws.cell(row=5, column=1, value="Sin alertas. ✔")
    _anchos(ws, {"A": 10, "B": 22, "C": 9, "D": 80, "E": 15, "F": 55})
    ws.freeze_panes = "A5"
    ws.auto_filter.ref = f"A4:F{4 + max(len(alertas), 1)}"
    ws.sheet_properties.tabColor = "C00000"


def hoja_semanal(wb, ctx):
    if ctx.semanal is None or ctx.semanal.empty:
        return
    ws = wb.create_sheet("Semanal")
    u = ctx.c.unidad_plural
    _titulo(ws, "Indicadores semanales (parte diario)")
    cols = [("unidades_producidas", f"{u.capitalize()} producidas"), ("unidades_vendidas", f"{u.capitalize()} vendidas"),
            ("unidades_descartadas", f"{u.capitalize()} descartadas"), ("horas_parada", "Horas de parada"),
            ("kwh", "kWh consumidos")]
    cols = [x for x in cols if x[0] in ctx.semanal]
    _encabezado(ws, 4, 1, ["Semana del"] + [x[1] for x in cols] + ["Merma %", f"kWh por {ctx.c.unidad}"])
    for i, (sem, row) in enumerate(ctx.semanal.iterrows()):
        f = 5 + i
        c = ws.cell(row=f, column=1, value=sem.date())
        c.number_format = FORMATO_FECHA_EXCEL
        for j, (k, _) in enumerate(cols):
            ws.cell(row=f, column=2 + j, value=float(row[k]) if pd.notna(row[k]) else None).number_format = "#,##0"
        idx = {k: get_column_letter(2 + j) for j, (k, _) in enumerate(cols)}
        if "unidades_descartadas" in idx and "unidades_producidas" in idx:
            ws.cell(row=f, column=2 + len(cols),
                    value=f"=IFERROR({idx['unidades_descartadas']}{f}/{idx['unidades_producidas']}{f},\"\")").number_format = "0.0%"
        if "kwh" in idx and "unidades_producidas" in idx:
            ws.cell(row=f, column=3 + len(cols),
                    value=f"=IFERROR({idx['kwh']}{f}/{idx['unidades_producidas']}{f},\"\")").number_format = "0.00"
    _anchos(ws, {get_column_letter(i): 16 for i in range(1, 10)})


def hoja_decisiones(wb, filas):
    ws = wb.create_sheet("Decisiones")
    _titulo(ws, "Decisiones de la reunión mensual",
            "Esta tabla se edita a mano (texto azul) y se conserva en el tablero del mes siguiente.")
    ws["A3"] = ("Estado: Pendiente / En curso / Hecha / Descartada. Fechas en formato dd/mm/aaaa. "
                "Agregá filas debajo de la última.")
    ws["A3"].font = Font(size=9, italic=True)
    _encabezado(ws, 5, 1, mod_dec.COLUMNAS)
    dv = DataValidation(type="list", formula1='"' + ",".join(mod_dec.ESTADOS) + '"', allow_blank=True)
    ws.add_data_validation(dv)
    total = max(len(filas) + 30, 40)
    hoy = date.today()
    for i in range(total):
        f = 6 + i
        d = filas[i] if i < len(filas) else {}
        for j, k in enumerate(mod_dec.COLUMNAS):
            c = ws.cell(row=f, column=1 + j, value=d.get(k))
            c.font = Font(color=AZUL_CARGA)
            c.border = BORDE
            if k in ("Fecha", "Vence"):
                c.number_format = FORMATO_FECHA_EXCEL
        dv.add(f"E{f}")
        if d and d.get("Vence") and d["Vence"] < hoy and d.get("Estado") not in ("Hecha", "Descartada"):
            ws.cell(row=f, column=4).fill = _fill("FFC7CE")
    _anchos(ws, {"A": 12, "B": 60, "C": 18, "D": 12, "E": 13, "F": 40})
    ws.freeze_panes = "A6"
    ws.sheet_properties.tabColor = "70AD47"


def hoja_leyenda(wb, ctx):
    ws = wb.create_sheet("Leyenda")
    _titulo(ws, "Cómo leer este tablero")
    filas = [
        ("Semáforo", None),
        ("● EN META", "verde"), ("● ATENCIÓN: se desvía de la meta hasta 1 tolerancia", "amarillo"),
        ("● FUERA DE META: se desvía más que la tolerancia", "rojo"), ("○ SIN DATO: falta la fuente", "gris"),
        ("— sin meta: el indicador se muestra pero no tiene meta cargada", "sin meta"),
        ("", None), ("Colores de celdas", None),
        ("Texto azul = dato que se carga o se puede cambiar a mano", "azul"),
        ("Fondo gris = cálculo o fórmula, no tocar", "calc"),
        ("Fondo amarillo = dato estimado o supuesto a revisar", "supuesto"),
        ("", None), ("Dónde se cambian las cosas", None),
        (f"Metas, tolerancias y KPIs activos: clientes/{ctx.c.id}/config/kpis.yaml", ""),
        (f"Reglas proveedor → rubro: clientes/{ctx.c.id}/config/rubros.yaml", ""),
        (f"Alícuotas y criterio de IIBB: clientes/{ctx.c.id}/config/impuestos.yaml", ""),
        (f"Personal registrado / no registrado: clientes/{ctx.c.id}/config/personal.yaml", ""),
        ("Después de editar, volver a correr el cierre del mes.", ""),
    ]
    for i, (txt, tipo) in enumerate(filas):
        c = ws.cell(row=3 + i, column=1, value=txt)
        if tipo is None and txt:
            c.font = Font(bold=True, color=C_META)
        elif tipo in SEM:
            bg, fg, _ = SEM[tipo]
            c.fill, c.font = _fill(bg), Font(bold=True, color=fg)
        elif tipo == "azul":
            c.font = Font(color=AZUL_CARGA, bold=True)
        elif tipo == "calc":
            c.fill = _fill(C_CALC)
        elif tipo == "supuesto":
            c.fill = _fill(C_SUPUESTO)
    ws.column_dimensions["A"].width = 95


def generar(ctx, tabla: pd.DataFrame, alertas: pd.DataFrame, escenario: dict, ruta) -> None:
    filas_dec = mod_dec.leer(ctx.c, ctx.mes)
    wb = Workbook()
    hoja_tablero(wb, ctx, tabla, alertas, escenario)
    hoja_resultado(wb, ctx)
    hoja_graficos(wb, ctx)
    hoja_clientes(wb, ctx)
    hoja_compras(wb, ctx)
    hoja_personal(wb, ctx, escenario)
    hoja_alertas(wb, alertas)
    hoja_semanal(wb, ctx)
    hoja_decisiones(wb, filas_dec)
    hoja_leyenda(wb, ctx)
    for ws in wb.worksheets:  # impresión: horizontal y una página de ancho
        ws.page_setup.orientation = "landscape"
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
        ws.print_options.horizontalCentered = True
    wb.properties.creator = "Control de gestión ARFinance"
    wb.properties.title = f"Tablero {ctx.c.nombre} {ctx.mes}"
    try:
        wb.save(ruta)
    except PermissionError:
        raise ErrorUsuario(f"No puedo guardar {ruta.name}: el archivo está abierto. Cerralo en Excel y volvé a correr.")
    mod_dec.guardar_copia(ctx.c, filas_dec)
