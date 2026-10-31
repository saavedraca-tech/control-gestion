"""Base acumulada por cliente (datos/historico.parquet).

En cada cierre se leen TODAS las carpetas entrada/AAAA-MM (de la más vieja a la más nueva) y se
actualiza la base: lo que trae un archivo reemplaza lo que había para esa fuente y esos meses.
Por eso reprocesar un mes no duplica nada y un archivo corregido pisa al anterior. Lo que ya está
en la base se conserva aunque se borren carpetas viejas de entrada/.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from .config import Cliente
from .lectores import arca, bancos, f931, opcionales, vacio, normalizar
from .lectores.pdf import texto_pdf
from .util import ErrorUsuario

# Columnas que definen "el mismo bloque de datos" para reemplazar.
BLOQUE = {"banco": ["fuente", "cuenta", "mes"], "saldos": ["clave"]}


@dataclass
class ResultadoCarga:
    base: pd.DataFrame
    archivos: list = field(default_factory=list)   # dicts: archivo, carpeta, fuente, filas, meses
    errores: list = field(default_factory=list)    # dicts: archivo, detalle
    extractos: list = field(default_factory=list)  # info de cada extracto bancario
    ignorados: list = field(default_factory=list)
    leidos: int = 0
    sin_cambios: int = 0


def _upsert(base: pd.DataFrame, nuevo: pd.DataFrame) -> pd.DataFrame:
    if nuevo.empty:
        return base
    if base.empty:
        return nuevo.drop_duplicates("clave", keep="last").reset_index(drop=True)
    fuente = nuevo["fuente"].iloc[0]
    cols = BLOQUE.get(fuente, ["fuente", "mes"])
    claves = nuevo[cols].drop_duplicates()
    marca = base.merge(claves.assign(_x=1), on=cols, how="left")["_x"].notna().to_numpy()
    base = base[~marca]
    base = base[~base["clave"].isin(nuevo["clave"])]
    return pd.concat([base, nuevo], ignore_index=True)


def _leer_archivo(c: Cliente, ruta: Path, mes_carpeta: str):
    """Devuelve (fuente, DataFrame, info_extra) o (None, None, motivo) si se ignora."""
    suf = ruta.suffix.lower()
    nombre = ruta.name.lower()
    if suf == ".csv":
        if arca.es_archivo_arca(ruta):
            df = arca.leer(ruta, c.cuit)
            return df["fuente"].iloc[0] if len(df) else "arca", df, None
        if "pagos_personal" in nombre:
            return "pagos_personal", opcionales.leer_pagos_personal(ruta, mes_carpeta), None
        if "saldo" in nombre:
            return "saldos", opcionales.leer_saldos(ruta), None
        if "sin_comprobante" in nombre or "ventas_sc" in nombre:
            return "ventas_sc", opcionales.leer_ventas_sc(ruta), None
        if "parte" in nombre:
            cols = (c.kpis.get("parte_operativo") or {}).get("columnas") or {}
            if not cols:
                return None, None, "hay un parte operativo pero kpis.yaml no define sus columnas"
            return "parte", opcionales.leer_parte(ruta, cols), None
        return None, None, "no reconozco este CSV (¿nombre?)"
    if suf == ".pdf":
        texto = texto_pdf(ruta)
        if f931.es_f931(texto):
            return "f931", f931.leer(ruta, c.cuit), None
        if bancos.es_extracto(texto):
            df, info = bancos.leer(ruta, c.cuit)
            return "banco", df, info
        return None, None, "PDF que no es F.931 ni extracto bancario reconocido"
    return None, None, "tipo de archivo no usado"


VERSION_LECTORES = "1"  # subir este número obliga a releer todos los archivos (cambio en los lectores)


def _firma(c: Cliente, ruta: Path) -> str:
    st = ruta.stat()
    extra = ""
    if "parte" in ruta.name.lower():
        extra = json.dumps((c.kpis.get("parte_operativo") or {}).get("columnas") or {}, sort_keys=True)
    return f"{VERSION_LECTORES}|{c.cuit}|{st.st_size}|{st.st_mtime_ns}|{extra}"


def cargar(c: Cliente) -> ResultadoCarga:
    """Lee los archivos nuevos o modificados de entrada/ y actualiza datos/historico.parquet.

    Para no releer todo cada mes se guarda una firma de cada archivo (datos/archivos_procesados.json).
    Si un archivo de la carpeta AAAA-MM es nuevo o cambió, se releen esa carpeta y todas las
    posteriores, para respetar el orden (lo más nuevo pisa a lo más viejo).
    """
    ruta_base = c.datos / "historico.parquet"
    ruta_firmas = c.datos / "archivos_procesados.json"
    hay_base = ruta_base.exists()
    base = pd.read_parquet(ruta_base) if hay_base else vacio()
    base = normalizar(base)
    firmas = json.loads(ruta_firmas.read_text(encoding="utf-8")) if (hay_base and ruta_firmas.exists()) else {}
    res = ResultadoCarga(base=base)
    if not c.entrada.is_dir():
        return res
    carpetas = sorted(p for p in c.entrada.iterdir() if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}", p.name))
    archivos = [(carpeta, ruta) for carpeta in carpetas for ruta in sorted(carpeta.iterdir())
                if ruta.is_file() and not ruta.name.startswith((".", "~$"))]
    desde = next((carpeta.name for carpeta, ruta in archivos
                  if firmas.get(f"{carpeta.name}/{ruta.name}", {}).get("firma") != _firma(c, ruta)), None)
    for carpeta, ruta in archivos:
        clave = f"{carpeta.name}/{ruta.name}"
        if desde is None or carpeta.name < desde:
            previo = firmas.get(clave, {})
            if previo.get("extracto"):
                res.extractos.append(previo["extracto"])
            continue
        try:
            fuente, df, info = _leer_archivo(c, ruta, carpeta.name)
        except ErrorUsuario as e:
            res.errores.append({"archivo": clave, "detalle": str(e)})
            firmas.pop(clave, None)
            continue
        except Exception as e:  # archivo dañado o formato inesperado: no frena el cierre
            res.errores.append({"archivo": clave, "detalle": f"No se pudo leer ({type(e).__name__}: {e})."})
            firmas.pop(clave, None)
            continue
        if fuente is None:
            res.ignorados.append({"archivo": clave, "detalle": info})
            continue
        extracto = None
        if fuente == "banco" and info:
            extracto = {"carpeta": carpeta.name, "archivo": ruta.name, "cuenta": info["cuenta"],
                        "correcciones": info["correcciones"], "cierra": info["cierra"]}
            res.extractos.append(extracto)
        res.base = _upsert(res.base, df)
        meses = sorted(df["mes"].dropna().unique())
        res.archivos.append({"carpeta": carpeta.name, "archivo": ruta.name, "fuente": fuente,
                             "filas": len(df), "desde": meses[0] if meses else "",
                             "hasta": meses[-1] if meses else "",
                             "procesado": datetime.now().strftime("%d/%m/%Y %H:%M")})
        firmas[clave] = {"firma": _firma(c, ruta), "fuente": fuente, "extracto": extracto}
    res.leidos = len(res.archivos)
    res.sin_cambios = len([1 for carpeta, _ in archivos if desde is None or carpeta.name < desde])
    if res.archivos or not hay_base:
        res.base = normalizar(res.base).sort_values(["fuente", "fecha", "clave"]).reset_index(drop=True)
        c.datos.mkdir(parents=True, exist_ok=True)
        res.base.to_parquet(ruta_base, index=False)
        ruta_firmas.write_text(json.dumps(firmas, ensure_ascii=False, indent=1), encoding="utf-8")
        reg_f = c.datos / "registro_cargas.csv"
        reg = pd.DataFrame(res.archivos)
        if reg_f.exists():
            reg = pd.concat([pd.read_csv(reg_f, sep=";", dtype=str), reg.astype(str)], ignore_index=True)
        reg.to_csv(reg_f, index=False, sep=";", encoding="utf-8-sig")
    return res
