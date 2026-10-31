"""Resumen de una página para la reunión mensual con los socios (Markdown y PDF)."""
from __future__ import annotations

from datetime import date

import pandas as pd

from ..util import fmt_pesos, fmt_pct, fmt_valor, mes_nombre, mes_sumar
from . import decisiones as mod_dec


def _var(a, b):
    if a is None or b is None or pd.isna(a) or pd.isna(b) or b == 0:
        return None
    return a / b - 1


def _cambio(texto, a, b, plural=False):
    v = _var(a, b)
    if v is None:
        return None
    if abs(v) < 0.03:
        verbo = "se mantuvieron" if plural else "se mantuvo"
        return f"{texto} {verbo}"
    if v > 0:
        verbo = "subieron" if plural else "subió"
    else:
        verbo = "bajaron" if plural else "bajó"
    return f"{texto} {verbo} {fmt_pct(abs(v), 0)}"


def _mayus(t: str) -> str:
    return t[:1].upper() + t[1:] if t else t


def causa_probable(ctx, fila) -> str:
    """Explicación simple, armada con los componentes del KPI (mes actual vs. mes anterior)."""
    s, mes = ctx.serie, ctx.mes
    ant = mes_sumar(mes, -1)
    g = lambda col, m=mes: ctx.v(col, m)
    nm = mes_nombre(ant).split(" ")[0]
    base = fila["base"]
    if base == "rubro_sobre_ventas":
        rubro = (next((k for k in ctx.c.kpis.get("kpis", []) if k["id"] == fila["id"]), {}).get("params") or {}).get("rubro")
        partes = [x for x in [_cambio(f"el gasto de {rubro}", g("costo:" + rubro), g("costo:" + rubro, ant)),
                              _cambio("las ventas", g("ventas_tot"), g("ventas_tot", ant), plural=True)] if x]
        txt = _mayus(" y ".join(partes) + f" respecto de {nm}.") if partes else ""
        if any(e["mes"] == mes and e["concepto"] == rubro for e in ctx.estimados):
            txt += f" (El gasto de {rubro} de este mes es estimado: todavía no llegó la factura.)"
        if ctx.c.temporada(mes) == "baja":
            txt += " En temporada baja se vende menos, así que el peso de este gasto sobre las ventas sube."
        return txt.strip() or "Gasto alto en relación con las ventas."
    if base in ("resultado_operativo", "resultado_operativo_pct"):
        costos = {r: g("costo:" + r) or 0 for r in ctx.rubros_operativos}
        costos["costo laboral"] = g("lab_total") or 0
        mayor = max(costos, key=costos.get) if costos else None
        v = g("ventas_tot") or 0
        txt = f"Las ventas ({fmt_pesos(v)}) no alcanzan a cubrir los costos."
        if mayor and v:
            txt += f" El costo más grande es {mayor}: {fmt_pesos(costos[mayor])} ({fmt_pct(costos[mayor] / v, 0)} de las ventas)."
        cv = _cambio("Las ventas", g("ventas_tot"), g("ventas_tot", ant), plural=True)
        return txt + (f" {cv} respecto de {nm}." if cv else "")
    if base == "caja_dias":
        txt = (f"A fin de mes había {fmt_pesos(g('caja'))} en bancos y caja, contra gastos fijos de "
               f"{fmt_pesos(g('gasto_fijo_diario'))} por día.")
        if s["inversion_neta"].notna().any():
            txt += " No incluye lo invertido en fondos de inversión."
        return txt
    if base == "gastos_a_revisar":
        comp = ctx.compras
        comp = comp[(comp["mes"] == mes) & (comp["rubro"] == ctx.c.rubro_revisar)]
        top = comp.groupby("nombre")["importe"].sum().nlargest(3)
        return "Facturas sin rubro o con posible gasto personal: " + ", ".join(
            f"{n} ({fmt_pesos(v)})" for n, v in top.items()) + "."
    if base in ("personal_no_registrado_cant", "personal_no_registrado_pct"):
        return "Hay personal trabajando sin registrar (riesgo laboral y de inspección)."
    if base == "ventas_facturadas":
        return (_cambio("Las ventas", g("ventas_fact"), g("ventas_fact", ant), plural=True) or "Ventas bajas") + \
            f" respecto de {nm}; temporada {ctx.c.temporada(mes)}."
    if base == "iibb_cargas_ventas":
        return "Las ventas del mes son bajas en relación con las cargas sociales fijas y el IIBB."
    if base == "merma_pct":
        return f"Se descartaron más {ctx.c.unidad_plural} que lo normal: revisar el proceso, el equipo y la manipulación."
    if base == "dias_cobertura":
        return "El stock no está en el rango de la meta para esta temporada (exceso o riesgo de faltante)."
    return f"Valor {fmt_valor(fila['valor'], fila['unidad'])} contra meta {fila['meta_txt']}."


