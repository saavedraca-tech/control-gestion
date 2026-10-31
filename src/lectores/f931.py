"""Formulario F.931 (SUSS) en PDF, uno por mes."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from ..util import ErrorUsuario, numero_ar, solo_digitos
from . import normalizar
from .pdf import texto_pdf

CODIGOS = ["301", "302", "351", "352", "312", "028"]
# Costo laboral registrado = Rem. 1 + contribuciones (351, 352), ART (312) y seguro de vida (028).
CODIGOS_COSTO = ["351", "352", "312", "028"]
NUM = r"(-?[\d\.]+,\d{2})"


def es_f931(texto: str) -> bool:
    return "931" in texto and "Suma de Rem. 1" in texto


def extraer(texto: str, nombre_archivo: str = "") -> dict:
    def buscar(patron, obligatorio=True):
        m = re.search(patron, texto)
        if not m and obligatorio:
            raise ErrorUsuario(f"{nombre_archivo}: no encontré '{patron}' en el F.931.")
        return m

    m = buscar(r"\b(0[1-9]|1[0-2])/(20\d{2})\b")
    periodo = f"{m.group(2)}-{m.group(1)}"
    cuit = buscar(r"C\.U\.I\.T\.\s*([\d\-]+)", False)
    rect = buscar(r"Rect\.\s*\(1/9\):\s*(\d)", False)
    datos = {
        "periodo": periodo,
        "cuit": solo_digitos(cuit.group(1)) if cuit else "",
        "rectificativa": int(rect.group(1)) if rect else 0,
        "empleados": int(buscar(r"Empleados en n[oó]mina:\s*(\d+)").group(1)),
        "rem1": numero_ar(buscar(r"Suma de Rem\. 1:\s*" + NUM).group(1)),
    }
    for cod in CODIGOS:
        m = re.search(rf"(?<!\d){cod}\s*-\s*[^\d\n]+?\s{NUM}", texto)
        datos["c" + cod] = numero_ar(m.group(1)) if m else 0.0
    datos["costo_laboral"] = datos["rem1"] + sum(datos["c" + c] for c in CODIGOS_COSTO)
    datos["contribuciones"] = sum(datos["c" + c] for c in CODIGOS_COSTO)
    return datos


def leer(ruta: Path, cuit_empresa: str) -> pd.DataFrame:
    texto = texto_pdf(ruta)
    if not es_f931(texto):
        raise ErrorUsuario(f"{ruta.name} no parece un F.931.")
    d = extraer(texto, ruta.name)
    if d["cuit"] and d["cuit"] != cuit_empresa:
        raise ErrorUsuario(f"{ruta.name} es del CUIT {d['cuit']}, no de esta empresa ({cuit_empresa}).")
    fecha = pd.Timestamp(d["periodo"] + "-01")
    filas = []
    for k, v in d.items():
        if k in ("periodo", "cuit"):
            continue
        filas.append({"fuente": "f931", "clave": f"f931|{d['periodo']}|{k}", "archivo": ruta.name,
                      "fecha": fecha, "mes": d["periodo"], "concepto": k, "valor": float(v)})
    return normalizar(pd.DataFrame(filas))
