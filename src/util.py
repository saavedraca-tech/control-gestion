"""Utilidades comunes: formato argentino, meses, normalización de texto, YAML."""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from pathlib import Path

import yaml

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


class ErrorUsuario(Exception):
    """Error que se le muestra tal cual a quien corre el cierre (en castellano, sin traza)."""


# ---------------------------------------------------------------- meses

def validar_mes(mes: str) -> str:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(mes)):
        raise ErrorUsuario(f"El mes '{mes}' no es válido. Usá el formato AAAA-MM, por ejemplo 2026-11.")
    return mes


def mes_sumar(mes: str, n: int) -> str:
    a, m = int(mes[:4]), int(mes[5:7])
    t = a * 12 + (m - 1) + n
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def mes_nombre(mes: str, corto: bool = False) -> str:
    a, m = int(mes[:4]), int(mes[5:7])
    if corto:
        return f"{MESES_CORTOS[m - 1]}-{str(a)[2:]}"
    return f"{MESES[m - 1]} {a}"


def mes_inicio(mes: str) -> date:
    return date(int(mes[:4]), int(mes[5:7]), 1)


def mes_fin(mes: str) -> date:
    sig = mes_inicio(mes_sumar(mes, 1))
    return date.fromordinal(sig.toordinal() - 1)


def dias_del_mes(mes: str) -> int:
    return mes_fin(mes).day


def rango_meses(desde: str, hasta: str) -> list[str]:
    out, m = [], desde
    while m <= hasta:
        out.append(m)
        m = mes_sumar(m, 1)
    return out


# ---------------------------------------------------------------- texto

def normalizar(texto) -> str:
    """Mayúsculas, sin acentos y con espacios simples: 'S D P  S.A.' -> 'S D P S.A.'"""
    if texto is None:
        return ""
    s = unicodedata.normalize("NFKD", str(texto))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().upper()


def solo_digitos(texto) -> str:
    return re.sub(r"\D", "", str(texto or ""))


def slug(texto: str) -> str:
    s = normalizar(texto).lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "cliente"


def numero_ar(texto) -> float:
    """'1.234.567,89' -> 1234567.89 ; '-43.290,00' -> -43290.0 ; '$44.311,90' -> 44311.9"""
    s = str(texto).replace("$", "").replace(" ", "").strip()
    if s in ("", "-"):
        return 0.0
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    return float(s)


# ---------------------------------------------------------------- formato argentino

def es_nulo(v) -> bool:
    try:
        return v is None or v != v  # NaN != NaN
    except Exception:
        return False


def _miles(n: float, dec: int) -> str:
    s = f"{abs(n):,.{dec}f}"
    s = s.replace(",", "§").replace(".", ",").replace("§", ".")
    return ("-" if n < 0 else "") + s


def fmt_pesos(v, dec: int = 0) -> str:
    if es_nulo(v):
        return "sin dato"
    return ("-$ " if v < 0 else "$ ") + _miles(abs(v), dec)


def fmt_pct(v, dec: int = 1) -> str:
    return "sin dato" if es_nulo(v) else _miles(v * 100, dec) + " %"


def fmt_num(v, dec: int = 0) -> str:
    return "sin dato" if es_nulo(v) else _miles(v, dec)


def fmt_valor(v, unidad: str) -> str:
    if es_nulo(v):
        return "sin dato"
    if unidad == "pesos":
        return fmt_pesos(v)
    if unidad == "pct":
        return fmt_pct(v)
    if unidad == "dias":
        return fmt_num(v, 1) + " días"
    if unidad == "horas":
        return fmt_num(v, 1) + " h"
    if unidad in ("decimal",):
        return fmt_num(v, 2)
    return fmt_num(v, 0)


def fmt_fecha(d) -> str:
    return "" if d is None else d.strftime("%d/%m/%Y")


# Formatos de número de Excel (Excel los muestra con punto de miles y coma decimal
# cuando la configuración regional de Windows es Español (Argentina)).
FORMATO_EXCEL = {
    "pesos": '"$" #,##0;[Red]-"$" #,##0',
    "pct": "0.0%",
    "dias": '0.0 "días"',
    "horas": '0.0 "h"',
    "decimal": "#,##0.00",
    "numero": "#,##0",
    "unidades": "#,##0",
}
FORMATO_FECHA_EXCEL = "dd/mm/yyyy"


# ---------------------------------------------------------------- yaml

def leer_yaml(ruta: Path) -> dict:
    try:
        with open(ruta, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise ErrorUsuario(f"No encuentro el archivo de configuración {ruta}.")
    except yaml.YAMLError as e:
        linea = getattr(getattr(e, "problem_mark", None), "line", None)
        donde = f" (cerca de la línea {linea + 1})" if linea is not None else ""
        raise ErrorUsuario(f"El archivo {ruta.name} tiene un error de formato{donde}. "
                           "Revisá sangrías y que los textos con ':' estén entre comillas.")


def escribir_yaml(ruta: Path, datos: dict, encabezado: str = "") -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    texto = yaml.safe_dump(datos, allow_unicode=True, sort_keys=False, width=110)
    with open(ruta, "w", encoding="utf-8") as f:
        if encabezado:
            f.write("".join(f"# {l}\n" if l else "#\n" for l in encabezado.splitlines()))
            f.write("\n")
        f.write(texto)
