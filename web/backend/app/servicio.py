"""Ejecuta el cierre mensual con el motor existente (src/ + cierre.py) a partir de la base y el Storage.

Por cada cierre se arma una carpeta de trabajo temporal con la misma estructura que usa el motor:
  clientes/<slug>/config/*.yaml   <- clientes.config (JSON)
  clientes/<slug>/entrada/AAAA-MM <- archivos subidos (Storage)
  clientes/<slug>/datos/          <- caché del histórico (Storage), para no releer PDFs ya procesados
Después se suben las salidas (Excel, PDF, MD, alertas, Power BI) y se guarda el resumen en `cierres`.
Así el motor sigue siendo uno solo para la terminal y para la web.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path

from . import db
from .config import RAIZ
from .storage import storage

sys.path.insert(0, str(RAIZ))

import cierre as motor_cierre  # noqa: E402
from src.util import ErrorUsuario, escribir_yaml  # noqa: E402

_locks: dict[str, threading.Lock] = {}
TIPOS = {".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".pdf": "application/pdf",
         ".md": "text/markdown; charset=utf-8", ".csv": "text/csv; charset=utf-8",
         ".parquet": "application/octet-stream", ".json": "application/json"}


def prefijo(cliente: dict) -> str:
    return f"{cliente['estudio_id']}/{cliente['id']}"


def _preparar(base: Path, cliente: dict, st) -> Path:
    carpeta = base / "clientes" / cliente["slug"]
    for clave, datos in cliente["config"].items():
        escribir_yaml(carpeta / "config" / f"{clave}.yaml", datos)
    for a in db.varios("select mes, nombre, storage_path, subido_en from archivos where cliente_id = %s "
                       "and estado <> 'ignorado' order by subido_en", (cliente["id"],)):
        destino = carpeta / "entrada" / a["mes"] / a["nombre"]
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(st.bajar(a["storage_path"]))
        t = a["subido_en"].timestamp()
        os.utime(destino, (t, t))   # fecha estable: el caché del histórico no relee lo que no cambió
    (carpeta / "datos").mkdir(parents=True, exist_ok=True)
    for ruta in st.listar(f"{prefijo(cliente)}/datos"):
        (carpeta / "datos" / Path(ruta).name).write_bytes(st.bajar(ruta))
    return carpeta


def _resumen(r: dict) -> dict:
    ctx = r["ctx"]

    def limpio(v):
        return None if v is None or v != v else float(v)
    return {
        "ventas": limpio(ctx.v("ventas_tot")), "resultado": limpio(ctx.v("resultado")),
        "caja": limpio(ctx.v("caja")), "rojos": r["rojos"], "amarillos": r["amarillos"],
        "sin_dato": r["sin_dato"], "alertas_altas": r["alertas_altas"],
        "alertas_medias": int((r["alertas"]["gravedad"] == "Media").sum()),
        "mes_incompleto": bool(ctx.mes_incompleto),
        "estimados": [e["concepto"] for e in ctx.estimados if e["mes"] == ctx.mes],
        "estrellas": [{"nombre": e["nombre"], "valor": limpio(e["valor"]), "unidad": e["unidad"],
                       "semaforo": e["semaforo"]} for e in r["estrellas"]],
        "alertas": [{k: (None if (isinstance(v, float) and v != v) else v) for k, v in a.items()}
                    for a in r["alertas"].head(50).to_dict("records")],
    }


def _actualizar_archivos(cliente: dict, carga) -> None:
    for a in carga.archivos:
        db.ejecutar("update archivos set estado='procesado', tipo_detectado=%s, detalle=%s "
                    "where cliente_id=%s and mes=%s and nombre=%s",
                    (a["fuente"], f"{a['filas']} filas · {a['desde']} a {a['hasta']}", cliente["id"],
                     a["carpeta"], a["archivo"]))
    for e in carga.errores:
        mes, nombre = e["archivo"].split("/", 1)
        db.ejecutar("update archivos set estado='con_error', detalle=%s where cliente_id=%s and mes=%s and nombre=%s",
                    (e["detalle"], cliente["id"], mes, nombre))
    for e in carga.ignorados:
        mes, nombre = e["archivo"].split("/", 1)
        db.ejecutar("update archivos set estado='ignorado', detalle=%s where cliente_id=%s and mes=%s and nombre=%s",
                    (e["detalle"], cliente["id"], mes, nombre))


def ejecutar_cierre(cierre_id: str) -> None:
    c = db.uno("select * from cierres where id = %s", (cierre_id,))
    cliente = db.uno("select id::text, estudio_id::text, slug, config from clientes where id = %s", (c["cliente_id"],))
    lock = _locks.setdefault(cliente["id"], threading.Lock())
    with lock:   # dos cierres del mismo cliente no corren a la vez (comparten el caché)
        db.ejecutar("update cierres set estado='procesando' where id=%s", (cierre_id,))
        st = storage()
        try:
            with tempfile.TemporaryDirectory(prefix="cierre-") as tmp:
                base = Path(tmp)
                carpeta = _preparar(base, cliente, st)
                r = motor_cierre.cerrar_cliente(base, cliente["slug"], c["mes"], silencioso=True)
                _actualizar_archivos(cliente, r["carga"])
                salidas, pre = {}, f"{prefijo(cliente)}/salida/{c['mes']}"
                for f in r["salida"].iterdir():
                    st.subir(f"{pre}/{f.name}", f.read_bytes(), TIPOS.get(f.suffix, "application/octet-stream"))
                    clave = {".xlsx": "excel", ".pdf": "pdf", ".md": "md", ".csv": "alertas"}.get(f.suffix)
                    if clave:
                        salidas[clave] = f"{pre}/{f.name}"
                for f in (carpeta / "datos").iterdir():
                    st.subir(f"{prefijo(cliente)}/datos/{f.name}", f.read_bytes())
                for f in (carpeta / "powerbi").glob("*"):
                    st.subir(f"{prefijo(cliente)}/powerbi/{f.name}", f.read_bytes(), TIPOS.get(f.suffix, ""))
                db.ejecutar("update cierres set estado='listo', resumen=%s, salidas=%s, terminado_en=%s where id=%s",
                            (db.Jsonb(_resumen(r)), db.Jsonb(salidas), datetime.now(timezone.utc), cierre_id))
        except ErrorUsuario as e:
            db.ejecutar("update cierres set estado='error', error=%s, terminado_en=now() where id=%s",
                        (str(e), cierre_id))
        except Exception as e:  # se guarda la traza para soporte, el usuario ve un mensaje simple
            db.ejecutar("update cierres set estado='error', error=%s, log=%s, terminado_en=now() where id=%s",
                        (f"Error inesperado ({type(e).__name__}). El estudio ya tiene el detalle.",
                         traceback.format_exc(), cierre_id))
