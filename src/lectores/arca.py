"""Comprobantes emitidos y recibidos de ARCA ("Mis Comprobantes", CSV)."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from ..util import ErrorUsuario, solo_digitos
from . import normalizar

# Notas de crédito: restan.
TIPOS_NOTA_CREDITO = {3, 8, 13, 53, 113, 203, 208, 213}

# Letra según código de comprobante ARCA (tabla general de comprobantes).
LETRA = {}
for _l, _cods in {
    "A": [1, 2, 3, 4, 5, 39, 60, 63, 201, 202, 203],
    "B": [6, 7, 8, 9, 10, 40, 61, 64, 206, 207, 208],
    "C": [11, 12, 13, 15, 211, 212, 213],
    "M": [51, 52, 53, 54],
    "E": [19, 20, 21],
}.items():
    for _c in _cods:
        LETRA[_c] = _l

NOMBRE_TIPO = {
    1: "Factura A", 2: "Nota de débito A", 3: "Nota de crédito A", 6: "Factura B",
    7: "Nota de débito B", 8: "Nota de crédito B", 11: "Factura C", 12: "Nota de débito C",
    13: "Nota de crédito C", 17: "Liquidación servicios públicos", 51: "Factura M",
    53: "Nota de crédito M", 63: "Liquidación A", 81: "Tique factura A", 82: "Tique factura B",
    83: "Tique", 113: "Tique nota de crédito A", 201: "Factura de crédito electrónica A",
    203: "Nota de crédito electrónica A", 206: "Factura de crédito electrónica B",
    208: "Nota de crédito electrónica B", 211: "Factura de crédito electrónica C",
    213: "Nota de crédito electrónica C",
}

COLS_IMPORTE = ["Imp. Neto Gravado Total", "Imp. Neto No Gravado", "Imp. Op. Exentas",
                "Otros Tributos", "Total IVA", "Imp. Total"]
OBLIGATORIAS = ["Fecha de Emisión", "Tipo de Comprobante", "Punto de Venta", "Número Desde",
                "Tipo Cambio", "Moneda"] + COLS_IMPORTE


def es_archivo_arca(ruta: Path) -> str | None:
    """Devuelve 'emitidos' / 'recibidos' si el CSV parece de Mis Comprobantes, si no None."""
    try:
        with open(ruta, encoding="utf-8-sig") as f:
            cab = f.readline()
    except UnicodeDecodeError:
        with open(ruta, encoding="latin-1") as f:
            cab = f.readline()
    if "Fecha de Emisi" not in cab or "Tipo de Comprobante" not in cab:
        return None
    return "recibidos" if "Denominación Emisor" in cab or "Denominacion Emisor" in cab else "emitidos"


def leer(ruta: Path, cuit_empresa: str) -> pd.DataFrame:
    fuente = es_archivo_arca(ruta)
    if fuente is None:
        raise ErrorUsuario(f"{ruta.name} no parece un CSV de 'Mis Comprobantes' de ARCA.")

    # Control: que el archivo sea de esta empresa (ARCA pone el CUIT en el nombre del archivo).
    cuits_nombre = re.findall(r"(?<!\d)(\d{11})(?!\d)", ruta.name)
    if cuits_nombre and cuit_empresa not in cuits_nombre:
        raise ErrorUsuario(f"{ruta.name} es de otro CUIT ({cuits_nombre[0]}), no de esta empresa "
                           f"({cuit_empresa}). Revisá que esté en la carpeta del cliente correcto.")

    doc_col, nom_col = (("Nro. Doc. Emisor", "Denominación Emisor") if fuente == "recibidos"
                        else ("Nro. Doc. Receptor", "Denominación Receptor"))
    try:
        d = pd.read_csv(ruta, sep=";", decimal=",", thousands=None, encoding="utf-8-sig",
                        dtype={doc_col: str, "Nro. Doc. Receptor": str, "Nro. Doc. Emisor": str})
    except UnicodeDecodeError:
        d = pd.read_csv(ruta, sep=";", decimal=",", encoding="latin-1",
                        dtype={doc_col: str, "Nro. Doc. Receptor": str, "Nro. Doc. Emisor": str})
    faltan = [c for c in OBLIGATORIAS + [doc_col, nom_col] if c not in d.columns]
    if faltan:
        raise ErrorUsuario(f"A {ruta.name} le faltan columnas: {', '.join(faltan)}. "
                           "Descargalo de nuevo desde Mis Comprobantes > Exportar CSV.")
    if d.empty:
        from . import vacio
        return vacio()

    for c in COLS_IMPORTE:
        d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0.0)
    tc = pd.to_numeric(d["Tipo Cambio"], errors="coerce").fillna(1.0)
    moneda = d["Moneda"].astype(str).str.strip().str.upper()
    tc = tc.where(~moneda.isin(["$", "PES", "ARS"]), 1.0)  # en pesos el tipo de cambio es 1
    for c in COLS_IMPORTE:
        d[c] = d[c] * tc

    tipo = pd.to_numeric(d["Tipo de Comprobante"], errors="coerce").astype("Int64")
    letra = tipo.map(lambda t: LETRA.get(int(t), "") if pd.notna(t) else "")
    neto = d["Imp. Neto Gravado Total"] + d["Imp. Neto No Gravado"] + d["Imp. Op. Exentas"]
    # Comprobantes C: no discriminan IVA y ARCA informa sólo el total => neto = total.
    es_c = letra.eq("C") & neto.abs().lt(0.005)
    neto = neto.where(~es_c, d["Imp. Total"] - d["Otros Tributos"])
    resto = d["Imp. Total"] - (neto + d["Total IVA"] + d["Otros Tributos"])
    no_discr = resto.where(resto.abs() > 0.01, 0.0)

    doc = d[doc_col].map(lambda s: solo_digitos(s) if pd.notna(s) else "")
    nombre = d[nom_col].fillna("").astype(str).str.strip()
    signo = tipo.map(lambda t: -1 if pd.notna(t) and int(t) in TIPOS_NOTA_CREDITO else 1)
    fecha = pd.to_datetime(d["Fecha de Emisión"], errors="coerce", dayfirst=False)
    if fecha.isna().any():
        malas = d.loc[fecha.isna(), "Fecha de Emisión"].head(3).tolist()
        raise ErrorUsuario(f"{ruta.name}: hay fechas que no se pueden leer: {malas}")

    nro = pd.to_numeric(d["Número Desde"], errors="coerce").astype("Int64").astype(str)
    pv = pd.to_numeric(d["Punto de Venta"], errors="coerce").astype("Int64").astype(str)
    clave = (fuente + "|" + tipo.astype(str) + "|" + pv + "|" + nro + "|" + doc.where(doc != "", "SD"))

    out = pd.DataFrame({
        "fuente": fuente, "clave": clave, "archivo": ruta.name, "fecha": fecha,
        "mes": fecha.dt.strftime("%Y-%m"), "tipo_cbte": tipo, "letra": letra, "signo": signo,
        "doc": doc, "nombre": nombre, "concepto": tipo.map(lambda t: NOMBRE_TIPO.get(int(t), f"Tipo {t}")),
        "neto": neto, "iva": d["Total IVA"], "otros_trib": d["Otros Tributos"],
        "no_discriminado": no_discr, "total": d["Imp. Total"],
    })
    return normalizar(out.drop_duplicates("clave", keep="last"))
