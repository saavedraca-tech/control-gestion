"""Alertas del cierre: gastos a revisar, proveedores sin regla, faltantes, estimaciones y diferencias."""
from __future__ import annotations

import pandas as pd

from .util import fmt_pesos, mes_nombre, mes_sumar

ALTA, MEDIA, INFO = "Alta", "Media", "Info"
_USO = {"maximo": "máximo", "minimo": "mínimo", "promedio": "promedio"}
COLUMNAS = ["gravedad", "tipo", "mes", "detalle", "monto", "que_hacer"]


def generar(ctx, carga, escenario: dict | None = None) -> pd.DataFrame:
    c, mes, s = ctx.c, ctx.mes, ctx.serie
    A = []

    def add(grav, tipo, m, detalle, monto=None, que=""):
        A.append({"gravedad": grav, "tipo": tipo, "mes": m, "detalle": detalle, "monto": monto, "que_hacer": que})

    # ---- archivos
    for e in carga.errores:
        add(ALTA, "Archivo con error", "", f"{e['archivo']}: {e['detalle']}", None,
            "Revisar el archivo y volver a correr el cierre.")
    for e in carga.ignorados:
        add(INFO, "Archivo no usado", "", f"{e['archivo']}: {e['detalle']}", None,
            "Si es un dato del cierre, renombralo como indica el README.")

    # ---- compras a revisar y sin regla
    comp = ctx.compras
    comp = comp[comp["mes"] <= mes] if len(comp) else comp
    if len(comp):
        rev = comp[(comp["rubro"] == c.rubro_revisar) & (comp["motivo"] != "sin regla")]
        for (m, doc, nom, mot), g in rev.groupby(["mes", "doc", "nombre", "motivo"]):
            add(ALTA if m == mes else MEDIA, "Gasto a revisar", m,
                f"{nom} (CUIT {doc}) · {len(g)} comprobante(s) · {mot}. Posible gasto ajeno a la operación.",
                float(g["importe"].sum()),
                "Confirmar con los socios. Si es de la empresa, agregar una regla en rubros.yaml con el rubro correcto.")
        sin = comp[comp["motivo"] == "sin regla"]
        for (doc, nom), g in sin.groupby(["doc", "nombre"]):
            ult = g["mes"].max()
            add(ALTA if ult == mes else MEDIA, "Proveedor sin regla", ult,
                f"{nom} (CUIT {doc}) · {len(g)} comprobante(s) entre {mes_nombre(g['mes'].min(), True)} y "
                f"{mes_nombre(ult, True)} · hoy está en A REVISAR, fuera del resultado.",
                float(g["importe"].sum()),
                f"Agregar en rubros.yaml:  - {{cuit: \"{doc}\", rubro: <rubro>}}")

    # ---- F.931
    if "f931" in ctx.fuentes or "emitidos" in ctx.fuentes:
        for m in ctx.meses:
            if pd.isna(s.at[m, "lab_931"]) and s.at[m, "ventas_fact"]:
                add(ALTA if m == mes else MEDIA, "Mes sin F.931", m,
                    f"No hay F.931 de {mes_nombre(m)}: el costo laboral registrado de ese mes queda sin dato.",
                    None, f"Dejar el PDF del F.931 en entrada/{m}/ y volver a correr el cierre.")
    for e in ctx.estimados:
        if e["mes"] == mes or e["mes"] == mes_sumar(mes, -1):
            add(MEDIA, "Dato estimado", e["mes"], f"{e['concepto']}: {e['motivo']}.", e["valor"],
                "Se corrige solo cuando llegue el dato y se vuelva a correr el cierre.")

    # ---- personal
    p = ctx.personal
    if p and p["n_no_registrados"]:
        texto = f"{p['n_no_registrados']} persona(s) trabajan sin registrar: " + \
                ", ".join(x["nombre"] for x in p["no_registrados"]) + "."
        monto = None
        if escenario and escenario.get("diferencia_total"):
            monto = escenario["diferencia_total"]
            texto += f" Registrarlas costaría {fmt_pesos(monto)} más por mes (ver hoja Personal)."
        add(ALTA, "Personal no registrado", mes, texto, monto,
            "Evaluar la regularización con los socios. La alerta sigue mientras haya personal no registrado.")
        if pd.isna(s.at[mes, "pagos_nr"]):
            add(MEDIA, "Falta dato", mes, "No hay pagos al personal no registrado cargados este mes: el costo "
                "laboral y el resultado quedan subestimados.", None,
                f"Cargar entrada/{mes}/pagos_personal.csv con columnas persona;monto.")
        for x in p["sin_identificar"]:
            add(MEDIA, "Diferencia", x["mes"], f"En pagos_personal.csv figura '{x['nombre']}', que no está en "
                "personal.yaml.", x["monto"], "Agregar a la persona en personal.yaml (o corregir el nombre).")
        for x in p["duplicados"]:
            add(MEDIA, "Diferencia", x["mes"], f"{x['persona']} tiene factura y además figura en "
                "pagos_personal.csv: puede estar contado dos veces.", None, "Dejar uno solo de los dos.")
    emp = s.at[mes, "empleados_931"] if "empleados_931" in s else None
    if p and pd.notna(emp) and int(emp) != p["n_registrados_yaml"]:
        add(MEDIA, "Diferencia", mes, f"El F.931 tiene {int(emp)} empleado(s) en nómina y personal.yaml tiene "
            f"{p['n_registrados_yaml']} registrado(s).", None, "Actualizar personal.yaml.")

    # ---- IIBB
    iibb = c.impuestos.get("iibb") or {}
    if iibb.get("criterio", "pendiente") == "pendiente" and pd.notna(s.at[mes, "iibb_max"]):
        add(MEDIA, "IIBB sin criterio", mes,
            f"Falta definir qué ventas van a cada alícuota. IIBB del mes entre {fmt_pesos(s.at[mes, 'iibb_min'])} "
            f"y {fmt_pesos(s.at[mes, 'iibb_max'])}; el resultado usa el {_USO.get(iibb.get("usar_en_resultado", "maximo"), "máximo")}.",
            float(s.at[mes, "iibb_max"] - s.at[mes, "iibb_min"]),
            "Definir el criterio en impuestos.yaml (tipo_comprobante, lista_cuit o porcentaje).")

    # ---- banco
    for m in [mes_sumar(mes, -2), mes_sumar(mes, -1), mes]:
        if m in s.index and pd.notna(s.at[m, "dep_efectivo"]) and s.at[m, "dep_efectivo"] > 0:
            sc = s.at[m, "ventas_sc"]
            add(MEDIA, "Depósito en efectivo", m,
                f"Depósitos en efectivo en el banco por {fmt_pesos(s.at[m, 'dep_efectivo'])}"
                + ("" if pd.isna(sc) else f" (ventas sin comprobante cargadas: {fmt_pesos(sc)})")
                + ". Pueden ser ventas sin comprobante.",
                float(s.at[m, "dep_efectivo"]),
                "Preguntar el origen. Si son ventas, cargarlas en ventas_sin_comprobante.csv.")
    for e in carga.extractos:
        if e.get("correcciones") or not e.get("cierra", True):
            add(MEDIA, "Diferencia", e["carpeta"], f"Extracto {e['archivo']}: {e['correcciones']} movimiento(s) "
                "con importe corregido por diferencia de saldos.", None, "Controlar contra el PDF.")
    cuentas = {x["cuenta"] for x in ctx.caja_detalle if not x.get("inversion")}
    meses_con_saldo = {x["mes"] for x in ctx.caja_detalle}
    if cuentas and mes not in meses_con_saldo:
        add(MEDIA, "Falta dato", mes, "No hay extracto bancario ni saldos.csv de este mes: la caja queda sin dato.",
            None, f"Dejar el extracto en entrada/{mes}/ o cargar saldos.csv (fecha;cuenta;saldo).")
    if s["inversion_neta"].notna().any() and s["inversiones"].isna().all():
        add(INFO, "Caja", mes, "Hay movimientos con fondos de inversión pero no su saldo: la caja "
            "muestra sólo la cuenta corriente.", None,
            "Si se quiere ver la inversión, cargar su saldo de fin de mes en saldos.csv con el nombre del fondo.")

    if ctx.mes_incompleto:
        add(MEDIA, "Mes incompleto", mes, f"Los comprobantes de ARCA llegan hasta el "
            f"{ctx.datos_hasta.strftime('%d/%m/%Y')}: el mes todavía no está completo y el resultado es provisorio.",
            None, "Volver a descargar Mis Comprobantes después del fin de mes y correr el cierre de nuevo.")

    # ---- fuentes opcionales
    if "parte" not in ctx.fuentes:
        add(INFO, "Falta fuente", mes, f"No hay parte diario: los KPIs de {c.unidad_plural}, stock, merma y consumo "
            "quedan sin dato.", None, "Exportar el CSV del Google Form a entrada/AAAA-MM/parte_diario.csv.")
    if "ventas_sc" not in ctx.fuentes:
        add(INFO, "Falta fuente", mes, "No se cargaron ventas sin comprobante: 'ventas totales' = sólo facturadas.",
            None, "Si hay ventas sin factura, cargarlas en ventas_sin_comprobante.csv (fecha;concepto;monto).")

    df = pd.DataFrame(A, columns=COLUMNAS)
    orden = {ALTA: 0, MEDIA: 1, INFO: 2}
    df["_o"] = df["gravedad"].map(orden)
    return df.sort_values(["_o", "mes", "tipo"], ascending=[True, False, True]).drop(columns="_o").reset_index(drop=True)
