"""Personal registrado y no registrado (personal.yaml) y escenario de regularización.

Costo laboral total = costo F.931 + pagos a no registrados. Los pagos a no registrados salen de
entrada/AAAA-MM/pagos_personal.csv (persona;monto) y de las facturas de proveedores clasificadas en
un rubro marcado `personal: true` (p. ej. un empleado que factura como monotributista).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Cliente
from .util import normalizar, solo_digitos


def personas(c: Cliente) -> list[dict]:
    out = []
    for p in c.personal.get("personas", []) or []:
        out.append({**p, "registrado": bool(p.get("registrado", True)),
                    "_nombres": [normalizar(x) for x in [p.get("nombre", "")] + (p.get("alias") or []) if x],
                    "_cuit": solo_digitos(p.get("cuit", ""))})
    return out


def _quien(lista: list[dict], nombre: str = "", doc: str = "") -> dict | None:
    n, d = normalizar(nombre), solo_digitos(doc)
    for p in lista:
        if d and p["_cuit"] and d == p["_cuit"]:
            return p
        if n and any(x and (x in n or n in x) for x in p["_nombres"]):
            return p
    return None


def calcular(c: Cliente, base: pd.DataFrame, compras: pd.DataFrame, rubros_personal: list, meses: list,
             serie: pd.DataFrame) -> dict:
    lista = personas(c)
    no_reg = [p for p in lista if not p["registrado"]]
    filas, sin_identificar = [], []

    pagos = base[base["fuente"] == "pagos_personal"]
    for r in pagos.itertuples():
        p = _quien(lista, r.nombre)
        if p is None:
            sin_identificar.append({"mes": r.mes, "nombre": r.nombre, "monto": r.valor})
        filas.append({"mes": r.mes, "persona": p["nombre"] if p else r.nombre, "origen": "pagos_personal.csv",
                      "monto": float(r.valor), "registrado": p["registrado"] if p else False})
    if len(compras) and rubros_personal:
        fc = compras[compras["rubro"].isin(rubros_personal)]
        for r in fc.itertuples():
            p = _quien(lista, r.nombre, r.doc)
            filas.append({"mes": r.mes, "persona": p["nombre"] if p else r.nombre,
                          "origen": f"factura {r.concepto}", "monto": float(r.importe),
                          "registrado": p["registrado"] if p else False})
    det = pd.DataFrame(filas, columns=["mes", "persona", "origen", "monto", "registrado"])
    pagos_nr = det[~det["registrado"].astype(bool)].groupby("mes")["monto"].sum().reindex(meses)

    # Posible doble carga: misma persona con factura y con pago en pagos_personal.csv el mismo mes.
    duplicados = []
    if len(det):
        g = det.groupby(["mes", "persona"])["origen"].agg(lambda x: set(o.split(" ")[0] for o in x))
        duplicados = [{"mes": m, "persona": p} for (m, p), o in g.items() if len(o) > 1]

    return {"personas": lista, "no_registrados": no_reg, "n_no_registrados": len(no_reg),
            "n_registrados_yaml": len([p for p in lista if p["registrado"]]),
            "detalle": det, "pagos_nr": pagos_nr, "sin_identificar": sin_identificar,
            "duplicados": duplicados}


def escenario_regularizacion(c: Cliente, serie: pd.DataFrame, mes: str, pers: dict) -> dict:
    """Cuánto costaría registrar a cada persona no registrada y cómo cambiaría el resultado.

    Sueldo bruto: el cargado en personal.yaml (sueldo_bruto_regularizacion) o, si no hay, la
    remuneración promedio por empleado del último F.931. Contribuciones: los mismos % efectivos
    del último F.931 del cliente (351 + 352 + 312 + 028 sobre Rem. 1). SAC prorrateado si se pide.
    """
    cfg = c.personal.get("regularizacion") or {}
    f9 = serie[serie["rem1_931"].notna() & ~serie["f931_estimado"].astype(bool)]
    f9 = f9[f9.index <= mes]
    if f9.empty:
        tasa, bruto_ref, mes_ref = None, None, None
    else:
        u = f9.iloc[-1]
        mes_ref = f9.index[-1]
        tasa = float(u["contrib_931"] / u["rem1_931"]) if u["rem1_931"] else None
        bruto_ref = float(u["rem1_931"] / u["empleados_931"]) if u["empleados_931"] else None
    sac = 13 / 12 if cfg.get("incluir_sac", True) else 1.0
    det = pers["detalle"]
    filas = []
    for p in pers["no_registrados"]:
        bruto = p.get("sueldo_bruto_regularizacion") or (
            cfg.get("sueldo_bruto_por_defecto") if isinstance(cfg.get("sueldo_bruto_por_defecto"), (int, float))
            else bruto_ref)
        origen_bruto = ("personal.yaml" if p.get("sueldo_bruto_regularizacion")
                        else f"promedio por empleado del F.931 {mes_ref}" if bruto_ref else "sin dato")
        pagos = det[(det["persona"] == p["nombre"])]
        ult3 = pagos[pagos["mes"] <= mes].groupby("mes")["monto"].sum().tail(3)
        pago_actual = float(ult3.mean()) if len(ult3) else None
        costo = bruto * (1 + tasa) * sac if (bruto and tasa is not None) else None
        filas.append({"persona": p["nombre"], "sueldo_bruto": bruto, "origen_bruto": origen_bruto,
                      "contribuciones_pct": tasa, "costo_mensual_registrado": costo,
                      "pago_actual_promedio": pago_actual,
                      "diferencia_mensual": (costo - pago_actual) if (costo is not None and pago_actual is not None)
                      else costo})
    res_mes = serie.at[mes, "resultado"] if mes in serie.index else np.nan
    dif_total = sum(f["diferencia_mensual"] or 0 for f in filas)
    return {"filas": filas, "tasa_contribuciones": tasa, "mes_referencia": mes_ref, "incluye_sac": sac > 1,
            "resultado_actual": None if pd.isna(res_mes) else float(res_mes),
            "diferencia_total": dif_total,
            "resultado_regularizado": None if pd.isna(res_mes) else float(res_mes) - dif_total}
