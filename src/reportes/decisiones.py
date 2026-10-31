"""Tabla de decisiones: se edita en la hoja "Decisiones" del Excel y se conserva de un mes al otro.

Al generar un tablero se toma la hoja Decisiones del Excel más recientemente modificado entre los
meses anteriores o iguales al del cierre (así cuentan los cambios que el estudio haya hecho a mano).
También se guarda una copia en datos/decisiones.csv.
"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd

COLUMNAS = ["Fecha", "Decisión", "Responsable", "Vence", "Estado", "Notas"]
ESTADOS = ["Pendiente", "En curso", "Hecha", "Descartada"]


def _a_fecha(v):
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return pd.to_datetime(str(v), dayfirst=True).date()
    except Exception:
        return None


def leer(c, mes: str) -> list[dict]:
    from openpyxl import load_workbook
    candidatos = []
    if c.salida.is_dir():
        for d in c.salida.iterdir():
            if d.is_dir() and d.name <= mes:
                for f in d.glob("Tablero_*.xlsx"):
                    if not f.name.startswith("~$"):
                        candidatos.append(f)
    for f in sorted(candidatos, key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            wb = load_workbook(f, read_only=True, data_only=True)
        except Exception:
            continue
        if "Decisiones" not in wb.sheetnames:
            continue
        ws = wb["Decisiones"]
        filas, cab = [], None
        for row in ws.iter_rows(values_only=True):
            if cab is None:
                if row and row[0] == COLUMNAS[0] and row[1] == COLUMNAS[1]:
                    cab = list(row)
                continue
            if not any(v not in (None, "") for v in row[:6]):
                continue
            d = dict(zip(COLUMNAS, list(row[:6]) + [None] * (6 - len(row[:6]))))
            d["Fecha"], d["Vence"] = _a_fecha(d["Fecha"]), _a_fecha(d["Vence"])
            d["Estado"] = d["Estado"] or "Pendiente"
            filas.append(d)
        wb.close()
        return filas
    archivo = c.datos / "decisiones.csv"
    if archivo.exists():
        df = pd.read_csv(archivo, sep=";", dtype=str, keep_default_na=False)
        out = []
        for r in df.to_dict("records"):
            r["Fecha"], r["Vence"] = _a_fecha(r.get("Fecha")), _a_fecha(r.get("Vence"))
            out.append({k: r.get(k) for k in COLUMNAS})
        return out
    return []


def guardar_copia(c, filas: list[dict]) -> None:
    c.datos.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(filas, columns=COLUMNAS)
    for col in ["Fecha", "Vence"]:
        df[col] = df[col].map(lambda d: d.strftime("%d/%m/%Y") if d else "")
    df.to_csv(c.datos / "decisiones.csv", sep=";", index=False, encoding="utf-8-sig")


def pendientes(filas: list[dict], hoy: date) -> list[dict]:
    out = []
    for f in filas:
        if (f.get("Estado") or "Pendiente") in ("Hecha", "Descartada"):
            continue
        f = dict(f)
        f["vencida"] = bool(f.get("Vence") and f["Vence"] < hoy)
        out.append(f)
    return out
