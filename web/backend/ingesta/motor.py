"""Motor de ingesta para la versión web: perfiles (M_Perfiles) -> filas normalizadas -> reglas (M_Reglas)
-> marcas de duplicado/sin regla -> filas de staging (IMP_Listo) que el usuario aprueba.

Reutiliza los lectores ya probados de src/lectores (ARCA, F.931, Galicia) y suma perfiles tabulares
genéricos (importe con signo, débito/crédito separados, columna D/C, billeteras con bruto/comisión).
Sin dependencias web: FastAPI sólo llama a `procesar_archivo(...)`.
"""
from __future__ import annotations

import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import pandas as pd

# ------------------------------------------------------------------ utilidades


def norm(t) -> str:
    s = unicodedata.normalize("NFKD", str(t or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().upper()


def num_ar(v) -> float | None:
    """'1.234,56' | '-1234.56' | '1.234,56-' | '(1.234,56)' | 1234.5 -> float."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("$", "").replace(" ", "").replace(" ", "")
    if not s:
        return None
    neg = s.endswith("-") or (s.startswith("(") and s.endswith(")"))
    s = s.strip("()-") if neg else s
    if "," in s and (s.rfind(",") > s.rfind(".")):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if neg else x


def huella(cuenta: str, fecha: date, importe: float, texto: str, ocurrencia: int = 0) -> str:
    """Identidad de un movimiento. `ocurrencia` distingue movimientos idénticos el mismo día
    (dos transferencias iguales) sin confundirlos con una recarga del mismo archivo."""
    base = f"{cuenta}|{fecha.isoformat()}|{importe:.2f}|{norm(texto)[:60]}|{ocurrencia}"
    return hashlib.sha256(base.encode()).hexdigest()


# ------------------------------------------------------------------ perfiles (M_Perfiles)

@dataclass
class Perfil:
    codigo: str
    formato: str                    # csv | xlsx | pdf
    encabezados: list = field(default_factory=list)   # columnas que identifican el archivo
    texto_contiene: list = field(default_factory=list)
    mapeo: dict = field(default_factory=dict)
    # mapeo: fecha, descripcion, contraparte, cuit, saldo, formato_fecha,
    #        modo_importe: 'signo' | 'debe_haber' | 'dc'  (+ importe | debito/credito | importe/col_dc/valor_debito)
    #        bruto/comision/impuestos (billeteras y procesadores)


PERFILES: list[Perfil] = [
    Perfil("mercadopago_csv", "csv",
           encabezados=["RELEASE_DATE", "TRANSACTION_TYPE", "TRANSACTION_NET_AMOUNT"],
           mapeo={"fecha": "RELEASE_DATE", "descripcion": "TRANSACTION_TYPE", "contraparte": "REFERENCE_ID",
                  "modo_importe": "signo", "importe": "TRANSACTION_NET_AMOUNT",
                  "saldo": "PARTIAL_BALANCE", "bruto": "TRANSACTION_AMOUNT", "comision": "FEE_AMOUNT",
                  "impuestos": "TAXES_AMOUNT"}),
    Perfil("banco_debe_haber", "csv", encabezados=["FECHA", "CONCEPTO", "DEBITO", "CREDITO"],
           mapeo={"fecha": "FECHA", "descripcion": "CONCEPTO", "modo_importe": "debe_haber",
                  "debito": "DEBITO", "credito": "CREDITO", "saldo": "SALDO", "formato_fecha": "%d/%m/%Y"}),
    Perfil("banco_dc", "csv", encabezados=["FECHA", "DESCRIPCION", "IMPORTE", "D/C"],
           mapeo={"fecha": "FECHA", "descripcion": "DESCRIPCION", "modo_importe": "dc", "importe": "IMPORTE",
                  "col_dc": "D/C", "valor_debito": "D", "formato_fecha": "%d/%m/%Y"}),
    Perfil("generico_signo", "csv", encabezados=["FECHA", "DESCRIPCION", "IMPORTE"],
           mapeo={"fecha": "FECHA", "descripcion": "DESCRIPCION", "modo_importe": "signo", "importe": "IMPORTE",
                  "saldo": "SALDO", "formato_fecha": "%d/%m/%Y"}),
    Perfil("galicia_pdf", "pdf", texto_contiene=["Resumen de Cuenta"]),
    Perfil("f931_pdf", "pdf", texto_contiene=["931", "Suma de Rem. 1"]),
]


def _leer_tabla(contenido: bytes, nombre: str) -> pd.DataFrame:
    if nombre.lower().endswith((".xlsx", ".xls")):
        crudo = pd.read_excel(io.BytesIO(contenido), header=None, dtype=str)
    else:
        import csv
        texto = contenido.decode("utf-8-sig", errors="replace")
        sep = ";" if texto.count(";") >= texto.count(",") else ","
        filas = list(csv.reader(io.StringIO(texto), delimiter=sep))
        ancho = max(len(f) for f in filas)   # las filas de título vienen más cortas que la tabla
        crudo = pd.DataFrame([f + [""] * (ancho - len(f)) for f in filas], dtype=str)
    # Los extractos traen filas de título antes del encabezado: se busca la primera fila "con forma de encabezado".
    for i in range(min(len(crudo), 30)):
        fila = [norm(x) for x in crudo.iloc[i].tolist()]
        if sum(1 for x in fila if x and not re.search(r"\d{2}/\d{2}", x)) >= 3:
            df = crudo.iloc[i + 1:].copy()
            df.columns = [norm(x) for x in crudo.iloc[i].tolist()]
            return df.reset_index(drop=True)
    raise ValueError("No encontré la fila de encabezados")


def detectar_perfil(contenido: bytes, nombre: str, texto_pdf: str | None = None) -> tuple[Perfil | None, pd.DataFrame | None]:
    if nombre.lower().endswith(".pdf"):
        for p in PERFILES:
            if p.formato == "pdf" and texto_pdf and all(t in texto_pdf for t in p.texto_contiene):
                return p, None
        return None, None
    df = _leer_tabla(contenido, nombre)
    cols = set(df.columns)
    # El perfil más específico (más encabezados coincidentes) gana.
    candidatos = [p for p in PERFILES if p.formato != "pdf" and all(norm(h) in cols for h in p.encabezados)]
    candidatos.sort(key=lambda p: -len(p.encabezados))
    return (candidatos[0] if candidatos else None), df


def _fecha(v, fmt: str | None) -> date | None:
    if v is None or str(v).strip() == "":
        return None
    try:
        return datetime.strptime(str(v).strip()[:len(datetime.now().strftime(fmt))], fmt).date() if fmt \
            else pd.to_datetime(v, dayfirst=True).date()
    except (ValueError, TypeError):
        try:
            return pd.to_datetime(v, dayfirst=True).date()
        except (ValueError, TypeError):
            return None


def normalizar_tabla(df: pd.DataFrame, p: Perfil) -> pd.DataFrame:
    m = {k: norm(v) if isinstance(v, str) and k not in ("modo_importe", "formato_fecha", "valor_debito") else v
         for k, v in p.mapeo.items()}
    out = []
    for _, r in df.iterrows():
        f = _fecha(r.get(m["fecha"]), m.get("formato_fecha"))
        if f is None:
            continue  # subtotales, pies de página
        if m["modo_importe"] == "signo":
            imp = num_ar(r.get(m["importe"]))
        elif m["modo_importe"] == "debe_haber":
            imp = (num_ar(r.get(m["credito"])) or 0) - abs(num_ar(r.get(m["debito"])) or 0)
        else:  # dc
            x = abs(num_ar(r.get(m["importe"])) or 0)
            imp = -x if norm(r.get(m["col_dc"])) == m["valor_debito"] else x
        if imp is None or imp == 0:
            continue
        out.append({"fecha": f, "descripcion": str(r.get(m["descripcion"], "")).strip(),
                    "contraparte": str(r.get(m.get("contraparte", ""), "") or "").strip(),
                    "importe": round(imp, 2), "saldo": num_ar(r.get(m.get("saldo", ""))),
                    "bruto": num_ar(r.get(m.get("bruto", ""))), "comision": num_ar(r.get(m.get("comision", ""))),
                    "impuestos": num_ar(r.get(m.get("impuestos", "")))})
    return pd.DataFrame(out)


# ------------------------------------------------------------------ reglas (M_Reglas)

@dataclass
class Regla:
    id: str
    prioridad: int
    patron: str
    rubro: str
    operador: str = "contiene"      # contiene | igual | regex | empieza
    campo: str = "texto"            # texto | cuit | contraparte
    signo: str | None = None        # ingreso | egreso | None
    tipo_movimiento: str | None = None
    es_sospechosa: bool = False
    cliente_id: str | None = None   # None = global

    def coincide(self, mov: dict) -> bool:
        if self.signo == "ingreso" and mov["importe"] < 0 or self.signo == "egreso" and mov["importe"] > 0:
            return False
        valor = {"texto": f"{mov.get('descripcion', '')} {mov.get('contraparte', '')}",
                 "cuit": mov.get("cuit") or "", "contraparte": mov.get("contraparte") or ""}[self.campo]
        v, p = norm(valor), norm(self.patron)
        return {"contiene": p in v, "igual": v == p, "empieza": v.startswith(p),
                "regex": bool(re.search(self.patron, v, re.I))}[self.operador]


# Extracto de las reglas argentinas globales (la base completa tiene 200+; se cargan desde la tabla).
REGLAS_GLOBALES = [
    Regla("g001", 10, "LEY 25413", "Impuestos y tasas", tipo_movimiento="impuesto_cheque"),
    Regla("g002", 11, "IMP. DEB.", "Impuestos y tasas", tipo_movimiento="impuesto_cheque"),
    Regla("g003", 12, "IMP. CRE.", "Impuestos y tasas", tipo_movimiento="impuesto_cheque"),
    Regla("g004", 20, "SIRCREB", "Impuestos y tasas", tipo_movimiento="retencion_iibb"),
    Regla("g005", 30, "VEP", "Impuestos y tasas", signo="egreso", tipo_movimiento="vep"),
    Regla("g006", 31, "F931|F\\.931|SUSS", "Cargas sociales", operador="regex", signo="egreso", tipo_movimiento="f931"),
    Regla("g007", 32, "TRANSF. AFIP", "Impuestos y tasas", signo="egreso", tipo_movimiento="vep"),
    Regla("g008", 40, "ACREDITAMIENTO DE HABERES|PAGO DE HABERES", "Sueldos", operador="regex", tipo_movimiento="haberes"),
    Regla("g009", 50, "SUSCRIPCION FIMA|RESCATE FIMA|FCI", "Movimiento interno", operador="regex", tipo_movimiento="inversion"),
    Regla("g010", 60, "ECHEQ", "A conciliar", tipo_movimiento="echeq"),
    Regla("g011", 61, "DEBIN", "A conciliar", tipo_movimiento="debin"),
    Regla("g012", 70, "COMISION", "Bancos", signo="egreso", tipo_movimiento="comision"),
    Regla("g013", 71, "INTERESES SOBRE SALDOS", "Bancos", signo="egreso", tipo_movimiento="interes"),
    Regla("g014", 80, "EDEMSA|EDENOR|EDESUR|ELECTRICIDAD", "Energía", operador="regex", signo="egreso"),
    Regla("g015", 90, "DEP.EFVO|DEPOSITO EN EFECTIVO", "Ventas a identificar", operador="regex", signo="ingreso",
          tipo_movimiento="deposito_efectivo"),
    Regla("g900", 900, "SALUD|AMBULATORIO|HOGAR|INDUMENTARIA|TURISMO", "A REVISAR", operador="regex",
          es_sospechosa=True),
]


def clasificar(mov: dict, reglas: list[Regla]) -> tuple[Regla | None, list[str]]:
    """Reglas del cliente primero, después las del estudio y por último las globales; dentro de cada
    nivel, por prioridad. Gana la primera que coincide."""
    orden = sorted(reglas, key=lambda r: (0 if r.cliente_id else 1, r.prioridad))
    for r in orden:
        if r.coincide(mov):
            return r, (["sospechosa"] if r.es_sospechosa else [])
    return None, ["sin_regla"]


# ------------------------------------------------------------------ orquestación

@dataclass
class ResultadoIngesta:
    perfil: str | None
    filas: list = field(default_factory=list)       # para filas_staging
    estado: str = "para_revisar"
    detalle: str = ""


def procesar_archivo(contenido: bytes, nombre: str, cuenta: str, reglas: list[Regla],
                     huellas_existentes: set[str], texto_pdf: str | None = None,
                     comprobantes: pd.DataFrame | None = None, tolerancia_dias: int = 3) -> ResultadoIngesta:
    perfil, df = detectar_perfil(contenido, nombre, texto_pdf)
    if perfil is None:
        return ResultadoIngesta(None, estado="error", detalle="Formato no reconocido: elegí un perfil a mano.")
    if perfil.codigo == "f931_pdf":
        return ResultadoIngesta(perfil.codigo, estado="para_revisar", detalle="F.931: usar src/lectores/f931.py")
    if perfil.codigo == "galicia_pdf":
        from src.lectores.bancos import FORMATOS          # lector ya probado con extractos reales
        movs, _ = FORMATOS["galicia"][1](texto_pdf, nombre)
        df = movs.rename(columns={"concepto": "descripcion", "nombre": "contraparte", "valor": "importe"})
        df["fecha"] = pd.to_datetime(df["fecha"]).dt.date
    else:
        df = normalizar_tabla(df, perfil)

    filas, vistos = [], {}
    for i, mov in enumerate(df.to_dict("records")):
        base = (mov["fecha"], round(mov["importe"], 2), norm(mov["descripcion"])[:60])
        vistos[base] = vistos.get(base, -1) + 1
        h = huella(cuenta, mov["fecha"], mov["importe"], mov["descripcion"], vistos[base])
        regla, marcas = clasificar(mov, reglas)
        if h in huellas_existentes:
            marcas.append("posible_duplicado")
        if comprobantes is not None and mov["importe"] < 0 and (regla is None or regla.tipo_movimiento is None):
            # Egreso sin factura de un importe parecido en ±N días -> "sin comprobante"
            c = comprobantes
            cerca = c[(abs(c["total"] - abs(mov["importe"])) <= 1)
                      & (abs((pd.to_datetime(c["fecha"]) - pd.Timestamp(mov["fecha"])).dt.days) <= tolerancia_dias)]
            if cerca.empty:
                marcas.append("sin_comprobante")
        filas.append({"nro_fila": i + 1, "destino": "tesoreria", "huella": h,
                      "datos": {**mov, "fecha": mov["fecha"].isoformat()},
                      "regla_id": regla.id if regla else None, "rubro_propuesto": regla.rubro if regla else None,
                      "tipo_movimiento": regla.tipo_movimiento if regla else None, "marcas": marcas,
                      "decision": "descartar" if "posible_duplicado" in marcas else "pendiente"})
    estado = "duplicado" if filas and all("posible_duplicado" in f["marcas"] for f in filas) else \
        "con_alerta" if any(f["marcas"] for f in filas) else "para_revisar"
    return ResultadoIngesta(perfil.codigo, filas, estado, f"{len(filas)} movimientos")


def regla_desde_correccion(cliente_id: str, texto: str, rubro: str, prioridad: int = 5) -> Regla:
    """Cuando el usuario asigna un rubro en IMP_Listo y tilda 'crear regla', se arma una regla del cliente
    con la parte estable del texto (sin números de operación, CBU ni fechas)."""
    limpio = re.sub(r"\b[\d\-/.:]{4,}\b", " ", norm(texto))
    patron = " ".join(limpio.split()[:4])
    return Regla(id=f"c-{hashlib.md5((cliente_id + patron).encode()).hexdigest()[:8]}", prioridad=prioridad,
                 patron=patron, rubro=rubro, cliente_id=cliente_id)