def preguntas(ctx, tabla, alertas, escenario) -> list[str]:
    s, mes, c = ctx.serie, ctx.mes, ctx.c
    cand = []  # (impacto $, texto)
    res = ctx.v("resultado")
    if res is not None and res < 0:
        principal = c.empresa.get("rubro_principal")
        extra = ""
        if principal and ctx.v("costo:" + principal) and ctx.v("ventas_tot"):
            extra = (f" {principal} se lleva el {fmt_pct(ctx.v('costo:' + principal) / ctx.v('ventas_tot'), 0)} "
                     "de las ventas.")
        cand.append((abs(res), f"El mes cerró con una pérdida operativa de {fmt_pesos(-res)}.{extra} "
                               "¿Qué hacemos: subir precios, bajar algún gasto o aceptar la pérdida por temporada?"))
    rev = ctx.v("revisar")
    if rev and rev > 0:
        comp = ctx.compras
        top = comp[(comp["mes"] == mes) & (comp["rubro"] == c.rubro_revisar)].groupby("nombre")["importe"].sum()
        nom = top.idxmax() if len(top) else "varios proveedores"
        cand.append((rev, f"Hay {fmt_pesos(rev)} en compras a revisar (la mayor: {nom}). ¿Son gastos de la "
                          "empresa (y de qué rubro) o gastos personales que hay que tratar como retiro?"))
    p = ctx.personal
    if p and p["n_no_registrados"]:
        dif = escenario.get("diferencia_total") or 0
        if dif:
            cand.append((dif, f"Registrar a {p['n_no_registrados']} persona(s) costaría unos {fmt_pesos(dif)} más por mes "
                              f"(el resultado pasaría a {fmt_pesos(escenario.get('resultado_regularizado'))}). "
                              "¿Avanzamos con la regularización? ¿Desde cuándo?"))
        else:
            cand.append((1, "¿Cuánto se le paga por mes a cada persona no registrada? Sin ese dato el costo "
                            "laboral y el resultado están subestimados."))
    iibb = c.impuestos.get("iibb") or {}
    if iibb.get("criterio", "pendiente") == "pendiente" and ctx.v("iibb_max") is not None:
        dif = (ctx.v("iibb_max") or 0) - (ctx.v("iibb_min") or 0)
        cand.append((dif, f"IIBB: falta definir qué ventas van al {fmt_pct(min(a['alicuota'] for a in iibb['actividades']), 1)} "
                          f"y cuáles al {fmt_pct(max(a['alicuota'] for a in iibb['actividades']), 1)}. "
                          f"La diferencia este mes es de {fmt_pesos(dif)}. ¿Qué criterio usamos?"))
    dep = sum(ctx.v("dep_efectivo", m) or 0 for m in [mes, mes_sumar(mes, -1)])
    if dep > 0:
        cand.append((dep, f"Entraron {fmt_pesos(dep)} en depósitos de efectivo al banco en los últimos meses. "
                          "¿Corresponden a ventas sin factura? ¿Las registramos?"))
    caja = tabla[tabla["base"] == "caja_dias"]
    if len(caja) and caja.iloc[0]["semaforo"] == "rojo":
        cand.append(((ctx.v("gasto_fijo_diario") or 0) * 30,
                     f"La caja alcanza para {fmt_valor(caja.iloc[0]['valor'], 'dias')} de gastos fijos. "
                     "¿Rescatamos fondos de inversión o postergamos algún pago?"))
    cand.sort(key=lambda x: -x[0])
    return [t for _, t in cand[:3]]


