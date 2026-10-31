"""API web del control de gestión (fase 1: cierre mensual desde el navegador)."""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import PurePath

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import db, servicio
from .auth import Usuario, usuario_actual
from .config import RAIZ, ajustes
from .storage import storage

sys.path.insert(0, str(RAIZ))
import nuevo_cliente  # noqa: E402
from src import plantillas  # noqa: E402
from src.config import validar as validar_config  # noqa: E402
from src.util import ErrorUsuario, slug as hacer_slug, solo_digitos  # noqa: E402

app = FastAPI(title="Control de gestión · ARFinance", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=ajustes.cors_origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

MES = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
EXTENSIONES = {".csv", ".pdf", ".xlsx", ".xls", ".txt"}


# ---------------------------------------------------------------- helpers de acceso

def _cliente(cliente_id: str, u: Usuario) -> dict:
    c = db.uno("select id::text, estudio_id::text, slug, razon_social, cuit, rubro, activo, config, creado_en "
               "from clientes where id::text = %s and estudio_id = %s", (cliente_id, u.estudio_id))
    if not c:
        raise HTTPException(404, "Cliente inexistente.")
    if not u.es_consultor and not db.uno("select 1 from usuarios_clientes where usuario_id=%s and cliente_id=%s",
                                         (u.id, cliente_id)):
        raise HTTPException(404, "Cliente inexistente.")
    return c


def _solo_consultor(u: Usuario):
    if not u.es_consultor:
        raise HTTPException(403, "Sólo el estudio puede hacer esto.")


# ---------------------------------------------------------------- general

@app.on_event("startup")
def cierres_interrumpidos():
    """Los cierres corren dentro del proceso: si el servidor se reinició, los que estaban a medias se marcan."""
    if ajustes.database_url:
        db.ejecutar("update cierres set estado='error', error='Se interrumpió (reinicio del servidor). "
                    "Volvé a pedir el cierre.', terminado_en=now() where estado in ('en_cola','procesando')")


@app.get("/api/salud")
def salud():
    return {"ok": True}


@app.get("/api/yo")
def yo(u: Usuario = Depends(usuario_actual)):
    est = db.uno("select nombre from estudios where id = %s", (u.estudio_id,))
    return {"id": u.id, "email": u.email, "rol": u.rol, "estudio": est["nombre"] if est else ""}


@app.get("/api/plantillas")
def listar_plantillas(u: Usuario = Depends(usuario_actual)):
    out = []
    for r in plantillas.disponibles(RAIZ):
        p = plantillas.cargar(RAIZ, r)
        out.append({"id": r, "nombre": p.get("nombre", r), "descripcion": p.get("descripcion", ""),
                    "unidad": (p.get("unidad_sugerida") or {}).get("nombre", "unidad"),
                    "actividades_iibb": (p.get("iibb") or {}).get("actividades", [])})
    return out


# ---------------------------------------------------------------- clientes

class ClienteNuevo(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    rubro: str
    cuit: str
    actividad: str = ""
    jurisdiccion: str = "Mendoza"
    unidad: str | None = None
    plural: str | None = None
    temporada_alta: list[int] = []
    socios: list[str] = []
    n_registrados: int = Field(0, ge=0, le=500)
    no_registrados: list[str] = []
    alicuotas: dict[str, float] = {}     # en tanto por uno: 0.035


@app.get("/api/clientes")
def listar_clientes(u: Usuario = Depends(usuario_actual)):
    filtro = "" if u.es_consultor else "and c.id in (select cliente_id from usuarios_clientes where usuario_id = %(u)s)"
    return db.varios(f"""
        select c.id::text, c.slug, c.razon_social, c.cuit, c.rubro, c.activo,
               ult.mes as ultimo_mes, ult.estado as ultimo_estado, ult.resumen as ultimo_resumen,
               (select count(*) from archivos a where a.cliente_id = c.id) as archivos
        from clientes c
        left join lateral (select mes, estado, resumen from cierres x where x.cliente_id = c.id
                           order by mes desc, creado_en desc limit 1) ult on true
        where c.estudio_id = %(e)s {filtro}
        order by c.activo desc, c.razon_social""", {"e": u.estudio_id, "u": u.id})


@app.post("/api/clientes", status_code=201)
def crear_cliente(d: ClienteNuevo, u: Usuario = Depends(usuario_actual)):
    _solo_consultor(u)
    if not nuevo_cliente.cuit_valido(d.cuit):
        raise HTTPException(422, "El CUIT no es válido (revisá los 11 dígitos).")
    if d.rubro not in plantillas.disponibles(RAIZ):
        raise HTTPException(422, f"Rubro inexistente. Opciones: {', '.join(plantillas.disponibles(RAIZ))}.")
    if any(m < 1 or m > 12 for m in d.temporada_alta):
        raise HTTPException(422, "Los meses de temporada alta van del 1 al 12.")
    p = plantillas.cargar(RAIZ, d.rubro)
    config = nuevo_cliente.armar_config(p, d.rubro, d.nombre, razon=d.nombre, cuit=d.cuit, actividad=d.actividad,
                                        jurisdiccion=d.jurisdiccion, unidad=d.unidad, plural=d.plural,
                                        temporada_alta=d.temporada_alta, socios=d.socios,
                                        n_registrados=d.n_registrados, no_registrados=d.no_registrados,
                                        alicuotas=d.alicuotas)
    cuit = solo_digitos(d.cuit)
    if db.uno("select 1 from clientes where estudio_id=%s and cuit=%s", (u.estudio_id, cuit)):
        raise HTTPException(409, "Ya hay un cliente con ese CUIT.")
    s = base = hacer_slug(d.nombre)
    n = 2
    while db.uno("select 1 from clientes where estudio_id=%s and slug=%s", (u.estudio_id, s)):
        s, n = f"{base}_{n}", n + 1
    c = db.uno("insert into clientes (estudio_id, slug, razon_social, cuit, rubro, config) values (%s,%s,%s,%s,%s,%s) "
               "returning id::text", (u.estudio_id, s, d.nombre, cuit, d.rubro, db.Jsonb(config)))
    db.auditar(u.estudio_id, u.id, "crear", "cliente", c["id"], {"nombre": d.nombre, "rubro": d.rubro})
    return {"id": c["id"], "slug": s}


@app.get("/api/clientes/{cliente_id}")
def ver_cliente(cliente_id: str, u: Usuario = Depends(usuario_actual)):
    return _cliente(cliente_id, u)


class ConfigCliente(BaseModel):
    config: dict


@app.put("/api/clientes/{cliente_id}/config")
def guardar_config(cliente_id: str, d: ConfigCliente, u: Usuario = Depends(usuario_actual)):
    """Reemplaza la configuración (las 5 secciones). Se valida con el mismo validador que la terminal."""
    _solo_consultor(u)
    c = _cliente(cliente_id, u)
    faltan = {"empresa", "rubros", "kpis", "impuestos", "personal"} - set(d.config)
    if faltan:
        raise HTTPException(422, f"Faltan secciones: {', '.join(sorted(faltan))}.")
    from src.config import Cliente
    try:
        validar_config(Cliente(id=c["slug"], carpeta=RAIZ, **{k: d.config[k] for k in
                                                               ["empresa", "rubros", "kpis", "impuestos", "personal"]}))
    except ErrorUsuario as e:
        raise HTTPException(422, str(e))
    db.ejecutar("update clientes set config=%s, activo=%s where id=%s",
                (db.Jsonb(d.config), bool(d.config["empresa"].get("activo", True)), cliente_id))
    db.auditar(u.estudio_id, u.id, "editar_config", "cliente", cliente_id)
    return {"ok": True}


# ---------------------------------------------------------------- archivos

@app.get("/api/clientes/{cliente_id}/archivos")
def listar_archivos(cliente_id: str, u: Usuario = Depends(usuario_actual)):
    _cliente(cliente_id, u)
    return db.varios("select id::text, mes, nombre, tamano_bytes, tipo_detectado, estado, detalle, subido_en "
                     "from archivos where cliente_id = %s order by mes desc, nombre", (cliente_id,))


@app.post("/api/clientes/{cliente_id}/archivos", status_code=201)
async def subir_archivos(cliente_id: str, mes: str = Form(...), archivos: list[UploadFile] = File(...),
                         u: Usuario = Depends(usuario_actual)):
    _solo_consultor(u)
    c = _cliente(cliente_id, u)
    if not MES.match(mes):
        raise HTTPException(422, "El mes tiene que ser AAAA-MM, por ejemplo 2026-11.")
    st, resultado = storage(), []
    for f in archivos:
        nombre = PurePath(f.filename or "archivo").name.replace("/", "_")
        ext = PurePath(nombre).suffix.lower()
        contenido = await f.read()
        if ext not in EXTENSIONES:
            resultado.append({"nombre": nombre, "estado": "rechazado", "detalle": "Tipo de archivo no admitido."})
            continue
        if len(contenido) > ajustes.max_mb * 1024 * 1024:
            resultado.append({"nombre": nombre, "estado": "rechazado", "detalle": f"Supera {ajustes.max_mb} MB."})
            continue
        sha = hashlib.sha256(contenido).hexdigest()
        previo = db.uno("select mes, nombre from archivos where cliente_id=%s and sha256=%s", (cliente_id, sha))
        if previo:
            resultado.append({"nombre": nombre, "estado": "duplicado",
                              "detalle": f"Ya estaba subido en {previo['mes']} como {previo['nombre']}."})
            continue
        # Un archivo con el mismo nombre en el mismo mes se reemplaza (p. ej. un CSV de ARCA corregido).
        viejo = db.uno("select id::text, storage_path from archivos where cliente_id=%s and mes=%s and nombre=%s",
                       (cliente_id, mes, nombre))
        ruta = f"{servicio.prefijo(c)}/entrada/{mes}/{nombre}"
        st.subir(ruta, contenido, f.content_type or "application/octet-stream")
        if viejo:
            db.ejecutar("delete from archivos where id=%s", (viejo["id"],))
        db.ejecutar("insert into archivos (cliente_id, mes, nombre, storage_path, sha256, tamano_bytes, subido_por) "
                    "values (%s,%s,%s,%s,%s,%s,%s)", (cliente_id, mes, nombre, ruta, sha, len(contenido), u.id))
        resultado.append({"nombre": nombre, "estado": "reemplazado" if viejo else "subido", "detalle": ""})
    db.auditar(u.estudio_id, u.id, "subir_archivos", "cliente", cliente_id, {"mes": mes, "resultado": resultado})
    return resultado


@app.delete("/api/clientes/{cliente_id}/archivos/{archivo_id}")
def borrar_archivo(cliente_id: str, archivo_id: str, u: Usuario = Depends(usuario_actual)):
    """Saca el archivo de los próximos cierres. Lo ya volcado al histórico queda (igual que en la terminal)."""
    _solo_consultor(u)
    _cliente(cliente_id, u)
    a = db.uno("select storage_path from archivos where id::text=%s and cliente_id=%s", (archivo_id, cliente_id))
    if not a:
        raise HTTPException(404, "Archivo inexistente.")
    storage().borrar(a["storage_path"])
    db.ejecutar("delete from archivos where id::text=%s", (archivo_id,))
    db.auditar(u.estudio_id, u.id, "borrar_archivo", "archivo", archivo_id)
    return {"ok": True}


# ---------------------------------------------------------------- cierres

class PedidoCierre(BaseModel):
    mes: str


@app.post("/api/clientes/{cliente_id}/cierres", status_code=202)
def pedir_cierre(cliente_id: str, d: PedidoCierre, tareas: BackgroundTasks, u: Usuario = Depends(usuario_actual)):
    _solo_consultor(u)
    _cliente(cliente_id, u)
    if not MES.match(d.mes):
        raise HTTPException(422, "El mes tiene que ser AAAA-MM.")
    if not db.uno("select 1 from archivos where cliente_id=%s", (cliente_id,)):
        raise HTTPException(422, "Todavía no hay archivos cargados para este cliente.")
    en_curso = db.uno("select id::text from cierres where cliente_id=%s and estado in ('en_cola','procesando')",
                      (cliente_id,))
    if en_curso:
        return {"id": en_curso["id"], "estado": "ya_en_curso"}
    c = db.uno("insert into cierres (cliente_id, mes, pedido_por) values (%s,%s,%s) returning id::text",
               (cliente_id, d.mes, u.id))
    tareas.add_task(servicio.ejecutar_cierre, c["id"])
    return {"id": c["id"], "estado": "en_cola"}


@app.get("/api/clientes/{cliente_id}/cierres")
def listar_cierres(cliente_id: str, u: Usuario = Depends(usuario_actual)):
    _cliente(cliente_id, u)
    return db.varios("select id::text, mes, estado, resumen, error, creado_en, terminado_en from cierres "
                     "where cliente_id=%s order by mes desc, creado_en desc limit 50", (cliente_id,))


@app.get("/api/cierres/{cierre_id}")
def ver_cierre(cierre_id: str, u: Usuario = Depends(usuario_actual)):
    c = db.uno("select id::text, cliente_id::text, mes, estado, resumen, salidas, error, creado_en, terminado_en "
               "from cierres where id::text=%s", (cierre_id,))
    if not c:
        raise HTTPException(404, "Cierre inexistente.")
    _cliente(c["cliente_id"], u)
    return c


@app.get("/api/cierres/{cierre_id}/descargas/{tipo}")
def descargar(cierre_id: str, tipo: str, u: Usuario = Depends(usuario_actual)):
    c = ver_cierre(cierre_id, u)
    ruta = (c.get("salidas") or {}).get(tipo)
    if not ruta:
        raise HTTPException(404, "Ese archivo no existe para este cierre.")
    contenido = storage().bajar(ruta)
    nombre = PurePath(ruta).name
    return Response(contenido, media_type=servicio.TIPOS.get(PurePath(ruta).suffix, "application/octet-stream"),
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})
