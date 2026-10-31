"""Asigna cada compra (y cada gasto bancario) a un rubro de gasto según rubros.yaml del cliente.

Orden: 1) reglas, en el orden en que están (gana la primera que coincide; por CUIT o por texto
contenido en el nombre del proveedor); 2) patrones sospechosos de gasto personal -> A REVISAR;
3) sin regla -> A REVISAR. La clasificación se calcula en cada cierre: si alguien edita
rubros.yaml, el próximo cierre ya refleja el cambio en todos los meses.
"""
from __future__ import annotations

import pandas as pd

from .config import Cliente
from .util import mes_sumar, normalizar, solo_digitos


def _reglas(c: Cliente, clave: str = "reglas"):
    out = []
    for r in c.rubros.get(clave, []) or []:
        out.append({"cuit": solo_digitos(r.get("cuit", "")), "contiene": normalizar(r.get("contiene", "")),
                    "rubro": r["rubro"], "texto": r.get("contiene") or r.get("cuit")})
    return out


def clasificar_proveedor(c: Cliente, doc: str, nombre: str) -> tuple[str, str]:
    """Devuelve (rubro, motivo). motivo: 'regla: ...', 'patrón sospechoso: ...' o 'sin regla'."""
    nom = normalizar(nombre)
    doc = solo_digitos(doc)
    for r in _reglas(c):
        if r["cuit"] and r["cuit"] == doc:
            return r["rubro"], f"regla CUIT {r['cuit']}"
        if r["contiene"] and r["contiene"] in nom:
            return r["rubro"], f"regla '{r['texto']}'"
    for p in c.rubros.get("patrones_revisar", []) or []:
        if normalizar(p) and normalizar(p) in nom:
            return c.rubro_revisar, f"patrón sospechoso '{p}'"
    return c.rubro_revisar, "sin regla"


def clasificar_compras(c: Cliente, recibidos: pd.DataFrame) -> pd.DataFrame:
    """Agrega columnas rubro, motivo, mes_imputado e importe (neto con signo)."""
    r = recibidos.copy()
    if r.empty:
        return r.assign(rubro=pd.Series(dtype="string"), motivo=pd.Series(dtype="string"),
                        mes_imputado=pd.Series(dtype="string"), importe=pd.Series(dtype="float64"))
    pares = r[["doc", "nombre"]].drop_duplicates()
    mapa = {(d, n): clasificar_proveedor(c, d, n) for d, n in pares.itertuples(index=False)}
    res = [mapa[(d, n)] for d, n in zip(r["doc"], r["nombre"])]
    r["rubro"] = [x[0] for x in res]
    r["motivo"] = [x[1] for x in res]
    r["importe"] = r["neto"] * r["signo"]
    r["no_discriminado"] = r["no_discriminado"].fillna(0) * r["signo"]
    dev = {x["nombre"]: x.get("devengamiento", "mes_factura") for x in c.rubros.get("rubros", [])}
    r["mes_imputado"] = [mes_sumar(m, -1) if dev.get(rb) == "mes_anterior" else m
                         for m, rb in zip(r["mes"], r["rubro"])]
    return r


def clasificar_banco(c: Cliente, banco: pd.DataFrame) -> pd.DataFrame:
    """Gastos bancarios que no tienen comprobante en ARCA (p. ej. impuesto al cheque)."""
    reglas = _reglas(c, "movimientos_bancarios")
    b = banco[(banco["concepto"] != "SALDO_FINAL") & (banco["valor"] < 0)].copy()
    if b.empty or not reglas:
        return b.iloc[0:0].assign(rubro=pd.Series(dtype="string"), importe=pd.Series(dtype="float64"))
    def rubro(concepto):
        t = normalizar(concepto)
        for r in reglas:
            if r["contiene"] and r["contiene"] in t:
                return r["rubro"]
        return None
    b["rubro"] = b["concepto"].map(rubro)
    b = b[b["rubro"].notna()].copy()
    b["importe"] = -b["valor"]
    return b