def armar(ctx, tabla, alertas, escenario) -> dict:
    c, mes = ctx.c, ctx.mes
    g = ctx.v
    ant = mes_sumar(mes, -1)
    d = {"titulo": f"Reunión mensual · {c.nombre} · {mes_nombre(mes)}",
         "ventas": g("ventas_tot"), "ventas_var": _var(g("ventas_tot"), g("ventas_tot", ant)),
         "ventas_anio_var": _var(g("ventas_tot"), g("ventas_tot", mes_sumar(mes, -12))),
         "resultado": g("resultado"), "resultado_pct": (g("resultado") / g("ventas_tot")) if g("ventas_tot") else None,
         "resultado_ant": g("resultado", ant), "caja": g("caja"),
         "caja_dias": next((r["valor"] for r in tabla.to_dict("records") if r["base"] == "caja_dias"), None),
         "estimados": [e for e in ctx.estimados if e["mes"] == mes],
         "incompleto": ctx.datos_hasta.strftime("%d/%m/%Y") if ctx.mes_incompleto else None}
    rojos = tabla[tabla["semaforo"] == "rojo"].sort_values(["estrella", "orden"], ascending=[False, True])
    d["rojos"] = [{"nombre": r["nombre"], "valor": fmt_valor(r["valor"], r["unidad"]), "meta": r["meta_txt"],
                   "causa": causa_probable(ctx, r)} for r in rojos.head(6).to_dict("records")]
    d["n_rojos"] = len(rojos)
    d["n_verdes"] = int((tabla["semaforo"] == "verde").sum())
    d["n_sin_dato"] = int((tabla["semaforo"] == "gris").sum())
    filas = mod_dec.leer(c, mes)
    d["decisiones"] = mod_dec.pendientes(filas, date.today())
    d["hechas"] = [f for f in filas if f.get("Estado") == "Hecha"]
    d["preguntas"] = preguntas(ctx, tabla, alertas, escenario)
    d["alertas_altas"] = int((alertas["gravedad"] == "Alta").sum())
    return d


