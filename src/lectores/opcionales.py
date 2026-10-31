"""CSV simples y opcionales: parte operativo, saldos, pagos al personal y ventas sin comprobante.

Aceptan separador ';' o ',' y números con coma decimal (1.234,56) o punto (1234.56).
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from ..util import ErrorUsuario, normalizar as norm_txt
from . import normalizar


def _leer_csv(ruta: Path) -> pd.DataFrame:
    for enc in ("utf-8-sig", "latin-1"):
        try:
            with open(ruta, encoding=enc) as f:
                cab = f.readline()
            sep = ";" if cab.count(";") >= cab.count(",") else ","
            d = pd.read_csv(ruta, sep=sep, encoding=enc, dtype=str, keep_default_na=False)
            d.columns = [c.strip() for c in d.columns]
            return d
        except UnicodeDecodeError:
            continue
    raise ErrorUsuario(f"No pude leer {ruta.name}. Guardalo como CSV UTF-8.")


def _num(s) -> float | None:
    s = str(s).strip().replace("$", "").replace(" ", "")
    if s == "":
        return None
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", s) or ("," in s and "." not in s):
        s = s.replace(".", "").replace(",", ".")
    elif "," in s and "." in s:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _fecha(serie: pd.Series, archivo: str) -> pd.Series:
    s = serie.astype(str).str.strip().str.split(" ").str[0]
    iso = s.str.match(r"^\d{4}-\d{2}-\d{2}$")
    f = pd.to_datetime(s.where(iso), errors="coerce", format="%Y-%m-%d")
    f = f.fillna(pd.to_datetime(s.where(~iso), errors="coerce", dayfirst=True))
    if f.isna().any():
        malas = serie[f.isna()].head(3).tolist()
        raise ErrorUsuario(f"{archivo}: no puedo leer estas fechas: {malas}. Usá dd/mm/aaaa.")
    return f


def _col(d: pd.DataFrame, nombre: str, archivo: str, obligatoria=True):
    objetivo = norm_txt(nombre)
    for c in d.columns:
        if norm_txt(c) == objetivo:
            return c
    if obligatoria:
        raise ErrorUsuario(f"{archivo}: falta la columna '{nombre}'. Columnas encontradas: {', '.join(d.columns)}")
    return None


def leer_parte(ruta: Path, columnas: dict) -> pd.DataFrame:
    """columnas: rol -> nombre de columna en el CSV (definido en kpis.yaml del cliente)."""
    d = _leer_csv(ruta)
    col_fecha = _col(d, columnas.get("fecha", "fecha"), ruta.name)
    fechas = _fecha(d[col_fecha], ruta.name)
    filas = []
    for rol, nombre_col in columnas.items():
        if rol == "fecha":
            continue
        c = _col(d, nombre_col, ruta.name, obligatoria=False)
        if c is None:
            continue
        for f, v in zip(fechas, d[c]):
            val = _num(v)
            if val is not None:
                filas.append({"fecha": f, "concepto": rol, "valor": val})
    out = pd.DataFrame(filas, columns=["fecha", "concepto", "valor"])
    out = out.assign(fuente="parte", archivo=ruta.name, mes=out["fecha"].dt.strftime("%Y-%m"),
                     clave="parte|" + out["fecha"].dt.strftime("%Y-%m-%d") + "|" + out["concepto"])
    return normalizar(out.drop_duplicates("clave", keep="last"))


def leer_saldos(ruta: Path) -> pd.DataFrame:
    d = _leer_csv(ruta)
    cf, cc, cs = (_col(d, n, ruta.name) for n in ("fecha", "cuenta", "saldo"))
    f = _fecha(d[cf], ruta.name)
    out = pd.DataFrame({"fecha": f, "cuenta": d[cc].str.strip(), "valor": d[cs].map(_num)})
    out = out.dropna(subset=["valor"]).assign(
        fuente="saldos", archivo=ruta.name, concepto="SALDO", mes=lambda x: x.fecha.dt.strftime("%Y-%m"))
    out["clave"] = "saldos|" + out["fecha"].dt.strftime("%Y-%m-%d") + "|" + out["cuenta"].map(norm_txt)
    out["saldo"] = out["valor"]
    return normalizar(out.drop_duplicates("clave", keep="last"))


def leer_pagos_personal(ruta: Path, mes: str) -> pd.DataFrame:
    d = _leer_csv(ruta)
    cp, cm = _col(d, "persona", ruta.name), _col(d, "monto", ruta.name)
    out = pd.DataFrame({"nombre": d[cp].str.strip(), "valor": d[cm].map(_num)}).dropna(subset=["valor"])
    out = out.groupby("nombre", as_index=False)["valor"].sum()
    out = out.assign(fuente="pagos_personal", archivo=ruta.name, mes=mes, fecha=pd.Timestamp(mes + "-01"),
                     concepto="PAGO", clave="pagos_personal|" + mes + "|" + out["nombre"].map(norm_txt))
    return normalizar(out)


def leer_ventas_sc(ruta: Path) -> pd.DataFrame:
    d = _leer_csv(ruta)
    cf, cc, cm = _col(d, "fecha", ruta.name), _col(d, "concepto", ruta.name), _col(d, "monto", ruta.name)
    f = _fecha(d[cf], ruta.name)
    out = pd.DataFrame({"fecha": f, "concepto": d[cc].str.strip(), "valor": d[cm].map(_num)})
    out = out.dropna(subset=["valor"]).reset_index(drop=True)
    out = out.assign(fuente="ventas_sc", archivo=ruta.name, mes=out.fecha.dt.strftime("%Y-%m"),
                     neto=out["valor"], signo=1)
    out["clave"] = ("ventas_sc|" + out["fecha"].dt.strftime("%Y-%m-%d") + "|" + out.index.astype(str)
                    + "|" + out["concepto"].map(norm_txt))
    return normalizar(out)
