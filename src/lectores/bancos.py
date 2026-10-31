"""Extractos bancarios en PDF.

Cada banco tiene su propio formato; acá se registra un intérprete por banco. Hoy: Banco Galicia
(Resumen de Cuenta Corriente). Para agregar otro banco se suma una función a FORMATOS.
Si el formato no se reconoce, el cierre sigue y avisa que hay que cargar saldos.csv.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from ..util import ErrorUsuario, numero_ar
from . import normalizar
from .pdf import texto_pdf

IMPORTE = r"-?\d{1,3}(?:\.\d{3})*,\d{2}"
RUIDO = ("Resumen de Cuenta", "Fecha Descripci", "Página", "Pagina")


def _galicia(texto: str, archivo: str) -> tuple[pd.DataFrame, dict]:
    m_cta = re.search(r"N°\s*([\d\-]+\s*[\d\-]*)", texto)
    cuenta = "Galicia " + (m_cta.group(1).strip() if m_cta else "cuenta")
    if "Moneda Extranjera" in texto[:600] or "Dólares" in texto[:600]:
        cuenta += " (USD)"
    fechas = re.findall(r"\b(\d{2}/\d{2}/\d{4})\b", texto[:3000])
    saldos_cab = re.findall(r"\$\s*(" + IMPORTE + ")", texto[:3000])
    desde = datetime.strptime(fechas[0], "%d/%m/%Y") if fechas else None
    hasta = datetime.strptime(fechas[1], "%d/%m/%Y") if len(fechas) > 1 else None
    saldo_ini = numero_ar(saldos_cab[0]) if saldos_cab else None
    saldo_fin = numero_ar(saldos_cab[1]) if len(saldos_cab) > 1 else None

    movs, actual = [], None
    # El saldo deudor (descubierto) viene con el signo al final: "23.357,35-".
    patron = re.compile(r"^(\d{2}/\d{2}/\d{2})\s+(.*?)\s+(" + IMPORTE + r")\s+(" + IMPORTE + r")(-?)\s*$")
    for linea in texto.splitlines():
        linea = linea.strip()
        m = patron.match(linea)
        if m:
            desc = re.sub(r"\s+\d{2}[A-Z0-9]{2}$", "", m.group(2)).strip()  # quita el código de origen (00G1, 00C4)
            actual = {"fecha": datetime.strptime(m.group(1), "%d/%m/%y"), "concepto": desc,
                      "valor": numero_ar(m.group(3)),
                      "saldo": numero_ar(m.group(4)) * (-1 if m.group(5) else 1), "detalle": []}
            movs.append(actual)
            continue
        if re.match(r"^\d{2}/\d{2}/\d{2}\b", linea) or not linea or any(r in linea for r in RUIDO) \
                or re.fullmatch(r"\d{14,}[A-Z]?", linea) or linea.startswith(("Consolidado", "PERIODO", "TOTAL")):
            if linea.startswith(("Consolidado", "PERIODO", "TOTAL")):
                actual = None
            continue
        if actual is not None and len(actual["detalle"]) < 3:
            actual["detalle"].append(linea)

    # Control de la cadena de saldos: si un importe se leyó mal, se corrige con la diferencia de saldos.
    correcciones = 0
    previo = saldo_ini
    for mv in movs:
        if previo is not None and abs(previo + mv["valor"] - mv["saldo"]) > 0.02:
            correcciones += 1
            mv["valor"] = round(mv["saldo"] - previo, 2)
        previo = mv["saldo"]
    # El saldo final sale del último movimiento; el del encabezado sólo se usa como control.
    saldo_cab = saldo_fin
    if movs:
        saldo_fin = movs[-1]["saldo"]
    if hasta is None and movs:
        hasta = movs[-1]["fecha"]
    info = {"cuenta": cuenta, "desde": desde, "hasta": hasta, "saldo_inicial": saldo_ini,
            "saldo_final": saldo_fin, "movimientos": len(movs), "correcciones": correcciones,
            "cierra": saldo_cab is None or saldo_fin is None or abs(abs(saldo_fin) - saldo_cab) < 0.02}

    filas = []
    for i, mv in enumerate(movs):
        det = mv["detalle"]
        doc = next((re.sub(r"\D", "", x) for x in det if re.fullmatch(r"\d{11}", x.strip())), "")
        nombre = det[0] if det else ""
        filas.append({"fecha": mv["fecha"], "concepto": mv["concepto"], "nombre": nombre, "doc": doc,
                      "valor": mv["valor"], "saldo": mv["saldo"], "orden": i})
    return pd.DataFrame(filas), info


FORMATOS = {
    "galicia": (lambda t: "Resumen de Cuenta" in t and ("galicia" in t.lower() or "0070" in t), _galicia),
}


def es_extracto(texto: str) -> str | None:
    for nombre, (detectar, _) in FORMATOS.items():
        if detectar(texto):
            return nombre
    return None


def leer(ruta: Path, cuit_empresa: str) -> tuple[pd.DataFrame, dict]:
    texto = texto_pdf(ruta)
    formato = es_extracto(texto)
    if formato is None:
        raise ErrorUsuario(f"{ruta.name}: no reconozco el formato de este extracto bancario. "
                           "Cargá el saldo de fin de mes en saldos.csv (fecha;cuenta;saldo).")
    cuits = re.findall(r"\b(\d{2}-\d{8}-\d)\b", texto[:1500])
    if cuits and cuits[0].replace("-", "") != cuit_empresa:
        raise ErrorUsuario(f"{ruta.name} es del CUIT {cuits[0]}, no de esta empresa.")
    movs, info = FORMATOS[formato][1](texto, ruta.name)
    info["formato"] = formato
    info["archivo"] = ruta.name
    if movs.empty:
        filas = pd.DataFrame(columns=["fecha", "concepto", "nombre", "doc", "valor", "saldo", "orden"])
    else:
        filas = movs
    filas = filas.assign(
        fuente="banco", archivo=ruta.name, cuenta=info["cuenta"],
        mes=pd.to_datetime(filas["fecha"]).dt.strftime("%Y-%m") if len(filas) else None,
        clave=[f"banco|{info['cuenta']}|{pd.Timestamp(f).date()}|{o}|{v:.2f}"
               for f, o, v in zip(filas["fecha"], filas["orden"], filas["valor"])] if len(filas) else None,
    )
    # Saldo final del extracto: una fila aparte (concepto SALDO_FINAL).
    if info["saldo_final"] is not None and info["hasta"] is not None:
        hasta = pd.Timestamp(info["hasta"])
        filas = pd.concat([filas, pd.DataFrame([{
            "fuente": "banco", "archivo": ruta.name, "cuenta": info["cuenta"], "fecha": hasta,
            "mes": hasta.strftime("%Y-%m"), "concepto": "SALDO_FINAL", "valor": info["saldo_final"],
            "saldo": info["saldo_final"], "clave": f"banco|{info['cuenta']}|SALDO_FINAL|{hasta.date()}"}])],
            ignore_index=True)
    return normalizar(filas), info
