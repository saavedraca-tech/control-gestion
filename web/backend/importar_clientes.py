"""Sube a la web (Supabase) los clientes que hoy están en carpetas: configuración YAML + archivos de entrada/.

Uso (con las variables de web/backend/.env cargadas):
    python web/backend/importar_clientes.py --email admin@estudio.com            # todos los clientes
    python web/backend/importar_clientes.py --email admin@estudio.com --cliente duclos
No duplica: un archivo ya subido (mismo contenido) se saltea y un cliente existente (mismo CUIT) se actualiza.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import db, servicio  # noqa: E402
from app.config import RAIZ  # noqa: E402
from app.storage import storage  # noqa: E402

sys.path.insert(0, str(RAIZ))
from src.config import cargar_cliente, listar_clientes  # noqa: E402


def importar(email: str, ids: list[str]) -> None:
    u = db.uno("select id::text, estudio_id::text from usuarios where lower(email)=lower(%s)", (email,))
    if not u:
        sys.exit(f"{email} todavía no entró a la web. Entrá una vez (crea el estudio) y volvé a correr esto.")
    st = storage()
    for cid in ids:
        c = cargar_cliente(RAIZ, cid)
        config = {k: getattr(c, k) for k in ["empresa", "rubros", "kpis", "impuestos", "personal"]}
        fila = db.uno("select id::text from clientes where estudio_id=%s and cuit=%s", (u["estudio_id"], c.cuit))
        if fila:
            db.ejecutar("update clientes set config=%s, razon_social=%s where id=%s",
                        (db.Jsonb(config), c.nombre, fila["id"]))
        else:
            fila = db.uno("insert into clientes (estudio_id, slug, razon_social, cuit, rubro, config) "
                          "values (%s,%s,%s,%s,%s,%s) returning id::text",
                          (u["estudio_id"], cid, c.nombre, c.cuit, c.empresa.get("rubro", "generico"), db.Jsonb(config)))
        cliente = {"id": fila["id"], "estudio_id": u["estudio_id"]}
        subidos = 0
        for carpeta in sorted(p for p in c.entrada.iterdir() if p.is_dir()):
            for f in sorted(x for x in carpeta.iterdir() if x.is_file() and not x.name.startswith(".")):
                datos = f.read_bytes()
                sha = hashlib.sha256(datos).hexdigest()
                if db.uno("select 1 from archivos where cliente_id=%s and sha256=%s", (fila["id"], sha)):
                    continue
                ruta = f"{servicio.prefijo(cliente)}/entrada/{carpeta.name}/{f.name}"
                st.subir(ruta, datos)
                db.ejecutar("insert into archivos (cliente_id, mes, nombre, storage_path, sha256, tamano_bytes, subido_por) "
                            "values (%s,%s,%s,%s,%s,%s,%s)", (fila["id"], carpeta.name, f.name, ruta, sha, len(datos), u["id"]))
                subidos += 1
        print(f"✔ {c.nombre}: configuración cargada, {subidos} archivo(s) subido(s).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True, help="email del administrador que ya entró a la web")
    ap.add_argument("--cliente", action="append", help="carpeta del cliente (se puede repetir); por defecto todos")
    a = ap.parse_args()
    importar(a.email, a.cliente or listar_clientes(RAIZ))