def a_markdown(d: dict) -> str:
    L = [f"# {d['titulo']}", ""]
    var = f" ({'+' if d['ventas_var'] > 0 else ''}{fmt_pct(d['ventas_var'], 0)} vs. mes anterior)" if d["ventas_var"] is not None else ""
    L.append("## 1. Cómo nos fue")
    L.append(f"- **Ventas:** {fmt_pesos(d['ventas'])}{var}.")
    if d["resultado"] is not None:
        signo = "ganancia" if d["resultado"] >= 0 else "pérdida"
        L.append(f"- **Resultado operativo:** {fmt_pesos(d['resultado'])} ({signo}; "
                 f"{fmt_pct(d['resultado_pct'], 0) if d['resultado_pct'] is not None else 'sin dato'} de las ventas)."
                 + (f" El mes anterior: {fmt_pesos(d['resultado_ant'])}." if d["resultado_ant"] is not None else ""))
    if d["caja"] is not None:
        L.append(f"- **Caja a fin de mes:** {fmt_pesos(d['caja'])}"
                 + (f", alcanza para {fmt_valor(d['caja_dias'], 'dias')} de gastos fijos." if d["caja_dias"] else "."))
    else:
        L.append("- **Caja a fin de mes:** sin dato (falta el extracto o los saldos del mes).")
    if d.get("incompleto"):
        L.append(f"- *Mes todavía incompleto: los comprobantes llegan hasta el {d['incompleto']}.*")
    if d["estimados"]:
        L.append("- *Resultado provisorio: " + "; ".join(e["concepto"] for e in d["estimados"]) + " está(n) estimado(s).*")
    L.append(f"- Indicadores: {d['n_verdes']} en verde, {d['n_rojos']} en rojo, {d['n_sin_dato']} sin dato.")
    L.append("")
    L.append("## 2. Lo que está en rojo y por qué")
    if not d["rojos"]:
        L.append("- Nada en rojo este mes.")
    for r in d["rojos"]:
        L.append(f"- **{r['nombre']}: {r['valor']}** (meta {r['meta']}). {r['causa']}")
    L.append("")
    L.append("## 3. Decisiones anteriores")
    if not d["decisiones"] and not d["hechas"]:
        L.append("- No hay decisiones cargadas (hoja *Decisiones* del Excel).")
    for f in d["decisiones"][:6]:
        vence = f["Vence"].strftime("%d/%m/%Y") if f.get("Vence") else "sin fecha"
        L.append(f"- {'⚠ VENCIDA · ' if f['vencida'] else ''}{f['Decisión']} — {f.get('Responsable') or 'sin responsable'}"
                 f" — vence {vence} — {f.get('Estado') or 'Pendiente'}")
    if d["hechas"]:
        L.append(f"- Cumplidas: {len(d['hechas'])}.")
    L.append("")
    L.append("## 4. Para decidir hoy")
    for i, p in enumerate(d["preguntas"], 1):
        L.append(f"{i}. {p}")
    if not d["preguntas"]:
        L.append("- Sin temas urgentes.")
    L.append("")
    L.append(f"*{d['alertas_altas']} alerta(s) de prioridad alta en el Excel (hoja Alertas). "
             f"Generado el {date.today().strftime('%d/%m/%Y')}.*")
    return "\n".join(L) + "\n"


def a_pdf(md: str, ruta) -> None:
    """PDF de una página a partir del Markdown simple de arriba."""
    import re
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import Frame, KeepInFrame, Paragraph, SimpleDocTemplate, Spacer

    st_t = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=colors.HexColor("#1F4E78"))
    st_h = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=11.5, leading=15, spaceBefore=7, spaceAfter=3,
                          textColor=colors.HexColor("#1F4E78"))
    st_p = ParagraphStyle("p", fontName="Helvetica", fontSize=9.5, leading=12.5, alignment=TA_LEFT, leftIndent=10,
                          bulletIndent=0, spaceAfter=2)
    st_n = ParagraphStyle("n", parent=st_p, fontSize=8, textColor=colors.HexColor("#595959"), leftIndent=0)

    def inline(t):
        t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"\*(.+?)\*", r"<i>\1</i>", t)
        t = t.replace("⚠", "<font color='#C00000'><b>!</b></font>")
        return t

    flow = []
    for linea in md.splitlines():
        if linea.startswith("# "):
            flow += [Paragraph(inline(linea[2:]), st_t), Spacer(1, 4)]
        elif linea.startswith("## "):
            flow.append(Paragraph(inline(linea[3:]), st_h))
        elif linea.startswith("- "):
            flow.append(Paragraph(inline(linea[2:]), st_p, bulletText="•"))
        elif re.match(r"^\d+\. ", linea):
            n, txt = linea.split(". ", 1)
            flow.append(Paragraph(inline(txt), st_p, bulletText=n + "."))
        elif linea.startswith("*") and linea.endswith("*"):
            flow.append(Paragraph(inline(linea), st_n))
        elif linea.strip():
            flow.append(Paragraph(inline(linea), st_p))
    doc = SimpleDocTemplate(str(ruta), pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm,
                            topMargin=1.4 * cm, bottomMargin=1.2 * cm, title="Resumen reunión mensual")
    ancho, alto = A4[0] - 3.2 * cm, A4[1] - 2.6 * cm
    doc.build([KeepInFrame(ancho, alto, flow, mode="shrink")])
