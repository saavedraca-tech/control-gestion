"""Fase 1: el cierre de Duclos hecho por la API da los mismos números que la terminal."""
import uuid
from pathlib import Path
from io import BytesIO

import pytest
import yaml
from openpyxl import load_workbook

RAIZ = Path(__file__).resolve().parents[3]

DUCLOS = RAIZ / "clientes" / "duclos"


def config_duclos() -> dict:
    return {k: yaml.safe_load((DUCLOS / "config" / f"{k}.yaml").read_text(encoding="utf-8"))
            for k in ["empresa", "rubros", "kpis", "impuestos", "personal"]}


@pytest.fixture(scope="module")
def duclos(app_cliente, admin):
    if not (DUCLOS / "entrada").is_dir():
        pytest.skip("Los archivos reales de Duclos no están en el repositorio (privacidad)")
    r = app_cliente.post("/api/clientes", headers=admin, json={"nombre": "DUCLOS SAS", "rubro": "fabrica",
                                                                "cuit": "30-71754735-3"})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert app_cliente.put(f"/api/clientes/{cid}/config", headers=admin,
                           json={"config": config_duclos()}).status_code == 200
    for carpeta in sorted((DUCLOS / "entrada").iterdir()):
        if not carpeta.is_dir():
            continue
        archivos = [("archivos", (f.name, f.read_bytes())) for f in sorted(carpeta.iterdir()) if f.is_file()]
        r = app_cliente.post(f"/api/clientes/{cid}/archivos", headers=admin, data={"mes": carpeta.name},
                             files=archivos)
        assert r.status_code == 201, r.text
        assert all(x["estado"] == "subido" for x in r.json())
    return cid


def test_primer_ingreso_crea_estudio_y_admin(app_cliente, admin):
    r = app_cliente.get("/api/yo", headers=admin)
    assert r.status_code == 200 and r.json()["rol"] == "admin"


def test_usuario_sin_invitacion(app_cliente):
    r = app_cliente.get("/api/yo", headers={"X-Usuario-Dev": f"{uuid.uuid4()}|extrano@x.com"})
    assert r.status_code == 403


def test_validaciones_alta(app_cliente, admin):
    r = app_cliente.post("/api/clientes", headers=admin, json={"nombre": "X", "rubro": "fabrica", "cuit": "30-71754735-0"})
    assert r.status_code == 422
    r = app_cliente.post("/api/clientes", headers=admin, json={"nombre": "Otra", "rubro": "inventado",
                                                                "cuit": "30-71234567-1"})
    assert r.status_code == 422


def test_config_invalida_se_rechaza(app_cliente, admin, duclos):
    cfg = config_duclos()
    cfg["rubros"]["reglas"].append({"contiene": "X", "rubro": "Rubro que no existe"})
    r = app_cliente.put(f"/api/clientes/{duclos}/config", headers=admin, json={"config": cfg})
    assert r.status_code == 422 and "Rubro que no existe" in r.text


def test_archivo_repetido_no_se_duplica(app_cliente, admin, duclos):
    f = next((DUCLOS / "entrada" / "2026-09").glob("*931*"))
    r = app_cliente.post(f"/api/clientes/{duclos}/archivos", headers=admin, data={"mes": "2026-11"},
                         files=[("archivos", ("copia.pdf", f.read_bytes()))])
    assert r.json()[0]["estado"] == "duplicado"


def test_cierre_septiembre_igual_que_la_terminal(app_cliente, admin, duclos):
    r = app_cliente.post(f"/api/clientes/{duclos}/cierres", headers=admin, json={"mes": "2026-09"})
    assert r.status_code == 202
    c = app_cliente.get(f"/api/cierres/{r.json()['id']}", headers=admin).json()   # TestClient corre la tarea
    assert c["estado"] == "listo", c.get("error")
    res = c["resumen"]
    assert res["ventas"] == pytest.approx(3_523_058.68, abs=0.01)
    assert res["resultado"] == pytest.approx(-1_061_153, abs=1)
    assert len(res["estrellas"]) == 8
    assert {e["nombre"]: e["semaforo"] for e in res["estrellas"]}["Energía / ventas"] == "rojo"
    x = app_cliente.get(f"/api/cierres/{c['id']}/descargas/excel", headers=admin)
    assert x.status_code == 200
    wb = load_workbook(BytesIO(x.content))
    assert "Tablero" in wb.sheetnames and "Decisiones" in wb.sheetnames
    pdf = app_cliente.get(f"/api/cierres/{c['id']}/descargas/pdf", headers=admin)
    assert pdf.content[:4] == b"%PDF"
    arch = app_cliente.get(f"/api/clientes/{duclos}/archivos", headers=admin).json()
    assert {a["tipo_detectado"] for a in arch} >= {"emitidos", "recibidos", "f931", "banco"}
    assert all(a["estado"] == "procesado" for a in arch)


def test_segundo_cierre_usa_cache_y_lista(app_cliente, admin, duclos):
    r = app_cliente.post(f"/api/clientes/{duclos}/cierres", headers=admin, json={"mes": "2026-10"})
    c = app_cliente.get(f"/api/cierres/{r.json()['id']}", headers=admin).json()
    assert c["estado"] == "listo" and c["resumen"]["mes_incompleto"] is True
    lista = app_cliente.get("/api/clientes", headers=admin).json()
    d = next(x for x in lista if x["id"] == duclos)
    assert d["ultimo_mes"] == "2026-10" and d["ultimo_resumen"]["estrellas"]


def test_socio_solo_ve_su_empresa(app_cliente, admin, duclos):
    from app import db
    otro = app_cliente.post("/api/clientes", headers=admin, json={"nombre": "Café Hefesto", "rubro": "gastronomia",
                                                                   "cuit": "30-71234567-1"}).json()["id"]
    est = db.uno("select estudio_id::text from clientes where id::text=%s", (duclos,))["estudio_id"]
    socio = str(uuid.uuid4())
    db.ejecutar("insert into usuarios (id, estudio_id, email, rol) values (%s,%s,'socio@duclos.com','socio_cliente')",
                (socio, est))
    db.ejecutar("insert into usuarios_clientes values (%s,%s)", (socio, duclos))
    h = {"X-Usuario-Dev": f"{socio}|socio@duclos.com"}
    ids = {c["id"] for c in app_cliente.get("/api/clientes", headers=h).json()}
    assert ids == {duclos}
    assert app_cliente.get(f"/api/clientes/{otro}", headers=h).status_code == 404
    assert app_cliente.post(f"/api/clientes/{duclos}/cierres", headers=h, json={"mes": "2026-09"}).status_code == 403
